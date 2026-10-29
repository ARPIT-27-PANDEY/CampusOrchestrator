"""Campus-local time with an injectable clock.

Every service decides "today" in the configured campus timezone (``CAMPUS_TIMEZONE``,
default ``Asia/Kolkata``), never in the host operating system's timezone.

* ``CampusClock.now()`` -> aware datetime in the campus timezone (for "today", menus, events).
* ``CampusClock.now_utc()`` -> aware UTC datetime (for ``retrieved_at`` and logs).
* The underlying clock is injectable so tests and evaluations can pin an exact instant.
  A clock that returns a naive datetime is interpreted as campus-local time.

This file is intentionally identical in every MCP service package (the services are
independently installable); ``tests/test_campus_time_copies.py`` keeps the copies in sync.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "Asia/Kolkata"
Clock = Callable[[], datetime]


def load_timezone(name: str | None = None) -> ZoneInfo:
    """Validate and load a timezone; ``None`` reads ``CAMPUS_TIMEZONE``."""
    value = (os.getenv("CAMPUS_TIMEZONE", DEFAULT_TIMEZONE) if name is None else name).strip() or DEFAULT_TIMEZONE
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"Invalid CAMPUS_TIMEZONE {value!r}: not an IANA timezone name.") from exc


def system_clock() -> datetime:
    return datetime.now(UTC)


class CampusClock:
    def __init__(self, tz: ZoneInfo | str | None = None, clock: Clock | None = None) -> None:
        self.tz = tz if isinstance(tz, ZoneInfo) else load_timezone(tz)
        self._clock = clock or system_clock

    @classmethod
    def fixed(cls, instant: datetime, tz: ZoneInfo | str | None = None) -> CampusClock:
        """A clock frozen at ``instant`` (tests and deterministic evaluations)."""
        return cls(tz, lambda: instant)

    def localize(self, value: datetime) -> datetime:
        """Convert to campus time; a naive value is taken to already be campus-local."""
        return value.replace(tzinfo=self.tz) if value.tzinfo is None else value.astimezone(self.tz)

    def now(self) -> datetime:
        return self.localize(self._clock())

    def now_utc(self) -> datetime:
        return self.now().astimezone(UTC)

    def today(self) -> date:
        return self.now().date()

    def tomorrow(self) -> date:
        return self.today() + timedelta(days=1)

    def start_of_day(self, day: date) -> datetime:
        return datetime(day.year, day.month, day.day, tzinfo=self.tz)

    def retrieved_at(self) -> str:
        """ISO-8601 UTC timestamp for provenance (``retrieved_at``)."""
        return self.now_utc().isoformat(timespec="seconds").replace("+00:00", "Z")
