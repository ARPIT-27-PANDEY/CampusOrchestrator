"""GroqCloud adapter (OpenAI-compatible Chat Completions API).

Uses the ``openai`` Python client pointed at ``https://api.groq.com/openai/v1``.
No OpenAI API key or endpoint is involved. Notes from Groq's documentation:

* ``openai/gpt-oss-120b`` supports tool use but **not** parallel tool calls,
  so ``parallel_tool_calls`` is never sent and the orchestrator executes sequentially.
* ``messages[].name`` is unsupported (HTTP 400), so tool messages omit ``name``.
* Invalid model-generated tool calls come back as HTTP 400 with ``failed_generation``.
* ``reasoning_effort`` (low/medium/high) and ``include_reasoning`` apply to GPT-OSS.
* Rate limits return HTTP 429 with ``retry-after``.
"""

from __future__ import annotations

import logging
from typing import Any

import openai
from openai import AsyncOpenAI

from .base import (
    ChatMessage,
    LLMAuthError,
    LLMBadRequestError,
    LLMConfigError,
    LLMError,
    LLMRateLimitError,
    LLMResponse,
    LLMTimeoutError,
    LLMToolCallFormatError,
    LLMUnavailableError,
    TextCallback,
    ToolCall,
    ToolSpec,
)

log = logging.getLogger("campusos.llm.groq")


def to_openai_messages(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "tool":
            out.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content or ""})
        elif m.role == "assistant" and m.tool_calls:
            out.append(
                {
                    "role": "assistant",
                    "content": m.content or None,
                    "tool_calls": [
                        {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments_raw}}
                        for c in m.tool_calls
                    ],
                }
            )
        else:
            out.append({"role": m.role, "content": m.content or ""})
    return out


def to_openai_tools(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
        for t in tools
    ]


def _retry_after(exc: openai.APIStatusError) -> float | None:
    value = exc.response.headers.get("retry-after") if exc.response is not None else None
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def map_openai_error(exc: Exception) -> LLMError:
    """Translate client exceptions into provider-neutral errors with safe messages (no secrets, no bodies)."""
    if isinstance(exc, openai.AuthenticationError | openai.PermissionDeniedError):
        return LLMAuthError("Groq rejected the API key (check GROQ_API_KEY).")
    if isinstance(exc, openai.RateLimitError):
        return LLMRateLimitError("Groq rate limit reached; try again shortly.", retry_after_s=_retry_after(exc))
    if isinstance(exc, openai.APITimeoutError):
        return LLMTimeoutError("Groq request timed out.")
    if isinstance(exc, openai.APIConnectionError):
        return LLMUnavailableError("Could not reach the Groq API.")
    if isinstance(exc, openai.BadRequestError):
        body = exc.body if isinstance(exc.body, dict) else {}
        err = body.get("error", body) if isinstance(body, dict) else {}
        code = str(err.get("code", "")) if isinstance(err, dict) else ""
        if code == "tool_use_failed" or (isinstance(err, dict) and "failed_generation" in err):
            return LLMToolCallFormatError("The model generated an invalid tool call.")
        return LLMBadRequestError("Groq rejected the request (HTTP 400).")
    if isinstance(exc, openai.InternalServerError):
        return LLMUnavailableError(f"Groq returned HTTP {exc.status_code}.")
    if isinstance(exc, openai.APIStatusError):
        return LLMError(f"Groq returned HTTP {exc.status_code}.")
    return LLMError(f"Unexpected Groq client error ({type(exc).__name__}).")


class GroqProvider:
    name = "groq"

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        base_url: str = "https://api.groq.com/openai/v1",
        temperature: float = 0.2,
        max_completion_tokens: int = 1024,
        reasoning_effort: str | None = "low",
        include_reasoning: bool = False,
        stream: bool = True,
        timeout_s: float = 30.0,
        max_retries: int = 2,
        client: AsyncOpenAI | None = None,
    ) -> None:
        if not api_key and client is None:
            raise LLMConfigError("LLM_PROVIDER=groq requires GROQ_API_KEY.")
        self.model = model
        self._temperature = temperature
        self._max_tokens = max_completion_tokens
        self._reasoning_effort = reasoning_effort
        self._include_reasoning = include_reasoning
        self._stream = stream
        # The OpenAI client retries 429/5xx itself (honouring retry-after) up to max_retries.
        self._client = client or AsyncOpenAI(
            api_key=api_key, base_url=base_url, timeout=timeout_s, max_retries=max_retries
        )

    def _params(self, messages: list[ChatMessage], tools: list[ToolSpec], allow_tools: bool) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": self.model,
            "messages": to_openai_messages(messages),
            "temperature": self._temperature,
            "max_completion_tokens": self._max_tokens,
        }
        if tools and allow_tools:
            params["tools"] = to_openai_tools(tools)
            params["tool_choice"] = "auto"
        extra: dict[str, Any] = {}
        if self.model.startswith("openai/gpt-oss"):
            if self._reasoning_effort:
                params["reasoning_effort"] = self._reasoning_effort
            extra["include_reasoning"] = self._include_reasoning
        if extra:
            params["extra_body"] = extra
        return params

    async def complete(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSpec],
        *,
        on_text: TextCallback | None = None,
        allow_tools: bool = True,
    ) -> LLMResponse:
        params = self._params(messages, tools, allow_tools)
        if self._stream and on_text is not None:
            try:
                return await self._complete_stream(params, on_text)
            except LLMBadRequestError:
                # Groq does not document streaming combined with tools; if a streamed
                # request is rejected, fall back to a non-streamed request for the
                # rest of this process instead of failing the user's query.
                log.warning("Streaming request rejected by Groq; disabling streaming and retrying once")
                self._stream = False
        return await self._complete_once(params)

    async def _complete_once(self, params: dict[str, Any]) -> LLMResponse:
        try:
            resp = await self._client.chat.completions.create(**params)
        except Exception as exc:
            raise map_openai_error(exc) from exc
        if not resp.choices:
            return LLMResponse(content=None, tool_calls=[], finish_reason="empty", model=resp.model or self.model)
        choice = resp.choices[0]
        calls = [
            ToolCall.parse(c.id, c.function.name, c.function.arguments)
            for c in (choice.message.tool_calls or [])
            if getattr(c, "function", None) is not None
        ]
        usage = (
            resp.usage.model_dump(include={"prompt_tokens", "completion_tokens", "total_tokens"}) if resp.usage else {}
        )
        return LLMResponse(
            content=choice.message.content,
            tool_calls=calls,
            finish_reason=choice.finish_reason,
            model=resp.model or self.model,
            usage={k: int(v) for k, v in usage.items() if v is not None},
        )

    async def _complete_stream(self, params: dict[str, Any], on_text: TextCallback) -> LLMResponse:
        content_parts: list[str] = []
        calls: dict[int, dict[str, str]] = {}
        finish_reason: str | None = None
        model = self.model
        usage: dict[str, int] = {}
        try:
            stream = await self._client.chat.completions.create(
                **params, stream=True, stream_options={"include_usage": True}
            )
            async for chunk in stream:
                model = chunk.model or model
                if chunk.usage:
                    usage = {
                        k: int(v)
                        for k, v in chunk.usage.model_dump(
                            include={"prompt_tokens", "completion_tokens", "total_tokens"}
                        ).items()
                        if v is not None
                    }
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta
                if delta and delta.content:
                    content_parts.append(delta.content)
                    await on_text(delta.content)
                for tc in (delta.tool_calls or []) if delta else []:
                    slot = calls.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.function and tc.function.name:
                        slot["name"] += tc.function.name
                    if tc.function and tc.function.arguments:
                        slot["arguments"] += tc.function.arguments
                if choice.finish_reason:
                    finish_reason = choice.finish_reason
        except LLMError:
            raise
        except Exception as exc:
            raise map_openai_error(exc) from exc
        tool_calls = [
            ToolCall.parse(slot["id"] or f"call_{i}", slot["name"], slot["arguments"])
            for i, slot in sorted(calls.items())
        ]
        return LLMResponse(
            content="".join(content_parts) or None,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            model=model,
            usage=usage,
            streamed=True,
        )
