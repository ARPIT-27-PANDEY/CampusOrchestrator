"""Library data providers.

``LibraryProvider`` is the seam between the MCP tool layer and the campus
library system. The demo provider reads a bundled JSON fixture; a real
integration (e.g. a Koha/Alma/Folio REST client) implements the same protocol
and is selected with ``LIBRARY_PROVIDER``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Protocol

from .campus_time import CampusClock
from .models import BookAvailability, BookSummary, LibraryHours, SourceInfo
from .semantic import SemanticIndex, rrf_fuse, semantic_from_env

DEMO_DATA_PATH = Path(__file__).parent / "data" / "demo_books.json"


class BookNotFoundError(LookupError):
    """Raised when a book id does not exist in the catalogue."""


class LibraryProvider(Protocol):
    clock: CampusClock

    def search_books(self, query: str, author: str | None, limit: int) -> list[BookSummary]: ...

    def search(
        self,
        query: str,
        author: str | None = None,
        limit: int = 5,
        *,
        subject: str | None = None,
        language: str | None = None,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> CatalogueSearch: ...

    def get_book_availability(self, book_id: str) -> BookAvailability: ...

    def get_library_hours(self, day: date) -> LibraryHours: ...

    def source_info(self) -> SourceInfo: ...


_STOPWORDS = {
    "the", "a", "an", "of", "and", "to", "in", "on", "for", "by", "with", "book", "books", "is", "it", "about",
    "any", "some", "textbook", "textbooks", "related", "topic", "topics", "do", "you", "have", "library",
}  # fmt: skip

# Common student shorthand -> catalogue subject terms. Expansion only; never fuzzy matching.
ALIASES: dict[str, list[str]] = {
    "som": ["strength of materials", "mechanics of materials"],
    "mom": ["mechanics of materials"],
    "thermo": ["thermodynamics"],
    "fm": ["fluid mechanics"],
    "ht": ["heat transfer"],
    "tom": ["theory of machines"],
    "dsa": ["data structures", "algorithms"],
    "algo": ["algorithms"],
    "os": ["operating systems"],
    "dbms": ["databases"],
    "cn": ["computer networks"],
    "ml": ["machine learning"],
    "ai": ["artificial intelligence"],
    "dl": ["deep learning"],
    "dsp": ["signal processing"],
    "s&s": ["signals and systems"],
    "emt": ["electromagnetics"],
    "pe": ["power electronics"],
    "rcc": ["concrete"],
    "geotech": ["geotechnical engineering"],
    "la": ["linear algebra"],
    "stats": ["statistics"],
    "eco": ["economics"],
    "psych": ["psychology"],
    "mechanics": ["mechanics", "statics", "dynamics", "engineering mechanics"],
    "electronics": ["electronics", "digital electronics", "analog electronics"],
    "civil": ["structural engineering", "geotechnical engineering", "hydraulics", "transportation engineering", "surveying"],
    "biography": ["biography", "autobiography"],
    "novel": ["fiction"],
    "novels": ["fiction"],
    "environment": ["environment", "environmental studies", "ecology"],
    "climate": ["climate", "climate change"],
}  # fmt: skip
_ISBN = re.compile(r"^(97[89])?\d{9}[\dXx]$")


def _normalise(text: str) -> str:
    return " ".join(text.lower().split())


def _terms(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9&]+", text.lower()) if len(t) > 1 and t not in _STOPWORDS]


@dataclass
class CatalogueSearch:
    books: list[BookSummary]
    matched_on: str | None = None
    suggestions: list[str] = field(default_factory=list)
    message: str | None = None
    search_mode: str = "keyword"


class DemoLibraryProvider:
    """Deterministic in-memory catalogue backed by ``demo_books.json``."""

    def __init__(self, data_path: Path = DEMO_DATA_PATH, clock: CampusClock | None = None) -> None:
        text = data_path.read_text(encoding="utf-8")
        raw: dict[str, Any] = json.loads(text)
        self._books: list[dict[str, Any]] = raw["books"]
        self._hours: dict[str, Any] = raw["hours"]
        self._as_of: str | None = raw.get("data_as_of")
        self._version = hashlib.sha256(text.encode()).hexdigest()[:12]
        self.clock = clock or CampusClock()
        self.semantic: SemanticIndex | None = None

    @property
    def books(self) -> list[dict[str, Any]]:
        return self._books

    def enable_semantic(self, index: SemanticIndex | None) -> None:
        """Turn on hybrid (keyword + embedding) ranking; ``None`` keeps keyword-only search."""
        self.semantic = index

    @property
    def search_mode(self) -> str:
        return self.semantic.label if self.semantic else "keyword"

    def source_info(self) -> SourceInfo:
        return SourceInfo(
            mode="demo",
            provider="demo-json",
            retrieved_at=self.clock.retrieved_at(),
            data_as_of=self._as_of,
            circulation_as_of=self._as_of,
            stale=None,
            staleness_reason="Synthetic holdings and circulation: not connected to the IIT Roorkee library system.",
            record_version=self._version,
            timezone=self.clock.tz.key,
            note=(
                "Demo catalogue: copies, shelf locations, due dates and opening hours are simulated. "
                "They do not describe the IIT Roorkee library's real holdings."
            ),
        )

    @staticmethod
    def _summary(book: dict[str, Any]) -> BookSummary:
        meta = book.get("metadata") or {}
        return BookSummary(
            book_id=book["book_id"],
            title=book["title"],
            authors=book["authors"],
            year=book.get("year"),
            edition=book.get("edition"),
            publisher=book.get("publisher"),
            isbn_13=book.get("isbn_13", []),
            discipline=book.get("discipline"),
            subjects=book.get("subjects", []),
            language=book.get("language", []),
            available_copies=book["available_copies"],
            total_copies=book["total_copies"],
            metadata_url=meta.get("record_url"),
        )

    def _subjects(self) -> list[str]:
        return sorted({s for b in self._books for s in [*b.get("subjects", []), b.get("discipline") or ""] if s})

    def search_books(self, query: str, author: str | None, limit: int) -> list[BookSummary]:
        return self.search(query, author, limit).books

    def search(
        self,
        query: str,
        author: str | None = None,
        limit: int = 5,
        *,
        subject: str | None = None,
        language: str | None = None,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> CatalogueSearch:
        """Tiered matching: identifier > exact/prefix title > subject (with aliases) > author > keywords.

        Keyword matching needs most query words to appear; there is no fuzzy matching, so a miss is an
        honest empty result (with related subjects as suggestions) rather than unrelated titles.
        With a semantic index (hybrid mode), identifier and title hits stay exact; otherwise the keyword
        ranking is fused (RRF) with books whose embedding similarity clears the index threshold.
        """
        q_norm = _normalise(query)
        compact = re.sub(r"[^0-9xX]", "", query)
        author_q = _normalise(author) if author else None
        subject_q = _normalise(subject) if subject else None

        def allowed(book: dict[str, Any]) -> bool:
            if author_q and not any(author_q in _normalise(a) for a in book["authors"]):
                return False
            if subject_q and not any(
                subject_q in _normalise(s) for s in [*book.get("subjects", []), book.get("discipline") or ""]
            ):
                return False
            if language and book.get("language") and language.lower()[:3] not in [x[:3] for x in book["language"]]:
                return False
            year = book.get("year")
            if year_from and (year is None or year < year_from):
                return False
            return not (year_to and (year is None or year > year_to))

        mode = self.search_mode
        pool = [b for b in self._books if allowed(b)]
        if query.strip().upper() in {b["book_id"] for b in pool}:
            hit = [b for b in pool if b["book_id"] == query.strip().upper()]
            return CatalogueSearch([self._summary(b) for b in hit], "identifier", search_mode=mode)
        if _ISBN.match(compact):
            hit = [b for b in pool if compact in b.get("isbn_13", [])]
            if hit:
                return CatalogueSearch([self._summary(b) for b in hit[:limit]], "identifier", search_mode=mode)

        words = _terms(query)
        expanded: list[str] = []
        for w in words:
            expanded.extend(ALIASES.get(w, []))
        phrases = [*expanded, " ".join(words)] if words else []
        scored: list[tuple[int, str, dict[str, Any]]] = []
        for book in pool:
            title = _normalise(book["title"])
            subjects = [_normalise(s) for s in [*book.get("subjects", []), book.get("discipline") or ""]]
            hay = set(_terms(" ".join([book["title"], *book.get("subjects", []), *book["authors"]])))
            if not words:
                scored.append((0, "filter", book))
                continue
            # Exact title always wins; a title *prefix* only counts for multi-word queries, so a broad
            # one-word subject ("mechanics") ranks by subject rather than by whichever title starts with it.
            if q_norm and (title == q_norm or (len(words) > 1 and title.startswith(q_norm))):
                scored.append((100 if title == q_norm else 80, "title", book))
                continue
            subj_hits = sum(1 for p in phrases if p and any(p == s or p in s.split(" / ") for s in subjects))
            if subj_hits:
                scored.append((50 + subj_hits, "subject", book))
                continue
            if any(_normalise(a).split()[-1:] == words[-1:] for a in book["authors"]) and len(words) <= 2:
                scored.append((40, "author", book))
                continue
            matched = sum(1 for t in words if t in hay or any(t in s for s in subjects))
            if matched and matched >= max(1, (len(words) * 2 + 2) // 3):  # at least two thirds of the words
                scored.append((10 + matched + (5 if q_norm in title else 0), "keywords", book))
        scored.sort(key=lambda x: (-x[0], x[2]["book_id"]))
        if self.semantic is not None and words and not (scored and scored[0][1] == "title"):
            semantic = self.semantic.rank(query, [b["book_id"] for b in pool])
            if semantic:
                by_id = {b["book_id"]: b for b in pool}
                fused = rrf_fuse([b["book_id"] for _, _, b in scored], [bid for bid, _ in semantic])[:limit]
                how = "hybrid" if scored else "semantic"
                return CatalogueSearch([self._summary(by_id[bid]) for bid in fused], how, search_mode=mode)
        if scored:
            top = scored[:limit]
            return CatalogueSearch([self._summary(b) for _, _, b in top], top[0][1], search_mode=mode)
        related = [s for s in self._subjects() if any(w[:4] in s for w in words if len(w) > 3)][:5]
        return CatalogueSearch(
            [],
            None,
            related,
            f"No title, subject or author in the campus catalogue matches '{query}'.",
            search_mode=mode,
        )

    def get_book_availability(self, book_id: str) -> BookAvailability:
        for book in self._books:
            if book["book_id"] == book_id.upper():
                today = self.clock.today()
                due = sorted(
                    [*book.get("due_dates", []), *[(today + timedelta(days=int(d))).isoformat() for d in
                                                   book.get("due_in_days", [])]]
                )  # fmt: skip
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


def load_provider_from_env(clock: CampusClock | None = None) -> LibraryProvider:
    """Select the provider configured by ``LIBRARY_PROVIDER`` (default: ``demo``)."""
    name = os.getenv("LIBRARY_PROVIDER", "demo").lower()
    if name == "demo":
        path = os.getenv("LIBRARY_DEMO_DATA")
        provider = DemoLibraryProvider(Path(path), clock=clock) if path else DemoLibraryProvider(clock=clock)
        provider.enable_semantic(semantic_from_env(provider.books))
        return provider
    raise ValueError(
        f"Unsupported LIBRARY_PROVIDER '{name}'. Implement LibraryProvider for your campus system "
        "and register it in library_mcp.provider.load_provider_from_env."
    )
