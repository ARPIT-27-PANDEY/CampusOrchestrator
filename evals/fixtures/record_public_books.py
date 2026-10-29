"""Record real public-book API responses for the offline v2 benchmark (run once; results are committed).

Makes 1 OpenStax catalogue request and one Open Library search per query in QUERIES, >= 1.1 s apart.
The recordings are replayed by evals/run_eval.py so CI never calls these APIs.

    python evals/fixtures/record_public_books.py
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

OUT = Path(__file__).with_name("public_books_replay.json")
UA = "CampusOrchestrator/0.2 (+https://github.com/ARPIT-27-PANDEY/CampusOrchestrator)"
QUERIES = ["thermodynamics", "physics", "calculus"]
OL_FIELDS = (
    "key,title,author_name,first_publish_year,publisher,isbn,language,subject,ebook_access,ia,"
    "edition_count,number_of_pages_median"
)
OS_FIELDS = (
    "title,book_state,authors,high_resolution_pdf_url,webview_rex_link,license_name,license_url,"
    "publish_date,print_isbn_13,digital_isbn_13,book_subjects,book_categories"
)


def main() -> None:
    out: dict[str, object] = {"recorded_at": datetime.now(UTC).isoformat(timespec="seconds"), "openlibrary": {}}
    with httpx.Client(timeout=30, headers={"User-Agent": UA}) as client:
        r = client.get(
            "https://openstax.org/apps/cms/api/v2/pages/",
            params={"type": "books.Book", "fields": OS_FIELDS, "limit": "250"},
        )
        r.raise_for_status()
        items = [i for i in r.json()["items"] if i.get("book_state") == "live"]
        for i in items:  # keep the replay small: drop long subject marketing text
            for s in i.get("book_subjects") or []:
                s.pop("subject_page_content", None)
                s.pop("subject_search_description", None)
        out["openstax"] = {"items": items}
        for q in QUERIES:
            time.sleep(1.1)
            r = client.get("https://openlibrary.org/search.json", params={"q": q, "limit": "10", "fields": OL_FIELDS})
            r.raise_for_status()
            out["openlibrary"][q] = r.json()  # type: ignore[index]
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT.name}: openstax={len(items)} live books, openlibrary={QUERIES}")


if __name__ == "__main__":
    main()
