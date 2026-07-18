import re
from dataclasses import dataclass, field
from typing import Any

# MCP clients (and the Anthropic API) restrict tool names to this alphabet.
_TOOL_NAME_ALLOWED = re.compile(r"[^a-zA-Z0-9_-]")


def sanitize_tool_name(raw: str) -> str:
    """Maps a UMP tool identifier ("provider:process_id") to a valid MCP tool name."""
    return _TOOL_NAME_ALLOWED.sub("_", raw)[:64]


@dataclass(frozen=True)
class UserContext:
    """The authenticated caller of the current MCP request.

    ``raw_token`` is the original, unmodified JWT — it is forwarded verbatim
    to UMP so UMP can make the final authorization decision (zero trust).
    ``raw_token is None`` means anonymous access.
    """

    raw_token: str | None
    claims: dict[str, Any] = field(default_factory=dict)

    @property
    def subject(self) -> str | None:
        return self.claims.get("sub")

    @property
    def is_anonymous(self) -> bool:
        return self.raw_token is None


ANONYMOUS = UserContext(raw_token=None)


@dataclass(frozen=True)
class ToolDescriptor:
    """One UMP process as advertised by GET /mcp/tools."""

    tool: str  # UMP identifier, "provider:process_id"
    title: str
    description: str
    input_schema: dict[str, Any]
    provider: str
    process_id: str

    @property
    def name(self) -> str:
        """MCP-safe tool name."""
        return sanitize_tool_name(self.tool)

    @property
    def process_id_with_prefix(self) -> str:
        """The ID UMP's /processes routes expect."""
        return self.tool

    @classmethod
    def from_ump(cls, entry: dict[str, Any]) -> "ToolDescriptor":
        return cls(
            tool=entry["tool"],
            title=entry.get("title") or entry["tool"],
            description=entry.get("description") or "",
            input_schema=entry.get("inputSchema") or {"type": "object", "properties": {}},
            provider=entry.get("provider", ""),
            process_id=entry.get("processId", ""),
        )


@dataclass(frozen=True)
class ExecutionResult:
    """Outcome of submitting a process execution to UMP."""

    job_id: str
    status: str
    raw: dict[str, Any]
