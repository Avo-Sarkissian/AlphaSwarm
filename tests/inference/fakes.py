"""Test fakes for the inference abstraction layer.

These helpers are intentionally NOT placed under src/ — they are test-only
and must never be imported by production code.
"""

from __future__ import annotations

from typing import Any, Callable

from alphaswarm.inference.types import InferenceMessage, InferenceResult, ProviderRole


class FakeInferenceProvider:
    """Scriptable stand-in for InferenceProvider used in unit tests.

    Satisfies the InferenceProvider Protocol (runtime isinstance check passes).

    Args:
        role: Provider role (ORCHESTRATOR or WORKER).
        model: Model identifier string.
        scripted: Either a list of InferenceResult values (consumed front-to-back)
            or a callable that receives the same kwargs as ``chat`` and returns
            an InferenceResult.  If a list is provided and exhausted, the next
            ``chat`` call raises AssertionError.
        is_local: Value returned by ``is_local()``; defaults to True.

    Attributes:
        calls: List of dicts, one per ``chat`` invocation, recording all kwargs
            including ``messages``, ``response_schema``, ``json_mode``,
            ``temperature``, and ``max_tokens``.
    """

    def __init__(
        self,
        role: ProviderRole,
        model: str,
        *,
        scripted: list[InferenceResult] | Callable[..., InferenceResult],
        is_local: bool = True,
    ) -> None:
        self.role = role
        self.model = model
        self._scripted = list(scripted) if isinstance(scripted, list) else scripted
        self._is_local = is_local
        self.calls: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Protocol surface
    # ------------------------------------------------------------------

    def is_local(self) -> bool:
        return self._is_local

    async def prepare(self) -> None:
        """No-op — fakes need no warm-up."""

    async def teardown(self) -> None:
        """No-op — fakes hold no resources."""

    async def aclose(self) -> None:
        """No-op alias for teardown."""

    async def chat(
        self,
        messages: list[InferenceMessage],
        *,
        response_schema: dict[str, Any] | None = None,
        json_mode: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> InferenceResult:
        """Record the call and return the next scripted result.

        Raises:
            AssertionError: If scripted is a list and has been exhausted.
        """
        self.calls.append(
            {
                "messages": messages,
                "response_schema": response_schema,
                "json_mode": json_mode,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )

        if callable(self._scripted):
            return self._scripted(
                messages=messages,
                response_schema=response_schema,
                json_mode=json_mode,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        # List path — scripted is a list at this point
        scripted_list: list[InferenceResult] = self._scripted  # type: ignore[assignment]
        if not scripted_list:
            raise AssertionError(
                f"FakeInferenceProvider({self.model!r}) scripted results exhausted "
                f"on call #{len(self.calls)}"
            )
        return scripted_list.pop(0)
