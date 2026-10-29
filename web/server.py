"""Local web bridge for the installed kugo-mcp service."""
import asyncio
import csv
import io
import json
import os
import socket
import subprocess
import sys
import threading
import time
from contextlib import AsyncExitStack
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import ProxyHandler, build_opener

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent
MCP_HOME = Path(os.environ.get('KUGO_MCP_HOME', str(ROOT.parent)))
PORT = 8765
state = {'mcp_connected': False, 'connected': False, 'startup_status': 'checking', 'message': '正在连接酷狗…', 'song': None, 'cover': '', 'lyrics': '', 'lyrics_status': '等待歌曲', 'position_ms': None, 'position_sampled_at': None, 'mode': '', 'recommendations': [], 'updated_at': None}
mutex = threading.Lock()
loop = asyncio.new_event_loop()
session = None
generation = 0
refresh_signal = None
reconnect_signal = None
daily_signal = None
pending_refresh = False
last_viewer = 0.0
client_ready = None
startup_task = None


def update(**values):
    with mutex:
        state.update(values)


async def call(name, arguments):
    if session is None:
        raise RuntimeError('酷狗服务尚未连接')
    try:
        result = await session.call_tool(name, arguments)
    except Exception:
        if reconnect_signal is not None:
            reconnect_signal.set()
        raise
    if result.isError:
        raise RuntimeError(result.content[0].text if result.content else '调用失败')
    if result.structuredContent is not None:
        return result.structuredContent
    return json.loads(result.content[0].text)


def update_song(song):
    with mutex:
        old_hash = (state.get('song') or {}).get('hash')
        new_hash = song.get('hash')
        if old_hash != new_hash:
            state.update(cover='', lyrics='', lyrics_status='正在加载歌词…', position_ms=None, position_sampled_at=None)
        state.update(song=song, connected=bool(song.get('available')), message='', updated_at=int(time.time() * 1000))


def update_if_current(song_hash, **values):
    with mutex:
        if (state.get('song') or {}).get('hash') == song_hash:
            state.update(values)


async def load_metadata(song_hash):
    try:
        pic = await call('pic', {'platform': 'kugou', 'id': song_hash})
        url = pic.get('data', {}).get('url', '')
        if url.startswith('http://imge.kugou.com/'):
            url = 'https://' + url[7:]
        update_if_current(song_hash, cover=url)
    except Exception as exc:
        print(f'Cover: {exc}', file=sys.stderr, flush=True)
    try:
        result = await call('lyric', {'platform': 'kugou', 'id': song_hash})
        if result.get('ok') is False:
            raise RuntimeError(result.get('message', '歌词接口不可用'))
        lyrics = (result.get('data') or {}).get('lyric') or ''
        update_if_current(song_hash, lyrics=lyrics, lyrics_status='' if lyrics else '暂无歌词')
    except Exception as exc:
        update_if_current(song_hash, lyrics='', lyrics_status='歌词暂时不可用')
        print(f'Lyrics: {exc}', file=sys.stderr, flush=True)


async def refresh_mode():
    while True:
        await client_ready.wait()
        try:
            mode = await call('kugou_get_play_mode', {})
            update(mode=mode.get('label', ''))
        except Exception as exc:
            print(f'mode: {exc}', file=sys.stderr, flush=True)
        await asyncio.sleep(30 if time.monotonic() - last_viewer < 30 else 120)


async def refresh_daily_on_request():
    while True:
        await daily_signal.wait()
        daily_signal.clear()
        await client_ready.wait()
        try:
            daily = await call('kugou_get_daily_recommendations', {})
            update(recommendations=daily.get('songs', []), daily_error='')
        except Exception as exc:
            update(daily_error='暂时无法读取每日推荐')
            print(f'daily: {exc}', file=sys.stderr, flush=True)


async def monitor_mcp():
    while True:
        try:
            await asyncio.wait_for(session.send_ping(), timeout=10)
        except Exception as exc:
            update(mcp_connected=False, connected=False, message='kugo-mcp 连接中断，正在重新连接…')
            print(f'MCP health: {exc}', file=sys.stderr, flush=True)
            reconnect_signal.set()
            return
        await asyncio.sleep(30)


def debug_available():
    port = int(os.environ.get('KUGOU_CDP_PORT', '9225'))
    try:
        with build_opener(ProxyHandler({})).open(f'http://127.0.0.1:{port}/json/list', timeout=2) as response:
            targets = json.load(response)
        return any(t.get('type') == 'page' and urlparse(t.get('url', '')).hostname == 'pc.service.kugou.com'
                   and urlparse(t.get('url', '')).path.startswith(('/yueku/', '/search/2024/')) for t in targets)
    except (OSError, ValueError):
        return False


def kugou_is_running():
    result = subprocess.run(['tasklist.exe', '/FI', 'IMAGENAME eq KuGou.exe', '/FO', 'CSV', '/NH'],
                            capture_output=True, text=True, timeout=8,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), check=True)
    return any(row and row[0].lower() == 'kugou.exe' for row in csv.reader(io.StringIO(result.stdout)))


async def ensure_kugou():
    try:
        update(startup_status='checking')
        if await asyncio.to_thread(debug_available):
            update(startup_status='ready')
            client_ready.set()
            refresh_signal.set()
            return
        if await asyncio.to_thread(kugou_is_running):
            client_ready.clear()
            update(startup_status='running_without_debug', connected=False,
                   message='酷狗已运行但无法连接。请完全退出酷狗后点击“重新连接”。')
            return
        client_ready.clear()
        update(startup_status='starting', connected=False, message='正在启动酷狗，请稍候…')
        proc = await asyncio.create_subprocess_exec(
            sys.executable, '-m', 'kugou_native_mcp', 'start', '--port', os.environ.get('KUGOU_CDP_PORT', '9225'),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            _, err = await asyncio.wait_for(proc.communicate(), timeout=100)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise RuntimeError('酷狗启动连接超时')
        if proc.returncode != 0:
            raise RuntimeError(err.decode('utf-8', errors='replace').strip() or '酷狗启动失败')
        update(startup_status='ready')
        client_ready.set()
        refresh_signal.set()
    except Exception as exc:
        client_ready.clear()
        update(startup_status='error', connected=False, message='无法自动启动酷狗，请确认客户端已安装后重试')
        print(f'KuGou startup: {exc}', file=sys.stderr, flush=True)


def schedule_startup():
    global startup_task
    if startup_task is None or startup_task.done():
        startup_task = asyncio.create_task(ensure_kugou())


def read_snapshot():
    # Read song, state and position in one invocation of the native bridge.
    from kugou_native_mcp.server import Client
    expression = """new Promise((resolve,reject)=>{const n='__kugoSnapshot'+Math.random().toString(36).slice(2);const t=setTimeout(()=>{delete window[n];reject(Error('status timeout'))},8000);window[n]=x=>{clearTimeout(t);delete window[n];try{const a=typeof x==='string'?JSON.parse(x):x;let source=null;try{source=JSON.parse(a.QueueSource||'{}').WebInfo}catch(_){};resolve({available:String(a.status)==='1',title:a.filename||'',hash:a.hash||'',mixsongid:a.mix_song_id||'',playback:a.play_status||'stopped',duration_ms:Number(a.duration||0),source:source?.type||'',source_name:source?.info?.name||'',progress:a.progress})}catch(e){reject(e)}};try{external.SuperCall(864,JSON.stringify({callback:n}))}catch(e){clearTimeout(t);delete window[n];reject(e)}})"""
    with Client() as client:
        raw = client.evaluate(expression)
    try:
        pos = int(raw.pop('progress')) / 10000
        duration = raw['duration_ms']
        position = min(pos, duration) if duration > 0 and 0 <= pos <= duration + 1000 else None
    except (KeyError, TypeError, ValueError):
        position = None
    return raw, position


async def refresh():
    last_hash = None
    metadata_task = None
    next_retry = 0
    failures = 0
    while True:
        if not client_ready.is_set():
            await client_ready.wait()
        try:
            request_generation = generation
            current, position = await asyncio.to_thread(read_snapshot)
            if request_generation != generation:
                continue
            failures = 0
            if not current.get('available'):
                update(connected=False, message='酷狗当前没有可用歌曲', song=current)
            else:
                update_song(current)
                song_hash = current.get('hash')
                update_if_current(song_hash, position_ms=position, position_sampled_at=int(time.time() * 1000) if position is not None else None)
                if song_hash != last_hash:
                    last_hash = song_hash
                    next_retry = 0
                if song_hash and time.monotonic() >= next_retry and (metadata_task is None or metadata_task.done()):
                    with mutex:
                        needs_metadata = not state['cover'] or state['lyrics_status'] == '歌词暂时不可用'
                    if needs_metadata:
                        next_retry = time.monotonic() + 30
                        metadata_task = asyncio.create_task(load_metadata(song_hash))
        except Exception as exc:
            failures += 1
            update(connected=False, message='无法读取酷狗，请确认客户端已通过 MCP 启动并打开推荐页')
            print(f'KuGou refresh: {exc}', file=sys.stderr, flush=True)
        try:
            delay = min(5 * (2 ** min(failures - 1, 3)), 30) if failures else (2.5 if time.monotonic() - last_viewer < 30 else 20)
            await asyncio.wait_for(refresh_signal.wait(), timeout=delay)
            refresh_signal.clear()
        except asyncio.TimeoutError:
            pass


async def perform(name, args):
    global generation
    generation += 1
    try:
        result = await call(name, args)
        if result.get('actual'):
            update_song(result['actual'])
        return result
    finally:
        generation += 1
        refresh_signal.set()


def request_refresh():
    global generation, pending_refresh
    generation += 1
    update(connected=False, message='正在重新读取酷狗…', position_ms=None, position_sampled_at=None, recommendations=[], daily_error='')
    if refresh_signal is not None:
        refresh_signal.set()
    if daily_signal is not None:
        daily_signal.set()
    else:
        pending_refresh = True
    if session is not None:
        schedule_startup()


async def bridge():
    global session, refresh_signal, reconnect_signal, daily_signal, pending_refresh, client_ready
    refresh_signal = asyncio.Event()
    reconnect_signal = asyncio.Event()
    daily_signal = asyncio.Event()
    client_ready = asyncio.Event()
    if pending_refresh:
        daily_signal.set()
        pending_refresh = False
    while True:
        try:
            params = StdioServerParameters(
                command=sys.executable,
                args=[str(MCP_HOME / 'server.py')], env=dict(os.environ, PYTHONIOENCODING='utf-8'))
            async with AsyncExitStack() as stack:
                read, write = await stack.enter_async_context(stdio_client(params))
                session = await stack.enter_async_context(ClientSession(read, write, read_timeout_seconds=timedelta(seconds=45)))
                await session.initialize()
                update(mcp_connected=True)
                schedule_startup()
                async with asyncio.TaskGroup() as tasks:
                    reconnect_signal.clear()
                    workers = [tasks.create_task(refresh_mode()), tasks.create_task(refresh_daily_on_request()), tasks.create_task(refresh()), tasks.create_task(monitor_mcp())]
                    await reconnect_signal.wait()
                    for worker in workers:
                        worker.cancel()
        except Exception as exc:
            session = None
            update(mcp_connected=False, connected=False, message='无法连接 kugo-mcp，请检查安装及酷狗客户端')
            print(f'MCP connection: {exc}', file=sys.stderr, flush=True)
            await asyncio.sleep(5)


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def valid_host(self):
        return self.headers.get('Host', '') in (f'127.0.0.1:{PORT}', f'localhost:{PORT}')

    def do_GET(self):
        global last_viewer
        if not self.valid_host():
            return self.send_error(403)
        path = urlparse(self.path).path
        if path == '/api/state':
            last_viewer = time.monotonic()
            with mutex:
                snapshot = dict(state)
            return self.send_json(200, snapshot)
        assets = {'/': ('index.html', 'text/html; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8')}
        if path not in assets:
            return self.send_error(404)
        filename, kind = assets[path]
        data = (ROOT / filename).read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if not self.valid_host() or self.headers.get('Origin') not in (f'http://127.0.0.1:{PORT}', f'http://localhost:{PORT}'):
            return self.send_error(403)
        if self.path not in ('/api/control', '/api/play-recommendation', '/api/refresh') or self.headers.get('Content-Type') != 'application/json':
            return self.send_error(404)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 256:
                raise ValueError('无效请求')
            body = json.loads(self.rfile.read(length))
            if self.path == '/api/refresh':
                loop.call_soon_threadsafe(request_refresh)
                return self.send_json(202, {'accepted': True})
            if self.path == '/api/control':
                action = body.get('action')
                if action not in ('play', 'pause'):
                    raise ValueError('不支持此操作')
                name, args = 'kugou_control_playback', {'action': action}
            else:
                index = body.get('index')
                with mutex:
                    rows = state.get('recommendations') or []
                    valid = type(index) is int and 1 <= index <= len(rows) and rows[index - 1].get('hash') == body.get('hash')
                if not valid:
                    raise ValueError('推荐列表已更新，请重试')
                name, args = 'kugou_play_daily_recommendations', {'start_index': index}
            future = asyncio.run_coroutine_threadsafe(perform(name, args), loop)
            result = future.result(timeout=45)
            self.send_json(200, result)
        except Exception as exc:
            self.send_json(503, {'error': '操作未能确认，请查看酷狗当前状态'})
            print(f'Playback control: {exc}', file=sys.stderr, flush=True)


def run_loop():
    asyncio.set_event_loop(loop)
    loop.run_until_complete(bridge())


class LocalServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


if __name__ == '__main__':
    with LocalServer(('127.0.0.1', PORT), Handler) as httpd:
        threading.Thread(target=run_loop, daemon=True).start()
        print(f'酷狗播放器：http://127.0.0.1:{PORT}', flush=True)
        httpd.serve_forever()
