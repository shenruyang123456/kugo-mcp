import sys
import unittest
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class StdioTests(unittest.IsolatedAsyncioTestCase):
    async def test_version_discovery_and_invalid_action_without_client(self):
        root = Path(__file__).resolve().parent.parent
        params = StdioServerParameters(command=sys.executable, args=[str(root / 'server.py')])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                initialized = await session.initialize()
                self.assertEqual(initialized.serverInfo.version, '1.1.0')
                self.assertEqual(len((await session.list_tools()).tools), 19)
                response = await session.call_tool('kugou_control_playback', {'action':'invalid'})
                self.assertTrue(response.isError)
