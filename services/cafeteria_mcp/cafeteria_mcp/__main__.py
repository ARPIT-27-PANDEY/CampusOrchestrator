"""Entry point: ``python -m cafeteria_mcp`` starts the Streamable HTTP server."""

from __future__ import annotations

import os

import uvicorn
from mcp.server.transport_security import TransportSecuritySettings

from .server import build_server


def transport_security_from_env() -> TransportSecuritySettings:
    """DNS-rebinding protection with an explicit Host allowlist.

    ``MCP_ALLOWED_HOSTS`` is a comma-separated list such as
    ``localhost:*,127.0.0.1:*,library-mcp:*`` (Docker service names must be listed).
    """
    hosts = [h.strip() for h in os.getenv("MCP_ALLOWED_HOSTS", "localhost:*,127.0.0.1:*").split(",") if h.strip()]
    return TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=hosts, allowed_origins=[])


def main() -> None:
    host = os.getenv("MCP_HOST", "127.0.0.1")
    port = int(os.getenv("MCP_PORT", "8103"))
    app = build_server().streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=transport_security_from_env(),
        host=host,
    )
    uvicorn.run(app, host=host, port=port, log_level=os.getenv("LOG_LEVEL", "info").lower())


if __name__ == "__main__":
    main()
