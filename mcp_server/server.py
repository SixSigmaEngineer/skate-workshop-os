"""SKATE MCP server for Codex and ChatGPT-compatible MCP clients."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("SKATE_ROOT", str(ROOT))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp.server.fastmcp import FastMCP  # noqa: E402
from mcp.types import ToolAnnotations  # noqa: E402

from mcp_server import service  # noqa: E402


INSTRUCTIONS = """
SKATE is a read-only workshop-memory server. Use search_memory for bounded,
governance-aware evidence retrieval. Use get_memory_object only when the full
note is necessary, and trace_evidence when provenance or supporting/conflicting
relationships matter. Never imply that inactive notes or inactive sessions
were searched: they are deliberately excluded by the server.
""".strip()


def create_server(host: str = "127.0.0.1", port: int = 8766) -> FastMCP:
    server = FastMCP(
        name="SKATE Workshop Memory",
        instructions=INSTRUCTIONS,
        host=host,
        port=port,
        stateless_http=True,
        json_response=True,
    )

    read_only = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
    server.tool(annotations=read_only)(service.server_info)
    server.tool(annotations=read_only)(service.list_active_sessions)
    server.tool(annotations=read_only)(service.search_memory)
    server.tool(annotations=read_only)(service.get_memory_object)
    server.tool(annotations=read_only)(service.get_session_context)
    server.tool(annotations=read_only)(service.trace_evidence)
    server.tool(annotations=read_only)(service.get_grind_outputs)
    server.tool(name="search", annotations=read_only)(service.search)
    server.tool(name="fetch", annotations=read_only)(service.fetch)
    return server


mcp = create_server()


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve governed SKATE memory over MCP.")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
        help="stdio for local Codex; streamable-http for a local tunnel or MCP Inspector.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()

    server = mcp if (args.host, args.port) == ("127.0.0.1", 8766) else create_server(args.host, args.port)
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
