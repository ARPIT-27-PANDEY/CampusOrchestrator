"""Cafeteria menu providers.

All providers normalise to ``MenuData`` (a weekly cycle plus always-available
items), so the MCP tool layer is identical regardless of where the menu comes from.

* ``demo``  – bundled simulated fixture (``mode="demo"``)
* ``json``  – operator-supplied structured menu file (``mode="imported"``)
* ``pdf``   – operator-supplied menu PDF parsed with PyMuPDF (``mode="imported"``)

Imported menus are snapshots: they are never labelled ``live`` and are flagged
``stale`` when today falls outside their declared validity window.
"""

from __future__ import annotations

import difflib
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .models import ItemPrice, MenuItem, MenuSearchResult, SourceInfo, TodayMenu

DEMO_MENU_PATH = Path(__file__).parent / "data" / "demo_menu.json"
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


@dataclass
class RawItem:
    name: str
    category: str
    price: float
    vegetarian: bool | None = None


@dataclass
class MenuData:
    cafeteria: str
    currency: str
    weekly: dict[str, list[RawItem]]
    always_available: list[RawItem] = field(default_factory=list)
    data_as_of: str | None = None
    valid_from: date | None = None
    valid_to: date | None = None


def _items(raw: list[dict[str, Any]]) -> list[RawItem]:
    return [
        RawItem(
            name=i["name"], category=i.get("category", "other"), price=float(i["price"]), vegetarian=i.get("vegetarian")
        )
        for i in raw
    ]


def menu_from_json(path: Path) -> MenuData:
    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    weekly = {day: _items(raw.get("weekly", {}).get(day, [])) for day in WEEKDAYS}
    return MenuData(
        cafeteria=raw.get("cafeteria", "Cafeteria"),
        currency=raw.get("currency", "INR"),
        weekly=weekly,
        always_available=_items(raw.get("always_available", [])),
        data_as_of=raw.get("data_as_of"),
        valid_from=date.fromisoformat(raw["valid_from"]) if raw.get("valid_from") else None,
        valid_to=date.fromisoformat(raw["valid_to"]) if raw.get("valid_to") else None,
    )


# "Veg Thali ........ Rs. 100"  |  "Veg Thali - 100"  |  "Veg Thali  INR 100.00"
_PRICE_LINE = re.compile(
    r"^(?P<name>[A-Za-z][\w&()'’,/ .-]*?)\s*(?:\.{2,}|-|:|\s{2,})\s*(?:Rs\.?|INR|₹)?\s*(?P<price>\d+(?:\.\d{1,2})?)\s*$"
)
_DAY_HEADER = re.compile(r"^(?P<day>monday|tuesday|wednesday|thursday|friday|saturday|sunday|daily|all days)\b", re.I)
_VALIDITY = re.compile(
    r"valid\s+(?:from\s+)?(?P<start>\d{4}-\d{2}-\d{2})\s+(?:to|-)\s+(?P<end>\d{4}-\d{2}-\d{2})", re.I
)


def menu_from_pdf(path: Path, currency: str = "INR") -> MenuData:
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
    with pymupdf.open(path) as doc:  # type: ignore[no-untyped-call]
        lines = [ln.strip() for page in doc for ln in page.get_text().splitlines() if ln.strip()]
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
    mtime = datetime.fromtimestamp(path.stat().st_mtime).date().isoformat()
    return MenuData(
        cafeteria=path.stem.replace("_", " ").title(),
        currency=currency,
        weekly=weekly,
        always_available=always,
        data_as_of=mtime,
        valid_from=valid_from,
        valid_to=valid_to,
    )


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


class MenuProvider:
    """Serves menu queries over a ``MenuData`` snapshot."""

    def __init__(self, data: MenuData, mode: str, provider: str, today: Callable[[], date] | None = None) -> None:
        self._data = data
        self._mode = mode
        self._provider = provider
        self._today = today or date.today

    def source_info(self) -> SourceInfo:
        today = self._today()
        stale = bool(
            (self._data.valid_from and today < self._data.valid_from)
            or (self._data.valid_to and today > self._data.valid_to)
        )
        notes = {
            "demo": "Simulated menu and prices for demonstration; not a live cafeteria feed.",
            "imported": "Menu imported from an operator-supplied file; not verified against a live system.",
        }
        return SourceInfo(
            mode=self._mode,  # type: ignore[arg-type]
            provider=self._provider,
            data_as_of=self._data.data_as_of,
            valid_from=self._data.valid_from,
            valid_to=self._data.valid_to,
            stale=stale,
            note=notes.get(self._mode),
        )

    def _all_items(self) -> list[MenuItem]:
        by_name: dict[str, MenuItem] = {}
        for day in WEEKDAYS:
            for raw in self._data.weekly.get(day, []):
                item = by_name.setdefault(raw.name, self._to_item(raw, []))
                item.available_on.append(day)
        for raw in self._data.always_available:
            by_name[raw.name] = self._to_item(raw, list(WEEKDAYS))
        return list(by_name.values())

    def _to_item(self, raw: RawItem, days: list[str]) -> MenuItem:
        return MenuItem(
            name=raw.name,
            category=raw.category,
            price=raw.price,
            currency=self._data.currency,
            vegetarian=raw.vegetarian,
            available_on=days,
        )

    def today_menu(self) -> TodayMenu:
        today = self._today()
        weekday = WEEKDAYS[today.weekday()]
        items = [self._to_item(r, [weekday]) for r in self._data.weekly.get(weekday, [])]
        items += [self._to_item(r, list(WEEKDAYS)) for r in self._data.always_available]
        return TodayMenu(
            date=today, weekday=weekday, cafeteria=self._data.cafeteria, items=items, source=self.source_info()
        )

    def search(self, query: str) -> MenuSearchResult:
        q_terms = _norm(query).split()
        matches = [
            item
            for item in self._all_items()
            if q_terms and all(t in _norm(f"{item.name} {item.category}") for t in q_terms)
        ]
        return MenuSearchResult(query=query, count=len(matches), items=matches[:15], source=self.source_info())

    def price(self, item_name: str) -> ItemPrice:
        items = self._all_items()
        target = _norm(item_name)
        exact = [i for i in items if _norm(i.name) == target]
        contains = [i for i in items if target and target in _norm(i.name)]
        hit = exact[0] if exact else (contains[0] if len(contains) == 1 else None)
        if hit:
            return ItemPrice(
                item_name=item_name,
                found=True,
                price=hit.price,
                currency=hit.currency,
                matched_item=hit.name,
                source=self.source_info(),
            )
        names = [i.name for i in items]
        close = difflib.get_close_matches(item_name, names, n=3, cutoff=0.5)
        suggestions = close or [i.name for i in contains[:3]]
        return ItemPrice(item_name=item_name, found=False, suggestions=suggestions, source=self.source_info())


def load_provider_from_env() -> MenuProvider:
    name = os.getenv("CAFETERIA_PROVIDER", "demo").lower()
    if name == "demo":
        return MenuProvider(menu_from_json(DEMO_MENU_PATH), mode="demo", provider="demo-json")
    path_str = os.getenv("CAFETERIA_MENU_PATH")
    if not path_str:
        raise ValueError(f"CAFETERIA_PROVIDER={name} requires CAFETERIA_MENU_PATH.")
    path = Path(path_str)
    if name == "json":
        return MenuProvider(menu_from_json(path), mode="imported", provider=f"json:{path.name}")
    if name == "pdf":
        return MenuProvider(
            menu_from_pdf(path, os.getenv("CAFETERIA_CURRENCY", "INR")), mode="imported", provider=f"pdf:{path.name}"
        )
    raise ValueError(f"Unsupported CAFETERIA_PROVIDER '{name}' (expected demo, json or pdf).")
