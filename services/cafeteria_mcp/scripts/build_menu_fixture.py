"""Build cafeteria_mcp/data/demo_menu.json: a SYNTHETIC four-week rotation for three demo locations.

None of this is IIT Roorkee mess or canteen data (mess.iitr.ac.in was not reachable when this was
built, and no official menu was used). Location names carry "(demo)". Dish names are generic
regional Indian and international dishes; prices are invented. "vegetarian" is defined by this
synthetic source only; no allergen or nutrition data is given because none is verified.

Rotation: week = ((date - anchor_monday).days // 7) % 4 + 1, computed in the campus timezone.

Run:  python services/cafeteria_mcp/scripts/build_menu_fixture.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

OUT = Path(__file__).resolve().parents[1] / "cafeteria_mcp" / "data" / "demo_menu.json"
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

# (name, cuisine, vegetarian, price)
BREAKFAST = [
    ("Idli Sambar", "south indian", True, 40), ("Masala Dosa", "south indian", True, 55), ("Medu Vada", "south indian", True, 40),
    ("Upma", "south indian", True, 35), ("Pongal", "south indian", True, 40), ("Aloo Paratha with Curd", "north indian", True, 50),
    ("Poha", "west indian", True, 35), ("Puri Bhaji", "north indian", True, 45), ("Chole Kulche", "north indian", True, 55),
    ("Luchi Aloo Dum", "east indian", True, 50), ("Sabudana Khichdi", "west indian", True, 40), ("Thepla with Chutney", "west indian", True, 40),
    ("Bread Omelette", "continental", False, 45), ("Masala Omelette with Toast", "continental", False, 50), ("Cornflakes with Milk", "continental", True, 35),
    ("Pancakes with Honey", "continental", True, 60), ("Uttapam", "south indian", True, 50), ("Misal Pav", "west indian", True, 50),
    ("Paneer Paratha", "north indian", True, 60), ("Egg Bhurji with Pav", "west indian", False, 50), ("Appam with Vegetable Stew", "regional", True, 60),
]  # fmt: skip
LUNCH = [
    ("Rajma Chawal", "north indian", True, 80), ("Kadhi Chawal", "north indian", True, 75), ("Chole Bhature", "north indian", True, 85),
    ("Dal Makhani with Jeera Rice", "north indian", True, 100), ("Veg Thali", "north indian", True, 100), ("Chicken Biryani", "regional", False, 140),
    ("Veg Biryani", "regional", True, 100), ("Hyderabadi Egg Biryani", "regional", False, 120), ("Sambar Rice with Poriyal", "south indian", True, 85),
    ("Curd Rice with Pickle", "south indian", True, 60), ("Bisi Bele Bath", "south indian", True, 80), ("Fish Curry with Rice", "east indian", False, 150),
    ("Machher Jhol with Rice", "east indian", False, 150), ("Shukto with Rice and Dal", "east indian", True, 90), ("Gujarati Thali", "west indian", True, 120),
    ("Pav Bhaji", "west indian", True, 80), ("Dal Baati Churma", "regional", True, 110), ("Chicken Curry with Roti", "north indian", False, 130),
    ("Paneer Butter Masala with Roti", "north indian", True, 120), ("Veg Hakka Noodles", "chinese", True, 90), ("Chilli Chicken with Fried Rice", "chinese", False, 140),
    ("Penne Arrabbiata", "italian", True, 130), ("Margherita Pizza (personal)", "italian", True, 150), ("Grilled Chicken Sandwich", "continental", False, 110),
    ("Veg Pulao with Raita", "north indian", True, 85), ("Kerala Fish Curry with Rice", "regional", False, 150), ("Litti Chokha", "regional", True, 80),
]  # fmt: skip
DINNER = [
    ("Paneer Butter Masala with Roti", "north indian", True, 120), ("Dal Tadka with Jeera Rice", "north indian", True, 90),
    ("Mixed Veg with Roti", "north indian", True, 85), ("Butter Chicken with Naan", "north indian", False, 160),
    ("Egg Curry with Rice", "north indian", False, 90), ("Lemon Rice with Rasam", "south indian", True, 75),
    ("Vegetable Kurma with Parotta", "south indian", True, 95), ("Chicken Chettinad with Rice", "south indian", False, 150),
    ("Aloo Posto with Rice", "east indian", True, 85), ("Kosha Mangsho with Rice", "east indian", False, 170),
    ("Bhindi Masala with Roti", "north indian", True, 85), ("Veg Fried Rice with Manchurian", "chinese", True, 110),
    ("Chicken Fried Rice", "chinese", False, 120), ("Spaghetti Aglio e Olio", "italian", True, 130), ("Veg Lasagne", "italian", True, 160),
    ("Grilled Vegetables with Herb Rice", "continental", True, 140), ("Chicken Stroganoff with Rice", "continental", False, 170),
    ("Malai Kofta with Roti", "north indian", True, 120), ("Undhiyu with Puri", "west indian", True, 110), ("Khichdi with Kadhi", "west indian", True, 75),
]  # fmt: skip
SNACKS = [
    ("Samosa (2 pcs)", "north indian", True, 25), ("Veg Sandwich", "continental", True, 40), ("Bread Pakora", "north indian", True, 25),
    ("Vada Pav", "west indian", True, 25), ("Dhokla", "west indian", True, 40), ("Veg Momos", "chinese", True, 60),
    ("Chicken Momos", "chinese", False, 80), ("Spring Rolls", "chinese", True, 60), ("French Fries", "continental", True, 60),
    ("Garlic Bread", "italian", True, 70), ("Jhalmuri", "east indian", True, 30), ("Egg Roll", "east indian", False, 50),
    ("Paneer Tikka", "north indian", True, 120), ("Maggi Noodles", "chinese", True, 40), ("Masala Corn", "regional", True, 40),
]  # fmt: skip
BEVERAGES = [
    ("Masala Chai", "north indian", True, 20), ("Filter Coffee", "south indian", True, 25), ("Fresh Lime Soda", "regional", True, 35),
    ("Cold Coffee", "continental", True, 60), ("Lassi", "north indian", True, 45), ("Buttermilk", "west indian", True, 25),
    ("Bottled Water (1 L)", "regional", True, 20), ("Hot Chocolate", "continental", True, 60),
]  # fmt: skip

LOCATIONS = [
    {"id": "central", "name": "Central Cafeteria (demo)", "hours": "07:30-22:00",
     "meals": {"breakfast": (BREAKFAST, 3), "lunch": (LUNCH, 4), "snacks": (SNACKS, 3), "dinner": (DINNER, 4)},
     "daily": [b for b in BEVERAGES]},
    {"id": "hostel-mess", "name": "Hostel Mess (demo)", "hours": "07:30-09:30, 12:30-14:30, 19:30-21:30",
     "meals": {"breakfast": (BREAKFAST, 2), "lunch": ([d for d in LUNCH if d[1] != "italian"], 3),
               "dinner": ([d for d in DINNER if d[1] not in ("italian", "continental")], 3)},
     "daily": [BEVERAGES[0], BEVERAGES[6]]},
    {"id": "night-canteen", "name": "Night Canteen (demo)", "hours": "20:00-02:00",
     "meals": {"snacks": (SNACKS, 5), "dinner": ([d for d in DINNER if d[1] in ("chinese", "italian", "continental")], 2)},
     "daily": [BEVERAGES[0], BEVERAGES[3], BEVERAGES[6]]},
]  # fmt: skip


def build() -> dict[str, Any]:
    weeks: dict[str, Any] = {}
    for loc_index, loc in enumerate(LOCATIONS):
        for week in range(1, 5):
            for d, day in enumerate(DAYS):
                items = []
                for m, (meal, (pool, per_day)) in enumerate(loc["meals"].items()):
                    # Deterministic rotation: a different window of the pool every day of the 28-day cycle.
                    start = ((week - 1) * 7 + d) * per_day + m * 3 + loc_index * 5
                    for k in range(per_day):
                        name, cuisine, veg, price = pool[(start + k) % len(pool)]
                        items.append({"name": name, "meal": meal, "category": meal, "cuisine": cuisine,
                                      "vegetarian": veg, "price": price + (5 if loc["id"] == "night-canteen" else 0)})  # fmt: skip
                weeks.setdefault(str(week), {}).setdefault(loc["id"], {})[day] = items
    return {
        "description": (
            "SYNTHETIC four-week menu rotation for three demo locations. Not IIT Roorkee mess or canteen data. "
            "Built by services/cafeteria_mcp/scripts/build_menu_fixture.py."
        ),
        "currency": "INR",
        "data_as_of": None,
        "rotation": {"weeks": 4, "anchor_monday": "2026-10-05"},
        "default_location": "central",
        "locations": [
            {
                "id": loc["id"],
                "name": loc["name"],
                "hours": loc["hours"],
                "synthetic": True,
                "always_available": [
                    {"name": n, "meal": "beverages", "category": "beverages", "cuisine": c, "vegetarian": v, "price": p}
                    for n, c, v, p in loc["daily"]
                ],
            }
            for loc in LOCATIONS
        ],
        "weeks": weeks,
    }


def main() -> None:
    data = build()
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    dishes = {i["name"] for w in data["weeks"].values() for loc in w.values() for day in loc.values() for i in day}
    cuisines = {i["cuisine"] for w in data["weeks"].values() for loc in w.values() for day in loc.values() for i in day}
    print(f"wrote {OUT.name}: {len(dishes)} distinct dishes, cuisines={sorted(cuisines)}")


if __name__ == "__main__":
    main()
