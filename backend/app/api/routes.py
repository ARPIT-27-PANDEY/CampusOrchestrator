"""REST + SSE endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import StreamingResponse

from .. import __version__
from ..agent.models import AgentResult, AgentTrace
from ..agent.orchestrator import Orchestrator
from ..mcp.faults import FaultInjectingConnector
from ..mcp.manager import clone_with_connector
from ..mcp.models import ServerStatus
from ..security import COOKIE_NAME, RateLimiter, origin_allowed, password_matches
from ..state import AppState
from .errors import ApiError
from .schemas import (
    ChatRequest,
    EvalRunInfo,
    HealthResponse,
    LoginRequest,
    SessionInfo,
    SourcesResponse,
    ToolInfo,
    TraceListItem,
)

log = logging.getLogger("campusos.api")
router = APIRouter(prefix="/api")
KEEPALIVE_S = 15.0
DISCONNECT_POLL_S = 0.5


def _state(request: Request) -> AppState:
    state: AppState = request.app.state.campus
    return state


# ---------------------------------------------------------------------------------------------- guards
def _limit(state: AppState, limiter: RateLimiter, key: str, metric: str) -> None:
    allowed, retry = limiter.check(key)
    if not allowed:
        state.guard.metrics.inc(metric)
        raise ApiError(
            429,
            "rate_limited",
            f"Too many requests; retry in {retry:.0f} s.",
            headers={"Retry-After": str(int(retry) + 1)},
        )


def _check_origin(request: Request, state: AppState) -> None:
    ok, reason = origin_allowed(request, state.settings.cors_origin_list)
    if not ok:
        state.guard.metrics.inc("origin_rejected")
        raise ApiError(403, "origin_rejected", reason)


def require_session(request: Request) -> str:
    """Protected endpoints: a valid session in password mode; Origin-checked for unsafe methods."""
    state = _state(request)
    _check_origin(request, state)
    if state.guard.mode == "password" and state.guard.session(request) is None:
        state.guard.metrics.inc("auth_required")
        raise ApiError(401, "auth_required", "Please sign in to use the assistant.")
    return state.guard.identity(request)


def read_limited(request: Request) -> None:
    state = _state(request)
    _limit(state, state.guard.read_limiter, state.guard.identity(request), "read_rate_limited")


# ---------------------------------------------------------------------------------------------- auth
@router.get("/auth/session", response_model=SessionInfo, summary="Current access mode and session state")
async def session_info(request: Request) -> SessionInfo:
    state = _state(request)
    session = state.guard.session(request)
    return SessionInfo(
        access_mode=state.guard.mode,
        authenticated=state.guard.mode == "open" or session is not None,
        expires_at=datetime.fromtimestamp(session.expires_at, UTC) if session else None,
    )


@router.post("/auth/login", response_model=SessionInfo, summary="Exchange the shared password for a session cookie")
async def login(body: LoginRequest, request: Request, response: Response) -> SessionInfo:
    state = _state(request)
    _check_origin(request, state)
    if state.guard.mode != "password" or state.guard.signer is None:
        return SessionInfo(access_mode="open", authenticated=True)
    from ..security import client_ip

    _limit(
        state, state.guard.login_limiter, client_ip(request, state.settings.trusted_proxy_hops), "login_rate_limited"
    )
    expected = state.settings.access_password.get_secret_value() if state.settings.access_password else ""
    if not password_matches(body.password, expected):
        state.guard.metrics.inc("login_failed")
        raise ApiError(401, "invalid_password", "Incorrect password.")
    token, session = state.guard.signer.issue()
    response.set_cookie(value=token, max_age=state.guard.signer.ttl_s, **state.guard.cookie_kwargs())
    state.guard.metrics.inc("login_succeeded")
    return SessionInfo(
        access_mode="password", authenticated=True, expires_at=datetime.fromtimestamp(session.expires_at, UTC)
    )


@router.post("/auth/logout", response_model=SessionInfo, summary="Clear the session cookie")
async def logout(request: Request, response: Response) -> SessionInfo:
    state = _state(request)
    _check_origin(request, state)
    kwargs = state.guard.cookie_kwargs()
    response.delete_cookie(kwargs.pop("key"), **kwargs)
    return SessionInfo(access_mode=state.guard.mode, authenticated=state.guard.mode == "open")


# ---------------------------------------------------------------------------------------------- chat
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
    return Orchestrator(o.llm, manager, o.traces, o.limits, clock=o.clock)


async def _acquire(state: AppState) -> None:
    try:
        await asyncio.wait_for(state.chat_slots.acquire(), timeout=2.0)
    except TimeoutError as exc:
        state.guard.metrics.inc("busy_rejected")
        raise ApiError(
            429, "too_many_requests", "The assistant is busy; please retry shortly.", headers={"Retry-After": "5"}
        ) from exc


def _chat_preflight(request: Request, req: ChatRequest, identity: str) -> tuple[AppState, Orchestrator]:
    state = _state(request)
    orch = _orchestrator_for(state, req)
    _limit(state, state.guard.chat_limiter, identity, "chat_rate_limited")
    return state, orch


@router.post("/chat", response_model=AgentResult, summary="Ask a question and wait for the full answer")
async def chat(req: ChatRequest, request: Request, identity: str = Depends(require_session)) -> AgentResult:
    state, orch = _chat_preflight(request, req, identity)
    await _acquire(state)
    task = asyncio.create_task(orch.run(req.message))
    try:
        while not task.done():
            done, _ = await asyncio.wait({task}, timeout=DISCONNECT_POLL_S)
            if not done and await request.is_disconnected():
                task.cancel()  # the browser went away: stop spending model/tool budget
                state.guard.metrics.inc("cancelled_on_disconnect")
                raise ApiError(499, "client_closed_request", "The client disconnected.")
        return task.result()
    finally:
        if not task.done():
            task.cancel()
        state.chat_slots.release()


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str, ensure_ascii=False)}\n\n"


@router.post(
    "/chat/stream",
    summary="Ask a question; receive Server-Sent Events",
    response_description="text/event-stream: start, discovery, llm_start, token, answer_reset, tool_start, tool_end, error, final, done",
)
async def chat_stream(
    req: ChatRequest, request: Request, identity: str = Depends(require_session)
) -> StreamingResponse:
    state, orch = _chat_preflight(request, req, identity)
    await _acquire(state)
    queue: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()
    released = False

    def release() -> None:
        nonlocal released
        if not released:
            released = True
            state.chat_slots.release()

    async def emit(kind: str, data: dict[str, Any]) -> None:
        await queue.put((kind, data))

    async def runner() -> None:
        try:
            await orch.run(req.message, emit=emit)
        except asyncio.CancelledError:
            state.guard.metrics.inc("cancelled_on_disconnect")
            raise
        except Exception:
            log.exception("Agent run failed")
            await queue.put(("error", {"code": "internal_error", "message": "An internal error occurred."}))
        finally:
            release()
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
                task.cancel()  # client disconnected; the runner counts the cancellation
            release()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


# ---------------------------------------------------------------------------------------------- sources/tools
@router.get("/sources", response_model=SourcesResponse, summary="Configured campus sources and their live status")
async def sources(
    request: Request, refresh: bool = Query(default=False), _: None = Depends(read_limited)
) -> SourcesResponse:
    state = _state(request)
    if refresh:
        await state.mcp.refresh()
    else:
        await state.mcp.ensure_fresh()
    return SourcesResponse(
        servers=state.mcp.server_states, tool_count=len(state.mcp.tools), checked_at=datetime.now(UTC)
    )


@router.get("/tools", response_model=list[ToolInfo], summary="Tool registry discovered from MCP servers")
async def tools(request: Request, _: None = Depends(read_limited)) -> list[ToolInfo]:
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


# ---------------------------------------------------------------------------------------------- traces (private)
@router.get("/traces", response_model=list[TraceListItem], summary="Recent execution traces (requires a session)")
async def traces(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    _: str = Depends(require_session),
    __: None = Depends(read_limited),
) -> list[TraceListItem]:
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


@router.get("/traces/{trace_id}", response_model=AgentTrace, summary="Full execution trace (requires a session)")
async def trace(
    trace_id: str, request: Request, _: str = Depends(require_session), __: None = Depends(read_limited)
) -> AgentTrace:
    found = _state(request).traces.get(trace_id)
    if found is None:
        raise ApiError(404, "trace_not_found", "No trace with that id (it may have expired).")
    return found


# ---------------------------------------------------------------------------------------------- evaluations (public)
def _runs_dir(state: AppState) -> Path:
    return state.settings.eval_report_path.parent / "runs"


@router.get("/evals/latest", summary="Latest evaluation report produced by evals/run_eval.py")
async def eval_report(request: Request, _: None = Depends(read_limited)) -> dict[str, Any]:
    path = _state(request).settings.eval_report_path
    if not path.exists():
        raise ApiError(404, "no_eval_report", "No evaluation report yet. Run: python -m evals.run_eval")
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8-sig"))
    return data


@router.get("/evals/runs", response_model=list[EvalRunInfo], summary="Saved evaluation runs (newest first)")
async def eval_runs(request: Request, _: None = Depends(read_limited)) -> list[EvalRunInfo]:
    out: list[EvalRunInfo] = []
    for path in sorted(_runs_dir(_state(request)).glob("*.json"), reverse=True):
        try:
            d = json.loads(path.read_text(encoding="utf-8-sig"))
        except ValueError:
            continue
        c = d.get("config") or {}
        summary = d.get("summary") or {}
        kind = d.get("kind", "agent")
        if kind not in ("agent", "retrieval", "library_search"):
            continue  # an unknown report type is skipped, never shown as an agent run
        results = d.get("results", [])
        out.append(
            EvalRunInfo(
                run_id=d.get("run_id") or path.stem,
                kind=kind,
                generated_at=d.get("generated_at"),
                dataset=d.get("dataset"),
                provider=d.get("provider") or ",".join(r.get("retriever") or r.get("mode") or "" for r in results),
                model=d.get("model"),
                transport=d.get("transport"),
                retriever=c.get("retriever"),
                repeat=c.get("repeat"),
                pass_rate=summary.get("pass_rate"),
                cases=summary.get("cases") or summary.get("runs"),
                legacy="legacy" in path.stem,
            )
        )
    return sorted(out, key=lambda r: r.generated_at or "", reverse=True)


@router.get("/evals/runs/{run_id}", summary="One saved evaluation run")
async def eval_run(run_id: str, request: Request, _: None = Depends(read_limited)) -> dict[str, Any]:
    if not run_id.replace("-", "").replace("_", "").isalnum():
        raise ApiError(422, "invalid_run_id", "Invalid run id.")
    path = _runs_dir(_state(request)) / f"{run_id}.json"
    if not path.exists():
        raise ApiError(404, "run_not_found", "No saved run with that id.")
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8-sig"))
    return data


# ---------------------------------------------------------------------------------------------- health/metrics
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
        campus_time=state.orchestrator.clock.now().isoformat(timespec="seconds"),
        access_mode=state.guard.mode,
    )


@router.get("/metrics", summary="Security and abuse-prevention counters (requires a session)")
async def metrics(request: Request, _: str = Depends(require_session)) -> dict[str, Any]:
    state = _state(request)
    return {"counters": state.guard.metrics.snapshot(), "note": "Per-process, in-memory counters."}


@router.get("/health/live", summary="Liveness probe")
async def live() -> dict[str, str]:
    return {"status": "ok"}


__all__ = ["COOKIE_NAME", "router"]
