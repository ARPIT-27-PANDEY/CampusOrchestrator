"""Application container: wires settings, MCP manager, LLM provider and orchestrator (DI-friendly)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

from .agent.orchestrator import AgentLimits, Orchestrator
from .agent.trace_store import TracePrivacy, TraceStore
from .config import Settings
from .llm.base import LLMProvider
from .llm.factory import build_provider
from .mcp.config import ServerConfig, load_server_configs
from .mcp.manager import Connector, MCPClientManager, http_connector
from .security import Guard


async def fetch_health(cfg: ServerConfig) -> dict[str, Any] | None:
    """GET <server>/health for data-mode/freshness metadata (same allowlisted host as the MCP URL)."""
    if not cfg.url:
        return None
    parsed = urlparse(cfg.url)
    url = urlunparse((parsed.scheme, parsed.netloc, "/health", "", "", ""))
    async with httpx.AsyncClient(timeout=3.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        return data


@dataclass
class AppState:
    settings: Settings
    mcp: MCPClientManager
    llm: LLMProvider
    traces: TraceStore
    orchestrator: Orchestrator
    chat_slots: asyncio.Semaphore
    llm_error: str | None = None
    guard: Guard = field(default=None)  # type: ignore[assignment]  # always set by build_state


def build_state(
    settings: Settings,
    *,
    connector: Connector | None = None,
    llm: LLMProvider | None = None,
    servers: list[ServerConfig] | None = None,
    fetch_source_health: bool = True,
) -> AppState:
    configs = (
        servers if servers is not None else load_server_configs(settings.mcp_servers_file, settings.allowed_host_set)
    )
    manager = MCPClientManager(
        configs,
        connector=connector or http_connector,
        default_timeout_s=settings.tool_timeout_s,
        max_retries=settings.tool_max_retries,
        registry_ttl_s=settings.tool_registry_ttl_s,
        unavailable_recheck_s=settings.unavailable_recheck_s,
        health_fetcher=fetch_health if fetch_source_health and connector is None else None,
    )
    llm_error = None
    if llm is None:
        try:
            llm = build_provider(settings)
        except Exception as exc:  # noqa: BLE001 - reported via /api/health and chat errors; no silent fallback
            llm_error = str(exc)
            llm = _UnconfiguredProvider(settings, llm_error)
    traces = TraceStore(
        settings.trace_capacity,
        settings.trace_log_path,
        backend=settings.trace_backend,
        db_path=settings.trace_db_path,
        retention_s=settings.trace_retention_hours * 3600,
        privacy=TracePrivacy(
            keep_query=settings.keep_query_text,
            keep_payloads=settings.keep_tool_payloads,
            redact_text=settings.trace_redact,
        ),
    )
    limits = AgentLimits(
        max_iterations=settings.max_agent_iterations,
        max_tool_calls=settings.max_tool_calls,
        max_tool_result_chars=settings.max_tool_result_chars,
        execution_mode=settings.tool_execution_mode,
    )
    return AppState(
        settings=settings,
        mcp=manager,
        llm=llm,
        traces=traces,
        orchestrator=Orchestrator(llm, manager, traces, limits, timezone=settings.campus_timezone),
        chat_slots=asyncio.Semaphore(settings.max_concurrent_chats),
        llm_error=llm_error,
        guard=Guard(settings),
    )


class _UnconfiguredProvider:
    """Placeholder that fails every request with a clear configuration error."""

    name = "unconfigured"

    def __init__(self, settings: Settings, message: str) -> None:
        self.model = settings.groq_model if settings.llm_provider == "groq" else settings.llm_provider
        self.name = settings.llm_provider
        self._message = message

    async def complete(self, *args: Any, **kwargs: Any) -> Any:
        from .llm.base import LLMConfigError

        raise LLMConfigError(self._message)
