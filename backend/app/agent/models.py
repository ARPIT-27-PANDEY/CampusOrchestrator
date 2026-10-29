"""Result and trace models returned by the orchestrator (and the API)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class Citation(BaseModel):
    number: int
    citation_id: str
    document_title: str
    source_filename: str
    document_version: str
    page: int
    section: str | None = None
    excerpt: str
    source_url: str | None = Field(default=None, description="Official document URL (https only), if known.")
    doc_status: str | None = Field(default=None, description="current | superseded | uncertain")


class SourceRef(BaseModel):
    server_id: str
    server_name: str
    tool: str
    mode: str | None = Field(default=None, description="demo | imported | live, as reported by the source")
    provider: str | None = None
    source_url: str | None = None
    retrieved_at: str | None = Field(default=None, description="When the service queried its source (UTC).")
    data_as_of: str | None = Field(default=None, description="Upstream update/version date, if the source states it.")
    stale: bool | None = Field(default=None, description="true = out of date; null = cannot be determined.")
    staleness_reason: str | None = None
    note: str | None = None


class ToolCallSummary(BaseModel):
    call_id: str
    tool: str
    server_id: str | None
    arguments: dict[str, Any] | None
    status: str
    duration_ms: float
    attempts: int
    error: str | None = None
    cached: bool = False


class CitationCheck(BaseModel):
    """What is verified - and only that.

    * ``checked``/``unsupported``: every ``[Title, p. N]`` or ``p. N`` in the answer matches a retrieved page.
    * ``numbers_checked``/``unsupported_numbers``: every number in a sentence that carries a citation also
      appears in a retrieved passage from a cited page. Other claims are NOT verified by this check.
    """

    checked: int = 0
    unsupported: list[str] = Field(default_factory=list)
    numbers_checked: int = 0
    unsupported_numbers: list[str] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.unsupported


class AgentResult(BaseModel):
    trace_id: str
    query: str
    answer: str
    status: Literal["ok", "partial", "error"]
    error_code: str | None = None
    insufficient_evidence: bool = False
    citations: list[Citation] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    tool_calls: list[ToolCallSummary] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    citation_check: CitationCheck = Field(default_factory=CitationCheck)
    provider: str
    model: str
    iterations: int = 0
    latency_ms: float = 0.0
    usage: dict[str, int] = Field(default_factory=dict)
    timings: RunTimings | None = None


class RunTimings(BaseModel):
    """Monotonic-clock timings for one run. Wall times are elapsed; *_work_ms are sums that may overlap."""

    wall_ms: float = Field(description="End-to-end server-side time for the run.")
    discovery_ms: float = 0.0
    first_token_ms: float | None = Field(default=None, description="Run start to first streamed answer token.")
    llm_wall_ms: float = Field(default=0.0, description="Elapsed time inside LLM calls (calls are sequential).")
    llm_call_ms: list[float] = Field(default_factory=list)
    tool_wall_ms: float = Field(default=0.0, description="Elapsed time of tool-execution phases.")
    tool_work_ms: float = Field(default=0.0, description="Sum of individual tool durations (overlaps if concurrent).")
    tool_ms_by_tool: dict[str, list[float]] = Field(default_factory=dict)
    tool_retries: int = 0
    cache_hits: int = 0
    orchestration_ms: float = Field(default=0.0, description="wall - discovery - llm wall - tool wall.")


class TraceStep(BaseModel):
    kind: Literal["discovery", "llm", "tool", "note"]
    started_at: datetime
    duration_ms: float = 0.0
    detail: dict[str, Any] = Field(default_factory=dict)


class AgentTrace(BaseModel):
    trace_id: str
    created_at: datetime
    query: str
    provider: str
    model: str
    status: str = "running"
    latency_ms: float = 0.0
    steps: list[TraceStep] = Field(default_factory=list)
    result: AgentResult | None = None


AgentResult.model_rebuild()
