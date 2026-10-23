"""Events MCP server (MCP Python SDK v2, Streamable HTTP)."""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from .models import EventDetails, EventList
from .provider import EventNotFoundError, EventsProvider, EventsProviderError, load_provider_from_env

SERVER_NAME = "campus-events"


def build_server(provider: EventsProvider | None = None) -> MCPServer:
    prov = provider or load_provider_from_env()
    mcp = MCPServer(
        SERVER_NAME,
        version="0.1.0",
        instructions="Read-only access to campus events: workshops, lectures, competitions and the academic calendar.",
    )

    @mcp.tool()
    async def search_events(
        query: Annotated[
            str, Field(max_length=200, description="Keywords, e.g. 'AI workshop'. Empty string matches all events.")
        ],
        start_date: Annotated[
            dt.date | None, Field(description="Earliest event date (YYYY-MM-DD). Omit for upcoming events.")
        ] = None,
        end_date: Annotated[dt.date | None, Field(description="Latest event date (YYYY-MM-DD).")] = None,
    ) -> EventList:
        """Search campus events by keyword and optional date range. Results are sorted by start time."""
        if start_date and end_date and end_date < start_date:
            raise ToolError("end_date must be on or after start_date.")
        try:
            events = await prov.search_events(query, start_date, end_date, limit=10)
        except EventsProviderError as exc:
            raise ToolError(str(exc)) from exc
        return EventList(query=query, count=len(events), events=events, source=prov.source_info())

    @mcp.tool()
    async def get_upcoming_events(
        limit: Annotated[int, Field(ge=1, le=20, description="Maximum number of events.")] = 5,
    ) -> EventList:
        """List the next upcoming campus events in chronological order."""
        try:
            events = await prov.get_upcoming_events(limit)
        except EventsProviderError as exc:
            raise ToolError(str(exc)) from exc
        return EventList(count=len(events), events=events, source=prov.source_info())

    @mcp.tool()
    async def get_event_details(
        event_id: Annotated[
            str, Field(pattern=r"^[A-Za-z0-9_-]{3,128}$", description="Event id from search results, e.g. EVT-101.")
        ],
    ) -> EventDetails:
        """Get full details (description, organizer, registration) for one event."""
        try:
            return await prov.get_event_details(event_id)
        except (EventNotFoundError, EventsProviderError) as exc:
            raise ToolError(str(exc)) from exc

    @mcp.custom_route("/health", methods=["GET"])  # type: ignore[untyped-decorator]  # SDK decorator is untyped
    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "server": SERVER_NAME, "source": prov.source_info().model_dump()})

    return mcp
