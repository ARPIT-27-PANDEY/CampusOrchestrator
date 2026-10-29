"""Campus-timezone date handling, event statuses and failure semantics for the events service."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest
from mcp import Client

from events_mcp.campus_time import CampusClock
from events_mcp.catalog import EventCatalog
from events_mcp.provider import DemoEventsProvider, EventsProviderError, GoogleCalendarProvider
from events_mcp.server import build_server

BEFORE_MIDNIGHT_IST = datetime(2026, 10, 28, 18, 29, tzinfo=UTC)  # 23:59 Wed 28 Oct in India
AT_MIDNIGHT_IST = datetime(2026, 10, 28, 18, 30, tzinfo=UTC)  # 00:00 Thu 29 Oct in India


def _fixture(tmp_path: Path, events: list[dict[str, Any]]) -> Path:
    path = tmp_path / "events.json"
    path.write_text(json.dumps({"events": events}), encoding="utf-8")
    return path


def _ev(event_id: str, **kw: Any) -> dict[str, Any]:
    base = {"event_id": event_id, "title": f"Event {event_id}", "category": "workshop", "start_time": "10:00"}
    base.update(kw)
    if "duration_minutes" not in base and "end_time" not in base and not base.get("all_day"):
        base["duration_minutes"] = 60
    return base


@pytest.fixture
def boundary_events(tmp_path: Path) -> Path:
    return _fixture(
        tmp_path,
        [
            _ev("WED-1", date="2026-10-28", start_time="18:00"),
            _ev("THU-1", date="2026-10-29", start_time="11:00"),
            _ev("NIGHT", date="2026-10-28", start_time="23:00", end_date="2026-10-29", end_time="01:30"),
            _ev("FEST", date="2026-10-27", end_date="2026-10-30", all_day=True, category="cultural"),
            _ev("GONE", date="2026-10-29", start_time="15:00", status="cancelled"),
            _ev(
                "MOVED",
                date="2026-10-29",
                start_time="16:00",
                status="rescheduled",
                original_date="2026-10-28",
                original_start_time="16:00",
            ),
            _ev("DONE", date="2026-10-20", status="completed"),
            _ev("DUP", date="2026-10-29"),
            _ev("DUP", date="2026-10-29", title="duplicate import"),
        ],
    )


def _catalog(path: Path, instant: datetime) -> EventCatalog:
    clock = CampusClock.fixed(instant, "Asia/Kolkata")
    return EventCatalog(DemoEventsProvider(path, clock=clock))


def test_clock_boundary_values() -> None:
    before = CampusClock.fixed(BEFORE_MIDNIGHT_IST, "Asia/Kolkata").now()
    after = CampusClock.fixed(AT_MIDNIGHT_IST, "Asia/Kolkata").now()
    assert (before.date(), before.strftime("%H:%M %A")) == (date(2026, 10, 28), "23:59 Wednesday")
    assert (after.date(), after.strftime("%H:%M %A")) == (date(2026, 10, 29), "00:00 Thursday")


async def test_today_switches_at_ist_midnight_not_utc_midnight(boundary_events: Path) -> None:
    wed = await _catalog(boundary_events, BEFORE_MIDNIGHT_IST).on_date()
    thu = await _catalog(boundary_events, AT_MIDNIGHT_IST).on_date()
    assert wed.date == date(2026, 10, 28) and thu.date == date(2026, 10, 29)
    assert "WED-1" in {e.event_id for e in wed.events} and "THU-1" not in {e.event_id for e in wed.events}
    assert "THU-1" in {e.event_id for e in thu.events} and "WED-1" not in {e.event_id for e in thu.events}


async def test_event_spanning_midnight_and_multi_day_appear_on_each_day(boundary_events: Path) -> None:
    cat = _catalog(boundary_events, AT_MIDNIGHT_IST)
    for day in (date(2026, 10, 28), date(2026, 10, 29)):
        ids = {e.event_id for e in (await cat.on_date(day)).events}
        assert {"NIGHT", "FEST"} <= ids
    assert "NIGHT" not in {e.event_id for e in (await cat.on_date(date(2026, 10, 30))).events}
    fest = {e.event_id: e for e in (await cat.on_date(date(2026, 10, 30))).events}["FEST"]
    assert fest.all_day and fest.end == datetime(2026, 10, 31, tzinfo=CampusClock(None).tz)


async def test_ongoing_event_is_marked_ongoing_at_midnight(boundary_events: Path) -> None:
    events = {e.event_id: e for e in (await _catalog(boundary_events, AT_MIDNIGHT_IST).on_date()).events}
    assert events["NIGHT"].timing == "ongoing"
    assert events["THU-1"].timing == "upcoming"


async def test_tomorrow_across_midnight(boundary_events: Path) -> None:
    cat = _catalog(boundary_events, BEFORE_MIDNIGHT_IST)
    tomorrow = cat.clock.tomorrow()
    assert tomorrow == date(2026, 10, 29)
    assert "THU-1" in {e.event_id for e in (await cat.on_date(tomorrow)).events}


async def test_cancelled_hidden_by_default_and_completed_never_upcoming(boundary_events: Path) -> None:
    cat = _catalog(boundary_events, AT_MIDNIGHT_IST)
    day = await cat.on_date()
    assert "GONE" not in {e.event_id for e in day.events} and "cancelled" in day.excluded_statuses
    with_cancelled = await cat.on_date(include_cancelled=True)
    assert {e.event_id: e.status for e in with_cancelled.events}["GONE"] == "cancelled"
    upcoming = await cat.upcoming(20)
    assert not {"GONE", "DONE"} & {e.event_id for e in upcoming.events}
    past_range = await cat.search("", date(2026, 10, 19), date(2026, 10, 21))
    assert [(e.event_id, e.status, e.timing) for e in past_range.events] == [("DONE", "completed", "past")]


async def test_rescheduled_event_keeps_original_time(boundary_events: Path) -> None:
    moved = await _catalog(boundary_events, AT_MIDNIGHT_IST).details("MOVED")
    assert moved.status == "rescheduled"
    assert moved.original_start is not None and moved.original_start.date() == date(2026, 10, 28)
    assert moved.start.date() == date(2026, 10, 29)


async def test_duplicate_records_are_imported_once(boundary_events: Path) -> None:
    result = await _catalog(boundary_events, AT_MIDNIGHT_IST).on_date()
    assert [e.event_id for e in result.events].count("DUP") == 1
    assert {e.title for e in result.events if e.event_id == "DUP"} == {"Event DUP"}


async def test_empty_day_is_an_explicit_successful_no_match(boundary_events: Path) -> None:
    result = await _catalog(boundary_events, AT_MIDNIGHT_IST).on_date(date(2026, 12, 25))
    assert result.count == 0 and result.note and "queried successfully" in result.note


async def test_explicit_date_is_honoured_exactly(boundary_events: Path) -> None:
    result = await _catalog(boundary_events, AT_MIDNIGHT_IST).on_date(date(2026, 10, 28))
    assert result.date == date(2026, 10, 28)
    assert "WED-1" in {e.event_id for e in result.events}


def test_naive_clock_values_are_campus_local() -> None:
    clock = CampusClock(clock=lambda: datetime(2026, 10, 29, 0, 0))  # naive -> IST
    assert clock.now_utc() == AT_MIDNIGHT_IST


def test_offset_timestamps_are_converted_not_relabelled() -> None:
    clock = CampusClock.fixed(datetime(2026, 10, 28, 20, 0, tzinfo=timezone(timedelta(hours=-4))))
    assert clock.today() == date(2026, 10, 29)  # 20:00 EDT == 05:30 IST next day


def test_asia_kolkata_has_no_dst() -> None:
    for month in (1, 4, 7, 10):
        local = CampusClock.fixed(datetime(2026, month, 15, 12, tzinfo=UTC)).now()
        assert local.utcoffset() == timedelta(hours=5, minutes=30)


def test_campus_timezone_env_is_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAMPUS_TIMEZONE", "Mars/Olympus_Mons")
    with pytest.raises(ValueError, match="CAMPUS_TIMEZONE"):
        CampusClock()
    monkeypatch.setenv("CAMPUS_TIMEZONE", "UTC")
    assert CampusClock.fixed(BEFORE_MIDNIGHT_IST).today() == date(2026, 10, 28)


async def test_get_events_for_date_tool_defaults_to_campus_today(boundary_events: Path) -> None:
    server = build_server(DemoEventsProvider(boundary_events, clock=CampusClock.fixed(AT_MIDNIGHT_IST)))
    async with Client(server) as client:
        res = await client.call_tool("get_events_for_date", {})
        assert res.structured_content is not None
        assert res.structured_content["date"] == "2026-10-29"
        explicit = await client.call_tool("get_events_for_date", {"date": "2026-10-28"})
        assert explicit.structured_content is not None and explicit.structured_content["date"] == "2026-10-28"


def _google(handler: Any, instant: datetime = AT_MIDNIGHT_IST) -> GoogleCalendarProvider:
    return GoogleCalendarProvider(
        "campus@group.calendar.google.com",
        "test-key",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        clock=CampusClock.fixed(instant),
    )


async def test_google_retrieved_at_and_data_as_of_are_distinct() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "updated": "2026-10-20T08:00:00.000Z",
                "items": [
                    {
                        "id": "x1",
                        "summary": "Seminar",
                        "status": "confirmed",
                        "start": {"dateTime": "2026-10-29T05:00:00+05:30"},
                        "end": {"dateTime": "2026-10-29T06:00:00+05:30"},
                    },
                    {
                        "id": "x2",
                        "summary": "Called off",
                        "status": "cancelled",
                        "start": {"dateTime": "2026-10-29T07:00:00Z"},
                        "end": {"dateTime": "2026-10-29T08:00:00Z"},
                    },
                ],
            },
        )

    result = await EventCatalog(_google(handle)).on_date()
    assert result.source.retrieved_at == "2026-10-28T18:30:00Z"  # our fetch time
    assert result.source.data_as_of == "2026-10-20T08:00:00.000Z"  # upstream modification time
    assert [e.event_id for e in result.events] == ["x1"]  # cancelled hidden by default


async def test_google_failure_is_a_tool_error_not_an_empty_list() -> None:
    server = build_server(_google(lambda r: httpx.Response(503)))
    async with Client(server) as client:
        res = await client.call_tool("get_events_for_date", {})
        assert res.is_error
        text = " ".join(getattr(c, "text", "") for c in res.content)
        assert "could not be checked" in text and "test-key" not in text


async def test_google_malformed_payload_is_a_provider_error() -> None:
    prov = _google(lambda r: httpx.Response(200, content=b"<html>not json</html>"))
    with pytest.raises(EventsProviderError, match="malformed"):
        await prov.fetch(None, None, "")
