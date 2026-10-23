"""Typed response models for the academics MCP server."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class IndexedDocumentInfo(BaseModel):
    title: str
    source_filename: str
    document_version: str = Field(description="First 12 hex chars of the file's sha256.")
    ingested_at: str
    pages: int
    chunks: int


class SourceInfo(BaseModel):
    source_id: str = "academics"
    mode: Literal["demo", "imported"]
    provider: str
    embedding_model: str
    index_freshness: str = Field(
        description="Documents are served from an index snapshot; re-run ingestion to pick up changes."
    )
    documents: list[IndexedDocumentInfo]


class Passage(BaseModel):
    citation_id: str = Field(description="Stable identifier: <doc_id>-p<page>-c<chunk>.")
    document_title: str
    source_filename: str
    document_version: str
    page: int
    section: str
    excerpt: str
    score: float
    untrusted_instructions_removed: bool = Field(
        default=False, description="True if instruction-like text was redacted from this excerpt."
    )


class HandbookSearchResult(BaseModel):
    query: str
    found: bool
    passages: list[Passage]
    message: str | None = None
    source: SourceInfo


class PolicyDetails(BaseModel):
    policy_name: str
    found: bool
    section: str | None = None
    document_title: str | None = None
    pages: list[int] = Field(default_factory=list)
    passages: list[Passage] = Field(default_factory=list)
    message: str | None = None
    source: SourceInfo
