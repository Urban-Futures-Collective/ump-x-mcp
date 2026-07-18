"""Ports (hexagonal architecture) per mcp-integration-strategy.md §9.

The MCP layer only depends on these interfaces. The v1 adapters talk to UMP
over HTTP and to Keycloak via JWKS; a later UMP refactor can swap in direct
application-service adapters without changing the MCP tool contracts.
"""

from typing import Any, Protocol

from ump_mcp.domain.models import ExecutionResult, ToolDescriptor, UserContext


class IdentityValidationError(Exception):
    """Raised when a presented JWT is invalid (signature, iss, aud, exp, ...)."""


class UmpApiError(Exception):
    """Raised when UMP rejects or fails a request."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class IdentityValidationPort(Protocol):
    def validate(self, raw_token: str) -> UserContext:
        """Validates the JWT locally and returns the caller's context.

        Raises IdentityValidationError if the token is not acceptable.
        """
        ...


class ToolCatalogPort(Protocol):
    async def list_tools(self, user: UserContext) -> list[ToolDescriptor]:
        """Fetches the per-user, role-filtered tool catalog from UMP."""
        ...


class ToolExecutionPort(Protocol):
    async def execute(
        self, user: UserContext, process_id_with_prefix: str, inputs: dict[str, Any]
    ) -> ExecutionResult:
        """Submits a process execution to UMP with the caller's original JWT."""
        ...


class JobsPort(Protocol):
    async def list_jobs(self, user: UserContext) -> dict[str, Any]: ...

    async def get_job(self, user: UserContext, job_id: str) -> dict[str, Any]: ...

    async def get_job_results(self, user: UserContext, job_id: str) -> dict[str, Any]: ...
