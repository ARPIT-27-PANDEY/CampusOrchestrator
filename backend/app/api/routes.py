"""REST + SSE endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from .. import __version__
from ..agent.models import AgentResult, AgentTrace
from ..agent.orchestrator import Orchestrator
from ..mcp.faults import FaultInjectingConnector
from ..mcp.manager import clone_with_connector
from ..mcp.models import ServerStatus
from ..state import AppState
from .errors import ApiError
from .schemas import ChatRequest, HealthResponse, SourcesResponse, ToolInfo, TraceListItem

log = logging.getLogger("campusos.api")
router = APIRouter(prefix="/api")
KEEPALIVE_S = 15.0


def _state(request: Request) -> AppState:
    state: AppState = request.app.state.campus
    return state


def _orchestrator_for(state: AppState, req: ChatRequest) -> Orchestrator:
    if len(req.message) > state.settings.max_query_chars:
        raise ApiError(422, "query_too_long", f"Messages are limited to {state.settings.max_query_chars} characters.")
    if not req.simulate_failures:
        return state.orchestrator
    if not state.settings.allow_fault_injection:
        raise ApiError(403, "fault_injection_disabled", "Fault injection is disabled (set ALLOW_FAULT_INJECTION=true).")
    unknown = set(req.simulate_failures) - {s.id for s in state.mcp.server_states}
    if unknown:
        raise ApiError(422, "unknown_server", f"Unknown server id(s): {', '.join(sorted(unknown))}")
    faulty = FaultInjectingConnector(state.mcp._connector, req.simulate_failures)
    manager = clone_with_connector(state.mcp, faulty)
    o = state.orchestrator
    return Orchestrator(o.llm, manager, o.traces, o.limits)


async def _acquire(state: AppState) -> None:
    try:
        await asyncio.wait_for(state.chat_slots.acquire(), timeout=2.0)
    except TimeoutError as exc:
        raise ApiError(429, "too_many_requests", "The assistant is busy; please retry shortly.") from exc


@router.post("/chat", response_model=AgentResult, summary="Ask a question and wait for the full answer")
async def chat(req: ChatRequest, request: Request) -> AgentResult:
    state = _state(request)
    orch = _orchestrator_for(state, req)
    await _acquire(state)
    try:
        return await orch.run(req.message)
    finally:
        state.chat_slots.release()


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str, ensure_ascii=False)}\n\n"


@router.post(
    "/chat/stream",
    summary="Ask a question; receive Server-Sent Events",
    response_description="text/event-stream: start, discovery, llm_start, token, answer_reset, tool_start, tool_end, error, final, done",
)
async def chat_stream(req: ChatRequest, request: Request) -> StreamingResponse:
    state = _state(request)
    orch = _orchestrator_for(state, req)
    await _acquire(state)
    queue: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()

    async def emit(kind: str, data: dict[str, Any]) -> None:
        await queue.put((kind, data))

    async def runner() -> None:
        try:
            await orch.run(req.message, emit=emit)
        except Exception:
            log.exception("Agent run failed")
            await queue.put(("error", {"code": "internal_error", "message": "An internal error occurred."}))
        finally:
            state.chat_slots.release()
            await queue.put(None)

    task = asyncio.create_task(runner())

    async def stream() -> Any:
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_S)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if item is None:
                    yield _sse("done", {})
                    return
                yield _sse(*item)
        finally:
            if not task.done():
                task.cancel()  # client disconnected

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@router.get("/sources", response_model=SourcesResponse, summary="Configured campus sources and their live status")
async def sources(request: Request, refresh: bool = Query(default=False)) -> SourcesResponse:
    state = _state(request)
    if refresh:
        await state.mcp.refresh()
    else:
        await state.mcp.ensure_fresh()
    return SourcesResponse(
        servers=state.mcp.server_states, tool_count=len(state.mcp.tools), checked_at=datetime.now(UTC)
    )


@router.get("/tools", response_model=list[ToolInfo], summary="Tool registry discovered from MCP servers")
async def tools(request: Request) -> list[ToolInfo]:
    state = _state(request)
    await state.mcp.ensure_fresh()
    return [
        ToolInfo(
            name=t.qualified_name,
            server_id=t.server_id,
            tool_name=t.tool_name,
            description=t.description,
            input_schema=t.input_schema,
            discovered_at=t.discovered_at,
        )
        for t in state.mcp.tools
    ]


@router.get("/traces", response_model=list[TraceListItem], summary="Recent execution traces")
async def traces(request: Request, limit: int = Query(default=50, ge=1, le=200)) -> list[TraceListItem]:
    return [
        TraceListItem(
            trace_id=t.trace_id,
            created_at=t.created_at,
            query=t.query[:200],
            status=t.status,
            latency_ms=t.latency_ms,
            tool_calls=sum(1 for s in t.steps if s.kind == "tool"),
            provider=t.provider,
        )
        for t in _state(request).traces.recent(limit)
    ]


@router.get("/traces/{trace_id}", response_model=AgentTrace, summary="Full execution trace")
async def trace(trace_id: str, request: Request) -> AgentTrace:
    found = _state(request).traces.get(trace_id)
    if found is None:
        raise ApiError(404, "trace_not_found", "No trace with that id (traces are kept in memory).")
    return found


@router.get("/evals/latest", summary="Latest evaluation report produced by evals/run_eval.py")
async def eval_report(request: Request) -> dict[str, Any]:
    path = _state(request).settings.eval_report_path
    if not path.exists():
        raise ApiError(404, "no_eval_report", "No evaluation report yet. Run: python -m evals.run_eval")
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


@router.get("/health", response_model=HealthResponse, summary="Application health")
async def health(request: Request) -> HealthResponse:
    state = _state(request)
    servers = state.mcp.server_states
    configured = [s for s in servers if s.status is not ServerStatus.NOT_CONFIGURED]
    available = [s for s in configured if s.status is ServerStatus.AVAILABLE]
    ok = state.llm_error is None and len(available) == len(configured)
    return HealthResponse(
        status="ok" if ok else "degraded",
        version=__version__,
        environment=state.settings.app_env,
        llm={
            "provider": state.llm.name,
            "model": state.llm.model,
            "configured": state.llm_error is None,
            "error": state.llm_error,
        },
        mcp={"configured": len(configured), "available": len(available), "tools": len(state.mcp.tools)},
        time=datetime.now(UTC),
    )


@router.get("/health/live", summary="Liveness probe")
async def live() -> dict[str, str]:
    return {"status": "ok"}
