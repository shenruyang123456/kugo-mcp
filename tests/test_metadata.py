import asyncio
import unittest
from unittest.mock import AsyncMock

from kugo_mcp.metadata import Metadata, parse_lyrics
from test_server import result


class MetadataTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.upstream = AsyncMock()
        self.upstream.call.return_value = result({'ok': True, 'data': {}})
        self.metadata = Metadata(self.upstream)

    async def asyncTearDown(self):
        await self.metadata.close()

    async def test_empty_results_and_concurrent_requests_are_cached(self):
        await asyncio.gather(self.metadata.get('hash'), self.metadata.get('hash'))
        await self.metadata.get('hash')
        self.assertEqual(self.upstream.call.await_count, 2)

    async def test_five_track_lru_keeps_recent_access(self):
        for i in range(5):
            await self.metadata.get(str(i))
        await self.metadata.get('0')
        await self.metadata.get('5')
        self.assertEqual(len(self.metadata.cache), 5)
        self.assertNotIn('1', self.metadata.cache)
        self.assertIn('0', self.metadata.cache)

    async def test_failure_is_partial_and_retried_after_backoff(self):
        async def call(name, args):
            return result({'ok':False,'message':'offline'}) if name == 'pic' else result({'ok':True,'data':{'lyric':'[00:01]line'}})
        self.upstream.call.side_effect = call
        entry = await self.metadata.get('hash')
        await self.metadata.get('hash')
        self.assertIn('cover_error', entry)
        self.assertIn('lyrics', entry)
        self.assertEqual(self.upstream.call.await_count, 2)
        entry['cover_retry_at'] = 0
        await self.metadata.get('hash')
        self.assertEqual(self.upstream.call.await_count, 3)

    async def test_no_search_or_client_queries_for_metadata(self):
        await self.metadata.get('actual')
        self.assertEqual([c.args[0] for c in self.upstream.call.await_args_list], ['pic', 'lyric'])
        self.assertTrue(all(c.args[1] == {'platform':'kugou','id':'actual'} for c in self.upstream.call.await_args_list))

    async def test_evicted_inflight_track_still_returns_coalesced_result(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def call(name, args):
            if args['id'] == 'old':
                entered.set()
                await release.wait()
            return result({'ok':True,'data':{'url':'https://imge.kugou.com/a.jpg'}})
        self.upstream.call.side_effect = call
        first = asyncio.create_task(self.metadata.get('old'))
        await entered.wait()
        for i in range(5):
            await self.metadata.get(str(i))
        repeated = asyncio.create_task(self.metadata.get('old'))
        await asyncio.sleep(0)
        release.set()
        _, entry = await asyncio.gather(first, repeated)
        self.assertEqual(entry['cover']['url'], 'https://imge.kugou.com/a.jpg')
        self.assertEqual(sum(c.args[1]['id']=='old' for c in self.upstream.call.await_args_list), 2)
        self.assertEqual(len(self.metadata.cache), 5)

    async def test_timestamp_duplicates_and_stale_position(self):
        lines = parse_lyrics('[00:01.2]first\n[00:03]one\n[00:03]last')
        entry = {'lyrics':{'lyric':'test'}, '_lines':lines, '_times':[line['time_ms'] for line in lines]}
        self.assertEqual(Metadata.view(entry, {'elapsed_ms':3000})['lyrics']['current_line'], 'last')
        self.assertEqual(Metadata.view(entry, {'elapsed_ms':0})['lyrics']['status'], 'intro')
        self.assertEqual(Metadata.view(entry, {'elapsed_ms':None})['lyrics']['status'], 'waiting_progress')
        self.assertEqual(lines[0]['time_ms'], 1200)
