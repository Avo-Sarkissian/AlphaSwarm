"""Test fakes for the inference abstraction layer.

These helpers are intentionally NOT placed under src/ — they are test-only
and must never be imported by production code.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

from alphaswarm.inference.types import InferenceMessage, InferenceResult, ProviderRole
from alphaswarm.types import AgentDecision, AgentPersona, SignalType


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
        if isinstance(scripted, list):
            self._scripted_list: list[InferenceResult] | None = list(scripted)
            self._scripted_fn: Callable[..., InferenceResult] | None = None
        else:
            self._scripted_list = None
            self._scripted_fn = scripted
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

        if self._scripted_fn is not None:
            return self._scripted_fn(
                messages=messages,
                response_schema=response_schema,
                json_mode=json_mode,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        # List path
        assert self._scripted_list is not None  # guaranteed by __init__
        if not self._scripted_list:
            raise AssertionError(
                f"FakeInferenceProvider({self.model!r}) scripted results exhausted "
                f"on call #{len(self.calls)}"
            )
        return self._scripted_list.pop(0)


# ---------------------------------------------------------------------------
# ScriptedProvider: deterministic worker/orchestrator for engine scenarios
# ---------------------------------------------------------------------------

# Persona header written by config.generate_personas: "[Sell-Side 3 | Sell-Side bracket]".
# Any change to persona or peer-context prompts MUST keep these regexes matching.
AGENT_HEADER_RE: Final = re.compile(r"\[(?P<name>[^\]|]+?) \| (?P<display>[^\]]+?) bracket\]")
# Peer line id: "[sell_side_03|sell_side]" or "[sell_side_03]".
PEER_LINE_RE: Final = re.compile(
    r"\[(?P<agent_id>[a-z]+(?:_[a-z]+)*_\d{2})(?:\|(?P<bracket>[a-z_]+))?\]"
)
# Narrative identity: the "Agent: Sell-Side 3 (sell_side)" line of the narrative user prompt.
# The narrator's system prompt must NOT match AGENT_HEADER_RE, or the call counts as a chat.
_NARRATIVE_AGENT_RE: Final = re.compile(r"^Agent: (?P<name>.+?) \([a-z_]+\)$", re.MULTILINE)
# LLM-facing decision fields only; never engine fields such as error_kind/parse_tier.
_LLM_DECISION_FIELDS: Final = frozenset(
    {"signal", "confidence", "sentiment", "rationale", "cited_agents"}
)
_SCRIPTED_SIGNALS: Final = (SignalType.BUY, SignalType.SELL, SignalType.HOLD)

CallKind = Literal["decision", "narrative", "orchestrator", "chat"]


@dataclass(frozen=True)
class ScriptedCall:
    """One classified chat() call seen by a ScriptedProvider."""

    kind: CallKind
    agent_id: str | None
    round_num: int | None
    shown_peer_ids: tuple[str, ...]  # parsed with PEER_LINE_RE from all messages, in order
    messages: list[InferenceMessage]
    kwargs: dict[str, Any]  # response_schema, json_mode, temperature, max_tokens


DecisionFn = Callable[[str, int, ScriptedCall], AgentDecision | BaseException]


def default_decision_script(agent_id: str, round_num: int, call: ScriptedCall) -> AgentDecision:
    """blake2b(agent_id, round_num)-derived signal/confidence; cites up to 2 shown peers."""
    digest = hashlib.blake2b(f"{agent_id}:{round_num}".encode(), digest_size=8).digest()
    signal = _SCRIPTED_SIGNALS[digest[0] % 3]
    return AgentDecision(
        signal=signal,
        confidence=round(0.30 + (digest[1] / 255) * 0.65, 2),
        sentiment=round((digest[2] / 255) * 2.0 - 1.0, 2),
        rationale=f"{agent_id} round {round_num}: scripted {signal.value} view",
        cited_agents=list(call.shown_peer_ids[:2]),
    )


class ScriptedProvider(FakeInferenceProvider):
    """Deterministic InferenceProvider for engine scenarios.

    Classification, first match wins: ``orchestrator`` iff role is ORCHESTRATOR;
    ``decision`` iff ``response_schema`` has a ``"signal"`` property; ``chat``
    (interview) iff there is no schema and the first system message carries the
    persona header; otherwise ``narrative``. Agent identity comes from the
    header's name (decision/chat) or the narrative prompt's ``Agent:`` line.
    Round = ``round_source()`` when given, else a per-agent decision counter.
    A DecisionFn that returns an exception makes ``chat`` raise it.
    """

    def __init__(
        self,
        *,
        role: ProviderRole = ProviderRole.WORKER,
        model: str = "scripted-worker",
        personas: Sequence[AgentPersona],
        decide: DecisionFn = default_decision_script,
        orchestrator_script: Sequence[str] | Callable[[ScriptedCall], str] = (),
        round_source: Callable[[], int] | None = None,
        is_local: bool = True,
    ) -> None:
        super().__init__(role, model, scripted=self._respond, is_local=is_local)
        self.decide = decide
        self._ids_by_name = {p.name: p.id for p in personas}
        if callable(orchestrator_script):
            self._orchestrator_fn: Callable[[ScriptedCall], str] | None = orchestrator_script
            self._orchestrator_queue: list[str] = []
        else:
            self._orchestrator_fn = None
            self._orchestrator_queue = list(orchestrator_script)
        self._round_source = round_source
        self._decision_counts: dict[str, int] = {}
        self.scripted_calls: list[ScriptedCall] = []
        self.prepare_calls = 0
        self.teardown_calls = 0

    async def prepare(self) -> None:
        self.prepare_calls += 1

    async def teardown(self) -> None:
        self.teardown_calls += 1

    def calls_for(self, kind: str) -> list[ScriptedCall]:
        """All recorded calls of one kind, in call order."""
        return [c for c in self.scripted_calls if c.kind == kind]

    def _agent_id(self, name: str) -> str:
        try:
            return self._ids_by_name[name]
        except KeyError:
            raise AssertionError(f"ScriptedProvider: unknown persona name {name!r}") from None

    def _classify(
        self, messages: list[InferenceMessage], schema: dict[str, Any] | None
    ) -> tuple[CallKind, str | None]:
        if self.role is ProviderRole.ORCHESTRATOR:
            return "orchestrator", None
        systems = [m["content"] for m in messages if m["role"] == "system"]
        if schema is not None and "signal" in schema.get("properties", {}):
            header = next((h for h in map(AGENT_HEADER_RE.search, systems) if h), None)
            if header is None:
                raise AssertionError("ScriptedProvider: decision call without a persona header")
            return "decision", self._agent_id(header.group("name"))
        first_header = AGENT_HEADER_RE.search(systems[0]) if systems else None
        if schema is None and first_header is not None:
            return "chat", self._agent_id(first_header.group("name"))
        user = next((m["content"] for m in messages if m["role"] == "user"), "")
        match = _NARRATIVE_AGENT_RE.search(user)
        return "narrative", (self._agent_id(match.group("name")) if match else None)

    def _respond(
        self,
        *,
        messages: list[InferenceMessage],
        response_schema: dict[str, Any] | None,
        json_mode: bool,
        temperature: float | None,
        max_tokens: int | None,
    ) -> InferenceResult:
        kind, agent_id = self._classify(messages, response_schema)
        round_num: int | None = None
        if kind == "decision" and agent_id is not None:
            self._decision_counts[agent_id] = self._decision_counts.get(agent_id, 0) + 1
            round_num = (
                self._round_source() if self._round_source else self._decision_counts[agent_id]
            )
        shown = tuple(
            dict.fromkeys(
                match.group("agent_id")
                for message in messages
                for match in PEER_LINE_RE.finditer(message["content"])
            )
        )
        call = ScriptedCall(
            kind=kind,
            agent_id=agent_id,
            round_num=round_num,
            shown_peer_ids=shown,
            messages=list(messages),
            kwargs={
                "response_schema": response_schema,
                "json_mode": json_mode,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
        )
        self.scripted_calls.append(call)
        if kind == "orchestrator":
            return InferenceResult(content=self._next_orchestrator_reply(call), model=self.model)
        if kind == "decision":
            assert agent_id is not None and round_num is not None
            outcome = self.decide(agent_id, round_num, call)
            if isinstance(outcome, BaseException):
                raise outcome
            payload = outcome.model_dump(mode="json", include=set(_LLM_DECISION_FIELDS))
            return InferenceResult(content=json.dumps(payload), model=self.model)
        if kind == "chat":
            return InferenceResult(
                content=f"Scripted interview reply from {agent_id}.", model=self.model
            )
        return InferenceResult(content=f"Scripted narrative for {agent_id}.", model=self.model)

    def _next_orchestrator_reply(self, call: ScriptedCall) -> str:
        if self._orchestrator_fn is not None:
            return self._orchestrator_fn(call)
        if not self._orchestrator_queue:
            raise AssertionError(
                f"ScriptedProvider({self.model!r}): orchestrator script exhausted "
                f"on call #{len(self.calls)}"
            )
        return self._orchestrator_queue.pop(0)
