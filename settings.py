"""Окно настроек «Скрина»."""
import copy
import math
import os
import sys
import time
import winsound
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame, QGridLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton,
                               QRadioButton, QSlider, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

import config
from audio import LevelMeter
from config import (MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, hotkey_text, px)

_MOD_VKS = {0x10, 0x11, 0x12, 0x5B, 0x5C, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5}


class HotkeyEdit(QLineEdit):
    """Поле «нажмите сочетание»: запоминает [модификаторы, VK]."""
    changed = Signal()

    def __init__(self, hk, parent=None):
        super().__init__(parent)
        self.hk = list(hk)
        self.setReadOnly(True)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumWidth(px(200))
        self.setText(hotkey_text(self.hk))
        self.setToolTip("Щёлкните и нажмите нужное сочетание клавиш")

    def set_hk(self, hk):
        self.hk = list(hk)
        self.setText(hotkey_text(self.hk))
        self.changed.emit()

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self.setText("Нажмите сочетание…")

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.setText(hotkey_text(self.hk))

    def keyPressEvent(self, e):
        self._take(e)

    def keyReleaseEvent(self, e):
        if e.nativeVirtualKey() == 0x2C:  # PrtScn приходит в Windows только отпусканием
            self._take(e)

    def _take(self, e):
        vk = e.nativeVirtualKey()
        if not vk or vk in _MOD_VKS:
            return
        m = e.modifiers()
        if vk == 0x1B and not m:
            self.clearFocus()
            return
        mods = ((MOD_CONTROL if m & Qt.ControlModifier else 0) | (MOD_ALT if m & Qt.AltModifier else 0) |
                (MOD_SHIFT if m & Qt.ShiftModifier else 0) | (MOD_WIN if m & Qt.MetaModifier else 0))
        self.set_hk([mods, vk])
        self.clearFocus()


def _hline():
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet("color: rgba(0,0,0,40);")
    return f


class SettingsWindow(QWidget):
    test_done = Signal(str)

    def __init__(self, app, first_run=False):
        super().__init__(None, Qt.Window)
        self.app = app
        self._first_run = first_run
        self.c = copy.deepcopy(app.cfg)
        self.meters = {}
        self.setWindowTitle("Скрин — настройки")
        self.setWindowIcon(app.tray.icon())
        self.setAttribute(Qt.WA_DeleteOnClose)
        f = QFont("Segoe UI")
        f.setPixelSize(px(13))
        self.setFont(f)
        self.setMinimumWidth(px(640))

        root = QVBoxLayout(self)
        root.setContentsMargins(px(14), px(12), px(14), px(12))
        if first_run:
            hello = QLabel("<b>Скрин установлен.</b> Проверьте папки и клавиши, затем нажмите «Сохранить».<br>"
                           "Потом настройки всегда можно открыть из меню значка в трее (рядом с часами).")
            hello.setWordWrap(True)
            hello.setStyleSheet("background: #e8f2ff; border: 1px solid #b5d4ff; border-radius: 6px; padding: 8px;")
            root.addWidget(hello)
        tabs = QTabWidget()
        tabs.addTab(self._tab_main(), "Основное")
        tabs.addTab(self._tab_keys(), "Клавиши")
        tabs.addTab(self._tab_video(), "Видео")
        tabs.addTab(self._tab_audio(), "Звук и микрофон")
        tabs.addTab(self._tab_about(), "О программе")
        root.addWidget(tabs)

        btns = QHBoxLayout()
        btns.addStretch(1)
        ok = QPushButton("Сохранить")
        ok.setDefault(True)
        ok.clicked.connect(self.save)
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.close)
        for b in (ok, cancel):
            b.setMinimumWidth(px(110))
            btns.addWidget(b)
        root.addLayout(btns)

        self.test_done.connect(self._play_test)
        self.meter_timer = QTimer(self)
        self.meter_timer.timeout.connect(self._update_meters)
        self.meter_timer.start(60)
        self.dev_timer = QTimer(self)
        self.dev_timer.timeout.connect(self._try_fill_devices)
        self.dev_timer.start(400)
        self._try_fill_devices()

    # ---------- вкладки ----------
    def _folder_row(self, key):
        row = QHBoxLayout()
        edit = QLineEdit(self.c[key])
        edit.textChanged.connect(lambda t: self.c.__setitem__(key, t))
        b1 = QPushButton("Выбрать…")
        b1.clicked.connect(lambda: self._pick_folder(edit))
        b2 = QPushButton("Открыть")
        b2.clicked.connect(lambda: self._open_folder(edit.text()))
        row.addWidget(edit, 1)
        row.addWidget(b1)
        row.addWidget(b2)
        return row, edit, (b1, b2)

    def _pick_folder(self, edit):
        d = QFileDialog.getExistingDirectory(self, "Выберите папку", edit.text())
        if d:
            edit.setText(str(Path(d)))

    @staticmethod
    def _open_folder(path):
        try:
            Path(path).mkdir(parents=True, exist_ok=True)
            os.startfile(path)
        except Exception:
            pass

    def _tab_main(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        g = QGroupBox("Куда сохранять")
        gl = QVBoxLayout(g)
        gl.addWidget(QLabel("Скриншоты:"))
        row, self.shot_edit, _ = self._folder_row("shot_dir")
        gl.addLayout(row)
        self.same_dir = QCheckBox("Видео сохранять в ту же папку")
        self.same_dir.setChecked(self.c["video_dir"] == self.c["shot_dir"])
        gl.addWidget(self.same_dir)
        self.video_label = QLabel("Видео:")
        gl.addWidget(self.video_label)
        row, self.video_edit, self.video_btns = self._folder_row("video_dir")
        gl.addLayout(row)

        def sync_same():
            same = self.same_dir.isChecked()
            for wdg in (self.video_label, self.video_edit, *self.video_btns):
                wdg.setVisible(not same)
            if same:
                self.video_edit.setText(self.shot_edit.text())
        self.same_dir.toggled.connect(sync_same)
        self.shot_edit.textChanged.connect(lambda t: self.same_dir.isChecked() and self.video_edit.setText(t))
        sync_same()
        lay.addWidget(g)

        g = QGroupBox("Скриншоты")
        gl = QVBoxLayout(g)
        fmt = QHBoxLayout()
        fmt.addWidget(QLabel("Формат файла:"))
        self.r_png = QRadioButton("PNG (без потерь)")
        self.r_jpg = QRadioButton("JPG (файлы меньше), качество:")
        grp = QButtonGroup(w)
        grp.addButton(self.r_png)
        grp.addButton(self.r_jpg)
        (self.r_jpg if self.c["shot_format"] == "jpg" else self.r_png).setChecked(True)
        self.jpg_q = QSpinBox()
        self.jpg_q.setRange(50, 100)
        self.jpg_q.setSuffix(" %")
        self.jpg_q.setValue(int(self.c.get("jpg_quality", 90)))
        self.jpg_q.valueChanged.connect(lambda v: self.c.__setitem__("jpg_quality", v))
        self.r_png.toggled.connect(lambda on: (self.c.__setitem__("shot_format", "png" if on else "jpg"),
                                               self.jpg_q.setEnabled(not on)))
        self.jpg_q.setEnabled(self.c["shot_format"] == "jpg")
        fmt.addWidget(self.r_png)
        fmt.addWidget(self.r_jpg)
        fmt.addWidget(self.jpg_q)
        fmt.addStretch(1)
        gl.addLayout(fmt)
        gl.addWidget(self._check("save_on_copy", "По Ctrl+C не только копировать в буфер, но и сохранять файл в папку"))
        gl.addWidget(self._check("copy_toast", "Показывать «Скопировано» после Ctrl+C"))
        gl.addWidget(self._check("open_editor", "Выделил область — сразу открывать её в окне редактора\n"
                                 "(смотреть рядом с другой работой; иначе — кнопка «Открыть в редакторе» или O)"))
        lay.addWidget(g)

        self.autostart = QCheckBox("Запускать «Скрин» вместе с Windows")
        self.autostart.setChecked(self.app.autostart_enabled())
        lay.addWidget(self.autostart)
        lay.addStretch(1)
        return w

    def _check(self, key, text):
        cb = QCheckBox(text)
        cb.setChecked(bool(self.c.get(key, True)))
        cb.toggled.connect(lambda v: self.c.__setitem__(key, v))
        return cb

    def _tab_keys(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        g = QGroupBox("Горячие клавиши (работают во всех программах)")
        gl = QGridLayout(g)
        self.hk_edits = {}
        rows = [("hk_shot", "Скриншот области:", [0, config.VK_SNAPSHOT]),
                ("hk_video", "Запись видео / стоп:", [MOD_CONTROL | MOD_ALT, config.VK_SNAPSHOT])]
        for i, (key, label, dflt) in enumerate(rows):
            e = HotkeyEdit(self.c[key])
            e.changed.connect(lambda k=key, ed=e: (self.c.__setitem__(k, list(ed.hk)), self._check_keys()))
            b = QPushButton("По умолчанию")
            b.clicked.connect(lambda _=False, ed=e, d=dflt: ed.set_hk(d))
            gl.addWidget(QLabel(label), i, 0)
            gl.addWidget(e, i, 1)
            gl.addWidget(b, i, 2)
            self.hk_edits[key] = e
        self.keys_status = QLabel("")
        self.keys_status.setWordWrap(True)
        gl.addWidget(self.keys_status, 2, 0, 1, 3)
        lay.addWidget(g)

        self.snip = None
        if sys.getwindowsversion().build >= 22000:
            self.snip = QCheckBox("Клавишу PrtScn отдать «Скрину» (выключить открытие «Ножниц» Windows по PrtScn)")
            # при первом запуске, если для скриншота выбран просто PrtScn, — сразу предложить
            proposed = self._first_run and list(self.c["hk_shot"]) == [0, config.VK_SNAPSHOT]
            self.snip.setChecked(not config.snipping_on_prtscn() or proposed)
            lay.addWidget(self.snip)
            note = QLabel("Изменение «Ножниц» может заработать только после перезахода в Windows.")
            note.setStyleSheet("color: #777;")
            lay.addWidget(note)

        help_ = QLabel(
            "<b>В окне скриншота:</b><br>"
            "Ctrl+C или Enter — в буфер и в папку · Ctrl+S — сохранить как · Esc — закрыть<br>"
            "Ctrl+Z / Ctrl+Y — отменить / вернуть · колесо мыши — толщина · 1–8 — цвет<br>"
            "A стрелка · L линия · R прямоугольник · E овал · P карандаш · M маркер · T текст · N номер · "
            "B размытие · V видео этой области<br>Shift при рисовании — ровно 45° / квадрат / круг · "
            "Delete — удалить выбранную пометку")
        help_.setWordWrap(True)
        help_.setStyleSheet("color: #444;")
        lay.addWidget(help_)
        lay.addStretch(1)
        self._check_keys()
        return w

    def _check_keys(self):
        a, b = self.c["hk_shot"], self.c["hk_video"]
        msgs = []
        if list(a) == list(b):
            msgs.append("⚠ Для скриншота и видео выбрано одно и то же сочетание.")
        failed = getattr(self.app, "hk_failed_names", [])
        if failed:
            msgs.append("⚠ Сейчас заняты другой программой: " + ", ".join(failed) + ". Выберите другое сочетание.")
        if not msgs:
            msgs.append("Если сочетание окажется занято другой программой (например, Скриншотером), "
                        "«Скрин» скажет об этом после сохранения.")
        self.keys_status.setText("\n".join(msgs))

    def _tab_video(self):
        w = QWidget()
        form = QFormLayout(w)
        self.fps = QComboBox()
        for v in (15, 24, 30, 60):
            self.fps.addItem(f"{v} кадров/с", v)
        self.fps.setCurrentIndex(max(0, self.fps.findData(int(self.c.get("fps", 30)))))
        self.fps.currentIndexChanged.connect(lambda _: self.c.__setitem__("fps", self.fps.currentData()))
        form.addRow("Плавность:", self.fps)
        self.quality = QComboBox()
        for k, t in (("normal", "Обычное — файлы меньше"), ("high", "Высокое"), ("max", "Максимальное — файлы больше")):
            self.quality.addItem(t, k)
        self.quality.setCurrentIndex(max(0, self.quality.findData(self.c.get("quality", "high"))))
        self.quality.currentIndexChanged.connect(lambda _: self.c.__setitem__("quality", self.quality.currentData()))
        form.addRow("Качество:", self.quality)
        self.cd = QComboBox()
        for v, t in ((0, "Без отсчёта"), (3, "3 секунды"), (5, "5 секунд")):
            self.cd.addItem(t, v)
        self.cd.setCurrentIndex(max(0, self.cd.findData(int(self.c.get("countdown", 3)))))
        self.cd.currentIndexChanged.connect(lambda _: self.c.__setitem__("countdown", self.cd.currentData()))
        form.addRow("Отсчёт перед записью:", self.cd)
        form.addRow("", self._check("draw_mouse", "Показывать курсор мыши в видео"))
        form.addRow("", self._check("video_popup", "После записи предлагать открыть папку или посмотреть видео"))
        enc = self.app.recorder.encoder
        from recorder import ENCODER_NAMES
        form.addRow("Чем сжимается видео:", QLabel(ENCODER_NAMES.get(enc, "определяется…") +
                                                   ("" if enc in (None, "x264") else " — почти не нагружает процессор")))
        return w

    def _tab_audio(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.audio_wait = QLabel("Подготовка списка звуковых устройств… (первый раз после запуска — до 15 секунд)")
        self.audio_wait.setStyleSheet("color: #a05a00;")
        lay.addWidget(self.audio_wait)

        self.dev = {}
        for kind, title, flag, vol_key in (("mic", "Микрофон", "mic", "mic_volume"),
                                           ("sys", "Звук компьютера (что играет в динамиках)", "system_audio",
                                            "sys_volume")):
            g = QGroupBox(title)
            gl = QGridLayout(g)
            on = self._check(flag, "Записывать в видео")
            gl.addWidget(on, 0, 0, 1, 3)
            combo = QComboBox()
            combo.setMinimumWidth(px(380))
            combo.currentIndexChanged.connect(lambda _, k=kind: self._device_changed(k))
            gl.addWidget(QLabel("Устройство:"), 1, 0)
            gl.addWidget(combo, 1, 1, 1, 2)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setTextVisible(False)
            bar.setFixedHeight(px(14))
            bar.setStyleSheet("QProgressBar { border: 1px solid #c8c8c8; border-radius: 4px; background: #f0f0f0; }"
                              "QProgressBar::chunk { background: #22c55e; border-radius: 3px; }")
            gl.addWidget(QLabel("Уровень:"), 2, 0)
            gl.addWidget(bar, 2, 1, 1, 2)
            vol = QSlider(Qt.Horizontal)
            vol.setRange(0, 300)
            vol.setSingleStep(10)
            vol.setPageStep(25)
            vol.setValue(int(self.c.get(vol_key, 100)))
            vlabel = QLabel(f"{vol.value()} %")
            vlabel.setMinimumWidth(px(48))
            vol.valueChanged.connect(lambda v, k=vol_key, lb=vlabel: (self.c.__setitem__(k, v), lb.setText(f"{v} %")))
            gl.addWidget(QLabel("Громкость в видео:"), 3, 0)
            gl.addWidget(vol, 3, 1)
            gl.addWidget(vlabel, 3, 2)
            if kind == "mic":
                self.test_btn = QPushButton("Проверить: записать 5 секунд и прослушать")
                self.test_btn.clicked.connect(self._start_test)
                gl.addWidget(self.test_btn, 4, 0, 1, 3)
                hint = QLabel("Скажите что-нибудь — полоска уровня должна прыгать. Если стоит на месте, "
                              "выберите другое устройство.")
            else:
                hint = QLabel("Включите любой звук на компьютере — полоска должна прыгать.")
            hint.setWordWrap(True)
            hint.setStyleSheet("color: #555;")
            gl.addWidget(hint, 5, 0, 1, 3)
            lay.addWidget(g)
            self.dev[kind] = {"combo": combo, "bar": bar, "vol": vol}

        refresh = QPushButton("Обновить список устройств (подключили новый микрофон или наушники)")
        refresh.clicked.connect(self._refresh_devices)
        lay.addWidget(refresh)
        lay.addStretch(1)
        self._audio_enabled(False)
        return w

    def _tab_about(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        t = QLabel(f"<h2>Скрин {config.VERSION}</h2>"
                   "Скриншоты области с пометками и запись видео экрана со звуком.<br><br>"
                   f"Программа: {config.APP_DIR}<br>Настройки и журнал: {config.DATA}")
        t.setTextInteractionFlags(Qt.TextSelectableByMouse)
        t.setWordWrap(True)
        lay.addWidget(t)
        row = QHBoxLayout()
        b = QPushButton("Открыть журнал")
        b.clicked.connect(lambda: config.LOG_PATH.exists() and os.startfile(str(config.LOG_PATH)))
        row.addWidget(b)
        b = QPushButton("Папка настроек")
        b.clicked.connect(lambda: os.startfile(str(config.DATA)))
        row.addWidget(b)
        b = QPushButton("Сбросить все настройки")
        b.clicked.connect(self._reset)
        row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)

        g = QGroupBox("Обновления и поддержка")
        gl = QVBoxLayout(g)
        gl.addWidget(self._check("auto_update", "Проверять обновления автоматически (значок в трее подскажет, "
                                                "когда выйдет новая версия)"))
        row = QHBoxLayout()
        self.upd_btn = QPushButton("Проверить обновления")
        self.upd_btn.clicked.connect(self._check_updates)
        row.addWidget(self.upd_btn)
        b = QPushButton("Написать в поддержку…")
        b.clicked.connect(self.app.open_support)
        row.addWidget(b)
        b = QPushButton("Страница программы")
        b.clicked.connect(lambda: os.startfile(config.SITE_URL))
        row.addWidget(b)
        b = QPushButton("Исходный код")
        b.setToolTip(config.GITHUB_URL)
        b.clicked.connect(lambda: os.startfile(config.GITHUB_URL))
        row.addWidget(b)
        row.addStretch(1)
        gl.addLayout(row)
        self.upd_status = QLabel("")
        self.upd_status.setWordWrap(True)
        gl.addWidget(self.upd_status)
        lay.addWidget(g)
        upd = self.app.updater
        upd.up_to_date.connect(self._upd_msg)
        upd.failed.connect(self._upd_msg)
        upd.available.connect(lambda info: self._upd_msg(
            f"Вышла версия {info['version']} — установить можно из меню значка в трее."))
        lay.addStretch(1)
        return w

    def _check_updates(self):
        if not config.FROZEN:
            self.upd_status.setText("Это версия из исходников — она обновляется сборкой (build.ps1), "
                                    "а не через интернет.")
        self.upd_status.setText(self.upd_status.text() + ("\n" if not config.FROZEN else "") + "Проверяю…")
        self.app.updater.check(manual=True)

    def _upd_msg(self, text):
        try:
            self.upd_status.setText(text)
        except RuntimeError:
            pass

    def _reset(self):
        if QMessageBox.question(self, "Скрин", "Вернуть все настройки как после установки?") == QMessageBox.Yes:
            self.c = config.defaults()
            self.app.apply_settings(self.c, self.autostart.isChecked())
            self.close()
            QTimer.singleShot(200, self.app.open_settings)

    # ---------- звук ----------
    def _audio_enabled(self, on):
        for d in self.dev.values():
            d["combo"].setEnabled(on)
        self.test_btn.setEnabled(on)

    def _try_fill_devices(self):
        host = self.app.recorder.audio
        if not host.ready.is_set():
            return
        self.dev_timer.stop()
        self.audio_wait.setVisible(host.p is None)
        if host.p is None:
            self.audio_wait.setText("Звук недоступен — подробности в журнале.")
            return
        host.busy = True  # пока окно открыто — не перезапускать звук
        for kind, items, current, dflt in (
                ("mic", host.inputs(), self.c.get("mic_device", ""), host.default_input),
                ("sys", host.loopbacks(), self.c.get("sys_device", ""), host.default_loopback)):
            combo = self.dev[kind]["combo"]
            combo.blockSignals(True)
            combo.clear()
            try:
                dname = dflt()["name"].replace(" [Loopback]", "")
            except Exception:
                dname = "—"
            combo.addItem(f"Как в Windows по умолчанию ({dname})", "")
            for name, _ in items:
                combo.addItem(name, name)
            i = combo.findData(current)
            combo.setCurrentIndex(i if i >= 0 else 0)
            combo.blockSignals(False)
        self._audio_enabled(True)
        self._device_changed("mic")
        self._device_changed("sys")

    def _device_changed(self, kind):
        host = self.app.recorder.audio
        combo = self.dev[kind]["combo"]
        name = combo.currentData() or ""
        self.c["mic_device" if kind == "mic" else "sys_device"] = name
        old = self.meters.pop(kind, None)
        if old:
            old.close()
        if not host.ready.is_set() or host.p is None:
            return
        try:
            info = host.find_input(name) if kind == "mic" else host.find_loopback(name)
            self.meters[kind] = LevelMeter(host.p, info)
        except Exception as e:
            self.dev[kind]["bar"].setFormat(f"не открывается: {e}")
            self.dev[kind]["bar"].setTextVisible(True)

    def _update_meters(self):
        for kind, d in self.dev.items():
            m = self.meters.get(kind)
            lvl = m.current() if m else 0.0
            vol = max(d["vol"].value(), 1) / 100
            if lvl > 0:
                lvl = max(0.0, min(1.0, lvl + 20 * math.log10(vol) / 60))
            d["bar"].setValue(int(lvl * 100))
        if getattr(self, "_test_until", 0):
            left = int(self._test_until - time.time()) + 1
            if left > 0:
                self.test_btn.setText(f"Идёт запись… говорите ({left})")

    def _start_test(self):
        m = self.meters.get("mic")
        if not m:
            return
        self.test_btn.setEnabled(False)
        self._test_until = time.time() + 5
        m.record_test(5, self.test_done.emit)

    def _play_test(self, path):
        self._test_until = 0
        self.test_btn.setText("Воспроизвожу…")
        winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        QTimer.singleShot(5200, lambda: (self.test_btn.setText("Проверить: записать 5 секунд и прослушать"),
                                         self.test_btn.setEnabled(True)))

    def _refresh_devices(self):
        for m in self.meters.values():
            m.close()
        self.meters.clear()
        self._audio_enabled(False)
        self.audio_wait.setText("Обновляю список устройств… (до 15 секунд)")
        self.audio_wait.setVisible(True)
        host = self.app.recorder.audio
        host.busy = False
        host.refresh()
        QTimer.singleShot(300, lambda: self.dev_timer.start(400))

    # ---------- сохранение ----------
    def save(self):
        if self.same_dir.isChecked():
            self.c["video_dir"] = self.c["shot_dir"]
        for key in ("shot_dir", "video_dir"):
            try:
                Path(self.c[key]).mkdir(parents=True, exist_ok=True)
            except Exception as e:
                QMessageBox.warning(self, "Скрин", f"Не удаётся создать папку:\n{self.c[key]}\n\n{e}")
                return
        if self.snip is not None:
            want_off = self.snip.isChecked()
            if want_off == config.snipping_on_prtscn():  # нужно поменять
                try:
                    config.set_snipping_on_prtscn(not want_off)
                except Exception:
                    pass
        self.app.apply_settings(self.c, self.autostart.isChecked())
        self.saved = True
        self.close()

    def closeEvent(self, e):
        for m in self.meters.values():
            m.close()
        self.meters.clear()
        winsound.PlaySound(None, 0)
        self.app.recorder.audio.busy = self.app.recorder.active
        self.app.settings_closed(getattr(self, "saved", False))
        super().closeEvent(e)
