# UMP-X MCP Server

MCP server for the [Urban Model Platform](https://github.com/Urban-Futures-Collective/urban-model-platform) (UMP): the Agent Experience (AX) layer that exposes UMP processes as [MCP](https://modelcontextprotocol.io) tools so LLMs and agents can discover and run urban simulation models on a user's behalf.

It is a thin translation layer, deployed as an independent sidecar service next to UMP (see UMP's [`ARCHITECTURE.md`](https://github.com/Urban-Futures-Collective/urban-model-platform/blob/feat/mcp/ARCHITECTURE.md) and [`mcp-integration-strategy.md`](https://github.com/Urban-Futures-Collective/urban-model-platform/blob/feat/mcp/mcp-integration-strategy.md)):

- **Dynamic tools, no hard-coded processes.** On every `tools/list`, the server calls UMP's per-user discovery endpoint `GET /mcp/tools` with the caller's JWT and translates each returned process into an MCP tool. New providers/processes in UMP appear as tools automatically; different users see different tool lists.
- **Zero trust.** The server validates every request's Keycloak JWT itself (signature via JWKS, issuer, expiry, and — when configured — audience), then forwards the *original, unmodified* JWT to UMP, which remains the final authorization authority. No synthetic identities, no direct database access.
- **Execution as tools.** Calling a process tool validates the arguments against the process input schema and submits `POST /processes/{provider:process}/execution`. Jobs run asynchronously; built-in tools `ump_list_jobs`, `ump_get_job_status`, and `ump_get_job_results` cover the job lifecycle.

## How a request flows

```
Agent/LLM client ──(MCP over Streamable HTTP + Bearer JWT)──▶ this server
    1. validate JWT against Keycloak JWKS (zero trust)
    2. GET  {UMP}/mcp/v1/tools                  (same JWT)  → per-user tool list
    3. POST {UMP}/v1.0/processes/{id}/execution (same JWT)  → jobID
    4. GET  {UMP}/v1.0/jobs/{jobID}[/results]   (same JWT)  → status / results
```

## Running

```bash
pip install .            # or: pip install -e ".[dev]" for development
ump-x-mcp                # serves Streamable HTTP MCP at http://0.0.0.0:8000/mcp
```

Or with Docker:

```bash
docker build -t ump-x-mcp .
docker run --rm -p 8000:8000 --env-file .env ump-x-mcp
```

`GET /health` is an unauthenticated liveness endpoint; everything under `/mcp` requires a valid Bearer JWT (unless `UMP_MCP_ALLOW_ANONYMOUS=true`).

For the server: [`DEPLOY.md`](DEPLOY.md) describes the Dokploy setup — pushing to the `deploy` branch rebuilds and redeploys.

## Configuration

All settings come from `UMP_MCP_*` environment variables (or a `.env` file — see [`.env.example`](.env.example)):

| Variable | Default | Purpose |
|---|---|---|
| `UMP_MCP_UMP_API_BASE_URL` | `http://localhost:5000` | UMP server root, without version prefix. |
| `UMP_MCP_UMP_CATALOG_PREFIX` | `/mcp/v1` | Prefix of UMP's tool-catalog contract (`{base}{prefix}/tools`). |
| `UMP_MCP_UMP_OGC_PREFIX` | `/v1.0` | Prefix of UMP's OGC API Processes surface (executions, jobs). |
| `UMP_MCP_KEYCLOAK_URL` | `http://localhost:8080` | Keycloak base URL as reachable from this service. |
| `UMP_MCP_KEYCLOAK_REALM` | `UMP` | Keycloak realm. |
| `UMP_MCP_KEYCLOAK_ISSUER` | derived | Expected `iss` claim; set when tokens carry a public URL but Keycloak is reached internally. |
| `UMP_MCP_JWKS_URL` | derived | JWKS endpoint override. |
| `UMP_MCP_AUDIENCE` | *(unset)* | Expected `aud` claim. **Unset disables the audience check** — configure a Keycloak audience mapper and set this in production. |
| `UMP_MCP_ALLOW_ANONYMOUS` | `false` | Accept requests without a JWT; UMP then only shows anonymous-access processes. |
| `UMP_MCP_HOST` / `UMP_MCP_PORT` | `0.0.0.0` / `8000` | Bind address. |
| `UMP_MCP_LOG_LEVEL` | `INFO` | Log level. |
| `UMP_MCP_UMP_REQUEST_TIMEOUT` | `30` | Timeout (s) for UMP API calls. |

## Connecting a client

Any MCP client that supports Streamable HTTP with a Bearer token works. Example (Claude Code):

```bash
claude mcp add --transport http ump http://localhost:8000/mcp \
  --header "Authorization: Bearer <keycloak-access-token>"
```

The token is a normal Keycloak user access token — the same one the UMP frontend uses.

## Architecture (code layout)

Structured as ports & adapters from the start (strategy §9), so the HTTP adapters can later be swapped for direct application-service adapters when UMP refactors — without changing the MCP tool contracts:

```
src/ump_mcp/
├── server.py            # MCP core: dynamic list_tools / call_tool against the ports
├── app.py               # ASGI wiring: Streamable HTTP transport + auth middleware
├── auth.py              # JWT middleware (zero trust) + per-request user context
├── config.py            # UMP_MCP_* settings
├── domain/models.py     # ToolDescriptor, UserContext, ExecutionResult
├── ports/               # ToolCatalogPort, ToolExecutionPort, JobsPort, IdentityValidationPort
└── adapters/
    ├── keycloak_jwt.py  # KeycloakJwtValidationAdapter (JWKS with cache)
    └── ump_http.py      # UmpHttpToolCatalogAdapter, UmpHttpExecutionAdapter, UmpHttpJobsAdapter
```

Tool names are sanitized for MCP clients (`bikebox:plan_network` → `bikebox_plan_network`); the original UMP process ID is kept internally for execution calls.

## Development

```bash
pip install -e ".[dev]"
pytest
```

The test suite covers the strategy's mandatory cases (§11): negative token tests (expired, wrong issuer, wrong audience, manipulated signature), JWT forwarding, per-user tool-list dynamics, input-schema validation, and authorization errors surfacing from UMP.
