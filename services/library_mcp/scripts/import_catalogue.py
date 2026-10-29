"""Build the demo campus catalogue from a curated title list + verified Open Library metadata.

* CURATED lists (title, author, discipline, extra subject tags). Nothing else is typed by hand.
* For each entry ONE Open Library search request is made (>= 1.1 s apart, identifying User-Agent).
  The best match must agree on title (normalised prefix/equality) and author surname; otherwise the
  entry is skipped and listed in the report. Title, authors, first publication year, publisher,
  ISBN-13s and the work id come from Open Library - never invented.
* Holdings (copies, available, shelf, call number, due dates) are SYNTHETIC, generated
  deterministically from the work id, and labelled as such in the fixture.

Run (one-off, network required; results are committed as library_mcp/data/demo_books.json):
    python services/library_mcp/scripts/import_catalogue.py [--dry-run] [--only-missing]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
import time
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "library_mcp" / "data" / "demo_books.json"
V1 = ROOT / "library_mcp" / "data" / "demo_books_v1.json"
REPORT = ROOT / "scripts" / "import_catalogue_report.json"
UA = "CampusOrchestrator/0.2 (+https://github.com/ARPIT-27-PANDEY/CampusOrchestrator)"

# (title, author surname or name, discipline, extra tags)
CURATED: list[tuple[str, str, str, list[str]]] = [
    # Mechanical engineering
    ("Engineering Mechanics: Statics", "Meriam", "mechanical", ["mechanics", "statics", "engineering mechanics"]),
    ("Engineering Mechanics: Dynamics", "Meriam", "mechanical", ["mechanics", "dynamics", "engineering mechanics"]),
    ("Vector Mechanics for Engineers", "Beer", "mechanical", ["mechanics", "statics", "dynamics"]),
    ("Engineering Mechanics", "Timoshenko", "mechanical", ["mechanics", "statics", "dynamics"]),
    ("Mechanics of Materials", "Gere", "mechanical", ["mechanics of materials", "strength of materials", "solid mechanics"]),
    ("Mechanics of Materials", "Hibbeler", "mechanical", ["mechanics of materials", "strength of materials"]),
    ("Strength of Materials", "Timoshenko", "mechanical", ["strength of materials", "mechanics of materials"]),
    ("Thermodynamics: An Engineering Approach", "Cengel", "mechanical", ["thermodynamics", "thermal engineering"]),
    ("Fundamentals of Engineering Thermodynamics", "Moran", "mechanical", ["thermodynamics"]),
    ("Engineering Thermodynamics", "Nag", "mechanical", ["thermodynamics"]),
    ("Fluid Mechanics", "White", "mechanical", ["fluid mechanics", "fluids"]),
    ("Introduction to Fluid Mechanics", "Fox", "mechanical", ["fluid mechanics", "fluids"]),
    ("Heat Transfer", "Holman", "mechanical", ["heat transfer", "thermal engineering"]),
    ("Fundamentals of Heat and Mass Transfer", "Incropera", "mechanical", ["heat transfer", "mass transfer"]),
    ("Shigley's Mechanical Engineering Design", "Budynas", "mechanical", ["machine design", "design"]),
    ("Design of Machine Elements", "Bhandari", "mechanical", ["machine design"]),
    ("Manufacturing Engineering and Technology", "Kalpakjian", "mechanical", ["manufacturing", "production"]),
    ("Theory of Machines and Mechanisms", "Uicker", "mechanical", ["theory of machines", "mechanisms", "kinematics"]),
    ("Mechanical Vibrations", "Rao", "mechanical", ["vibrations", "dynamics"]),
    ("Machine Design", "Norton", "mechanical", ["machine design"]),
    # Electrical and electronics
    ("Engineering Circuit Analysis", "Hayt", "electrical", ["circuit analysis", "circuits", "network analysis"]),
    ("Fundamentals of Electric Circuits", "Alexander", "electrical", ["circuit analysis", "circuits"]),
    ("Signals and Systems", "Oppenheim", "electrical", ["signals and systems", "signal processing"]),
    ("Signals and Systems", "Haykin", "electrical", ["signals and systems"]),
    ("Modern Control Engineering", "Ogata", "electrical", ["control systems", "control engineering"]),
    ("Control Systems Engineering", "Nise", "electrical", ["control systems"]),
    ("Microelectronic Circuits", "Sedra", "electrical", ["electronics", "analog electronics", "microelectronics"]),
    ("Digital Design", "Mano", "electrical", ["digital electronics", "logic design"]),
    ("The Art of Electronics", "Horowitz", "electrical", ["electronics", "analog electronics"]),
    ("Communication Systems", "Haykin", "electrical", ["communication systems", "communications"]),
    ("Principles of Communication Systems", "Taub", "electrical", ["communication systems"]),
    ("Power System Analysis", "Grainger", "electrical", ["power systems"]),
    ("Electric Machinery", "Fitzgerald", "electrical", ["electrical machines", "power systems"]),
    ("Introduction to Embedded Systems", "Lee", "electrical", ["embedded systems", "cyber-physical systems"]),
    ("The 8051 Microcontroller and Embedded Systems", "Mazidi", "electrical", ["embedded systems", "microcontrollers"]),
    ("Digital Signal Processing", "Proakis", "electrical", ["signal processing", "dsp"]),
    ("Electronic Devices and Circuit Theory", "Boylestad", "electrical", ["electronics", "devices"]),
    ("Power Electronics", "Rashid", "electrical", ["power electronics", "power systems"]),
    ("Electromagnetic Waves and Radiating Systems", "Jordan", "electrical", ["electromagnetics"]),
    # Civil engineering
    ("Structural Analysis", "Hibbeler", "civil", ["structural engineering", "structures"]),
    ("Design of Reinforced Concrete", "McCormac", "civil", ["structural engineering", "concrete", "rcc"]),
    ("Steel Design", "Segui", "civil", ["structural engineering", "steel structures"]),
    ("Principles of Geotechnical Engineering", "Das", "civil", ["geotechnical engineering", "soil mechanics"]),
    ("Soil Mechanics in Engineering Practice", "Terzaghi", "civil", ["geotechnical engineering", "soil mechanics"]),
    ("Open-Channel Hydraulics", "Chow", "civil", ["hydraulics", "water resources"]),
    ("Hydraulics in Civil and Environmental Engineering", "Chadwick", "civil", ["hydraulics"]),
    ("Traffic Engineering", "Roess", "civil", ["transportation engineering", "traffic"]),
    ("Principles of Highway Engineering and Traffic Analysis", "Mannering", "civil", ["transportation engineering", "highways"]),
    ("Elementary Surveying", "Ghilani", "civil", ["surveying"]),
    ("Surveying: Principles and Applications", "Kavanagh", "civil", ["surveying"]),
    ("Construction Planning, Equipment, and Methods", "Peurifoy", "civil", ["construction", "construction management"]),
    ("Environmental Engineering", "Peavy", "civil", ["environmental engineering", "water supply"]),
    ("Engineering Hydrology", "Subramanya", "civil", ["hydrology", "water resources"]),
    # Computer science
    ("Introduction to Algorithms", "Cormen", "computer science", ["algorithms", "data structures"]),
    ("Algorithm Design", "Kleinberg", "computer science", ["algorithms"]),
    ("The Algorithm Design Manual", "Skiena", "computer science", ["algorithms"]),
    ("Data Structures and Algorithm Analysis in C++", "Weiss", "computer science", ["data structures", "algorithms"]),
    ("Artificial Intelligence: A Modern Approach", "Russell", "computer science", ["artificial intelligence", "ai"]),
    ("Pattern Recognition and Machine Learning", "Bishop", "computer science", ["machine learning", "pattern recognition"]),
    ("Deep Learning", "Goodfellow", "computer science", ["deep learning", "machine learning", "neural networks"]),
    ("The Elements of Statistical Learning", "Hastie", "computer science", ["machine learning", "statistics"]),
    ("Machine Learning", "Mitchell", "computer science", ["machine learning"]),
    ("Database System Concepts", "Silberschatz", "computer science", ["databases", "dbms"]),
    ("Fundamentals of Database Systems", "Elmasri", "computer science", ["databases", "dbms"]),
    ("Operating System Concepts", "Silberschatz", "computer science", ["operating systems"]),
    ("Modern Operating Systems", "Tanenbaum", "computer science", ["operating systems"]),
    ("Computer Networks", "Tanenbaum", "computer science", ["computer networks", "networking"]),
    ("Computer Networking: A Top-Down Approach", "Kurose", "computer science", ["computer networks", "networking"]),
    ("Software Engineering", "Sommerville", "computer science", ["software engineering"]),
    ("Clean Code", "Martin", "computer science", ["software engineering", "programming"]),
    ("Design Patterns", "Gamma", "computer science", ["software engineering", "design patterns"]),
    ("Security Engineering", "Anderson", "computer science", ["cybersecurity", "security"]),
    ("Cryptography and Network Security", "Stallings", "computer science", ["cybersecurity", "cryptography"]),
    ("Structure and Interpretation of Computer Programs", "Abelson", "computer science", ["programming"]),
    ("The C Programming Language", "Kernighan", "computer science", ["programming", "c"]),
    ("Computer Organization and Design", "Patterson", "computer science", ["computer architecture"]),
    ("Compilers: Principles, Techniques, and Tools", "Aho", "computer science", ["compilers"]),
    # Mathematics and sciences
    ("Linear Algebra and Its Applications", "Strang", "mathematics", ["linear algebra"]),
    ("Introduction to Linear Algebra", "Strang", "mathematics", ["linear algebra"]),
    ("Linear Algebra Done Right", "Axler", "mathematics", ["linear algebra"]),
    ("Calculus", "Spivak", "mathematics", ["calculus"]),
    ("Thomas' Calculus", "Thomas", "mathematics", ["calculus"]),
    ("Advanced Engineering Mathematics", "Kreyszig", "mathematics", ["engineering mathematics", "calculus", "differential equations"]),
    ("A First Course in Probability", "Ross", "mathematics", ["probability", "statistics"]),
    ("Probability and Statistics for Engineers and Scientists", "Walpole", "mathematics", ["probability", "statistics"]),
    ("Introduction to Probability", "Bertsekas", "mathematics", ["probability"]),
    ("All of Statistics", "Wasserman", "mathematics", ["statistics"]),
    ("Numerical Methods for Engineers", "Chapra", "mathematics", ["numerical methods"]),
    ("Numerical Recipes", "Press", "mathematics", ["numerical methods", "scientific computing"]),
    ("Fundamentals of Physics", "Halliday", "physics", ["physics", "mechanics"]),
    ("The Feynman Lectures on Physics", "Feynman", "physics", ["physics"]),
    ("Concepts of Physics", "Verma", "physics", ["physics"]),
    ("Introduction to Electrodynamics", "Griffiths", "physics", ["physics", "electromagnetics"]),
    ("Introduction to Quantum Mechanics", "Griffiths", "physics", ["physics", "quantum mechanics"]),
    ("Physical Chemistry", "Atkins", "chemistry", ["chemistry", "physical chemistry"]),
    ("Organic Chemistry", "Clayden", "chemistry", ["chemistry", "organic chemistry"]),
    ("Inorganic Chemistry", "Shriver", "chemistry", ["chemistry", "inorganic chemistry"]),
    ("Chemistry: The Central Science", "Brown", "chemistry", ["chemistry"]),
    # Humanities and management
    ("Principles of Economics", "Mankiw", "economics", ["economics", "microeconomics", "macroeconomics"]),
    ("Economics", "Samuelson", "economics", ["economics"]),
    ("The Wealth of Nations", "Smith", "economics", ["economics", "classics"]),
    ("Thinking, Fast and Slow", "Kahneman", "psychology", ["psychology", "behavioural economics"]),
    ("Psychology", "Myers", "psychology", ["psychology"]),
    ("Influence: The Psychology of Persuasion", "Cialdini", "psychology", ["psychology", "persuasion"]),
    ("The Lean Startup", "Ries", "entrepreneurship", ["entrepreneurship", "startups"]),
    ("Zero to One", "Thiel", "entrepreneurship", ["entrepreneurship", "startups"]),
    ("Innovation and Entrepreneurship", "Drucker", "entrepreneurship", ["entrepreneurship", "innovation"]),
    ("The Effective Executive", "Drucker", "management", ["management"]),
    ("Good to Great", "Collins", "management", ["management", "leadership"]),
    ("Marketing Management", "Kotler", "management", ["management", "marketing"]),
    ("On Writing Well", "Zinsser", "communication", ["communication", "writing"]),
    ("The Elements of Style", "Strunk", "communication", ["communication", "writing"]),
    ("How to Win Friends and Influence People", "Carnegie", "communication", ["communication", "soft skills"]),
    ("Sapiens", "Harari", "history", ["history", "anthropology"]),
    ("Guns, Germs, and Steel", "Diamond", "history", ["history", "geography"]),
    ("The Discovery of India", "Nehru", "history", ["history", "india"]),
    ("India's Struggle for Independence", "Chandra", "history", ["history", "india"]),
    ("Sociology", "Giddens", "sociology", ["sociology"]),
    # General reading
    ("To Kill a Mockingbird", "Lee", "fiction", ["fiction", "novel"]),
    ("Nineteen Eighty-Four", "Orwell", "fiction", ["fiction", "novel", "dystopia"]),
    ("Pride and Prejudice", "Austen", "fiction", ["fiction", "classics", "public domain"]),
    ("Frankenstein", "Shelley", "fiction", ["fiction", "classics", "public domain"]),
    ("The God of Small Things", "Roy", "fiction", ["fiction", "indian literature"]),
    ("Malgudi Days", "Narayan", "fiction", ["fiction", "indian literature", "short stories"]),
    ("Gitanjali", "Tagore", "literature", ["poetry", "indian literature", "public domain"]),
    ("The Great Gatsby", "Fitzgerald", "fiction", ["fiction", "classics"]),
    ("Crime and Punishment", "Dostoyevsky", "fiction", ["fiction", "classics", "public domain"]),
    ("The Adventures of Sherlock Holmes", "Doyle", "fiction", ["fiction", "mystery", "public domain"]),
    ("Hamlet", "Shakespeare", "literature", ["drama", "classics", "public domain"]),
    ("War and Peace", "Tolstoy", "fiction", ["fiction", "classics", "public domain"]),
    ("Meditations", "Marcus Aurelius", "literature", ["philosophy", "classics", "public domain"]),
    ("Wings of Fire", "Kalam", "biography", ["biography", "autobiography", "india"]),
    ("The Story of My Experiments with Truth", "Gandhi", "biography", ["biography", "autobiography", "india"]),
    ("Steve Jobs", "Isaacson", "biography", ["biography", "technology"]),
    ("Surely You're Joking, Mr. Feynman!", "Feynman", "biography", ["biography", "physics"]),
    ("The Diary of a Young Girl", "Frank", "biography", ["biography", "history"]),
    ("Silent Spring", "Carson", "environment", ["environment", "ecology", "environmental studies"]),
    ("The Sixth Extinction", "Kolbert", "environment", ["environment", "ecology", "climate"]),
    ("This Changes Everything", "Klein", "environment", ["environment", "climate change"]),
    ("A Brief History of Time", "Hawking", "general science", ["science", "cosmology", "physics"]),
    ("The Selfish Gene", "Dawkins", "general science", ["science", "biology", "evolution"]),
    ("Cosmos", "Sagan", "general science", ["science", "astronomy"]),
    ("On the Origin of Species", "Darwin", "general science", ["science", "biology", "evolution", "public domain"]),
    ("The Gene: An Intimate History", "Mukherjee", "general science", ["science", "biology", "genetics"]),
]  # fmt: skip

DISCIPLINE_PREFIX = {
    "mechanical": "ME", "electrical": "EE", "civil": "CE", "computer science": "CS", "mathematics": "MA",
    "physics": "PH", "chemistry": "CY", "economics": "HS", "psychology": "HS", "entrepreneurship": "MS",
    "management": "MS", "communication": "HS", "history": "HS", "sociology": "HS", "fiction": "GR",
    "literature": "GR", "biography": "GR", "environment": "GR", "general science": "GR",
}  # fmt: skip


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]", "", text.lower().replace("&", "and")).strip()


def title_ok(wanted: str, got: str) -> bool:
    w, g = norm(wanted), norm(got)
    w_main, g_main = norm(wanted.split(":")[0]), norm(got.split(":")[0])
    return w == g or g.startswith(w) or w.startswith(g) or w_main == g_main


def author_ok(wanted: str, authors: list[str]) -> bool:
    key = norm(wanted).split()[-1]
    return any(key in norm(a).split() for a in authors) or any(key in norm(a) for a in authors)


def lookup(client: httpx.Client, title: str, author: str) -> dict[str, Any] | None:
    fields = "key,title,author_name,first_publish_year,publisher,isbn,language,edition_count"
    resp = client.get(
        "https://openlibrary.org/search.json",
        params={"title": title, "author": author, "limit": "5", "fields": fields},
    )
    resp.raise_for_status()
    docs = resp.json().get("docs", [])
    good = [d for d in docs if title_ok(title, d.get("title", "")) and author_ok(author, d.get("author_name") or [])]
    good.sort(key=lambda d: -(d.get("edition_count") or 0))  # the main work has the most editions
    return good[0] if good else None


def synthetic_holdings(work: str, prefix: str, n: int) -> dict[str, Any]:
    rng = random.Random(hashlib.sha256(work.encode()).hexdigest())
    total = rng.randint(1, 6)
    available = rng.randint(0, total)
    out = available - 0
    due = sorted(rng.randint(1, 28) for _ in range(total - out))
    return {
        "total_copies": total,
        "available_copies": available,
        "location": f"Demo stacks, {prefix} section, shelf {rng.randint(1, 40)}",
        "call_number": f"DEMO-{prefix}-{n:04d}",
        "due_in_days": due,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    v1 = json.loads(V1.read_text(encoding="utf-8"))
    retrieved = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    books: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    seen: set[str] = set()
    with httpx.Client(timeout=30, headers={"User-Agent": UA}) as client:
        for i, (title, author, discipline, tags) in enumerate(CURATED, start=1):
            try:
                doc = lookup(client, title, author)
            except httpx.HTTPError as exc:
                skipped.append({"title": title, "author": author, "reason": f"request failed: {type(exc).__name__}"})
                doc = None
            time.sleep(1.1)
            if doc is None:
                skipped.append({"title": title, "author": author, "reason": "no confident Open Library match"})
                print(f"SKIP {title} / {author}", file=sys.stderr)
                continue
            work = str(doc["key"]).rsplit("/", 1)[-1]
            if work in seen:
                skipped.append({"title": title, "author": author, "reason": f"duplicate work {work}"})
                continue
            seen.add(work)
            isbn13 = [x for x in (doc.get("isbn") or []) if len(x) == 13][:2]
            prefix = DISCIPLINE_PREFIX[discipline]
            books.append({
                "book_id": f"LIB-{1000 + i}",
                "title": doc["title"],
                "authors": (doc.get("author_name") or [])[:4],
                "year": doc.get("first_publish_year"),
                "publisher": (doc.get("publisher") or [None])[0],
                "isbn_13": isbn13,
                "language": (doc.get("language") or [])[:3],
                "discipline": discipline,
                "subjects": tags,
                "metadata": {
                    "provider": "Open Library",
                    "record_url": f"https://openlibrary.org/works/{work}",
                    "openlibrary_work": work,
                    "retrieved_at": retrieved,
                    "note": "year = first publication of the work; publisher and ISBNs belong to some edition.",
                },
                **synthetic_holdings(work, prefix, i),
            })  # fmt: skip
            print(f"ok   {doc['title'][:60]:<60} {work}", file=sys.stderr)
    payload = {
        "description": (
            "Demo campus catalogue. Bibliographic fields come from Open Library (see metadata.record_url); "
            "copies, availability, shelf locations, call numbers and due dates are SYNTHETIC and do not "
            "describe IIT Roorkee library holdings. Built by services/library_mcp/scripts/import_catalogue.py."
        ),
        "data_as_of": retrieved[:10],
        "holdings": "synthetic",
        "hours": v1["hours"],
        "books": books,
    }
    REPORT.write_text(json.dumps({"retrieved_at": retrieved, "curated": len(CURATED), "imported": len(books),
                                  "skipped": skipped}, indent=2) + "\n", encoding="utf-8")  # fmt: skip
    print(f"imported {len(books)}/{len(CURATED)}; skipped {len(skipped)} (see {REPORT.name})", file=sys.stderr)
    if not args.dry_run:
        OUT.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
