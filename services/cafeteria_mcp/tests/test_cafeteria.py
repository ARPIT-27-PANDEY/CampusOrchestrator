"""Cafeteria MCP server tests."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pymupdf
import pytest
from mcp import Client

from cafeteria_mcp.provider import DEMO_MENU_PATH, MenuProvider, menu_from_json, menu_from_pdf
from cafeteria_mcp.server import build_server

FRIDAY = date(2026, 10, 23)


@pytest.fixture
def demo() -> MenuProvider:
    return MenuProvider(menu_from_json(DEMO_MENU_PATH), mode="demo", provider="demo-json", today=lambda: FRIDAY)


def test_today_menu_uses_weekday_and_always_items(demo: MenuProvider) -> None:
    menu = demo.today_menu()
    names = {i.name for i in menu.items}
    assert menu.weekday == "friday"
    assert "Veg Biryani" in names and "Masala Chai" in names
    assert "Idli Sambar" not in names  # Monday only
    assert menu.source.mode == "demo"


def test_search_reports_weekdays(demo: MenuProvider) -> None:
    result = demo.search("chicken biryani")
    assert result.count == 1
    assert result.items[0].available_on == ["monday", "friday"]


def test_price_exact_partial_and_unknown(demo: MenuProvider) -> None:
    assert demo.price("masala dosa").price == 55
    assert demo.price("Pav").matched_item == "Pav Bhaji"
    unknown = demo.price("Sushi Platter")
    assert unknown.found is False and unknown.price is None


def test_price_ambiguous_partial_returns_suggestions(demo: MenuProvider) -> None:
    result = demo.price("biryani")  # Chicken + Veg biryani -> ambiguous
    assert result.found is False
    assert {"Veg Biryani", "Chicken Biryani"} <= set(result.suggestions)


def test_imported_json_menu_is_flagged_stale_outside_window(tmp_path: Path) -> None:
    raw = json.loads(DEMO_MENU_PATH.read_text())
    raw.update(valid_from="2026-09-01", valid_to="2026-09-30")
    path = tmp_path / "menu.json"
    path.write_text(json.dumps(raw))
    prov = MenuProvider(menu_from_json(path), mode="imported", provider="json:menu.json", today=lambda: FRIDAY)
    info = prov.source_info()
    assert info.mode == "imported" and info.stale is True


def test_pdf_menu_import(tmp_path: Path) -> None:
    path = tmp_path / "weekly_menu.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    text = "Weekly Menu\nValid 2026-10-19 to 2026-10-25\nFriday\nPaneer Wrap ...... Rs. 90\nNot a price line\nDaily\nCold Coffee - 60"
    page.insert_text((72, 72), text, fontsize=11)
    doc.save(path)
    data = menu_from_pdf(path)
    assert [i.name for i in data.weekly["friday"]] == ["Paneer Wrap"]
    assert data.weekly["friday"][0].price == 90
    assert [i.name for i in data.always_available] == ["Cold Coffee"]
    assert data.valid_to == date(2026, 10, 25)


async def test_mcp_tools() -> None:
    prov = MenuProvider(menu_from_json(DEMO_MENU_PATH), mode="demo", provider="demo-json", today=lambda: FRIDAY)
    async with Client(build_server(prov)) as client:
        assert {t.name for t in (await client.list_tools()).tools} == {
            "get_today_menu",
            "search_menu_item",
            "get_item_price",
        }
        res = await client.call_tool("get_item_price", {"item_name": "Masala Chai"})
        assert res.structured_content is not None and res.structured_content["price"] == 20
        bad = await client.call_tool("search_menu_item", {"query": ""})
        assert bad.is_error
