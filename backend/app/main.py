"""FastAPI application factory."""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import __version__
from .api.errors import install_error_handlers
from .api.routes import router
from .config import Settings, get_settings
from .logging_setup import configure_logging
from .state import AppState, build_state

log = logging.getLogger("campusos")


def create_app(settings: Settings | None = None, state: AppState | None = None) -> FastAPI:
    cfg = settings or (state.settings if state else get_settings())
    configure_logging(cfg.log_level, cfg.log_json)
    app_state = state or build_state(cfg)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await app_state.mcp.refresh()  # initial discovery; failures are recorded, not raised
        log.info(
            "CampusOS backend started: llm=%s model=%s tools=%d",
            app_state.llm.name, app_state.llm.model, len(app_state.mcp.tools),
        )  # fmt: skip
        yield

    app = FastAPI(
        title="CampusOS AI API",
        version=__version__,
        description="Campus assistant backend: MCP tool discovery, agent orchestration, RAG citations and traces.",
        lifespan=lifespan,
    )
    app.state.campus = app_state
    install_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origin_list,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        request_id = request.headers.get("x-request-id", "")[:64] or uuid.uuid4().hex[:16]
        request.state.request_id = request_id
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > cfg.max_request_bytes:
            return JSONResponse(
                {
                    "error": {
                        "code": "payload_too_large",
                        "message": "Request body too large.",
                        "request_id": request_id,
                    }
                },
                status_code=413,
                headers={"X-Request-ID": request_id},
            )
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    app.include_router(router)
    return app


def app_factory() -> FastAPI:  # used by: uvicorn app.main:app_factory --factory
    return create_app()
