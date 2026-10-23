"""Typed response models for the library MCP server.

Every response carries a ``source`` block so callers can tell demo data from a
live integration and see how fresh the data is.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

DataMode = Literal["demo", "live"]


class SourceInfo(BaseModel):
    source_id: str = "library"
    mode: DataMode
    provider: str
    data_as_of: str | None = Field(
        default=None, description="ISO date the underlying data was last refreshed, if known."
    )
    note: str | None = None


class BookSummary(BaseModel):
    book_id: str
    title: str
    authors: list[str]
    year: int | None = None
    edition: str | None = None
    subjects: list[str] = Field(default_factory=list)
    available_copies: int
    total_copies: int


class SearchBooksResult(BaseModel):
    query: str
    author: str | None = None
    count: int
    books: list[BookSummary]
    source: SourceInfo


class BookAvailability(BaseModel):
    book_id: str
    title: str
    available: bool
    available_copies: int
    total_copies: int
    location: str | None = None
    call_number: str | None = None
    next_due_date: date | None = Field(default=None, description="Earliest due date among checked-out copies, if any.")
    source: SourceInfo


class LibraryHours(BaseModel):
    date: date
    is_open: bool
    open_time: str | None = None
    close_time: str | None = None
    note: str | None = None
    source: SourceInfo
