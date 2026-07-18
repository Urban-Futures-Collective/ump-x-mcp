"""The HTTP adapters must forward the caller's original JWT unchanged and map
UMP's discovery/execution/job responses faithfully."""

import pytest
import respx

from ump_mcp.adapters.ump_http import (
    UmpHttpExecutionAdapter,
    UmpHttpJobsAdapter,
    UmpHttpToolCatalogAdapter,
    build_ump_client,
)
from ump_mcp.domain.models import ANONYMOUS, UserContext
from ump_mcp.ports import UmpApiError

BASE = "http://ump.test/api"
USER = UserContext(raw_token="the-original-jwt", claims={"sub": "user-123"})

CATALOG_RESPONSE = {
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
        },
        {
            "tool": "traffic:noise-sim",
            "title": "Noise simulation",
            "description": "",
            "inputSchema": {"type": "object", "properties": {}},
            "provider": "traffic",
            "processId": "noise-sim",
        },
    ]
}


@pytest.fixture
def client():
    return build_ump_client(BASE, timeout=5.0)


@respx.mock
async def test_catalog_forwards_jwt_and_maps_tools(client):
    route = respx.get(f"{BASE}/mcp/tools").respond(json=CATALOG_RESPONSE)
    tools = await UmpHttpToolCatalogAdapter(client).list_tools(USER)

    assert route.call_count == 1
    assert route.calls[0].request.headers["Authorization"] == "Bearer the-original-jwt"

    assert [t.tool for t in tools] == ["bikebox:plan_network", "traffic:noise-sim"]
    # Names are MCP-safe (colon replaced), originals preserved for execution.
    assert tools[0].name == "bikebox_plan_network"
    assert tools[0].process_id_with_prefix == "bikebox:plan_network"
    assert tools[0].input_schema["required"] == ["num_boxes"]


@respx.mock
async def test_catalog_anonymous_sends_no_auth_header(client):
    route = respx.get(f"{BASE}/mcp/tools").respond(json={"tools": []})
    await UmpHttpToolCatalogAdapter(client).list_tools(ANONYMOUS)
    assert "Authorization" not in route.calls[0].request.headers


@respx.mock
async def test_catalog_error_maps_to_ump_api_error(client):
    respx.get(f"{BASE}/mcp/tools").respond(status_code=401, json={"detail": "nope"})
    with pytest.raises(UmpApiError) as excinfo:
        await UmpHttpToolCatalogAdapter(client).list_tools(USER)
    assert excinfo.value.status_code == 401


@respx.mock
async def test_execution_forwards_jwt_and_inputs(client):
    route = respx.post(f"{BASE}/processes/bikebox:plan_network/execution").respond(
        status_code=201, json={"jobID": "job-1", "status": "accepted"}
    )
    result = await UmpHttpExecutionAdapter(client).execute(
        USER, "bikebox:plan_network", {"num_boxes": 3}
    )

    request = route.calls[0].request
    assert request.headers["Authorization"] == "Bearer the-original-jwt"
    import json

    assert json.loads(request.content) == {"inputs": {"num_boxes": 3}}
    assert result.job_id == "job-1"
    assert result.status == "accepted"


@respx.mock
async def test_execution_error_surfaces_status(client):
    respx.post(f"{BASE}/processes/x:y/execution").respond(
        status_code=403, json={"detail": "missing role"}
    )
    with pytest.raises(UmpApiError) as excinfo:
        await UmpHttpExecutionAdapter(client).execute(USER, "x:y", {})
    assert excinfo.value.status_code == 403
    assert "missing role" in str(excinfo.value)


@respx.mock
async def test_jobs_adapter_paths(client):
    respx.get(f"{BASE}/jobs/").respond(json={"jobs": []})
    respx.get(f"{BASE}/jobs/job-1").respond(json={"jobID": "job-1", "status": "running"})
    respx.get(f"{BASE}/jobs/job-1/results").respond(json={"answer": 42})

    adapter = UmpHttpJobsAdapter(client)
    assert await adapter.list_jobs(USER) == {"jobs": []}
    assert (await adapter.get_job(USER, "job-1"))["status"] == "running"
    assert await adapter.get_job_results(USER, "job-1") == {"answer": 42}
