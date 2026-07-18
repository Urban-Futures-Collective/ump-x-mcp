from functools import cached_property

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from UMP_MCP_* environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="UMP_MCP_", env_file=".env", extra="ignore"
    )

    # UMP API root the MCP server talks to, including the API prefix,
    # e.g. "http://localhost:5000/api". Discovery is GET {base}/mcp/tools,
    # execution is POST {base}/processes/{provider:process}/execution.
    ump_api_base_url: str = "http://localhost:5000/api"

    # Keycloak base URL as reachable from this service (may be an internal
    # cluster URL), e.g. "http://keycloak:8080" or "https://auth.example.com".
    keycloak_url: str = "http://localhost:8080"
    keycloak_realm: str = "UMP"

    # Expected `iss` claim. Defaults to {keycloak_url}/realms/{realm}; override
    # when tokens are issued under a public URL but Keycloak is reached
    # internally under a different one.
    keycloak_issuer: str | None = None
    # JWKS endpoint override; defaults to {issuer_internal}/protocol/openid-connect/certs.
    jwks_url: str | None = None

    # Expected `aud` claim. When None the audience check is disabled — only do
    # this deliberately (Keycloak does not include a client audience by default;
    # configure an audience mapper and set this in production).
    audience: str | None = None

    # Accept requests without a JWT. UMP then filters the catalog down to
    # anonymous-access processes. Default: require a valid token (zero trust).
    allow_anonymous: bool = False

    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"

    # Timeout (seconds) for calls against the UMP API.
    ump_request_timeout: float = Field(default=30.0, gt=0)

    @cached_property
    def issuer(self) -> str:
        if self.keycloak_issuer:
            return self.keycloak_issuer
        return f"{self.keycloak_url.rstrip('/')}/realms/{self.keycloak_realm}"

    @cached_property
    def effective_jwks_url(self) -> str:
        if self.jwks_url:
            return self.jwks_url
        internal_issuer = f"{self.keycloak_url.rstrip('/')}/realms/{self.keycloak_realm}"
        return f"{internal_issuer}/protocol/openid-connect/certs"
