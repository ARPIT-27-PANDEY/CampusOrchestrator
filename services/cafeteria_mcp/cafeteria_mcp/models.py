"""Typed response models for the cafeteria MCP server."""

from __future__ import annotations

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
    data_as_of: str | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    stale: bool = Field(default=False, description="True when today is outside the menu's declared validity window.")
    note: str | None = None


class MenuItem(BaseModel):
    name: str
    category: str
    price: float
    currency: str
    vegetarian: bool | None = None
    available_on: list[str] = Field(default_factory=list, description="Weekdays the item is served.")


class TodayMenu(BaseModel):
    date: date
    weekday: str
    cafeteria: str
    items: list[MenuItem]
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
    suggestions: list[str] = Field(default_factory=list)
    source: SourceInfo
