# Deployment (Dokploy)

The `deploy` branch is the release pointer: **every push to it triggers a rebuild
and redeploy** of the MCP server on the Dokploy host. `main` is where work lands;
`deploy` is what runs.

Dokploy builds the repository's [`Dockerfile`](Dockerfile) as an *Application*.
Domain, TLS and routing come from the Dokploy UI; configuration comes from the
Environment tab and stays on the server. Nothing secret is committed.

## One-time setup in Dokploy

1. **Create → Application** in the target project.
2. **Provider**: GitHub (or Git) → repository `Urban-Futures-Collective/ump-x-mcp`,
   **branch `deploy`**.
3. **Build Type**: `Dockerfile`, path `./Dockerfile`.
4. **Environment**: paste the variables below. Dokploy injects them into the
   container and keeps them on the server.
5. **Domains**: add the public hostname, **container port `8000`**, HTTPS on with
   the Let's Encrypt certificate resolver. Point the DNS record at the server first
   so the certificate can be issued.
6. **Enable Auto Deploy**. Dokploy shows a webhook URL; add it to the repo under
   *Settings → Webhooks* (content type `application/json`, event: `push`) if the
   GitHub integration did not add it automatically.
7. **Deploy**.

The transport is stateless (`json_response=True`), so no session affinity is needed
— the replica count in the Advanced tab can be raised without further changes.

## Environment

Required:

```dotenv
UMP_MCP_UMP_API_BASE_URL=https://ump.example.org/api
UMP_MCP_KEYCLOAK_URL=https://auth.example.org
UMP_MCP_KEYCLOAK_REALM=UMP
UMP_MCP_AUDIENCE=ump-client
UMP_MCP_ALLOW_ANONYMOUS=false
```

Set `UMP_MCP_KEYCLOAK_ISSUER` / `UMP_MCP_JWKS_URL` as well when tokens are issued
under a public URL but Keycloak is reached internally under another one. See
`.env.example` for the full list and defaults.

`UMP_MCP_AUDIENCE` unset disables the audience check — set it in production, with a
matching Keycloak audience mapper. Leave `UMP_MCP_ALLOW_ANONYMOUS=false` so the
zero-trust invariant holds: no valid JWT, no tools.

Leave `UMP_MCP_HOST`/`UMP_MCP_PORT` at their defaults (`0.0.0.0:8000`) — the
Dockerfile's `EXPOSE` and healthcheck and the domain's container port assume `8000`.

## Shipping a release

```bash
git push origin main:deploy      # promote current main
```

Dokploy picks up the push, rebuilds the image and restarts the service. To ship an
older or specific commit:

```bash
git push origin <sha>:deploy
```

Roll back that way, or from Dokploy's deployment history. `deploy` is only ever
fast-forwarded from `main`; nothing is committed on it directly, so the two branches
never diverge.

## Verifying

```bash
curl https://mcp.example.org/health                       # unauthenticated, expects 200
curl -H "Authorization: Bearer $TOKEN" \
     -H "Accept: application/json, text/event-stream" \
     -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
     https://mcp.example.org/mcp
```
