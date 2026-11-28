"""Настройки «Скрина»: значения по умолчанию, чтение/запись, пути, названия клавиш, масштаб интерфейса."""
import ctypes
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path

VERSION = "1.3.2"
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
        "open_editor": True,           # выделил область — сразу в окно редактора (а не рисовать поверх экрана)
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


# Ответы на вопросы установщика (build/skrin.iss): он пишет их сюда, а Скрин при запуске переносит в настройки
# и удаляет файл. Так всё настраивается при установке, и окно настроек само не открывается.
SETUP_PATH = DATA / "setup.json"


def apply_setup(cfg):
    """Перенести ответы установщика в настройки. Возвращает ответы или None, если их нет."""
    if not SETUP_PATH.exists():
        return None
    try:
        answers = json.loads(SETUP_PATH.read_text("utf-8-sig"))
    except Exception:
        answers = {}
    known = defaults()
    cfg.update({k: v for k, v in answers.items() if k in known and type(v) is type(known[k])})
    for key in ("shot_dir", "video_dir"):
        try:
            Path(cfg[key]).mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
    save_cfg(cfg)
    try:
        SETUP_PATH.unlink()
    except OSError:
        pass
    return answers


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


# ---------- масштаб интерфейса (экраны 100–200 %, у каждого монитора свой) ----------
# Qt работает в настоящих пикселях (QT_ENABLE_HIGHDPI_SCALING=0), поэтому кнопки и шрифты умножаются на масштаб
# сами — и на масштаб того монитора, где окно, а не основного: у ноутбука 200 % со вторым монитором 100 % иначе
# всё на втором мониторе вдвое крупнее.
def _system_scale():
    try:
        return max(1.0, ctypes.windll.user32.GetDpiForSystem() / 96.0)
    except Exception:
        return 1.0


SCALE = _system_scale()  # основной монитор — пока неизвестно, на каком мониторе окно
_scales = []


def screen_scale(screen):
    """Масштаб монитора (QScreen): 1.0 — 100 %, 2.0 — 200 %."""
    try:
        return max(1.0, screen.logicalDotsPerInch() / 96.0)
    except Exception:
        return SCALE


def scale_at(pt):
    """Масштаб монитора под точкой (экранные пиксели)."""
    from PySide6.QtGui import QGuiApplication
    s = QGuiApplication.screenAt(pt) or QGuiApplication.primaryScreen()
    return screen_scale(s) if s is not None else SCALE


def scale_for(rect):
    """Масштаб монитора, на который приходится большая часть области."""
    from PySide6.QtGui import QGuiApplication
    best, most = None, 0
    for s in QGuiApplication.screens():
        r = s.geometry().intersected(rect)
        if not r.isEmpty() and r.width() * r.height() > most:
            best, most = s, r.width() * r.height()
    return screen_scale(best) if best is not None else scale_at(rect.center())


@contextmanager
def ui_scale(k):
    """Всё, что строится внутри with, получает размеры px() для монитора с масштабом k."""
    _scales.append(k)
    try:
        yield k
    finally:
        _scales.pop()


def cur_scale():
    return _scales[-1] if _scales else SCALE


def px(n, k=None):
    return int(round(n * (cur_scale() if k is None else k)))


class Rescaler:
    """Размеры окна под масштаб монитора, где оно сейчас. Окно можно перетащить на монитор с другим
    масштабом — тогда всё, что зарегистрировано через fit(), выставляется заново."""

    def __init__(self, window, k, resize=True):
        self.window, self.k, self.resize = window, k, resize
        self._fns = []
        self._following = False

    def fit(self, fn):
        """fn() выставляет размеры через px(); вызывается сразу и после каждой смены масштаба."""
        self._fns.append(fn)
        with ui_scale(self.k):
            fn()

    def follow(self):
        """Вызвать, когда окно показано (showEvent): следить, на каком мониторе оно."""
        wh = self.window.windowHandle()
        if wh is None or self._following:
            return
        self._following = True
        wh.screenChanged.connect(lambda s: self.set(screen_scale(s)))
        self.set(screen_scale(wh.screen()))  # Windows могла открыть окно не на том мониторе, что ждали

    def set(self, k):
        if abs(k - self.k) < 0.01:
            return
        ratio, self.k = k / self.k, k
        with ui_scale(k):
            for fn in self._fns:
                fn()
        if self.resize:
            from PySide6.QtCore import QTimer
            w = self.window

            def _resize():  # после того, как Windows сама подвинет окно на новый монитор
                try:
                    w.resize((w.size() * ratio).expandedTo(w.minimumSizeHint()))
                except RuntimeError:  # окно уже закрыто
                    pass
            QTimer.singleShot(0, _resize)


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
