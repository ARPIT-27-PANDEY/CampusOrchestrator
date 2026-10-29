"""Four-week, multi-location synthetic menu: rotation, filters, locations and invalid inputs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from mcp import Client

from cafeteria_mcp.campus_time import CampusClock
from cafeteria_mcp.provider import DEMO_MENU_PATH, MenuError, MenuProvider, menu_from_json
from cafeteria_mcp.server import build_server

NOW = datetime(2026, 10, 28, 18, 30, tzinfo=UTC)  # 00:00 Thursday 29 Oct 2026 IST
RAW = json.loads(DEMO_MENU_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def menu() -> MenuProvider:
    return MenuProvider(menu_from_json(DEMO_MENU_PATH), mode="demo", provider="demo-json", clock=CampusClock.fixed(NOW))


def test_fixture_is_labelled_synthetic() -> None:
    assert "SYNTHETIC" in RAW["description"] and "Not IIT Roorkee" in RAW["description"]
    assert all("(demo)" in loc["name"] and loc["synthetic"] for loc in RAW["locations"])


def test_four_week_rotation_with_variety() -> None:
    assert sorted(RAW["weeks"]) == ["1", "2", "3", "4"]
    central = [{i["name"] for i in RAW["weeks"][w]["central"]["monday"]} for w in "1234"]
    assert len({frozenset(s) for s in central}) == 4  # Mondays differ across the four weeks
    cuisines = {i["cuisine"] for w in RAW["weeks"].values() for loc in w.values() for d in loc.values() for i in d}
    assert {"north indian", "south indian", "east indian", "west indian", "continental", "chinese", "italian",
            "regional"} <= cuisines  # fmt: skip
    meals = {i["meal"] for w in RAW["weeks"].values() for loc in w.values() for d in loc.values() for i in d}
    assert {"breakfast", "lunch", "snacks", "dinner"} <= meals


def test_rotation_week_follows_campus_dates(menu: MenuProvider) -> None:
    anchor = date(2026, 10, 5)  # week 1 Monday
    assert menu.rotation_week(anchor) == 1
    assert menu.rotation_week(date(2026, 10, 12)) == 2
    assert menu.rotation_week(date(2026, 11, 2)) == 1  # 28 days later: cycle restarts
    assert menu.rotation_week(date(2026, 10, 4)) == 4  # the Sunday before the anchor


def test_today_and_tomorrow_are_campus_dates(menu: MenuProvider) -> None:
    today = menu.today_menu()
    assert (today.date, today.weekday) == (date(2026, 10, 29), "thursday")
    tomorrow = menu.menu_for(menu.clock.tomorrow())
    assert (tomorrow.date, tomorrow.weekday) == (date(2026, 10, 30), "friday")
    assert {i.name for i in today.items} != {i.name for i in tomorrow.items}


def test_location_meal_cuisine_and_veg_filters(menu: MenuProvider) -> None:
    night = menu.today_menu("night canteen")
    assert night.location_id == "night-canteen" and night.items
    lunch = menu.menu_for(date(2026, 10, 29), meal="lunch", vegetarian=True)
    assert lunch.items and all(i.meal == "lunch" and i.vegetarian for i in lunch.items)
    south = menu.search("", cuisine="south indian")
    assert south.count and all(i.cuisine == "south indian" for i in south.items)


def test_unknown_location_is_an_error_not_an_empty_menu(menu: MenuProvider) -> None:
    with pytest.raises(MenuError, match="Known locations"):
        menu.today_menu("Malviya Bhawan Mess")


def test_filters_with_no_match_say_so(menu: MenuProvider) -> None:
    result = menu.menu_for(date(2026, 10, 29), meal="breakfast", cuisine="italian")
    assert result.items == [] and result.note and "no items matching" in result.note


def test_price_differs_by_location(menu: MenuProvider) -> None:
    chai = menu.price("Masala Chai")
    assert chai.found and chai.currency == "INR"
    fries = menu.price("French Fries")
    assert fries.found and len(fries.prices_by_location) >= 2  # night canteen charges more


@pytest.mark.parametrize(
    "payload",
    [
        {"weeks": {"1": {}}, "rotation": {"weeks": 2}, "locations": [{"id": "a", "name": "A"}]},  # missing week 2
        {
            "weeks": {"1": {}},
            "rotation": {"weeks": 1, "anchor_monday": "2026-10-06"},
            "locations": [{"id": "a", "name": "A"}],
        },
        {"weeks": {"1": {}}, "locations": []},
        {"weekly": {"monday": [{"name": "X"}]}},  # item without a price
    ],
)
def test_invalid_menu_files_are_rejected(tmp_path: Path, payload: dict[str, object]) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(MenuError):
        menu_from_json(path)


def test_expired_import_in_rotation_format_is_stale(tmp_path: Path) -> None:
    raw = dict(RAW, valid_from="2026-09-01", valid_to="2026-10-28")
    path = tmp_path / "import.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    prov = MenuProvider(menu_from_json(path), mode="imported", provider="json", clock=CampusClock.fixed(NOW))
    info = prov.source_info()
    assert info.stale is True and "2026-10-28" in (info.staleness_reason or "")


async def test_mcp_tools() -> None:
    prov = MenuProvider(menu_from_json(DEMO_MENU_PATH), mode="demo", provider="demo-json", clock=CampusClock.fixed(NOW))
    async with Client(build_server(prov)) as client:
        res = await client.call_tool("get_menu_for_date", {"date": "2026-10-30", "meal": "lunch", "vegetarian": True})
        assert res.structured_content is not None and res.structured_content["weekday"] == "friday"
        locs = await client.call_tool("list_dining_locations", {})
        assert locs.structured_content is not None and len(locs.structured_content["locations"]) == 3
        bad = await client.call_tool("get_today_menu", {"location": "Nowhere"})
        assert bad.is_error
