"""Access control, CSRF/Origin checks, client identity and rate limiting.

* Sessions: ``v1.<base64url(json{sid, exp})>.<base64url(HMAC-SHA256)>`` in an HttpOnly cookie
  (Secure in production, SameSite=Strict). The password check and signature check use
  ``hmac.compare_digest``. Nothing secret is ever sent to the browser bundle.
* CSRF: cookie-authenticated unsafe requests must come from an allowed Origin (CORS_ORIGINS) and
  must not be marked ``Sec-Fetch-Site: cross-site``. CORS itself is not treated as authentication.
* Client identity: the session id when logged in; otherwise the client IP, taken from
  X-Forwarded-For only for the configured number of trusted proxy hops (never blindly).
* Rate limiting: in-memory token buckets per identity. This is per process, NOT a distributed
  limiter: with several instances, use a shared store (e.g. Redis) instead.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request

from .config import Settings

COOKIE_NAME = "campus_session"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


@dataclass(frozen=True)
class Session:
    sid: str
    expires_at: int


class SessionSigner:
    def __init__(self, secret: str, ttl_s: int) -> None:
        self._key = hashlib.sha256(secret.encode()).digest()
        self.ttl_s = ttl_s

    def _sig(self, payload: str) -> str:
        return _b64(hmac.new(self._key, payload.encode(), hashlib.sha256).digest())

    def issue(self, now: float | None = None) -> tuple[str, Session]:
        session = Session(sid=secrets.token_urlsafe(16), expires_at=int((now or time.time()) + self.ttl_s))
        payload = _b64(json.dumps({"sid": session.sid, "exp": session.expires_at}, separators=(",", ":")).encode())
        return f"v1.{payload}.{self._sig(payload)}", session

    def verify(self, token: str | None, now: float | None = None) -> Session | None:
        if not token or token.count(".") != 2:
            return None
        version, payload, sig = token.split(".")
        if version != "v1" or not hmac.compare_digest(sig, self._sig(payload)):
            return None
        try:
            data = json.loads(_unb64(payload))
            session = Session(sid=str(data["sid"]), expires_at=int(data["exp"]))
        except (ValueError, KeyError, TypeError):
            return None
        return session if session.expires_at > (now or time.time()) else None


def password_matches(given: str, expected: str) -> bool:
    # Compare fixed-length digests so the comparison time does not depend on the password length.
    return hmac.compare_digest(hashlib.sha256(given.encode()).digest(), hashlib.sha256(expected.encode()).digest())


def client_ip(request: Request, trusted_hops: int) -> str:
    """The peer address, or the address added by the outermost *trusted* proxy.

    With N trusted proxies in front of the app, the client is the N-th entry from the right of
    X-Forwarded-For. Entries further left are client-controlled and ignored.
    """
    peer = request.client.host if request.client else "unknown"
    if trusted_hops <= 0:
        return peer
    chain = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    return chain[-trusted_hops] if len(chain) >= trusted_hops else peer


def origin_allowed(request: Request, allowed: list[str]) -> tuple[bool, str]:
    if request.method not in UNSAFE_METHODS:
        return True, ""
    if request.headers.get("sec-fetch-site") == "cross-site":
        return False, "Cross-site request rejected."
    origin = request.headers.get("origin")
    if origin is not None and origin not in allowed:
        return False, "Request origin is not allowed."
    return True, ""


@dataclass
class _Bucket:
    tokens: float
    updated: float


@dataclass
class RateLimiter:
    """Token bucket per key: ``rate_per_minute`` sustained, ``burst`` at once. Bounded memory (LRU)."""

    rate_per_minute: float
    burst: int
    max_keys: int = 10000
    _buckets: OrderedDict[str, _Bucket] = field(default_factory=OrderedDict)

    def check(self, key: str, now: float | None = None) -> tuple[bool, float]:
        """Return (allowed, retry_after_seconds)."""
        t = time.monotonic() if now is None else now
        rate = self.rate_per_minute / 60.0
        bucket = self._buckets.get(key) or _Bucket(tokens=float(self.burst), updated=t)
        bucket.tokens = min(float(self.burst), bucket.tokens + (t - bucket.updated) * rate)
        bucket.updated = t
        self._buckets[key] = bucket
        self._buckets.move_to_end(key)
        while len(self._buckets) > self.max_keys:
            self._buckets.popitem(last=False)
        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            return True, 0.0
        return False, round((1.0 - bucket.tokens) / rate, 1)


@dataclass
class Metrics:
    counters: dict[str, int] = field(default_factory=dict)

    def inc(self, name: str) -> None:
        self.counters[name] = self.counters.get(name, 0) + 1

    def snapshot(self) -> dict[str, Any]:
        return dict(sorted(self.counters.items()))


class Guard:
    """Per-application security state built from Settings."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.mode = settings.access_mode
        self.signer = (
            SessionSigner(settings.session_secret.get_secret_value(), settings.session_ttl_s)
            if settings.access_mode == "password" and settings.session_secret
            else None
        )
        self.chat_limiter = RateLimiter(settings.chat_rate_per_minute, settings.chat_burst)
        self.login_limiter = RateLimiter(settings.login_rate_per_minute, max(1, int(settings.login_rate_per_minute)))
        self.read_limiter = RateLimiter(settings.read_rate_per_minute, max(10, int(settings.read_rate_per_minute / 4)))
        self.metrics = Metrics()

    def session(self, request: Request) -> Session | None:
        if self.signer is None:
            return None
        return self.signer.verify(request.cookies.get(COOKIE_NAME))

    def identity(self, request: Request) -> str:
        session = self.session(request)
        if session is not None:
            return f"session:{session.sid}"
        return f"ip:{client_ip(request, self.settings.trusted_proxy_hops)}"

    def cookie_kwargs(self) -> dict[str, Any]:
        return {
            "key": COOKIE_NAME,
            "httponly": True,
            "secure": self.settings.secure_cookies,
            "samesite": "strict",
            "path": "/",
        }
