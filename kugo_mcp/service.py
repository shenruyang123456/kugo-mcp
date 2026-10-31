"""Public MCP tools; startup and tool discovery have no client side effects."""
import json
import os
import sys
from pathlib import Path

from mcp import StdioServerParameters, types

from . import __version__
from .connection import connect
from .metadata import Metadata
from .playback import Playback
from .upstream import LazyMcp

ROOT = Path(__file__).resolve().parent.parent
LEGACY = {'kugou_get_daily_recommendations', 'kugou_play_daily_recommendations',
          'kugou_get_favorites', 'kugou_get_play_mode'}
METING = {'platforms', 'search', 'song', 'album', 'artist', 'playlist', 'lyric', 'pic'}


def schemas():
    tools = {t['name']: types.Tool.model_validate(t) for t in json.loads(Path(__file__).with_name('tool_schemas.json').read_text('utf-8'))}
    tools['kugou_control_playback'].inputSchema['properties']['action']['enum'] = ['play', 'pause', 'next', 'prev']
    tools['kugou_control_playback'].description = '播放、暂停、上一首或下一首；只发送一次，约600毫秒后读回确认。verified=false时不要自动重发。'
    tools['kugou_control_playback'].annotations = types.ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
    descriptions = {
        'kugo_get_current_cover': '按当前歌曲真实hash读取封面地址；共用4.4秒状态缓存，不搜索歌曲名。',
        'kugo_get_current_lyrics': '读取当前歌曲LRC、当前歌词和同步状态；可选择返回时间轴。',
        'kugo_get_current_track': '一次获取当前歌曲、歌手、封面、歌词、当前歌词与进度；优先使用此工具减少重复查询。',
        'kugo_get_current_progress': '读取采样进度、本地推算进度、总时长和过期状态；不启动Meting。',
        'kugo_connect': '启动或复用酷狗。新启动后静置3秒并等窗口就绪，不结束已有酷狗，不循环重启。',
    }
    for name, description in descriptions.items():
        properties = {}
        if name in ('kugo_get_current_lyrics', 'kugo_get_current_track'):
            properties['include_lines'] = {'type': 'boolean', 'default': False, 'description': '是否包含完整歌词时间轴'}
        if name == 'kugo_connect':
            properties['start_if_needed'] = {'type': 'boolean', 'default': True}
        tools[name] = types.Tool(name=name, description=description,
            inputSchema={'type': 'object', 'properties': properties, 'additionalProperties': False},
            annotations=types.ToolAnnotations(readOnlyHint=name != 'kugo_connect', destructiveHint=False,
                                             openWorldHint=name not in ('kugo_connect', 'kugo_get_current_progress')))
    return tools


class Service:
    def __init__(self, root=None, playback=None):
        self.root = Path(root or os.environ.get('KUGO_MCP_HOME', ROOT))
        self.playback = playback or Playback()
        self.meting = LazyMcp(self._meting_params)
        self.legacy = LazyMcp(self._legacy_params)
        self.metadata = Metadata(self.meting)
        self.tools = schemas()

    def _meting_params(self):
        node = os.environ.get('KUGOU_MCP_NODE') or (str(self.root / 'node/node.exe') if (self.root / 'node/node.exe').is_file() else 'node')
        entry = self.root / 'node_modules/@eldment/meting-agent/src/index.js'
        if not entry.is_file():
            entry = self.root / 'meting/node_modules/@eldment/meting-agent/src/index.js'
        if not entry.is_file():
            raise RuntimeError('找不到 Meting-Agent；请在仓库运行 npm ci')
        return StdioServerParameters(command=node, args=[str(entry)], env=dict(os.environ))

    def _legacy_params(self):
        env = dict(os.environ, PYTHONIOENCODING='utf-8')
        vendor = ROOT / 'vendor/kugou-native/src'
        env['PYTHONPATH'] = str(vendor) + (os.pathsep + env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
        return StdioServerParameters(command=sys.executable, args=['-m', 'kugou_native_mcp', 'serve'], env=env)

    async def call(self, name, arguments):
        if name not in self.tools:
            raise ValueError(f'Unknown tool: {name}')
        if name == 'kugo_connect':
            async with self.playback.lock:
                result = await connect(self.playback.native.port, arguments.get('start_if_needed', True))
                self.playback.error = None
                self.playback.failures = 0
                self.playback.next_sample_at = 0
                return dict(result, version=__version__)
        if name in METING:
            return await self.meting.call(name, arguments)
        if name in LEGACY:
            return await self.playback.legacy(self.legacy, name, arguments)
        if name == 'kugou_control_playback':
            return await self.playback.control(arguments['action'])
        playback = await self.playback.read()
        if name == 'kugou_get_playback':
            return playback
        if name == 'kugo_get_current_progress':
            return {key: playback[key] for key in ('hash', 'playback', 'position_ms', 'position_sampled_at',
                                                  'elapsed_ms', 'duration_ms', 'progress_ratio', 'stale')}
        song_hash = playback.get('hash')
        if not song_hash:
            raise RuntimeError('当前歌曲没有可用的酷狗标识')
        fields = ('cover',) if name == 'kugo_get_current_cover' else ('lyrics',) if name == 'kugo_get_current_lyrics' else ('cover', 'lyrics')
        entry = await self.metadata.get(song_hash, fields)
        changed = (self.playback.cached or {}).get('hash') != song_hash
        if not changed:
            playback = self.playback._view()
        data = self.metadata.view(entry, playback, arguments.get('include_lines', False))
        if name == 'kugo_get_current_cover':
            data.pop('lyrics')
            if data['errors'].get('cover'):
                return types.CallToolResult(isError=True,
                    content=[types.TextContent(type='text', text=data['errors']['cover'])],
                    structuredContent={'playback': playback, **data})
        elif name == 'kugo_get_current_lyrics':
            data.pop('cover')
        return {'playback': playback, 'track_changed': changed, **data}

    async def close(self):
        self.playback.close()
        await self.metadata.close()
        await self.meting.close()
        await self.legacy.close()
