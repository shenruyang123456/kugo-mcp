"""One MCP endpoint for KuGou Native and Meting-Agent."""
import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

ROOT = Path(__file__).resolve().parent
server = Server('kugo-mcp')
sessions = {}
tools_by_name = {}
SUPPORTED = {
    'kugou_get_playback', 'kugou_get_daily_recommendations',
    'kugou_play_daily_recommendations', 'kugou_get_favorites',
    'kugou_control_playback', 'kugou_get_play_mode',
    'platforms', 'search', 'song', 'album', 'artist', 'playlist', 'lyric', 'pic',
}


@server.list_tools()
async def list_tools():
    return list(tools_by_name.values()) + [types.Tool(
        name='kugo_get_current_cover',
        description='读取酷狗当前歌曲，并通过 Meting 查询其封面链接。',
        inputSchema={'type': 'object', 'properties': {}, 'additionalProperties': False},
        annotations=types.ToolAnnotations(readOnlyHint=True, destructiveHint=False),
    )]


@server.call_tool()
async def call_tool(name, arguments):
    if name == 'kugo_get_current_cover':
        status = await sessions['native'].call_tool('kugou_get_playback', {})
        if status.isError:
            return status
        playback = json.loads(status.content[0].text)
        song_id = playback.get('hash')
        if not song_id:
            raise ValueError('当前歌曲没有可用的酷狗标识')
        cover = await sessions['meting'].call_tool('pic', {'platform': 'kugou', 'id': song_id})
        if cover.isError:
            return cover
        data = json.loads(cover.content[0].text)
        if not data.get('ok'):
            return types.CallToolResult(content=cover.content, isError=True)
        return {'playback': playback, 'cover': data.get('data')}
    if name not in tools_by_name:
        raise ValueError(f'Unknown tool: {name}')
    owner = 'native' if name.startswith('kugou_') else 'meting'
    return await sessions[owner].call_tool(name, arguments)


async def main():
    native_env = dict(os.environ, PYTHONIOENCODING='utf-8')
    specs = {
        'native': StdioServerParameters(command=sys.executable, args=['-m', 'kugou_native_mcp', 'serve'], env=native_env),
        'meting': StdioServerParameters(command=os.environ.get('KUGOU_MCP_NODE', 'node'), args=[str(ROOT / 'node_modules' / '@eldment' / 'meting-agent' / 'src' / 'index.js')], env=dict(os.environ)),
    }
    async with AsyncExitStack() as stack:
        for owner, spec in specs.items():
            read, write = await stack.enter_async_context(stdio_client(spec))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            sessions[owner] = session
            for tool in (await session.list_tools()).tools:
                if tool.name not in SUPPORTED:
                    continue
                if tool.name in tools_by_name or tool.name == 'kugo_get_current_cover':
                    raise RuntimeError(f'Duplicate tool: {tool.name}')
                tools_by_name[tool.name] = tool
        missing = SUPPORTED - tools_by_name.keys()
        if missing:
            raise RuntimeError(f'Missing upstream tools: {sorted(missing)}')
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())


if __name__ == '__main__':
    asyncio.run(main())
