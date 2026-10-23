"""Events MCP server tests (demo provider, Google adapter with mocked HTTP, MCP protocol)."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
from mcp import Client

from events_mcp.provider import (
    DemoEventsProvider,
    EventNotFoundError,
    EventsProviderError,
    GoogleCalendarProvider,
)
from events_mcp.server import build_server

TZ = ZoneInfo("Asia/Kolkata")
FIXED_NOW = datetime(2026, 10, 23, 9, 0, tzinfo=TZ)


@pytest.fixture
def provider() -> DemoEventsProvider:
    return DemoEventsProvider(clock=lambda: FIXED_NOW)


async def test_upcoming_excludes_past_and_is_sorted(provider: DemoEventsProvider) -> None:
    events = await provider.get_upcoming_events(20)
    assert all(e.end >= FIXED_NOW for e in events)
    assert [e.start for e in events] == sorted(e.start for e in events)
    assert "EVT-110" not in {e.event_id for e in events}  # past event


async def test_search_ai_workshop_finds_next_one_first(provider: DemoEventsProvider) -> None:
    events = await provider.search_events("AI workshop", None, None, 10)
    assert events[0].event_id == "EVT-101"
    assert events[0].start.date() == date(2026, 10, 26)


async def test_search_with_date_range(provider: DemoEventsProvider) -> None:
    events = await provider.search_events("", date(2026, 10, 25), date(2026, 10, 29), 10)
    # offsets 2, 3, 5, 6 days from 2026-10-23
    assert {e.event_id for e in events} == {"EVT-108", "EVT-101", "EVT-106", "EVT-103"}


async def test_search_word_matching_avoids_substring_false_positive(provider: DemoEventsProvider) -> None:
    # "ai" must not match words like "maintain"/"training" — only the whole word or tag.
    events = await provider.search_events("ai", None, None, 20)
    assert "EVT-108" not in {e.event_id for e in events}


async def test_details_unknown(provider: DemoEventsProvider) -> None:
    with pytest.raises(EventNotFoundError):
        await provider.get_event_details("EVT-999")


async def test_mcp_tools_and_invalid_range() -> None:
    async with Client(build_server(DemoEventsProvider(clock=lambda: FIXED_NOW))) as client:
        tools = {t.name for t in (await client.list_tools()).tools}
        assert tools == {"search_events", "get_upcoming_events", "get_event_details"}
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
    events = await prov.search_events("AI", None, None, 5)
    assert [e.event_id for e in events] == ["abc123", "allday"]
    assert events[0].start.tzinfo is not None
    assert seen[0].url.host == "www.googleapis.com"
    assert seen[0].url.params["q"] == "AI"
    assert prov.source_info().mode == "live"


async def test_google_adapter_error_message_is_sanitised() -> None:
    prov = _google(httpx.MockTransport(lambda r: httpx.Response(403, json={"error": "quota"})))
    with pytest.raises(EventsProviderError) as info:
        await prov.get_upcoming_events(3)
    assert "test-key" not in str(info.value)
    assert "403" in str(info.value)
