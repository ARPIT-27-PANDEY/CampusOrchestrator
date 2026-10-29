"""The expanded events fixture: official IIT Roorkee calendar records vs labelled synthetic records."""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, date, datetime

import pytest

from events_mcp.campus_time import CampusClock
from events_mcp.catalog import EventCatalog
from events_mcp.provider import DEMO_DATA_PATH, DemoEventsProvider

NOW = datetime(2026, 10, 29, 4, 30, tzinfo=UTC)  # 10:00 IST, Thursday 29 Oct 2026
RAW = json.loads(DEMO_DATA_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def catalog() -> EventCatalog:
    return EventCatalog(DemoEventsProvider(clock=CampusClock.fixed(NOW)))


def test_dataset_size_and_mix() -> None:
    origins = Counter(e["origin"] for e in RAW["events"])
    assert 80 <= len(RAW["events"]) <= 130
    assert origins["official"] >= 60 and origins["synthetic"] >= 30
    assert len({e["event_id"] for e in RAW["events"]}) == len(RAW["events"])


def test_every_official_record_cites_a_known_document_and_page() -> None:
    for e in RAW["events"]:
        if e["origin"] == "official":
            assert e["document"] in RAW["documents"] and e["page"] in (1, 2), e["event_id"]
            assert RAW["documents"][e["document"]]["url"].startswith("https://iitr.ac.in/")
            assert "day_offset" not in e  # official dates are absolute, never relative to "today"


def test_synthetic_records_are_marked_demo() -> None:
    for e in RAW["events"]:
        if e["origin"] == "synthetic":
            assert "(demo)" in e.get("organizer", "(demo)"), e["event_id"]
            assert "date" not in e  # synthetic dates are always relative


def test_category_status_and_registration_coverage() -> None:
    cats = {e["category"] for e in RAW["events"]}
    assert {"workshop", "lecture", "seminar", "competition", "cultural", "sports", "career", "examination",
            "holiday", "registration", "deadline"} <= cats  # fmt: skip
    assert {e.get("status", "scheduled") for e in RAW["events"]} == {
        "scheduled",
        "cancelled",
        "rescheduled",
        "completed",
    }
    assert {e.get("registration_status", "unknown") for e in RAW["events"]} == {
        "open",
        "closed",
        "not_required",
        "unknown",
    }


async def test_official_holiday_is_returned_for_its_date(catalog: EventCatalog) -> None:
    day = await catalog.on_date(date(2026, 11, 8))
    diwali = [e for e in day.events if e.event_id == "IITR-A26-H08"]
    assert diwali and diwali[0].origin == "official" and diwali[0].all_day


async def test_multi_day_official_exam_window_covers_each_day(catalog: EventCatalog) -> None:
    for d in (date(2026, 11, 13), date(2026, 11, 20), date(2026, 11, 24)):
        assert "IITR-A26-21" in {e.event_id for e in (await catalog.on_date(d)).events}
    assert "IITR-A26-21" not in {e.event_id for e in (await catalog.on_date(date(2026, 11, 25))).events}


async def test_tentative_convocation_keeps_the_calendar_wording(catalog: EventCatalog) -> None:
    conv = await catalog.details("IITR-A26-12")
    assert conv.tentative and conv.date_note and "OR 26.09.2026" in conv.date_note
    assert conv.source.mode == "imported" and conv.source_document and conv.source_page == 1


async def test_official_source_metadata_differs_from_synthetic(catalog: EventCatalog) -> None:
    official = await catalog.details("IITR-A26-21")
    synthetic = await catalog.details("EVT-101")
    assert official.source.mode == "imported" and official.source.source_url
    assert official.source.data_as_of == "2026-04-06"  # calendar issue date, not our query time
    assert synthetic.source.mode == "demo" and synthetic.origin == "synthetic"


async def test_today_mixes_synthetic_and_reports_cancellations_only_on_request(catalog: EventCatalog) -> None:
    upcoming = await catalog.upcoming(20)
    assert "EVT-120" not in {e.event_id for e in upcoming.events}  # cancelled
    assert "EVT-132" not in {e.event_id for e in upcoming.events}  # completed
    week = await catalog.search("", date(2026, 11, 2), date(2026, 11, 3), include_cancelled=True)
    assert {"EVT-120"} <= {e.event_id for e in week.events}


async def test_concurrent_events_are_all_listed(catalog: EventCatalog) -> None:
    today = await catalog.on_date()
    at_three = [e for e in today.events if not e.all_day and e.start.hour == 15]
    assert len(at_three) >= 2  # EVT-113 and EVT-115 both start at 15:00
