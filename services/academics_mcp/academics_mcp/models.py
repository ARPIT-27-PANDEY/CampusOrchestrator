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
    origin: Literal["official", "demo"] = Field(
        default="demo", description="official = IIT Roorkee document from the source manifest; demo = fictional."
    )
    source_url: str | None = None
    status: str | None = Field(default=None, description="current | superseded | uncertain (from the manifest).")
    issued: str | None = None


class SourceInfo(BaseModel):
    source_id: str = "academics"
    mode: Literal["demo", "imported"]
    provider: str
    embedding_model: str
    retrieval: str = Field(default="dense", description="dense | hybrid")
    index_freshness: str = Field(
        description="Documents are served from an index snapshot; re-run ingestion to pick up changes."
    )
    retrieved_at: str | None = None
    stale: bool | None = None
    staleness_reason: str | None = None
    documents: list[IndexedDocumentInfo]
    not_indexed: list[str] = Field(
        default_factory=list, description="Manifest documents that could not be indexed (e.g. scanned, needs OCR)."
    )


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
    origin: Literal["official", "demo"] = "demo"
    source_url: str | None = Field(default=None, description="Official URL of the document (open at #page=N).")
    authority: str | None = None
    issued: str | None = None
    reference: str | None = None
    applies_to: list[str] = Field(default_factory=list)
    doc_status: str | None = Field(default=None, description="current | superseded | uncertain")
    superseded_by: list[str] = Field(default_factory=list, description="Titles of documents that supersede this one.")


class HandbookSearchResult(BaseModel):
    query: str
    found: bool
    passages: list[Passage]
    message: str | None = None
    applicability_notes: list[str] = Field(
        default_factory=list,
        description="Conflicts or supersession between returned documents that the answer must mention.",
    )
    source: SourceInfo


class PolicyDetails(BaseModel):
    policy_name: str
    found: bool
    section: str | None = None
    document_title: str | None = None
    pages: list[int] = Field(default_factory=list)
    passages: list[Passage] = Field(default_factory=list)
    message: str | None = None
    applicability_notes: list[str] = Field(default_factory=list)
    source: SourceInfo
