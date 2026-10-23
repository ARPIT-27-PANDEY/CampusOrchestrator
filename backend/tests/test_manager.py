"""MCP client manager: discovery, registry, validation, routing, failure classification."""

from __future__ import annotations

import pytest

from app.mcp.manager import MCPClientManager, classify_exception
from app.mcp.models import ServerStatus, ToolStatus

from .fakes import FakeConnector, academics_server, configs, library_server


def _manager(**servers: object) -> tuple[MCPClientManager, FakeConnector]:
    connector = FakeConnector(servers)  # type: ignore[arg-type]
    mgr = MCPClientManager(
        configs(*servers), connector=connector, default_timeout_s=0.5, max_retries=1, unavailable_recheck_s=0
    )
    return mgr, connector


async def test_discovery_builds_namespaced_registry_from_mcp() -> None:
    mgr, _ = _manager(library=library_server(), academics=academics_server())
    await mgr.refresh()
    names = [t.qualified_name for t in mgr.tools]
    assert names == ["academics__search_handbook", "library__get_book_availability", "library__search_books"]
    tool = mgr.get_tool("library__search_books")
    assert tool is not None and "title" not in tool.input_schema  # compacted
    state = {s.id: s for s in mgr.server_states}["library"]
    assert state.status is ServerStatus.AVAILABLE and state.protocol_version == "2026-07-28"


async def test_registry_reflects_server_changes_on_refresh() -> None:
    lib = library_server()
    mgr, _ = _manager(library=lib)
    await mgr.refresh()
    del lib.tools["get_book_availability"]
    await mgr.refresh()
    assert [t.tool_name for t in mgr.tools] == ["search_books"]


async def test_unavailable_server_is_isolated() -> None:
    lib, acad = library_server(), academics_server()
    acad.down = True
    mgr, _ = _manager(library=lib, academics=acad)
    await mgr.refresh()
    states = {s.id: s for s in mgr.server_states}
    assert states["academics"].status is ServerStatus.UNAVAILABLE
    assert states["library"].status is ServerStatus.AVAILABLE
    assert all(t.server_id == "library" for t in mgr.tools)


async def test_not_configured_server_is_reported() -> None:
    from app.mcp.config import ServerConfig

    mgr = MCPClientManager([ServerConfig(id="events", name="Events", url=None)], connector=FakeConnector({}))
    await mgr.refresh()
    assert mgr.server_states[0].status is ServerStatus.NOT_CONFIGURED


async def test_routes_call_to_owning_server() -> None:
    lib, acad = library_server(), academics_server()
    mgr, _ = _manager(library=lib, academics=acad)
    await mgr.refresh()
    ex = await mgr.call_tool("library__search_books", {"query": "algorithms"})
    assert ex.status is ToolStatus.SUCCESS
    assert lib.calls == [("search_books", {"query": "algorithms"})]
    assert acad.calls == []
    assert ex.data and ex.data["books"][0]["book_id"] == "LIB-0001"


@pytest.mark.parametrize(
    ("args", "fragment"),
    [
        ({}, "required"),
        ({"query": ""}, "query"),
        ({"query": "x", "limit": 99}, "limit"),
        ({"query": "x", "limit": "three"}, "limit"),
        ({"query": "x", "path": "/etc/passwd"}, "Unexpected argument"),
    ],
)
async def test_invalid_arguments_never_reach_server(args: dict[str, object], fragment: str) -> None:
    lib = library_server()
    mgr, _ = _manager(library=lib)
    await mgr.refresh()
    ex = await mgr.call_tool("library__search_books", args)
    assert ex.status is ToolStatus.INVALID_ARGUMENTS
    assert fragment in (ex.error or "")
    assert lib.calls == []


async def test_unknown_tool() -> None:
    mgr, _ = _manager(library=library_server())
    await mgr.refresh()
    ex = await mgr.call_tool("library__delete_everything", {})
    assert ex.status is ToolStatus.UNKNOWN_TOOL


async def test_tool_error_is_not_retried() -> None:
    lib = library_server()
    mgr, _ = _manager(library=lib)
    await mgr.refresh()
    before = lib.connections
    ex = await mgr.call_tool("library__get_book_availability", {"book_id": "NOPE"})
    assert ex.status is ToolStatus.TOOL_ERROR and ex.attempts == 1
    assert lib.connections - before == 1


async def test_transient_failure_is_retried_then_succeeds() -> None:
    lib = library_server()
    mgr, _ = _manager(library=lib)
    await mgr.refresh()
    lib.fail_next = 1
    ex = await mgr.call_tool("library__search_books", {"query": "x"})
    assert ex.status is ToolStatus.SUCCESS and ex.attempts == 2


async def test_timeout_is_bounded_and_marks_server_unavailable() -> None:
    lib = library_server()
    mgr, _ = _manager(library=lib)
    await mgr.refresh()
    lib.delay_s = 5
    ex = await mgr.call_tool("library__search_books", {"query": "x"})
    assert ex.status is ToolStatus.TIMEOUT
    assert ex.attempts == 2  # one retry
    assert ex.duration_ms < 2500
    assert mgr.server_states[0].status is ServerStatus.UNAVAILABLE


async def test_server_down_mid_session_then_recovers() -> None:
    lib = library_server()
    mgr, _ = _manager(library=lib)
    await mgr.refresh()
    lib.down = True
    ex = await mgr.call_tool("library__search_books", {"query": "x"})
    assert ex.status is ToolStatus.UNAVAILABLE
    lib.down = False
    await mgr.ensure_fresh()  # recheck interval is 0 in this test
    assert mgr.server_states[0].status is ServerStatus.AVAILABLE


def test_classify_nested_exception_groups() -> None:
    nested = ExceptionGroup("outer", [ExceptionGroup("inner", [TimeoutError()])])
    assert classify_exception(nested)[0] is ToolStatus.TIMEOUT
    assert classify_exception(ConnectionRefusedError())[0] is ToolStatus.UNAVAILABLE
    assert classify_exception(ValueError("x"))[0] is ToolStatus.PROTOCOL_ERROR
