"""Typed response models for the library MCP server.

Every response carries a ``source`` block so callers can tell demo data from a
live integration and see how fresh the data is.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

DataMode = Literal["demo", "imported", "live"]


class SourceInfo(BaseModel):
    source_id: str = "library"
    mode: DataMode
    provider: str
    source_url: str | None = None
    retrieved_at: str | None = Field(default=None, description="UTC time this lookup was executed.")
    data_as_of: str | None = Field(
        default=None, description="Date the underlying catalogue data was last updated, if known (not the query time)."
    )
    circulation_as_of: str | None = Field(
        default=None, description="Date the copy-availability figures refer to, if known."
    )
    stale: bool | None = None
    staleness_reason: str | None = None
    record_version: str | None = None
    timezone: str | None = Field(default=None, description="Campus timezone used for default dates.")
    note: str | None = None


class BookSummary(BaseModel):
    book_id: str
    title: str
    authors: list[str]
    year: int | None = None
    edition: str | None = None
    publisher: str | None = None
    isbn_13: list[str] = Field(default_factory=list)
    discipline: str | None = None
    subjects: list[str] = Field(default_factory=list)
    language: list[str] = Field(default_factory=list)
    available_copies: int = Field(description="SYNTHETIC in the demo catalogue.")
    total_copies: int = Field(description="SYNTHETIC in the demo catalogue.")
    metadata_url: str | None = Field(default=None, description="Where the bibliographic record was verified.")


class SearchBooksResult(BaseModel):
    query: str
    author: str | None = None
    count: int
    books: list[BookSummary]
    matched_on: str | None = Field(
        default=None,
        description="identifier | title | author | subject | keywords | semantic | hybrid - how the query matched.",
    )
    search_mode: str = Field(
        default="keyword", description="keyword, or hybrid:<embedder> when embedding similarity is fused in."
    )
    suggestions: list[str] = Field(
        default_factory=list, description="Related subjects held in the catalogue when nothing matched."
    )
    message: str | None = None
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


AccessType = Literal[
    "open_access_download",  # a legal, freely downloadable full copy (e.g. CC-licensed OpenStax PDF)
    "open_access_read",  # free to read online in full, no verified download
    "borrow_online",  # controlled digital lending (account, waiting list)
    "preview_only",  # partial preview (e.g. Google Books PARTIAL)
    "metadata_only",  # bibliographic record only; no verified way to read it
    "unknown",
]


class PublicBook(BaseModel):
    """A book from a public metadata provider. Says nothing about IIT Roorkee library holdings."""

    title: str
    authors: list[str] = Field(default_factory=list)
    publisher: str | None = None
    published: str | None = Field(default=None, description="Publication year or date as the provider gives it.")
    edition: str | None = None
    isbn_10: list[str] = Field(default_factory=list)
    isbn_13: list[str] = Field(default_factory=list)
    identifiers: dict[str, str] = Field(default_factory=dict, description="Provider ids, e.g. openlibrary_work.")
    subjects: list[str] = Field(default_factory=list)
    language: list[str] = Field(default_factory=list)
    metadata_provider: str
    record_url: str | None = Field(default=None, description="Canonical record page at the provider.")
    access_type: AccessType = "unknown"
    read_url: str | None = None
    download_url: str | None = None
    preview_url: str | None = None
    license: str | None = None
    license_url: str | None = None
    access_notes: str | None = None
    retrieved_at: str | None = None


class ProviderStatus(BaseModel):
    provider: str
    status: Literal["ok", "error", "timeout", "rate_limited", "disabled", "cached"]
    count: int = 0
    error: str | None = None
    duration_ms: float | None = None


class PublicBookSearchResult(BaseModel):
    query: str
    open_access_only: bool = False
    count: int
    books: list[PublicBook]
    providers: list[ProviderStatus] = Field(description="Which public sources were searched and how each fared.")
    note: str = (
        "Public bibliographic metadata, not IIT Roorkee library holdings. Use search_books for the campus "
        "catalogue. Only open_access_download/open_access_read links are free full copies."
    )
    source: SourceInfo


class LibraryHours(BaseModel):
    date: date
    is_open: bool
    open_time: str | None = None
    close_time: str | None = None
    note: str | None = None
    source: SourceInfo
