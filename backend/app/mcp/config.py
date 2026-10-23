"""Allowlisted MCP server configuration."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, Field

_ID = re.compile(r"^[a-z][a-z0-9_]{1,30}$")


class ServerConfig(BaseModel):
    id: str
    name: str
    url: str | None = None
    description: str | None = None
    enabled: bool = True
    timeout_s: float | None = Field(default=None, gt=0, le=120)

    @property
    def configured(self) -> bool:
        return bool(self.enabled and self.url)


class ServerConfigError(ValueError):
    pass


def validate_server_url(url: str, allowed_hosts: set[str]) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ServerConfigError(f"MCP server URL must be http(s): {url!r}")
    if not parsed.hostname or parsed.hostname.lower() not in allowed_hosts:
        raise ServerConfigError(
            f"MCP server host {parsed.hostname!r} is not in MCP_ALLOWED_HOSTS; refusing to connect."
        )
    if parsed.username or parsed.password:
        raise ServerConfigError("Credentials must not be embedded in MCP server URLs.")


def load_server_configs(path: Path, allowed_hosts: set[str], env: dict[str, str] | None = None) -> list[ServerConfig]:
    """Load server definitions; ``MCP_<ID>_URL`` overrides a URL and an empty value disables it."""
    environ = os.environ if env is None else env
    raw = json.loads(path.read_text(encoding="utf-8"))
    configs: list[ServerConfig] = []
    seen: set[str] = set()
    for entry in raw.get("servers", []):
        cfg = ServerConfig.model_validate(entry)
        if not _ID.match(cfg.id):
            raise ServerConfigError(f"Invalid server id {cfg.id!r} (lowercase letters, digits, underscore).")
        if cfg.id in seen:
            raise ServerConfigError(f"Duplicate server id {cfg.id!r}.")
        seen.add(cfg.id)
        override = environ.get(f"MCP_{cfg.id.upper()}_URL")
        if override is not None:
            cfg = cfg.model_copy(update={"url": override.strip() or None})
        if cfg.url:
            validate_server_url(cfg.url, allowed_hosts)
        configs.append(cfg)
    return configs
