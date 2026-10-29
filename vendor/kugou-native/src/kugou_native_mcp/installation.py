"""Find the user's installed client without embedding a developer's paths."""
import ctypes
import os
import sys
from pathlib import Path

def find_executable(explicit=None):
    chosen=explicit or os.environ.get('KUGOU_EXE_PATH')
    candidates=[]
    if chosen:
        candidates=[Path(chosen)]
    elif sys.platform=='win32':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT,r'kugou\shell\open\command') as key:
                command=winreg.QueryValueEx(key,'')[0]
            count=ctypes.c_int()
            shell=ctypes.WinDLL('shell32',use_last_error=True)
            shell.CommandLineToArgvW.argtypes=[ctypes.c_wchar_p,ctypes.POINTER(ctypes.c_int)]
            shell.CommandLineToArgvW.restype=ctypes.POINTER(ctypes.c_wchar_p)
            args=shell.CommandLineToArgvW(command,ctypes.byref(count))
            if args:
                try:candidates.append(Path(args[0]))
                finally:
                    kernel=ctypes.WinDLL('kernel32')
                    kernel.LocalFree.argtypes=[ctypes.c_void_p]
                    kernel.LocalFree(ctypes.cast(args,ctypes.c_void_p))
        except OSError:pass
        for variable in ('ProgramFiles(x86)','ProgramFiles'):
            if os.environ.get(variable):candidates.append(Path(os.environ[variable])/'KuGou2012/KuGou.exe')
    for candidate in candidates:
        if candidate.name.lower()=='kugou.exe' and candidate.is_file():return candidate.resolve()
    raise RuntimeError('未找到已安装的 KuGou.exe；使用 --exe 或 KUGOU_EXE_PATH 指定客户端路径')

def is_client_path(path):
    if not path:return False
    actual=Path(path).resolve()
    try:
        installed=find_executable()
        # CEF subprocess executables live below the verified installation root.
        return actual.name.lower()=='kugou.exe' and actual.is_relative_to(installed.parent)
    except RuntimeError:return False
