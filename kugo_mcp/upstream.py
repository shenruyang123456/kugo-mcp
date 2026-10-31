"""Own child MCP sessions in one task so AnyIO cleanup runs in its original scope."""
import asyncio
import logging
import time
from contextlib import AsyncExitStack
from datetime import timedelta

from mcp import ClientSession
from mcp.client.stdio import stdio_client

log = logging.getLogger(__name__)


class LazyMcp:
    def __init__(self, params, idle_seconds=30):
        self.params = params
        self.idle_seconds = idle_seconds
        self.queue = asyncio.Queue()
        self.worker = None
        self.closed = False
        self.retry_at = 0
        self.last_used = 0
        self.pending = set()

    async def call(self, name, arguments):
        if self.closed:
            raise RuntimeError('上游服务已关闭')
        if time.monotonic() < self.retry_at:
            raise RuntimeError('上游服务暂不可用，正在退避，请稍后重试')
        if len(self.pending) >= 16:
            raise RuntimeError('上游请求已满；未加入更多请求')
        future = asyncio.get_running_loop().create_future()
        self.pending.add(future)
        future.add_done_callback(self.pending.discard)
        self.queue.put_nowait((name, arguments, future))
        if self.worker is None:
            self.worker = asyncio.create_task(self._run())
        try:
            return await asyncio.wait_for(future, timeout=50)
        except TimeoutError as exc:
            raise RuntimeError('上游请求超时；不会重复发送指令') from exc

    async def _request(self, session, item):
        name, arguments, future = item
        if future.done():
            return
        try:
            result = await session.call_tool(name, arguments)
            if not future.done():
                future.set_result(result)
        except Exception as exc:
            if not future.done():
                future.set_exception(RuntimeError(f'上游调用失败，不自动重发：{type(exc).__name__}'))
        finally:
            self.last_used = time.monotonic()

    async def _run(self):
        while True:
            item = await self.queue.get()
            if item is None:
                return
            if item[2].done():
                continue
            active = set()
            owned = {item[2]}
            try:
                async with AsyncExitStack() as stack:
                    read, write = await stack.enter_async_context(stdio_client(self.params()))
                    session = await stack.enter_async_context(ClientSession(read, write, read_timeout_seconds=timedelta(seconds=25)))
                    await session.initialize()
                    log.info('upstream started on demand')
                    self.last_used = time.monotonic()
                    try:
                        while True:
                            if item is not None and not item[2].done():
                                owned.add(item[2])
                                item[2].add_done_callback(owned.discard)
                                task = asyncio.create_task(self._request(session, item))
                                active.add(task)
                                task.add_done_callback(active.discard)
                            item = None
                            timeout = self.idle_seconds if active else max(.01, self.idle_seconds - (time.monotonic() - self.last_used))
                            try:
                                item = await asyncio.wait_for(self.queue.get(), timeout=timeout)
                                if item is None:
                                    return
                            except TimeoutError:
                                if not active and time.monotonic() - self.last_used >= self.idle_seconds:
                                    log.info('upstream idle; releasing process')
                                    break
                    finally:
                        for task in active:
                            task.cancel()
                        await asyncio.gather(*active, return_exceptions=True)
            except Exception as exc:
                self.retry_at = time.monotonic() + 5
                error = RuntimeError(f'无法启动或连接上游服务：{type(exc).__name__}；请检查 Python、Node 和 npm ci')
                for future in owned:
                    if not future.done():
                        future.set_exception(error)
                # Requests queued during initialization share the same failure.
                while not self.queue.empty():
                    queued = self.queue.get_nowait()
                    if queued is None:
                        return
                    if not queued[2].done():
                        queued[2].set_exception(error)

    async def close(self):
        self.closed = True
        if self.worker is not None:
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)
        for future in list(self.pending):
            if not future.done():
                future.cancel()
