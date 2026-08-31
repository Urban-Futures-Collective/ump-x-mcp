"""HTTP adapters against the UMP REST API (v1 of the strategy's adapter layer).

Every request forwards the caller's original JWT unchanged — the MCP server
never mints its own identities and never talks to UMP's database. UMP remains
the final authorization authority.
"""

import logging
from typing import Any

import httpx

from ump_mcp.domain.models import ExecutionResult, ToolDescriptor, UserContext
from ump_mcp.ports import UmpApiError

logger = logging.getLogger(__name__)

#: Major of UMP's tool-catalog contract this adapter implements. UMP reports the
#: exact revision in the body's ``version`` field; the path prefix carries only
#: the major. A mismatch means the field contract may have changed underneath us.
SUPPORTED_CATALOG_MAJOR = "1"


def _auth_headers(user: UserContext) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if user.raw_token is not None:
        headers["Authorization"] = f"Bearer {user.raw_token}"
    return headers


def _raise_for_ump_error(response: httpx.Response, what: str) -> None:
    if response.is_success:
        return
    detail = ""
    try:
        body = response.json()
        detail = body.get("detail") or body.get("message") or body.get("title") or ""
    except Exception:
        detail = response.text[:500]
    raise UmpApiError(
        f"UMP {what} failed with HTTP {response.status_code}: {detail}",
        status_code=response.status_code,
    )


class UmpHttpToolCatalogAdapter:
    """ToolCatalogPort: GET {base}{prefix}/tools, filtered by UMP per user token."""

    def __init__(self, client: httpx.AsyncClient, prefix: str = "/mcp/v1"):
        self._client = client
        self._prefix = prefix.rstrip("/")
        self._version_warned = False

    def _check_contract(self, version: str) -> None:
        """Warn once when UMP publishes a catalog major we were not written for."""
        if self._version_warned or not version:
            return
        if version.split(".", 1)[0] != SUPPORTED_CATALOG_MAJOR:
            self._version_warned = True
            logger.warning(
                "UMP tool-catalog contract is v%s but this server implements v%s.x "
                "(catalog prefix %r). Tool fields may not map correctly — point "
                "UMP_MCP_UMP_CATALOG_PREFIX at the matching version.",
                version,
                SUPPORTED_CATALOG_MAJOR,
                self._prefix,
            )

    async def list_tools(self, user: UserContext) -> list[ToolDescriptor]:
        response = await self._client.get(
            f"{self._prefix}/tools", headers=_auth_headers(user)
        )
        _raise_for_ump_error(response, "tool discovery")
        payload = response.json()
        self._check_contract(str(payload.get("version", "")))
        entries = payload.get("tools", [])

        descriptors: list[ToolDescriptor] = []
        seen_names: set[str] = set()
        for entry in entries:
            try:
                descriptor = ToolDescriptor.from_ump(entry)
            except (KeyError, TypeError) as exc:
                logger.error("Skipping malformed tool entry %r: %s", entry, exc)
                continue
            if descriptor.name in seen_names:
                logger.warning(
                    "Tool name collision after sanitization: %r shadows an earlier "
                    "tool; skipping. Rename the provider/process in UMP to resolve.",
                    descriptor.tool,
                )
                continue
            seen_names.add(descriptor.name)
            descriptors.append(descriptor)
        return descriptors


class UmpHttpExecutionAdapter:
    """ToolExecutionPort: POST {base}{prefix}/processes/{provider:process}/execution."""

    def __init__(self, client: httpx.AsyncClient, prefix: str = "/v1.0"):
        self._client = client
        self._prefix = prefix.rstrip("/")

    async def execute(
        self, user: UserContext, process_id_with_prefix: str, inputs: dict[str, Any]
    ) -> ExecutionResult:
        response = await self._client.post(
            f"{self._prefix}/processes/{process_id_with_prefix}/execution",
            json={"inputs": inputs},
            headers=_auth_headers(user),
        )
        _raise_for_ump_error(response, f"execution of '{process_id_with_prefix}'")
        body = response.json()
        return ExecutionResult(
            job_id=str(body.get("jobID", "")),
            status=str(body.get("status", "")),
            raw=body,
        )


class UmpHttpJobsAdapter:
    """JobsPort: read-only job endpoints (status, results, listing)."""

    def __init__(self, client: httpx.AsyncClient, prefix: str = "/v1.0"):
        self._client = client
        self._prefix = prefix.rstrip("/")

    async def list_jobs(self, user: UserContext) -> dict[str, Any]:
        response = await self._client.get(f"{self._prefix}/jobs/", headers=_auth_headers(user))
        _raise_for_ump_error(response, "job listing")
        return response.json()

    async def get_job(self, user: UserContext, job_id: str) -> dict[str, Any]:
        response = await self._client.get(
            f"{self._prefix}/jobs/{job_id}", headers=_auth_headers(user)
        )
        _raise_for_ump_error(response, f"status of job '{job_id}'")
        return response.json()

    async def get_job_results(self, user: UserContext, job_id: str) -> dict[str, Any]:
        response = await self._client.get(
            f"{self._prefix}/jobs/{job_id}/results", headers=_auth_headers(user)
        )
        _raise_for_ump_error(response, f"results of job '{job_id}'")
        return response.json()


def build_ump_client(base_url: str, timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        timeout=timeout,
        headers={"Content-Type": "application/json"},
    )
