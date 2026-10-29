"""MCP client manager.

Responsibilities
* connect to the allowlisted MCP servers (Streamable HTTP by default),
* discover their tools and input schemas over MCP (``tools/list``),
* maintain a normalised registry with TTL-based refresh,
* validate model-generated arguments against the discovered schema,
* route calls to the owning server with per-call timeouts and bounded retries,
* classify every failure into a structured ``ToolStatus`` instead of raising.

Connections are short-lived (one MCP session per discovery or call). The
servers run in stateless HTTP mode, so this costs one extra round trip per
call but makes server restarts and outages trivially recoverable: there is no
long-lived session to repair.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Callable, Iterable, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import Any, Protocol

import anyio
import httpx
from mcp import Client
from mcp.shared.exceptions import MCPError

from .config import ServerConfig
from .models import (
    TOOL_NAME_SEPARATOR,
    TRANSIENT_STATUSES,
    RegisteredTool,
    ServerState,
    ServerStatus,
    ToolExecution,
    ToolStatus,
)
from .validation import validate_arguments


class MCPSession(Protocol):
    async def list_tools(self, *, cursor: str | None = None, cache_mode: Any = ...) -> Any: ...

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None, read_timeout_seconds: float | None = None
    ) -> Any: ...


Connector = Callable[[ServerConfig, float], AbstractAsyncContextManager[MCPSession]]


def http_connector(cfg: ServerConfig, timeout_s: float) -> AbstractAsyncContextManager[MCPSession]:
    """Default connector: Streamable HTTP via the official SDK ``Client``."""
    assert cfg.url  # guarded by ServerConfig.configured
    return Client(cfg.url, read_timeout_seconds=timeout_s, cache=None)  # type: ignore[return-value]


def _now() -> datetime:
    return datetime.now(UTC)


def _leaves(exc: BaseException) -> Iterable[BaseException]:
    if isinstance(exc, BaseExceptionGroup):
        for inner in exc.exceptions:
            yield from _leaves(inner)
    else:
        yield exc


def classify_exception(exc: BaseException) -> tuple[ToolStatus, str]:
    """Map transport/protocol exceptions (often wrapped in ExceptionGroups) to a status and safe message."""
    for leaf in _leaves(exc):
        name = type(leaf).__name__
        if isinstance(leaf, TimeoutError) or "Timeout" in name:
            return ToolStatus.TIMEOUT, "The server did not respond in time."
        if isinstance(leaf, (ConnectionError, OSError, httpx.TransportError)) or any(
            key in name for key in ("Connect", "Network", "RemoteProtocol", "ReadError", "WriteError")
        ):
            return ToolStatus.UNAVAILABLE, "The server is unreachable."
        if isinstance(leaf, MCPError):
            return ToolStatus.PROTOCOL_ERROR, f"MCP error: {leaf}"[:300]
        status_code = getattr(getattr(leaf, "response", None), "status_code", None)
        if status_code is not None:
            return ToolStatus.UNAVAILABLE, f"The server returned HTTP {status_code}."
    return ToolStatus.PROTOCOL_ERROR, f"Unexpected client error ({type(exc).__name__})."


def compact_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Drop noise (``title`` keys) to keep tool definitions small for the LLM context."""

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items() if k != "title"}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    result = walk(schema)
    result.setdefault("properties", {})
    return result  # type: ignore[no-any-return]


class MCPClientManager:
    def __init__(
        self,
        servers: Sequence[ServerConfig],
        *,
        connector: Connector = http_connector,
        default_timeout_s: float = 8.0,
        max_retries: int = 1,
        registry_ttl_s: float = 300.0,
        unavailable_recheck_s: float = 15.0,
        health_fetcher: Callable[[ServerConfig], Any] | None = None,
    ) -> None:
        self._servers = {s.id: s for s in servers}
        self._connector = connector
        self._default_timeout = default_timeout_s
        self._max_retries = max_retries
        self._ttl = registry_ttl_s
        self._recheck = unavailable_recheck_s
        self._health_fetcher = health_fetcher
        self._tools: dict[str, RegisteredTool] = {}
        self._states: dict[str, ServerState] = {
            s.id: ServerState(
                id=s.id,
                name=s.name,
                description=s.description,
                url=s.url,
                status=ServerStatus.UNKNOWN if s.configured else ServerStatus.NOT_CONFIGURED,
            )
            for s in servers
        }
        self._last_refresh: dict[str, float] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ discovery
    def _timeout(self, cfg: ServerConfig) -> float:
        return cfg.timeout_s or self._default_timeout

    async def _discover_server(self, cfg: ServerConfig) -> None:
        state = self._states[cfg.id]
        started = time.perf_counter()
        try:
            with anyio.fail_after(self._timeout(cfg)):
                async with self._connector(cfg, self._timeout(cfg)) as client:
                    tools: list[Any] = []
                    cursor: str | None = None
                    for _ in range(20):  # pagination guard
                        page = await client.list_tools(cursor=cursor, cache_mode="refresh")
                        tools.extend(page.tools)
                        cursor = page.next_cursor
                        if not cursor:
                            break
                    protocol = getattr(client, "protocol_version", None)
                    info = getattr(client, "server_info", None)
        except Exception as exc:  # noqa: BLE001 - boundary: classified into a server state, never propagated
            _, message = classify_exception(exc)
            self._drop_server_tools(cfg.id)
            state.status = ServerStatus.UNAVAILABLE
            state.error = message
            state.tool_names = []
            state.latency_ms = None
        else:
            discovered = _now()
            self._drop_server_tools(cfg.id)
            for tool in tools:
                qualified = f"{cfg.id}{TOOL_NAME_SEPARATOR}{tool.name}"
                self._tools[qualified] = RegisteredTool(
                    qualified_name=qualified,
                    server_id=cfg.id,
                    tool_name=tool.name,
                    description=(tool.description or "").strip()[:1024],
                    input_schema=compact_schema(dict(tool.input_schema or {"type": "object"})),
                    has_output_schema=bool(getattr(tool, "output_schema", None)),
                    discovered_at=discovered,
                )
            state.status = ServerStatus.AVAILABLE
            state.error = None
            state.tool_names = sorted(t.name for t in tools)
            state.latency_ms = round((time.perf_counter() - started) * 1000, 1)
            state.protocol_version = protocol if isinstance(protocol, str) else None
            state.server_version = getattr(info, "version", None) or None
        state.last_checked = _now()
        self._last_refresh[cfg.id] = time.monotonic()
        if self._health_fetcher and state.status is ServerStatus.AVAILABLE:
            try:
                detail = await self._health_fetcher(cfg)
                source = (detail or {}).get("source") or {}
                state.data_mode = source.get("mode")
                state.source_detail = source
            except Exception:  # noqa: BLE001 - /health metadata is optional
                state.source_detail = None

    def _drop_server_tools(self, server_id: str) -> None:
        for name in [n for n, t in self._tools.items() if t.server_id == server_id]:
            del self._tools[name]

    async def refresh(self, server_ids: Iterable[str] | None = None) -> None:
        """Re-discover tools for the given (or all configured) servers concurrently."""
        targets = [
            self._servers[i]
            for i in (server_ids if server_ids is not None else self._servers)
            if i in self._servers and self._servers[i].configured
        ]
        async with self._lock:
            await asyncio.gather(*(self._discover_server(cfg) for cfg in targets))

    async def ensure_fresh(self) -> None:
        """Refresh servers whose registry entry is older than the TTL, or recently unavailable."""
        now = time.monotonic()
        stale = []
        for sid, cfg in self._servers.items():
            if not cfg.configured:
                continue
            last = self._last_refresh.get(sid)
            state = self._states[sid]
            limit = self._recheck if state.status is not ServerStatus.AVAILABLE else self._ttl
            # ">=": monotonic() can return the same value twice on coarse clocks (Windows ~15 ms),
            # which with a 0 s recheck interval would otherwise never re-check a failed server.
            if last is None or now - last >= limit:
                stale.append(sid)
        if stale:
            await self.refresh(stale)

    # ------------------------------------------------------------------ registry views
    @property
    def tools(self) -> list[RegisteredTool]:
        return sorted(self._tools.values(), key=lambda t: t.qualified_name)

    @property
    def server_states(self) -> list[ServerState]:
        return [self._states[s] for s in self._servers]

    def get_tool(self, qualified_name: str) -> RegisteredTool | None:
        return self._tools.get(qualified_name)

    def server_name(self, server_id: str | None) -> str:
        return self._servers[server_id].name if server_id in self._servers else str(server_id)

    # ------------------------------------------------------------------ execution
    def _result(
        self,
        call_id: str,
        name: str,
        args: dict[str, Any] | None,
        status: ToolStatus,
        started: datetime,
        t0: float,
        tool: RegisteredTool | None = None,
        **extra: Any,
    ) -> ToolExecution:
        return ToolExecution(
            call_id=call_id,
            qualified_name=name,
            server_id=tool.server_id if tool else None,
            tool_name=tool.tool_name if tool else None,
            arguments=args,
            status=status,
            started_at=started,
            finished_at=_now(),
            duration_ms=round((time.perf_counter() - t0) * 1000, 1),
            **extra,
        )

    async def call_tool(
        self, qualified_name: str, arguments: dict[str, Any] | None, *, call_id: str | None = None
    ) -> ToolExecution:
        call_id = call_id or uuid.uuid4().hex[:12]
        started, t0 = _now(), time.perf_counter()
        tool = self.get_tool(qualified_name)
        if tool is None:
            return self._result(
                call_id, qualified_name, arguments, ToolStatus.UNKNOWN_TOOL, started, t0,
                error=f"Unknown tool '{qualified_name}'. Only the provided tools may be called.",
            )  # fmt: skip
        args = arguments if arguments is not None else {}
        errors = validate_arguments(tool.input_schema, args)
        unknown = sorted(set(args) - set(tool.input_schema.get("properties", {}))) if isinstance(args, dict) else []
        if unknown:
            errors.append(f"Unexpected argument(s): {', '.join(unknown)}")
        if errors:
            return self._result(
                call_id, qualified_name, args, ToolStatus.INVALID_ARGUMENTS, started, t0, tool,
                error="Invalid arguments: " + "; ".join(errors),
            )  # fmt: skip

        cfg = self._servers[tool.server_id]
        timeout = self._timeout(cfg)
        attempts = 0
        status, message = ToolStatus.UNAVAILABLE, "not attempted"
        while attempts <= self._max_retries:
            attempts += 1
            try:
                with anyio.fail_after(timeout):
                    async with self._connector(cfg, timeout) as client:
                        result = await client.call_tool(tool.tool_name, args, read_timeout_seconds=timeout)
            except Exception as exc:  # noqa: BLE001 - boundary: classified into a ToolStatus, never propagated
                status, message = classify_exception(exc)
                if status not in TRANSIENT_STATUSES or attempts > self._max_retries:
                    break
                await asyncio.sleep(min(0.25 * 2 ** (attempts - 1), 2.0))
                continue
            text = "\n".join(getattr(c, "text", "") for c in (result.content or []) if getattr(c, "text", None))
            if result.is_error:
                return self._result(
                    call_id, qualified_name, args, ToolStatus.TOOL_ERROR, started, t0, tool,
                    error=text[:500] or "The tool reported an error.", attempts=attempts,
                )  # fmt: skip
            data = result.structured_content
            if data is None and text:
                try:
                    parsed = json.loads(text)
                    data = parsed if isinstance(parsed, dict) else {"result": parsed}
                except ValueError:
                    data = None
            if tool.has_output_schema and not isinstance(data, dict):
                # The tool promised structured output and did not deliver it: never treat as a result.
                return self._result(
                    call_id, qualified_name, args, ToolStatus.MALFORMED_RESPONSE, started, t0, tool,
                    error="The server returned a malformed or missing structured response.", attempts=attempts,
                )  # fmt: skip
            self._states[cfg.id].status = ServerStatus.AVAILABLE
            return self._result(
                call_id, qualified_name, args, ToolStatus.SUCCESS, started, t0, tool,
                data=data, text=None if data is not None else text[:4000], attempts=attempts,
            )  # fmt: skip

        if status in TRANSIENT_STATUSES:
            state = self._states[cfg.id]
            state.status, state.error, state.last_checked = ServerStatus.UNAVAILABLE, message, _now()
            self._last_refresh[cfg.id] = time.monotonic()
        return self._result(call_id, qualified_name, args, status, started, t0, tool, error=message, attempts=attempts)


def clone_with_connector(manager: MCPClientManager, connector: Connector) -> MCPClientManager:
    """Copy a manager (config + current registry snapshot) but route calls through ``connector``.

    Used for per-request fault injection without disturbing the shared registry.
    """
    clone = MCPClientManager(
        list(manager._servers.values()),
        connector=connector,
        default_timeout_s=manager._default_timeout,
        max_retries=manager._max_retries,
        registry_ttl_s=float("inf"),
        unavailable_recheck_s=float("inf"),
    )
    clone._tools = dict(manager._tools)
    clone._states = {k: v.model_copy(deep=True) for k, v in manager._states.items()}
    clone._last_refresh = {k: time.monotonic() for k in manager._servers}
    return clone
