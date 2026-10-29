import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import server


class FakeClient:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def evaluate(self, _):
        return {'available': True, 'hash': 'abc', 'duration_ms': 20000, 'progress': '123450000', 'playback': 'playing'}


class SnapshotTests(unittest.TestCase):
    @patch('kugou_native_mcp.server.Client', FakeClient)
    def test_progress_and_status_come_from_one_snapshot(self):
        song, position = server.read_snapshot()
        self.assertEqual(song['hash'], 'abc')
        self.assertEqual(position, 12345)
        self.assertNotIn('progress', song)

    def test_metadata_does_not_overwrite_new_song(self):
        server.update(song={'hash': 'new'}, cover='new-cover')
        server.update_if_current('old', cover='stale-cover')
        self.assertEqual(server.state['cover'], 'new-cover')

    def test_refresh_invalidates_stale_status(self):
        old = server.generation
        server.request_refresh()
        self.assertGreater(server.generation, old)
        self.assertFalse(server.state['connected'])


class DailyTests(unittest.IsolatedAsyncioTestCase):
    async def test_daily_only_reads_after_refresh_signal(self):
        old_signal, old_refresh, old_ready = server.daily_signal, server.refresh_signal, server.client_ready
        server.daily_signal = asyncio.Event()
        server.refresh_signal = asyncio.Event()
        server.client_ready = asyncio.Event()
        server.client_ready.set()
        calls = []

        async def fake_call(name, args):
            calls.append(name)
            return {'songs': [{'title': 'test'}]}

        try:
            with patch.object(server, 'call', fake_call):
                task = asyncio.create_task(server.refresh_daily_on_request())
                await asyncio.sleep(0)
                self.assertEqual(calls, [])
                server.request_refresh()
                await asyncio.sleep(0.01)
                self.assertEqual(calls, ['kugou_get_daily_recommendations'])
                await asyncio.sleep(0.01)
                self.assertEqual(len(calls), 1)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
        finally:
            server.daily_signal, server.refresh_signal, server.client_ready = old_signal, old_refresh, old_ready

    async def test_failed_mcp_ping_requests_reconnection(self):
        old_session, old_reconnect = server.session, server.reconnect_signal

        class BrokenSession:
            async def send_ping(self):
                raise RuntimeError('disconnected')

        server.session = BrokenSession()
        server.reconnect_signal = asyncio.Event()
        try:
            await server.monitor_mcp()
            self.assertTrue(server.reconnect_signal.is_set())
            self.assertFalse(server.state['mcp_connected'])
        finally:
            server.session, server.reconnect_signal = old_session, old_reconnect


class StartupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.old_ready, self.old_refresh = server.client_ready, server.refresh_signal
        server.client_ready = asyncio.Event()
        server.refresh_signal = asyncio.Event()

    async def asyncTearDown(self):
        server.client_ready, server.refresh_signal = self.old_ready, self.old_refresh

    async def test_reuses_existing_debug_connection(self):
        with patch.object(server, 'debug_available', return_value=True), patch.object(server, 'kugou_is_running') as running:
            await server.ensure_kugou()
        running.assert_not_called()
        self.assertTrue(server.client_ready.is_set())
        self.assertEqual(server.state['startup_status'], 'ready')

    async def test_running_normal_client_is_not_terminated_or_restarted(self):
        with patch.object(server, 'debug_available', return_value=False), patch.object(server, 'kugou_is_running', return_value=True), patch('asyncio.create_subprocess_exec') as launch:
            await server.ensure_kugou()
        launch.assert_not_called()
        self.assertFalse(server.client_ready.is_set())
        self.assertEqual(server.state['startup_status'], 'running_without_debug')

    async def test_stopped_client_is_launched(self):
        proc = AsyncMock()
        proc.returncode = 0
        proc.communicate.return_value = (b'', b'')
        with patch.object(server, 'debug_available', return_value=False), patch.object(server, 'kugou_is_running', return_value=False), patch('asyncio.create_subprocess_exec', new=AsyncMock(return_value=proc)) as launch:
            await server.ensure_kugou()
        launch.assert_awaited_once()
        self.assertTrue(server.client_ready.is_set())
        self.assertEqual(server.state['startup_status'], 'ready')


if __name__ == '__main__':
    unittest.main()
