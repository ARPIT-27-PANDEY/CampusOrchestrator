"""A brand-new MCP server is integrated by configuration alone, over the real Streamable HTTP transport.

The Transport server (tests/fixtures/transport_mcp.py) is unknown to the orchestrator, the MCP manager
and the MockProvider's routing rules. This test:
  1. starts it as a separate OS process,
  2. registers it through the existing server-config mechanism (a mcp_servers.json + host allowlist),
  3. discovers its tool name, description and input schema dynamically,
  4. calls the tool through the existing MCP client manager,
  5. runs the existing agent (a scripted model that only uses the *discovered* tool list) and checks the
     answer is grounded in the returned result,
  6. removes the server again and checks the other servers are unaffected,
  7. restarts it with a changed schema and checks the registry picks the change up, and that the
     manager recovers after the restart,
  8. checks that no backend source file mentions the new server or its tool.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from .conftest import ROOT, InProcessConnector, inprocess_servers

sys.path.insert(0, str(ROOT / "backend"))

from app.agent.orchestrator import Orchestrator
from app.agent.trace_store import TraceStore
from app.llm.base import ChatMessage, LLMResponse, ToolCall, ToolSpec
from app.mcp.config import ServerConfig, load_server_configs
from app.mcp.manager import MCPClientManager, http_connector

FIXTURE = ROOT / "tests" / "fixtures" / "transport_mcp.py"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _start(port: int, schema_version: int) -> subprocess.Popen[bytes]:
    env = {**os.environ, "TRANSPORT_SCHEMA_VERSION": str(schema_version)}
    proc = subprocess.Popen([sys.executable, str(FIXTURE), "--port", str(port)], env=env, stderr=subprocess.PIPE)
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            if httpx.get(f"http://127.0.0.1:{port}/health", timeout=1).status_code == 200:
                return proc
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    proc.kill()
    raise RuntimeError("transport test server did not start")


@pytest.fixture
def transport() -> Iterator[tuple[int, list[subprocess.Popen[bytes]]]]:
    port = _free_port()
    procs = [_start(port, 1)]
    try:
        yield port, procs
    finally:
        for p in procs:
            p.terminate()
            p.wait(timeout=10)


def _register(tmp_path: Path, port: int) -> list[ServerConfig]:
    """The existing configuration mechanism: an allowlisted mcp_servers.json, nothing else."""
    cfg = tmp_path / "mcp_servers.json"
    cfg.write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "id": "transport",
                        "name": "Transport",
                        "url": f"http://127.0.0.1:{port}/mcp",
                        "description": "Campus shuttle (test only)",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return load_server_configs(cfg, {"127.0.0.1", "localhost"}, env={})


class DiscoveredToolModel:
    """A scripted 'model' that knows nothing in advance: it picks the shuttle tool from the discovered
    tool list (by description), then answers using only the tool result it was given."""

    name = "scripted-discovery"
    model = "scripted"

    def __init__(self) -> None:
        self.seen_tools: list[str] = []

    async def complete(self, messages: list[ChatMessage], tools: list[ToolSpec], **_: object) -> LLMResponse:
        self.seen_tools = [t.name for t in tools]
        results = [m for m in messages if m.role == "tool"]
        if not results:
            tool = next(t for t in tools if "shuttle" in t.description.lower())
            args = {"stop": "Main Gate", "after": "10:00"}
            return LLMResponse(None, [ToolCall("c1", tool.name, json.dumps(args), args)], "tool_calls", self.model)
        body = results[-1].content or ""
        data = json.loads(body[body.index("{") : body.rindex("}") + 1])
        first = data["departures"][0]
        return LLMResponse(
            f"The next shuttle from {data['stop']} leaves at {first['time']} ({first['route']} to {first['destination']}).",
            [],
            "stop",
            self.model,
        )


async def test_new_server_is_discovered_called_and_grounded(
    transport: tuple[int, list[subprocess.Popen[bytes]]], tmp_path: Path
) -> None:
    port, _ = transport
    configs = _register(tmp_path, port)
    mgr = MCPClientManager(configs, connector=http_connector, default_timeout_s=5)
    await mgr.refresh()
    tool = mgr.get_tool("transport__get_shuttle_departures")
    assert tool is not None and "shuttle" in tool.description.lower()
    assert set(tool.input_schema["properties"]) == {"stop", "after"}
    assert tool.input_schema["required"] == ["stop"]

    direct = await mgr.call_tool(tool.qualified_name, {"stop": "Library"})
    assert direct.status.value == "success" and direct.data and direct.data["count"] == 2

    model = DiscoveredToolModel()
    result = await Orchestrator(model, mgr, TraceStore()).run("When is the next shuttle from the main gate?")
    assert "transport__get_shuttle_departures" in model.seen_tools
    assert [c.tool for c in result.tool_calls] == ["transport__get_shuttle_departures"]
    assert result.tool_calls[0].status == "success"
    assert "10:30" in result.answer and "Loop B" in result.answer  # grounded in the tool result
    assert {s.server_id for s in result.sources} == {"transport"}


async def test_adding_and_removing_the_server_does_not_affect_existing_ones(
    transport: tuple[int, list[subprocess.Popen[bytes]]], tmp_path: Path
) -> None:
    port, _ = transport
    servers = inprocess_servers()
    base = [ServerConfig(id=i, name=i.title(), url=f"inprocess://{i}") for i in servers]
    inproc = InProcessConnector(servers)

    def connector(cfg: ServerConfig, timeout: float):  # type: ignore[no-untyped-def]
        return http_connector(cfg, timeout) if cfg.id == "transport" else inproc(cfg, timeout)

    with_new = MCPClientManager([*base, *_register(tmp_path, port)], connector=connector, default_timeout_s=5)
    await with_new.refresh()
    without = MCPClientManager(base, connector=connector, default_timeout_s=5)
    await without.refresh()
    names_with = {t.qualified_name for t in with_new.tools}
    names_without = {t.qualified_name for t in without.tools}
    assert names_with - names_without == {"transport__get_shuttle_departures"}
    lib = await without.call_tool("library__get_library_hours", {"date": "2026-10-26"})
    assert lib.status.value == "success"


async def test_schema_change_and_restart_are_picked_up(
    transport: tuple[int, list[subprocess.Popen[bytes]]], tmp_path: Path
) -> None:
    port, procs = transport
    mgr = MCPClientManager(_register(tmp_path, port), connector=http_connector, default_timeout_s=3,
                           registry_ttl_s=0, unavailable_recheck_s=0, max_retries=0)  # fmt: skip
    await mgr.refresh()
    assert "route" not in mgr.get_tool("transport__get_shuttle_departures").input_schema["properties"]  # type: ignore[union-attr]

    procs[0].terminate()
    procs[0].wait(timeout=10)
    down = await mgr.call_tool("transport__get_shuttle_departures", {"stop": "Main Gate"})
    assert down.status.value == "unavailable"  # a dead server is a failure, never an empty result

    procs.append(_start(port, 2))  # restarted with a new optional argument
    await mgr.ensure_fresh()
    tool = mgr.get_tool("transport__get_shuttle_departures")
    assert tool is not None and "route" in tool.input_schema["properties"]
    ok = await mgr.call_tool(tool.qualified_name, {"stop": "Main Gate", "route": "Loop B"})
    assert ok.status.value == "success" and {d["route"] for d in ok.data["departures"]} == {"Loop B"}  # type: ignore[index]


def test_core_code_has_no_knowledge_of_the_new_server() -> None:
    offenders = [
        str(p.relative_to(ROOT))
        for p in (ROOT / "backend" / "app").rglob("*.py")
        # The server's identifiers (not the generic word "transport", used for HTTP transports).
        if any(w in p.read_text(encoding="utf-8").lower() for w in ("shuttle", "transport__", "campus-transport"))
    ]
    assert offenders == [], f"core code mentions the test-only server: {offenders}"
