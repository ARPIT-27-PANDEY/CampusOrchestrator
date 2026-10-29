"""Event data providers.

Providers only *fetch* events for a time window and describe where that data came
from. All campus-day logic (today/tomorrow, statuses, past/ongoing/upcoming) lives in
``catalog.EventCatalog`` so every provider behaves the same way.

* ``DemoEventsProvider`` - bundled fixture mixing:
    - ``origin: official`` records copied from IIT Roorkee documents (absolute dates,
      with the document and page they come from), and
    - ``origin: synthetic`` demo records whose dates are relative to the campus clock.
* ``GoogleCalendarProvider`` - optional read-only adapter for a *public* Google Calendar
  (Calendar API v3, API key). The calendar id comes from configuration, never from
  model-generated arguments.

A provider failure raises ``EventsProviderError``; it is never turned into an empty list.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from .campus_time import CampusClock
from .models import EventDetails, SourceInfo

DEMO_DATA_PATH = Path(__file__).parent / "data" / "demo_events.json"


class EventNotFoundError(LookupError):
    pass


class EventsProviderError(RuntimeError):
    """Upstream calendar failure (network, auth, quota, malformed data)."""


@dataclass
class EventBatch:
    events: list[EventDetails]
    source: SourceInfo
    warnings: list[str] = field(default_factory=list)


class EventsProvider(Protocol):
    clock: CampusClock

    async def fetch(self, start: datetime | None, end: datetime | None, query: str) -> EventBatch:
        """Events overlapping [start, end) whose text matches ``query`` (empty = all)."""
        ...

    async def fetch_event(self, event_id: str) -> EventDetails: ...

    def source_info(self) -> SourceInfo: ...


_WORD = re.compile(r"[a-z0-9]+")
_STOPWORDS = {"the", "a", "an", "next", "upcoming", "event", "events", "any", "on", "in", "at", "for", "of"}


def matches_query(query: str, text: str) -> bool:
    """All meaningful query words must appear as whole words in the event text."""
    terms = [t for t in _WORD.findall(query.lower()) if t not in _STOPWORDS]
    words = set(_WORD.findall(text.lower()))
    return all(t in words or (len(t) > 3 and t.rstrip("s") in words) for t in terms)


def overlaps(e: EventDetails, start: datetime | None, end: datetime | None) -> bool:
    """True if the event intersects [start, end); an event ending exactly at ``start`` does not."""
    if start is not None and e.end <= start and not (e.start == e.end == start):
        return False
    return not (end is not None and e.start >= end)


def _as_clock(clock: CampusClock | Callable[[], datetime] | None) -> CampusClock:
    if clock is None or isinstance(clock, CampusClock):
        return clock or CampusClock()
    return CampusClock(clock=clock)  # plain callable (tests): naive values are campus-local


def _parse_hhmm(value: str) -> time:
    hh, mm = (int(x) for x in value.split(":"))
    return time(hh, mm)


class DemoEventsProvider:
    def __init__(
        self,
        data_path: Path = DEMO_DATA_PATH,
        clock: CampusClock | Callable[[], datetime] | None = None,
    ) -> None:
        text = data_path.read_text(encoding="utf-8")
        raw: dict[str, Any] = json.loads(text)
        self.clock = _as_clock(clock)
        self._raw_events: list[dict[str, Any]] = raw["events"]
        self._documents: dict[str, dict[str, Any]] = raw.get("documents", {})
        self._version = hashlib.sha256(text.encode()).hexdigest()[:12]
        self.duplicates_skipped = 0

    def source_info(self) -> SourceInfo:
        return SourceInfo(
            mode="demo",
            provider="demo-json",
            retrieved_at=self.clock.retrieved_at(),
            record_version=self._version,
            timezone=self.clock.tz.key,
            note=(
                "Mixed fixture. Records with origin=official are copied from IIT Roorkee documents (see "
                "source_document); records with origin=synthetic are invented demo events with dates relative "
                "to today and are not IIT Roorkee announcements."
            ),
        )

    def _official_source(self, doc_key: str | None) -> SourceInfo:
        doc = self._documents.get(doc_key or "", {})
        return SourceInfo(
            mode="imported",
            provider=f"iitr-document:{doc_key}" if doc_key else "iitr-document",
            source_url=doc.get("url"),
            retrieved_at=self.clock.retrieved_at(),
            data_as_of=doc.get("issued"),
            record_version=doc.get("sha256", "")[:12] or None,
            timezone=self.clock.tz.key,
            note=doc.get("title"),
        )

    def _materialise(self) -> list[EventDetails]:
        tz = self.clock.tz
        today = self.clock.today()
        out: list[EventDetails] = []
        seen: set[str] = set()
        self.duplicates_skipped = 0
        for e in self._raw_events:
            event_id = str(e["event_id"]).upper()
            if event_id in seen:  # duplicate import of the same record
                self.duplicates_skipped += 1
                continue
            seen.add(event_id)
            day = date.fromisoformat(e["date"]) if e.get("date") else today + timedelta(days=int(e["day_offset"]))
            all_day = bool(e.get("all_day"))
            if all_day:
                start = datetime.combine(day, time(0, 0), tzinfo=tz)
                last = date.fromisoformat(e["end_date"]) if e.get("end_date") else day
                end = datetime.combine(last + timedelta(days=1), time(0, 0), tzinfo=tz)
            else:
                start = datetime.combine(day, _parse_hhmm(e["start_time"]), tzinfo=tz)
                if "duration_minutes" in e:
                    end = start + timedelta(minutes=int(e["duration_minutes"]))
                else:
                    end_day = date.fromisoformat(e["end_date"]) if e.get("end_date") else day
                    end = datetime.combine(end_day, _parse_hhmm(e["end_time"]), tzinfo=tz)
            original_start = original_end = None
            if e.get("original_day_offset") is not None or e.get("original_date"):
                o_day = (
                    date.fromisoformat(e["original_date"])
                    if e.get("original_date")
                    else today + timedelta(days=int(e["original_day_offset"]))
                )
                original_start = datetime.combine(o_day, _parse_hhmm(e.get("original_start_time", "00:00")), tzinfo=tz)
                original_end = original_start + (end - start)
            official = e.get("origin") == "official"
            out.append(
                EventDetails(
                    event_id=event_id,
                    title=e["title"],
                    category=e["category"],
                    start=start,
                    end=end,
                    all_day=all_day,
                    location=e.get("location"),
                    status=e.get("status", "scheduled"),
                    origin="official" if official else "synthetic",
                    tentative=bool(e.get("tentative")),
                    date_note=e.get("date_note"),
                    description=e.get("description"),
                    organizer=e.get("organizer"),
                    tags=e.get("tags", []),
                    online_url=e.get("online_url"),
                    registration_required=e.get("registration_required"),
                    registration_status=e.get("registration_status", "unknown"),
                    registration_deadline=(
                        datetime.combine(
                            today + timedelta(days=int(e["registration_deadline_offset"])), time(23, 59), tzinfo=tz
                        )
                        if e.get("registration_deadline_offset") is not None
                        else None
                    ),
                    capacity=e.get("capacity"),
                    recurrence=e.get("recurrence"),
                    original_start=original_start,
                    original_end=original_end,
                    source_document=self._documents.get(e.get("document", ""), {}).get("title") if official else None,
                    source_page=e.get("page") if official else None,
                    source=self._official_source(e.get("document")) if official else self.source_info(),
                )
            )
        out.sort(key=lambda ev: (ev.start, ev.event_id))
        return out

    async def fetch(self, start: datetime | None, end: datetime | None, query: str) -> EventBatch:
        events = [
            e
            for e in self._materialise()
            if overlaps(e, start, end)
            and matches_query(query, " ".join([e.title, e.category, e.description or "", " ".join(e.tags)]))
        ]
        warnings = [f"{self.duplicates_skipped} duplicate record(s) ignored."] if self.duplicates_skipped else []
        return EventBatch(events=events, source=self.source_info(), warnings=warnings)

    async def fetch_event(self, event_id: str) -> EventDetails:
        for e in self._materialise():
            if e.event_id == event_id.upper():
                return e
        raise EventNotFoundError(f"No event with id '{event_id}'.")


class GoogleCalendarProvider:
    """Read-only adapter for a public Google Calendar (API-key auth).

    Network access is limited to ``https://www.googleapis.com/calendar/v3``.
    ``retrieved_at`` is when we fetched; ``data_as_of`` is the ``updated`` timestamp the
    API returns (last modification of the calendar or event), or null if absent.
    """

    BASE_URL = "https://www.googleapis.com/calendar/v3"

    def __init__(
        self,
        calendar_id: str,
        api_key: str,
        timezone: str | None = None,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = 8.0,
        clock: CampusClock | None = None,
    ) -> None:
        self._calendar_id = calendar_id
        self._api_key = api_key
        self.clock = clock or CampusClock(timezone)
        self._client = client or httpx.AsyncClient(timeout=timeout_s)

    def source_info(self, retrieved_at: str | None = None, data_as_of: str | None = None) -> SourceInfo:
        return SourceInfo(
            mode="live",
            provider="google-calendar",
            source_url=f"https://calendar.google.com/calendar/embed?src={quote(self._calendar_id, safe='')}",
            retrieved_at=retrieved_at,
            data_as_of=data_as_of,
            timezone=self.clock.tz.key,
            note="Read-only public Google Calendar via API key.",
        )

    async def _get(self, path: str, params: dict[str, str]) -> tuple[dict[str, Any], str]:
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
        try:
            data: dict[str, Any] = resp.json()
        except ValueError as exc:
            raise EventsProviderError("Google Calendar returned a malformed response.") from exc
        return data, self.clock.retrieved_at()

    def _parse_dt(self, node: dict[str, str]) -> tuple[datetime, bool]:
        if "dateTime" in node:
            return datetime.fromisoformat(node["dateTime"].replace("Z", "+00:00")).astimezone(self.clock.tz), False
        return self.clock.start_of_day(date.fromisoformat(node["date"])), True

    def _to_details(self, item: dict[str, Any], source: SourceInfo) -> EventDetails:
        try:
            start, all_day = self._parse_dt(item["start"])
            end, _ = self._parse_dt(item["end"])
        except (KeyError, ValueError) as exc:
            raise EventsProviderError("Google Calendar returned an event without valid start/end.") from exc
        return EventDetails(
            event_id=item["id"],
            title=item.get("summary", "(untitled)"),
            category="calendar",
            start=start,
            end=end,
            all_day=all_day,
            location=item.get("location"),
            status="cancelled" if item.get("status") == "cancelled" else "scheduled",
            origin="calendar",
            description=item.get("description"),
            organizer=(item.get("organizer") or {}).get("displayName"),
            online_url=item.get("hangoutLink"),
            recurrence="; ".join(item["recurrence"]) if item.get("recurrence") else None,
            source=source,
        )

    async def fetch(self, start: datetime | None, end: datetime | None, query: str) -> EventBatch:
        params = {"singleEvents": "true", "orderBy": "startTime", "maxResults": "100"}
        if query.strip():
            params["q"] = query
        params["timeMin"] = (start or self.clock.now()).astimezone(UTC).isoformat()
        if end:
            params["timeMax"] = end.astimezone(UTC).isoformat()
        data, retrieved = await self._get("/events", params)
        source = self.source_info(retrieved, data.get("updated"))
        return EventBatch(events=[self._to_details(i, source) for i in data.get("items", [])], source=source)

    async def fetch_event(self, event_id: str) -> EventDetails:
        data, retrieved = await self._get(f"/events/{quote(event_id, safe='')}", {})
        return self._to_details(data, self.source_info(retrieved, data.get("updated")))


def load_provider_from_env(clock: CampusClock | None = None) -> EventsProvider:
    clock = clock or CampusClock()
    name = os.getenv("EVENTS_PROVIDER", "demo").lower()
    if name == "demo":
        path = os.getenv("EVENTS_DEMO_DATA")
        return DemoEventsProvider(Path(path), clock=clock) if path else DemoEventsProvider(clock=clock)
    if name == "google":
        cal = os.getenv("GOOGLE_CALENDAR_ID")
        key = os.getenv("GOOGLE_CALENDAR_API_KEY")
        if not cal or not key:
            raise ValueError("EVENTS_PROVIDER=google requires GOOGLE_CALENDAR_ID and GOOGLE_CALENDAR_API_KEY.")
        return GoogleCalendarProvider(cal, key, clock=clock)
    raise ValueError(f"Unsupported EVENTS_PROVIDER '{name}' (expected 'demo' or 'google').")
