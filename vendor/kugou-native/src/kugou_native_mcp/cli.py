import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlparse
from . import __version__

def check_port(port):
    if not 1024<=port<=65535:raise ValueError('端口必须为 1024–65535')
    return port

def doctor(port):
    with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list',timeout=3) as response:
        targets=json.load(response)
    targets=[t for t in targets if t.get('type')=='page' and
        urlparse(t.get('url','')).hostname=='pc.service.kugou.com' and
        urlparse(t['url']).path.startswith(('/yueku/','/search/2024/'))]
    if not targets:raise RuntimeError('没有官方酷狗页面；请在客户端打开推荐页')
    os.environ['KUGOU_CDP_PORT']=str(port)
    from .server import Client
    with Client() as client:version=client.evaluate('external.GetVersion()')
    return {'connected':True,'host':'127.0.0.1','port':port,'client_version':version,
        'mode_adapter_verified_version':20022,'mcp_version':__version__}

def start(port,exe=None):
    from .installation import find_executable
    try:return doctor(port)
    except (OSError,RuntimeError):pass
    client=find_executable(exe)
    subprocess.Popen([str(client),f'--remote_debug_port={port}','--remote-debugging-address=127.0.0.1'],cwd=client.parent)
    for attempt in range(25):
        time.sleep(.3)
        try:return doctor(port)
        except (OSError,RuntimeError):pass
    raise RuntimeError('连接未开启。如果酷狗已正常运行，请先关闭它，再执行 start；不会自动停止正在播放的客户端。')

def main():
    parser=argparse.ArgumentParser(description='官方酷狗 Windows 客户端的本地 MCP 适配器')
    parser.add_argument('--version',action='version',version=__version__)
    sub=parser.add_subparsers(dest='command')
    sub.add_parser('serve',help='运行 MCP stdio 服务（默认）')
    for name in ('start','doctor','install-codex'):
        p=sub.add_parser(name,help={'start':'打开本地酷狗连接','doctor':'核实客户端接口','install-codex':'添加 Codex MCP 配置'}[name])
        p.add_argument('--port',type=int,default=int(os.environ.get('KUGOU_CDP_PORT','9225')))
        if name!='doctor':p.add_argument('--exe',help='已安装的 KuGou.exe 路径')
    sub.add_parser('uninstall-codex',help='仅移除本包创建的配置区块')
    args=parser.parse_args()
    try:
        if args.command in (None,'serve'):
            if sys.platform!='win32':raise RuntimeError('客户端控制仅支持 Windows')
            from .server import main as serve
            serve();return
        if args.command in ('doctor','start','install-codex'):check_port(args.port)
        if args.command=='doctor':result=doctor(args.port)
        elif args.command=='start':result=start(args.port,args.exe)
        elif args.command=='install-codex':
            from .configuration import install
            result=install(port=args.port,exe=args.exe)
        else:
            from .configuration import uninstall
            result=uninstall()
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (OSError,RuntimeError,ValueError) as exc:
        parser.exit(1,f'{exc}\n')
