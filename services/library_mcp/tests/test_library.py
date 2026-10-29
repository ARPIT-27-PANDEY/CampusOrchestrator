"""Library MCP server tests: provider logic plus the real MCP protocol (in-process)."""

from __future__ import annotations

from datetime import date

import pytest
from mcp import Client

from library_mcp.provider import DEMO_DATA_PATH, BookNotFoundError, DemoLibraryProvider
from library_mcp.server import build_server

V1_CATALOGUE = DEMO_DATA_PATH.with_name("demo_books_v1.json")
EXPECTED_TOOLS = {"search_books", "get_book_availability", "get_library_hours"}


@pytest.fixture
def provider() -> DemoLibraryProvider:
    return DemoLibraryProvider(V1_CATALOGUE)  # the original 23-book catalogue these tests describe


def test_search_ranks_exact_title_first(provider: DemoLibraryProvider) -> None:
    books = provider.search_books("Introduction to Algorithms", None, 5)
    assert books[0].book_id == "LIB-0001"


def test_search_author_filter(provider: DemoLibraryProvider) -> None:
    books = provider.search_books("concepts", "Silberschatz", 10)
    assert {b.book_id for b in books} == {"LIB-0006", "LIB-0008"}


def test_search_no_match_returns_empty(provider: DemoLibraryProvider) -> None:
    assert provider.search_books("underwater basket weaving", None, 5) == []


def test_availability_unknown_book(provider: DemoLibraryProvider) -> None:
    with pytest.raises(BookNotFoundError):
        provider.get_book_availability("LIB-9999")


def test_availability_reports_next_due_date(provider: DemoLibraryProvider) -> None:
    result = provider.get_book_availability("lib-0002")  # case-insensitive id
    assert result.available is False
    assert result.next_due_date == date(2026, 10, 30)
    assert result.source.mode == "demo"


@pytest.mark.parametrize(
    ("day", "is_open", "open_time"),
    [
        (date(2026, 10, 26), True, "08:00"),  # Monday
        (date(2026, 10, 24), True, "09:00"),  # Saturday
        (date(2026, 10, 25), True, "12:00"),  # Sunday
        (date(2026, 11, 8), False, None),  # closure
        (date(2026, 12, 7), True, "08:00"),  # special hours
    ],
)
def test_hours(provider: DemoLibraryProvider, day: date, is_open: bool, open_time: str | None) -> None:
    hours = provider.get_library_hours(day)
    assert hours.is_open is is_open
    assert hours.open_time == open_time


async def test_mcp_lists_expected_tools() -> None:
    async with Client(build_server()) as client:
        tools = await client.list_tools()
    assert {t.name for t in tools.tools} == EXPECTED_TOOLS
    for tool in tools.tools:
        assert tool.description, f"{tool.name} must be described for the LLM"
        assert tool.input_schema["type"] == "object"


async def test_mcp_search_returns_structured_demo_result() -> None:
    async with Client(build_server()) as client:
        result = await client.call_tool("search_books", {"query": "machine learning", "limit": 3})
    assert not result.is_error
    data = result.structured_content
    assert data is not None
    assert 0 < data["count"] <= 3
    assert data["source"]["mode"] == "demo"


@pytest.mark.parametrize(
    "args",
    [
        {"query": ""},
        {"query": "x", "limit": 0},
        {"query": "x", "limit": 500},
        {"limit": 3},
    ],
)
async def test_mcp_rejects_invalid_search_args(args: dict[str, object]) -> None:
    async with Client(build_server()) as client:
        result = await client.call_tool("search_books", args)
    assert result.is_error


async def test_mcp_rejects_malformed_book_id() -> None:
    async with Client(build_server()) as client:
        result = await client.call_tool("get_book_availability", {"book_id": "../../etc/passwd"})
    assert result.is_error


async def test_mcp_unknown_book_is_tool_error_not_crash() -> None:
    async with Client(build_server()) as client:
        result = await client.call_tool("get_book_availability", {"book_id": "LIB-9999"})
    assert result.is_error
    assert "LIB-9999" in result.content[0].text  # type: ignore[union-attr]


async def test_mcp_hours_with_explicit_date() -> None:
    async with Client(build_server()) as client:
        result = await client.call_tool("get_library_hours", {"date": "2026-11-08"})
    assert result.structured_content is not None
    assert result.structured_content["is_open"] is False
