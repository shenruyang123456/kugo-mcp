"""Explicit startup with a quiet period; never kill or repeatedly relaunch KuGou."""
import asyncio
import csv
import io
import json
import socket
import subprocess
import time
from urllib.parse import urlparse
from urllib.request import ProxyHandler, build_opener

from .process import client_ui_ready


def debug_available(port):
    try:
        with build_opener(ProxyHandler({})).open(f'http://127.0.0.1:{port}/json/list', timeout=2) as response:
            targets = json.load(response)
        return any(t.get('type') == 'page' and urlparse(t.get('url', '')).hostname == 'pc.service.kugou.com'
                   and urlparse(t.get('url', '')).path.startswith(('/yueku/', '/search/2024/')) for t in targets)
    except (OSError, ValueError, TypeError):
        return False


def is_running():
    result = subprocess.run(['tasklist.exe', '/FI', 'IMAGENAME eq KuGou.exe', '/FO', 'CSV', '/NH'],
                            capture_output=True, text=True, timeout=3, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return any(row and row[0].lower() == 'kugou.exe' for row in csv.reader(io.StringIO(result.stdout)))


def port_open(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=.3):
            return True
    except OSError:
        return False


async def connect(port, start_if_needed=True):
    from kugou_native_mcp.installation import find_executable
    launched = False
    debugging = await asyncio.to_thread(debug_available, port)
    running = await asyncio.to_thread(is_running)
    if not debugging and not running:
        if await asyncio.to_thread(port_open, port):
            raise RuntimeError('调试端口被其他程序占用；请设置其他 KUGOU_CDP_PORT，不会结束占用者')
        if not start_if_needed:
            raise RuntimeError('酷狗尚未启动；可调用 kugo_connect 或先运行 start')
        executable = await asyncio.to_thread(find_executable)
        await asyncio.to_thread(subprocess.Popen,
            [str(executable), f'--remote_debug_port={port}', '--remote-debugging-address=127.0.0.1'],
            cwd=str(executable.parent), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        launched = True
        await asyncio.sleep(3)  # No port, window, CDP or native probes during startup.
    elif not debugging:
        raise RuntimeError('酷狗已普通启动，未发现调试页面；请完全退出后再调用 kugo_connect，不会强制结束酷狗')
    stable = 0
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        ready = await asyncio.to_thread(client_ui_ready)
        ready = ready and await asyncio.to_thread(debug_available, port)
        stable = stable + 1 if ready else 0
        if stable >= (3 if launched else 1):
            return {'ready': True, 'launched': launched, 'debug_port': port}
        await asyncio.sleep(2)
    raise RuntimeError('酷狗仍未就绪；请求已停止，不会循环重启客户端。请检查窗口响应并打开推荐页')
