"""Application settings loaded from environment variables (and an optional .env file)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_json: bool = False
    campus_timezone: str = "Asia/Kolkata"  # IANA name; decides "today" for prompts, menus and events

    # --- LLM -------------------------------------------------------------------
    llm_provider: Literal["groq", "mock"] = "mock"
    groq_api_key: SecretStr | None = None
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "openai/gpt-oss-120b"
    groq_temperature: float = Field(default=0.2, gt=0, le=2)  # Groq maps 0 to 1e-8; keep it explicit
    groq_max_completion_tokens: int = Field(default=1024, ge=64, le=65536)
    groq_reasoning_effort: Literal["low", "medium", "high"] | None = "low"
    groq_include_reasoning: bool = False
    groq_stream: bool = True
    groq_timeout_s: float = 30.0
    groq_max_retries: int = Field(default=2, ge=0, le=5)

    # --- MCP -------------------------------------------------------------------
    mcp_servers_file: Path = BACKEND_DIR / "config" / "mcp_servers.json"
    mcp_allowed_hosts: str = "localhost,127.0.0.1,library-mcp,events-mcp,cafeteria-mcp,academics-mcp"
    tool_registry_ttl_s: float = 300.0
    unavailable_recheck_s: float = 15.0

    # --- Orchestration budgets -------------------------------------------------
    max_agent_iterations: int = Field(default=5, ge=1, le=20)
    max_tool_calls: int = Field(default=8, ge=1, le=50)
    tool_timeout_s: float = Field(default=8.0, gt=0, le=120)
    tool_max_retries: int = Field(default=1, ge=0, le=5)
    tool_execution_mode: Literal["sequential", "concurrent"] = "sequential"
    max_tool_result_chars: int = Field(default=3500, ge=500, le=50000)
    max_query_chars: int = Field(default=2000, ge=10, le=20000)
    max_request_bytes: int = 64 * 1024
    max_concurrent_chats: int = Field(default=4, ge=1, le=100)

    # --- API -------------------------------------------------------------------
    cors_origins: str = "http://localhost:3000"  # also the allowed Origins for cookie-authenticated POSTs
    trace_capacity: int = 200
    trace_log_path: Path | None = None  # optional append-only JSONL export (same privacy rules as the store)
    eval_report_path: Path = BACKEND_DIR.parent / "evals" / "reports" / "latest.json"
    allow_fault_injection: bool = False

    # --- Access control (see docs/security.md) ---------------------------------------
    # open: no login (local development). password: shared-password gate with signed, expiring,
    # HttpOnly session cookies. Production refuses "open" unless allow_open_access is set explicitly.
    access_mode: Literal["open", "password"] = "open"
    access_password: SecretStr | None = None
    session_secret: SecretStr | None = None  # >= 32 random characters; signs session cookies
    session_ttl_s: int = Field(default=12 * 3600, ge=300, le=7 * 24 * 3600)
    cookie_secure: bool | None = None  # default: true in production
    allow_open_access: bool = False  # explicit, documented override for a public demo without a password
    trusted_proxy_hops: int = Field(default=0, ge=0, le=5)  # proxies whose X-Forwarded-For entries are trusted

    # --- Abuse prevention ------------------------------------------------------------
    chat_rate_per_minute: float = Field(default=10.0, gt=0, le=600)
    chat_burst: int = Field(default=5, ge=1, le=100)
    login_rate_per_minute: float = Field(default=5.0, gt=0, le=600)
    read_rate_per_minute: float = Field(default=120.0, gt=0, le=10000)  # traces, evals, sources

    # --- Trace persistence and privacy -------------------------------------------------
    trace_backend: Literal["memory", "sqlite"] = "memory"
    trace_db_path: Path = BACKEND_DIR / "data" / "traces.sqlite3"
    trace_retention_hours: float = Field(default=24.0, gt=0, le=24 * 365)
    trace_store_query_text: bool | None = None  # default: true in development, false in production
    trace_store_tool_payloads: bool | None = None  # tool arguments/results; same default
    trace_redact: bool = True  # e-mails, phone numbers, API keys and tokens are always masked when stored

    @field_validator("campus_timezone")
    @classmethod
    def _valid_timezone(cls, v: str) -> str:
        from .campus_time import load_timezone

        return load_timezone(v).key  # raises ValueError for unknown zones

    @field_validator("groq_api_key", "access_password", "session_secret", mode="before")
    @classmethod
    def _empty_key_is_none(cls, v: object) -> object:
        return None if v in ("", None) else v

    @model_validator(mode="after")
    def _security_checks(self) -> Settings:
        if self.access_mode == "password":
            pw = self.access_password.get_secret_value() if self.access_password else ""
            secret = self.session_secret.get_secret_value() if self.session_secret else ""
            if len(pw) < 8:
                raise ValueError("ACCESS_MODE=password requires ACCESS_PASSWORD (at least 8 characters).")
            if len(secret) < 32:
                raise ValueError("ACCESS_MODE=password requires SESSION_SECRET (at least 32 random characters).")
        elif self.app_env == "production" and not self.allow_open_access:
            raise ValueError(
                "Refusing to start: APP_ENV=production with ACCESS_MODE=open would expose an unrestricted, "
                "quota-consuming API. Set ACCESS_MODE=password (with ACCESS_PASSWORD and SESSION_SECRET) or, for a "
                "deliberate public demo, ALLOW_OPEN_ACCESS=true."
            )
        return self

    @property
    def secure_cookies(self) -> bool:
        return self.app_env == "production" if self.cookie_secure is None else self.cookie_secure

    @property
    def keep_query_text(self) -> bool:
        return self.app_env != "production" if self.trace_store_query_text is None else self.trace_store_query_text

    @property
    def keep_tool_payloads(self) -> bool:
        return (
            self.app_env != "production" if self.trace_store_tool_payloads is None else self.trace_store_tool_payloads
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_host_set(self) -> set[str]:
        return {h.strip().lower() for h in self.mcp_allowed_hosts.split(",") if h.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
