"""Events MCP server (MCP Python SDK v2, Streamable HTTP)."""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from .campus_time import CampusClock
from .catalog import EventCatalog
from .models import EventDetails, EventList
from .provider import EventNotFoundError, EventsProvider, EventsProviderError, load_provider_from_env

SERVER_NAME = "campus-events"


def build_server(provider: EventsProvider | None = None, clock: CampusClock | None = None) -> MCPServer:
    prov = provider or load_provider_from_env(clock)
    catalog = EventCatalog(prov, clock)
    tz = catalog.clock.tz.key
    mcp = MCPServer(
        SERVER_NAME,
        version="0.2.0",
        instructions=(
            f"Read-only IIT Roorkee campus events and academic-calendar dates. Dates are in {tz}. "
            "origin=official records come from IIT Roorkee documents; origin=synthetic records are demo data. "
            "A tool error means the calendar could not be checked - never report that as 'no events'."
        ),
    )

    def _fail(exc: Exception) -> ToolError:
        if isinstance(exc, EventsProviderError):
            return ToolError(f"The events source could not be checked: {exc}")
        return ToolError(str(exc))

    @mcp.tool()
    async def search_events(
        query: Annotated[
            str, Field(max_length=200, description="Keywords, e.g. 'AI workshop'. Empty string matches all events.")
        ],
        start_date: Annotated[
            dt.date | None,
            Field(description="Earliest campus date (YYYY-MM-DD, campus timezone). Omit for upcoming events."),
        ] = None,
        end_date: Annotated[dt.date | None, Field(description="Latest campus date (YYYY-MM-DD), inclusive.")] = None,
        include_cancelled: Annotated[bool, Field(description="Also return cancelled events.")] = False,
    ) -> EventList:
        """Search campus events by keyword and optional date range. Results are sorted by start time.

        Without dates only ongoing and upcoming events are returned; with dates, any event overlapping
        the range is returned (past ones are marked timing=past)."""
        if start_date and end_date and end_date < start_date:
            raise ToolError("end_date must be on or after start_date.")
        try:
            return await catalog.search(query, start_date, end_date, include_cancelled=include_cancelled)
        except EventsProviderError as exc:
            raise _fail(exc) from exc

    @mcp.tool()
    async def get_events_for_date(
        date: Annotated[
            dt.date | None,
            Field(description="Campus date (YYYY-MM-DD). Omit for today on campus; pass tomorrow's date explicitly."),
        ] = None,
        include_cancelled: Annotated[bool, Field(description="Also return cancelled events.")] = False,
    ) -> EventList:
        """List every event taking place on one campus day, including all-day and multi-day events."""
        try:
            return await catalog.on_date(date, include_cancelled=include_cancelled)
        except EventsProviderError as exc:
            raise _fail(exc) from exc

    @mcp.tool()
    async def get_upcoming_events(
        limit: Annotated[int, Field(ge=1, le=20, description="Maximum number of events.")] = 5,
    ) -> EventList:
        """List the next scheduled campus events in chronological order (cancelled/completed excluded)."""
        try:
            return await catalog.upcoming(limit)
        except EventsProviderError as exc:
            raise _fail(exc) from exc

    @mcp.tool()
    async def get_event_details(
        event_id: Annotated[
            str, Field(pattern=r"^[A-Za-z0-9_-]{3,128}$", description="Event id from search results, e.g. EVT-101.")
        ],
    ) -> EventDetails:
        """Get full details (description, organiser, registration, status, source document) for one event."""
        try:
            return await catalog.details(event_id)
        except (EventNotFoundError, EventsProviderError) as exc:
            raise _fail(exc) from exc

    @mcp.custom_route("/health", methods=["GET"])  # type: ignore[untyped-decorator]  # SDK decorator is untyped
    async def health(_: Request) -> JSONResponse:
        return JSONResponse(
            {"status": "ok", "server": SERVER_NAME, "source": prov.source_info().model_dump(mode="json")}
        )

    return mcp
