"""All services and the agent agree on the campus date, including across IST midnight."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from mcp import Client

from .conftest import ROOT, inprocess_servers

BEFORE_MIDNIGHT_IST = datetime(2026, 10, 28, 18, 29, tzinfo=UTC)  # 23:59 Wed 28 Oct, Asia/Kolkata
AT_MIDNIGHT_IST = datetime(2026, 10, 28, 18, 30, tzinfo=UTC)  # 00:00 Thu 29 Oct, Asia/Kolkata


async def _call(server: Any, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    async with Client(server) as client:
        res = await client.call_tool(tool, args)
        assert not res.is_error and res.structured_content is not None
        return dict(res.structured_content)


@pytest.mark.parametrize(
    ("instant", "expected"), [(BEFORE_MIDNIGHT_IST, "2026-10-28"), (AT_MIDNIGHT_IST, "2026-10-29")]
)
async def test_cafeteria_library_and_events_agree_on_today(instant: datetime, expected: str) -> None:
    servers = inprocess_servers(instant)
    menu = await _call(servers["cafeteria"], "get_today_menu", {})
    hours = await _call(servers["library"], "get_library_hours", {})
    events = await _call(servers["events"], "get_events_for_date", {})
    assert menu["date"] == hours["date"] == events["date"] == expected


def test_agent_prompt_uses_campus_date_not_utc_date() -> None:
    import sys

    sys.path.insert(0, str(ROOT / "backend"))
    from app.agent.prompts import system_prompt
    from app.campus_time import CampusClock

    prompt = system_prompt(CampusClock.fixed(AT_MIDNIGHT_IST).now(), [])
    assert "Today on campus is Thursday, 2026-10-29" in prompt  # UTC date is still 2026-10-28
    assert "Tomorrow is 2026-10-30" in prompt and "Asia/Kolkata" in prompt


def test_campus_time_module_is_identical_in_every_package() -> None:
    copies = [
        ROOT / "backend" / "app" / "campus_time.py",
        *(ROOT / "services" / f"{s}_mcp" / f"{s}_mcp" / "campus_time.py" for s in
          ("library", "events", "cafeteria", "academics")),
    ]  # fmt: skip
    digests = {p.relative_to(ROOT).as_posix(): hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in copies}
    assert len(set(digests.values())) == 1, f"campus_time.py copies diverged: {digests}"
