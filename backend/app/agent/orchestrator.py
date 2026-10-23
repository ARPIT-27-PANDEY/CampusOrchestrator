"""The agent loop: discover -> let the model pick tools -> execute via MCP -> synthesise.

Implemented explicitly (no agent framework) so each decision is inspectable:

1. refresh the tool registry from the MCP servers (TTL-based),
2. send the user query plus the discovered tool schemas to the LLM,
3. validate and execute requested tool calls through ``MCPClientManager``
   (sequential by default because GPT-OSS on Groq does not emit parallel calls;
   ``concurrent`` mode runs independent read-only calls of one turn together),
4. return untrusted-wrapped results to the model and loop, bounded by
   ``max_iterations`` and ``max_tool_calls``,
5. produce the final answer with citations/sources taken from tool output,
   plus a full execution trace.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..llm.base import ChatMessage, LLMError, LLMProvider, LLMResponse, LLMToolCallFormatError, ToolCall, ToolSpec
from ..mcp.manager import MCPClientManager
from ..mcp.models import FAILURE_STATUSES, ServerStatus, ToolExecution, ToolStatus
from . import prompts
from .citations import collect_citations, collect_sources, verify_citations
from .models import AgentResult, AgentTrace, ToolCallSummary, TraceStep
from .trace_store import TraceStore

EventSink = Callable[[str, dict[str, Any]], Awaitable[None]]


async def _discard(_: str, __: dict[str, Any]) -> None:
    return None


@dataclass(frozen=True)
class AgentLimits:
    max_iterations: int = 5
    max_tool_calls: int = 8
    max_tool_result_chars: int = 3500
    execution_mode: str = "sequential"  # or "concurrent"


class Orchestrator:
    def __init__(
        self,
        llm: LLMProvider,
        mcp: MCPClientManager,
        traces: TraceStore,
        limits: AgentLimits | None = None,
        timezone: str = "Asia/Kolkata",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.llm = llm
        self.mcp = mcp
        self.traces = traces
        self.limits = limits or AgentLimits()
        self._tz = ZoneInfo(timezone)
        self._clock = clock or (lambda: datetime.now(self._tz))

    def tool_specs(self) -> list[ToolSpec]:
        return [ToolSpec(t.qualified_name, t.description, t.input_schema) for t in self.mcp.tools]

    async def run(self, query: str, emit: EventSink = _discard, trace_id: str | None = None) -> AgentResult:
        run = _Run(self, query, emit, trace_id or uuid.uuid4().hex[:16])
        return await run.execute()


class _Run:
    """State for one query; kept separate so the Orchestrator itself stays stateless."""

    def __init__(self, orch: Orchestrator, query: str, emit: EventSink, trace_id: str) -> None:
        self.o = orch
        self.query = query
        self.emit = emit
        self.trace = AgentTrace(
            trace_id=trace_id,
            created_at=datetime.now(UTC),
            query=query,
            provider=orch.llm.name,
            model=orch.llm.model,
        )
        self.executions: list[ToolExecution] = []
        self.summaries: list[ToolCallSummary] = []
        self.cache: dict[str, ToolExecution] = {}
        self.warnings: list[str] = []
        self.usage: dict[str, int] = {"llm_calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
        self.t0 = time.perf_counter()
        self.streamed_text = False

    # ------------------------------------------------------------------ helpers
    def _step(self, kind: str, started: float, **detail: Any) -> None:
        self.trace.steps.append(
            TraceStep(
                kind=kind,  # type: ignore[arg-type]
                started_at=datetime.now(UTC),
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
                detail=detail,
            )
        )

    async def _on_text(self, text: str) -> None:
        self.streamed_text = True
        await self.emit("token", {"text": text})

    async def _call_llm(
        self, messages: list[ChatMessage], tools: list[ToolSpec], iteration: int, allow_tools: bool
    ) -> LLMResponse:
        started = time.perf_counter()
        await self.emit("llm_start", {"iteration": iteration})
        self.streamed_text = False
        try:
            resp = await self.o.llm.complete(messages, tools, on_text=self._on_text, allow_tools=allow_tools)
        except LLMError as exc:
            self._step("llm", started, iteration=iteration, error=exc.code, message=str(exc))
            raise
        self.usage["llm_calls"] += 1
        for key in ("prompt_tokens", "completion_tokens"):
            self.usage[key] += int(resp.usage.get(key, 0))
        self._step(
            "llm",
            started,
            iteration=iteration,
            finish_reason=resp.finish_reason,
            requested_tools=[c.name for c in resp.tool_calls],
            content_chars=len(resp.content or ""),
            usage=resp.usage,
        )
        if resp.tool_calls and self.streamed_text:
            await self.emit("answer_reset", {})  # pre-tool chatter is not the answer
        return resp

    async def _execute_one(self, call: ToolCall, budget_left: bool) -> tuple[ToolCall, ToolExecution, bool]:
        started_at = datetime.now(UTC)
        tool = self.o.mcp.get_tool(call.name)
        await self.emit(
            "tool_start",
            {
                "call_id": call.id,
                "tool": call.name,
                "server_id": tool.server_id if tool else None,
                "arguments": call.arguments,
            },
        )
        cache_key = f"{call.name}:{json.dumps(call.arguments, sort_keys=True)}"
        cached = False
        if call.parse_error is not None:
            ex = ToolExecution(
                call_id=call.id, qualified_name=call.name, server_id=tool.server_id if tool else None,
                tool_name=tool.tool_name if tool else None, arguments=None, status=ToolStatus.INVALID_ARGUMENTS,
                error=call.parse_error, started_at=started_at, finished_at=datetime.now(UTC),
            )  # fmt: skip
        elif not budget_left:
            ex = ToolExecution(
                call_id=call.id, qualified_name=call.name, server_id=tool.server_id if tool else None,
                tool_name=tool.tool_name if tool else None, arguments=call.arguments, status=ToolStatus.BUDGET_EXCEEDED,
                error="Tool-call budget exhausted for this request.", started_at=started_at, finished_at=datetime.now(UTC),
            )  # fmt: skip
        elif cache_key in self.cache:
            ex = self.cache[cache_key].model_copy(update={"call_id": call.id, "duration_ms": 0.0})
            cached = True
        else:
            ex = await self.o.mcp.call_tool(call.name, call.arguments, call_id=call.id)
            if ex.status is ToolStatus.SUCCESS:
                self.cache[cache_key] = ex
        return call, ex, cached

    async def _execute_calls(self, calls: list[ToolCall]) -> list[ChatMessage]:
        real_calls = sum(1 for s in self.summaries if not s.cached and s.status != ToolStatus.BUDGET_EXCEEDED)
        remaining = self.o.limits.max_tool_calls - real_calls
        plans = [(c, i < remaining) for i, c in enumerate(calls)]
        started = time.perf_counter()
        if self.o.limits.execution_mode == "concurrent" and len(plans) > 1:
            outcomes = await asyncio.gather(*(self._execute_one(c, ok) for c, ok in plans))
        else:
            outcomes = [await self._execute_one(c, ok) for c, ok in plans]

        messages: list[ChatMessage] = []
        for call, ex, cached in outcomes:
            self.executions.append(ex)
            summary = ToolCallSummary(
                call_id=call.id, tool=call.name, server_id=ex.server_id, arguments=ex.arguments, status=ex.status.value,
                duration_ms=ex.duration_ms, attempts=ex.attempts, error=ex.error, cached=cached,
            )  # fmt: skip
            self.summaries.append(summary)
            self._step(
                "tool", started, call_id=call.id, tool=call.name, server_id=ex.server_id, arguments=ex.arguments,
                status=ex.status.value, attempts=ex.attempts, tool_duration_ms=ex.duration_ms, error=ex.error,
                cached=cached, result_preview=json.dumps(ex.data, default=str)[:1500] if ex.data else ex.text,
            )  # fmt: skip
            await self.emit("tool_end", summary.model_dump())
            if ex.status in FAILURE_STATUSES:
                self.warnings.append(f"{self.o.mcp.server_name(ex.server_id)}: {ex.error}")
            payload: dict[str, Any] = (
                ex.data if ex.status is ToolStatus.SUCCESS and ex.data is not None
                else {"result": ex.text} if ex.status is ToolStatus.SUCCESS
                else {"error": ex.error, "status": ex.status.value}
            )  # fmt: skip
            messages.append(
                ChatMessage(
                    role="tool",
                    tool_call_id=call.id,
                    content=prompts.wrap_tool_result(
                        call.name, ex.status.value, payload, self.o.limits.max_tool_result_chars
                    ),
                )
            )
        return messages

    # ------------------------------------------------------------------ main loop
    async def execute(self) -> AgentResult:
        self.o.traces.put(self.trace)
        await self.emit(
            "start", {"trace_id": self.trace.trace_id, "provider": self.o.llm.name, "model": self.o.llm.model}
        )

        started = time.perf_counter()
        await self.o.mcp.ensure_fresh()
        states = self.o.mcp.server_states
        unavailable = [s.name for s in states if s.status is ServerStatus.UNAVAILABLE]
        tools = self.o.tool_specs()
        self._step("discovery", started, tools=[t.name for t in tools], servers={s.id: s.status.value for s in states})
        await self.emit(
            "discovery", {"tool_count": len(tools), "servers": [{"id": s.id, "status": s.status.value} for s in states]}
        )
        for name in unavailable:
            self.warnings.append(f"{name} is currently unavailable.")

        messages = [
            ChatMessage(role="system", content=prompts.system_prompt(self.o._clock(), unavailable)),
            ChatMessage(role="user", content=self.query),
        ]
        answer: str | None = None
        error_code: str | None = None
        iteration = 0
        nudged_malformed = nudged_empty = False
        try:
            while iteration < self.o.limits.max_iterations:
                iteration += 1
                try:
                    resp = await self._call_llm(messages, tools, iteration, allow_tools=True)
                except LLMToolCallFormatError:
                    if nudged_malformed:
                        raise
                    nudged_malformed = True
                    self.warnings.append("The model produced a malformed tool call; retried once.")
                    messages.append(ChatMessage(role="system", content=prompts.MALFORMED_RETRY))
                    continue
                if not resp.tool_calls:
                    if resp.content and resp.content.strip():
                        answer = resp.content.strip()
                        break
                    if nudged_empty:
                        error_code = "llm_empty_response"
                        break
                    nudged_empty = True
                    messages.append(ChatMessage(role="system", content=prompts.EMPTY_RETRY))
                    continue
                messages.append(ChatMessage(role="assistant", content=resp.content, tool_calls=resp.tool_calls))
                messages.extend(await self._execute_calls(resp.tool_calls))

            if answer is None and error_code is None:
                # Iteration budget reached while the model still wanted tools: force a final answer.
                self.warnings.append("Reached the agent iteration limit; answered with the information gathered.")
                messages.append(ChatMessage(role="system", content=prompts.BUDGET_EXHAUSTED))
                resp = await self._call_llm(messages, tools, iteration + 1, allow_tools=False)
                if resp.content and resp.content.strip():
                    answer = resp.content.strip()
                else:
                    error_code = "max_iterations"
        except LLMError as exc:
            error_code = exc.code
            await self.emit("error", {"code": exc.code, "message": str(exc)})
            self.warnings.append(str(exc))

        return await self._finish(answer, error_code, iteration)

    async def _finish(self, answer: str | None, error_code: str | None, iteration: int) -> AgentResult:
        citations = collect_citations(self.executions)
        names = {s.id: s.name for s in self.o.mcp.server_states}
        sources = collect_sources(self.executions, names)
        failed = any(ex.status in FAILURE_STATUSES for ex in self.executions)
        searched_docs = [
            ex
            for ex in self.executions
            if ex.status is ToolStatus.SUCCESS and ex.data is not None and "passages" in ex.data
        ]
        insufficient = bool(searched_docs) and not citations
        if answer is None:
            answer = {
                "llm_rate_limited": "The language model is rate-limited right now. Please try again in a minute.",
                "llm_auth_failed": "The language model provider rejected the configured credentials.",
                "llm_not_configured": "The language model provider is not configured.",
                "max_iterations": "I couldn't finish within the step limit for this request.",
            }.get(error_code or "", "I wasn't able to produce an answer for this request.")
            if sources:
                answer += " Partial tool results are listed below."
        # "partial": at least one executed tool call failed (timeout/unreachable/protocol); other results kept.
        status = "error" if error_code else "partial" if failed else "ok"
        result = AgentResult(
            trace_id=self.trace.trace_id,
            query=self.query,
            answer=answer,
            status=status,  # type: ignore[arg-type]
            error_code=error_code,
            insufficient_evidence=insufficient,
            citations=citations,
            sources=sources,
            tool_calls=self.summaries,
            warnings=list(dict.fromkeys(self.warnings)),
            citation_check=verify_citations(answer, citations),
            provider=self.o.llm.name,
            model=self.o.llm.model,
            iterations=iteration,
            latency_ms=round((time.perf_counter() - self.t0) * 1000, 1),
            usage=self.usage,
        )
        self.trace.status = result.status
        self.trace.latency_ms = result.latency_ms
        self.trace.result = result
        self.o.traces.finish(self.trace)
        await self.emit("final", result.model_dump(mode="json"))
        return result
