"""Cafeteria MCP server (MCP Python SDK v2, Streamable HTTP)."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from .campus_time import CampusClock
from .models import ItemPrice, LocationList, MenuSearchResult, TodayMenu
from .provider import MenuError, MenuProvider, load_provider_from_env

SERVER_NAME = "campus-cafeteria"
Meal = Literal["breakfast", "brunch", "lunch", "snacks", "dinner", "beverages"]
LocationArg = Annotated[
    str | None, Field(max_length=60, description="Dining location name or id; omit for the default location.")
]


def build_server(provider: MenuProvider | None = None, clock: CampusClock | None = None) -> MCPServer:
    prov = provider or load_provider_from_env(clock)
    mcp = MCPServer(
        SERVER_NAME,
        version="0.2.0",
        instructions=(
            "Read-only campus dining menus and prices. Dates are campus dates (Asia/Kolkata). Check source.mode "
            "(demo = synthetic, not IIT Roorkee data) and source.stale before calling data current. An unknown "
            "location is a tool error; an empty item list is a successful 'nothing matches'."
        ),
    )

    @mcp.tool()
    def get_today_menu(
        location: LocationArg = None,
        meal: Annotated[Meal | None, Field(description="Optional meal filter.")] = None,
    ) -> TodayMenu:
        """Get today's menu (today = campus date in Asia/Kolkata) with prices, for one dining location."""
        try:
            return prov.today_menu(location, meal)
        except MenuError as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool()
    def get_menu_for_date(
        date: Annotated[dt.date, Field(description="Campus date (YYYY-MM-DD), e.g. tomorrow's date.")],
        location: LocationArg = None,
        meal: Annotated[Meal | None, Field(description="Optional meal filter.")] = None,
        cuisine: Annotated[
            str | None, Field(max_length=40, description="Optional cuisine filter, e.g. 'south indian', 'chinese'.")
        ] = None,
        vegetarian: Annotated[bool | None, Field(description="true = vegetarian only, false = non-veg only.")] = None,
    ) -> TodayMenu:
        """Get the menu for a specific campus date, optionally filtered by meal, cuisine or vegetarian."""
        try:
            return prov.menu_for(date, location, meal, cuisine=cuisine, vegetarian=vegetarian)
        except MenuError as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool()
    def search_menu_item(
        query: Annotated[str, Field(min_length=1, max_length=100, description="Dish name or keyword, e.g. 'biryani'.")],
        cuisine: Annotated[str | None, Field(max_length=40, description="Optional cuisine filter.")] = None,
        vegetarian: Annotated[bool | None, Field(description="Optional vegetarian filter.")] = None,
        location: LocationArg = None,
    ) -> MenuSearchResult:
        """Search the menu rotation for a dish and see which weekdays and locations serve it."""
        try:
            return prov.search(query, cuisine=cuisine, vegetarian=vegetarian, location=location)
        except MenuError as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool()
    def get_item_price(
        item_name: Annotated[str, Field(min_length=1, max_length=100, description="Exact or partial dish name.")],
        location: LocationArg = None,
    ) -> ItemPrice:
        """Get the price of a menu item. Returns found=false with suggestions if unknown."""
        try:
            return prov.price(item_name, location)
        except MenuError as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool()
    def list_dining_locations() -> LocationList:
        """List the dining locations this service has menus for (with opening hours if known)."""
        return LocationList(locations=prov.locations(), source=prov.source_info())

    @mcp.custom_route("/health", methods=["GET"])  # type: ignore[untyped-decorator]  # SDK decorator is untyped
    async def health(_: Request) -> JSONResponse:
        return JSONResponse(
            {"status": "ok", "server": SERVER_NAME, "source": prov.source_info().model_dump(mode="json")}
        )

    return mcp
