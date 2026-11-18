"""Скриншоты Яндекс Браузера: у него свои горячие клавиши, и с галочкой «привычные сочетания с Print Screen»
он тоже срабатывает на PrtScn — тогда по одному нажатию снимают и «Скрин», и браузер.

Браузер ловит клавиши сам (не через RegisterHotKey), поэтому «Скрин» не может их у него забрать.
Выключить можно только настройкой браузера `ya.screenshoter.hotkeys_enabled` в файле «Local State»
(в браузере: Настройки → Инструменты → Скриншоты → «Использовать горячие клавиши»).
Пока браузер запущен, он держит настройки в памяти и при выходе перезапишет файл — поэтому файл правится,
только когда браузер закрыт; если открыт — его нужно перезапустить (вкладки восстанавливаются).
"""
import ctypes
import json
import logging
import os
import subprocess
import time
from ctypes import wintypes
from pathlib import Path

log = logging.getLogger("skrin")

_LOCAL = Path(os.environ.get("LOCALAPPDATA", ""))
LOCAL_STATE = _LOCAL / "Yandex" / "YandexBrowser" / "User Data" / "Local State"
EXES = [Path(os.environ.get(v, "")) / "Yandex" / "YandexBrowser" / "Application" / "browser.exe"
        for v in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")]
NO_WINDOW = 0x08000000


def _state():
    try:
        return json.loads(LOCAL_STATE.read_text(encoding="utf-8"))
    except Exception:
        return None


def _screenshoter(st):
    return ((st or {}).get("ya") or {}).get("screenshoter") or {}


def installed():
    return LOCAL_STATE.exists()


def hotkeys_on():
    """Горячие клавиши скриншотов браузера включены (по умолчанию — да)."""
    s = _screenshoter(_state())
    return s.get("enabled", True) is not False and s.get("hotkeys_enabled", True) is not False


def prtscn_conflict():
    """Браузер сейчас ловит PrtScn: клавиши включены и выбраны «привычные сочетания с Print Screen»."""
    st = _state()
    s = _screenshoter(st)
    return st is not None and hotkeys_on() and bool(s.get("alternative_hotkeys"))


def exe_path():
    return next((p for p in EXES if p.is_file()), None)


# ---------- процессы браузера ----------
class _PE(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]


def browser_pids():
    """PID процессов browser.exe именно Яндекс Браузера (browser.exe бывает и у других программ)."""
    k32 = ctypes.windll.kernel32
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.OpenProcess.restype = wintypes.HANDLE
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)
    pids = []
    if not snap or snap == wintypes.HANDLE(-1).value:
        return pids
    try:
        pe = _PE()
        pe.dwSize = ctypes.sizeof(_PE)
        ok = k32.Process32FirstW(snap, ctypes.byref(pe))
        while ok:
            if pe.szExeFile.lower() == "browser.exe":
                h = k32.OpenProcess(0x1000, False, pe.th32ProcessID)  # PROCESS_QUERY_LIMITED_INFORMATION
                if h:
                    buf = ctypes.create_unicode_buffer(1024)
                    n = wintypes.DWORD(1024)
                    if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) and \
                            "\\yandex\\yandexbrowser\\" in buf.value.lower():
                        pids.append(pe.th32ProcessID)
                    k32.CloseHandle(h)
            ok = k32.Process32NextW(snap, ctypes.byref(pe))
    finally:
        k32.CloseHandle(snap)
    return pids


def running():
    return bool(browser_pids())


# ---------- смена настройки ----------
def write_hotkeys(on):
    """Записать настройку в Local State. Только при закрытом браузере, иначе он её перезапишет."""
    st = _state()
    if st is None:
        raise RuntimeError("не прочитать настройки Яндекс Браузера")
    s = st.setdefault("ya", {}).setdefault("screenshoter", {})
    if hotkeys_on() == bool(on):
        return False
    backup = LOCAL_STATE.with_name("Local State.skrin-backup")
    if not backup.exists():
        backup.write_bytes(LOCAL_STATE.read_bytes())
    s["hotkeys_enabled"] = bool(on)
    if on:
        s["enabled"] = True  # скриншоты могли выключить в браузере целиком («Разрешить браузеру делать скриншоты»)
    tmp = LOCAL_STATE.with_name("Local State.skrin-tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, LOCAL_STATE)
    log.info("Яндекс Браузер: горячие клавиши скриншотов %s", "включены" if on else "выключены")
    return True


def _wait_closed(seconds):
    end = time.time() + seconds
    while time.time() < end:
        if not browser_pids():
            return True
        time.sleep(0.3)
    return not browser_pids()


def restart_with_hotkeys(on):
    """Закрыть браузер (сначала вежливо, потом принудительно), поменять настройку и открыть его снова
    с прежними вкладками. Возвращает True, если настройка записана."""
    pids = browser_pids()
    if pids:
        args = ["taskkill"] + sum((["/PID", str(p)] for p in pids), [])
        subprocess.run(args, capture_output=True, creationflags=NO_WINDOW)  # окна закрываются как по крестику
        if not _wait_closed(10):
            # фоновый процесс («работать в фоне») по крестику не выходит
            args = ["taskkill", "/F", "/T"] + sum((["/PID", str(p)] for p in browser_pids()), [])
            subprocess.run(args, capture_output=True, creationflags=NO_WINDOW)
            if not _wait_closed(10):
                log.warning("Яндекс Браузер не закрылся")
                return False
        time.sleep(1)  # дать браузеру дописать файлы
    try:
        write_hotkeys(on)
    finally:
        exe = exe_path()
        if pids and exe:
            subprocess.Popen([str(exe), "--restore-last-session"], creationflags=NO_WINDOW, close_fds=True)
    return hotkeys_on() == on
