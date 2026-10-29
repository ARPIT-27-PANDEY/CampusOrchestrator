"""Expanded demo catalogue: verified bibliographic metadata, synthetic holdings, topic search."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest

from library_mcp.campus_time import CampusClock
from library_mcp.provider import ALIASES, DEMO_DATA_PATH, DemoLibraryProvider

RAW = json.loads(DEMO_DATA_PATH.read_text(encoding="utf-8"))
NOW = datetime(2026, 10, 29, 4, 30, tzinfo=UTC)


@pytest.fixture
def lib() -> DemoLibraryProvider:
    return DemoLibraryProvider(DEMO_DATA_PATH, clock=CampusClock.fixed(NOW))


def test_size_and_discipline_coverage() -> None:
    assert 100 <= len(RAW["books"]) <= 200
    disciplines = {b["discipline"] for b in RAW["books"]}
    assert {"mechanical", "electrical", "civil", "computer science", "mathematics", "physics", "chemistry",
            "economics", "psychology", "entrepreneurship", "management", "communication", "history",
            "sociology", "fiction", "biography", "environment", "general science"} <= disciplines  # fmt: skip


def test_every_record_has_verifiable_metadata_and_synthetic_holdings() -> None:
    assert RAW["holdings"] == "synthetic" and "SYNTHETIC" in RAW["description"]
    for b in RAW["books"]:
        meta = b["metadata"]
        assert meta["provider"] == "Open Library" and meta["record_url"].startswith("https://openlibrary.org/works/")
        assert b["call_number"].startswith("DEMO-") and "Demo stacks" in b["location"]
        assert 0 <= b["available_copies"] <= b["total_copies"]
        assert all(len(i) == 13 and i.isdigit() for i in b["isbn_13"])


@pytest.mark.parametrize(
    ("query", "expected_tag"),
    [
        ("books about mechanics", "mechanics"),
        ("thermodynamics", "thermodynamics"),
        ("SOM", "strength of materials"),
        ("dbms", "databases"),
        ("signals and systems", "signals and systems"),
        ("geotechnical engineering", "geotechnical engineering"),
        ("linear algebra", "linear algebra"),
        ("entrepreneurship", "entrepreneurship"),
        ("biography", "biography"),
    ],
)
def test_subject_and_alias_queries(lib: DemoLibraryProvider, query: str, expected_tag: str) -> None:
    found = lib.search(query, limit=10)
    assert found.books, query
    assert found.matched_on in ("subject", "title", "keywords")
    if found.matched_on == "subject":
        # Subject-tier matches rank first; weaker keyword matches may follow them.
        accepted = {expected_tag, *ALIASES.get(query.split()[-1].lower(), [])}
        top = found.books[0]
        assert accepted & {*top.subjects, top.discipline or ""}, top.title


def test_exact_title_ranks_first(lib: DemoLibraryProvider) -> None:
    found = lib.search("Introduction to Algorithms")
    assert found.matched_on == "title" and found.books[0].title.lower().startswith("introduction to algorithms")


def test_identifier_lookups(lib: DemoLibraryProvider) -> None:
    book = RAW["books"][0]
    assert lib.search(book["book_id"]).matched_on == "identifier"
    isbn_book = next(b for b in RAW["books"] if b["isbn_13"])
    assert lib.search(isbn_book["isbn_13"][0]).books[0].book_id == isbn_book["book_id"]


def test_author_search(lib: DemoLibraryProvider) -> None:
    found = lib.search("Feynman", limit=10)
    assert found.books and all(any("Feynman" in a for a in b.authors) for b in found.books)


def test_no_fuzzy_false_positives(lib: DemoLibraryProvider) -> None:
    found = lib.search("underwater basket weaving")
    assert found.books == [] and found.message and "No title" in found.message


def test_filters(lib: DemoLibraryProvider) -> None:
    old = lib.search("physics", limit=20, year_to=1970)
    assert all(b.year is not None and b.year <= 1970 for b in old.books)
    mech = lib.search("design", limit=20, subject="mechanical")
    assert mech.books and all(b.discipline == "mechanical" for b in mech.books)


def test_due_dates_are_relative_to_the_campus_clock(lib: DemoLibraryProvider) -> None:
    book = next(b for b in RAW["books"] if b["due_in_days"])
    avail = lib.get_book_availability(book["book_id"])
    assert avail.next_due_date == date(2026, 10, 29).fromordinal(
        date(2026, 10, 29).toordinal() + min(book["due_in_days"])
    )
