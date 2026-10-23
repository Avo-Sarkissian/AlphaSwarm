"""Ollama AsyncClient wrapper enforcing project contracts.

Contracts:
- No per-request num_ctx (causes silent model reloads)
- Exponential backoff on transient errors (ResponseError, ConnectionError, httpx.ConnectError)
- OllamaInferenceError raised after max_tries exhausted
- RequestError wrapped in OllamaInferenceError at public boundary (not retried)
- All inference goes through this wrapper, never raw AsyncClient
- Per-role read timeouts: worker calls are cut at OllamaTimeouts.worker_read_s,
  everything else at orchestrator_read_s (docs/DECISIONS.md#adr-inference-timeouts)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Literal

import backoff
import httpx
import structlog
from ollama import AsyncClient, ChatResponse, RequestError, ResponseError

from alphaswarm.errors import OllamaInferenceError

logger = structlog.get_logger(component="ollama_client")

TimeoutRole = Literal["worker", "orchestrator"]

# Fixed parts of every Ollama HTTP timeout (docs/DECISIONS.md#adr-inference-timeouts).
WRITE_TIMEOUT_S: Final = 30.0
POOL_TIMEOUT_S: Final = 30.0


@dataclass(frozen=True)
class OllamaTimeouts:
    """Per-role HTTP timeouts for the Ollama server (docs/DECISIONS.md#adr-inference-timeouts).

    ``connect_s`` makes an unreachable host fail fast. The read timeout bounds
    the wait for a whole non-streamed reply: worker decisions take seconds, so a
    stalled one is cut at ``worker_read_s``; orchestrator calls, model loads and
    warm-ups (which pay MLX kernel compilation) get ``orchestrator_read_s``.
    """

    connect_s: float = 5.0
    worker_read_s: float = 120.0
    orchestrator_read_s: float = 600.0

    def httpx_timeout(self, role: TimeoutRole) -> httpx.Timeout:
        """The ``httpx.Timeout`` for one role's connection pool."""
        read = self.worker_read_s if role == "worker" else self.orchestrator_read_s
        return httpx.Timeout(connect=self.connect_s, read=read, write=WRITE_TIMEOUT_S, pool=POOL_TIMEOUT_S)


def _strip_num_ctx(options: dict[str, Any] | None) -> dict[str, Any] | None:
    """Remove num_ctx from options dict to prevent silent model reloads."""
    if options is None:
        return None
    filtered = {k: v for k, v in options.items() if k != "num_ctx"}
    return filtered if filtered else None


class OllamaClient:
    """Wrapper around ollama.AsyncClient enforcing project contracts.

    Usage:
        client = OllamaClient(base_url="http://localhost:11434")
        response = await client.chat(model="alphaswarm-worker", messages=[...])
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        timeouts: OllamaTimeouts | None = None,
    ) -> None:
        # Every call has a bounded wait, so a wedged server (e.g. after macOS
        # sleep/wake) becomes OllamaInferenceError -> PARSE_ERROR instead of a hung
        # dispatch_wave. ollama.AsyncClient fixes its timeout per client, so each
        # role gets its own pool (docs/DECISIONS.md#adr-inference-timeouts).
        #
        # trust_env=False: httpx would otherwise send requests through any
        # HTTP_PROXY/ALL_PROXY or macOS system proxy, with no automatic
        # localhost bypass, so a "local" Ollama call (and the advisory's
        # portfolio prompt) could reach a proxy on another machine.
        # follow_redirects=False: a process on the Ollama port cannot redirect
        # a request body to another host. Ollama itself never redirects
        # (docs/DECISIONS.md#adr-advisory-pipeline).
        self._timeouts = timeouts or OllamaTimeouts()
        self._client = AsyncClient(
            host=base_url,
            timeout=self._timeouts.httpx_timeout("orchestrator"),
            trust_env=False,
            follow_redirects=False,
        )
        self._worker_client = AsyncClient(
            host=base_url,
            timeout=self._timeouts.httpx_timeout("worker"),
            trust_env=False,
            follow_redirects=False,
        )
        self._base_url = base_url

    @property
    def raw_client(self) -> AsyncClient:
        """The orchestrator-timeout AsyncClient, for model management (ps, list, create)."""
        return self._client

    @property
    def base_url(self) -> str:
        """The host this client really connects to.

        Read from the underlying httpx client, after ollama resolved the
        configured host (or ``OLLAMA_HOST`` when it is empty), so a locality
        check sees the same value as the connection.
        """
        return str(self._http.base_url)

    @property
    def _http(self) -> httpx.AsyncClient:
        # ollama.AsyncClient keeps its httpx client in ``_client`` (0.4 to 0.6).
        http: httpx.AsyncClient = self._client._client
        return http

    async def is_remote_model(self, model: str) -> bool:
        """True when the Ollama server runs *model* remotely (an Ollama cloud model).

        Newer servers answer ``/api/show`` for a cloud model, or an alias whose
        Modelfile is ``FROM`` one, with ``remote_host``/``remote_model``.
        ollama-python 0.6 drops those fields from ``ShowResponse``, so this reads
        the raw JSON. Any transport, HTTP or decoding error is raised, never read
        as "local", so callers can fail closed.
        """
        response = await self._http.post("/api/show", json={"model": model})
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("unexpected /api/show response shape")
        return bool(body.get("remote_host") or body.get("remote_model"))

    async def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        format: str | dict[str, Any] | None = None,
        think: bool | None = None,
        keep_alive: float | str | None = None,
        options: dict[str, Any] | None = None,
        timeout_role: TimeoutRole = "orchestrator",
    ) -> ChatResponse:
        """Send a chat request with contract enforcement.

        Args:
            model: Ollama model tag (e.g., "alphaswarm-worker" or base tag).
            messages: List of message dicts with "role" and "content" keys.
            format: Output format. Use "json" for JSON mode.
            think: Enable/disable thinking mode for Qwen3 models.
            keep_alive: Model keep-alive duration. Use 0 to unload.
            options: Additional model options. num_ctx is STRIPPED if present.
            timeout_role: "worker" for worker inference (short read timeout); the
                default "orchestrator" for everything long (orchestrator calls,
                loads, warm-ups).

        Raises:
            OllamaInferenceError: On transient errors after retries exhausted,
                or immediately on non-retryable RequestError.
        """
        safe_options = _strip_num_ctx(options)
        if options and "num_ctx" in options:
            logger.warning(
                "num_ctx stripped from options -- use Modelfiles instead",
                model=model,
            )
        try:
            return await self._chat_with_backoff(
                self._pool(timeout_role),
                model=model,
                messages=messages,
                format=format,
                think=think,
                keep_alive=keep_alive,
                options=safe_options,
            )
        except RequestError as exc:
            # Non-retryable: wrap at public boundary per review feedback
            raise OllamaInferenceError(
                message=f"Ollama request validation failed: {exc}",
                model=model,
                original_error=exc,
            ) from exc
        except httpx.TimeoutException as exc:
            # Deliberately NOT retried: a request that exhausted the full
            # timeout budget indicates a wedged/overloaded server — retrying
            # would multiply the stall, not fix it.
            raise OllamaInferenceError(
                message=f"Ollama chat timed out: {exc}",
                model=model,
                original_error=exc,
            ) from exc
        except (ResponseError, ConnectionError, httpx.ConnectError) as exc:
            raise OllamaInferenceError(
                message=f"Ollama chat failed after retries: {exc}",
                model=model,
                original_error=exc,
            ) from exc

    async def aclose(self) -> None:
        """Close both HTTP connection pools.

        Meant for process shutdown: every provider shares this client, so no
        single operation may close it. ``ollama.AsyncClient`` has no close
        method, so the ``httpx.AsyncClient`` each one wraps is closed directly.
        Closing twice is a no-op.
        """
        for pool in (self._client, self._worker_client):
            http_client = getattr(pool, "_client", None)
            if isinstance(http_client, httpx.AsyncClient) and not http_client.is_closed:
                await http_client.aclose()

    def _pool(self, role: TimeoutRole) -> AsyncClient:
        return self._worker_client if role == "worker" else self._client

    @backoff.on_exception(
        backoff.expo,
        (ResponseError, ConnectionError, httpx.ConnectError),
        max_tries=3,
    )
    async def _chat_with_backoff(self, pool: AsyncClient, **kwargs: Any) -> ChatResponse:
        """Internal chat call with exponential backoff on transient errors."""
        result: ChatResponse = await pool.chat(**kwargs)
        return result
