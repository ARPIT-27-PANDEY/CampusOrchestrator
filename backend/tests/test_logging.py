"""Secrets must never reach log output."""

from __future__ import annotations

import logging

import pytest

from app.logging_setup import configure_logging, redact


def test_structlog_processor_redacts_keys_and_values() -> None:
    event = {
        "event": "calling groq with Bearer abcdefghijklmnop",
        "api_key": "gsk_abcdefghijklmnop",
        "nested": {"token": "x"},
    }
    out = redact(None, "info", event)
    assert out["api_key"] == "[REDACTED]"
    assert out["nested"] == {"token": "[REDACTED]"}
    assert "abcdefghijklmnop" not in out["event"]


def test_stdlib_logging_is_redacted(caplog: pytest.LogCaptureFixture) -> None:
    configure_logging("INFO")
    with caplog.at_level(logging.INFO):
        logging.getLogger("campusos.test").info("key=%s", "gsk_supersecretvalue123")
    assert "gsk_supersecretvalue123" not in caplog.text
    assert "[REDACTED]" in caplog.text
