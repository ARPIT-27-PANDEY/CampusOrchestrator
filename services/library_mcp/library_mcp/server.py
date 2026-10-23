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

from .models import BookAvailability, LibraryHours, SearchBooksResult
from .provider import BookNotFoundError, LibraryProvider, load_provider_from_env

SERVER_NAME = "campus-library"


def build_server(provider: LibraryProvider | None = None) -> MCPServer:
    """Create the MCP server. Inject ``provider`` in tests or alternative deployments."""
    prov = provider or load_provider_from_env()
    mcp = MCPServer(
        SERVER_NAME,
        version="0.1.0",
        instructions="Read-only access to the campus library catalogue, copy availability, and opening hours.",
    )

    @mcp.tool()
    def search_books(
        query: Annotated[str, Field(min_length=1, max_length=200, description="Title, subject, or keyword.")],
        author: Annotated[str | None, Field(max_length=100, description="Optional author name filter.")] = None,
        limit: Annotated[int, Field(ge=1, le=20, description="Maximum number of results.")] = 5,
    ) -> SearchBooksResult:
        """Search the library catalogue by title, subject or keyword, optionally filtered by author.

        Returns matching books with their book_id and copy counts.
        """
        books = prov.search_books(query, author, limit)
        return SearchBooksResult(query=query, author=author, count=len(books), books=books, source=prov.source_info())

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
            Field(description="ISO date (YYYY-MM-DD). Defaults to today in the server's timezone."),
        ] = None,
    ) -> LibraryHours:
        """Get the library's opening hours for a given date (defaults to today)."""
        return prov.get_library_hours(date or dt.date.today())

    @mcp.custom_route("/health", methods=["GET"])  # type: ignore[untyped-decorator]  # SDK decorator is untyped
    async def health(_: Request) -> JSONResponse:
        info = prov.source_info()
        return JSONResponse({"status": "ok", "server": SERVER_NAME, "source": info.model_dump()})

    return mcp
