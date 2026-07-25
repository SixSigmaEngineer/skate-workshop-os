import asyncio
import os
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class MCPProtocolTests(unittest.TestCase):
    def test_stdio_server_lists_and_calls_tools(self):
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError as exc:  # pragma: no cover - dependency setup failure
            self.fail(f"The required MCP SDK is not installed: {exc}")

        async def exercise_server():
            env = dict(os.environ)
            env["SKATE_ROOT"] = str(ROOT)
            env["SKATE_EMBED_BACKEND"] = "off"
            params = StdioServerParameters(
                command=sys.executable,
                args=[str(ROOT / "mcp_server" / "server.py"), "--transport", "stdio"],
                env=env,
            )
            async with stdio_client(params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    names = {tool.name for tool in listed.tools}
                    expected = {
                        "server_info",
                        "list_active_sessions",
                        "search_memory",
                        "get_memory_object",
                        "get_session_context",
                        "trace_evidence",
                        "get_grind_outputs",
                        "search",
                        "fetch",
                    }
                    self.assertTrue(expected.issubset(names))
                    result = await session.call_tool(
                        "search_memory",
                        {"query": "families repeat their story", "top_k": 2},
                    )
                    self.assertFalse(result.isError)
                    self.assertTrue(result.content)

        asyncio.run(exercise_server())


if __name__ == "__main__":
    unittest.main()
