"""ASGI application wiring: transport, auth middleware, and adapters.

The server runs stateless Streamable HTTP at /mcp — suitable for deployment
behind the k8s Gateway next to UMP (sidecar model, see ARCHITECTURE.md).
"""

import contextlib
import logging
from collections.abc import AsyncIterator

from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from mcp.server.auth.routes import create_protected_resource_routes
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

_BARE_METADATA_PATH = "/.well-known/oauth-protected-resource"


def _discovery_routes(settings: Settings) -> list[Route]:
    """OAuth 2.0 Protected Resource Metadata (RFC 9728), served unauthenticated.

    This is what lets an MCP client log the user in itself: it reads the
    document, finds Keycloak, and runs auth-code + PKCE with refresh — instead
    of a human pasting a five-minute access token into a config file.

    RFC 9728 §3.1 puts the document at the path-inserted URL
    (/.well-known/oauth-protected-resource/mcp). Clients in the wild also probe
    the bare /.well-known/oauth-protected-resource, so both are served.
    """
    if not settings.resource_url:
        logger.warning(
            "UMP_MCP_RESOURCE_URL is not set — OAuth discovery is disabled and "
            "clients cannot log in on their own. Bearer tokens still validate."
        )
        return []

    routes = create_protected_resource_routes(
        resource_url=AnyHttpUrl(settings.resource_url),
        authorization_servers=[AnyHttpUrl(settings.issuer)],
        scopes_supported=settings.scopes or None,
        resource_name="Urban Model Platform MCP server",
    )
    canonical = routes[0]
    if canonical.path != _BARE_METADATA_PATH:
        routes.append(
            Route(
                _BARE_METADATA_PATH,
                endpoint=canonical.endpoint,
                methods=["GET", "OPTIONS"],
            )
        )
    return routes


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
        handle_mcp,
        validator=validator,
        allow_anonymous=settings.allow_anonymous,
        resource_metadata_url=settings.resource_metadata_url,
        required_scopes=settings.scopes,
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
        routes=[Route("/health", health, methods=["GET"])] + _discovery_routes(settings),
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
