"""Настройки «Скрина»: значения по умолчанию, чтение/запись, пути, названия клавиш, масштаб интерфейса."""
import ctypes
import json
import os
import sys
from pathlib import Path

VERSION = "1.3.1"
APP_NAME = "Skrin"
SITE_URL = "https://website18.ru/skrin/"
UPDATE_URL = SITE_URL + "latest.json"
GITHUB_URL = "https://github.com/q115234/skrin"

FROZEN = getattr(sys, "frozen", False)  # собран PyInstaller'ом (установленная версия)
APP_DIR = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
BIN = APP_DIR / "bin"
FFMPEG = str(BIN / "ffmpeg.exe")

DATA = Path(os.environ.get("APPDATA", Path.home())) / "Skrin"
DATA.mkdir(parents=True, exist_ok=True)
CFG_PATH = DATA / "config.json"
LOG_PATH = DATA / "skrin.log"

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN = 0x1, 0x2, 0x4, 0x8
VK_SNAPSHOT = 0x2C


def _desktop():
    try:
        buf = ctypes.create_unicode_buffer(260)
        ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf)  # CSIDL_DESKTOPDIRECTORY
        if buf.value:
            return Path(buf.value)
    except Exception:
        pass
    return Path.home() / "Desktop"


def defaults():
    folder = str(_desktop() / "Скриншоты")
    return {
        # папки и файлы
        "shot_dir": folder,
        "video_dir": folder,
        "shot_format": "png",          # png | jpg
        "jpg_quality": 90,
        "save_on_copy": True,          # Ctrl+C: кроме буфера ещё и файл в папку
        "copy_toast": True,            # показывать «Скопировано»
        "open_editor": False,          # выделил область — сразу в окно редактора (а не рисовать поверх экрана)
        # клавиши
        "hk_shot": [0, VK_SNAPSHOT],                          # PrtScn
        "hk_video": [MOD_CONTROL | MOD_ALT, VK_SNAPSHOT],     # Ctrl+Alt+PrtScn
        # видео
        "fps": 30,
        "quality": "high",             # normal | high | max
        "countdown": 3,
        "draw_mouse": True,
        "video_popup": True,
        # звук
        "mic": True,
        "system_audio": True,
        "mic_device": "",              # "" — устройство Windows по умолчанию
        "sys_device": "",
        "mic_volume": 100,             # %
        "sys_volume": 100,
        # обновления
        "auto_update": True,
        "notified_version": "",
        # редактор
        "tool": "arrow",
        "color": "#ff2a2a",
        "width": 4,
    }


def load_cfg():
    cfg = defaults()
    first_run = not CFG_PATH.exists()
    try:
        saved = json.loads(CFG_PATH.read_text("utf-8"))
    except Exception:
        saved = {}
    if saved and "hk_shot" not in saved:
        # конфиг первой версии (рядом со Скриншотером, который держит PrtScn) — оставить старые клавиши
        saved["hk_shot"] = [MOD_CONTROL, VK_SNAPSHOT]
        saved["hk_video"] = [MOD_CONTROL | MOD_ALT, VK_SNAPSHOT]
    cfg.update(saved)
    return cfg, first_run


def save_cfg(cfg):
    tmp = CFG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), "utf-8")
    os.replace(tmp, CFG_PATH)


# ---------- названия клавиш ----------
_VK_NAMES = {
    0x2C: "PrtScn", 0x13: "Pause", 0x91: "ScrollLock", 0x2D: "Insert", 0x2E: "Delete", 0x24: "Home",
    0x23: "End", 0x21: "PgUp", 0x22: "PgDn", 0x20: "Пробел", 0x09: "Tab", 0x0D: "Enter", 0x1B: "Esc",
    0x08: "Backspace", 0x25: "←", 0x26: "↑", 0x27: "→", 0x28: "↓", 0xC0: "`", 0xBD: "-", 0xBB: "=",
    0xDB: "[", 0xDD: "]", 0xDC: "\\", 0xBA: ";", 0xDE: "'", 0xBC: ",", 0xBE: ".", 0xBF: "/",
}


def vk_name(vk):
    if vk in _VK_NAMES:
        return _VK_NAMES[vk]
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        return chr(vk)
    if 0x70 <= vk <= 0x87:
        return f"F{vk - 0x6F}"
    if 0x60 <= vk <= 0x69:
        return f"Num {vk - 0x60}"
    return f"VK{vk:02X}"


def hotkey_text(hk):
    mods, vk = hk
    parts = []
    if mods & MOD_CONTROL:
        parts.append("Ctrl")
    if mods & MOD_ALT:
        parts.append("Alt")
    if mods & MOD_SHIFT:
        parts.append("Shift")
    if mods & MOD_WIN:
        parts.append("Win")
    parts.append(vk_name(vk))
    return "+".join(parts)


# ---------- масштаб интерфейса (экраны 125–200 %) ----------
def _system_scale():
    try:
        return max(1.0, ctypes.windll.user32.GetDpiForSystem() / 96.0)
    except Exception:
        return 1.0


SCALE = _system_scale()


def px(n):
    return int(round(n * SCALE))


# ---------- «Ножницы» Windows на PrtScn ----------
_KB_KEY = r"Control Panel\Keyboard"


def snipping_on_prtscn():
    """True, если Windows открывает «Ножницы» по PrtScn (в Windows 11 включено по умолчанию)."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _KB_KEY) as k:
            v, _ = winreg.QueryValueEx(k, "PrintScreenKeyForSnippingEnabled")
            return bool(v)
    except OSError:
        return sys.getwindowsversion().build >= 22000


def set_snipping_on_prtscn(on):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _KB_KEY, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, "PrintScreenKeyForSnippingEnabled", 0, winreg.REG_DWORD, 1 if on else 0)
