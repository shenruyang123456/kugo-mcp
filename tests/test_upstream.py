import asyncio
import time
import unittest
from contextlib import asynccontextmanager
from unittest.mock import patch

from kugo_mcp.upstream import LazyMcp


class UpstreamTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.starts = self.active = self.max_active = self.exits = self.calls = 0
        self.fail_start = False
        self.gate = None
        test = self
        @asynccontextmanager
        async def stdio(params):
            self.starts += 1; self.active += 1
            self.max_active = max(self.max_active, self.active)
            try:
                yield None, None
            finally:
                self.active -= 1; self.exits += 1
        class Session:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def initialize(self):
                if test.fail_start:
                    raise RuntimeError('failed')
            async def call_tool(self, name, args):
                test.calls += 1
                if test.gate is not None:
                    await test.gate.wait()
                return {'name':name,'args':args}
        for mock in (patch('kugo_mcp.upstream.stdio_client', stdio),
                     patch('kugo_mcp.upstream.ClientSession', side_effect=lambda *a,**k:Session())):
            mock.start(); self.addCleanup(mock.stop)
        self.client = LazyMcp(lambda: None, idle_seconds=.04)

    async def asyncTearDown(self):
        await self.client.close()
        self.assertEqual(self.active, 0)

    async def until(self, condition):
        deadline = time.monotonic() + 1
        while not condition():
            if time.monotonic() > deadline: self.fail('lifecycle timeout')
            await asyncio.sleep(.002)

    async def test_lazy_parallel_idle_restart_and_no_overlap(self):
        await asyncio.sleep(.01)
        self.assertEqual(self.starts, 0)
        await asyncio.gather(self.client.call('pic',{}), self.client.call('lyric',{}))
        self.assertEqual(self.starts, 1)
        self.assertEqual(self.calls, 2)
        await self.until(lambda: self.exits == 1)
        await self.client.call('pic',{})
        self.assertEqual(self.starts, 2)
        self.assertEqual(self.max_active, 1)

    async def test_does_not_close_while_requests_are_running(self):
        self.gate = asyncio.Event()
        request = asyncio.create_task(self.client.call('pic',{}))
        await self.until(lambda:self.calls == 1)
        await asyncio.sleep(.09)
        self.assertEqual(self.exits, 0)
        self.gate.set()
        await request
        await self.until(lambda:self.exits == 1)

    async def test_failed_initialization_fails_coalesced_queue_and_can_recover(self):
        self.fail_start = True
        results = await asyncio.gather(self.client.call('pic',{}),self.client.call('lyric',{}),return_exceptions=True)
        self.assertTrue(all(isinstance(r,RuntimeError) for r in results))
        self.assertEqual(self.starts, 1)
        self.fail_start = False
        self.client.retry_at = 0
        await self.client.call('pic',{})
        self.assertEqual(self.starts, 2)

    async def test_cancellation_does_not_leak_worker_or_future(self):
        self.gate = asyncio.Event()
        request = asyncio.create_task(self.client.call('pic',{}))
        await self.until(lambda:self.calls == 1)
        request.cancel()
        await asyncio.gather(request,return_exceptions=True)
        await self.client.close()
        self.assertEqual(len(self.client.pending), 0)
