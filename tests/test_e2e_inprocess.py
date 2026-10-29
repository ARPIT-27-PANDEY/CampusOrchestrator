"""End-to-end orchestration over the four real MCP servers (in-process transport, mock LLM)."""

from __future__ import annotations

import pytest

from app.agent.orchestrator import AgentLimits, Orchestrator
from app.agent.trace_store import TraceStore
from app.llm.mock import MockProvider
from app.mcp.config import ServerConfig
from app.mcp.faults import FaultInjectingConnector
from app.mcp.manager import MCPClientManager

from .conftest import InProcessConnector, inprocess_servers

IDS = ["library", "events", "cafeteria", "academics"]
CONFIGS = [ServerConfig(id=i, name=i.title(), url=f"http://localhost/{i}") for i in IDS]
FLAGSHIP = (
    "Find the next AI workshop, check whether Introduction to Algorithms is available in the library, "
    "and tell me which prerequisite the handbook specifies."
)


@pytest.fixture(scope="module")
def servers() -> dict[str, object]:
    return inprocess_servers()


def orchestrator(
    servers: dict[str, object], faults: dict[str, str] | None = None, scope: str = "calls"
) -> Orchestrator:
    connector = InProcessConnector(servers)
    conn = FaultInjectingConnector(connector, faults, scope=scope) if faults else connector  # type: ignore[arg-type]
    mgr = MCPClientManager(CONFIGS, connector=conn, default_timeout_s=2.0, max_retries=0)
    return Orchestrator(MockProvider(), mgr, TraceStore(), AgentLimits())


async def test_discovers_all_tools_over_mcp(servers: dict[str, object]) -> None:
    orch = orchestrator(servers)
    await orch.mcp.refresh()
    # 14 = the original 11 + events__get_events_for_date + cafeteria__get_menu_for_date
    # + cafeteria__list_dining_locations (discovery is disabled in tests: no public-book tool).
    names = {t.qualified_name for t in orch.mcp.tools}
    assert len(names) == 14
    assert {"events__get_events_for_date", "cafeteria__get_menu_for_date", "cafeteria__list_dining_locations"} <= names
    assert {t.server_id for t in orch.mcp.tools} == set(IDS)


async def test_flagship_multi_server_query(servers: dict[str, object]) -> None:
    result = await orchestrator(servers).run(FLAGSHIP)
    servers_used = {t.server_id for t in result.tool_calls}
    assert servers_used == {"events", "library", "academics"}  # cafeteria not called
    assert all(t.status == "success" for t in result.tool_calls)
    assert "Hands-on AI Workshop" in result.answer
    assert "Introduction to Algorithms" in result.answer
    assert "CS 210" in result.answer
    assert result.citations and result.citations[0].page == 4
    assert result.citations[0].source_filename == "academic_handbook_2026.pdf"
    assert result.citation_check.ok
    assert all(s.mode == "demo" for s in result.sources)


async def test_events_failure_mid_request_keeps_other_results(servers: dict[str, object]) -> None:
    result = await orchestrator(servers, {"events": "down"}).run(FLAGSHIP)
    statuses = {t.server_id: t.status for t in result.tool_calls}
    assert statuses["events"] == "unavailable"
    assert statuses["library"] == "success" and statuses["academics"] == "success"
    assert result.status == "partial"
    assert "events service is unreachable" in result.answer
    assert "CS 210" in result.answer


async def test_server_down_at_discovery(servers: dict[str, object]) -> None:
    result = await orchestrator(servers, {"cafeteria": "down"}, scope="all").run("How much is the masala dosa?")
    assert result.tool_calls == []
    assert "cafeteria service is currently unavailable" in result.answer
    assert any("Cafeteria" in w for w in result.warnings)


async def test_timeout_is_contained(servers: dict[str, object]) -> None:
    orch = orchestrator(servers, {"library": "timeout"})
    orch.mcp._default_timeout = 0.3
    result = await orch.run("Is Deep Learning available?")
    assert result.tool_calls[0].status == "timeout"
    assert result.status == "partial"


async def test_unsupported_academic_question_reports_insufficient_evidence(servers: dict[str, object]) -> None:
    result = await orchestrator(servers).run("What does the handbook say about parking permits for cars?")
    assert result.insufficient_evidence
    assert result.citations == []
    assert "couldn't find supporting evidence" in result.answer


async def test_prompt_injection_in_document_is_neutralised(servers: dict[str, object]) -> None:
    result = await orchestrator(servers).run(
        "What does the FAQ say about the campus notice board and scholarship queries?"
    )
    assert result.citations
    faq = [c for c in result.citations if c.source_filename == "student_services_faq_2026.pdf"]
    assert faq and "Ignore all previous instructions" not in faq[0].excerpt
    assert "cancelled" not in result.answer.lower()
    assert len(result.tool_calls) == 1  # the injected "call every tool" was not obeyed


async def test_no_tools_for_greeting(servers: dict[str, object]) -> None:
    result = await orchestrator(servers).run("hello")
    assert result.tool_calls == []
