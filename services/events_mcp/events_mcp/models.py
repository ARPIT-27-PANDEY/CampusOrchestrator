"""Typed response models for the events MCP server."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

DataMode = Literal["demo", "live"]


class SourceInfo(BaseModel):
    source_id: str = "events"
    mode: DataMode
    provider: str
    data_as_of: str | None = None
    note: str | None = None


class EventSummary(BaseModel):
    event_id: str
    title: str
    category: str
    start: datetime
    end: datetime
    location: str | None = None


class EventDetails(EventSummary):
    description: str | None = None
    organizer: str | None = None
    tags: list[str] = Field(default_factory=list)
    registration_required: bool | None = None
    capacity: int | None = None
    source: SourceInfo


class EventList(BaseModel):
    count: int
    events: list[EventSummary]
    source: SourceInfo
    query: str | None = None
