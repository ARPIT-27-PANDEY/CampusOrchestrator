"""Library data providers.

``LibraryProvider`` is the seam between the MCP tool layer and the campus
library system. The demo provider reads a bundled JSON fixture; a real
integration (e.g. a Koha/Alma/Folio REST client) implements the same protocol
and is selected with ``LIBRARY_PROVIDER``.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Any, Protocol

from .models import BookAvailability, BookSummary, LibraryHours, SourceInfo

DEMO_DATA_PATH = Path(__file__).parent / "data" / "demo_books.json"


class BookNotFoundError(LookupError):
    """Raised when a book id does not exist in the catalogue."""


class LibraryProvider(Protocol):
    def search_books(self, query: str, author: str | None, limit: int) -> list[BookSummary]: ...

    def get_book_availability(self, book_id: str) -> BookAvailability: ...

    def get_library_hours(self, day: date) -> LibraryHours: ...

    def source_info(self) -> SourceInfo: ...


_STOPWORDS = {"the", "a", "an", "of", "and", "to", "in", "on", "for", "by", "with", "book", "books", "is", "it"}


def _normalise(text: str) -> str:
    return " ".join(text.lower().split())


def _terms(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 1 and t not in _STOPWORDS]


class DemoLibraryProvider:
    """Deterministic in-memory catalogue backed by ``demo_books.json``."""

    def __init__(self, data_path: Path = DEMO_DATA_PATH) -> None:
        raw: dict[str, Any] = json.loads(data_path.read_text(encoding="utf-8"))
        self._books: list[dict[str, Any]] = raw["books"]
        self._hours: dict[str, Any] = raw["hours"]
        self._as_of: str | None = raw.get("data_as_of")

    def source_info(self) -> SourceInfo:
        return SourceInfo(
            mode="demo",
            provider="demo-json",
            data_as_of=self._as_of,
            note="Simulated catalogue availability for demonstration; not a live library feed.",
        )

    @staticmethod
    def _summary(book: dict[str, Any]) -> BookSummary:
        return BookSummary(
            book_id=book["book_id"],
            title=book["title"],
            authors=book["authors"],
            year=book.get("year"),
            edition=book.get("edition"),
            subjects=book.get("subjects", []),
            available_copies=book["available_copies"],
            total_copies=book["total_copies"],
        )

    def search_books(self, query: str, author: str | None, limit: int) -> list[BookSummary]:
        terms = _terms(query)
        author_q = _normalise(author) if author else None
        scored: list[tuple[int, dict[str, Any]]] = []
        for book in self._books:
            haystack_words = set(_terms(" ".join([book["title"], *book.get("subjects", []), *book["authors"]])))
            title = _normalise(book["title"])
            if author_q and not any(author_q in _normalise(a) for a in book["authors"]):
                continue
            score = 0
            if terms:
                if _normalise(query) in title:
                    score += 10
                matched = sum(1 for t in terms if t in haystack_words)
                # Require most query terms to match so "Lord of the Rings" doesn't match unrelated titles.
                if matched == 0 or matched < (len(terms) + 1) // 2:
                    continue
                score += matched
            scored.append((score, book))
        scored.sort(key=lambda item: (-item[0], item[1]["book_id"]))
        return [self._summary(b) for _, b in scored[:limit]]

    def get_book_availability(self, book_id: str) -> BookAvailability:
        for book in self._books:
            if book["book_id"] == book_id.upper():
                due = sorted(book.get("due_dates", []))
                return BookAvailability(
                    book_id=book["book_id"],
                    title=book["title"],
                    available=book["available_copies"] > 0,
                    available_copies=book["available_copies"],
                    total_copies=book["total_copies"],
                    location=book.get("location"),
                    call_number=book.get("call_number"),
                    next_due_date=date.fromisoformat(due[0]) if due else None,
                    source=self.source_info(),
                )
        raise BookNotFoundError(f"No book with id '{book_id}' exists in the catalogue.")

    def get_library_hours(self, day: date) -> LibraryHours:
        key = day.isoformat()
        closures: dict[str, str] = self._hours.get("closures", {})
        if key in closures:
            return LibraryHours(date=day, is_open=False, note=closures[key], source=self.source_info())
        special: dict[str, dict[str, str]] = self._hours.get("special", {})
        if key in special:
            s = special[key]
            return LibraryHours(
                date=day,
                is_open=True,
                open_time=s["open"],
                close_time=s["close"],
                note=s.get("note"),
                source=self.source_info(),
            )
        weekday = day.weekday()
        slot = "saturday" if weekday == 5 else "sunday" if weekday == 6 else "weekday"
        hours = self._hours[slot]
        return LibraryHours(
            date=day,
            is_open=True,
            open_time=hours["open"],
            close_time=hours["close"],
            note="Regular schedule (demo calendar)",
            source=self.source_info(),
        )


def load_provider_from_env() -> LibraryProvider:
    """Select the provider configured by ``LIBRARY_PROVIDER`` (default: ``demo``)."""
    name = os.getenv("LIBRARY_PROVIDER", "demo").lower()
    if name == "demo":
        path = os.getenv("LIBRARY_DEMO_DATA")
        return DemoLibraryProvider(Path(path)) if path else DemoLibraryProvider()
    raise ValueError(
        f"Unsupported LIBRARY_PROVIDER '{name}'. Implement LibraryProvider for your campus system "
        "and register it in library_mcp.provider.load_provider_from_env."
    )
