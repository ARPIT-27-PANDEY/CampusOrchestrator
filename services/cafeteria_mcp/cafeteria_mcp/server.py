"""Cafeteria MCP server (MCP Python SDK v2, Streamable HTTP)."""

from __future__ import annotations

from typing import Annotated

from mcp.server import MCPServer
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from .models import ItemPrice, MenuSearchResult, TodayMenu
from .provider import MenuProvider, load_provider_from_env

SERVER_NAME = "campus-cafeteria"


def build_server(provider: MenuProvider | None = None) -> MCPServer:
    prov = provider or load_provider_from_env()
    mcp = MCPServer(
        SERVER_NAME,
        version="0.1.0",
        instructions="Read-only cafeteria menu and prices. Check source.mode and source.stale before calling data current.",
    )

    @mcp.tool()
    def get_today_menu() -> TodayMenu:
        """Get today's cafeteria menu with prices, including items available every day."""
        return prov.today_menu()

    @mcp.tool()
    def search_menu_item(
        query: Annotated[str, Field(min_length=1, max_length=100, description="Dish name or keyword, e.g. 'biryani'.")],
    ) -> MenuSearchResult:
        """Search the weekly cafeteria menu for a dish and see which weekdays it is served."""
        return prov.search(query)

    @mcp.tool()
    def get_item_price(
        item_name: Annotated[str, Field(min_length=1, max_length=100, description="Exact or partial dish name.")],
    ) -> ItemPrice:
        """Get the price of a specific cafeteria menu item. Returns found=false with suggestions if unknown."""
        return prov.price(item_name)

    @mcp.custom_route("/health", methods=["GET"])  # type: ignore[untyped-decorator]  # SDK decorator is untyped
    async def health(_: Request) -> JSONResponse:
        return JSONResponse(
            {"status": "ok", "server": SERVER_NAME, "source": prov.source_info().model_dump(mode="json")}
        )

    return mcp
