"""Structured logging configuration for AlphaSwarm."""

import logging

import structlog


def configure_logging(log_level: str = "INFO", json_output: bool = True) -> None:
    """Configure structlog for the application. Call once at startup.

    Args:
        log_level: Python log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        json_output: If True, output JSON lines. If False, use colored console output.
    """
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,  # MUST be first processor
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
    ]

    if json_output:
        shared_processors.append(structlog.processors.JSONRenderer())
    else:
        shared_processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=shared_processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(**initial_bindings: object) -> structlog.stdlib.BoundLogger:
    """Get a structlog logger with optional initial context bindings.

    Args:
        **initial_bindings: Key-value pairs bound to every log line from this logger.
                           Common: component="main", agent_id="quant_03"
    """
    return structlog.get_logger(**initial_bindings)
