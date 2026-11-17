"""Обращения к Windows: горячие клавиши, список окон, мониторы DXGI, скрытие окна от записи."""
import ctypes
import os
import threading
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi")

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x4000
VK_SNAPSHOT = 0x2C
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012

user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsIconic.argtypes = [wintypes.HWND]
dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]


class HotkeyThread(threading.Thread):
    """Регистрирует глобальные клавиши и вызывает callback(id) при нажатии (из своего потока)."""

    def __init__(self, hotkeys, callback):
        super().__init__(daemon=True, name="hotkeys")
        self.hotkeys = hotkeys  # {id: (mods, vk)}
        self.callback = callback
        self.failed = []
        self.ready = threading.Event()
        self.tid = None

    def run(self):
        self.tid = kernel32.GetCurrentThreadId()
        for hid, (mods, vk) in self.hotkeys.items():
            if not user32.RegisterHotKey(None, hid, mods | MOD_NOREPEAT, vk):
                self.failed.append(hid)
        self.ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                try:
                    self.callback(int(msg.wParam))
                except Exception:
                    pass
        for hid in self.hotkeys:
            user32.UnregisterHotKey(None, hid)

    def stop(self):
        if self.tid:
            user32.PostThreadMessageW(self.tid, WM_QUIT, 0, 0)


WS_EX_TRANSPARENT = 0x20
WS_EX_TOOLWINDOW = 0x80
DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_CLOAKED = 14
_SKIP_CLASSES = {"Progman", "WorkerW", "Windows.UI.Core.CoreWindow"}
_KEEP_UNTITLED = {"Shell_TrayWnd", "Shell_SecondaryTrayWnd"}


def list_windows():
    """Видимые окна сверху вниз по z-порядку: [(left, top, right, bottom)] в экранных пикселях."""
    out = []
    my_pid = os.getpid()
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        try:
            if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == my_pid:
                return True
            cloaked = wintypes.DWORD(0)
            dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), 4)
            if cloaked.value:
                return True
            buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, buf, 256)
            cls = buf.value
            if cls in _SKIP_CLASSES:
                return True
            ex = user32.GetWindowLongW(hwnd, -20)
            if ex & WS_EX_TRANSPARENT:
                return True
            if user32.GetWindowTextLengthW(hwnd) == 0 and cls not in _KEEP_UNTITLED:
                return True
            r = wintypes.RECT()
            if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(r), ctypes.sizeof(r)) != 0:
                user32.GetWindowRect(hwnd, ctypes.byref(r))
            if r.right - r.left < 30 or r.bottom - r.top < 30:
                return True
            out.append((r.left, r.top, r.right, r.bottom))
        except Exception:
            pass
        return True

    user32.EnumWindows(proc(cb), 0)
    return out


def exclude_from_capture(hwnd):
    """Окно не попадёт в запись экрана и скриншоты (Windows 10 2004+)."""
    try:
        return bool(user32.SetWindowDisplayAffinity(wintypes.HWND(int(hwnd)), 0x11))
    except Exception:
        return False


def force_foreground(hwnd):
    try:
        user32.SetForegroundWindow(wintypes.HWND(int(hwnd)))
    except Exception:
        pass


# ---------- мониторы в порядке DXGI (так их нумерует ffmpeg ddagrab) ----------

class _GUID(ctypes.Structure):
    _fields_ = [("d1", ctypes.c_ulong), ("d2", ctypes.c_ushort), ("d3", ctypes.c_ushort), ("d4", ctypes.c_ubyte * 8)]


class _OUTPUT_DESC(ctypes.Structure):
    _fields_ = [("DeviceName", ctypes.c_wchar * 32), ("Desktop", wintypes.RECT),
                ("Attached", wintypes.BOOL), ("Rotation", ctypes.c_uint), ("Monitor", ctypes.c_void_p)]


def _vcall(obj, index, *argtypes):
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(vtbl[index])


def dxgi_outputs():
    """[(output_idx, (left, top, right, bottom))] для первой видеокарты — как в ddagrab."""
    dxgi = ctypes.WinDLL("dxgi")
    iid = _GUID(0x770AAE78, 0xF26F, 0x4DBA, (ctypes.c_ubyte * 8)(0xA8, 0x29, 0x25, 0x3C, 0x83, 0xD1, 0xB3, 0x87))
    factory = ctypes.c_void_p()
    if dxgi.CreateDXGIFactory1(ctypes.byref(iid), ctypes.byref(factory)) != 0:
        return []
    result = []
    try:
        adapter = ctypes.c_void_p()
        if _vcall(factory, 12, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p))(factory, 0, ctypes.byref(adapter)) != 0:
            return []
        try:
            i = 0
            while True:
                out = ctypes.c_void_p()
                if _vcall(adapter, 7, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p))(adapter, i, ctypes.byref(out)) != 0:
                    break
                desc = _OUTPUT_DESC()
                _vcall(out, 7, ctypes.POINTER(_OUTPUT_DESC))(out, ctypes.byref(desc))
                r = desc.Desktop
                result.append((i, (r.left, r.top, r.right, r.bottom)))
                _vcall(out, 2)(out)
                i += 1
        finally:
            _vcall(adapter, 2)(adapter)
    finally:
        _vcall(factory, 2)(factory)
    return result


def single_instance(name):
    """True, если мы первая копия программы."""
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    single_instance._h = kernel32.CreateMutexW(None, False, name)
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS
