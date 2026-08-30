# Deployment (Dokploy)

The `deploy` branch is the release pointer: **every push to it triggers a rebuild
and redeploy** of the MCP server on the Dokploy host. `main` is where work lands;
`deploy` is what runs.

## One-time setup in Dokploy

1. **Create → Compose** in the target project.
2. **Provider**: GitHub (or Git) → repository `Urban-Futures-Collective/ump-x-mcp`,
   **branch `deploy`**, compose path `./docker-compose.yml`.
3. **Environment**: paste the variables below. Dokploy stores them on the server and
   writes them to `.env` beside the compose file — they are never committed.
4. **Enable Auto Deploy**. Dokploy shows a webhook URL; add it to the repo under
   *Settings → Webhooks* (content type `application/json`, event: `push`) if the
   GitHub integration did not add it automatically.
5. **Deploy**.

The compose file attaches the service to the external `dokploy-network` and carries
its own Traefik labels, so the domain comes from `UMP_MCP_DOMAIN` rather than the
Dokploy domain UI. Point that DNS record at the server before the first deploy so
Let's Encrypt can issue the certificate.

## Environment

Required:

```dotenv
UMP_MCP_DOMAIN=mcp.example.org
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

## Shipping a release

```bash
git push origin main:deploy      # promote current main
```

Dokploy picks up the push, rebuilds the image and restarts the service. To ship an
older or specific commit:

```bash
git push origin <sha>:deploy
```

Roll back the same way — push the previous good SHA. `deploy` is only ever
fast-forwarded from `main`; nothing is committed on it directly, so the two branches
never diverge.

## Verifying

```bash
curl https://$UMP_MCP_DOMAIN/health                       # unauthenticated, expects 200
curl -H "Authorization: Bearer $TOKEN" \
     -H "Accept: application/json, text/event-stream" \
     -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
     https://$UMP_MCP_DOMAIN/mcp
```

The transport is stateless (`json_response=True`), so no session affinity is needed
and the service can be scaled to several replicas behind Traefik.
