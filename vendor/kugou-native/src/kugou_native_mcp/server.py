"""KuGou-specific MCP: client bridge for music, native accessibility for modes."""
from __future__ import annotations
import json
import os
import threading
import urllib.request
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlparse
import websocket
from mcp.server.fastmcp import FastMCP
from pydantic import Field

ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get('KUGOU_CDP_PORT', '9225'))
LOCK = threading.RLock()
BRIDGE = (ROOT / 'bridge.js').read_text('utf-8')
mcp = FastMCP('kugou_mcp')

class Client:
    def __enter__(self):
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json/list',timeout=3) as response:
                targets=json.load(response)
            pages=[t for t in targets if t.get('type')=='page' and
                urlparse(t.get('url','')).hostname=='pc.service.kugou.com' and
                urlparse(t['url']).path.startswith(('/yueku/','/search/2024/'))]
            if not pages:raise RuntimeError('没有可用的官方酷狗页面，请打开客户端的推荐页')
            # Reuse the first verified official page; never attach to another app's browser.
            target=pages[0]
            wsurl=target['webSocketDebuggerUrl']
            parsed=urlparse(wsurl)
            if parsed.hostname!='127.0.0.1' or parsed.port!=PORT:
                raise RuntimeError('拒绝非本机的客户端连接')
            self.ws=websocket.create_connection(wsurl,timeout=25,suppress_origin=True)
            self.n=0
            self.evaluate(BRIDGE)
            return self
        except Exception as exc:
            if hasattr(self,'ws'):self.ws.close()
            raise RuntimeError('酷狗底层连接失败；请运行 kugou-mcp start。'+str(exc)) from exc
    def __exit__(self,*args):self.ws.close()
    def evaluate(self,expression):
        self.n+=1
        self.ws.send(json.dumps({'id':self.n,'method':'Runtime.evaluate','params':{
            'expression':expression,'returnByValue':True,'awaitPromise':True}}))
        while True:
            response=json.loads(self.ws.recv())
            if response.get('id')!=self.n:continue
            if 'error' in response:raise RuntimeError(str(response['error']))
            result=response['result']
            if 'exceptionDetails' in result:
                error=result['exceptionDetails']
                raise RuntimeError(error.get('exception',{}).get('description',error.get('text','客户端操作失败')))
            return result['result'].get('value')
    def invoke(self,method,*args):
        # Methods are internal constants. MCP clients cannot submit JavaScript.
        if method not in {'status','getDaily','search','playDaily','playSearch','control','getFavorites','playFavorites'}:
            raise ValueError('Unsupported method')
        return self.evaluate(f'window.__kugouNativeMcp.{method}('+','.join(json.dumps(a,ensure_ascii=True) for a in args)+')')

def invoke(method,*args):
    with LOCK,Client() as client:
        result=client.invoke(method,*args)
        return {'backend':'kugou_native_bridge_cdp',**result}

@mcp.tool(annotations={'readOnlyHint':True,'destructiveHint':False})
def kugou_get_playback() -> dict:
    """读取官方酷狗当前歌曲、播放状态及队列来源。停止状态不等于接口失败。"""
    return invoke('status')

@mcp.tool(annotations={'readOnlyHint':True,'destructiveHint':False})
def kugou_get_daily_recommendations() -> dict:
    """读取当前官方PC客户端账户的每日推荐，返回曲序和歌曲；不读取或导出账户凭据。"""
    return invoke('getDaily')

@mcp.tool(annotations={'readOnlyHint':True,'destructiveHint':False})
def kugou_search_music(keyword:Annotated[str,Field(min_length=1,max_length=100)],
                       limit:Annotated[int,Field(ge=1,le=15)]=5) -> dict:
    """在线搜索官方酷狗曲库，返回最多15个候选及result_id。选择准确歌手/版本后再播放。"""
    if not keyword.strip():raise ValueError('关键词不能为空')
    return invoke('search',keyword.strip(),limit)

@mcp.tool(annotations={'readOnlyHint':False,'destructiveHint':False})
def kugou_play_search_result(result_id:Annotated[str,Field(min_length=5,max_length=100)]) -> dict:
    """播放本次搜索返回的精确候选，替换临时播放队列；结果10分钟内有效。必须验证实际播放。"""
    return invoke('playSearch',result_id)

@mcp.tool(annotations={'readOnlyHint':False,'destructiveHint':False})
def kugou_play_daily_recommendations(start_index:Annotated[int,Field(ge=1,le=100)]=1) -> dict:
    """在官方客户端加载每日推荐并从指定曲序播放；替换临时队列，不改收藏。模式另用set_play_mode。"""
    return invoke('playDaily',start_index-1)

@mcp.tool(annotations={'readOnlyHint':True,'destructiveHint':False})
def kugou_get_favorites(
    collection_name:Annotated[str,Field(min_length=1,max_length=100)]='我喜欢',
    offset:Annotated[int,Field(ge=0)]=0,
    limit:Annotated[int,Field(ge=1,le=200)]=50,
) -> dict:
    """读取当前账户的收藏歌曲，默认“我喜欢”；可指定收藏歌单名称，按offset/limit分页。不导出账户凭据。"""
    if not collection_name.strip():raise ValueError('收藏歌单名称不能为空')
    return invoke('getFavorites',collection_name.strip(),offset,limit)

@mcp.tool(annotations={'readOnlyHint':False,'destructiveHint':False})
def kugou_play_favorites(
    collection_name:Annotated[str,Field(min_length=1,max_length=100)]='我喜欢',
    start_index:Annotated[int,Field(ge=1)]=1,
    mode:Literal['keep','order','list_loop','single_loop','shuffle']='keep',
) -> dict:
    """直接播放我的收藏，默认“我喜欢”第1首并保持现有模式；一调用完成读取、加载和实际播放验证。

    替换临时播放队列，不改收藏。可按歌单名称、曲序播放；mode为keep时不切换模式。
    """
    if not collection_name.strip():raise ValueError('收藏歌单名称不能为空')
    with LOCK:
        result=invoke('playFavorites',collection_name.strip(),start_index-1)
        mode_result=kugou_set_play_mode(mode) if mode!='keep' else None
        try:
            result['mode']=kugou_get_play_mode()
        except Exception:
            if mode!='keep':raise
            result['mode']={'verified':False,'error':'歌曲已验证播放，但当前模式暂时无法读取'}
        result['mode_changed']=bool(mode_result and mode_result.get('changed'))
        if mode!='keep' and result['mode']['mode']!=mode:raise RuntimeError('收藏已播放，但请求的播放模式未验证')
        return result

@mcp.tool(annotations={'readOnlyHint':False,'destructiveHint':False})
def kugou_control_playback(action:Literal['play','pause']) -> dict:
    """明确播放或暂停，调用客户端原生接口并读回验证。"""
    return invoke('control',action)

@mcp.tool(annotations={'readOnlyHint':True,'destructiveHint':False})
def kugou_get_play_mode() -> dict:
    """读取酷狗模式按钮的实际名称。此功能使用Windows可访问性接口，不调用Windows-MCP。"""
    from .mode_adapter import get_mode
    with LOCK:return get_mode()

@mcp.tool(annotations={'readOnlyHint':False,'destructiveHint':False})
def kugou_set_play_mode(mode:Literal['order','list_loop','single_loop','shuffle']) -> dict:
    """设置四种模式并读回验证。后备使用控件接口和定向窗口消息，非纯播放API；仅支持已验证客户端版本。"""
    from .mode_adapter import set_mode
    with LOCK:
        with Client() as client:
            version=client.evaluate('external.GetVersion()')
            if int(version)!=20022:raise RuntimeError('播放模式后备仅验证过酷狗20.0.22；当前版本不同，拒绝猜测菜单顺序')
        return set_mode(mode)

def main():
    mcp.run(transport='stdio')

if __name__=='__main__':main()
