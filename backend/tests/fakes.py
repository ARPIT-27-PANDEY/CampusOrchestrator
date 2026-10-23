"""Fake MCP sessions/connectors for backend unit tests (real mcp_types result models)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import mcp_types as mt

from app.mcp.config import ServerConfig

Handler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]] | dict[str, Any]]


class FakeServer:
    def __init__(self, tools: dict[str, tuple[str, dict[str, Any], Handler]]) -> None:
        self.tools = tools
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.connections = 0
        self.down = False
        self.delay_s = 0.0
        self.fail_next = 0  # number of upcoming connections that fail with ConnectionResetError


class FakeSession:
    def __init__(self, server: FakeServer) -> None:
        self.server = server
        self.protocol_version = "2026-07-28"
        self.server_info = mt.Implementation(name="fake", version="9.9.9")

    async def list_tools(self, *, cursor: str | None = None, cache_mode: Any = "use") -> mt.ListToolsResult:
        return mt.ListToolsResult(
            tools=[
                mt.Tool(name=name, description=desc, input_schema=schema)
                for name, (desc, schema, _) in self.server.tools.items()
            ]
        )

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None, read_timeout_seconds: float | None = None
    ) -> mt.CallToolResult:
        self.server.calls.append((name, dict(arguments or {})))
        if self.server.delay_s:
            await asyncio.sleep(self.server.delay_s)
        if name not in self.server.tools:
            return mt.CallToolResult(content=[mt.TextContent(type="text", text=f"Unknown tool: {name}")], is_error=True)
        result = self.server.tools[name][2](arguments or {})
        if asyncio.iscoroutine(result):
            result = await result
        assert isinstance(result, dict)
        if result.get("__error__"):
            return mt.CallToolResult(
                content=[mt.TextContent(type="text", text=str(result["__error__"]))], is_error=True
            )
        return mt.CallToolResult(content=[mt.TextContent(type="text", text="{}")], structured_content=result)


class FakeConnector:
    def __init__(self, servers: dict[str, FakeServer]) -> None:
        self.servers = servers

    def __call__(self, cfg: ServerConfig, timeout_s: float) -> Any:
        return self._connect(cfg)

    @asynccontextmanager
    async def _connect(self, cfg: ServerConfig) -> AsyncIterator[FakeSession]:
        server = self.servers[cfg.id]
        server.connections += 1
        if server.down:
            raise ExceptionGroup("unhandled errors in a TaskGroup", [ConnectionRefusedError("refused")])
        if server.fail_next > 0:
            server.fail_next -= 1
            raise ConnectionResetError("reset")
        yield FakeSession(server)


SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "minLength": 1},
        "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 3},
    },
    "required": ["query"],
    "title": "searchArguments",
}


def library_server() -> FakeServer:
    return FakeServer(
        {
            "search_books": (
                "Search books",
                SEARCH_SCHEMA,
                lambda a: {
                    "count": 1,
                    "books": [{"book_id": "LIB-0001", "title": "Introduction to Algorithms"}],
                    "source": {"source_id": "library", "mode": "demo", "provider": "fake"},
                },
            ),
            "get_book_availability": (
                "Availability",
                {"type": "object", "properties": {"book_id": {"type": "string"}}, "required": ["book_id"]},
                lambda a: (
                    {"__error__": "No such book"}
                    if a["book_id"] == "NOPE"
                    else {"book_id": a["book_id"], "available": True, "source": {"mode": "demo"}}
                ),
            ),
        }
    )


def academics_server() -> FakeServer:
    return FakeServer(
        {
            "search_handbook": (
                "Search handbook",
                {
                    "type": "object",
                    "properties": {"query": {"type": "string"}, "top_k": {"type": "integer"}},
                    "required": ["query"],
                },
                lambda a: {
                    "found": True,
                    "passages": [
                        {
                            "citation_id": "abc-p4-c2",
                            "document_title": "Academic Handbook 2026-27",
                            "source_filename": "academic_handbook_2026.pdf",
                            "document_version": "ce1e90b84acc",
                            "page": 4,
                            "section": "Section 3 - Course Prerequisites",
                            "excerpt": "3.3 AI Workshop Series prerequisite. Requires CS 210.",
                            "score": 0.42,
                        }
                    ],
                    "source": {"source_id": "academics", "mode": "demo", "provider": "qdrant"},
                },
            )
        }
    )


def configs(*ids: str) -> list[ServerConfig]:
    return [
        ServerConfig(id=i, name=i.title(), url=f"http://localhost:81{n:02d}/mcp") for n, i in enumerate(ids, start=1)
    ]
