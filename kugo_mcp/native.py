"""One persistent, bounded CDP connection for this MCP server; never retries commands."""
import json
import logging
import math
import os
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import ProxyHandler, build_opener

import websocket

BRIDGE = Path(__file__).with_name('bridge.js').read_text('utf-8')
log = logging.getLogger('kugou')


class NativeClient:
    def __init__(self):
        self.port = int(os.environ.get('KUGOU_CDP_PORT', '9225'))
        self.ws = None
        self.serial = 0
        self.lock = threading.Lock()
        self.job = None
        self.result = None
        self.phase = 'idle'

    def close(self):
        ws, self.ws = self.ws, None
        if ws is not None:
            # Close the transport without waiting for an unresponsive renderer.
            ws.shutdown()

    def _receive(self, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('酷狗响应超时')
        self.ws.settimeout(remaining)
        message = json.loads(self.ws.recv())
        if message.get('method') == 'Runtime.bindingCalled':
            params = message.get('params', {})
            if params.get('name') == '__kugoMcpResult':
                payload = json.loads(params['payload'])
                if payload.get('id') == self.job:
                    self.result = payload
        return message

    def _rpc(self, method, params, deadline):
        self.serial += 1
        request_id = self.serial
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('酷狗请求已过期')
        self.ws.settimeout(remaining)
        self.ws.send(json.dumps({'id': request_id, 'method': method, 'params': params}))
        while True:
            message = self._receive(deadline)
            if message.get('id') != request_id:
                continue
            if 'error' in message:
                raise RuntimeError('酷狗调试接口不可用')
            result = message['result']
            if 'exceptionDetails' in result:
                raise RuntimeError('酷狗页面忙或已变化，稍后自动重试')
            return result

    def _evaluate(self, expression, deadline):
        return self._rpc('Runtime.evaluate', {
            'expression': expression, 'returnByValue': True, 'awaitPromise': False
        }, deadline).get('result', {}).get('value')

    def _connect(self, deadline):
        if self.ws is not None:
            return
        self.phase = 'discover'
        with build_opener(ProxyHandler({})).open(
                f'http://127.0.0.1:{self.port}/json/list', timeout=min(2, max(.01, deadline - time.monotonic()))) as response:
            targets = json.load(response)
        pages = [t for t in targets if t.get('type') == 'page'
                 and urlparse(t.get('url', '')).hostname == 'pc.service.kugou.com'
                 and urlparse(t.get('url', '')).path.startswith(('/yueku/', '/search/2024/'))]
        if not pages:
            raise RuntimeError('请打开酷狗的推荐页以建立连接')
        url = pages[0]['webSocketDebuggerUrl']
        parsed = urlparse(url)
        if parsed.scheme != 'ws' or parsed.hostname != '127.0.0.1' or parsed.port != self.port or parsed.username:
            raise RuntimeError('拒绝非本机酷狗连接')
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('酷狗连接已过期')
        self.phase = 'connect'
        self.ws = websocket.create_connection(url, timeout=min(3, remaining), suppress_origin=True, http_no_proxy=['127.0.0.1'])
        self.phase = 'page_ready'
        ready = self._evaluate("document.readyState === 'complete' && !!document.body", deadline)
        if ready is not True:
            raise RuntimeError('酷狗页面尚未加载完成')
        self.phase = 'binding'
        self._rpc('Runtime.addBinding', {'name': '__kugoMcpResult'}, deadline)
        self.phase = 'install'
        self._evaluate(BRIDGE, deadline)
        log.info('native connected')

    def request(self, action, expires_at=None):
        if action not in ('snapshot', 'play', 'pause', 'next', 'prev'):
            raise ValueError('不支持的操作')
        if not self.lock.acquire(blocking=False):
            raise RuntimeError('酷狗正在处理上一请求')
        started = time.monotonic()
        deadline = min(started + 12, expires_at) if expires_at is not None else started + 12
        self.job, self.result = uuid.uuid4().hex, None
        try:
            self._connect(deadline)
            self.phase = action
            # Page deadline protects against delayed execution even if CDP disconnects.
            expires_ms = int((time.time() + max(0, deadline - time.monotonic())) * 1000)
            expression = 'window.__kugoMcpBridge.begin(' + ','.join(json.dumps(v) for v in (self.job, action, expires_ms)) + ')'
            self._evaluate(expression, deadline)
            while self.result is None:
                self._receive(deadline)
            if self.result.get('error'):
                raise RuntimeError(self.result['error'])
            return self.result['result']
        except Exception:
            self.close()
            log.warning('native %s failed phase=%s after %.2fs', action, self.phase, time.monotonic() - started)
            raise
        finally:
            elapsed = time.monotonic() - started
            if action != 'snapshot' or elapsed > 1:
                log.info('native %s %.2fs', action, elapsed)
            self.job, self.result = None, None
            self.lock.release()

    def snapshot(self):
        raw = self.request('snapshot')
        try:
            pos = int(raw.pop('progress')) / 10000
            duration = raw['duration_ms']
            position = min(pos, duration) if math.isfinite(duration) and duration > 0 and 0 <= pos <= duration + 1000 else None
        except (KeyError, TypeError, ValueError, OverflowError):
            position = None
        return raw, position
