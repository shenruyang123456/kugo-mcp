import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from mcp import types
import server
from kugo_mcp.playback import Playback
from kugo_mcp.service import Service


def result(value, error=False):
    return types.CallToolResult(content=[types.TextContent(type='text', text=json.dumps(value))], isError=error)


class ServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.previous = server.service
        self.native = MagicMock()
        self.native.snapshot.return_value = ({'available': True, 'hash':'abc', 'title':'Artist - Example',
            'playback':'playing', 'duration_ms':180000}, 1000)
        self.playback = Playback(self.native)
        self.app = Service(playback=self.playback)
        server.service = self.app
        self.ready = patch('kugo_mcp.playback.client_ui_ready', return_value=True)
        self.interacting = patch('kugo_mcp.playback.client_recent_input', return_value=False)
        self.ready.start(); self.interacting.start()
        self.app.meting.call = AsyncMock(return_value=result({'ok':True,'data':{'url':'https://imge.kugou.com/a.jpg','lyric':'[00:00]line'}}))

    async def asyncTearDown(self):
        await self.app.close()
        self.ready.stop(); self.interacting.stop()
        server.service = self.previous

    async def test_current_cover_uses_current_song_hash(self):
        data = await server.call_tool('kugo_get_current_cover', {})
        self.assertEqual(data['cover']['url'], 'https://imge.kugou.com/a.jpg')
        self.app.meting.call.assert_awaited_once_with('pic', {'platform':'kugou','id':'abc'})

    async def test_upstream_error_is_preserved(self):
        self.app.meting.call.return_value = result('disconnected', error=True)
        data = await server.call_tool('kugo_get_current_cover', {})
        self.assertTrue(data.isError)

    async def test_unexposed_tool_is_rejected(self):
        data = await server.call_tool('kugou_set_play_mode', {'mode':'shuffle'})
        self.assertTrue(data.isError)

    async def test_forwarded_tool_preserves_arguments(self):
        expected = result({'ok':True})
        self.app.meting.call.return_value = expected
        data = await server.call_tool('search', {'platform':'kugou','keyword':'test'})
        self.assertIs(data, expected)
        self.app.meting.call.assert_awaited_once_with('search', {'platform':'kugou','keyword':'test'})

    async def test_discovery_is_lazy_and_preserves_all_old_names(self):
        tools = {t.name for t in await server.list_tools()}
        old = {'kugou_get_playback','kugou_get_daily_recommendations','kugou_play_daily_recommendations',
            'kugou_get_favorites','kugou_control_playback','kugou_get_play_mode','platforms','search',
            'song','album','artist','playlist','lyric','pic','kugo_get_current_cover'}
        self.assertTrue(old <= tools)
        self.assertEqual(len(tools), 19)
        self.assertIsNone(self.app.meting.worker)
        self.assertIsNone(self.app.legacy.worker)
        self.native.snapshot.assert_not_called()

    async def test_combined_and_separate_calls_share_snapshot_and_metadata(self):
        track = await server.call_tool('kugo_get_current_track', {'include_lines':True})
        lyric = await server.call_tool('kugo_get_current_lyrics', {})
        progress = await server.call_tool('kugo_get_current_progress', {})
        self.assertEqual(track['lyrics']['current_line'], 'line')
        self.assertEqual(lyric['lyrics']['lyric'], '[00:00]line')
        self.assertEqual(progress['hash'], 'abc')
        self.assertEqual(self.native.snapshot.call_count, 1)
        self.assertEqual(self.app.meting.call.await_count, 2)

    async def test_legacy_tools_are_only_started_by_explicit_call(self):
        self.app.legacy.call = AsyncMock(return_value=result({'mode':'order'}))
        await server.call_tool('kugou_get_playback', {})
        self.app.legacy.call.assert_not_called()
        await server.call_tool('kugou_get_play_mode', {})
        self.app.legacy.call.assert_awaited_once_with('kugou_get_play_mode', {})

    async def test_late_metadata_is_marked_changed_and_keeps_original_hash(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def slow(*args):
            entered.set(); await release.wait()
            return result({'ok':True,'data':{'url':'https://imge.kugou.com/a.jpg'}})
        self.app.meting.call.side_effect = slow
        fetch = asyncio.create_task(server.call_tool('kugo_get_current_cover', {}))
        await entered.wait()
        self.playback.cached = dict(self.playback.cached, hash='new')
        release.set()
        data = await fetch
        self.assertTrue(data['track_changed'])
        self.assertEqual(data['playback']['hash'], 'abc')
