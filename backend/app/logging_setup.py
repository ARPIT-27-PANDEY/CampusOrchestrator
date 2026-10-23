"""Structured logging with secret redaction."""

from __future__ import annotations

import logging
import re
from collections.abc import MutableMapping
from typing import Any

import structlog

_SECRET_KEYS = re.compile(r"(api[_-]?key|token|secret|password|authorization|cookie)", re.I)
_SECRET_VALUES = re.compile(r"(gsk_[A-Za-z0-9]{8,}|sk-[A-Za-z0-9]{8,}|Bearer\s+[A-Za-z0-9._-]{8,})")


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return _SECRET_VALUES.sub("[REDACTED]", value)
    if isinstance(value, dict):
        return {k: "[REDACTED]" if _SECRET_KEYS.search(str(k)) else _redact_value(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_redact_value(v) for v in value]
    return value


def redact(_: Any, __: str, event_dict: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    for key in list(event_dict):
        event_dict[key] = "[REDACTED]" if _SECRET_KEYS.search(key) else _redact_value(event_dict[key])
    return event_dict


class _RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _SECRET_VALUES.sub("[REDACTED]", record.msg)
        if record.args:
            record.args = (
                tuple(_redact_value(a) for a in record.args) if isinstance(record.args, tuple) else record.args
            )
        return True


def configure_logging(level: str = "INFO", json_logs: bool = False) -> None:
    logging.basicConfig(level=level.upper(), format="%(message)s")
    for handler in logging.getLogger().handlers:
        handler.addFilter(_RedactingFilter())
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redact,
            structlog.processors.JSONRenderer() if json_logs else structlog.dev.ConsoleRenderer(colors=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        cache_logger_on_first_use=True,
    )
