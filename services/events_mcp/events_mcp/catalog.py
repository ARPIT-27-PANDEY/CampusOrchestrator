"""Campus-day event logic shared by every provider.

* Dates are campus-local (``CAMPUS_TIMEZONE``). "Events on 2026-10-29" means events that
  overlap 2026-10-29 00:00 to 2026-10-30 00:00 in that timezone, so multi-day and
  past-midnight events are included on every day they touch.
* Cancelled events are excluded unless ``include_cancelled`` is set; completed events are
  never offered as upcoming. ``excluded_statuses`` in the response says what was filtered.
* Every record gets ``timing`` (past/ongoing/upcoming) relative to the clock at query time.
* An empty list means the source was queried successfully and nothing matched; source
  failures propagate as ``EventsProviderError`` instead.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from .campus_time import CampusClock
from .models import EventDetails, EventList, EventStatus, EventSummary, Timing
from .provider import EventBatch, EventsProvider


def timing(e: EventDetails, now: datetime) -> Timing:
    if e.end <= now:
        return "past"
    return "ongoing" if e.start <= now else "upcoming"


def to_summary(e: EventDetails, now: datetime) -> EventSummary:
    return EventSummary(
        event_id=e.event_id,
        title=e.title,
        category=e.category,
        start=e.start,
        end=e.end,
        all_day=e.all_day,
        location=e.location,
        status=e.status,
        timing=timing(e, now),
        origin=e.origin,
        tentative=e.tentative,
        date_note=e.date_note,
    )


class EventCatalog:
    def __init__(self, provider: EventsProvider, clock: CampusClock | None = None) -> None:
        self.provider = provider
        self.clock = clock or provider.clock

    def _filter(
        self, batch: EventBatch, excluded: list[EventStatus], *, drop_past: bool, limit: int
    ) -> tuple[list[EventSummary], datetime]:
        now = self.clock.now()
        kept = [e for e in batch.events if e.status not in excluded and not (drop_past and timing(e, now) == "past")]
        kept.sort(key=lambda e: (e.start, e.event_id))
        return [to_summary(e, now) for e in kept[:limit]], now

    @staticmethod
    def _empty_note(count: int, scope: str) -> str | None:
        if count:
            return None
        return f"The events source was queried successfully and has no matching events {scope}."

    async def search(
        self,
        query: str,
        start_date: date | None = None,
        end_date: date | None = None,
        *,
        include_cancelled: bool = False,
        limit: int = 10,
    ) -> EventList:
        explicit = start_date is not None or end_date is not None
        start = self.clock.start_of_day(start_date) if start_date else None
        end = self.clock.start_of_day(end_date + timedelta(days=1)) if end_date else None
        if not explicit:
            start = self.clock.now()  # default: ongoing and upcoming events only
        excluded: list[EventStatus] = [] if include_cancelled else ["cancelled"]
        if not explicit:
            excluded.append("completed")
        batch = await self.provider.fetch(start, end, query)
        events, _ = self._filter(batch, excluded, drop_past=not explicit, limit=limit)
        scope = f"between {start_date or '...'} and {end_date or '...'}" if explicit else "from now on"
        return EventList(
            query=query,
            count=len(events),
            events=events,
            source=batch.source,
            range_start=start,
            range_end=end,
            excluded_statuses=excluded,
            note=self._empty_note(len(events), scope) or ("; ".join(batch.warnings) or None),
        )

    async def upcoming(self, limit: int = 5) -> EventList:
        now = self.clock.now()
        batch = await self.provider.fetch(now, None, "")
        excluded: list[EventStatus] = ["cancelled", "completed"]
        events, _ = self._filter(batch, excluded, drop_past=True, limit=limit)
        return EventList(
            count=len(events),
            events=events,
            source=batch.source,
            range_start=now,
            excluded_statuses=excluded,
            note=self._empty_note(len(events), "from now on"),
        )

    async def on_date(self, day: date | None = None, *, include_cancelled: bool = False, limit: int = 50) -> EventList:
        target = day or self.clock.today()
        start = self.clock.start_of_day(target)
        end = self.clock.start_of_day(target + timedelta(days=1))
        batch = await self.provider.fetch(start, end, "")
        excluded: list[EventStatus] = [] if include_cancelled else ["cancelled"]
        events, _ = self._filter(batch, excluded, drop_past=False, limit=limit)
        return EventList(
            count=len(events),
            events=events,
            source=batch.source,
            date=target,
            range_start=start,
            range_end=end,
            excluded_statuses=excluded,
            note=self._empty_note(len(events), f"on {target} ({self.clock.tz.key})"),
        )

    async def details(self, event_id: str) -> EventDetails:
        e = await self.provider.fetch_event(event_id)
        return e.model_copy(update={"timing": timing(e, self.clock.now())})
