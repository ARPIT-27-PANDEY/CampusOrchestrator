"""Cafeteria: campus-local 'today' and menu provenance/staleness semantics."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pymupdf
import pytest
from mcp import Client

from cafeteria_mcp.campus_time import CampusClock
from cafeteria_mcp.provider import DEMO_MENU_PATH, MenuProvider, menu_from_json, menu_from_pdf
from cafeteria_mcp.server import build_server

BEFORE_MIDNIGHT_IST = datetime(2026, 10, 28, 18, 29, tzinfo=UTC)  # Wed 23:59 IST
AT_MIDNIGHT_IST = datetime(2026, 10, 28, 18, 30, tzinfo=UTC)  # Thu 00:00 IST


def _demo(instant: datetime) -> MenuProvider:
    return MenuProvider(
        menu_from_json(DEMO_MENU_PATH), mode="demo", provider="demo-json", clock=CampusClock.fixed(instant)
    )


@pytest.mark.parametrize(
    ("instant", "expected_date", "weekday"),
    [(BEFORE_MIDNIGHT_IST, date(2026, 10, 28), "wednesday"), (AT_MIDNIGHT_IST, date(2026, 10, 29), "thursday")],
)
def test_today_menu_uses_campus_date_at_midnight_boundary(instant: datetime, expected_date: date, weekday: str) -> None:
    menu = _demo(instant).today_menu()
    assert menu.date == expected_date and menu.weekday == weekday
    assert menu.source.timezone == "Asia/Kolkata"
    assert menu.source.retrieved_at == instant.isoformat().replace("+00:00", "Z")


def test_today_is_computed_per_request_not_at_startup() -> None:
    current = {"t": BEFORE_MIDNIGHT_IST}
    prov = MenuProvider(
        menu_from_json(DEMO_MENU_PATH), mode="demo", provider="demo-json", clock=CampusClock(clock=lambda: current["t"])
    )
    assert prov.today_menu().weekday == "wednesday"
    current["t"] = AT_MIDNIGHT_IST
    assert prov.today_menu().weekday == "thursday"


def test_demo_menu_is_labelled_demo_and_not_stale() -> None:
    info = _demo(AT_MIDNIGHT_IST).source_info()
    assert info.mode == "demo" and info.stale is False
    assert info.note and "not IIT Roorkee" in info.note
    assert info.imported_at is None  # demo data is not an import


def _imported(tmp_path: Path, instant: datetime, **window: str) -> MenuProvider:
    raw = json.loads(DEMO_MENU_PATH.read_text(encoding="utf-8"))
    raw.pop("valid_from", None)
    raw.pop("valid_to", None)
    raw.update(window)
    path = tmp_path / "menu.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return MenuProvider(
        menu_from_json(path, imported_at=datetime(2026, 10, 1, 6, tzinfo=UTC)),
        mode="imported",
        provider="json:menu.json",
        clock=CampusClock.fixed(instant),
    )


def test_validity_end_is_checked_against_campus_date(tmp_path: Path) -> None:
    # Valid until Wed 28 Oct: still valid at 23:59 IST, stale one minute later.
    assert _imported(tmp_path, BEFORE_MIDNIGHT_IST, valid_to="2026-10-28").source_info().stale is False
    info = _imported(tmp_path, AT_MIDNIGHT_IST, valid_to="2026-10-28").source_info()
    assert info.stale is True and info.staleness_reason and "2026-10-28" in info.staleness_reason


def test_menu_not_yet_valid_is_stale(tmp_path: Path) -> None:
    info = _imported(tmp_path, AT_MIDNIGHT_IST, valid_from="2026-11-01").source_info()
    assert info.stale is True and "valid from 2026-11-01" in (info.staleness_reason or "")


def test_imported_menu_without_validity_is_unverifiable_not_current(tmp_path: Path) -> None:
    info = _imported(tmp_path, AT_MIDNIGHT_IST).source_info()
    assert info.mode == "imported"  # never "live", however recently it was read
    assert info.stale is None and "cannot be verified" in (info.staleness_reason or "")
    assert info.imported_at == "2026-10-01T06:00:00Z"
    assert info.retrieved_at == "2026-10-28T18:30:00Z"
    assert info.record_version and len(info.record_version) == 12


def test_pdf_import_does_not_report_file_mtime_as_data_as_of(tmp_path: Path) -> None:
    path = tmp_path / "weekly_menu.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Monday\nPoha - 30", fontsize=11)
    doc.save(path)
    data = menu_from_pdf(path, imported_at=AT_MIDNIGHT_IST)
    assert data.data_as_of is None
    assert data.imported_at == "2026-10-28T18:30:00Z"


async def test_mcp_today_menu_reports_campus_date() -> None:
    async with Client(build_server(_demo(AT_MIDNIGHT_IST))) as client:
        res = await client.call_tool("get_today_menu", {})
        assert res.structured_content is not None
        assert res.structured_content["date"] == "2026-10-29"
        assert res.structured_content["weekday"] == "thursday"
