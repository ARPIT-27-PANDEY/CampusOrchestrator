"""Provider-neutral chat types and the ``LLMProvider`` protocol.

The orchestrator only speaks these types. Each adapter converts them to its
own wire format, so swapping the model never touches MCP or orchestration code.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Role = Literal["system", "user", "assistant", "tool"]
TextCallback = Callable[[str], Awaitable[None]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments_raw: str
    arguments: dict[str, Any] | None = None
    parse_error: str | None = None

    @classmethod
    def parse(cls, call_id: str, name: str, raw: str | None) -> ToolCall:
        text = (raw or "").strip() or "{}"
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            return cls(call_id, name, text, None, f"Arguments are not valid JSON: {exc.msg}")
        if not isinstance(value, dict):
            return cls(call_id, name, text, None, "Arguments must be a JSON object.")
        return cls(call_id, name, text, value, None)


@dataclass
class ChatMessage:
    role: Role
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall]
    finish_reason: str | None
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    streamed: bool = False


class LLMError(Exception):
    """Base class for provider failures. ``code`` is stable and safe to show to clients."""

    code = "llm_error"
    retryable = False

    def __init__(self, message: str, *, retry_after_s: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class LLMConfigError(LLMError):
    code = "llm_not_configured"


class LLMAuthError(LLMError):
    code = "llm_auth_failed"


class LLMRateLimitError(LLMError):
    code = "llm_rate_limited"
    retryable = True


class LLMTimeoutError(LLMError):
    code = "llm_timeout"
    retryable = True


class LLMUnavailableError(LLMError):
    code = "llm_unavailable"
    retryable = True


class LLMBadRequestError(LLMError):
    code = "llm_bad_request"


class LLMToolCallFormatError(LLMError):
    """The model produced a tool call the provider could not parse (Groq returns HTTP 400)."""

    code = "llm_malformed_tool_call"


class LLMProvider(Protocol):
    name: str
    model: str

    async def complete(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSpec],
        *,
        on_text: TextCallback | None = None,
        allow_tools: bool = True,
    ) -> LLMResponse: ...
