"""OAuth resource-server behaviour (RFC 9728 + RFC 6750).

These are what let an MCP client log a user in *once* and stay connected: the
client discovers Keycloak from the challenge and the metadata document, then
runs auth-code + PKCE with refresh on its own. Without them the only way in is
pasting a short-lived token by hand.
"""

import pytest
from starlette.testclient import TestClient

from tests.conftest import AUDIENCE, ISSUER, make_token
from ump_mcp.app import create_app
from ump_mcp.config import Settings

RESOURCE = "https://mcp.example.org/mcp"
METADATA_PATH = "/.well-known/oauth-protected-resource/mcp"
BARE_METADATA_PATH = "/.well-known/oauth-protected-resource"

MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
    "MCP-Protocol-Version": "2025-06-18",
}


def _settings(**overrides) -> Settings:
    base = dict(
        ump_api_base_url="http://ump.test",
        keycloak_url="https://auth.example.com",
        keycloak_realm="UMP",
        keycloak_issuer=ISSUER,
        audience=AUDIENCE,
        allow_anonymous=False,
        resource_url=RESOURCE,
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def client(jwks_server):
    with TestClient(create_app(_settings())) as c:
        yield c


@pytest.mark.parametrize("path", [METADATA_PATH, BARE_METADATA_PATH])
def test_metadata_served_unauthenticated_at_both_paths(client, path):
    """RFC 9728 §3.1 mandates the path-inserted URL; clients in the wild also
    probe the bare one. Both must answer, and without a token — a client that
    needed a token to discover how to get a token could never start."""
    response = client.get(path)

    assert response.status_code == 200
    body = response.json()
    assert body["resource"] == RESOURCE
    assert ISSUER in body["authorization_servers"]


def test_metadata_absent_when_resource_url_unset(jwks_server):
    """Discovery is opt-in: without a public URL the document would advertise a
    resource identifier that does not resolve."""
    with TestClient(create_app(_settings(resource_url=None))) as c:
        assert c.get(METADATA_PATH).status_code == 404


def test_401_challenge_points_at_metadata(client):
    """The one header that makes a client able to log the user in by itself."""
    response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers=MCP_HEADERS)

    assert response.status_code == 401
    challenge = response.headers["WWW-Authenticate"]
    assert challenge.startswith("Bearer ")
    assert f'resource_metadata="https://mcp.example.org{METADATA_PATH}"' in challenge


def test_invalid_token_challenge_is_invalid_token(client, rsa_keypair):
    expired = make_token(rsa_keypair, expires_in=-60)

    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers={**MCP_HEADERS, "Authorization": f"Bearer {expired}"},
    )

    assert response.status_code == 401
    assert 'error="invalid_token"' in response.headers["WWW-Authenticate"]


def test_missing_required_scope_is_403_insufficient_scope(jwks_server, rsa_keypair):
    token = make_token(rsa_keypair, extra_claims={"scope": "openid profile"})

    with TestClient(create_app(_settings(required_scopes="openid ump:use"))) as c:
        response = c.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={**MCP_HEADERS, "Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 403
    assert response.json()["error"] == "insufficient_scope"
    challenge = response.headers["WWW-Authenticate"]
    assert 'error="insufficient_scope"' in challenge
    assert 'scope="openid ump:use"' in challenge


def test_required_scopes_published_in_metadata(jwks_server):
    with TestClient(create_app(_settings(required_scopes="openid, ump:use"))) as c:
        body = c.get(METADATA_PATH).json()

    assert body["scopes_supported"] == ["openid", "ump:use"]
