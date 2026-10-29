"""Test-only "Campus Transport" MCP server, used to prove that new servers are discovered dynamically.

Nothing in the backend (orchestrator, MCP manager, MockProvider routing rules) knows this server or
its tool names. Run standalone over the real Streamable HTTP transport:

    python tests/fixtures/transport_mcp.py --port 8199

``TRANSPORT_SCHEMA_VERSION=2`` adds an optional ``route`` argument, to test schema changes after a
registry refresh. The timetable is synthetic.
"""

from __future__ import annotations

import argparse
import os
from typing import Annotated, Any

from mcp.server import MCPServer
from pydantic import BaseModel, Field

SERVER_NAME = "campus-transport-test"
TIMETABLE: dict[str, list[dict[str, str]]] = {
    "Main Gate": [
        {"time": "08:00", "route": "Loop A", "destination": "Hospital"},
        {"time": "09:15", "route": "Loop A", "destination": "Hospital"},
        {"time": "10:30", "route": "Loop B", "destination": "Railway Station"},
        {"time": "12:00", "route": "Loop A", "destination": "Hospital"},
        {"time": "14:00", "route": "Loop B", "destination": "Railway Station"},
    ],
    "Library": [
        {"time": "08:20", "route": "Loop A", "destination": "Main Gate"},
        {"time": "11:00", "route": "Loop B", "destination": "Main Gate"},
    ],
}


class Departure(BaseModel):
    time: str
    route: str
    destination: str


class Departures(BaseModel):
    stop: str | None
    count: int
    departures: list[Departure]
    known_stops: list[str]
    source: dict[str, Any]


def build_server(schema_version: int | None = None) -> MCPServer:
    version = schema_version or int(os.getenv("TRANSPORT_SCHEMA_VERSION", "1"))
    mcp = MCPServer(
        SERVER_NAME, version=f"0.{version}.0", instructions="Synthetic campus shuttle timetable (test only)."
    )

    def _lookup(stop: str, after: str | None, route: str | None) -> Departures:
        match = next((s for s in TIMETABLE if s.lower() in stop.lower() or stop.lower() in s.lower()), None)
        rows = [Departure(**d) for d in TIMETABLE.get(match or "", [])]
        if after:
            rows = [d for d in rows if d.time >= after]
        if route:
            rows = [d for d in rows if d.route.lower() == route.lower()]
        return Departures(
            stop=match,
            count=len(rows),
            departures=rows,
            known_stops=sorted(TIMETABLE),
            source={
                "source_id": "transport",
                "mode": "demo",
                "provider": "test-fixture",
                "note": "Synthetic shuttle timetable for tests; not an IIT Roorkee service.",
            },
        )

    if version >= 2:

        @mcp.tool()
        def get_shuttle_departures(
            stop: Annotated[str, Field(min_length=2, max_length=80, description="Stop name, e.g. 'Main Gate'.")],
            after: Annotated[
                str | None, Field(pattern=r"^\d{2}:\d{2}$", description="Only departures at/after HH:MM.")
            ] = None,
            route: Annotated[str | None, Field(max_length=20, description="Only this route, e.g. 'Loop B'.")] = None,
        ) -> Departures:
            """Campus shuttle bus departures from a stop (timetable)."""
            return _lookup(stop, after, route)

    else:

        @mcp.tool()
        def get_shuttle_departures(  # type: ignore[no-redef,misc]
            stop: Annotated[str, Field(min_length=2, max_length=80, description="Stop name, e.g. 'Main Gate'.")],
            after: Annotated[
                str | None, Field(pattern=r"^\d{2}:\d{2}$", description="Only departures at/after HH:MM.")
            ] = None,
        ) -> Departures:
            """Campus shuttle bus departures from a stop (timetable)."""
            return _lookup(stop, after, None)

    return mcp


def main() -> None:
    import uvicorn
    from mcp.server.transport_security import TransportSecuritySettings

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    app = build_server().streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True, allowed_hosts=["127.0.0.1:*", "localhost:*"], allowed_origins=[]
        ),
        host="127.0.0.1",
    )

    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def health(_: Any) -> JSONResponse:
        return JSONResponse({"status": "ok", "server": SERVER_NAME, "source": {"mode": "demo"}})

    app.router.routes.append(Route("/health", health))
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
