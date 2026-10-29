"""Backend campus-timezone configuration and clock wiring."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.agent.orchestrator import Orchestrator
from app.agent.trace_store import TraceStore
from app.campus_time import CampusClock
from app.config import Settings
from app.llm.base import ChatMessage, LLMResponse, ToolSpec
from app.mcp.manager import MCPClientManager

AT_MIDNIGHT_IST = datetime(2026, 10, 28, 18, 30, tzinfo=UTC)


def test_settings_default_and_validation() -> None:
    assert Settings(_env_file=None).campus_timezone == "Asia/Kolkata"  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        Settings(_env_file=None, campus_timezone="Not/AZone")  # type: ignore[call-arg]


class _CapturePrompt:
    name = "capture"
    model = "capture"

    def __init__(self) -> None:
        self.system = ""

    async def complete(self, messages: list[ChatMessage], tools: list[ToolSpec], **_: object) -> LLMResponse:
        self.system = messages[0].content or ""
        return LLMResponse(content="ok", tool_calls=[], finish_reason="stop", model=self.model)


async def test_orchestrator_gives_the_model_the_campus_date() -> None:
    llm = _CapturePrompt()
    orch = Orchestrator(llm, MCPClientManager([]), TraceStore(), clock=CampusClock.fixed(AT_MIDNIGHT_IST))
    await orch.run("hello")
    assert "Today on campus is Thursday, 2026-10-29" in llm.system
    assert "Asia/Kolkata" in llm.system


def test_orchestrator_accepts_plain_callable_clock() -> None:
    orch = Orchestrator(_CapturePrompt(), MCPClientManager([]), TraceStore(), clock=lambda: AT_MIDNIGHT_IST)
    assert orch.clock.today().isoformat() == "2026-10-29"
