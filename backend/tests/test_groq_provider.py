"""Groq adapter tests against mocked HTTP (no network, no API key)."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from openai import AsyncOpenAI

from app.llm.base import (
    ChatMessage,
    LLMAuthError,
    LLMConfigError,
    LLMRateLimitError,
    LLMToolCallFormatError,
    ToolCall,
    ToolSpec,
)
from app.llm.groq import GroqProvider, to_openai_messages

URL = "https://api.groq.com/openai/v1/chat/completions"
TOOLS = [
    ToolSpec("library__search_books", "Search books", {"type": "object", "properties": {"query": {"type": "string"}}})
]
MSGS = [ChatMessage(role="system", content="sys"), ChatMessage(role="user", content="Is CLRS available?")]


def provider(stream: bool = False) -> GroqProvider:
    # openai>=3 defaults to httpx2; inject a legacy httpx client so respx can intercept requests.
    client = AsyncOpenAI(
        api_key="gsk_test_not_real",
        base_url="https://api.groq.com/openai/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(),
    )
    return GroqProvider(api_key=None, model="openai/gpt-oss-120b", stream=stream, client=client)


def completion(message: dict[str, object], finish: str = "stop") -> dict[str, object]:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1,
        "model": "openai/gpt-oss-120b",
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
    }


def test_requires_api_key() -> None:
    with pytest.raises(LLMConfigError):
        GroqProvider(api_key=None, model="openai/gpt-oss-120b")


@respx.mock
async def test_request_shape_and_tool_call_parsing() -> None:
    route = respx.post(URL).mock(
        return_value=httpx.Response(
            200,
            json=completion(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "library__search_books", "arguments": '{"query":"CLRS"}'},
                        }
                    ],
                },
                "tool_calls",
            ),
        )
    )
    resp = await provider().complete(MSGS, TOOLS)
    body = json.loads(route.calls[0].request.content)
    assert body["model"] == "openai/gpt-oss-120b"
    assert body["tools"][0]["function"]["name"] == "library__search_books"
    assert body["tool_choice"] == "auto"
    assert "parallel_tool_calls" not in body  # not supported by gpt-oss on Groq
    assert body["reasoning_effort"] == "low" and body["include_reasoning"] is False
    assert route.calls[0].request.headers["authorization"] == "Bearer gsk_test_not_real"
    assert resp.tool_calls[0].arguments == {"query": "CLRS"}
    assert resp.usage["prompt_tokens"] == 120


def test_tool_messages_omit_unsupported_name_field() -> None:
    msgs = [
        ChatMessage(
            role="assistant", tool_calls=[ToolCall("c1", "library__search_books", '{"query":"x"}', {"query": "x"})]
        ),
        ChatMessage(role="tool", tool_call_id="c1", content="<tool_result>{}</tool_result>"),
    ]
    out = to_openai_messages(msgs)
    assert out[1] == {"role": "tool", "tool_call_id": "c1", "content": "<tool_result>{}</tool_result>"}
    assert all("name" not in m for m in out)


@respx.mock
async def test_malformed_arguments_are_flagged_not_raised() -> None:
    respx.post(URL).mock(
        return_value=httpx.Response(
            200,
            json=completion(
                {
                    "role": "assistant",
                    "tool_calls": [
                        {"id": "c", "type": "function", "function": {"name": "x", "arguments": "{bad json"}}
                    ],
                },
                "tool_calls",
            ),
        )
    )
    resp = await provider().complete(MSGS, TOOLS)
    assert resp.tool_calls[0].arguments is None and resp.tool_calls[0].parse_error


@respx.mock
async def test_rate_limit_maps_with_retry_after() -> None:
    respx.post(URL).mock(
        return_value=httpx.Response(429, headers={"retry-after": "7"}, json={"error": {"message": "slow down"}})
    )
    with pytest.raises(LLMRateLimitError) as info:
        await provider().complete(MSGS, TOOLS)
    assert info.value.retry_after_s == 7


@respx.mock
async def test_auth_error_message_has_no_secret() -> None:
    respx.post(URL).mock(
        return_value=httpx.Response(401, json={"error": {"message": "Invalid API Key gsk_test_not_real"}})
    )
    with pytest.raises(LLMAuthError) as info:
        await provider().complete(MSGS, TOOLS)
    assert "gsk_" not in str(info.value)


@respx.mock
async def test_tool_use_failed_maps_to_malformed_tool_call() -> None:
    respx.post(URL).mock(
        return_value=httpx.Response(
            400,
            json={
                "error": {
                    "message": "Invalid tool call generated",
                    "type": "invalid_request_error",
                    "code": "tool_use_failed",
                    "failed_generation": "...",
                }
            },
        )
    )
    with pytest.raises(LLMToolCallFormatError):
        await provider().complete(MSGS, TOOLS)


def _sse(chunks: list[dict[str, object]]) -> bytes:
    return b"".join(f"data: {json.dumps(c)}\n\n".encode() for c in chunks) + b"data: [DONE]\n\n"


def _chunk(
    delta: dict[str, object], finish: str | None = None, usage: dict[str, int] | None = None
) -> dict[str, object]:
    return {
        "id": "c",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "openai/gpt-oss-120b",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}] if delta is not None else [],
        **({"usage": usage} if usage else {}),
    }


@respx.mock
async def test_streaming_text_and_tool_call_deltas_are_assembled() -> None:
    body = _sse(
        [
            _chunk({"role": "assistant", "content": "Checking "}),
            _chunk({"content": "now."}),
            _chunk(
                {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_9",
                            "type": "function",
                            "function": {"name": "library__search_books", "arguments": '{"que'},
                        }
                    ]
                }
            ),
            _chunk({"tool_calls": [{"index": 0, "function": {"arguments": 'ry":"CLRS"}'}}]}, finish="tool_calls"),
        ]
    )
    respx.post(URL).mock(return_value=httpx.Response(200, content=body, headers={"content-type": "text/event-stream"}))
    tokens: list[str] = []

    async def on_text(t: str) -> None:
        tokens.append(t)

    resp = await provider(stream=True).complete(MSGS, TOOLS, on_text=on_text)
    assert tokens == ["Checking ", "now."]
    assert resp.streamed and resp.finish_reason == "tool_calls"
    assert resp.tool_calls[0].id == "call_9" and resp.tool_calls[0].arguments == {"query": "CLRS"}


@respx.mock
async def test_streaming_rejected_falls_back_to_non_streaming() -> None:
    route = respx.post(URL).mock(
        side_effect=[
            httpx.Response(400, json={"error": {"message": "stream not supported with tools"}}),
            httpx.Response(200, json=completion({"role": "assistant", "content": "Hello"})),
        ]
    )
    p = provider(stream=True)

    async def on_text(_: str) -> None:
        return None

    resp = await p.complete(MSGS, TOOLS, on_text=on_text)
    assert resp.content == "Hello" and not resp.streamed
    assert json.loads(route.calls[1].request.content).get("stream") in (None, False)


@respx.mock
async def test_allow_tools_false_sends_no_tools() -> None:
    route = respx.post(URL).mock(
        return_value=httpx.Response(200, json=completion({"role": "assistant", "content": "Done"}))
    )
    await provider().complete(MSGS, TOOLS, allow_tools=False)
    assert "tools" not in json.loads(route.calls[0].request.content)
