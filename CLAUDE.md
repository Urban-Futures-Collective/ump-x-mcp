# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

The MCP server for the Urban Model Platform (UMP-X): a thin, independently deployed sidecar that translates UMP processes into MCP tools over Streamable HTTP. The authoritative design docs live in the `urban-model-platform` repo (branch `feat/mcp`): `mcp-integration-strategy.md` and `ARCHITECTURE.md`. A local checkout usually exists at `../urban-model-platform`.

## Commands

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"   # setup
.venv/bin/pytest                                             # all tests
.venv/bin/pytest tests/test_server_e2e.py -k tools_list      # single test
.venv/bin/ruff check src tests                               # lint
.venv/bin/python -m ump_mcp                                  # run server (or: ump-x-mcp)
```

Configuration is env-based (`UMP_MCP_*`, see `.env.example`); the server listens on `:8000` with MCP at `/mcp` and an unauthenticated `/health`.

## Architecture

Three invariants drive everything; don't break them:

1. **Zero trust.** Every request's Keycloak JWT is validated locally (JWKS, `iss`, `exp`, optional `aud`) in `auth.py`'s ASGI middleware *before* it reaches the MCP transport. The validated `UserContext` (including the raw token) travels via a contextvar (`ump_mcp.auth.current_user()`).
2. **UMP is the source of truth.** There are no hard-coded process tools. `tools/list` fetches `GET {UMP}{catalog_prefix}/tools` with the caller's JWT (per-user filtered by UMP); `tools/call` re-fetches the catalog to resolve the tool, validates arguments against its `inputSchema`, then `POST {UMP}{ogc_prefix}/processes/{provider:process}/execution`. Never duplicate UMP's role logic here.

   UMP 3.0 versions those two surfaces on separate clocks — the catalog contract at `/mcp/v1` (body field `version` reports the exact revision; `SUPPORTED_CATALOG_MAJOR` in the adapter is what we implement), the OGC surface at `/v1.0`. Both prefixes are settings (`ump_catalog_prefix`, `ump_ogc_prefix`) so a UMP bump is an env change, not a release. `ump_api_base_url` is the bare server root.
3. **The original JWT is forwarded unchanged.** No synthetic identities, no direct DB access. `_auth_headers()` in `adapters/ump_http.py` is the only place the token goes onto outbound requests.

Ports & adapters (strategy doc §9): `ports/` holds the Protocols (`ToolCatalogPort`, `ToolExecutionPort`, `JobsPort`, `IdentityValidationPort`); `adapters/` holds the v1 HTTP implementations. `server.py` (MCP core) depends only on the ports — a future UMP refactor swaps adapters without touching tool contracts.

Non-obvious details:

- **Tool naming:** UMP identifies processes as `provider:process_id`, but MCP clients require `[a-zA-Z0-9_-]` tool names. `domain/models.py:sanitize_tool_name` maps `bikebox:plan_network` → `bikebox_plan_network`; the original ID is kept on the `ToolDescriptor` for execution URLs. Collisions after sanitization are skipped with a warning in the catalog adapter.
- **Input validation is ours, not the SDK's.** `server.py` registers `call_tool(validate_input=False)` because the SDK's schema cache is global while our tool schemas are per-user; we validate with `jsonschema` against the freshly fetched catalog instead. Note the SDK may still call our `list_tools` handler during `tools/call` to refresh its own cache.
- **Transport is stateless** (`StreamableHTTPSessionManager(stateless=True, json_response=True)`) so the service scales horizontally behind the k8s gateway without session affinity.
- **Executions are async jobs:** a process tool call returns `{jobID, status}`; the built-in tools `ump_list_jobs` / `ump_get_job_status` / `ump_get_job_results` cover the rest of the lifecycle.

## Tests

`tests/conftest.py` generates an RSA keypair and monkeypatches `PyJWKClient.fetch_data`, so JWTs are really signed/verified without network. UMP HTTP is mocked with `respx`. `test_server_e2e.py` drives the full ASGI app (auth middleware + real MCP transport) via Starlette's `TestClient` with raw JSON-RPC bodies. The strategy doc's §11 test matrix (negative token tests, per-user dynamics, parity of forwarded JWTs) is the checklist new tests should extend.
