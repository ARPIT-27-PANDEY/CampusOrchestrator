from __future__ import annotations

from collections.abc import Iterator

import pytest

from library_mcp.provider import DEMO_DATA_PATH

V1_CATALOGUE = DEMO_DATA_PATH.with_name("demo_books_v1.json")


@pytest.fixture(autouse=True)
def _offline_defaults(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Tests never call public book APIs; build_server() without arguments uses the v1 catalogue."""
    monkeypatch.setenv("PUBLIC_BOOK_PROVIDERS", "")
    monkeypatch.setenv("LIBRARY_DEMO_DATA", str(V1_CATALOGUE))
    yield
