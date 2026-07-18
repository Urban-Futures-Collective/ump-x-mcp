"""Request authentication for the Streamable HTTP transport.

A plain ASGI middleware validates the Bearer JWT on every request (zero
trust) and exposes the resulting UserContext to the MCP tool handlers via a
contextvar. The raw token is kept so it can be forwarded to UMP unchanged.
"""

import json
import logging
from contextvars import ContextVar

from starlette.types import ASGIApp, Receive, Scope, Send

from ump_mcp.domain.models import ANONYMOUS, UserContext
from ump_mcp.ports import IdentityValidationError, IdentityValidationPort

logger = logging.getLogger(__name__)

_current_user: ContextVar[UserContext] = ContextVar("ump_mcp_current_user")


def current_user() -> UserContext:
    """The authenticated caller of the request currently being handled."""
    return _current_user.get()


class JwtAuthMiddleware:
    """Rejects requests without a valid Keycloak JWT (401) before they reach MCP.

    With ``allow_anonymous`` enabled, requests without an Authorization header
    proceed as anonymous — UMP then filters the catalog to anonymous-access
    processes. A *present but invalid* token is always rejected.
    """

    def __init__(
        self,
        app: ASGIApp,
        validator: IdentityValidationPort,
        allow_anonymous: bool = False,
    ):
        self._app = app
        self._validator = validator
        self._allow_anonymous = allow_anonymous

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        authorization = headers.get("authorization", "")

        if authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
            try:
                user = self._validator.validate(token)
            except IdentityValidationError as exc:
                logger.info("Rejected request: %s", exc)
                await _unauthorized(send, str(exc))
                return
        elif self._allow_anonymous:
            user = ANONYMOUS
        else:
            await _unauthorized(send, "Missing Bearer token")
            return

        reset = _current_user.set(user)
        try:
            await self._app(scope, receive, send)
        finally:
            _current_user.reset(reset)


async def _unauthorized(send: Send, detail: str) -> None:
    body = json.dumps({"error": "unauthorized", "detail": detail}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"www-authenticate", b"Bearer"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
