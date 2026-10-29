"""Typed response models for the events MCP server."""

from __future__ import annotations

import datetime as dt
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# demo     -> bundled synthetic fixture (relative dates) - NOT IIT Roorkee announcements
# imported -> snapshot of an official document (e.g. the academic calendar PDF), checked by an operator
# live     -> fetched from an upstream calendar API at request time
DataMode = Literal["demo", "imported", "live"]
EventStatus = Literal["scheduled", "cancelled", "rescheduled", "completed"]
RegistrationStatus = Literal["open", "closed", "not_required", "unknown"]
Timing = Literal["past", "ongoing", "upcoming"]


class SourceInfo(BaseModel):
    source_id: str = "events"
    mode: DataMode
    provider: str
    source_url: str | None = None
    retrieved_at: str | None = Field(default=None, description="UTC time this query was executed against the source.")
    data_as_of: str | None = Field(
        default=None,
        description="Upstream last-modified time or document date when the source provides one; null if unknown.",
    )
    stale: bool | None = None
    staleness_reason: str | None = None
    record_version: str | None = None
    timezone: str | None = Field(default=None, description="Campus timezone used for 'today' and date filters.")
    note: str | None = None


class EventSummary(BaseModel):
    event_id: str
    title: str
    category: str
    start: datetime
    end: datetime
    all_day: bool = False
    location: str | None = None
    status: EventStatus = "scheduled"
    timing: Timing | None = Field(default=None, description="Relative to the campus clock at query time.")
    origin: Literal["official", "synthetic", "calendar"] = Field(
        default="synthetic",
        description="official = taken from an IIT Roorkee document; synthetic = demo record; calendar = live feed.",
    )
    tentative: bool = Field(default=False, description="The source gives this date as tentative or undecided.")
    date_note: str | None = Field(default=None, description="Exactly how the source states an uncertain date.")


class EventDetails(EventSummary):
    description: str | None = None
    organizer: str | None = None
    tags: list[str] = Field(default_factory=list)
    online_url: str | None = None
    registration_required: bool | None = None
    registration_status: RegistrationStatus = "unknown"
    registration_deadline: datetime | None = None
    capacity: int | None = None
    recurrence: str | None = None
    original_start: datetime | None = Field(default=None, description="Previous start time of a rescheduled event.")
    original_end: datetime | None = None
    source_document: str | None = Field(default=None, description="Official document an 'official' record cites.")
    source_page: int | None = None
    source: SourceInfo


class EventList(BaseModel):
    count: int
    events: list[EventSummary]
    source: SourceInfo
    query: str | None = None
    date: dt.date | None = Field(default=None, description="Campus-local day queried (get_events_for_date).")
    range_start: datetime | None = None
    range_end: datetime | None = None
    excluded_statuses: list[EventStatus] = Field(default_factory=list)
    note: str | None = None
