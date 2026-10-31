"""One serialized native connection, one combined sample, no background polling."""
import asyncio
import time

from .native import NativeClient
from .process import client_recent_input, client_ui_ready

SAMPLE_INTERVAL = 4.4
POSITION_MAX_AGE_MS = 6000


class ClientInteracting(RuntimeError):
    pass


class ClientNotReady(RuntimeError):
    pass


async def native_work(function, *args):
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # Keep the async lock until the native worker really finishes.
        await asyncio.gather(task, return_exceptions=True)
        raise


class Playback:
    def __init__(self, native=None):
        self.native = native or NativeClient()
        self.lock = asyncio.Lock()
        self.cached = None
        self.next_sample_at = 0
        self.failures = 0
        self.error = None

    def _snapshot(self):
        if not client_ui_ready():
            raise ClientNotReady('酷狗正在加载或未响应，已暂停原生请求')
        if client_recent_input():
            raise ClientInteracting('正在操作酷狗界面，请稍后再读取状态')
        return self.native.snapshot()

    def _control(self, action, deadline):
        if not client_ui_ready():
            raise RuntimeError('酷狗未响应，未发送控制')
        return self.native.request(action, deadline)

    def _view(self):
        result = dict(self.cached)
        age = int(time.time() * 1000) - result['position_sampled_at']
        pos = result['position_ms']
        result['stale'] = age < 0 or age > POSITION_MAX_AGE_MS
        elapsed = None if result['stale'] or pos is None else pos + (age if result['playback'] == 'playing' else 0)
        duration = result.get('duration_ms') or 0
        if elapsed is not None and duration > 0:
            elapsed = min(elapsed, duration)
        result['elapsed_ms'] = elapsed
        result['progress_ratio'] = elapsed / duration if elapsed is not None and duration > 0 else None
        return result

    async def _sample(self):
        try:
            song, position = await native_work(self._snapshot)
        except ClientInteracting:
            self.next_sample_at = time.monotonic() + .5
            if self.cached is not None:
                return dict(self._view(), deferred=True)
            raise
        except ClientNotReady as exc:
            self.error = str(exc)
            self.next_sample_at = time.monotonic() + SAMPLE_INTERVAL
            raise
        except Exception:
            self.failures += 1
            self.error = '酷狗请求正在退避；稍后再读取，不要反复重试控制'
            self.next_sample_at = time.monotonic() + min(30 * 2 ** min(self.failures - 1, 1), 60)
            raise
        self.failures = 0
        self.error = None
        self.next_sample_at = time.monotonic() + SAMPLE_INTERVAL
        parts = song.get('title', '').split(' - ', 1)
        self.cached = dict(song, backend='kugou_native_bridge_cdp', position_ms=position,
                           position_sampled_at=int(time.time() * 1000),
                           artist=parts[0] if len(parts) > 1 else '', song_name=parts[-1])
        return self._view()

    async def read(self):
        async with self.lock:
            if self.error and time.monotonic() < self.next_sample_at:
                raise RuntimeError(self.error)
            if self.cached is not None and time.monotonic() < self.next_sample_at:
                return self._view()
            delay = self.next_sample_at - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            return await self._sample()

    async def control(self, action):
        if action not in ('play', 'pause', 'next', 'prev'):
            raise ValueError('action 必须为 play、pause、next 或 prev')
        # Reject overlapping actions instead of silently queuing double clicks.
        if self.lock.locked():
            raise RuntimeError('酷狗正在处理上一请求；未排队发送新控制')
        async with self.lock:
            if self.error and time.monotonic() < self.next_sample_at:
                raise RuntimeError('酷狗请求正在退避；本次未发送控制')
            old_hash = (self.cached or {}).get('hash')
            try:
                await native_work(self._control, action, time.monotonic() + 14)
            except Exception as exc:
                self.cached = None
                self.failures += 1
                self.error = '控制结果不确定，已暂停请求；请稍后读取实际状态'
                self.next_sample_at = time.monotonic() + 30
                raise RuntimeError('控制未能确认，指令可能已执行；不要重发，请稍后读取实际状态') from exc
            self.cached = None
            await asyncio.sleep(.6)
            try:
                actual = await self._sample()
            except Exception as exc:
                return {'accepted': True, 'verified': False, 'action': action,
                        'message': f'已提交一次，读回未确认；不要重发：{exc}'}
            verified = actual.get('available', False) and ((actual['playback'] == 'playing') == (action == 'play') if action in ('play', 'pause')
                        else bool(old_hash and actual.get('hash') and actual['hash'] != old_hash))
            return {'backend': 'kugou_native_bridge_cdp', 'accepted': True, 'verified': verified,
                    'action': action, 'actual': actual, 'playback': actual,
                    'message': '' if verified else '已提交一次，状态尚未确认；不要自动重发'}

    async def legacy(self, upstream, name, arguments):
        async with self.lock:
            try:
                return await upstream.call(name, arguments)
            finally:
                self.cached = None
                self.next_sample_at = time.monotonic() + .6

    def close(self):
        self.native.close()
