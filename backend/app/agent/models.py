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


class SourceRef(BaseModel):
    server_id: str
    server_name: str
    tool: str
    mode: str | None = Field(default=None, description="demo | imported | live, as reported by the source")
    provider: str | None = None
    data_as_of: str | None = None
    stale: bool | None = None


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
    checked: int = 0
    unsupported: list[str] = Field(default_factory=list)

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
