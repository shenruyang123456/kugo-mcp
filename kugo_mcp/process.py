"""Bounded readiness check for KuGou's own main window, without CDP or COM."""
import ctypes
from ctypes import wintypes

_client_pid = 0
_client_hwnd = 0


def _responding(user, hwnd):
    if user.IsHungAppWindow(hwnd):
        return False
    result = ctypes.c_size_t()
    return bool(user.SendMessageTimeoutW(hwnd, 0, 0, 0, 2, 100, ctypes.byref(result)))


def client_ui_ready():
    global _client_pid, _client_hwnd
    from kugou_native_mcp.installation import is_client_path
    user = ctypes.WinDLL('user32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.IsWindow.argtypes = [wintypes.HWND]
    user.IsHungAppWindow.argtypes = [wintypes.HWND]
    user.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_size_t,
                                       ctypes.c_ssize_t, wintypes.UINT, wintypes.UINT,
                                       ctypes.POINTER(ctypes.c_size_t)]
    user.SendMessageTimeoutW.restype = ctypes.c_ssize_t
    if _client_hwnd and user.IsWindow(_client_hwnd):
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(_client_hwnd, ctypes.byref(pid))
        if pid.value == _client_pid:
            return _responding(user, _client_hwnd)
    _client_hwnd, _client_pid = 0, 0
    windows = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(hwnd, _):
        title = ctypes.create_unicode_buffer(512)
        user.GetWindowTextW(hwnd, title, 512)
        if '酷狗音乐' not in title.value or '桌面歌词' in title.value:
            return True
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        handle = kernel.OpenProcess(0x1000, False, pid.value)
        if handle:
            try:
                size = wintypes.DWORD(32768)
                path = ctypes.create_unicode_buffer(size.value)
                if kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)) and is_client_path(path.value):
                    windows.append((hwnd, pid.value))
            finally:
                kernel.CloseHandle(handle)
        return True

    callback = callback_type(visit)
    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user.EnumWindows(callback, 0)
    if len(windows) != 1:
        return False
    _client_hwnd, _client_pid = windows[0]
    # WM_NULL only checks the message queue. Abort after 100 ms; no app command.
    return _responding(user, _client_hwnd)


def client_recent_input():
    """Defer passive sampling briefly while the user operates KuGou itself."""
    if not _client_pid:
        return False
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.GetForegroundWindow.restype = wintypes.HWND
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    pid = wintypes.DWORD()
    user.GetWindowThreadProcessId(user.GetForegroundWindow(), ctypes.byref(pid))
    if pid.value != _client_pid:
        return False
    class LastInput(ctypes.Structure):
        _fields_ = [('size', wintypes.UINT), ('time', wintypes.DWORD)]
    info = LastInput()
    info.size = ctypes.sizeof(info)
    user.GetLastInputInfo.argtypes = [ctypes.POINTER(LastInput)]
    if not user.GetLastInputInfo(ctypes.byref(info)):
        return False
    kernel = ctypes.WinDLL('kernel32')
    kernel.GetTickCount.restype = wintypes.DWORD
    return ((kernel.GetTickCount() - info.time) & 0xffffffff) < 500
