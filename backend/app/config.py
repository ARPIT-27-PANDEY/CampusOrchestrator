"""Application settings loaded from environment variables (and an optional .env file)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_json: bool = False

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
    cors_origins: str = "http://localhost:3000"
    trace_capacity: int = 200
    trace_log_path: Path | None = None
    eval_report_path: Path = BACKEND_DIR.parent / "evals" / "reports" / "latest.json"
    allow_fault_injection: bool = False

    @field_validator("groq_api_key", mode="before")
    @classmethod
    def _empty_key_is_none(cls, v: object) -> object:
        return None if v in ("", None) else v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_host_set(self) -> set[str]:
        return {h.strip().lower() for h in self.mcp_allowed_hosts.split(",") if h.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
