"""Each MCP server runs as an independent process; the backend discovers and uses them over Streamable HTTP."""

from __future__ import annotations

import httpx
import pytest

from app.agent.orchestrator import Orchestrator
from app.agent.trace_store import TraceStore
from app.llm.mock import MockProvider
from app.mcp.config import ServerConfig
from app.mcp.manager import MCPClientManager
from app.mcp.models import ServerStatus

pytestmark = pytest.mark.integration


def _manager(urls: dict[str, str]) -> MCPClientManager:
    cfgs = [ServerConfig(id=sid, name=sid.title(), url=f"{base}/mcp") for sid, base in urls.items()]
    return MCPClientManager(cfgs, default_timeout_s=10, max_retries=1)


def test_health_endpoints_report_demo_mode(http_servers: dict[str, str]) -> None:
    for sid, base in http_servers.items():
        body = httpx.get(f"{base}/health", timeout=5).json()
        assert body["status"] == "ok", sid
        assert body["source"]["mode"] == "demo", sid


def test_dns_rebinding_protection_rejects_foreign_host(http_servers: dict[str, str]) -> None:
    resp = httpx.post(f"{http_servers['library']}/mcp", headers={"Host": "attacker.example"}, json={})
    assert resp.status_code in (400, 421)


async def test_discovery_and_multi_server_query_over_http(http_servers: dict[str, str]) -> None:
    mgr = _manager(http_servers)
    await mgr.refresh()
    assert all(s.status is ServerStatus.AVAILABLE for s in mgr.server_states)
    assert all(s.protocol_version for s in mgr.server_states)
    names = {t.qualified_name for t in mgr.tools}
    assert len(names) == 14  # original 11 + get_events_for_date, get_menu_for_date, list_dining_locations
    assert {"events__get_events_for_date", "cafeteria__get_menu_for_date", "cafeteria__list_dining_locations"} <= names
    orch = Orchestrator(MockProvider(), mgr, TraceStore())
    result = await orch.run(
        "Find the next AI workshop, check whether Introduction to Algorithms is available in the library, "
        "and tell me which prerequisite the handbook specifies."
    )
    assert {t.server_id for t in result.tool_calls} == {"events", "library", "academics"}
    assert result.status == "ok"
    assert result.citations[0].page == 4


async def test_unreachable_server_is_isolated(http_servers: dict[str, str]) -> None:
    urls = dict(http_servers)
    urls["cafeteria"] = "http://127.0.0.1:9"  # nothing listens on the discard port
    mgr = _manager(urls)
    await mgr.refresh()
    states = {s.id: s.status for s in mgr.server_states}
    assert states["cafeteria"] is ServerStatus.UNAVAILABLE
    assert sum(st is ServerStatus.AVAILABLE for st in states.values()) == 3
