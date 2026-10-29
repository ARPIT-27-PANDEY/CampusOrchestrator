"""Academics MCP server: handbook search with page-level citations."""

from __future__ import annotations

import logging
import time
from typing import Annotated

import anyio.to_thread
from mcp.server import MCPServer
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from .config import AcademicsSettings
from .ingest import ingest_directory
from .models import HandbookSearchResult, PolicyDetails
from .service import HandbookService, build_index_and_embedder, load_manifest_for

SERVER_NAME = "campus-academics"
log = logging.getLogger("academics_mcp")


def build_service(settings: AcademicsSettings | None = None, connect_retries: int = 15) -> HandbookService:
    cfg = settings or AcademicsSettings.from_env()
    index, embedder = build_index_and_embedder(cfg)
    manifest = load_manifest_for(cfg)
    not_indexed: list[str] = []
    for attempt in range(1, connect_retries + 1):  # Qdrant may still be starting (e.g. under Docker Compose)
        try:
            if cfg.auto_ingest:
                report = ingest_directory(cfg.handbook_dir, index, embedder, manifest=manifest)
                not_indexed = [f"{n} (scanned PDF: needs OCR or manual text)" for n in report.needs_ocr]
                not_indexed += [f"{n} (no extractable text)" for n in report.empty]
                not_indexed += [f"{n} ({err})" for n, err in report.errors.items()]
            else:
                index.ensure_collection()
            break
        except Exception as exc:  # qdrant-client raises several transport error types; re-raised when final
            if attempt == connect_retries or cfg.qdrant_url is None:
                raise
            log.warning("Qdrant not ready (%s); retrying in 2s (%d/%d)", type(exc).__name__, attempt, connect_retries)
            time.sleep(2)
    if manifest:
        present = {p.name for p in cfg.handbook_dir.glob("*.pdf")} if cfg.handbook_dir.exists() else set()
        not_indexed += [f"{d.filename} (not downloaded; run academics_mcp.sources fetch)" for d in
                        manifest.documents if d.filename not in present]  # fmt: skip
    return HandbookService(index, embedder, cfg, manifest=manifest, not_indexed=not_indexed)


def build_server(service: HandbookService | None = None) -> MCPServer:
    svc = service or build_service()
    mcp = MCPServer(
        SERVER_NAME,
        version="0.1.0",
        instructions=(
            "Retrieval over IIT Roorkee academic regulations, Senate notifications and academic calendars "
            "(official PDFs from iitr.ac.in; origin=demo passages are fictional). Every passage includes the "
            "document title, page, citation_id and official source_url. If found=false there is no supporting "
            "evidence; do not answer from general knowledge. Always relay applicability_notes: superseded "
            "documents and programme-specific rules must not be presented as applying to everyone."
        ),
    )

    @mcp.tool()
    async def search_handbook(
        query: Annotated[
            str, Field(min_length=3, max_length=300, description="Natural-language question or keywords.")
        ],
        top_k: Annotated[int, Field(ge=1, le=8, description="Number of passages to return.")] = 4,
    ) -> HandbookSearchResult:
        """Search academic handbooks and policy documents. Returns cited passages (title, page, excerpt)."""
        return await anyio.to_thread.run_sync(svc.search, query, top_k)

    @mcp.tool()
    async def get_policy_details(
        policy_name: Annotated[
            str,
            Field(min_length=3, max_length=120, description="Policy name, e.g. 'attendance' or 'academic integrity'."),
        ],
    ) -> PolicyDetails:
        """Get the full text of one handbook policy section, with page citations."""
        return await anyio.to_thread.run_sync(svc.policy, policy_name)

    @mcp.custom_route("/health", methods=["GET"])  # type: ignore[untyped-decorator]  # SDK decorator is untyped
    async def health(_: Request) -> JSONResponse:
        info = await anyio.to_thread.run_sync(svc.source_info)
        status = "ok" if info.documents else "degraded"
        return JSONResponse({"status": status, "server": SERVER_NAME, "source": info.model_dump(mode="json")})

    return mcp
