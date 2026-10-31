"""kugo-mcp 1.1 entry point. Diagnostics go to stderr; stdout is MCP only."""
import argparse
import asyncio
import json
import logging
from contextlib import asynccontextmanager

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from kugo_mcp import __version__
from kugo_mcp.service import Service, schemas

service = None


@asynccontextmanager
async def lifespan(_server):
    global service
    service = Service()
    try:
        yield service
    finally:
        await service.close()
        service = None


server = Server('kugo-mcp', version=__version__, lifespan=lifespan)


@server.list_tools()
async def list_tools():
    return list(schemas().values())


@server.call_tool()
async def call_tool(name, arguments):
    if service is None:
        raise RuntimeError('服务尚未启动')
    try:
        return await service.call(name, arguments or {})
    except (RuntimeError, ValueError, OSError) as exc:
        return types.CallToolResult(isError=True, content=[types.TextContent(type='text', text=str(exc))])


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def cli():
    parser = argparse.ArgumentParser(description='kugo-mcp：轻量酷狗播放与音乐资料 MCP')
    parser.add_argument('--version', action='version', version=__version__)
    parser.add_argument('command', choices=['serve', 'start', 'doctor'], nargs='?', default='serve')
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    if args.command == 'serve':
        asyncio.run(main())
    else:
        from kugo_mcp.connection import connect
        from kugo_mcp.native import NativeClient
        try:
            result = asyncio.run(connect(NativeClient().port, args.command == 'start'))
            print(json.dumps(dict(result, version=__version__), ensure_ascii=False))
        except (RuntimeError, OSError) as exc:
            parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    cli()
