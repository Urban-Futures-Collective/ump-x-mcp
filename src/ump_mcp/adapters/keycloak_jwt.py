import logging

import jwt
from jwt import PyJWKClient

from ump_mcp.domain.models import UserContext
from ump_mcp.ports import IdentityValidationError

logger = logging.getLogger(__name__)

_ALLOWED_ALGORITHMS = ["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"]


class KeycloakJwtValidationAdapter:
    """Validates Keycloak-issued JWTs locally against the realm's JWKS.

    Zero-trust: the MCP server never assumes an upstream hop already checked
    the token. Signature, issuer, and expiry are always verified; the audience
    check is enabled iff an expected audience is configured.
    """

    def __init__(
        self,
        jwks_url: str,
        issuer: str,
        audience: str | None = None,
        jwks_cache_lifespan: int = 300,
    ):
        self._issuer = issuer
        self._audience = audience
        self._jwk_client = PyJWKClient(
            jwks_url, cache_keys=True, lifespan=jwks_cache_lifespan
        )
        if audience is None:
            logger.warning(
                "No expected audience configured (UMP_MCP_AUDIENCE) — the JWT "
                "'aud' claim will not be checked. Configure a Keycloak audience "
                "mapper and set UMP_MCP_AUDIENCE in production."
            )

    def validate(self, raw_token: str) -> UserContext:
        try:
            signing_key = self._jwk_client.get_signing_key_from_jwt(raw_token)
            claims = jwt.decode(
                raw_token,
                signing_key.key,
                algorithms=_ALLOWED_ALGORITHMS,
                issuer=self._issuer,
                audience=self._audience,
                options={
                    "require": ["exp", "iss"],
                    "verify_aud": self._audience is not None,
                },
            )
        except jwt.PyJWTError as exc:
            raise IdentityValidationError(f"Invalid token: {exc}") from exc
        except Exception as exc:  # JWKS fetch/parse failures
            raise IdentityValidationError(f"Token validation failed: {exc}") from exc

        return UserContext(raw_token=raw_token, claims=claims)
