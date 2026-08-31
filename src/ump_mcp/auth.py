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
        resource_metadata_url: str | None = None,
        required_scopes: list[str] | None = None,
    ):
        self._app = app
        self._validator = validator
        self._allow_anonymous = allow_anonymous
        self._resource_metadata_url = resource_metadata_url
        self._required_scopes = required_scopes or []

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
                await self._unauthorized(send, str(exc), error="invalid_token")
                return
            missing = self._missing_scopes(user)
            if missing:
                logger.info("Rejected request: missing scope(s) %s", ", ".join(missing))
                await self._forbidden(send, missing)
                return
        elif self._allow_anonymous:
            user = ANONYMOUS
        else:
            await self._unauthorized(send, "Missing Bearer token")
            return

        reset = _current_user.set(user)
        try:
            await self._app(scope, receive, send)
        finally:
            _current_user.reset(reset)

    def _missing_scopes(self, user: UserContext) -> list[str]:
        """Scopes required but absent from the token's space-delimited `scope`."""
        if not self._required_scopes:
            return []
        granted = set(str(user.claims.get("scope", "")).split())
        return [s for s in self._required_scopes if s not in granted]

    def _challenge(self, **params: str) -> str:
        """RFC 6750 challenge; `resource_metadata` points clients at RFC 9728
        discovery so they can run the auth-code flow instead of being handed a
        token out of band."""
        if self._resource_metadata_url:
            params["resource_metadata"] = self._resource_metadata_url
        if not params:
            return "Bearer"
        rendered = ", ".join(f'{k}="{v}"' for k, v in params.items())
        return f"Bearer {rendered}"

    async def _unauthorized(
        self, send: Send, detail: str, error: str = "invalid_request"
    ) -> None:
        await _send_json(
            send,
            401,
            {"error": "unauthorized", "detail": detail},
            self._challenge(error=error, error_description=detail),
        )

    async def _forbidden(self, send: Send, missing: list[str]) -> None:
        detail = f"Token is missing required scope(s): {' '.join(missing)}"
        await _send_json(
            send,
            403,
            {"error": "insufficient_scope", "detail": detail},
            self._challenge(
                error="insufficient_scope",
                error_description=detail,
                scope=" ".join(self._required_scopes),
            ),
        )


async def _send_json(send: Send, status: int, body: dict, challenge: str) -> None:
    payload = json.dumps(body).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"www-authenticate", challenge.encode()),
                (b"content-length", str(len(payload)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": payload})
