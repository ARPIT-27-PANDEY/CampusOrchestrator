"""Request/response schemas for the REST API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from ..mcp.models import ServerState


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, description="The user's question.")
    simulate_failures: dict[str, Literal["down", "timeout"]] | None = Field(
        default=None,
        description="Dev-only fault injection per server id (requires ALLOW_FAULT_INJECTION=true).",
    )

    @field_validator("message")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("message must not be blank")
        return v


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str | None = None
    details: list[dict[str, Any]] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class SourcesResponse(BaseModel):
    servers: list[ServerState]
    tool_count: int
    checked_at: datetime


class ToolInfo(BaseModel):
    name: str
    server_id: str
    tool_name: str
    description: str
    input_schema: dict[str, Any]
    discovered_at: datetime


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    environment: str
    llm: dict[str, Any]
    mcp: dict[str, int]
    time: datetime
    campus_time: str | None = Field(default=None, description="Current campus-local time (ISO, with offset).")
    access_mode: str | None = None


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=200)


class SessionInfo(BaseModel):
    access_mode: Literal["open", "password"]
    authenticated: bool
    expires_at: datetime | None = None


class EvalRunInfo(BaseModel):
    run_id: str
    kind: Literal["agent", "retrieval"]
    generated_at: str | None = None
    dataset: str | None = None
    provider: str | None = None
    model: str | None = None
    transport: str | None = None
    retriever: str | None = None
    repeat: int | None = None
    pass_rate: float | None = None
    cases: int | None = None
    legacy: bool = False


class TraceListItem(BaseModel):
    trace_id: str
    created_at: datetime
    query: str
    status: str
    latency_ms: float
    tool_calls: int
    provider: str
