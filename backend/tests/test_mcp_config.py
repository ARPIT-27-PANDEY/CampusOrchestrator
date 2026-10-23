from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.mcp.config import ServerConfigError, load_server_configs, validate_server_url

ALLOWED = {"localhost", "library-mcp"}


def _write(tmp_path: Path, servers: list[dict[str, object]]) -> Path:
    path = tmp_path / "servers.json"
    path.write_text(json.dumps({"servers": servers}))
    return path


def test_loads_and_applies_env_override(tmp_path: Path) -> None:
    path = _write(tmp_path, [{"id": "library", "name": "Library", "url": "http://localhost:8101/mcp"}])
    cfgs = load_server_configs(path, ALLOWED, env={"MCP_LIBRARY_URL": "http://library-mcp:8101/mcp"})
    assert cfgs[0].url == "http://library-mcp:8101/mcp"
    assert cfgs[0].configured


def test_empty_env_override_marks_not_configured(tmp_path: Path) -> None:
    path = _write(tmp_path, [{"id": "events", "name": "Events", "url": "http://localhost:8102/mcp"}])
    cfgs = load_server_configs(path, ALLOWED, env={"MCP_EVENTS_URL": ""})
    assert not cfgs[0].configured


@pytest.mark.parametrize(
    "url",
    ["http://evil.example.com/mcp", "file:///etc/passwd", "ftp://localhost/mcp", "http://user:pw@localhost/mcp"],
)
def test_rejects_non_allowlisted_or_unsafe_urls(url: str) -> None:
    with pytest.raises(ServerConfigError):
        validate_server_url(url, ALLOWED)


def test_rejects_duplicate_and_invalid_ids(tmp_path: Path) -> None:
    dup = _write(tmp_path, [{"id": "a1", "name": "A"}, {"id": "a1", "name": "B"}])
    with pytest.raises(ServerConfigError):
        load_server_configs(dup, ALLOWED, env={})
    bad = _write(tmp_path, [{"id": "Bad-Id", "name": "A"}])
    with pytest.raises(ServerConfigError):
        load_server_configs(bad, ALLOWED, env={})


def test_repository_config_is_valid() -> None:
    path = Path(__file__).resolve().parents[1] / "config" / "mcp_servers.json"
    cfgs = load_server_configs(path, {"localhost"}, env={})
    assert [c.id for c in cfgs] == ["library", "events", "cafeteria", "academics"]
