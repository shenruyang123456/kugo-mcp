"""Five-track metadata cache, coalesced misses and timestamp-based lyrics."""
import asyncio
import json
import re
import time
from bisect import bisect_right
from collections import OrderedDict

STAMP = re.compile(r'\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]')


def unpack(result):
    if result.isError:
        message = next((c.text for c in result.content if c.type == 'text'), '上游调用失败')
        raise RuntimeError(message)
    if result.structuredContent is not None:
        return result.structuredContent
    return json.loads(next(c.text for c in result.content if c.type == 'text'))


def parse_lyrics(lrc):
    lines = []
    for row in lrc.splitlines():
        text = STAMP.sub('', row).strip()
        if not text:
            continue
        for stamp in STAMP.finditer(row):
            minutes, seconds, fraction = stamp.groups()
            lines.append({'time_ms': (int(minutes) * 60 + int(seconds)) * 1000 + int((fraction or '').ljust(3, '0')),
                          'text': text})
    lines.sort(key=lambda line: line['time_ms'])
    return lines


class Metadata:
    def __init__(self, upstream):
        self.upstream = upstream
        self.cache = OrderedDict()
        self.tasks = {}

    def _entry(self, song_hash):
        entry = self.cache.setdefault(song_hash, {})
        self.cache.move_to_end(song_hash)
        while len(self.cache) > 5:
            self.cache.popitem(last=False)
        return entry

    async def _fetch(self, song_hash, field, entry):
        try:
            result = unpack(await self.upstream.call('pic' if field == 'cover' else 'lyric',
                                                    {'platform': 'kugou', 'id': song_hash}))
            if result.get('ok') is False:
                raise RuntimeError(result.get('message') or '音乐资料接口不可用')
            data = result.get('data') or {}
            if field == 'cover':
                url = data.get('url') or ''
                if url.startswith('http://imge.kugou.com/'):
                    url = 'https://' + url[7:]
                entry[field] = dict(data, url=url)
            else:
                lrc = data.get('lyric') or ''
                lines = parse_lyrics(lrc)
                entry[field] = {'lyric': lrc}
                entry['_lines'] = lines
                entry['_times'] = [line['time_ms'] for line in lines]
            entry.pop(field + '_error', None)
            entry.pop(field + '_retry_at', None)
        except Exception as exc:
            entry[field + '_error'] = str(exc)
            entry[field + '_retry_at'] = time.monotonic() + 30
        return entry

    async def get(self, song_hash, fields=('cover', 'lyrics')):
        entry = self._entry(song_hash)
        work = []
        for field in fields:
            if field in entry or time.monotonic() < entry.get(field + '_retry_at', 0):
                continue
            key = (song_hash, field)
            task = self.tasks.get(key)
            if task is None:
                task = asyncio.create_task(self._fetch(song_hash, field, entry))
                self.tasks[key] = task
                task.add_done_callback(lambda _task, key=key: self.tasks.pop(key, None))
            work.append(asyncio.shield(task))
        if work:
            for completed in await asyncio.gather(*work):
                # A rapid six-track round trip can evict an in-flight entry.
                # Reuse its result for the same hash without fetching it twice.
                if completed is not entry:
                    entry.update(completed)
        return entry

    @staticmethod
    def view(entry, playback, include_lines=False):
        result = {'cover': entry.get('cover'), 'lyrics': None,
                  'errors': {field: entry[field + '_error'] for field in ('cover', 'lyrics') if field + '_error' in entry}}
        if 'lyrics' in entry:
            lyrics = dict(entry['lyrics'], current_line=None, line_index=None)
            lines, elapsed = entry.get('_lines', []), playback['elapsed_ms']
            if not lyrics['lyric']:
                lyrics['status'] = 'no_lyrics'
            elif not lines:
                lyrics['status'] = 'unsynced'
            elif elapsed is None:
                lyrics['status'] = 'waiting_progress'
            else:
                index = bisect_right(entry['_times'], elapsed) - 1
                lyrics.update(status='intro' if index < 0 else 'synced', line_index=index,
                              current_line=None if index < 0 else lines[index]['text'])
            if include_lines:
                lyrics['lines'] = lines
            result['lyrics'] = lyrics
        return result

    async def close(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
