"""ConcurrencyController protocol: the seam between the engine and its concurrency backend.

ResourceGovernor (alphaswarm.governor) implements it for the local Ollama path,
RateLimitController (alphaswarm.inference.rate_limit) for the cloud path.
inference.factory.build_controller returns one of them behind this protocol, so
callers stay backend-agnostic (docs/DECISIONS.md#adr-governor).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from types import TracebackType


@runtime_checkable
class ConcurrencyController(Protocol):
    """Protocol for objects that manage inference concurrency slots.

    Both local (ResourceGovernor) and cloud (RateLimitController) backends must
    satisfy this interface. The protocol is runtime_checkable so factory code can
    assert conformance at construction time.

    Methods
    -------
    acquire
        Block until a concurrency slot is available, then claim it.
    release
        Return the slot. ``success`` lets the governor update its state machine;
        ``result_tokens`` is used for cloud token-rate accounting.
    report_wave_failures
        Inform the controller of aggregate batch success/failure counts so it can
        shrink concurrency if needed.
    start_monitoring
        Begin any background monitoring tasks (e.g. memory polling).
    stop_monitoring
        Cleanly shut down background monitoring.
    """

    async def acquire(self) -> None: ...

    def release(self, *, success: bool = True, result_tokens: int | None = None) -> None: ...

    def report_wave_failures(self, success_count: int, failure_count: int) -> None: ...

    async def start_monitoring(self) -> None: ...

    async def stop_monitoring(self) -> None: ...

    async def __aenter__(self) -> ConcurrencyController: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...
