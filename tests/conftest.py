"""Shared fixtures: the four real MCP servers, in-process or as separate HTTP processes."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from mcp import Client

ROOT = Path(__file__).resolve().parents[1]
FIXED_NOW = datetime(2026, 10, 23, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


def inprocess_servers(now: datetime = FIXED_NOW) -> dict[str, Any]:
    """Real MCPServer instances sharing one fixed campus clock (connected in-process via the SDK Client)."""
    from academics_mcp.config import DEMO_HANDBOOK_DIR, AcademicsSettings
    from academics_mcp.server import build_server as academics
    from academics_mcp.server import build_service
    from cafeteria_mcp.campus_time import CampusClock as CafeteriaClock
    from cafeteria_mcp.provider import DEMO_MENU_PATH, MenuProvider, menu_from_json
    from cafeteria_mcp.server import build_server as cafeteria
    from events_mcp.campus_time import CampusClock as EventsClock
    from events_mcp.provider import DEMO_DATA_PATH as EVENTS_DATA
    from events_mcp.provider import DemoEventsProvider
    from events_mcp.server import build_server as events
    from library_mcp.campus_time import CampusClock as LibraryClock
    from library_mcp.provider import DEMO_DATA_PATH as LIB_DATA
    from library_mcp.provider import DemoLibraryProvider
    from library_mcp.server import build_server as library

    return {
        "library": library(
            DemoLibraryProvider(LIB_DATA.with_name("demo_books_v1.json"), clock=LibraryClock.fixed(now)), discovery=None
        ),
        "events": events(
            DemoEventsProvider(EVENTS_DATA.with_name("demo_events_v1.json"), clock=EventsClock.fixed(now))
        ),
        "cafeteria": cafeteria(
            MenuProvider(
                menu_from_json(DEMO_MENU_PATH.with_name("demo_menu_v1.json")),
                mode="demo",
                provider="demo-json",
                clock=CafeteriaClock.fixed(now),
            )
        ),
        "academics": academics(
            build_service(AcademicsSettings(handbook_dir=DEMO_HANDBOOK_DIR, manifest_path=None, qdrant_path=":memory:"))
        ),
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
                # These process-level tests exercise the v1 demo data (fixed expectations).
                "HANDBOOK_DIR": str(ROOT / "services" / "academics_mcp" / "data" / "handbooks"),
                "SOURCE_MANIFEST": "",
                "PUBLIC_BOOK_PROVIDERS": "",  # no outbound calls to public book APIs in tests
                "LIBRARY_DEMO_DATA": str(ROOT / "services/library_mcp/library_mcp/data/demo_books_v1.json"),
                "EVENTS_DEMO_DATA": str(ROOT / "services/events_mcp/events_mcp/data/demo_events_v1.json"),
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
