"""Shared fixtures: the four real MCP servers, in-process or as separate HTTP processes."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from mcp import Client

ROOT = Path(__file__).resolve().parents[1]
FIXED_NOW = datetime(2026, 10, 23, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


def inprocess_servers() -> dict[str, Any]:
    """Real MCPServer instances with deterministic clocks (connected in-process via the SDK Client)."""
    from academics_mcp.config import AcademicsSettings
    from academics_mcp.server import build_server as academics
    from academics_mcp.server import build_service
    from cafeteria_mcp.provider import DEMO_MENU_PATH, MenuProvider, menu_from_json
    from cafeteria_mcp.server import build_server as cafeteria
    from events_mcp.provider import DemoEventsProvider
    from events_mcp.server import build_server as events
    from library_mcp.server import build_server as library

    return {
        "library": library(),
        "events": events(DemoEventsProvider(clock=lambda: FIXED_NOW)),
        "cafeteria": cafeteria(
            MenuProvider(
                menu_from_json(DEMO_MENU_PATH), mode="demo", provider="demo-json", today=lambda: date(2026, 10, 23)
            )
        ),
        "academics": academics(build_service(AcademicsSettings(qdrant_path=":memory:"))),
    }


class InProcessConnector:
    def __init__(self, servers: dict[str, Any]) -> None:
        self.servers = servers

    def __call__(self, cfg: Any, timeout_s: float) -> Any:
        return Client(self.servers[cfg.id], read_timeout_seconds=timeout_s, cache=None)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="session")
def http_servers() -> Iterator[dict[str, str]]:
    """Launch each MCP server as its own OS process (python -m <pkg>) on a free port."""
    procs: list[subprocess.Popen[bytes]] = []
    urls: dict[str, str] = {}
    try:
        for sid in ("library", "events", "cafeteria", "academics"):
            port = _free_port()
            env = {
                **os.environ,
                "MCP_PORT": str(port),
                "MCP_HOST": "127.0.0.1",
                "LOG_LEVEL": "warning",
                "QDRANT_PATH": ":memory:",
            }
            procs.append(
                subprocess.Popen(
                    [sys.executable, "-m", f"{sid}_mcp"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
                )
            )
            urls[sid] = f"http://127.0.0.1:{port}"
        deadline = time.time() + 30
        for sid, base in urls.items():
            while True:
                try:
                    if httpx.get(f"{base}/health", timeout=1).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if time.time() > deadline:
                    raise RuntimeError(f"{sid} MCP server did not start")
                time.sleep(0.2)
        yield urls
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            p.wait(timeout=10)
