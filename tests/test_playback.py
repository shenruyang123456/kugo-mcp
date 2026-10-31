import asyncio
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from kugo_mcp.playback import Playback


def song(song_hash='one'):
    return {'available': True, 'hash': song_hash, 'title': 'Artist - Song',
            'playback': 'playing', 'duration_ms': 180000}, 1000


class PlaybackTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.native = MagicMock()
        self.native.snapshot.return_value = song()
        self.player = Playback(self.native)
        for mock in (patch('kugo_mcp.playback.client_ui_ready', return_value=True),
                     patch('kugo_mcp.playback.client_recent_input', return_value=False)):
            mock.start()
            self.addCleanup(mock.stop)

    async def test_concurrent_reads_share_one_sample_and_44_second_limit(self):
        await asyncio.gather(*(self.player.read() for _ in range(12)))
        self.native.snapshot.assert_called_once()
        self.assertGreater(self.player.next_sample_at - time.monotonic(), 4.2)
        self.assertLessEqual(self.player.next_sample_at - time.monotonic(), 4.4)
        self.player.next_sample_at = 0
        await self.player.read()
        self.assertEqual(self.native.snapshot.call_count, 2)

    async def test_one_control_and_one_readback_preserve_cache(self):
        await self.player.read()
        self.native.snapshot.return_value = song('two')
        result = await self.player.control('next')
        for _ in range(10):
            await self.player.read()
        self.native.request.assert_called_once()
        self.assertTrue(result['verified'])
        self.assertEqual(result['actual']['hash'], 'two')
        self.assertEqual(self.native.snapshot.call_count, 2)

    async def test_uncertain_control_is_not_retried(self):
        self.native.request.side_effect = TimeoutError
        with self.assertRaisesRegex(RuntimeError, '不要重发'):
            await self.player.control('next')
        with self.assertRaises(RuntimeError):
            await self.player.control('next')
        self.native.request.assert_called_once()
        self.native.snapshot.assert_not_called()

    async def test_native_failure_backs_off_without_reconnecting(self):
        self.native.snapshot.side_effect = TimeoutError
        for _ in range(2):
            with self.assertRaises((RuntimeError, TimeoutError)):
                await self.player.read()
        self.native.snapshot.assert_called_once()

    async def test_unresponsive_window_does_not_call_native(self):
        with patch('kugo_mcp.playback.client_ui_ready', return_value=False):
            with self.assertRaises(RuntimeError):
                await self.player.read()
        self.native.snapshot.assert_not_called()

    async def test_recent_input_reuses_cache_without_disconnect_backoff(self):
        await self.player.read()
        self.player.next_sample_at = 0
        with patch('kugo_mcp.playback.client_recent_input', return_value=True):
            result = await self.player.read()
        self.assertTrue(result['deferred'])
        self.assertEqual(self.player.failures, 0)
        self.native.snapshot.assert_called_once()

    async def test_stale_progress_does_not_advance(self):
        await self.player.read()
        self.player.cached['position_sampled_at'] -= 7000
        result = self.player._view()
        self.assertTrue(result['stale'])
        self.assertIsNone(result['elapsed_ms'])

    async def test_cancellation_retains_lock_until_worker_finishes(self):
        entered, release = threading.Event(), threading.Event()
        def slow():
            entered.set(); release.wait(2)
            return song()
        self.native.snapshot.side_effect = slow
        request = asyncio.create_task(self.player.read())
        await asyncio.to_thread(entered.wait, 1)
        request.cancel()
        await asyncio.sleep(.02)
        self.assertTrue(self.player.lock.locked())
        with self.assertRaises(RuntimeError):
            await self.player.control('next')
        release.set()
        await asyncio.gather(request, return_exceptions=True)
        self.assertFalse(self.player.lock.locked())
