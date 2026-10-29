"""Events MCP server tests (demo provider, Google adapter with mocked HTTP, MCP protocol)."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
from mcp import Client

from events_mcp.catalog import EventCatalog
from events_mcp.provider import (
    DEMO_DATA_PATH,
    DemoEventsProvider,
    EventNotFoundError,
    EventsProviderError,
    GoogleCalendarProvider,
)
from events_mcp.server import build_server

TZ = ZoneInfo("Asia/Kolkata")
FIXED_NOW = datetime(2026, 10, 23, 9, 0, tzinfo=TZ)
V1_FIXTURE = DEMO_DATA_PATH.with_name("demo_events_v1.json")  # the original 12-event fixture these tests describe


@pytest.fixture
def provider() -> DemoEventsProvider:
    return DemoEventsProvider(V1_FIXTURE, clock=lambda: FIXED_NOW)


@pytest.fixture
def catalog(provider: DemoEventsProvider) -> EventCatalog:
    return EventCatalog(provider)


async def test_upcoming_excludes_past_and_is_sorted(catalog: EventCatalog) -> None:
    events = (await catalog.upcoming(20)).events
    assert all(e.end >= FIXED_NOW for e in events)
    assert [e.start for e in events] == sorted(e.start for e in events)
    assert "EVT-110" not in {e.event_id for e in events}  # past event


async def test_search_ai_workshop_finds_next_one_first(catalog: EventCatalog) -> None:
    events = (await catalog.search("AI workshop")).events
    assert events[0].event_id == "EVT-101"
    assert events[0].start.date() == date(2026, 10, 26)


async def test_search_with_date_range(catalog: EventCatalog) -> None:
    events = (await catalog.search("", date(2026, 10, 25), date(2026, 10, 29))).events
    # offsets 2, 3, 5, 6 days from 2026-10-23
    assert {e.event_id for e in events} == {"EVT-108", "EVT-101", "EVT-106", "EVT-103"}


async def test_search_word_matching_avoids_substring_false_positive(catalog: EventCatalog) -> None:
    # "ai" must not match words like "maintain"/"training" — only the whole word or tag.
    events = (await catalog.search("ai", limit=20)).events
    assert "EVT-108" not in {e.event_id for e in events}


async def test_details_unknown(catalog: EventCatalog) -> None:
    with pytest.raises(EventNotFoundError):
        await catalog.details("EVT-999")


async def test_mcp_tools_and_invalid_range() -> None:
    async with Client(build_server(DemoEventsProvider(clock=lambda: FIXED_NOW))) as client:
        tools = {t.name for t in (await client.list_tools()).tools}
        assert tools == {"search_events", "get_events_for_date", "get_upcoming_events", "get_event_details"}
        bad = await client.call_tool(
            "search_events", {"query": "x", "start_date": "2026-11-10", "end_date": "2026-11-01"}
        )
        assert bad.is_error
        ok = await client.call_tool("get_event_details", {"event_id": "EVT-101"})
        assert not ok.is_error
        assert ok.structured_content is not None
        assert ok.structured_content["source"]["mode"] == "demo"


def _google(handler: httpx.MockTransport) -> GoogleCalendarProvider:
    return GoogleCalendarProvider(
        "campus@group.calendar.google.com", "test-key", client=httpx.AsyncClient(transport=handler)
    )


async def test_google_adapter_parses_events_and_never_leaks_key() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "abc123",
                        "summary": "AI Seminar",
                        "start": {"dateTime": "2026-10-30T10:00:00Z"},
                        "end": {"dateTime": "2026-10-30T11:00:00Z"},
                        "location": "Hall 1",
                    },
                    {
                        "id": "allday",
                        "summary": "Holiday",
                        "start": {"date": "2026-11-08"},
                        "end": {"date": "2026-11-09"},
                    },
                ]
            },
        )

    prov = _google(httpx.MockTransport(handle))
    batch = await prov.fetch(None, None, "AI")
    events = batch.events
    assert [e.event_id for e in events] == ["abc123", "allday"]
    assert events[0].start.tzinfo is not None
    assert events[1].all_day is True
    assert seen[0].url.host == "www.googleapis.com"
    assert seen[0].url.params["q"] == "AI"
    assert batch.source.mode == "live"
    assert batch.source.retrieved_at is not None
    assert batch.source.data_as_of is None  # the response carried no "updated" field: never fabricated


async def test_google_adapter_error_message_is_sanitised() -> None:
    prov = _google(httpx.MockTransport(lambda r: httpx.Response(403, json={"error": "quota"})))
    with pytest.raises(EventsProviderError) as info:
        await EventCatalog(prov).upcoming(3)
    assert "test-key" not in str(info.value)
    assert "403" in str(info.value)
