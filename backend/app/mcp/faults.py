"""Fault injection for tests, evals and the failure demo.

Wraps a connector so that selected servers fail. ``scope="calls"`` (default)
keeps discovery working and fails tool calls, which simulates a server dying
mid-request; ``scope="all"`` also fails discovery (server down from the start).
Enabled in the API only when ``ALLOW_FAULT_INJECTION=true``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, Literal

from .config import ServerConfig
from .manager import Connector, MCPSession

FaultKind = Literal["down", "timeout", "slow", "flaky", "malformed"]
FaultScope = Literal["calls", "all"]


class _MalformedResult:
    """What a misbehaving server might send: no structured content, non-JSON text."""

    is_error = False
    structured_content = None

    def __init__(self) -> None:
        self.content = [type("Text", (), {"text": "<html><body>502 Bad Gateway</body></html>"})()]


class _FaultySession:
    def __init__(self, inner: MCPSession, fault: FaultKind, server_id: str, owner: FaultInjectingConnector) -> None:
        self._inner = inner
        self._fault = fault
        self._server_id = server_id
        self._owner = owner

    async def list_tools(self, **kwargs: Any) -> Any:
        return await self._inner.list_tools(**kwargs)

    async def call_tool(self, *args: Any, **kwargs: Any) -> Any:
        await self._owner.inject(self._fault, self._server_id)
        if self._fault == "malformed":
            return _MalformedResult()
        return await self._inner.call_tool(*args, **kwargs)


class FaultInjectingConnector:
    """``faults`` maps server id -> fault kind. ``flaky`` fails only the first tool call per server."""

    def __init__(
        self,
        base: Connector,
        faults: Mapping[str, FaultKind],
        *,
        scope: FaultScope = "calls",
        hang_s: float = 3600.0,
        slow_delay_s: float = 0.5,
    ) -> None:
        self._base = base
        self.faults: dict[str, FaultKind] = dict(faults)
        self.scope = scope
        self._hang = hang_s
        self._slow = slow_delay_s
        self._flaky_seen: set[str] = set()

    async def inject(self, fault: FaultKind, server_id: str) -> None:
        if fault == "down":
            raise ConnectionRefusedError(f"[fault injection] {server_id} is down")
        if fault == "timeout":
            await asyncio.sleep(self._hang)  # cancelled by the caller's timeout
        if fault == "slow":
            await asyncio.sleep(self._slow)
        if fault == "flaky" and server_id not in self._flaky_seen:
            self._flaky_seen.add(server_id)
            raise ConnectionResetError(f"[fault injection] {server_id} dropped the connection")

    def __call__(self, cfg: ServerConfig, timeout_s: float) -> AbstractAsyncContextManager[MCPSession]:
        return self._connect(cfg, timeout_s)

    @asynccontextmanager
    async def _connect(self, cfg: ServerConfig, timeout_s: float) -> AsyncIterator[MCPSession]:
        fault = self.faults.get(cfg.id)
        if fault and self.scope == "all" and fault != "flaky":
            await self.inject(fault, cfg.id)
        async with self._base(cfg, timeout_s) as session:
            yield _FaultySession(session, fault, cfg.id, self) if fault else session
