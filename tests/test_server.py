import json
import unittest
from unittest.mock import AsyncMock

from mcp import types
import server


def result(value, error=False):
    return types.CallToolResult(
        content=[types.TextContent(type='text', text=json.dumps(value))], isError=error
    )


class ServerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.old_sessions = dict(server.sessions)
        self.old_tools = dict(server.tools_by_name)
        self.addCleanup(self.restore)
        server.sessions.clear()
        server.tools_by_name.clear()

    def restore(self):
        server.sessions.clear()
        server.sessions.update(self.old_sessions)
        server.tools_by_name.clear()
        server.tools_by_name.update(self.old_tools)

    async def test_current_cover_uses_current_song_hash(self):
        native = AsyncMock()
        native.call_tool.return_value = result({'title': 'Example', 'hash': 'abc'})
        meting = AsyncMock()
        meting.call_tool.return_value = result({'ok': True, 'data': {'url': 'https://example.com/cover.jpg'}})
        server.sessions.update(native=native, meting=meting)
        data = await server.call_tool('kugo_get_current_cover', {})
        self.assertEqual(data['cover']['url'], 'https://example.com/cover.jpg')
        meting.call_tool.assert_awaited_once_with('pic', {'platform': 'kugou', 'id': 'abc'})

    async def test_upstream_error_is_preserved(self):
        native = AsyncMock()
        native.call_tool.return_value = result('disconnected', error=True)
        server.sessions['native'] = native
        data = await server.call_tool('kugo_get_current_cover', {})
        self.assertTrue(data.isError)

    async def test_unexposed_tool_is_rejected(self):
        with self.assertRaises(ValueError):
            await server.call_tool('kugou_set_play_mode', {'mode': 'shuffle'})

    async def test_forwarded_tool_preserves_arguments(self):
        session = AsyncMock()
        expected = result({'ok': True})
        session.call_tool.return_value = expected
        server.sessions['meting'] = session
        server.tools_by_name['search'] = types.Tool(name='search', inputSchema={'type': 'object'})
        data = await server.call_tool('search', {'platform': 'kugou', 'keyword': 'test'})
        self.assertIs(data, expected)
        session.call_tool.assert_awaited_once_with('search', {'platform': 'kugou', 'keyword': 'test'})


if __name__ == '__main__':
    unittest.main()
