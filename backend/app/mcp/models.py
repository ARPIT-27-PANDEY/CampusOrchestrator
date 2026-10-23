"""Data types shared by the MCP client manager and the orchestrator."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

TOOL_NAME_SEPARATOR = "__"


class ServerStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    NOT_CONFIGURED = "not_configured"
    UNKNOWN = "unknown"


class ToolStatus(StrEnum):
    SUCCESS = "success"
    TOOL_ERROR = "tool_error"  # the server ran the tool and reported an error (e.g. not found)
    INVALID_ARGUMENTS = "invalid_arguments"
    UNKNOWN_TOOL = "unknown_tool"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    PROTOCOL_ERROR = "protocol_error"
    BUDGET_EXCEEDED = "budget_exceeded"


TRANSIENT_STATUSES = {ToolStatus.TIMEOUT, ToolStatus.UNAVAILABLE}
FAILURE_STATUSES = {ToolStatus.TIMEOUT, ToolStatus.UNAVAILABLE, ToolStatus.PROTOCOL_ERROR}


class RegisteredTool(BaseModel):
    qualified_name: str = Field(description="LLM-facing name: <server_id>__<tool_name>")
    server_id: str
    tool_name: str
    description: str
    input_schema: dict[str, Any]
    discovered_at: datetime


class ServerState(BaseModel):
    id: str
    name: str
    description: str | None = None
    url: str | None = None
    status: ServerStatus = ServerStatus.UNKNOWN
    error: str | None = None
    last_checked: datetime | None = None
    latency_ms: float | None = None
    protocol_version: str | None = None
    server_version: str | None = None
    tool_names: list[str] = Field(default_factory=list)
    data_mode: str | None = Field(default=None, description="demo/imported/live as reported by the server's /health.")
    source_detail: dict[str, Any] | None = None


class ToolExecution(BaseModel):
    call_id: str
    qualified_name: str
    server_id: str | None
    tool_name: str | None
    arguments: dict[str, Any] | None
    status: ToolStatus
    data: dict[str, Any] | None = None
    text: str | None = None
    error: str | None = None
    attempts: int = 0
    duration_ms: float = 0.0
    started_at: datetime
    finished_at: datetime | None = None
