"""Cafeteria menu providers.

All providers normalise to ``MenuData``: one or more dining locations, each with a menu per
weekday for every week of an N-week rotation, plus always-available items. The MCP tool layer
is identical regardless of where the menu comes from.

* ``demo``  - bundled SYNTHETIC fixture (``mode="demo"``): a four-week rotation for three demo
  locations. Not IIT Roorkee mess or canteen data.
* ``json``  - operator-supplied structured menu file (``mode="imported"``); either the rotation
  format or the simple single-week format ``{"weekly": {...}, "always_available": [...]}``.
* ``pdf``   - operator-supplied single-week menu PDF parsed with PyMuPDF (``mode="imported"``).

Imported menus are snapshots: they are never labelled ``live`` and are flagged ``stale`` when
the campus date falls outside their declared validity window (``stale=None`` when no window is
declared, because currency then cannot be verified).

"Today" is always the campus-local date (``CAMPUS_TIMEZONE``, default Asia/Kolkata) computed at
request time from an injectable clock. The rotation week is derived from that date.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from .campus_time import CampusClock
from .models import DiningLocation, ItemPrice, MenuItem, MenuSearchResult, SourceInfo, TodayMenu

DEMO_MENU_PATH = Path(__file__).parent / "data" / "demo_menu.json"
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MEALS = ["breakfast", "brunch", "lunch", "snacks", "dinner", "beverages"]


class MenuError(ValueError):
    """Invalid request (e.g. unknown location) or invalid menu file."""


@dataclass
class RawItem:
    name: str
    category: str
    price: float
    vegetarian: bool | None = None
    meal: str | None = None
    cuisine: str | None = None


@dataclass
class Location:
    id: str
    name: str
    hours: str | None = None
    always_available: list[RawItem] = field(default_factory=list)


@dataclass
class MenuData:
    cafeteria: str
    currency: str
    weekly: dict[str, list[RawItem]]  # week-1 menu of the default location (single-week compatibility)
    always_available: list[RawItem] = field(default_factory=list)
    data_as_of: str | None = None  # last verified source update, only when the source states it
    valid_from: date | None = None
    valid_to: date | None = None
    imported_at: str | None = None  # when an operator file was read (UTC)
    source_url: str | None = None
    record_version: str | None = None  # sha256 prefix of the imported file
    rotation_weeks: int = 1
    anchor_monday: date | None = None
    locations: list[Location] = field(default_factory=list)
    schedule: dict[int, dict[str, dict[str, list[RawItem]]]] = field(default_factory=dict)  # week->loc->day
    default_location: str = "main"


def _utc_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _file_version(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def _items(raw: list[dict[str, Any]]) -> list[RawItem]:
    try:
        return [
            RawItem(
                name=str(i["name"]),
                category=str(i.get("category", i.get("meal", "other"))),
                price=float(i["price"]),
                vegetarian=i.get("vegetarian"),
                meal=i.get("meal"),
                cuisine=i.get("cuisine"),
            )
            for i in raw
        ]
    except (KeyError, TypeError, ValueError) as exc:
        raise MenuError(f"Invalid menu item: {exc}") from exc


def _single_location(data: MenuData) -> MenuData:
    """Wrap a single-week, single-location menu in the rotation structure."""
    data.locations = [Location("main", data.cafeteria, None, data.always_available)]
    data.schedule = {1: {"main": data.weekly}}
    data.default_location = "main"
    return data


def menu_from_json(path: Path, *, imported_at: datetime | None = None) -> MenuData:
    try:
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise MenuError(f"Cannot read menu file {path.name}: {type(exc).__name__}") from exc
    common = {
        "currency": raw.get("currency", "INR"),
        "data_as_of": raw.get("data_as_of"),
        "valid_from": date.fromisoformat(raw["valid_from"]) if raw.get("valid_from") else None,
        "valid_to": date.fromisoformat(raw["valid_to"]) if raw.get("valid_to") else None,
        "imported_at": _utc_iso(imported_at or datetime.now(UTC)),
        "source_url": raw.get("source_url"),
        "record_version": _file_version(path),
    }
    if "weeks" not in raw:
        weekly = {day: _items(raw.get("weekly", {}).get(day, [])) for day in WEEKDAYS}
        return _single_location(
            MenuData(
                cafeteria=raw.get("cafeteria", "Cafeteria"),
                weekly=weekly,
                always_available=_items(raw.get("always_available", [])),
                **common,
            )
        )
    rotation = raw.get("rotation") or {}
    n_weeks = int(rotation.get("weeks", len(raw["weeks"])))
    locations = [
        Location(str(loc["id"]), str(loc["name"]), loc.get("hours"), _items(loc.get("always_available", [])))
        for loc in raw.get("locations", [])
    ]
    if not locations:
        raise MenuError("A rotation menu must define at least one location.")
    schedule = {
        int(w): {loc: {day: _items(items) for day, items in days.items()} for loc, days in by_loc.items()}
        for w, by_loc in raw["weeks"].items()
    }
    if sorted(schedule) != list(range(1, n_weeks + 1)):
        raise MenuError(f"Rotation declares {n_weeks} weeks but defines {sorted(schedule)}.")
    default = str(raw.get("default_location") or locations[0].id)
    anchor = rotation.get("anchor_monday")
    anchor_day = date.fromisoformat(anchor) if anchor else None
    if anchor_day and anchor_day.weekday() != 0:
        raise MenuError("rotation.anchor_monday must be a Monday.")
    default_loc = next(loc for loc in locations if loc.id == default)
    return MenuData(
        cafeteria=default_loc.name,
        weekly=schedule[1].get(default, {}),
        always_available=default_loc.always_available,
        rotation_weeks=n_weeks,
        anchor_monday=anchor_day,
        locations=locations,
        schedule=schedule,
        default_location=default,
        **common,
    )


# "Veg Thali ........ Rs. 100"  |  "Veg Thali - 100"  |  "Veg Thali  INR 100.00"
_PRICE_LINE = re.compile(
    r"^(?P<name>[A-Za-z][\w&()'’,/ .-]*?)\s*(?:\.{2,}|-|:|\s{2,})\s*(?:Rs\.?|INR|₹)?\s*(?P<price>\d+(?:\.\d{1,2})?)\s*$"
)
_DAY_HEADER = re.compile(r"^(?P<day>monday|tuesday|wednesday|thursday|friday|saturday|sunday|daily|all days)\b", re.I)
_VALIDITY = re.compile(
    r"valid\s+(?:from\s+)?(?P<start>\d{4}-\d{2}-\d{2})\s+(?:to|-)\s+(?P<end>\d{4}-\d{2}-\d{2})", re.I
)


def menu_from_pdf(path: Path, currency: str = "INR", *, imported_at: datetime | None = None) -> MenuData:
    """Parse a simple text menu PDF.

    Expected layout: a weekday heading ("Monday", ... or "Daily") followed by
    ``Item name .... Rs. 80`` lines. Lines that do not match are ignored, so the
    parser never invents prices. An optional ``Valid 2026-10-01 to 2026-10-31``
    line sets the validity window.
    """
    import pymupdf  # local import: only needed for PDF imports

    weekly: dict[str, list[RawItem]] = {d: [] for d in WEEKDAYS}
    always: list[RawItem] = []
    current: str | None = None
    valid_from = valid_to = None
    try:
        with pymupdf.open(path) as doc:  # type: ignore[no-untyped-call]
            lines = [ln.strip() for page in doc for ln in page.get_text().splitlines() if ln.strip()]
    except (pymupdf.FileDataError, RuntimeError, ValueError) as exc:
        raise MenuError(f"Cannot read menu PDF {path.name}: {type(exc).__name__}") from exc
    for line in lines:
        if m := _VALIDITY.search(line):
            valid_from, valid_to = date.fromisoformat(m["start"]), date.fromisoformat(m["end"])
            continue
        if m := _DAY_HEADER.match(line):
            current = m["day"].lower()
            continue
        if current and (m := _PRICE_LINE.match(line)):
            item = RawItem(name=m["name"].strip(" .-"), category="menu", price=float(m["price"]))
            if current in ("daily", "all days"):
                always.append(item)
            else:
                weekly[current].append(item)
    # A PDF states no authoritative "last updated" time; the file's mtime is only when our copy
    # was written, so it is NOT reported as data_as_of. The import time is recorded instead.
    return _single_location(
        MenuData(
            cafeteria=path.stem.replace("_", " ").title(),
            currency=currency,
            weekly=weekly,
            always_available=always,
            data_as_of=None,
            valid_from=valid_from,
            valid_to=valid_to,
            imported_at=_utc_iso(imported_at or datetime.now(UTC)),
            record_version=_file_version(path),
        )
    )


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


class MenuProvider:
    """Serves menu queries over a ``MenuData`` snapshot."""

    def __init__(
        self,
        data: MenuData,
        mode: str,
        provider: str,
        today: Callable[[], date] | None = None,
        *,
        clock: CampusClock | None = None,
    ) -> None:
        """``clock`` supplies campus-local time; ``today`` (tests only) pins the menu date directly."""
        if not data.schedule:
            _single_location(data)
        self._data = data
        self._mode = mode
        self._provider = provider
        self._clock = clock or CampusClock()
        self._today = today or self._clock.today

    @property
    def clock(self) -> CampusClock:
        return self._clock

    def today(self) -> date:
        return self._today()

    # ------------------------------------------------------------------ provenance
    def _staleness(self, today: date) -> tuple[bool | None, str | None]:
        d = self._data
        if d.valid_from and today < d.valid_from:
            return True, f"The menu is declared valid from {d.valid_from}; today is {today} ({self._clock.tz.key})."
        if d.valid_to and today > d.valid_to:
            return True, f"The menu's declared validity ended on {d.valid_to}; today is {today} ({self._clock.tz.key})."
        if self._mode == "imported" and not (d.valid_from or d.valid_to):
            return None, "The imported menu declares no validity period, so whether it is current cannot be verified."
        return False, None

    def source_info(self) -> SourceInfo:
        stale, reason = self._staleness(self._today())
        notes = {
            "demo": "Simulated menu and prices for demonstration; not IIT Roorkee mess or canteen data.",
            "imported": "Menu imported from an operator-supplied file; a snapshot, not a live feed.",
        }
        return SourceInfo(
            mode=self._mode,  # type: ignore[arg-type]
            provider=self._provider,
            source_url=self._data.source_url,
            retrieved_at=self._clock.retrieved_at(),
            imported_at=self._data.imported_at if self._mode == "imported" else None,
            data_as_of=self._data.data_as_of,
            valid_from=self._data.valid_from,
            valid_to=self._data.valid_to,
            stale=stale,
            staleness_reason=reason,
            record_version=self._data.record_version if self._mode == "imported" else None,
            timezone=self._clock.tz.key,
            note=notes.get(self._mode),
        )

    # ------------------------------------------------------------------ helpers
    def locations(self) -> list[DiningLocation]:
        return [
            DiningLocation(id=loc.id, name=loc.name, hours=loc.hours, default=loc.id == self._data.default_location)
            for loc in self._data.locations
        ]

    def resolve_location(self, query: str | None) -> Location:
        if not query:
            return next(loc for loc in self._data.locations if loc.id == self._data.default_location)
        q = _norm(query)
        for loc in self._data.locations:
            if q in (_norm(loc.id), _norm(loc.name)) or q in _norm(loc.name):
                return loc
        names = ", ".join(loc.name for loc in self._data.locations)
        raise MenuError(f"Unknown dining location '{query}'. Known locations: {names}.")

    def rotation_week(self, day: date) -> int:
        if self._data.rotation_weeks <= 1 or self._data.anchor_monday is None:
            return 1
        return ((day - self._data.anchor_monday).days // 7) % self._data.rotation_weeks + 1

    def _to_item(self, raw: RawItem, days: list[str], location: Location | None = None) -> MenuItem:
        return MenuItem(
            name=raw.name,
            category=raw.category,
            meal=raw.meal,
            cuisine=raw.cuisine,
            price=raw.price,
            currency=self._data.currency,
            vegetarian=raw.vegetarian,
            available_on=days,
            locations=[location.name] if location else [],
        )

    # ------------------------------------------------------------------ queries
    def menu_for(
        self,
        day: date,
        location: str | None = None,
        meal: str | None = None,
        *,
        cuisine: str | None = None,
        vegetarian: bool | None = None,
    ) -> TodayMenu:
        loc = self.resolve_location(location)
        weekday = WEEKDAYS[day.weekday()]
        week = self.rotation_week(day)
        raw = self._data.schedule.get(week, {}).get(loc.id, {}).get(weekday, [])
        items = [self._to_item(r, [weekday], loc) for r in raw]
        items += [self._to_item(r, list(WEEKDAYS), loc) for r in loc.always_available]
        if meal:
            items = [i for i in items if (i.meal or i.category).lower() == meal.lower()]
        if cuisine:
            items = [i for i in items if i.cuisine and cuisine.lower() in i.cuisine.lower()]
        if vegetarian is not None:
            items = [i for i in items if i.vegetarian is vegetarian]
        note = None
        if not raw:
            note = f"No menu is listed for {loc.name} on {weekday} {day} (rotation week {week})."
        elif not items:
            note = "The menu for this day has no items matching the filters."
        return TodayMenu(
            date=day,
            weekday=weekday,
            cafeteria=loc.name,
            location_id=loc.id,
            rotation_week=week,
            meal=meal,
            items=items,
            note=note,
            source=self.source_info(),
        )

    def today_menu(self, location: str | None = None, meal: str | None = None) -> TodayMenu:
        return self.menu_for(self._today(), location, meal)

    def _all_items(self, location: str | None = None) -> list[MenuItem]:
        locs = [self.resolve_location(location)] if location else self._data.locations
        by_name: dict[str, MenuItem] = {}
        for loc in locs:
            for days in (self._data.schedule.get(w, {}).get(loc.id, {}) for w in sorted(self._data.schedule)):
                for day in WEEKDAYS:
                    for raw in days.get(day, []):
                        item = by_name.setdefault(raw.name, self._to_item(raw, []))
                        if day not in item.available_on:
                            item.available_on.append(day)
                        if loc.name not in item.locations:
                            item.locations.append(loc.name)
            for raw in loc.always_available:
                item = by_name.setdefault(raw.name, self._to_item(raw, []))
                item.available_on = list(WEEKDAYS)
                if loc.name not in item.locations:
                    item.locations.append(loc.name)
        for item in by_name.values():
            item.available_on.sort(key=WEEKDAYS.index)
        return list(by_name.values())

    def search(
        self,
        query: str,
        *,
        cuisine: str | None = None,
        vegetarian: bool | None = None,
        location: str | None = None,
    ) -> MenuSearchResult:
        q_terms = _norm(query).split()
        matches = [
            item
            for item in self._all_items(location)
            if (not q_terms or all(t in _norm(f"{item.name} {item.category} {item.cuisine or ''}") for t in q_terms))
            and (not cuisine or (item.cuisine and cuisine.lower() in item.cuisine.lower()))
            and (vegetarian is None or item.vegetarian is vegetarian)
        ]
        return MenuSearchResult(query=query, count=len(matches), items=matches[:15], source=self.source_info())

    def price(self, item_name: str, location: str | None = None) -> ItemPrice:
        items = self._all_items(location)
        target = _norm(item_name)
        exact = [i for i in items if _norm(i.name) == target]
        contains = [i for i in items if target and target in _norm(i.name)]
        hit = exact[0] if exact else (contains[0] if len(contains) == 1 else None)
        if hit:
            by_location = self._prices_by_location(hit.name) if not location else {}
            return ItemPrice(
                item_name=item_name,
                found=True,
                price=hit.price,
                currency=hit.currency,
                matched_item=hit.name,
                prices_by_location=by_location if len(set(by_location.values())) > 1 else {},
                source=self.source_info(),
            )
        names = [i.name for i in items]
        close = difflib.get_close_matches(item_name, names, n=3, cutoff=0.5)
        suggestions = close or [i.name for i in contains[:3]]
        return ItemPrice(item_name=item_name, found=False, suggestions=suggestions, source=self.source_info())

    def _prices_by_location(self, name: str) -> dict[str, float]:
        out: dict[str, float] = {}
        for loc in self._data.locations:
            for item in self._all_items(loc.id):
                if item.name == name:
                    out[loc.name] = item.price
        return out


def load_provider_from_env(clock: CampusClock | None = None) -> MenuProvider:
    clock = clock or CampusClock()
    name = os.getenv("CAFETERIA_PROVIDER", "demo").lower()
    if name == "demo":
        path = Path(os.getenv("CAFETERIA_DEMO_DATA") or DEMO_MENU_PATH)
        return MenuProvider(menu_from_json(path), mode="demo", provider="demo-json", clock=clock)
    path_str = os.getenv("CAFETERIA_MENU_PATH")
    if not path_str:
        raise ValueError(f"CAFETERIA_PROVIDER={name} requires CAFETERIA_MENU_PATH.")
    path = Path(path_str)
    if name == "json":
        data = menu_from_json(path, imported_at=clock.now_utc())
        return MenuProvider(data, mode="imported", provider=f"json:{path.name}", clock=clock)
    if name == "pdf":
        data = menu_from_pdf(path, os.getenv("CAFETERIA_CURRENCY", "INR"), imported_at=clock.now_utc())
        return MenuProvider(data, mode="imported", provider=f"pdf:{path.name}", clock=clock)
    raise ValueError(f"Unsupported CAFETERIA_PROVIDER '{name}' (expected demo, json or pdf).")
