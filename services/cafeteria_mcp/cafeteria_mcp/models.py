"""Typed response models for the cafeteria MCP server."""

from __future__ import annotations

import datetime as dt
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

# demo     -> bundled simulated fixture
# imported -> operator-supplied file snapshot (JSON/PDF); NOT verified against a live system
# live     -> fetched from an active upstream system at request time
DataMode = Literal["demo", "imported", "live"]


class SourceInfo(BaseModel):
    source_id: str = "cafeteria"
    mode: DataMode
    provider: str
    source_url: str | None = Field(default=None, description="Public page the menu was taken from, if any.")
    retrieved_at: str | None = Field(
        default=None, description="UTC time this response was produced from the menu snapshot (query time)."
    )
    imported_at: str | None = Field(default=None, description="UTC time an operator-supplied menu file was imported.")
    data_as_of: str | None = Field(
        default=None, description="Last verified update of the underlying menu source, when the source states it."
    )
    valid_from: date | None = None
    valid_to: date | None = None
    stale: bool | None = Field(
        default=False,
        description="True outside the declared validity window; null when currency cannot be determined.",
    )
    staleness_reason: str | None = None
    record_version: str | None = Field(default=None, description="sha256 prefix of the imported file, if any.")
    timezone: str | None = Field(default=None, description="Campus timezone used to decide 'today'.")
    note: str | None = None


class DiningLocation(BaseModel):
    id: str
    name: str
    hours: str | None = None
    default: bool = False


class MenuItem(BaseModel):
    name: str
    category: str
    meal: str | None = Field(default=None, description="breakfast | lunch | snacks | dinner | beverages ...")
    cuisine: str | None = None
    price: float
    currency: str
    vegetarian: bool | None = Field(default=None, description="As labelled by the menu source; null if unstated.")
    available_on: list[str] = Field(default_factory=list, description="Weekdays the item is served.")
    locations: list[str] = Field(default_factory=list, description="Dining locations serving the item.")


class TodayMenu(BaseModel):
    date: dt.date = Field(description="Menu date in the campus timezone (not the caller's or server OS date).")
    weekday: str
    cafeteria: str = Field(description="Dining location name.")
    location_id: str | None = None
    rotation_week: int = Field(default=1, description="Week of the menu rotation this date falls in.")
    meal: str | None = Field(default=None, description="Meal filter applied, if any.")
    items: list[MenuItem]
    note: str | None = None
    source: SourceInfo


class MenuSearchResult(BaseModel):
    query: str
    count: int
    items: list[MenuItem]
    source: SourceInfo


class ItemPrice(BaseModel):
    item_name: str
    found: bool
    price: float | None = None
    currency: str | None = None
    matched_item: str | None = None
    prices_by_location: dict[str, float] = Field(
        default_factory=dict, description="Set when the price differs between dining locations."
    )
    suggestions: list[str] = Field(default_factory=list)
    source: SourceInfo


class LocationList(BaseModel):
    locations: list[DiningLocation]
    source: SourceInfo
