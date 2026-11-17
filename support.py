"""Окно «Написать в поддержку»: сообщение уходит на website18.ru/skrin/support.php → уведомление в MAX."""
import json
import platform
import threading
import urllib.request

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout,
                               QWidget)

import config
from config import px

SUPPORT_URL = config.SITE_URL + "support.php"


def system_info(app=None):
    enc = getattr(getattr(app, "recorder", None), "encoder", None) if app else None
    screens = QGuiApplication.screens()
    return {
        "version": config.VERSION + (" exe" if config.FROZEN else " py"),
        "windows": f"{platform.release()} build {platform.version()}",
        "screens": ", ".join(f"{s.geometry().width()}x{s.geometry().height()}" for s in screens),
        "scale": f"{int(config.SCALE * 100)}%",
        "encoder": enc or "?",
    }


def read_log_tail(limit=40_000):
    try:
        data = config.LOG_PATH.read_text("utf-8", "replace")
        return data[-limit:]
    except Exception:
        return ""


class SupportWindow(QWidget):
    sent = Signal(bool, str)

    def __init__(self, app=None):
        super().__init__(None, Qt.Window)
        self.app = app
        self.setWindowTitle("Скрин — написать в поддержку")
        self.setAttribute(Qt.WA_DeleteOnClose)
        if app is not None:
            self.setWindowIcon(app.tray.icon())
        f = QFont("Segoe UI")
        f.setPixelSize(px(13))
        self.setFont(f)
        self.setMinimumWidth(px(520))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(px(16), px(14), px(16), px(14))
        intro = QLabel("Что-то не работает или есть идея? Напишите — ответим.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        lay.addWidget(QLabel("Как с вами связаться (почта, телефон, Telegram или MAX):"))
        self.contact = QLineEdit()
        self.contact.setPlaceholderText("например, ivan@mail.ru или +7 900 000-00-00")
        lay.addWidget(self.contact)
        lay.addWidget(QLabel("Что случилось:"))
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("Опишите, что делали и что пошло не так. Например: «нажимаю PrtScn — ничего не "
                                     "происходит», «в видео нет звука микрофона».")
        self.text.setMinimumHeight(px(140))
        lay.addWidget(self.text)
        self.attach = QCheckBox("Приложить журнал работы программы — поможет быстрее найти причину\n"
                                "(там версия, ошибки, названия папок и звуковых устройств; скриншотов и видео нет)")
        self.attach.setChecked(True)
        lay.addWidget(self.attach)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        row = QHBoxLayout()
        row.addStretch(1)
        self.send_btn = QPushButton("Отправить")
        self.send_btn.setDefault(True)
        self.send_btn.clicked.connect(self.send)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.close)
        for b in (self.send_btn, close):
            b.setMinimumWidth(px(110))
            row.addWidget(b)
        lay.addLayout(row)
        self.sent.connect(self._done)

    def send(self):
        contact = self.contact.text().strip()
        text = self.text.toPlainText().strip()
        if len(text) < 5:
            self.status.setStyleSheet("color: #c0392b;")
            self.status.setText("Напишите, пожалуйста, что случилось.")
            return
        if len(contact) < 3:
            self.status.setStyleSheet("color: #c0392b;")
            self.status.setText("Укажите, как с вами связаться, — иначе не сможем ответить.")
            return
        payload = {"source": "app", "contact": contact[:200], "message": text[:3000],
                   "info": system_info(self.app), "log": read_log_tail() if self.attach.isChecked() else ""}
        self.send_btn.setEnabled(False)
        self.status.setStyleSheet("color: #555;")
        self.status.setText("Отправляю…")
        threading.Thread(target=self._post, args=(payload,), daemon=True).start()

    def _post(self, payload):
        try:
            req = urllib.request.Request(
                SUPPORT_URL, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), method="POST",
                headers={"Content-Type": "application/json", "Accept": "application/json",
                         "User-Agent": f"Skrin/{config.VERSION} (Windows)", "X-Skrin-App": config.VERSION})
            with urllib.request.urlopen(req, timeout=30) as r:
                ok = json.loads(r.read().decode("utf-8")).get("ok", False)
            self.sent.emit(bool(ok), "")
        except Exception as e:
            self.sent.emit(False, str(e))

    def _done(self, ok, err):
        if ok:
            self.status.setStyleSheet("color: #1e8e3e;")
            self.status.setText("Спасибо! Сообщение отправлено, ответим по указанному контакту.")
            self.text.clear()
        else:
            self.status.setStyleSheet("color: #c0392b;")
            self.status.setText("Не удалось отправить" + (f" ({err})" if err else "") +
                                ". Проверьте интернет или напишите через сайт: " + config.SITE_URL)
            self.send_btn.setEnabled(True)
