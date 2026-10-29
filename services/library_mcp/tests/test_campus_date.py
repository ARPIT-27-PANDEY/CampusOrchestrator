"""Library: default dates come from the campus clock; query time is separate from data dates."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from mcp import Client

from library_mcp.campus_time import CampusClock
from library_mcp.provider import DemoLibraryProvider
from library_mcp.server import build_server

BEFORE_MIDNIGHT_IST = datetime(2026, 10, 28, 18, 29, tzinfo=UTC)
AT_MIDNIGHT_IST = datetime(2026, 10, 28, 18, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    ("instant", "expected"), [(BEFORE_MIDNIGHT_IST, "2026-10-28"), (AT_MIDNIGHT_IST, "2026-10-29")]
)
async def test_default_library_hours_date_is_campus_today(instant: datetime, expected: str) -> None:
    clock = CampusClock.fixed(instant)
    async with Client(build_server(DemoLibraryProvider(clock=clock))) as client:
        res = await client.call_tool("get_library_hours", {})
        assert res.structured_content is not None
        assert res.structured_content["date"] == expected


async def test_explicit_date_is_honoured() -> None:
    clock = CampusClock.fixed(AT_MIDNIGHT_IST)
    async with Client(build_server(DemoLibraryProvider(clock=clock))) as client:
        res = await client.call_tool("get_library_hours", {"date": "2026-11-08"})
        assert res.structured_content is not None and res.structured_content["date"] == "2026-11-08"


def test_query_time_is_not_reported_as_catalogue_date() -> None:
    info = DemoLibraryProvider(clock=CampusClock.fixed(AT_MIDNIGHT_IST)).source_info()
    assert info.retrieved_at == "2026-10-28T18:30:00Z"
    assert info.data_as_of != info.retrieved_at  # catalogue snapshot date, not the lookup time
    assert info.mode == "demo"
    assert info.stale is None and "Synthetic" in (info.staleness_reason or "")
    assert info.timezone == "Asia/Kolkata"
