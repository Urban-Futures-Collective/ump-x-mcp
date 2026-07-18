"""The MCP server core: dynamic, per-user tools backed by the UMP catalog.

Tool discovery and execution both run against UMP with the caller's original
JWT, so the visible tool set — and whether an execution is allowed — is always
UMP's decision. Nothing here is hard-coded per process: new UMP providers and
processes appear as MCP tools without a code change.
"""

import json
import logging
from typing import Any

import jsonschema
import mcp.types as types
from mcp.server.lowlevel import Server

from ump_mcp.auth import current_user
from ump_mcp.domain.models import ToolDescriptor
from ump_mcp.ports import JobsPort, ToolCatalogPort, ToolExecutionPort, UmpApiError

logger = logging.getLogger(__name__)

# Built-in read-only tools (strategy roadmap phase 1), next to the dynamic
# per-process execution tools (phase 2).
_LIST_JOBS = types.Tool(
    name="ump_list_jobs",
    title="List jobs",
    description=(
        "List the Urban Model Platform jobs visible to the current user "
        "(own jobs and jobs shared with them)."
    ),
    inputSchema={"type": "object", "properties": {}},
)
_JOB_STATUS = types.Tool(
    name="ump_get_job_status",
    title="Get job status",
    description="Get the current status and metadata of a UMP job by its job ID.",
    inputSchema={
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "The UMP job ID."}
        },
        "required": ["job_id"],
    },
)
_JOB_RESULTS = types.Tool(
    name="ump_get_job_results",
    title="Get job results",
    description="Fetch the results of a finished UMP job by its job ID.",
    inputSchema={
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "The UMP job ID."}
        },
        "required": ["job_id"],
    },
)
_BUILTIN_TOOLS = [_LIST_JOBS, _JOB_STATUS, _JOB_RESULTS]
_BUILTIN_NAMES = {tool.name for tool in _BUILTIN_TOOLS}


def _to_mcp_tool(descriptor: ToolDescriptor) -> types.Tool:
    description = descriptor.description
    if descriptor.name != descriptor.tool:
        description = (
            f"{description}\n\n(UMP process '{descriptor.tool}' "
            f"from provider '{descriptor.provider}'.)"
        ).strip()
    return types.Tool(
        name=descriptor.name,
        title=descriptor.title,
        description=description,
        inputSchema=descriptor.input_schema,
    )


def _json_content(payload: Any) -> list[types.TextContent]:
    return [types.TextContent(type="text", text=json.dumps(payload, indent=2))]


def build_mcp_server(
    catalog: ToolCatalogPort,
    execution: ToolExecutionPort,
    jobs: JobsPort,
) -> Server:
    server: Server = Server(
        "ump-x-mcp",
        instructions=(
            "Tools of the Urban Model Platform (UMP). Each urban simulation "
            "process is exposed as its own tool; invoking one submits an "
            "asynchronous job and returns its job ID. Use ump_get_job_status "
            "to poll until the job has finished, then ump_get_job_results to "
            "fetch the results."
        ),
    )

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        user = current_user()
        descriptors = await catalog.list_tools(user)
        return [_to_mcp_tool(d) for d in descriptors] + _BUILTIN_TOOLS

    # Input validation happens below against the freshly fetched per-user
    # catalog — the SDK's cached validation would mix schemas across users.
    @server.call_tool(validate_input=False)
    async def call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        arguments = arguments or {}
        try:
            if name in _BUILTIN_NAMES:
                return await _call_builtin(jobs, name, arguments)
            return await _call_process(catalog, execution, name, arguments)
        except UmpApiError as exc:
            return types.CallToolResult(
                content=_json_content({"error": str(exc), "status_code": exc.status_code}),
                isError=True,
            )

    async def _call_builtin(
        jobs_port: JobsPort, name: str, arguments: dict[str, Any]
    ) -> types.CallToolResult:
        user = current_user()
        if name == _LIST_JOBS.name:
            payload = await jobs_port.list_jobs(user)
        else:
            job_id = arguments.get("job_id")
            if not isinstance(job_id, str) or not job_id:
                return types.CallToolResult(
                    content=_json_content({"error": "'job_id' (string) is required"}),
                    isError=True,
                )
            if name == _JOB_STATUS.name:
                payload = await jobs_port.get_job(user, job_id)
            else:
                payload = await jobs_port.get_job_results(user, job_id)
        return types.CallToolResult(content=_json_content(payload))

    async def _call_process(
        catalog_port: ToolCatalogPort,
        execution_port: ToolExecutionPort,
        name: str,
        arguments: dict[str, Any],
    ) -> types.CallToolResult:
        user = current_user()
        # Re-resolve against a fresh, per-user catalog: the tool must (still)
        # be visible to this user before we even attempt an execution. UMP
        # re-checks authorization on the execution call regardless.
        descriptors = {d.name: d for d in await catalog_port.list_tools(user)}
        descriptor = descriptors.get(name)
        if descriptor is None:
            return types.CallToolResult(
                content=_json_content(
                    {"error": f"Unknown tool '{name}' (not available for this user)"}
                ),
                isError=True,
            )

        try:
            jsonschema.validate(arguments, descriptor.input_schema)
        except jsonschema.ValidationError as exc:
            return types.CallToolResult(
                content=_json_content(
                    {"error": f"Invalid arguments for '{name}': {exc.message}"}
                ),
                isError=True,
            )

        result = await execution_port.execute(
            user, descriptor.process_id_with_prefix, arguments
        )
        logger.info(
            "Submitted process '%s' as job '%s' for user '%s'",
            descriptor.tool,
            result.job_id,
            user.subject or "<anonymous>",
        )
        return types.CallToolResult(
            content=_json_content(
                {
                    "jobID": result.job_id,
                    "status": result.status,
                    "hint": (
                        "The job runs asynchronously. Poll ump_get_job_status "
                        "with this jobID, then fetch ump_get_job_results."
                    ),
                }
            )
        )

    return server
