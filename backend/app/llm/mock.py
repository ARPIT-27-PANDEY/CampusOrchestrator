"""Deterministic LLM test doubles.

``MockProvider`` is a rule-based stand-in for the real model so the whole
pipeline (discovery -> tool selection -> MCP execution -> synthesis) runs in
tests, CI and evals with no API key. It only calls tools that were actually
discovered and passed to it (it matches on the tool-name suffix), so it still
exercises dynamic discovery. Its "intelligence" is keyword routing; eval
reports label mock results accordingly and they say nothing about GPT-OSS quality.

``ScriptedProvider`` replays canned responses to test failure paths
(malformed calls, unknown tools, empty output, endless tool loops).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from .base import ChatMessage, LLMResponse, TextCallback, ToolCall, ToolSpec

_RESULT_RE = re.compile(r"<tool_result[^>]*>\s*(.*?)\s*</tool_result>", re.S)

_WORD = re.compile(r"[a-z0-9][a-z0-9'+-]*")
_FILLER = {
    "find", "show", "me", "the", "next", "upcoming", "a", "an", "is", "are", "there", "any", "when", "what",
    "whats", "what's", "tell", "please", "can", "you", "i", "check", "whether", "if", "list", "get", "also",
    "and", "about", "on", "campus", "of", "for", "in", "at", "to", "do", "does", "which", "my", "it", "be",
    "will", "this", "week", "so", "far", "know", "want", "need", "give", "happening", "held", "scheduled",
    "coming", "up", "soon", "served", "serve", "serving", "day", "days", "cafeteria", "canteen", "menu",
}  # fmt: skip

EVENT_WORDS = (
    "event", "events", "workshop", "workshops", "hackathon", "lecture", "seminar", "career fair", "contest",
    "competition", "cultural night", "reading group", "football", "happening", "coming up", "talk", "holiday",
    "fest", "thomso", "cognizance", "sangram", "convocation",
)  # fmt: skip
LIBRARY_BOOK_WORDS = (
    "book",
    "borrow",
    "ebook",
    "copies",
    "copy of",
    "textbook",
    "on the shelf",
    "checked out",
    "catalogue",
)
LIBRARY_HOURS = re.compile(
    r"library\s+(hours|timings?|open|close|closing|opening)|(when|is|what time)\b.*\blibrary\b.*\b(open|close)", re.I
)
CAFE_WORDS = (
    "menu", "cafeteria", "canteen", "lunch", "dinner", "breakfast", "food", "eat", "dish", "biryani", "chai",
    "coffee", "thali", "dosa", "samosa", "sandwich", "pizza", "noodles", "paneer", "veg ", "price of",
)  # fmt: skip
ACADEMIC_WORDS = (
    "handbook", "policy", "policies", "prerequisite", "attendance", "grading", "grade", "cgpa", "gpa",
    "re-evaluation", "reevaluation", "plagiarism", "integrity", "internship", "credit", "probation",
    "examination", "rule", "regulation", "allowed", "fine", "fines", "id card", "hostel", "curfew",
    "certificate", "scholarship", "condonation", "generative ai", "chatgpt", "re-register", "make-up",
    "makeup exam", "debarred", "notice board", "faq", "moocs", "mooc", "waiver", "register for", "semester",
    "penalty", "unfair means", "prohibited", "cheating", "duration", "programme", "b.tech", "phd", "ph.d", "thesis",
    "academic bank", "minor programme", "minor program", "re-examination", "backlog", "branch change",
)  # fmt: skip
GREETING = re.compile(r"^\s*(hi|hello|hey|good (morning|afternoon|evening)|thanks|thank you)\b[!. ]*$", re.I)
VAGUE = re.compile(r"^\s*(is it|how much( is it)?|when is it|where is it|what about (it|that)|and that)\??\s*$", re.I)
TITLE_AVAILABLE = re.compile(
    r"(?i:whether|if|is|are)\s+(?i:the\s+book\s+)?[\"'“]?(?P<title>[A-Z][\w:,'’ -]+?)[\"'”]?\s+(?:is\s+|are\s+)?"
    r"(?i:available|in stock|on the shelf|checked out|in the library)",
)
QUOTED = re.compile(r"[\"“']([^\"”']{3,80})[\"”']")
BOOKS_ON = re.compile(r"books?\s+(?:on|about|for|by)\s+(?P<q>[\w ,.'-]+)", re.I)
PRICE_OF = re.compile(
    r"(?:price of|cost of|how much (?:is|are|does|do)(?: the| a| an)?)\s+(?:the\s+|a\s+|an\s+)?(?P<item>[\w ()'-]+?)(?:\s+cost)?(?:\s+(?:in|at) the (?:cafeteria|canteen))?\s*[?.]?$",
    re.I,
)
SERVE_ITEM = re.compile(
    r"(?:serve|served|serving|have|is there|get)\s+(?:any\s+)?(?P<item>[a-z][\w ]+?)(?:\s+(?:today|on|this|in|at)\b.*)?\s*[?.]?$",
    re.I,
)


def _has(text: str, words: tuple[str, ...]) -> bool:
    """Whole-word match that also accepts a plural ('textbook' matches 'textbooks')."""
    low = f" {text.lower()} "
    return any(re.search(rf"(?<![a-z]){re.escape(w.strip())}(?:e?s)?(?![a-z])", low) for w in words)


def _keywords(text: str) -> str:
    words = [w for w in _WORD.findall(text.lower()) if w not in _FILLER]
    return " ".join(words)


@dataclass
class Intent:
    domain: str  # events | library | library_hours | cafeteria | academics
    clause: str
    args: dict[str, Any] = field(default_factory=dict)
    tool: str = ""


def classify(clause: str) -> str | None:
    if LIBRARY_HOURS.search(clause):
        return "library_hours"
    if _has(clause, ACADEMIC_WORDS) and not _has(clause, LIBRARY_BOOK_WORDS):
        return "academics"
    if _has(clause, LIBRARY_BOOK_WORDS) or TITLE_AVAILABLE.search(clause):
        return "library"
    if _has(clause, EVENT_WORDS):
        return "events"
    if _has(clause, CAFE_WORDS) or PRICE_OF.search(clause):
        return "cafeteria"
    return None


def split_clauses(query: str) -> list[str]:
    pieces = [p.strip(" .") for p in re.split(r"[,;?]|\.\s|\balso\b|\bthen\b", query) if p and p.strip(" .")]
    out: list[str] = []
    for piece in pieces:
        piece = re.sub(r"^(and|but|plus)\s+", "", piece, flags=re.I)
        parts = re.split(r"\band\b", piece)
        if len(parts) == 2 and all(classify(p) for p in parts) and classify(parts[0]) != classify(parts[1]):
            out.extend(p.strip() for p in parts)
        elif piece:
            out.append(piece)
    return out


_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_TODAY_RE = re.compile(r"Today on campus is \w+, (\d{4}-\d{2}-\d{2})")


def resolve_date(clause: str, today: date | None, *, explicit_today: bool = False) -> str | None:
    """Turn 'today', 'tomorrow', a weekday name or an ISO date into YYYY-MM-DD (campus date from the prompt)."""
    if m := re.search(r"\b(\d{4}-\d{2}-\d{2})\b", clause):
        return m.group(1)
    if today is None:
        return None
    low = clause.lower()
    if "tomorrow" in low:
        return (today + timedelta(days=1)).isoformat()
    if explicit_today and re.search(r"\b(today|tonight)\b", low):
        return today.isoformat()
    for i, name in enumerate(_WEEKDAYS):
        if re.search(rf"\b{name}\b", low):
            return (today + timedelta(days=(i - today.weekday()) % 7)).isoformat()
    return None


_DATE_WORDS = re.compile(r"\b(today|tonight|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday|\d{4}-\d{2}-\d{2})\b", re.I)  # fmt: skip
_MEAL = re.compile(r"\b(breakfast|lunch|dinner|snacks?)\b", re.I)
_CUISINE = re.compile(
    r"\b(north indian|south indian|east indian|west indian|chinese|italian|continental|regional)\b", re.I
)
_OPEN_BOOKS = re.compile(
    r"\b(open[- ]access|free(ly)?|download(able)?|pdfs?|read online|public domain|e-?books?)\b", re.I
)


def plan(query: str, today: date | None = None) -> list[Intent]:
    intents: list[Intent] = []
    if VAGUE.match(query):
        return intents  # "how much is it?" - nothing to look up; ask for clarification instead
    for clause in split_clauses(query):
        domain = classify(clause)
        if domain is None:
            continue
        if domain == "events":
            kw = _keywords(re.sub(r"\bevents?\b", "", _DATE_WORDS.sub("", clause), flags=re.I))
            day = resolve_date(clause, today, explicit_today=True) if _DATE_WORDS.search(clause) else None
            if day and not kw:
                intents.append(Intent("events", clause, {"date": day}, "get_events_for_date"))
            elif not kw:
                intents.append(Intent("events", clause, {"limit": 5}, "get_upcoming_events"))
            else:
                intents.append(Intent("events", clause, {"query": kw or clause}, "search_events"))
        elif domain == "library" and _OPEN_BOOKS.search(clause):
            topic = _keywords(
                _OPEN_BOOKS.sub(
                    "", re.sub(r"\b(books?|textbooks?|library|available|online|on|in)\b", "", clause, flags=re.I)
                )
            )
            intents.append(Intent("public_books", clause, {"query": topic or clause, "open_access_only": True}, "discover_public_books"))  # fmt: skip
        elif domain == "library":
            m = TITLE_AVAILABLE.search(clause) or QUOTED.search(clause)
            if m:
                title = (m.group("title") if "title" in m.re.groupindex else m.group(1)).strip()
                title = re.sub(r"^(the book|book)\s+", "", title, flags=re.I)
            elif mb := BOOKS_ON.search(clause):
                title = mb.group("q").strip()
            else:
                title = _keywords(re.sub(r"\b(books?|library|available|copies|borrow)\b", "", clause, flags=re.I))
            intents.append(Intent("library", clause, {"query": title or clause, "limit": 3}, "search_books"))
        elif domain == "library_hours":
            day = resolve_date(clause, today)
            intents.append(Intent("library_hours", clause, {"date": day} if day else {}, "get_library_hours"))
        elif domain == "cafeteria":
            meal = _MEAL.search(clause)
            cuisine = _CUISINE.search(clause)
            veg = re.search(r"\b(veg|vegetarian)\b", clause, re.I) and not re.search(r"non[- ]?veg", clause, re.I)
            day = resolve_date(clause, today, explicit_today=bool(cuisine or veg))
            filters: dict[str, Any] = {}
            if meal:
                filters["meal"] = meal.group(1).lower().rstrip("s") if meal.group(1).lower() != "snacks" else "snacks"
            if mp := PRICE_OF.search(clause):
                intents.append(Intent("cafeteria", clause, {"item_name": mp.group("item").strip()}, "get_item_price"))
            elif day and (
                cuisine or veg or "tomorrow" in clause.lower() or re.search(r"\d{4}-\d{2}-\d{2}|day\b", clause)
            ):
                args = {"date": day, **filters}
                if cuisine:
                    args["cuisine"] = cuisine.group(1).lower()
                if veg:
                    args["vegetarian"] = True
                intents.append(Intent("cafeteria", clause, args, "get_menu_for_date"))
            elif re.search(r"menu|today|lunch|dinner|breakfast|what.*eat|food", clause, re.I) and not re.search(
                r"when|which day", clause, re.I
            ):
                intents.append(Intent("cafeteria", clause, filters, "get_today_menu"))
            else:
                ms = SERVE_ITEM.search(clause)
                item = ms.group("item") if ms else _keywords(clause)
                intents.append(Intent("cafeteria", clause, {"query": item.strip()}, "search_menu_item"))
        elif domain == "academics":
            intents.append(Intent("academics", clause, {"query": clause, "top_k": 3}, "search_handbook"))

    # Resolve anaphora like "which prerequisite the handbook specifies" using the events clause.
    events = next((i for i in intents if i.domain == "events" and "query" in i.args), None)
    for i in intents:
        if (
            i.domain == "academics"
            and events
            and re.search(r"\bprerequisite", i.clause, re.I)
            and not re.search(r"[A-Z]{2,4}\s?\d{3}", i.clause)
        ):
            i.args["query"] = f"prerequisite for the {events.args['query']} series"
    return intents


def _parse_tool_results(messages: list[ChatMessage]) -> dict[str, tuple[str, dict[str, Any] | None, str]]:
    """Map tool_call_id -> (tool_name, parsed payload, status) from the conversation."""
    names: dict[str, str] = {}
    for m in messages:
        for c in m.tool_calls:
            names[c.id] = c.name
    out: dict[str, tuple[str, dict[str, Any] | None, str]] = {}
    for m in messages:
        if m.role != "tool" or not m.tool_call_id:
            continue
        status_match = re.search(r'status="([a-z_]+)"', m.content or "")
        status = status_match.group(1) if status_match else "success"
        body = _RESULT_RE.search(m.content or "")
        payload: dict[str, Any] | None = None
        if body:
            try:
                parsed = json.loads(body.group(1))
                payload = parsed if isinstance(parsed, dict) else None
            except ValueError:
                payload = None
        out[m.tool_call_id] = (names.get(m.tool_call_id, ""), payload, status)
    return out


def _best_sentences(text: str, query: str, limit: int = 2) -> str:
    """Extractive synthesis: quote the passage sentences that share the most words with the question."""
    # Split on sentence ends, but not after abbreviations ("Rs.", "No.", "B.Tech.", "Ph.D.", "M.Sc." ...).
    protected = re.sub(
        r"\b(Rs|No|e\.g|i\.e|B\.Tech|M\.Tech|B\.Arch|B\.Des|Ph\.D|M\.Sc|Dr|Prof|viz)\.", r"\1<DOT>", text
    )
    parts = [x.strip() for x in re.split(r"(?<=[.?!])\s+", protected) if x.strip()]
    sentences = [p.replace("<DOT>", ".") for p in parts]
    q = {w for w in _WORD.findall(query.lower()) if w not in _FILLER and len(w) > 2}

    def overlap(sentence: str) -> int:
        words = set(_WORD.findall(sentence.lower()))
        return sum(1 for w in q if w in words or any(x.startswith(w[:5]) for x in words if len(w) > 5))

    ranked = sorted(range(len(sentences)), key=lambda i: (-overlap(sentences[i]), i))[:limit]
    return " ".join(sentences[i] for i in sorted(ranked)) if sentences else text


def _fmt_dt(value: str) -> str:
    # 2026-10-26T14:00:00+05:30 -> 2026-10-26 14:00
    return value.replace("T", " ")[:16]


def generic_intent(query: str, tools: list[ToolSpec]) -> Intent | None:
    """Fallback for tools the keyword rules do not know: pick the discovered tool whose name and
    description share the most content words with the query, and fill its required string
    arguments with the query keywords. Uses only discovered metadata - no hard-coded names."""
    q = {w for w in _WORD.findall(query.lower()) if w not in _FILLER and len(w) > 2}
    best: tuple[int, ToolSpec] | None = None
    for t in tools:
        words = set(_WORD.findall(f"{t.name.replace('_', ' ')} {t.description}".lower()))
        stems = {w.rstrip("s") for w in words}
        overlap = sum(1 for w in q if w in words or w.rstrip("s") in stems)
        if overlap >= 2 and (best is None or overlap > best[0]):
            best = (overlap, t)
    if best is None:
        return None
    tool = best[1]
    props = tool.parameters.get("properties", {})
    args: dict[str, Any] = {}
    for name in tool.parameters.get("required", []):
        spec = props.get(name, {})
        if spec.get("type") == "string" or "anyOf" not in spec:
            args[name] = _keywords(query) or query
    return Intent("generic", query, args, tool.name.split("__", 1)[-1])


class MockProvider:
    name = "mock"
    model = "mock-deterministic-v1"

    async def complete(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSpec],
        *,
        on_text: TextCallback | None = None,
        allow_tools: bool = True,
    ) -> LLMResponse:
        query = next((m.content or "" for m in reversed(messages) if m.role == "user"), "")
        available = {t.name.split("__", 1)[-1]: t.name for t in tools}
        results = _parse_tool_results(messages)
        system = next((m.content or "" for m in messages if m.role == "system"), "")
        today_match = _TODAY_RE.search(system)
        intents = plan(query, date.fromisoformat(today_match.group(1)) if today_match else None)
        if not intents and not GREETING.match(query) and not VAGUE.match(query):
            known = {"search_books", "get_book_availability", "get_library_hours", "discover_public_books",
                     "search_events", "get_events_for_date", "get_upcoming_events", "get_event_details",
                     "get_today_menu", "get_menu_for_date", "search_menu_item", "get_item_price",
                     "list_dining_locations", "search_handbook", "get_policy_details"}  # fmt: skip
            # Only tools the rules above do not cover are candidates for the generic fallback.
            fallback = generic_intent(query, [t for t in tools if t.name.split("__", 1)[-1] not in known])
            intents = [fallback] if fallback else []
        called = {name for name, _, _ in results.values()}

        calls: list[ToolCall] = []
        if allow_tools and not results:
            for n, intent in enumerate(intents):
                if intent.tool in available:
                    calls.append(
                        ToolCall(f"mock_{n}", available[intent.tool], json.dumps(intent.args), dict(intent.args))
                    )
        elif allow_tools and "get_book_availability" in available and available["get_book_availability"] not in called:
            # Follow-up step: availability check for the best library match.
            for name, payload, status in results.values():
                if name.endswith("__search_books") and status == "success" and payload and payload.get("books"):
                    book_id = payload["books"][0]["book_id"]
                    args = {"book_id": book_id}
                    calls.append(ToolCall("mock_follow_0", available["get_book_availability"], json.dumps(args), args))
                    break
        if calls:
            return LLMResponse(content=None, tool_calls=calls, finish_reason="tool_calls", model=self.model)

        answer = self._compose(query, intents, available, results)
        if on_text:
            for token in re.findall(r"\S+\s*", answer):
                await on_text(token)
        return LLMResponse(
            content=answer, tool_calls=[], finish_reason="stop", model=self.model, streamed=on_text is not None
        )

    # ------------------------------------------------------------------ synthesis
    def _compose(
        self,
        query: str,
        intents: list[Intent],
        available: dict[str, str],
        results: dict[str, tuple[str, dict[str, Any] | None, str]],
    ) -> str:
        if not intents:
            if GREETING.match(query):
                return "Hello! I can look up library books and hours, campus events, the cafeteria menu, and the academic handbook."
            if VAGUE.match(query) or len(_keywords(query).split()) <= 1:
                return (
                    "Could you clarify what you are asking about? For example, which book, event, menu item or policy?"
                )
            return (
                "I can only answer questions about the campus library, events, cafeteria, and academic handbook, "
                "and I don't have a source for that."
            )

        by_tool: dict[str, list[tuple[dict[str, Any] | None, str]]] = {}
        for name, payload, status in results.values():
            by_tool.setdefault(name.split("__", 1)[-1], []).append((payload, status))

        lines: list[str] = []
        demo_sources: set[str] = set()
        for intent in intents:
            if intent.tool not in available:
                lines.append(
                    f"The {intent.domain.replace('_', ' ')} service is currently unavailable, so I couldn't check that."
                )
                continue
            entries = by_tool.get(intent.tool, [])
            payload, status = entries[0] if entries else (None, "missing")
            if status != "success" or payload is None:
                failure = {
                    "timeout": "did not respond in time",
                    "unavailable": "is unreachable right now",
                    "tool_error": "returned an error",
                    "invalid_arguments": "could not process the request",
                }.get(status, "could not be queried")
                lines.append(
                    f"The {intent.domain.replace('_', ' ')} service {failure}, so I couldn't answer that part."
                )
                continue
            source = payload.get("source") or {}
            if source.get("mode") == "demo":
                demo_sources.add(str(source.get("source_id", intent.domain)))
            lines.append(self._describe(intent, payload, by_tool))

        if demo_sources:
            lines.append(
                f"Note: results from {', '.join(sorted(demo_sources))} are demo data, not live campus records."
            )
        return "\n\n".join(line for line in lines if line)

    def _describe(
        self,
        intent: Intent,
        payload: dict[str, Any],
        by_tool: dict[str, list[tuple[dict[str, Any] | None, str]]],
    ) -> str:
        tool = intent.tool
        if tool == "get_events_for_date":
            events = payload.get("events") or []
            day = payload.get("date") or intent.args.get("date")
            if not events:
                return f"The events calendar was checked and lists no events on {day}."
            parts = []
            for e in events[:6]:
                when = "all day" if e.get("all_day") else _fmt_dt(e["start"])[11:]
                tags = [
                    t
                    for t in (
                        "tentative" if e.get("tentative") else "",
                        "demo event" if e.get("origin") == "synthetic" else "",
                    )
                    if t
                ]
                parts.append(f"{e['title']} ({when}{'; ' + ', '.join(tags) if tags else ''})")
            return f"Events on {day}: " + "; ".join(parts) + "."
        if tool == "discover_public_books":
            books = payload.get("books") or []
            failed = [p["provider"] for p in payload.get("providers") or [] if p.get("status") not in ("ok", "cached")]
            note = f" ({', '.join(failed)} could not be searched.)" if failed else ""
            if not books:
                return f'No openly accessible books matched "{intent.args.get("query")}" in the public catalogues searched.{note}'
            listing = "; ".join(
                f"**{b['title']}** ({b['metadata_provider']}, {b['access_type'].replace('_', ' ')})" for b in books[:3]
            )
            return f"Public catalogues (not the campus library) list: {listing}.{note}"
        if tool in ("search_events", "get_upcoming_events"):
            events = payload.get("events") or []
            if not events:
                return f'I couldn\'t find any matching events for "{intent.args.get("query", "upcoming")}".'
            if tool == "search_events":
                e = events[0]
                return f"The next matching event is **{e['title']}** on {_fmt_dt(e['start'])} at {e.get('location') or 'TBA'} ({e['event_id']})."
            upcoming = "; ".join(f"{e['title']} ({_fmt_dt(e['start'])})" for e in events)
            return f"Upcoming events: {upcoming}."
        if tool == "search_books":
            books = payload.get("books") or []
            if not books:
                related = payload.get("suggestions") or []
                extra = f" Related subjects in the catalogue: {', '.join(related)}." if related else ""
                return f'The campus library catalogue has no match for "{intent.args.get("query")}".{extra}'
            avail = next((p for p, s in by_tool.get("get_book_availability", []) if s == "success" and p), None)
            if avail and avail.get("book_id") == books[0]["book_id"]:
                title = avail.get("title", books[0].get("title"))
                total = avail.get("total_copies", "?")
                if avail.get("available"):
                    where = f" at {avail['location']}" if avail.get("location") else ""
                    return f"**{title}** is available: {avail.get('available_copies', '?')} of {total} copies{where}."
                due = f" The next copy is due back on {avail['next_due_date']}." if avail.get("next_due_date") else ""
                return f"**{title}** is currently not available (0 of {total} copies).{due}"
            b = books[0]
            return f"**{b['title']}** has {b['available_copies']} of {b['total_copies']} copies available."
        if tool == "get_library_hours":
            if not payload.get("is_open"):
                return f"The library is closed on {payload['date']} ({payload.get('note') or 'closure'})."
            return f"On {payload['date']} the library is open {payload['open_time']}–{payload['close_time']}."
        if tool in ("get_today_menu", "get_menu_for_date"):
            items = payload.get("items") or []
            meals = [i for i in items if i.get("category") not in ("beverages", "snacks")] or items
            label = "Today's" if tool == "get_today_menu" else f"The {payload.get('date')}"
            where = f" at {payload['cafeteria']}" if payload.get("cafeteria") else ""
            if not items:
                return f"{label} ({payload.get('weekday', '').title()}) menu{where} has no items matching that request."
            listing = "; ".join(f"{i['name']} ({i['currency']} {i['price']:g})" for i in meals[:8])
            return f"{label} ({payload.get('weekday', '').title()}) menu{where}: {listing}."
        if tool == "get_item_price":
            if payload.get("found"):
                return f"{payload['matched_item']} costs {payload['currency']} {payload['price']:g}."
            sugg = payload.get("suggestions") or []
            extra = f" Did you mean: {', '.join(sugg)}?" if sugg else ""
            return f'I couldn\'t find "{payload.get("item_name")}" on the menu.{extra}'
        if tool == "search_menu_item":
            items = payload.get("items") or []
            if not items:
                return f'The cafeteria menu has no item matching "{intent.args.get("query")}".'
            return (
                "; ".join(
                    f"{i['name']} ({i['currency']} {i['price']:g}) is served on {', '.join(d.title() for d in i['available_on'])}"
                    for i in items[:3]
                )
                + "."
            )
        if tool in ("search_handbook", "get_policy_details"):
            passages = payload.get("passages") or []
            if not payload.get("found") or not passages:
                return "I couldn't find supporting evidence for that in the indexed academic documents."
            p = passages[0]
            excerpt = _best_sentences(p["excerpt"], str(intent.args.get("query") or intent.clause))
            return f'According to the {p["document_title"]} (p. {p["page"]}): "{excerpt}" [{p["document_title"]}, p. {p["page"]}]'
        # Unknown (dynamically discovered) tool: report its structured result compactly, without the source block.
        body = {k: v for k, v in payload.items() if k != "source"}
        return f"From {tool.replace('_', ' ')}: {json.dumps(body, ensure_ascii=False)[:400]}"


class ScriptedProvider:
    """Returns pre-defined responses in order; repeats the last one when exhausted."""

    name = "scripted"
    model = "scripted"

    def __init__(self, responses: list[LLMResponse | Exception]) -> None:
        self._responses = responses
        self.calls: list[tuple[list[ChatMessage], list[ToolSpec], bool]] = []

    async def complete(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSpec],
        *,
        on_text: TextCallback | None = None,
        allow_tools: bool = True,
    ) -> LLMResponse:
        self.calls.append((list(messages), list(tools), allow_tools))
        item = self._responses[min(len(self.calls) - 1, len(self._responses) - 1)]
        if isinstance(item, Exception):
            raise item
        if on_text and item.content:
            await on_text(item.content)
        return item
