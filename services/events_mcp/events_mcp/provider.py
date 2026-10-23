"""Event data providers.

* ``DemoEventsProvider`` — deterministic fixture; dates are generated relative to
  an injectable clock so the demo always has upcoming events.
* ``GoogleCalendarProvider`` — optional, read-only adapter for a *public* Google
  Calendar using an API key (Calendar API v3 ``events.list`` / ``events.get``).
  Private calendars need OAuth, which is documented in docs/google-calendar.md
  but intentionally not required for the MVP.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

from .models import EventDetails, EventSummary, SourceInfo

DEMO_DATA_PATH = Path(__file__).parent / "data" / "demo_events.json"


class EventNotFoundError(LookupError):
    pass


class EventsProviderError(RuntimeError):
    """Upstream calendar failure (network, auth, quota)."""


class EventsProvider(Protocol):
    async def search_events(
        self, query: str, start_date: date | None, end_date: date | None, limit: int
    ) -> list[EventSummary]: ...

    async def get_upcoming_events(self, limit: int) -> list[EventSummary]: ...

    async def get_event_details(self, event_id: str) -> EventDetails: ...

    def source_info(self) -> SourceInfo: ...


_WORD = re.compile(r"[a-z0-9]+")
_STOPWORDS = {"the", "a", "an", "next", "upcoming", "event", "events", "any", "on", "in", "at", "for", "of"}


def _matches(query: str, text: str) -> bool:
    """All meaningful query words must appear as whole words in the event text."""
    terms = [t for t in _WORD.findall(query.lower()) if t not in _STOPWORDS]
    words = set(_WORD.findall(text.lower()))
    return all(t in words or (len(t) > 3 and t.rstrip("s") in words) for t in terms)


class DemoEventsProvider:
    def __init__(
        self,
        data_path: Path = DEMO_DATA_PATH,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        raw: dict[str, Any] = json.loads(data_path.read_text(encoding="utf-8"))
        self._tz = ZoneInfo(raw.get("timezone", "UTC"))
        self._clock = clock or (lambda: datetime.now(self._tz))
        self._raw_events: list[dict[str, Any]] = raw["events"]

    def _now(self) -> datetime:
        now = self._clock()
        return now if now.tzinfo else now.replace(tzinfo=self._tz)

    def source_info(self) -> SourceInfo:
        return SourceInfo(
            mode="demo",
            provider="demo-json",
            data_as_of=self._now().date().isoformat(),
            note="Simulated events with dates relative to today; not a live campus calendar.",
        )

    def _materialise(self) -> list[EventDetails]:
        today = self._now().date()
        out: list[EventDetails] = []
        for e in self._raw_events:
            day = today + timedelta(days=int(e["day_offset"]))
            hh, mm = (int(x) for x in e["start_time"].split(":"))
            start = datetime.combine(day, time(hh, mm), tzinfo=self._tz)
            out.append(
                EventDetails(
                    event_id=e["event_id"],
                    title=e["title"],
                    category=e["category"],
                    start=start,
                    end=start + timedelta(minutes=int(e["duration_minutes"])),
                    location=e.get("location"),
                    description=e.get("description"),
                    organizer=e.get("organizer"),
                    tags=e.get("tags", []),
                    registration_required=e.get("registration_required"),
                    capacity=e.get("capacity"),
                    source=self.source_info(),
                )
            )
        out.sort(key=lambda ev: (ev.start, ev.event_id))
        return out

    @staticmethod
    def _summary(e: EventDetails) -> EventSummary:
        return EventSummary(
            event_id=e.event_id, title=e.title, category=e.category, start=e.start, end=e.end, location=e.location
        )

    async def search_events(
        self, query: str, start_date: date | None, end_date: date | None, limit: int
    ) -> list[EventSummary]:
        now = self._now()
        results = []
        for e in self._materialise():
            text = " ".join([e.title, e.category, e.description or "", " ".join(e.tags)])
            if not _matches(query, text):
                continue
            if start_date is None and end_date is None and e.end < now:
                continue  # default to upcoming/ongoing events only
            if start_date and e.start.date() < start_date:
                continue
            if end_date and e.start.date() > end_date:
                continue
            results.append(self._summary(e))
        return results[:limit]

    async def get_upcoming_events(self, limit: int) -> list[EventSummary]:
        now = self._now()
        return [self._summary(e) for e in self._materialise() if e.end >= now][:limit]

    async def get_event_details(self, event_id: str) -> EventDetails:
        for e in self._materialise():
            if e.event_id == event_id.upper():
                return e
        raise EventNotFoundError(f"No event with id '{event_id}'.")


class GoogleCalendarProvider:
    """Read-only adapter for a public Google Calendar (API-key auth).

    Network access is limited to ``https://www.googleapis.com/calendar/v3`` and the
    calendar id comes from configuration, never from model-generated arguments.
    """

    BASE_URL = "https://www.googleapis.com/calendar/v3"

    def __init__(
        self,
        calendar_id: str,
        api_key: str,
        timezone: str = "Asia/Kolkata",
        client: httpx.AsyncClient | None = None,
        timeout_s: float = 8.0,
    ) -> None:
        self._calendar_id = calendar_id
        self._api_key = api_key
        self._tz = ZoneInfo(timezone)
        self._client = client or httpx.AsyncClient(timeout=timeout_s)
        self._last_fetch: str | None = None

    def source_info(self) -> SourceInfo:
        return SourceInfo(
            mode="live",
            provider="google-calendar",
            data_as_of=self._last_fetch,
            note="Read-only public Google Calendar via API key.",
        )

    async def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        url = f"{self.BASE_URL}/calendars/{quote(self._calendar_id, safe='')}{path}"
        try:
            resp = await self._client.get(url, params={**params, "key": self._api_key})
        except httpx.HTTPError as exc:
            raise EventsProviderError(f"Google Calendar request failed: {type(exc).__name__}") from exc
        if resp.status_code == 404:
            raise EventNotFoundError("Event or calendar not found in Google Calendar.")
        if resp.status_code >= 400:
            # Never echo the URL (it contains the API key).
            raise EventsProviderError(f"Google Calendar returned HTTP {resp.status_code}.")
        self._last_fetch = datetime.now(self._tz).isoformat(timespec="seconds")
        data: dict[str, Any] = resp.json()
        return data

    def _parse_dt(self, node: dict[str, str]) -> datetime:
        if "dateTime" in node:
            return datetime.fromisoformat(node["dateTime"].replace("Z", "+00:00")).astimezone(self._tz)
        return datetime.combine(date.fromisoformat(node["date"]), time(0, 0), tzinfo=self._tz)

    def _to_details(self, item: dict[str, Any]) -> EventDetails:
        return EventDetails(
            event_id=item["id"],
            title=item.get("summary", "(untitled)"),
            category="calendar",
            start=self._parse_dt(item["start"]),
            end=self._parse_dt(item["end"]),
            location=item.get("location"),
            description=item.get("description"),
            organizer=(item.get("organizer") or {}).get("displayName"),
            source=self.source_info(),
        )

    def _summary(self, item: dict[str, Any]) -> EventSummary:
        d = self._to_details(item)
        return EventSummary(
            event_id=d.event_id, title=d.title, category=d.category, start=d.start, end=d.end, location=d.location
        )

    async def search_events(
        self, query: str, start_date: date | None, end_date: date | None, limit: int
    ) -> list[EventSummary]:
        params = {"singleEvents": "true", "orderBy": "startTime", "maxResults": str(limit)}
        if query.strip():
            params["q"] = query
        start = datetime.combine(start_date, time(0, 0), tzinfo=self._tz) if start_date else datetime.now(self._tz)
        params["timeMin"] = start.isoformat()
        if end_date:
            params["timeMax"] = datetime.combine(end_date + timedelta(days=1), time(0, 0), tzinfo=self._tz).isoformat()
        data = await self._get("/events", params)
        return [self._summary(i) for i in data.get("items", [])][:limit]

    async def get_upcoming_events(self, limit: int) -> list[EventSummary]:
        return await self.search_events("", None, None, limit)

    async def get_event_details(self, event_id: str) -> EventDetails:
        data = await self._get(f"/events/{quote(event_id, safe='')}", {})
        return self._to_details(data)


def load_provider_from_env() -> EventsProvider:
    name = os.getenv("EVENTS_PROVIDER", "demo").lower()
    if name == "demo":
        return DemoEventsProvider()
    if name == "google":
        cal = os.getenv("GOOGLE_CALENDAR_ID")
        key = os.getenv("GOOGLE_CALENDAR_API_KEY")
        if not cal or not key:
            raise ValueError("EVENTS_PROVIDER=google requires GOOGLE_CALENDAR_ID and GOOGLE_CALENDAR_API_KEY.")
        return GoogleCalendarProvider(cal, key, timezone=os.getenv("CAMPUS_TIMEZONE", "Asia/Kolkata"))
    raise ValueError(f"Unsupported EVENTS_PROVIDER '{name}' (expected 'demo' or 'google').")
