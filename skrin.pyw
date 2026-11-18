"""Скрин — скриншоты области с пометками и запись видео экрана.

Клавиши по умолчанию: PrtScn — скриншот, Ctrl+Alt+PrtScn — видео (меняются в настройках).
Запуск: pythonw skrin.pyw [--settings]   (установленная версия — Skrin.exe)
"""
import os
import sys

os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"  # координаты Qt = настоящие пиксели экрана

import ctypes
import getpass
import logging
import subprocess
import winreg
from logging.handlers import RotatingFileHandler
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QObject, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QGuiApplication, QIcon, QImage, QPainter, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QMenu, QMessageBox,
                               QProgressDialog, QPushButton, QSystemTrayIcon, QVBoxLayout, QWidget)

import config
import winapi
from config import hotkey_text, px
from editor import EditorWindow, load_image
from overlay import Overlay
from recorder import Countdown, RecordFrame, Recorder, RecordPanel
from updater import Updater

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
HK_SHOT, HK_VIDEO = 1, 2
SERVER_NAME = f"SkrinApp-{getpass.getuser()}"

log = logging.getLogger("skrin")
log.setLevel(logging.INFO)
_h = RotatingFileHandler(config.LOG_PATH, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
_h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
log.addHandler(_h)
sys.excepthook = lambda t, v, tb: log.error("необработанная ошибка", exc_info=(t, v, tb))


def app_icon(recording=False, update=False):
    pm = QPixmap(64, 64)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    if recording:
        p.setBrush(QColor(229, 51, 58))
        p.setPen(QColor(255, 255, 255))
        p.drawEllipse(6, 6, 52, 52)
        p.setBrush(QColor(255, 255, 255))
        p.drawRoundedRect(22, 22, 20, 20, 3, 3)
    else:
        p.setPen(QColor(0, 0, 0, 0))
        p.setBrush(QColor(10, 132, 255))
        p.drawRoundedRect(4, 10, 56, 44, 10, 10)
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(20, 20, 24, 24)
        p.setBrush(QColor(10, 132, 255))
        p.drawEllipse(26, 26, 12, 12)
    if update:  # зелёная метка «есть обновление»
        p.setPen(QColor(255, 255, 255))
        p.setBrush(QColor(34, 197, 94))
        p.drawEllipse(34, 0, 30, 30)
        pen = p.pen()
        pen.setWidth(3)
        p.setPen(pen)
        p.drawLine(49, 7, 49, 22)
        p.drawLine(43, 13, 49, 7)
        p.drawLine(55, 13, 49, 7)
    p.end()
    return QIcon(pm)


def grab_screen():
    """Весь рабочий стол (все мониторы) в настоящих пикселях."""
    m = ctypes.windll.user32.GetSystemMetrics
    x, y, w, h = m(76), m(77), m(78), m(79)  # SM_X/YVIRTUALSCREEN, SM_CX/CYVIRTUALSCREEN
    pm = QGuiApplication.primaryScreen().grabWindow(0, x, y, w, h)
    return pm.toImage().convertToFormat(QImage.Format_RGB32), QPoint(x, y)


def show_in_folder(path):
    subprocess.Popen(["explorer", "/select,", str(Path(path))])


POPUP_CSS = """
QFrame#box { background: rgba(30,31,36,245); border: 1px solid rgba(255,255,255,50); border-radius: 12px; }
QLabel { color: #f0f0f0; font: %(f)spx 'Segoe UI'; }
QLabel#title { font: 600 %(t)spx 'Segoe UI'; }
QPushButton { background: rgba(255,255,255,28); color: white; border: none; border-radius: 7px;
              padding: %(pv)spx %(ph)spx; font: %(f)spx 'Segoe UI'; }
QPushButton:hover { background: rgba(255,255,255,50); }
QPushButton#main { background: #0a84ff; font-weight: 600; }
QPushButton#main:hover { background: #3b9bff; }""" % {"f": px(14), "t": px(16), "pv": px(9), "ph": px(16)}


class SavedPopup(QWidget):
    """Окошко после записи видео: открыть папку / посмотреть."""

    def __init__(self, path):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.path = Path(path)
        box = QFrame(self)
        box.setObjectName("box")
        box.setStyleSheet(POPUP_CSS)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(box)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(px(18), px(14), px(18), px(16))
        lay.setSpacing(px(8))
        t = QLabel("Видео сохранено", box)
        t.setObjectName("title")
        lay.addWidget(t)
        lay.addWidget(QLabel(self.path.name, box))
        row = QHBoxLayout()
        row.setSpacing(px(8))
        b1 = QPushButton("Открыть папку", box)
        b1.setObjectName("main")
        b1.clicked.connect(self.open_folder)
        b2 = QPushButton("Смотреть видео", box)
        b2.clicked.connect(self.play)
        b3 = QPushButton("Закрыть", box)
        b3.clicked.connect(self.close)
        for b in (b1, b2, b3):
            b.setCursor(Qt.PointingHandCursor)
            row.addWidget(b)
        lay.addLayout(row)
        self.adjustSize()
        ag = QGuiApplication.primaryScreen().availableGeometry()
        self.move(ag.right() - self.width() - 16, ag.bottom() - self.height() - 16)
        QTimer.singleShot(30000, self.close)

    def open_folder(self):
        show_in_folder(self.path)
        self.close()

    def play(self):
        os.startfile(str(self.path))
        self.close()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()
        elif e.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.open_folder()


class Toast(QWidget):
    """Короткое «Скопировано» у нижнего края выделенной области. Щелчок — показать файл в папке."""

    def __init__(self, text, area: QRect, path=""):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool |
                         Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.path = path
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lab = QLabel(text, self)
        lab.setStyleSheet(f"background: rgba(30,31,36,235); color: white; border-radius: {px(16)}px;"
                          f" padding: {px(8)}px {px(18)}px; font: 600 {px(14)}px 'Segoe UI';")
        lay.addWidget(lab)
        if path:
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip("Показать файл в папке")
        self.adjustSize()
        screen = QGuiApplication.screenAt(area.center()) or QGuiApplication.primaryScreen()
        sr = screen.availableGeometry()
        x = area.center().x() - self.width() // 2
        y = area.bottom() - self.height() - px(16)
        x = max(sr.left() + 8, min(x, sr.right() - self.width() - 8))
        y = max(sr.top() + 8, min(y, sr.bottom() - self.height() - 8))
        self.move(x, y)
        QTimer.singleShot(1600, self.close)

    def mousePressEvent(self, e):
        if self.path:
            show_in_folder(self.path)
        self.close()


class App(QObject):
    hotkey = Signal(int)

    def __init__(self, app, open_settings=False):
        super().__init__()
        self.app = app
        self.cfg, first_run = config.load_cfg()
        if first_run:
            config.save_cfg(self.cfg)
        self.overlay = None
        self.editors = []  # открытые окна редактора
        self.settings = None
        self.rec_ui = []
        self.last_video = None
        self.countdown = None
        self.popup = None
        self.toast = None
        self.hk = None
        self.hk_failed_names = []
        self.support = None
        self.update_info = None
        self.msg_kind = ""  # что открыть по щелчку на уведомлении: video | update
        self.progress_dlg = None

        self.updater = Updater()
        self.updater.available.connect(self.on_update_available)
        self.updater.progress.connect(self.on_update_progress)
        self.updater.downloaded.connect(self.on_update_downloaded)
        self.updater.failed.connect(self.on_update_failed)

        self.recorder = Recorder()
        self.recorder.finished.connect(self.on_video_done)
        self.recorder.failed.connect(self.on_video_failed)

        self.tray = QSystemTrayIcon(app_icon(), app)
        menu = QMenu()
        self.a_update = QAction("", menu)
        bold = self.a_update.font()
        bold.setBold(True)
        self.a_update.setFont(bold)
        self.a_update.triggered.connect(self.ask_update)
        self.a_update.setVisible(False)
        menu.addAction(self.a_update)
        self.a_shot = QAction("", menu)
        self.a_shot.triggered.connect(lambda: QTimer.singleShot(250, lambda: self.capture("shot")))
        self.a_video = QAction("", menu)
        self.a_video.triggered.connect(lambda: QTimer.singleShot(250, self.video_hotkey))
        menu.addAction(self.a_shot)
        menu.addAction(self.a_video)
        menu.addSeparator()
        menu.addAction("Открыть картинку в редакторе…", self.open_image_file)
        menu.addAction("Картинку из буфера обмена — в редактор", self.open_clipboard)
        menu.addAction("Открыть папку со скриншотами", lambda: self.open_dir(self.cfg["shot_dir"]))
        self.a_vdir = menu.addAction("Открыть папку с видео", lambda: self.open_dir(self.cfg["video_dir"]))
        menu.addSeparator()
        menu.addAction("Настройки…", self.open_settings)
        menu.addAction("Написать в поддержку…", self.open_support)
        menu.addAction("Выход", self.quit)
        self.menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.on_tray)
        self.tray.messageClicked.connect(self.on_message_clicked)
        self.tray.show()

        self.hotkey.connect(self.on_hotkey)
        self.start_hotkeys(report=True)
        self.update_texts()
        log.info("запущен %s (%s), клавиши: %s", config.VERSION, "exe" if config.FROZEN else "py",
                 "ок" if not self.hk_failed_names else self.hk_failed_names)
        if first_run or open_settings:
            QTimer.singleShot(300, lambda: self.open_settings(first_run))
        # обновления — только у установленной версии (версия из исходников обновляется сборкой)
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.auto_check_update)
        self.update_timer.start(6 * 3600 * 1000)
        QTimer.singleShot(30_000, self.auto_check_update)

    # ---------- обновления ----------
    def auto_check_update(self):
        if config.FROZEN and self.cfg.get("auto_update", True):
            self.updater.check()

    def on_update_available(self, info):
        self.update_info = info
        ver = info["version"]
        self.a_update.setText(f"⬆  Установить обновление {ver}")
        self.a_update.setVisible(True)
        if not self.recorder.active:
            self.tray.setIcon(app_icon(update=True))
        self.update_texts()
        if self.cfg.get("notified_version") != ver:  # всплывашка — один раз на версию
            self.cfg["notified_version"] = ver
            config.save_cfg(self.cfg)
            self.msg_kind = "update"
            first = (info.get("notes") or "").split("\n")[0][:120]
            self.tray.showMessage(f"Вышло обновление Скрина {ver}", (first + "\n" if first else "") +
                                  "Нажмите, чтобы установить", QSystemTrayIcon.Information, 15000)

    def ask_update(self):
        info = self.update_info
        if not info:
            return
        if self.recorder.active or self.countdown is not None:
            self.tray.showMessage("Скрин", "Сначала остановите запись видео, потом установите обновление.",
                                  QSystemTrayIcon.Information, 5000)
            return
        notes = info.get("notes") or ""
        box = QMessageBox(QMessageBox.Question, "Обновление Скрина",
                          f"Вышла новая версия {info['version']} (у вас {config.VERSION}).\n\n" +
                          (f"Что нового:\n{notes}\n\n" if notes else "") +
                          "Скачать и установить сейчас? Скрин закроется и сам запустится снова, "
                          "настройки сохранятся.")
        box.setWindowIcon(app_icon())
        yes = box.addButton("Установить", QMessageBox.AcceptRole)
        box.addButton("Позже", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not yes:
            return
        self.progress_dlg = QProgressDialog("Скачиваю обновление…", "", 0, 100)
        self.progress_dlg.setWindowTitle("Скрин")
        self.progress_dlg.setCancelButton(None)
        self.progress_dlg.setMinimumDuration(0)
        self.progress_dlg.setValue(0)
        self.progress_dlg.show()
        self.updater.download()

    def on_update_progress(self, pct):
        if self.progress_dlg:
            self.progress_dlg.setValue(pct)

    def on_update_downloaded(self, path):
        if self.progress_dlg:
            self.progress_dlg.setLabelText("Устанавливаю…")
        Updater.install(path)
        QTimer.singleShot(500, self.quit)

    def on_update_failed(self, msg):
        if self.progress_dlg:
            self.progress_dlg.close()
            self.progress_dlg = None
        self.tray.showMessage("Обновление не удалось", msg, QSystemTrayIcon.Warning, 8000)

    def open_support(self):
        if self.support is not None:
            try:
                self.support.showNormal()
                self.support.raise_()
                self.support.activateWindow()
                return
            except RuntimeError:
                self.support = None
        from support import SupportWindow
        self.support = SupportWindow(self)
        self.support.destroyed.connect(lambda: setattr(self, "support", None))
        self.support.show()
        self.support.raise_()
        self.support.activateWindow()
        winapi.force_foreground(self.support.winId())

    # ---------- клавиши ----------
    def start_hotkeys(self, report=False):
        self.stop_hotkeys()
        keys = {HK_SHOT: tuple(self.cfg["hk_shot"]), HK_VIDEO: tuple(self.cfg["hk_video"])}
        self.hk = winapi.HotkeyThread(keys, self.hotkey.emit)
        self.hk.start()
        self.hk.ready.wait(3)
        self.hk_failed_names = [hotkey_text(keys[i]) for i in self.hk.failed]
        if self.hk_failed_names:
            log.warning("клавиши заняты: %s", self.hk_failed_names)
            if report:
                self.tray.showMessage("Скрин", "Клавиши заняты другой программой: " +
                                      ", ".join(self.hk_failed_names) +
                                      ".\nВыберите другие в «Настройки… → Клавиши».", QSystemTrayIcon.Warning, 8000)

    def stop_hotkeys(self):
        if self.hk is not None:
            self.hk.stop()
            self.hk.join(2)
            self.hk = None

    def update_texts(self):
        ks, kv = hotkey_text(self.cfg["hk_shot"]), hotkey_text(self.cfg["hk_video"])
        self.a_shot.setText(f"Скриншот области\t{ks}")
        if self.recorder.active:
            self.a_video.setText(f"Остановить запись\t{kv}")
        elif self.countdown is not None:
            self.a_video.setText(f"Отменить запись\t{kv}")
        else:
            self.a_video.setText(f"Записать видео\t{kv}")
        self.a_vdir.setVisible(self.cfg["video_dir"] != self.cfg["shot_dir"])
        if self.recorder.active:
            self.tray.setToolTip(f"Скрин — идёт запись. Щелчок по значку или {kv} — стоп")
        elif self.update_info:
            self.tray.setToolTip(f"Скрин — вышло обновление {self.update_info['version']} (меню значка)")
        else:
            self.tray.setToolTip(f"Скрин — {ks} скриншот, {kv} видео")

    # ---------- настройки ----------
    def open_settings(self, first_run=False):
        if self.settings is not None:
            self.settings.showNormal()
            self.settings.raise_()
            self.settings.activateWindow()
            return
        from settings import SettingsWindow
        self.stop_hotkeys()  # чтобы в поле можно было нажать любое сочетание
        self.settings = SettingsWindow(self, first_run)
        self.settings.show()
        self.settings.raise_()
        self.settings.activateWindow()
        winapi.force_foreground(self.settings.winId())

    def apply_settings(self, c, autostart):
        self.cfg.update(c)
        config.save_cfg(self.cfg)
        try:
            self.set_autostart(autostart)
        except Exception:
            log.exception("автозапуск")
        log.info("настройки сохранены")

    def settings_closed(self, saved):
        self.settings = None
        self.start_hotkeys(report=True)
        self.update_texts()

    def autostart_cmd(self):
        if config.FROZEN:
            return f'"{sys.executable}"'
        exe = Path(sys.executable)
        pyw = exe.with_name("pythonw.exe")
        return f'"{pyw if pyw.exists() else exe}" "{config.APP_DIR / "skrin.pyw"}"'

    def autostart_enabled(self):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
                winreg.QueryValueEx(k, config.APP_NAME)
                return True
        except OSError:
            return False

    def set_autostart(self, on):
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, config.APP_NAME, 0, winreg.REG_SZ, self.autostart_cmd())
            else:
                try:
                    winreg.DeleteValue(k, config.APP_NAME)
                except OSError:
                    pass

    @staticmethod
    def open_dir(path):
        Path(path).mkdir(parents=True, exist_ok=True)
        os.startfile(path)

    # ---------- события ----------
    def on_tray(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            if self.countdown is not None:
                self.cancel_countdown()
            elif self.recorder.active:
                self.stop_record()
            else:
                QTimer.singleShot(200, lambda: self.capture("shot"))

    def on_hotkey(self, hid):
        if hid == HK_SHOT:
            self.capture("shot")
        elif hid == HK_VIDEO:
            self.video_hotkey()

    def video_hotkey(self):
        if self.countdown is not None:
            self.cancel_countdown()
        elif self.recorder.active:
            self.stop_record()
        else:
            self.capture("video")

    def capture(self, mode):
        if self.overlay is not None:
            self.overlay.present()
            return
        try:
            img, origin = grab_screen()
            windows = winapi.list_windows()
            monitors = [s.geometry() for s in QGuiApplication.screens()]
        except Exception:
            log.exception("не удалось снять экран")
            return
        ov = Overlay(img, origin, mode, windows, monitors, self.cfg)
        ov.closed.connect(self.on_overlay_closed)
        ov.record.connect(self.start_record)
        ov.copied.connect(self.on_copied)
        ov.to_editor.connect(self.open_editor)
        self.overlay = ov
        ov.present()

    # ---------- редактор ----------
    def open_editor(self, img, shapes=(), area=None, path=None):
        w = EditorWindow(img, list(shapes), self.cfg, area, path)
        w.copied.connect(self.on_copied)
        w.closing.connect(self.on_editor_closed)
        self.editors.append(w)
        w.present()
        log.info("редактор: %dx%d%s", img.width(), img.height(), f", {Path(path).name}" if path else "")

    def on_editor_closed(self, w):
        if w in self.editors:
            self.editors.remove(w)
        config.save_cfg(self.cfg)

    def open_image_file(self):
        path, _ = QFileDialog.getOpenFileName(None, "Открыть картинку в редакторе", self.cfg["shot_dir"],
                                              "Картинки (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;Все файлы (*)")
        if not path:
            return
        img = load_image(path)
        if img is None:
            QMessageBox.warning(None, "Скрин", f"Не удалось открыть картинку:\n{path}")
            return
        self.open_editor(img, path=path)

    def open_clipboard(self):
        img = QGuiApplication.clipboard().image()
        if img.isNull():
            self.tray.showMessage("Скрин", "В буфере обмена нет картинки.", QSystemTrayIcon.Information, 4000)
            return
        self.open_editor(img.convertToFormat(QImage.Format_RGB32))

    def on_overlay_closed(self):
        self.overlay = None
        config.save_cfg(self.cfg)

    def on_copied(self, path, area):
        if not self.cfg.get("copy_toast", True):
            return
        text = "✓  Скопировано и сохранено" if path else "✓  Скопировано"
        self.toast = Toast(text, area, path)
        self.toast.show()

    # ---------- видео ----------
    def start_record(self, rect, mic, system):
        """Сначала отсчёт в рамке (если включён), потом запись."""
        if self.recorder.active or self.countdown is not None:
            return
        self.cfg["mic"], self.cfg["system_audio"] = mic, system
        config.save_cfg(self.cfg)
        seconds = int(self.cfg.get("countdown", 3))
        if seconds <= 0:
            self._begin_record(rect, mic, system)
            return
        self.countdown = Countdown(rect, seconds, hotkey_text(self.cfg["hk_video"]))
        self.countdown.done.connect(lambda: self._begin_record(rect, mic, system))
        self.countdown.show()
        self.update_texts()

    def cancel_countdown(self):
        if self.countdown is not None:
            self.countdown.cancel()
            self.countdown = None
            self.update_texts()

    def _begin_record(self, rect, mic, system):
        self.countdown = None
        area = self.recorder.start(rect, mic, system, self.cfg)
        if area is None:
            self.update_texts()
            return
        screen = QGuiApplication.screenAt(area.center())
        srect = screen.geometry() if screen else area
        frame = RecordFrame(area)
        panel = RecordPanel(area, srect, hotkey_text(self.cfg["hk_video"]))
        panel.stop_clicked.connect(self.stop_record)
        frame.show()
        panel.show()
        self.rec_ui = [frame, panel]
        self.tray.setIcon(app_icon(True))
        self.update_texts()

    def stop_record(self):
        for w in self.rec_ui:
            w.close()
            w.deleteLater()
        self.rec_ui = []
        self.recorder.stop()
        self.tray.setIcon(app_icon(update=self.update_info is not None))
        self.update_texts()
        self.tray.setToolTip("Скрин — сохраняю видео…")

    def on_video_done(self, path):
        self.last_video = path
        self.update_texts()
        if not self.cfg.get("video_popup", True):
            self.msg_kind = "video"
            self.tray.showMessage("Видео сохранено", Path(path).name, QSystemTrayIcon.Information, 4000)
            return
        if self.popup is not None:
            try:
                self.popup.close()
            except RuntimeError:
                pass
        self.popup = SavedPopup(path)
        self.popup.show()
        self.popup.raise_()
        self.popup.activateWindow()

    def on_video_failed(self, msg):
        for w in self.rec_ui:
            w.close()
        self.rec_ui = []
        self.tray.setIcon(app_icon(update=self.update_info is not None))
        self.update_texts()
        self.tray.showMessage("Запись видео не удалась", msg, QSystemTrayIcon.Critical, 8000)

    def on_message_clicked(self):
        if self.msg_kind == "update":
            self.ask_update()
        elif self.last_video and Path(self.last_video).exists():
            show_in_folder(self.last_video)

    def quit(self):
        self.cancel_countdown()
        self.stop_hotkeys()
        if self.recorder.active:
            # сначала дописать и свести видео, потом выйти
            self.recorder.finished.connect(lambda _: self.app.quit())
            self.recorder.failed.connect(lambda _: self.app.quit())
            if not self.recorder.stopping:
                self.stop_record()
            return
        self.tray.hide()
        self.app.quit()


def main():
    want_settings = "--settings" in sys.argv
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Скрин")
    app.setWindowIcon(app_icon())

    # уже запущен? — попросить его открыть настройки и выйти
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if sock.waitForConnected(500):
        sock.write(b"settings")
        sock.flush()
        sock.waitForBytesWritten(500)
        sock.disconnectFromServer()
        return
    if not winapi.single_instance("Local\\SkrinScreenshotApp"):
        return

    main_app = App(app, open_settings=want_settings)
    server = QLocalServer()
    QLocalServer.removeServer(SERVER_NAME)
    server.listen(SERVER_NAME)

    def on_conn():
        c = server.nextPendingConnection()
        c.readyRead.connect(lambda: (c.readAll(), main_app.open_settings()))
    server.newConnection.connect(on_conn)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
