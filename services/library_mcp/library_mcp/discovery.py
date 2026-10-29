"""Public book discovery: Open Library, OpenStax and (optionally) Google Books.

Kept strictly separate from the campus catalogue: nothing here says whether IIT Roorkee's
library holds a copy. Every result states its metadata provider and an explicit access type:

    open_access_download  legal free full copy (OpenStax CC-licensed PDF; Google Books public-domain PDF)
    open_access_read      free to read in full online (Open Library "public" scan; Google Books free/PD)
    borrow_online         controlled digital lending (Open Library "borrowable": account + waitlist)
    preview_only          partial preview (Google Books PARTIAL)
    metadata_only         record only (Open Library "printdisabled"/"no_ebook"; Google NO_PAGES)

Links are only those the provider returns; nothing is constructed or guessed except the
canonical record page and Internet Archive /details/ pages for identifiers the provider lists.

Usage policy: on-demand, human-scale queries only (no harvesting). Each provider has a minimum
interval between requests, one bounded retry for transient errors, a TTL cache and a timeout;
a failing provider yields a structured status while the others still return results.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from .campus_time import CampusClock
from .models import ProviderStatus, PublicBook

USER_AGENT = "CampusOrchestrator/0.2 (+https://github.com/ARPIT-27-PANDEY/CampusOrchestrator)"
_WORD = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "of", "and", "to", "in", "on", "for", "by", "with", "book", "books", "about", "free",
         "open", "access", "textbook", "textbooks", "pdf", "online", "read", "download"}  # fmt: skip


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, status: str = "error") -> None:
        super().__init__(message)
        self.status = status


def terms(text: str) -> list[str]:
    return [t for t in _WORD.findall(text.lower()) if t not in _STOP and len(t) > 1]


def _split_isbns(values: list[str], limit: int = 5) -> tuple[list[str], list[str]]:
    clean = [re.sub(r"[^0-9Xx]", "", v) for v in values]
    return [v for v in clean if len(v) == 10][:limit], [v for v in clean if len(v) == 13][:limit]


class Provider(Protocol):
    name: str
    min_interval_s: float

    async def search(self, query: str, limit: int, client: httpx.AsyncClient) -> list[PublicBook]: ...


class OpenLibraryProvider:
    name = "openlibrary"
    min_interval_s = 1.0
    URL = "https://openlibrary.org/search.json"
    FIELDS = ("key,title,author_name,first_publish_year,publisher,isbn,language,subject,ebook_access,ia,"
              "edition_count,number_of_pages_median")  # fmt: skip

    async def search(self, query: str, limit: int, client: httpx.AsyncClient) -> list[PublicBook]:
        resp = await client.get(self.URL, params={"q": query, "limit": str(limit), "fields": self.FIELDS})
        _raise_for(resp, self.name)
        docs = _json(resp, self.name).get("docs", [])
        return [self._book(d) for d in docs if d.get("title")]

    @staticmethod
    def _book(d: dict[str, Any]) -> PublicBook:
        isbn10, isbn13 = _split_isbns(list(d.get("isbn") or []))
        key = str(d.get("key", ""))
        ia = [str(x) for x in d.get("ia") or []]
        access = str(d.get("ebook_access") or "no_ebook")
        record = f"https://openlibrary.org{key}" if key.startswith("/works/") else None
        mapping: dict[str, tuple[str, str | None, str]] = {
            "public": ("open_access_read", f"https://archive.org/details/{ia[0]}" if ia else record,
                       "Open Library marks this scan as public: free to read online. No download link is verified."),
            "borrowable": ("borrow_online", record,
                           "Controlled digital lending via Open Library/Internet Archive: free account, one reader at a time."),
            "printdisabled": ("metadata_only", None,
                              "Scan available only to print-disabled readers; for others this is a record only."),
        }  # fmt: skip
        access_type, read_url, note = mapping.get(access, ("metadata_only", None, "No online copy listed."))
        return PublicBook(
            title=str(d["title"]),
            authors=[str(a) for a in (d.get("author_name") or [])][:6],
            publisher=(d.get("publisher") or [None])[0],
            published=str(d["first_publish_year"]) if d.get("first_publish_year") else None,
            isbn_10=isbn10,
            isbn_13=isbn13,
            identifiers={"openlibrary_work": key.rsplit("/", 1)[-1]} if key else {},
            subjects=[str(s) for s in (d.get("subject") or [])][:8],
            language=[str(x) for x in (d.get("language") or [])][:4],
            metadata_provider="Open Library",
            record_url=record,
            access_type=access_type,  # type: ignore[arg-type]
            read_url=read_url,
            access_notes=note,
        )


class GoogleBooksProvider:
    """Optional. Works without a key at low volume; set GOOGLE_BOOKS_API_KEY for quota. Key never logged."""

    name = "googlebooks"
    min_interval_s = 1.0
    URL = "https://www.googleapis.com/books/v1/volumes"

    def __init__(self, api_key: str | None = None) -> None:
        self._key = api_key

    async def search(self, query: str, limit: int, client: httpx.AsyncClient) -> list[PublicBook]:
        params = {"q": query, "maxResults": str(min(limit, 40)), "printType": "books"}
        if self._key:
            params["key"] = self._key
        resp = await client.get(self.URL, params=params)
        _raise_for(resp, self.name)
        return [
            self._book(i) for i in _json(resp, self.name).get("items", []) if (i.get("volumeInfo") or {}).get("title")
        ]

    @staticmethod
    def _book(item: dict[str, Any]) -> PublicBook:
        v = item.get("volumeInfo") or {}
        a = item.get("accessInfo") or {}
        sale = (item.get("saleInfo") or {}).get("saleability")
        ids = {x.get("type"): x.get("identifier") for x in v.get("industryIdentifiers") or []}
        public = bool(a.get("publicDomain"))
        view = a.get("viewability")
        download = None
        for fmt in ("pdf", "epub"):
            info = a.get(fmt) or {}
            if public and info.get("isAvailable") and info.get("downloadLink"):
                download = str(info["downloadLink"])
                break
        if download:
            access, note = "open_access_download", "Public-domain volume with a Google Books download link."
        elif view == "ALL_PAGES" and (public or sale == "FREE"):
            access, note = "open_access_read", "Full view on Google Books."
        elif view in ("PARTIAL", "ALL_PAGES"):
            access, note = "preview_only", "Google Books preview only - not a complete free copy."
        else:
            access, note = "metadata_only", "No preview available on Google Books."
        return PublicBook(
            title=str(v["title"]) + (f": {v['subtitle']}" if v.get("subtitle") else ""),
            authors=[str(x) for x in v.get("authors") or []][:6],
            publisher=v.get("publisher"),
            published=v.get("publishedDate"),
            isbn_10=[ids["ISBN_10"]] if ids.get("ISBN_10") else [],
            isbn_13=[ids["ISBN_13"]] if ids.get("ISBN_13") else [],
            identifiers={"google_books": str(item.get("id"))} if item.get("id") else {},
            subjects=[str(x) for x in v.get("categories") or []][:8],
            language=[str(v["language"])] if v.get("language") else [],
            metadata_provider="Google Books",
            record_url=v.get("infoLink") or v.get("canonicalVolumeLink"),
            access_type=access,  # type: ignore[arg-type]
            read_url=a.get("webReaderLink") if access == "open_access_read" else None,
            download_url=download,
            preview_url=v.get("previewLink") if access == "preview_only" else None,
            license="Public domain" if public else None,
            access_notes=note,
        )


class OpenStaxProvider:
    """Curated open textbooks (CC licensed). Fetches the catalogue once, then searches it locally."""

    name = "openstax"
    min_interval_s = 1.0
    URL = "https://openstax.org/apps/cms/api/v2/pages/"
    FIELDS = ("title,book_state,authors,high_resolution_pdf_url,webview_rex_link,license_name,license_url,"
              "publish_date,print_isbn_13,digital_isbn_13,book_subjects,book_categories")  # fmt: skip

    def __init__(self, catalogue_ttl_s: float = 86400.0) -> None:
        self._ttl = catalogue_ttl_s
        self._books: list[PublicBook] | None = None
        self._fetched = 0.0

    async def _catalogue(self, client: httpx.AsyncClient) -> list[PublicBook]:
        if self._books is not None and time.monotonic() - self._fetched < self._ttl:
            return self._books
        resp = await client.get(self.URL, params={"type": "books.Book", "fields": self.FIELDS, "limit": "250"})
        _raise_for(resp, self.name)
        items = _json(resp, self.name).get("items", [])
        self._books = [self._book(i) for i in items if i.get("book_state") == "live" and i.get("title")]
        self._fetched = time.monotonic()
        return self._books

    @staticmethod
    def _book(i: dict[str, Any]) -> PublicBook:
        subjects = sorted({s.get("subject_name", "") for s in i.get("book_subjects") or []} |
                          {c.get("subject_category", "") for c in i.get("book_categories") or []} - {""})  # fmt: skip
        pdf = i.get("high_resolution_pdf_url")
        isbn13 = [re.sub(r"[^0-9]", "", x) for x in (i.get("print_isbn_13"), i.get("digital_isbn_13")) if x]
        return PublicBook(
            title=str(i["title"]),
            authors=[str((a.get("value") or {}).get("name")) for a in i.get("authors") or [] if (a.get("value") or {}).get("name")][:6],
            publisher="OpenStax (Rice University)",
            published=i.get("publish_date"),
            isbn_13=isbn13,
            identifiers={"openstax_slug": str((i.get("meta") or {}).get("slug"))} if (i.get("meta") or {}).get("slug") else {},
            subjects=subjects,
            language=["en"],
            metadata_provider="OpenStax",
            record_url=(i.get("meta") or {}).get("html_url"),
            access_type="open_access_download" if pdf else "open_access_read",
            read_url=i.get("webview_rex_link"),
            download_url=pdf,
            license=i.get("license_name"),
            license_url=i.get("license_url"),
            access_notes="Openly licensed textbook; free to read online and download.",
        )  # fmt: skip

    async def search(self, query: str, limit: int, client: httpx.AsyncClient) -> list[PublicBook]:
        wanted = terms(query)
        if not wanted:
            return []
        hits = []
        for b in await self._catalogue(client):
            hay = set(terms(" ".join([b.title, *b.subjects])))
            # Whole words (plural-tolerant) only: a prefix rule matched "physics" to "Physiology".
            score = sum(1 for t in wanted if t in hay or f"{t}s" in hay or t.rstrip("s") in hay)
            if score and score >= (len(wanted) + 1) // 2:
                hits.append((score, b))
        hits.sort(key=lambda x: (-x[0], x[1].title))
        return [b for _, b in hits[:limit]]


def _raise_for(resp: httpx.Response, provider: str) -> None:
    if resp.status_code == 429:
        raise ProviderError(f"{provider} rate limit (HTTP 429)", status="rate_limited")
    if resp.status_code >= 400:
        raise ProviderError(f"{provider} returned HTTP {resp.status_code}")


def _json(resp: httpx.Response, provider: str) -> dict[str, Any]:
    try:
        data = resp.json()
    except ValueError as exc:
        raise ProviderError(f"{provider} returned a malformed response") from exc
    if not isinstance(data, dict):
        raise ProviderError(f"{provider} returned an unexpected payload")
    return data


@dataclass
class _CacheEntry:
    at: float
    books: list[PublicBook]


class DiscoveryService:
    def __init__(
        self,
        providers: list[Provider],
        *,
        clock: CampusClock | None = None,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = 8.0,
        cache_ttl_s: float = 3600.0,
        cache_size: int = 256,
        max_retries: int = 1,
    ) -> None:
        self.providers = providers
        self.clock = clock or CampusClock()
        self._client = client
        self._timeout = timeout_s
        self._ttl = cache_ttl_s
        self._cache: OrderedDict[tuple[str, str, int], _CacheEntry] = OrderedDict()
        self._cache_size = cache_size
        self._retries = max_retries
        self._last_call: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {p.name: asyncio.Lock() for p in providers}

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout, headers={"User-Agent": USER_AGENT})
        return self._client

    def clear_cache(self) -> int:
        n = len(self._cache)
        self._cache.clear()
        return n

    async def _query(self, p: Provider, query: str, limit: int) -> tuple[list[PublicBook], ProviderStatus]:
        key = (p.name, " ".join(terms(query)) or query.lower().strip(), limit)
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit.at < self._ttl:
            return hit.books, ProviderStatus(provider=p.name, status="cached", count=len(hit.books))
        started = time.perf_counter()
        attempt = 0
        while True:
            attempt += 1
            try:
                async with self._locks[p.name]:  # polite: min interval between calls per provider
                    wait = p.min_interval_s - (time.monotonic() - self._last_call.get(p.name, -1e9))
                    if wait > 0:
                        await asyncio.sleep(wait)
                    self._last_call[p.name] = time.monotonic()
                    books = await asyncio.wait_for(p.search(query, limit, self._http()), self._timeout)
                break
            except TimeoutError:
                status, msg, transient = "timeout", f"{p.name} did not respond within {self._timeout:.0f}s", True
            except ProviderError as exc:
                status, msg, transient = exc.status, str(exc), exc.status == "error" and "HTTP 5" in str(exc)
            except httpx.HTTPError as exc:
                status, msg, transient = "error", f"{p.name} request failed ({type(exc).__name__})", True
            if not transient or attempt > self._retries:
                ms = round((time.perf_counter() - started) * 1000, 1)
                return [], ProviderStatus(provider=p.name, status=status, error=msg, duration_ms=ms)  # type: ignore[arg-type]
            await asyncio.sleep(0.5 * attempt)
        stamp = self.clock.retrieved_at()
        books = [b.model_copy(update={"retrieved_at": stamp}) for b in books]
        self._cache[key] = _CacheEntry(time.monotonic(), books)
        self._cache.move_to_end(key)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
        ms = round((time.perf_counter() - started) * 1000, 1)
        return books, ProviderStatus(provider=p.name, status="ok", count=len(books), duration_ms=ms)

    async def search(
        self, query: str, *, open_access_only: bool = False, limit: int = 10
    ) -> tuple[list[PublicBook], list[ProviderStatus]]:
        per_provider = max(limit, 10)
        outcomes = await asyncio.gather(*(self._query(p, query, per_provider) for p in self.providers))
        statuses = [s for _, s in outcomes]
        # Interleave providers so one source does not crowd out the others; open access first.
        rank = {"open_access_download": 0, "open_access_read": 1, "borrow_online": 2, "preview_only": 3,
                "metadata_only": 4, "unknown": 5}  # fmt: skip
        merged: list[PublicBook] = []
        seen: set[str] = set()
        lists = [books for books, _ in outcomes]
        for i in range(max((len(b) for b in lists), default=0)):
            for books in lists:
                if i < len(books):
                    b = books[i]
                    dedupe = (
                        b.isbn_13[0] if b.isbn_13 else ""
                    ) or f"{b.title.lower()}|{','.join(b.authors[:1]).lower()}"
                    if dedupe in seen:
                        continue
                    seen.add(dedupe)
                    merged.append(b)
        if open_access_only:
            merged = [b for b in merged if b.access_type in ("open_access_download", "open_access_read")]
        merged.sort(key=lambda b: rank[b.access_type])  # stable: keeps the interleaved relevance order
        return merged[:limit], statuses


def build_discovery_from_env(clock: CampusClock | None = None) -> DiscoveryService | None:
    """``PUBLIC_BOOK_PROVIDERS`` = comma list (default openlibrary,openstax). Empty string disables discovery."""
    raw = os.getenv("PUBLIC_BOOK_PROVIDERS", "openlibrary,openstax")
    names = [n.strip().lower() for n in raw.split(",") if n.strip()]
    if not names:
        return None
    providers: list[Provider] = []
    for n in names:
        if n == "openlibrary":
            providers.append(OpenLibraryProvider())
        elif n == "openstax":
            providers.append(OpenStaxProvider())
        elif n == "googlebooks":
            providers.append(GoogleBooksProvider(os.getenv("GOOGLE_BOOKS_API_KEY") or None))
        else:
            raise ValueError(f"Unknown public book provider {n!r} (openlibrary, openstax, googlebooks).")
    return DiscoveryService(
        providers,
        clock=clock,
        timeout_s=float(os.getenv("PUBLIC_BOOK_TIMEOUT_S", "8")),
        cache_ttl_s=float(os.getenv("PUBLIC_BOOK_CACHE_TTL_S", "3600")),
    )
