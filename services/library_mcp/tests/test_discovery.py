"""Public book discovery: access-type mapping, partial failure, caching, rate limits - no network."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from mcp import Client

from library_mcp.campus_time import CampusClock
from library_mcp.discovery import (
    DiscoveryService,
    GoogleBooksProvider,
    OpenLibraryProvider,
    OpenStaxProvider,
    build_discovery_from_env,
)
from library_mcp.provider import DemoLibraryProvider
from library_mcp.server import build_server

NOW = datetime(2026, 10, 29, 4, 30, tzinfo=UTC)

OL_DOCS = {
    "numFound": 3,
    "docs": [
        {"key": "/works/OL1W", "title": "Thermodynamics", "author_name": ["Yunus A. Cengel"], "first_publish_year": 1989,
         "publisher": ["McGraw-Hill"], "isbn": ["0070116636", "9780070116634"], "language": ["eng"],
         "ebook_access": "borrowable", "ia": ["thermodynamicsen00ceng"]},
        {"key": "/works/OL2W", "title": "Principles of Thermodynamics", "author_name": ["A. Author"],
         "ebook_access": "public", "ia": ["principlesofther00auth"]},
        {"key": "/works/OL3W", "title": "Fundamentals of Engineering Thermodynamics", "author_name": ["Moran"],
         "ebook_access": "printdisabled", "ia": ["fundamentalsofen00mora"]},
        {"key": "/works/OL4W", "title": "Thermo Notes", "author_name": ["X"], "ebook_access": "no_ebook"},
    ],
}  # fmt: skip
OPENSTAX = {
    "items": [
        {"title": "University Physics Volume 2", "book_state": "live",
         "meta": {"slug": "university-physics-volume-2", "html_url": "https://openstax.org/details/books/university-physics-volume-2"},
         "authors": [{"value": {"name": "Samuel J. Ling"}}], "high_resolution_pdf_url": "https://assets.openstax.org/x/UP2.pdf",
         "webview_rex_link": "https://openstax.org/books/university-physics-volume-2/pages/1-introduction",
         "license_name": "Creative Commons Attribution License", "license_url": "https://creativecommons.org/licenses/by/4.0/",
         "publish_date": "2016-10-06", "print_isbn_13": "978-1-938168-16-1",
         "book_subjects": [{"subject_name": "Science"}], "book_categories": [{"subject_category": "Physics"}]},
        {"title": "Old Physics", "book_state": "retired", "meta": {}, "book_subjects": [{"subject_name": "Science"}]},
    ]
}  # fmt: skip
GOOGLE = {
    "items": [
        {"id": "pd1", "volumeInfo": {"title": "Theory of Heat", "authors": ["J. C. Maxwell"], "publishedDate": "1872",
                                     "infoLink": "https://books.google.com/books?id=pd1"},
         "accessInfo": {"publicDomain": True, "viewability": "ALL_PAGES", "webReaderLink": "https://play.google.com/x",
                        "pdf": {"isAvailable": True, "downloadLink": "https://books.google.com/books/download/pd1.pdf"}}},
        {"id": "pv1", "volumeInfo": {"title": "Heat Transfer", "authors": ["J. P. Holman"], "previewLink": "https://books.google.com/p",
                                     "industryIdentifiers": [{"type": "ISBN_13", "identifier": "9780073529363"}]},
         "accessInfo": {"publicDomain": False, "viewability": "PARTIAL"}, "saleInfo": {"saleability": "FOR_SALE"}},
        {"id": "nv1", "volumeInfo": {"title": "Steam Tables"}, "accessInfo": {"viewability": "NO_PAGES"}},
    ]
}  # fmt: skip


def _transport(routes: dict[str, Any], calls: list[str] | None = None) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request.url.host)
        for host, reply in routes.items():
            if request.url.host == host:
                return reply(request) if callable(reply) else httpx.Response(200, json=reply)
        return httpx.Response(404)

    return httpx.MockTransport(handle)


def _service(
    routes: dict[str, Any], providers: list[Any] | None = None, calls: list[str] | None = None
) -> DiscoveryService:
    for p in providers or []:
        p.min_interval_s = 0.0
    return DiscoveryService(
        providers or [OpenLibraryProvider(), OpenStaxProvider()],
        clock=CampusClock.fixed(NOW),
        client=httpx.AsyncClient(transport=_transport(routes, calls)),
    )


def _fast(*providers: Any) -> list[Any]:
    for p in providers:
        p.min_interval_s = 0.0
    return list(providers)


async def test_open_library_access_types_are_mapped_conservatively() -> None:
    svc = _service({"openlibrary.org": OL_DOCS}, _fast(OpenLibraryProvider()))
    books, statuses = await svc.search("thermodynamics", limit=10)
    by_title = {b.title: b for b in books}
    assert by_title["Thermodynamics"].access_type == "borrow_online"
    assert by_title["Thermodynamics"].download_url is None  # borrowing is never a download
    assert by_title["Principles of Thermodynamics"].access_type == "open_access_read"
    assert by_title["Principles of Thermodynamics"].read_url == "https://archive.org/details/principlesofther00auth"
    assert by_title["Fundamentals of Engineering Thermodynamics"].access_type == "metadata_only"
    assert by_title["Thermo Notes"].access_type == "metadata_only"
    assert by_title["Thermodynamics"].isbn_13 == ["9780070116634"] and by_title["Thermodynamics"].isbn_10 == [
        "0070116636"
    ]
    assert all(b.retrieved_at == "2026-10-29T04:30:00Z" for b in books)
    assert statuses[0].status == "ok"


async def test_openstax_only_live_books_with_licensed_downloads() -> None:
    svc = _service({"openstax.org": OPENSTAX}, _fast(OpenStaxProvider()))
    books, _ = await svc.search("physics", limit=5)
    assert [b.title for b in books] == ["University Physics Volume 2"]
    b = books[0]
    assert b.access_type == "open_access_download" and b.download_url and b.license_url
    assert b.isbn_13 == ["9781938168161"]


async def test_google_preview_is_never_reported_as_free_download() -> None:
    svc = _service({"www.googleapis.com": GOOGLE}, _fast(GoogleBooksProvider()))
    books, _ = await svc.search("heat", limit=5)
    kinds = {b.title: b.access_type for b in books}
    assert kinds == {
        "Theory of Heat": "open_access_download",
        "Heat Transfer": "preview_only",
        "Steam Tables": "metadata_only",
    }
    preview = next(b for b in books if b.title == "Heat Transfer")
    assert preview.download_url is None and preview.read_url is None and preview.preview_url


async def test_one_failing_provider_does_not_hide_the_others() -> None:
    routes = {"openlibrary.org": lambda r: httpx.Response(503), "openstax.org": OPENSTAX}
    svc = _service(routes, _fast(OpenLibraryProvider(), OpenStaxProvider()))
    books, statuses = await svc.search("physics", limit=5)
    assert [b.metadata_provider for b in books] == ["OpenStax"]
    status = {s.provider: s for s in statuses}
    assert status["openlibrary"].status == "error" and "503" in (status["openlibrary"].error or "")
    assert status["openstax"].status == "ok"


async def test_rate_limit_is_reported_and_not_retried() -> None:
    calls: list[str] = []
    svc = _service({"www.googleapis.com": lambda r: httpx.Response(429)}, _fast(GoogleBooksProvider()), calls)
    books, statuses = await svc.search("heat", limit=5)
    assert books == [] and statuses[0].status == "rate_limited"
    assert len(calls) == 1


async def test_transient_error_is_retried_once() -> None:
    calls: list[str] = []
    state = {"n": 0}

    def flaky(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        return httpx.Response(502) if state["n"] == 1 else httpx.Response(200, json=OL_DOCS)

    svc = _service({"openlibrary.org": flaky}, _fast(OpenLibraryProvider()), calls)
    books, statuses = await svc.search("thermodynamics")
    assert books and statuses[0].status == "ok" and len(calls) == 2


async def test_results_are_cached_per_query() -> None:
    calls: list[str] = []
    svc = _service({"openlibrary.org": OL_DOCS}, _fast(OpenLibraryProvider()), calls)
    await svc.search("thermodynamics")
    _, statuses = await svc.search("Thermodynamics")
    assert statuses[0].status == "cached" and len(calls) == 1
    assert svc.clear_cache() == 1


async def test_open_access_filter() -> None:
    svc = _service({"openlibrary.org": OL_DOCS}, _fast(OpenLibraryProvider()))
    books, _ = await svc.search("thermodynamics", open_access_only=True)
    assert [b.title for b in books] == ["Principles of Thermodynamics"]


async def test_malformed_payload_is_a_provider_error() -> None:
    svc = _service({"openlibrary.org": lambda r: httpx.Response(200, content=b"<html>")}, _fast(OpenLibraryProvider()))
    books, statuses = await svc.search("x y")
    assert books == [] and statuses[0].status == "error" and "malformed" in (statuses[0].error or "")


def test_env_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUBLIC_BOOK_PROVIDERS", "")
    assert build_discovery_from_env() is None
    monkeypatch.setenv("PUBLIC_BOOK_PROVIDERS", "openlibrary,googlebooks")
    svc = build_discovery_from_env()
    assert svc is not None and [p.name for p in svc.providers] == ["openlibrary", "googlebooks"]
    monkeypatch.setenv("PUBLIC_BOOK_PROVIDERS", "scrapeeverything")
    with pytest.raises(ValueError):
        build_discovery_from_env()


async def test_tool_is_separate_from_campus_catalogue() -> None:
    svc = _service({"openlibrary.org": OL_DOCS}, _fast(OpenLibraryProvider()))
    server = build_server(DemoLibraryProvider(clock=CampusClock.fixed(NOW)), discovery=svc)
    async with Client(server) as client:
        names = {t.name for t in (await client.list_tools()).tools}
        assert "discover_public_books" in names and "search_books" in names
        res = await client.call_tool("discover_public_books", {"query": "thermodynamics"})
        data = res.structured_content
        assert data is not None and data["count"] == 4
        assert "not IIT Roorkee" in data["note"] and data["source"]["mode"] == "live"
        assert data["providers"][0]["provider"] == "openlibrary"


async def test_discovery_disabled_hides_the_tool() -> None:
    async with Client(build_server(DemoLibraryProvider(), discovery=None)) as client:
        assert "discover_public_books" not in {t.name for t in (await client.list_tools()).tools}
