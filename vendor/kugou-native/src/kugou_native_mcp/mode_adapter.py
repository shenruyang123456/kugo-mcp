"""Narrow native accessibility adapter: only four KuGou playback modes.

No Windows-MCP process, screenshots, coordinates, SendInput or general UI tools.
Menu navigation is sent only to the verified KuGou-owned playback-mode popup.
"""
import ctypes
import subprocess
import sys
from pathlib import Path
import time
import uiautomation as auto
from kugou_native_mcp.installation import is_client_path

MODES={'order':'顺序播放','list_loop':'列表循环','single_loop':'单曲循环','shuffle':'随机播放'}

def _path(pid):
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.restype=ctypes.c_void_p
    kernel.QueryFullProcessImageNameW.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_wchar_p,ctypes.POINTER(ctypes.c_uint32)]
    kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    handle=kernel.OpenProcess(0x1000,False,pid)
    if not handle:return ''
    try:
        size=ctypes.c_uint32(32768);buffer=ctypes.create_unicode_buffer(size.value)
        if not kernel.QueryFullProcessImageNameW(handle,0,buffer,ctypes.byref(size)):return ''
        return buffer.value
    finally:kernel.CloseHandle(handle)

def _handles(pid=None):
    user=ctypes.WinDLL('user32',use_last_error=True)
    user.IsWindowVisible.argtypes=[ctypes.c_void_p]
    user.GetWindowTextW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_int]
    user.GetWindowThreadProcessId.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint32)]
    result=[]
    callback_type=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)
    def visit(handle,_):
        if not user.IsWindowVisible(handle):return True
        process_id=ctypes.c_uint32();user.GetWindowThreadProcessId(handle,ctypes.byref(process_id))
        if pid is not None and process_id.value!=pid:return True
        name=ctypes.create_unicode_buffer(1024);user.GetWindowTextW(handle,name,1024)
        result.append((handle,process_id.value,name.value))
        return True
    callback=callback_type(visit)
    user.EnumWindows.argtypes=[callback_type,ctypes.c_void_p]
    user.EnumWindows(callback,None)
    return result

def _window():
    windows=[]
    for handle,pid,title in _handles():
        if '酷狗音乐' not in title or '桌面歌词' in title:continue
        path=_path(pid).lower()
        if is_client_path(path):windows.append(auto.ControlFromHandle(handle))
    if len(windows)!=1:raise RuntimeError('官方酷狗主窗口不是唯一可识别窗口，拒绝操作')
    return windows[0]

def _button(window):
    # Native controls sit directly inside the window's custom root, beside the web tab.
    controls=[]
    pending=[(window,0)]
    while pending:
        parent,depth=pending.pop()
        if depth>=6:continue
        for c in parent.GetChildren():
            kind=c.ControlType
            if kind==auto.ControlType.ButtonControl and c.Name in MODES.values():controls.append(c)
            if kind not in (auto.ControlType.TabControl,auto.ControlType.DocumentControl,
                            auto.ControlType.ButtonControl,auto.ControlType.ImageControl):
                pending.append((c,depth+1))
    if len(controls)!=1:raise RuntimeError('无法唯一读取酷狗模式按钮')
    return controls[0]

def _invoke(control):
    legacy=control.GetLegacyIAccessiblePattern()
    if legacy:legacy.DoDefaultAction();return
    pattern=control.GetInvokePattern()
    if pattern:pattern.Invoke();return
    raise RuntimeError('控件未提供可调用接口；拒绝坐标点击后备')

def get_mode():
    with auto.UIAutomationInitializerInThread():
        for attempt in range(4):
            try:
                name=_button(_window()).Name
                return {'backend':'windows_accessibility_control','verified':True,
                        'mode':next(k for k,v in MODES.items() if v==name),'label':name}
            except Exception:
                if attempt==3:raise
                # Loading a new native queue briefly replaces accessible objects.
                # Always reacquire the current window/control instead of reusing it.
                time.sleep(.25)

def set_mode(mode):
    if mode not in MODES:raise ValueError('Unsupported playback mode')
    with auto.UIAutomationInitializerInThread():
        for attempt in range(4):
            try:
                window=_window();current=_button(window)
                before=current.Name
                process_id=window.ProcessId
                main_handle=window.NativeWindowHandle
                break
            except Exception:
                if attempt==3:raise
                time.sleep(.25)
        if before==MODES[mode]:return {'backend':'windows_accessibility_control',
            'verified':True,'mode':mode,'label':before,'changed':False}
        # KuGou's menu-open call waits for its modal popup to close. Dispatch that
        # one invocation in a hidden helper process with an independent COM client.
        if not any(title=='播放模式' for _,_,title in _handles(process_id)):
            opener=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),
                '--open-only',str(main_handle),str(process_id)],
                stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW)
        else:opener=None
        selected=False
        for attempt in range(30):
            time.sleep(.1)
            menus=[h for h,p,t in _handles(process_id) if t=='播放模式']
            if len(menus)==1:
                # The 20.0.22 native popup blocks accessibility queries while its
                # modal invocation is active. Send only navigation messages to
                # this verified owned popup, then independently read the button.
                user=ctypes.WinDLL('user32',use_last_error=True)
                user.PostMessageW.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_size_t,ctypes.c_ssize_t]
                index={'order':0,'list_loop':1,'shuffle':2,'single_loop':3}[mode]
                for key in [0x24]+[0x28]*index+[0x0D]:
                    if not user.PostMessageW(menus[0],0x100,key,0):raise RuntimeError('模式菜单消息发送失败')
                    user.PostMessageW(menus[0],0x101,key,0)
                    time.sleep(.05)
                selected=True;break
            if len(menus)>1:raise RuntimeError('播放模式菜单歧义，拒绝操作')
        if opener:
            try:opener.wait(timeout=2)
            except subprocess.TimeoutExpired:opener.terminate();opener.wait(timeout=2)
        if not selected:raise RuntimeError('无法通过控件接口选择播放模式')
        for attempt in range(15):
            time.sleep(.1)
            try:actual=_button(_window()).Name
            except Exception:
                if attempt==14:raise
                continue
            if actual==MODES[mode]:return {'backend':'windows_accessibility_and_window_messages',
                'verified':True,'changed':True,'previous_label':before,'mode':mode,'label':actual}
        raise RuntimeError('模式切换未读回验证成功')

if __name__=='__main__':
    if len(sys.argv)!=4 or sys.argv[1]!='--open-only':raise SystemExit(2)
    handle,pid=map(int,sys.argv[2:])
    path=_path(pid).lower()
    if not is_client_path(path):raise SystemExit(3)
    if not any(h==handle and p==pid and '酷狗音乐' in t for h,p,t in _handles(pid)):raise SystemExit(4)
    with auto.UIAutomationInitializerInThread():_invoke(_button(auto.ControlFromHandle(handle)))
