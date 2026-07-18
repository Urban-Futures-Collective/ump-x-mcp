"""End-to-end tests through the ASGI app: JWT enforcement at the transport,
per-user dynamic tool lists, schema validation, and execution forwarding."""

import json

import pytest
import respx
from starlette.testclient import TestClient

from tests.conftest import AUDIENCE, ISSUER, make_token
from ump_mcp.app import create_app
from ump_mcp.config import Settings

BASE = "http://ump.test/api"

MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
    "MCP-Protocol-Version": "2025-06-18",
}

CATALOG_USER_A = {
    "tools": [
        {
            "tool": "bikebox:plan_network",
            "title": "Plan bike box network",
            "description": "Plans a network of bike boxes.",
            "inputSchema": {
                "type": "object",
                "properties": {"num_boxes": {"type": "integer"}},
                "required": ["num_boxes"],
            },
            "provider": "bikebox",
            "processId": "plan_network",
        }
    ]
}
CATALOG_EMPTY = {"tools": []}


def rpc(method: str, params: dict | None = None, id_: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}}


@pytest.fixture
def settings():
    return Settings(
        ump_api_base_url=BASE,
        keycloak_url="https://auth.example.com",
        keycloak_realm="UMP",
        keycloak_issuer=ISSUER,
        audience=AUDIENCE,
        allow_anonymous=False,
    )


@pytest.fixture
def app_client(settings, jwks_server):
    app = create_app(settings)
    with TestClient(app) as client:
        yield client


def post_mcp(client, body: dict, token: str | None = None):
    headers = dict(MCP_HEADERS)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return client.post("/mcp", json=body, headers=headers)


def rpc_result(response):
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "error" not in payload, payload
    return payload["result"]


def test_health_is_public(app_client):
    response = app_client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_request_without_token_is_401(app_client):
    response = app_client.post("/mcp", json=rpc("tools/list"), headers=MCP_HEADERS)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_request_with_invalid_token_is_401(app_client):
    response = post_mcp(app_client, rpc("tools/list"), token="garbage.token.here")
    assert response.status_code == 401


@respx.mock
def test_tools_list_is_per_user(app_client, rsa_keypair):
    def catalog_by_token(request):
        import httpx

        auth = request.headers.get("Authorization", "")
        payload = CATALOG_USER_A if "user-a" in _sub_of(auth) else CATALOG_EMPTY
        return httpx.Response(200, json=payload)

    respx.get(f"{BASE}/mcp/tools").mock(side_effect=catalog_by_token)

    token_a = make_token(rsa_keypair, subject="user-a")
    token_b = make_token(rsa_keypair, subject="user-b")

    result_a = rpc_result(post_mcp(app_client, rpc("tools/list"), token=token_a))
    names_a = {t["name"] for t in result_a["tools"]}
    assert "bikebox_plan_network" in names_a
    assert {"ump_list_jobs", "ump_get_job_status", "ump_get_job_results"} <= names_a

    result_b = rpc_result(post_mcp(app_client, rpc("tools/list"), token=token_b))
    names_b = {t["name"] for t in result_b["tools"]}
    assert "bikebox_plan_network" not in names_b
    assert "ump_list_jobs" in names_b


@respx.mock
def test_call_process_tool_executes_and_returns_job(app_client, rsa_keypair):
    respx.get(f"{BASE}/mcp/tools").respond(json=CATALOG_USER_A)
    execution = respx.post(f"{BASE}/processes/bikebox:plan_network/execution").respond(
        status_code=201, json={"jobID": "job-42", "status": "accepted"}
    )

    token = make_token(rsa_keypair, subject="user-a")
    result = rpc_result(
        post_mcp(
            app_client,
            rpc(
                "tools/call",
                {"name": "bikebox_plan_network", "arguments": {"num_boxes": 5}},
            ),
            token=token,
        )
    )

    assert result.get("isError") in (None, False)
    body = json.loads(result["content"][0]["text"])
    assert body["jobID"] == "job-42"

    request = execution.calls[0].request
    assert request.headers["Authorization"] == f"Bearer {token}"
    assert json.loads(request.content) == {"inputs": {"num_boxes": 5}}


@respx.mock
def test_call_with_invalid_arguments_is_tool_error(app_client, rsa_keypair):
    respx.get(f"{BASE}/mcp/tools").respond(json=CATALOG_USER_A)
    token = make_token(rsa_keypair)
    result = rpc_result(
        post_mcp(
            app_client,
            rpc(
                "tools/call",
                {"name": "bikebox_plan_network", "arguments": {"num_boxes": "three"}},
            ),
            token=token,
        )
    )
    assert result["isError"] is True
    assert "Invalid arguments" in result["content"][0]["text"]


@respx.mock
def test_call_tool_not_in_user_catalog_is_tool_error(app_client, rsa_keypair):
    respx.get(f"{BASE}/mcp/tools").respond(json=CATALOG_EMPTY)
    token = make_token(rsa_keypair)
    result = rpc_result(
        post_mcp(
            app_client,
            rpc("tools/call", {"name": "bikebox_plan_network", "arguments": {}}),
            token=token,
        )
    )
    assert result["isError"] is True
    assert "not available" in result["content"][0]["text"]


@respx.mock
def test_ump_authorization_error_surfaces_as_tool_error(app_client, rsa_keypair):
    respx.get(f"{BASE}/mcp/tools").respond(json=CATALOG_USER_A)
    respx.post(f"{BASE}/processes/bikebox:plan_network/execution").respond(
        status_code=403, json={"detail": "missing role"}
    )
    token = make_token(rsa_keypair)
    result = rpc_result(
        post_mcp(
            app_client,
            rpc(
                "tools/call",
                {"name": "bikebox_plan_network", "arguments": {"num_boxes": 1}},
            ),
            token=token,
        )
    )
    assert result["isError"] is True
    assert "403" in result["content"][0]["text"]


@respx.mock
def test_builtin_job_status_tool(app_client, rsa_keypair):
    # The MCP SDK may refresh its tool cache on tools/call, so discovery can
    # be hit even for built-in tools.
    respx.get(f"{BASE}/mcp/tools").respond(json=CATALOG_EMPTY)
    respx.get(f"{BASE}/jobs/job-42").respond(
        json={"jobID": "job-42", "status": "successful"}
    )
    token = make_token(rsa_keypair)
    result = rpc_result(
        post_mcp(
            app_client,
            rpc("tools/call", {"name": "ump_get_job_status", "arguments": {"job_id": "job-42"}}),
            token=token,
        )
    )
    body = json.loads(result["content"][0]["text"])
    assert body["status"] == "successful"


def _sub_of(auth_header: str) -> str:
    """Extracts the 'sub' claim from a Bearer JWT without verification."""
    import base64

    token = auth_header.removeprefix("Bearer ")
    payload_b64 = token.split(".")[1]
    payload_b64 += "=" * (-len(payload_b64) % 4)
    return json.loads(base64.urlsafe_b64decode(payload_b64)).get("sub", "")
