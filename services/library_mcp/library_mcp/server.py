"""Library MCP server (MCP Python SDK v2, Streamable HTTP).

Run standalone with ``python -m library_mcp``. The server owns all library
integration logic; the CampusOS backend only sees the MCP tools it exposes.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from .campus_time import CampusClock
from .discovery import DiscoveryService, build_discovery_from_env
from .models import BookAvailability, LibraryHours, PublicBookSearchResult, SearchBooksResult, SourceInfo
from .provider import BookNotFoundError, LibraryProvider, load_provider_from_env

SERVER_NAME = "campus-library"
_NOT_SET = object()


def build_server(
    provider: LibraryProvider | None = None,
    clock: CampusClock | None = None,
    discovery: DiscoveryService | object | None = _NOT_SET,
) -> MCPServer:
    """Create the MCP server. Inject ``provider``/``clock``/``discovery`` in tests or other deployments.

    ``discovery=None`` disables public book discovery (the tool is then not registered at all).
    """
    prov = provider or load_provider_from_env(clock)
    campus_clock = clock or prov.clock
    disco = build_discovery_from_env(campus_clock) if discovery is _NOT_SET else discovery
    mcp = MCPServer(
        SERVER_NAME,
        version="0.1.0",
        instructions="Read-only access to the campus library catalogue, copy availability, and opening hours.",
    )

    @mcp.tool()
    def search_books(
        query: Annotated[
            str,
            Field(
                min_length=1,
                max_length=200,
                description="Title, ISBN, catalogue id, subject (e.g. 'mechanics'), or keywords.",
            ),
        ],
        author: Annotated[str | None, Field(max_length=100, description="Optional author name filter.")] = None,
        limit: Annotated[int, Field(ge=1, le=20, description="Maximum number of results.")] = 5,
        subject: Annotated[str | None, Field(max_length=60, description="Optional subject/discipline filter.")] = None,
        language: Annotated[str | None, Field(max_length=10, description="Optional language code, e.g. 'eng'.")] = None,
        published_after: Annotated[
            int | None, Field(ge=1000, le=2100, description="Earliest first-publication year.")
        ] = None,
        published_before: Annotated[
            int | None, Field(ge=1000, le=2100, description="Latest first-publication year.")
        ] = None,
    ) -> SearchBooksResult:
        """Search the CAMPUS library catalogue (holdings and copy counts) by title, subject, author or topic.

        Returns book_id and copy counts; use get_book_availability for shelf location and due dates.
        A miss means this catalogue has no match - it says nothing about books in general
        (use discover_public_books for that, when available)."""
        found = prov.search(
            query,
            author,
            limit,
            subject=subject,
            language=language,
            year_from=published_after,
            year_to=published_before,
        )
        return SearchBooksResult(
            query=query,
            author=author,
            count=len(found.books),
            books=found.books,
            matched_on=found.matched_on,
            search_mode=found.search_mode,
            suggestions=found.suggestions,
            message=found.message,
            source=prov.source_info(),
        )

    @mcp.tool()
    def get_book_availability(
        book_id: Annotated[
            str,
            Field(
                pattern=r"^[A-Za-z0-9-]{3,20}$",
                description="Catalogue id returned by search_books, e.g. LIB-0001.",
            ),
        ],
    ) -> BookAvailability:
        """Get copy availability, shelf location and next due date for one book by its book_id."""
        try:
            return prov.get_book_availability(book_id)
        except BookNotFoundError as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool()
    def get_library_hours(
        date: Annotated[
            dt.date | None,
            Field(description="ISO date (YYYY-MM-DD). Omit for today in the campus timezone (Asia/Kolkata)."),
        ] = None,
    ) -> LibraryHours:
        """Get the library's opening hours for a given date (defaults to today on campus)."""
        return prov.get_library_hours(date or campus_clock.today())

    if isinstance(disco, DiscoveryService):
        service = disco

        @mcp.tool()
        async def discover_public_books(
            query: Annotated[
                str, Field(min_length=2, max_length=200, description="Title, author or subject, e.g. 'thermodynamics'.")
            ],
            open_access_only: Annotated[
                bool, Field(description="Only books that are legally free to read or download in full.")
            ] = False,
            limit: Annotated[int, Field(ge=1, le=20, description="Maximum number of books.")] = 8,
        ) -> PublicBookSearchResult:
            """Search PUBLIC book metadata (Open Library, OpenStax, Google Books when configured) for any subject.

            This is NOT the campus library: it never says whether IIT Roorkee holds a copy. Each book has an
            access_type (open_access_download, open_access_read, borrow_online, preview_only, metadata_only)
            and only provider-supplied links. Use search_books for campus holdings."""
            books, statuses = await service.search(query, open_access_only=open_access_only, limit=limit)
            ok = [s.provider for s in statuses if s.status in ("ok", "cached")]
            return PublicBookSearchResult(
                query=query,
                open_access_only=open_access_only,
                count=len(books),
                books=books,
                providers=statuses,
                source=SourceInfo(
                    mode="live",
                    provider=",".join(ok) or "none",
                    retrieved_at=campus_clock.retrieved_at(),
                    stale=None,
                    staleness_reason="Live public metadata; access rights can change at the provider.",
                    timezone=campus_clock.tz.key,
                    note="Public bibliographic metadata, not IIT Roorkee holdings or circulation.",
                ),
            )

    @mcp.custom_route("/health", methods=["GET"])  # type: ignore[untyped-decorator]  # SDK decorator is untyped
    async def health(_: Request) -> JSONResponse:
        info = prov.source_info()
        return JSONResponse({"status": "ok", "server": SERVER_NAME, "source": info.model_dump()})

    return mcp
