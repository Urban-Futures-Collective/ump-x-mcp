"""MCP server for the Urban Model Platform (UMP-X).

Translates UMP processes into MCP tools (discovery + execution), enforces its
own JWT validation (zero trust), and forwards the original user JWT to UMP
unchanged. See mcp-integration-strategy.md and ARCHITECTURE.md in the
urban-model-platform repository for the overall design.
"""

__version__ = "0.1.0"
