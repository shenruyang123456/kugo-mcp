"""Transactional, narrowly scoped Codex MCP configuration registration."""
import json
import os
import sys
import time
import tomllib
from pathlib import Path

BEGIN='# BEGIN kugou-native-mcp managed'
END='# END kugou-native-mcp managed'
TOOLS=['kugou_get_playback','kugou_get_daily_recommendations','kugou_search_music',
       'kugou_play_search_result','kugou_play_daily_recommendations','kugou_control_playback',
       'kugou_get_play_mode','kugou_set_play_mode','kugou_get_favorites','kugou_play_favorites']

def config_path():
    return Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))/'config.toml'

def make_block(python=None,port=9225,exe=None):
    python=str(Path(python or sys.executable).resolve()).replace('\\','/')
    quote=lambda value:json.dumps(value,ensure_ascii=False)
    lines=[BEGIN,'[mcp_servers.kugou-native]',f'command = {quote(python)}',
        'args = ["-m", "kugou_native_mcp", "serve"]','startup_timeout_sec = 30.0',
        'tool_timeout_sec = 40.0','default_tools_approval_mode = "prompt"',
        'enabled_tools = '+quote(TOOLS),'','[mcp_servers.kugou-native.env]',
        f'KUGOU_CDP_PORT = "{port}"','PYTHONIOENCODING = "utf-8"']
    if exe:lines.append('KUGOU_EXE_PATH = '+quote(str(Path(exe).resolve()).replace('\\','/')))
    return '\n'.join(lines+[END])

def _save(path,old,new):
    path.parent.mkdir(parents=True,exist_ok=True)
    if old:
        backup=path.with_name(path.name+f'.backup-{time.time_ns()}')
        backup.write_text(old,encoding='utf-8')
    temporary=path.with_name(path.name+f'.kugou-{time.time_ns()}.tmp')
    temporary.write_text(new,encoding='utf-8')
    temporary.replace(path)

def install(path=None,python=None,port=9225,exe=None):
    path=Path(path or config_path())
    old=path.read_text('utf-8') if path.exists() else ''
    before=tomllib.loads(old)
    if 'kugou-native' in before.get('mcp_servers',{}):
        raise RuntimeError('已有 kugou-native 配置，未修改；请先回退旧接入或手动合并')
    new=old.rstrip()+'\n\n'+make_block(python,port,exe)+'\n'
    after=tomllib.loads(new)
    after['mcp_servers'].pop('kugou-native')
    if not after['mcp_servers'] and 'mcp_servers' not in before:after.pop('mcp_servers')
    if after!=before:raise RuntimeError('检测到无关配置变化，拒绝写入')
    _save(path,old,new)
    return {'status':'installed','config':str(path),'tools':len(TOOLS),'restart_codex':True}

def uninstall(path=None):
    path=Path(path or config_path());old=path.read_text('utf-8')
    if old.count(BEGIN)!=1 or old.count(END)!=1:raise RuntimeError('没有唯一的受管理配置块，未修改')
    start=old.index(BEGIN);stop=old.index(END)+len(END)
    before=tomllib.loads(old)
    block=tomllib.loads(old[start+len(BEGIN):stop-len(END)])
    if set(block)!={'mcp_servers'} or set(block['mcp_servers'])!={'kugou-native'}:
        raise RuntimeError('管理区块包含其他配置，未修改')
    if before.get('mcp_servers',{}).get('kugou-native')!=block['mcp_servers']['kugou-native']:
        raise RuntimeError('管理区块与实际配置不一致，未修改')
    new=old[:start]+old[stop:]
    after=tomllib.loads(new);before['mcp_servers'].pop('kugou-native')
    if not before['mcp_servers'] and 'mcp_servers' not in after:before.pop('mcp_servers')
    if after!=before:raise RuntimeError('检测到无关配置变化，拒绝写入')
    _save(path,old,new)
    return {'status':'uninstalled','config':str(path),'restart_codex':True}
