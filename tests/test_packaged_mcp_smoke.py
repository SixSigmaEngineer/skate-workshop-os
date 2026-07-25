import asyncio
import os
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGED_SERVER = ROOT / "build" / "app-staging" / "SKATE" / "SKATE-MCP.exe"


@unittest.skipUnless(PACKAGED_SERVER.exists(), "Build SKATE-MCP.exe before packaged smoke testing")
class PackagedMCPTests(unittest.TestCase):
    def test_stdio_handshake_and_server_info(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        async def exercise_server():
            env = dict(os.environ)
            env["SKATE_EMBED_BACKEND"] = "off"
            params = StdioServerParameters(
                command=str(PACKAGED_SERVER),
                args=["--transport", "stdio"],
                env=env,
            )
            async with stdio_client(params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    self.assertIn("search_memory", {tool.name for tool in tools.tools})
                    result = await session.call_tool("server_info", {})
                    self.assertFalse(result.isError)

        asyncio.run(exercise_server())


if __name__ == "__main__":
    unittest.main()
