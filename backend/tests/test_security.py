"""Access control, CSRF/Origin checks, rate limiting, proxy headers, cancellation and fail-closed config."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.llm.base import LLMResponse
from app.llm.mock import MockProvider
from app.main import create_app
from app.security import COOKIE_NAME, RateLimiter, SessionSigner, client_ip
from app.state import build_state

from .fakes import FakeConnector, academics_server, configs, library_server

ORIGIN = "http://localhost:3000"
PASSWORD = "correct horse battery"
SECRET = "s" * 40


def make_app(llm: Any = None, **overrides: Any) -> Any:
    base: dict[str, Any] = {
        "llm_provider": "mock",
        "cors_origins": ORIGIN,
        "access_mode": "password",
        "access_password": PASSWORD,
        "session_secret": SECRET,
    }
    settings = Settings(_env_file=None, **{**base, **overrides})  # type: ignore[call-arg]
    servers = {"library": library_server(), "academics": academics_server()}
    state = build_state(
        settings, connector=FakeConnector(servers), llm=llm or MockProvider(), servers=configs(*servers)
    )
    return create_app(state=state)


def login(client: TestClient, password: str = PASSWORD) -> httpx.Response:
    return client.post("/api/auth/login", json={"password": password}, headers={"Origin": ORIGIN})


def ask(
    client: TestClient, message: str = "Is Introduction to Algorithms available?", **headers: str
) -> httpx.Response:
    return client.post("/api/chat", json={"message": message}, headers={"Origin": ORIGIN, **headers})


# ---------------------------------------------------------------------------------------------- configuration
def test_production_fails_closed_without_access_control() -> None:
    with pytest.raises(ValidationError, match="Refusing to start"):
        Settings(_env_file=None, app_env="production", access_mode="open")  # type: ignore[call-arg]
    ok = Settings(_env_file=None, app_env="production", access_mode="open", allow_open_access=True)  # type: ignore[call-arg]
    assert ok.allow_open_access


@pytest.mark.parametrize(("password", "secret"), [("short", SECRET), (PASSWORD, "too-short"), (None, SECRET)])
def test_password_mode_requires_strong_settings(password: str | None, secret: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, access_mode="password", access_password=password, session_secret=secret)  # type: ignore[call-arg]


def test_production_defaults_minimise_retained_content() -> None:
    s = Settings(
        _env_file=None, app_env="production", access_mode="password", access_password=PASSWORD, session_secret=SECRET
    )  # type: ignore[call-arg]
    assert s.secure_cookies and not s.keep_query_text and not s.keep_tool_payloads


# ---------------------------------------------------------------------------------------------- sessions
def test_unauthenticated_chat_and_traces_are_rejected() -> None:
    with TestClient(make_app()) as client:
        assert ask(client).status_code == 401
        assert client.get("/api/traces").status_code == 401
        assert client.get("/api/auth/session").json() == {
            "access_mode": "password",
            "authenticated": False,
            "expires_at": None,
        }
        assert client.get("/api/health").status_code == 200  # public


def test_login_sets_secure_cookie_and_unlocks_chat() -> None:
    with TestClient(make_app(cookie_secure=True), base_url="https://testserver") as client:
        assert login(client, "wrong password").status_code == 401
        resp = login(client)
        assert resp.status_code == 200 and resp.json()["authenticated"] is True
        cookie = resp.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=strict" in cookie and "secure" in cookie and "max-age=" in cookie
        assert ask(client).status_code == 200
        assert client.get("/api/traces").status_code == 200
        out = client.post("/api/auth/logout", headers={"Origin": ORIGIN})
        assert out.status_code == 200 and COOKIE_NAME in out.headers["set-cookie"]
        client.cookies.clear()
        assert ask(client).status_code == 401


def test_password_is_never_echoed_or_sent_to_the_client() -> None:
    with TestClient(make_app()) as client:
        resp = login(client, "wrong password")
        assert PASSWORD not in resp.text and "wrong password" not in resp.text


def test_expired_and_tampered_sessions_are_rejected() -> None:
    signer = SessionSigner(SECRET, 3600)
    token, _ = signer.issue(now=time.time() - 7200)  # expired an hour ago
    assert signer.verify(token) is None
    good, _ = signer.issue()
    assert signer.verify(good) is not None
    head, payload, sig = good.split(".")
    assert signer.verify(f"{head}.{payload}.{sig[:-2]}AA") is None
    assert SessionSigner("x" * 40, 3600).verify(good) is None  # signed with another secret
    with TestClient(make_app()) as client:
        client.cookies.set(COOKIE_NAME, token)
        assert ask(client).status_code == 401


# ---------------------------------------------------------------------------------------------- CSRF / Origin
def test_cross_origin_and_cross_site_posts_are_rejected() -> None:
    with TestClient(make_app()) as client:
        login(client)
        assert (
            client.post("/api/chat", json={"message": "hi"}, headers={"Origin": "https://evil.example"}).status_code
            == 403
        )
        assert ask(client, **{"Sec-Fetch-Site": "cross-site"}).status_code == 403
        bad_login = client.post(
            "/api/auth/login", json={"password": PASSWORD}, headers={"Origin": "https://evil.example"}
        )
        assert bad_login.status_code == 403


# ---------------------------------------------------------------------------------------------- abuse prevention
def test_chat_rate_limit_returns_429_with_retry_after() -> None:
    with TestClient(make_app(chat_rate_per_minute=1, chat_burst=2)) as client:
        login(client)
        codes = [ask(client, "hello").status_code for _ in range(3)]
        assert codes[:2] == [200, 200] and codes[2] == 429
        last = ask(client, "hello")
        assert last.status_code == 429 and int(last.headers["Retry-After"]) >= 1
        metrics = client.get("/api/metrics").json()["counters"]
        assert metrics["chat_rate_limited"] >= 2


def test_login_is_rate_limited() -> None:
    with TestClient(make_app(login_rate_per_minute=3)) as client:
        codes = [login(client, "bad password").status_code for _ in range(5)]
        assert codes[:3] == [401, 401, 401] and 429 in codes[3:]


def test_oversized_bodies_and_queries_are_rejected() -> None:
    with TestClient(make_app(max_request_bytes=200)) as client:
        login(client)
        assert ask(client, "x" * 500).status_code == 413
    with TestClient(make_app(max_query_chars=20)) as client:
        login(client)
        assert ask(client, "y" * 50).status_code == 422


def test_rate_limiter_refills_over_time() -> None:
    lim = RateLimiter(rate_per_minute=60, burst=1)
    assert lim.check("k", now=0.0) == (True, 0.0)
    allowed, retry = lim.check("k", now=0.1)
    assert not allowed and 0 < retry <= 1
    assert lim.check("k", now=1.2)[0]


class _Req:
    def __init__(self, peer: str, xff: str | None) -> None:
        self.client = type("C", (), {"host": peer})()
        self.headers = {"x-forwarded-for": xff} if xff else {}


def test_forwarded_for_is_only_trusted_for_configured_hops() -> None:
    spoofed = _Req("10.0.0.5", "6.6.6.6, 203.0.113.9")
    assert client_ip(spoofed, 0) == "10.0.0.5"  # no trusted proxies: header ignored
    assert client_ip(spoofed, 1) == "203.0.113.9"  # one trusted proxy: its entry, not the client-supplied one
    assert client_ip(_Req("10.0.0.5", None), 1) == "10.0.0.5"


# ---------------------------------------------------------------------------------------------- cancellation
class _SlowLLM:
    name = "slow"
    model = "slow"

    async def complete(self, *args: Any, **kwargs: Any) -> LLMResponse:
        await asyncio.sleep(30)
        return LLMResponse(content="late", tool_calls=[], finish_reason="stop", model="slow")


async def test_abandoned_stream_releases_its_slot_and_cancels_the_run() -> None:
    # A real socket is needed: httpx's in-process ASGITransport buffers the whole response, so it
    # cannot simulate a browser that goes away mid-stream.
    import socket

    import uvicorn

    app = make_app(llm=_SlowLLM(), access_mode="open", max_concurrent_chats=1)
    state = app.state.campus
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on"))
    serve = asyncio.create_task(server.serve())
    try:
        while not server.started:  # noqa: ASYNC110 - uvicorn exposes only a flag, not an event
            await asyncio.sleep(0.05)
        started = time.perf_counter()
        async with (
            httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client,
            client.stream("POST", "/api/chat/stream", json={"message": "hello"}, headers={"Origin": ORIGIN}) as r,
        ):
            assert r.status_code == 200
            async for line in r.aiter_lines():
                if line.startswith("event: llm_start"):
                    break  # the browser goes away while the model is "thinking"
        for _ in range(100):
            if state.chat_slots._value == 1 and state.guard.metrics.snapshot().get("cancelled_on_disconnect"):
                break
            await asyncio.sleep(0.05)
        assert state.chat_slots._value == 1
        assert state.guard.metrics.snapshot().get("cancelled_on_disconnect", 0) >= 1  # the run was cancelled
        assert time.perf_counter() - started < 15  # it did not wait for the 30 s model call
    finally:
        server.should_exit = True
        await serve


async def test_busy_server_rejects_with_429_instead_of_queueing_forever() -> None:
    app = make_app(llm=_SlowLLM(), access_mode="open", max_concurrent_chats=1)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=10) as client:
        first = asyncio.create_task(client.post("/api/chat", json={"message": "one"}, headers={"Origin": ORIGIN}))
        await asyncio.sleep(0.2)
        second = await client.post("/api/chat", json={"message": "two"}, headers={"Origin": ORIGIN})
        assert second.status_code == 429 and "Retry-After" in second.headers
        first.cancel()
