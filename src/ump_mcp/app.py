"""ASGI application wiring: transport, auth middleware, and adapters.

The server runs stateless Streamable HTTP at /mcp — suitable for deployment
behind the k8s Gateway next to UMP (sidecar model, see ARCHITECTURE.md).
"""

import contextlib
import logging
from collections.abc import AsyncIterator

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from ump_mcp import __version__
from ump_mcp.adapters.keycloak_jwt import KeycloakJwtValidationAdapter
from ump_mcp.adapters.ump_http import (
    UmpHttpExecutionAdapter,
    UmpHttpJobsAdapter,
    UmpHttpToolCatalogAdapter,
    build_ump_client,
)
from ump_mcp.auth import JwtAuthMiddleware
from ump_mcp.config import Settings
from ump_mcp.server import build_mcp_server

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> ASGIApp:
    settings = settings or Settings()
    logging.basicConfig(level=settings.log_level.upper())

    ump_client = build_ump_client(
        settings.ump_api_base_url, settings.ump_request_timeout
    )
    catalog = UmpHttpToolCatalogAdapter(ump_client, settings.ump_catalog_prefix)
    execution = UmpHttpExecutionAdapter(ump_client, settings.ump_ogc_prefix)
    jobs = UmpHttpJobsAdapter(ump_client, settings.ump_ogc_prefix)
    validator = KeycloakJwtValidationAdapter(
        jwks_url=settings.effective_jwks_url,
        issuer=settings.issuer,
        audience=settings.audience,
    )

    mcp_server = build_mcp_server(catalog=catalog, execution=execution, jobs=jobs)
    session_manager = StreamableHTTPSessionManager(
        app=mcp_server, stateless=True, json_response=True
    )

    async def handle_mcp(scope: Scope, receive: Receive, send: Send) -> None:
        await session_manager.handle_request(scope, receive, send)

    mcp_endpoint = JwtAuthMiddleware(
        handle_mcp, validator=validator, allow_anonymous=settings.allow_anonymous
    )

    async def health(_request):
        return JSONResponse({"status": "ok", "version": __version__})

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with session_manager.run():
            logger.info(
                "ump-x-mcp %s ready — UMP at %s (catalog %s, OGC %s), issuer %s",
                __version__,
                settings.ump_api_base_url,
                settings.ump_catalog_prefix,
                settings.ump_ogc_prefix,
                settings.issuer,
            )
            try:
                yield
            finally:
                await ump_client.aclose()

    starlette_app = Starlette(
        routes=[Route("/health", health, methods=["GET"])],
        lifespan=lifespan,
    )

    # Dispatch /mcp ourselves: Starlette's Mount would 307-redirect the bare
    # "/mcp" path to "/mcp/" before the auth middleware ever runs, and MCP
    # clients POST to "/mcp" exactly.
    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and (
            scope["path"] == "/mcp" or scope["path"].startswith("/mcp/")
        ):
            await mcp_endpoint(scope, receive, send)
        else:
            await starlette_app(scope, receive, send)

    return app
