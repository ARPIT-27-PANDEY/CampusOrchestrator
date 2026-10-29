"""Hybrid (keyword + embedding) catalogue search, tested offline with a small concept embedder."""

from __future__ import annotations

import builtins
from typing import Any

import pytest
from mcp import Client

from library_mcp.provider import DemoLibraryProvider, load_provider_from_env
from library_mcp.semantic import (
    EmbedderUnavailableError,
    HashingEmbedder,
    SemanticIndex,
    book_text,
    build_embedder,
    rrf_fuse,
    semantic_from_env,
)
from library_mcp.server import build_server

# Words -> concept axes. Paraphrases share an axis with the catalogue subject they describe.
CONCEPTS = {
    "heat": 0, "warmth": 0, "thermal": 0,
    "security": 1, "cybersecurity": 1, "hackers": 1, "cryptography": 1,
    "biography": 2, "autobiography": 2, "life": 2,
    "startups": 3, "company": 3, "entrepreneurship": 3,
}  # fmt: skip
DIM = 5  # axis 4 is a weak shared background so no vector is zero


class ConceptEmbedder:
    name = "concept-test"

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * DIM
        vec[4] = 0.05
        for word in text.lower().replace(",", " ").replace(".", " ").split():
            if word in CONCEPTS:
                vec[CONCEPTS[word]] += 1.0
        return vec

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


@pytest.fixture
def hybrid() -> DemoLibraryProvider:
    prov = DemoLibraryProvider()  # the full catalogue
    prov.enable_semantic(SemanticIndex.build(ConceptEmbedder(), prov.books, min_score=0.6, min_z=1.0))
    return prov


def test_keyword_mode_is_the_default_and_unchanged() -> None:
    prov = load_provider_from_env()
    assert prov.semantic is None if isinstance(prov, DemoLibraryProvider) else True
    found = prov.search("how warmth travels")
    assert found.books == [] and found.search_mode == "keyword"


def test_paraphrase_finds_books_by_meaning(hybrid: DemoLibraryProvider) -> None:
    found = hybrid.search("how warmth travels", limit=5)
    assert found.matched_on == "semantic"
    assert found.search_mode == "hybrid:concept-test"
    assert {b.book_id for b in found.books} >= {"LIB-1013", "LIB-1014"}  # the two heat transfer books
    assert all("heat transfer" in b.subjects or "thermal engineering" in b.subjects for b in found.books)


def test_books_found_by_both_rankings_come_first(hybrid: DemoLibraryProvider) -> None:
    found = hybrid.search("security", limit=5)
    assert found.matched_on == "hybrid"
    assert [b.book_id for b in found.books[:2]] == ["LIB-1072", "LIB-1073"]


def test_exact_title_and_identifier_stay_exact(hybrid: DemoLibraryProvider) -> None:
    title = hybrid.search("Introduction to Algorithms", limit=5)
    assert title.matched_on == "title" and title.books[0].book_id == "LIB-1054"
    ident = hybrid.search("LIB-1013")
    assert ident.matched_on == "identifier" and [b.book_id for b in ident.books] == ["LIB-1013"]


def test_unrelated_query_is_still_an_honest_miss(hybrid: DemoLibraryProvider) -> None:
    found = hybrid.search("underwater basket weaving")
    assert found.books == [] and found.matched_on is None
    assert found.message and "No title, subject or author" in found.message


def test_filters_apply_to_semantic_results(hybrid: DemoLibraryProvider) -> None:
    found = hybrid.search("biography life stories", author="Isaacson", limit=5)
    assert [b.book_id for b in found.books] == ["LIB-1134"]


def test_z_gate_drops_books_that_do_not_stand_out() -> None:
    class Flat(ConceptEmbedder):
        def _embed(self, text: str) -> list[float]:
            return [1.0, 0.0, 0.0, 0.0, 0.0]  # every book equally similar to every query

    prov = DemoLibraryProvider()
    prov.enable_semantic(SemanticIndex.build(Flat(), prov.books, min_score=0.5, min_z=1.0))
    assert prov.search("pet grooming").books == []
    loose = SemanticIndex.build(Flat(), prov.books, min_score=0.5, min_z=0.0)
    assert len(loose.rank("pet grooming", [b["book_id"] for b in prov.books])) == len(prov.books)


def test_rrf_fuse_rewards_agreement_and_is_deterministic() -> None:
    assert rrf_fuse(["a", "b", "c"], ["b"]) == ["b", "a", "c"]  # found by both lists -> first
    assert rrf_fuse(["x"], ["y"]) == ["x", "y"]


def test_book_text_uses_catalogue_metadata_only() -> None:
    book: dict[str, Any] = {
        "book_id": "LIB-1", "title": "Heat transfer", "subjects": ["heat transfer"], "discipline": "mechanical",
        "authors": ["J. P. Holman"], "available_copies": 3, "location": "Shelf 9",
    }  # fmt: skip
    text = book_text(book)
    assert "Heat transfer" in text and "Holman" in text and "mechanical" in text
    assert "Shelf" not in text and "3" not in text


def test_env_selects_mode_and_never_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    books = DemoLibraryProvider().books
    monkeypatch.setenv("LIBRARY_SEARCH_MODE", "keyword")
    assert semantic_from_env(books) is None
    monkeypatch.setenv("LIBRARY_SEARCH_MODE", "fuzzy")
    with pytest.raises(ValueError, match="LIBRARY_SEARCH_MODE"):
        semantic_from_env(books)
    monkeypatch.setenv("LIBRARY_SEARCH_MODE", "hybrid")
    monkeypatch.setenv("LIBRARY_EMBEDDER", "hashing")
    index = semantic_from_env(books)
    assert index is not None and isinstance(index.embedder, HashingEmbedder)
    assert index.min_score == 0.60 and index.min_z == 4.0
    monkeypatch.setenv("LIBRARY_SEMANTIC_MIN_SCORE", "0.3")
    monkeypatch.setenv("LIBRARY_SEMANTIC_MIN_Z", "2")
    index = semantic_from_env(books)
    assert index is not None and (index.min_score, index.min_z) == (0.3, 2.0)

    real_import = builtins.__import__

    def no_fastembed(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "fastembed":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_fastembed)
    with pytest.raises(EmbedderUnavailableError, match="fastembed"):
        build_embedder("fastembed")


async def test_mcp_tool_reports_the_search_mode(hybrid: DemoLibraryProvider) -> None:
    async with Client(build_server(provider=hybrid, discovery=None)) as client:
        result = await client.call_tool("search_books", {"query": "starting a company", "limit": 3})
    data = result.structured_content
    assert data is not None
    assert data["search_mode"] == "hybrid:concept-test"
    assert data["matched_on"] in ("semantic", "hybrid")
    assert data["books"] and data["source"]["mode"] == "demo"
