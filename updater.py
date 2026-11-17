"""Обновления: проверка https://website18.ru/skrin/latest.json, скачивание и тихая установка новой версии."""
import hashlib
import json
import logging
import re
import subprocess
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from PySide6.QtCore import QObject, Signal

import config

log = logging.getLogger("skrin")
UA = f"Skrin/{config.VERSION} (Windows)"


def vtuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:4])


def is_newer(remote, local=config.VERSION):
    return vtuple(remote) > vtuple(local)


class Updater(QObject):
    available = Signal(dict)  # сведения о новой версии
    up_to_date = Signal(str)  # для кнопки «Проверить» в настройках
    progress = Signal(int)
    downloaded = Signal(str)
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self.info = None
        self.checking = False
        self.downloading = False

    # ---------- проверка ----------
    def check(self, manual=False):
        if self.checking:
            return
        self.checking = True
        threading.Thread(target=self._check, args=(manual,), daemon=True, name="update-check").start()

    def _check(self, manual):
        try:
            url = f"{config.UPDATE_URL}?t={int(time.time())}"  # мимо кеша
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Cache-Control": "no-cache"})
            with urllib.request.urlopen(req, timeout=20) as r:
                info = json.loads(r.read().decode("utf-8"))
            ver = str(info.get("version", ""))
            if ver and is_newer(ver):
                log.info("обновление: есть %s (у нас %s)", ver, config.VERSION)
                self.info = info
                self.available.emit(info)
            else:
                self.up_to_date.emit(f"Установлена последняя версия ({config.VERSION}).")
        except Exception as e:
            log.warning("проверка обновлений не удалась: %s", e)
            if manual:
                self.failed.emit(f"Не удалось проверить обновления: {e}")
        finally:
            self.checking = False

    # ---------- скачивание и установка ----------
    def download(self):
        if self.downloading or not self.info:
            return
        self.downloading = True
        threading.Thread(target=self._download, daemon=True, name="update-download").start()

    def _download(self):
        info = self.info
        try:
            dest = Path(tempfile.gettempdir()) / f"SkrinSetup-{info['version']}.exe"
            req = urllib.request.Request(info["url"], headers={"User-Agent": UA})
            h = hashlib.sha256()
            with urllib.request.urlopen(req, timeout=30) as r, open(dest, "wb") as f:
                total = int(r.headers.get("Content-Length") or info.get("size") or 0)
                got, last = 0, -1
                while True:
                    chunk = r.read(256 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    h.update(chunk)
                    got += len(chunk)
                    if total:
                        pct = int(got * 100 / total)
                        if pct != last:
                            self.progress.emit(pct)
                            last = pct
            want = info.get("sha256", "").lower()
            if want and h.hexdigest() != want:
                dest.unlink(missing_ok=True)
                raise RuntimeError("файл скачался с ошибкой (не совпала контрольная сумма), попробуйте ещё раз")
            log.info("обновление %s скачано: %s", info["version"], dest)
            self.downloaded.emit(str(dest))
        except Exception as e:
            log.exception("скачивание обновления")
            self.failed.emit(f"Не удалось скачать обновление: {e}")
        finally:
            self.downloading = False

    @staticmethod
    def install(path):
        """Запускает установщик тихо (он сам закроет «Скрин» и запустит новую версию)."""
        log.info("запуск установщика обновления %s", path)
        subprocess.Popen([path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"], close_fds=True,
                         creationflags=subprocess.DETACHED_PROCESS)
