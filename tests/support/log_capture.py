"""Render module log calls the way the production JSON logs do.

A test swaps a module's ``log`` for a RenderedLog. Each call is rendered when it
is made, so ``exc_info=True`` resolves while the exception is being handled, by
the processors ``configure_logging(json_output=True)`` applies after the context
ones: the traceback without locals, the PII redactor, then JSON. Searching the
rendered text therefore finds anything the real log line would carry.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import structlog
from structlog.tracebacks import ExceptionDictTransformer

from alphaswarm.logging import pii_redaction_processor

_RENDER_CHAIN: tuple[Callable[..., Any], ...] = (
    structlog.processors.ExceptionRenderer(ExceptionDictTransformer(show_locals=False)),
    pii_redaction_processor,
    structlog.processors.JSONRenderer(),
)


class RenderedLog:
    """Stand-in for a module-level structlog logger that keeps every rendered line."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.lines: list[str] = []

    def __getattr__(self, level: str) -> Callable[..., None]:
        def _log(event: str, **kw: Any) -> None:
            if level == "exception":
                kw.setdefault("exc_info", True)
            rendered: Any = {"event": event, "level": level, **kw}
            for processor in _RENDER_CHAIN:
                rendered = processor(None, level, rendered)
            self.events.append(event)
            self.lines.append(str(rendered))

        return _log

    @property
    def text(self) -> str:
        """Every rendered line, newline-separated."""
        return "\n".join(self.lines)
