from functools import cached_property
from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from UMP_MCP_* environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="UMP_MCP_", env_file=".env", extra="ignore"
    )

    # UMP API root the MCP server talks to — the server root, *without* a
    # version prefix (UMP's own UMP_API_SERVER_URL_PREFIX, default "/"), e.g.
    # "https://ump.example.org". The two prefixes below are appended to it.
    ump_api_base_url: str = "http://localhost:5000"

    # UMP publishes the tool catalog and the OGC API Processes surface under
    # *separate*, independently versioned prefixes (UMP 3.0, see its
    # adapters/web/mcp.py): the catalog contract versions on its own clock,
    # the OGC prefix tracks the standard. Both are configurable so a UMP
    # version bump is an environment change here, not a release.
    #
    # Catalog:   GET  {base}{catalog_prefix}/tools
    ump_catalog_prefix: str = "/mcp/v1"
    # Execution: POST {base}{ogc_prefix}/processes/{provider:process}/execution
    # Jobs:      GET  {base}{ogc_prefix}/jobs[/{job_id}[/results]]
    ump_ogc_prefix: str = "/v1.0"

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

    # Public URL of this server's MCP endpoint, e.g.
    # "https://mcp.example.org/mcp". This is the OAuth *resource identifier*
    # (RFC 9728): it is published in the protected-resource metadata and named
    # in the WWW-Authenticate challenge, so MCP clients can discover Keycloak
    # and run the auth-code flow themselves instead of being handed a token.
    #
    # It cannot be inferred — TLS is terminated by the ingress, so the app only
    # ever sees http://0.0.0.0:8000. Leaving it unset disables OAuth discovery;
    # bearer validation is unaffected.
    resource_url: str | None = None

    # Scopes a token must carry, space- or comma-separated. Published in the
    # metadata as scopes_supported and enforced on every request. Empty means
    # no scope requirement beyond a valid token.
    required_scopes: str = ""

    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"

    # Timeout (seconds) for calls against the UMP API.
    ump_request_timeout: float = Field(default=30.0, gt=0)

    @field_validator("ump_api_base_url", "ump_catalog_prefix", "ump_ogc_prefix")
    @classmethod
    def _normalize_path(cls, value: str) -> str:
        """Trim trailing slashes so prefixes concatenate predictably."""
        return value.rstrip("/")

    @cached_property
    def scopes(self) -> list[str]:
        return [s for s in self.required_scopes.replace(",", " ").split() if s]

    @cached_property
    def resource_metadata_url(self) -> str | None:
        """RFC 9728 §3.1 metadata URL for `resource_url` (path-inserted form)."""
        if not self.resource_url:
            return None
        parsed = urlparse(self.resource_url)
        path = parsed.path if parsed.path != "/" else ""
        return (
            f"{parsed.scheme}://{parsed.netloc}"
            f"/.well-known/oauth-protected-resource{path}"
        )

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
