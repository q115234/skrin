"""Картинки для страницы website18.ru/skrin/ — на выдуманной демо-странице (не на настоящем экране).

    python site/make_shots.py   → site/img/*.webp, site/img/og.png
"""
import os
import sys
import time
from pathlib import Path

os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QTabWidget

import config

OUT = Path(__file__).resolve().parent / "img"
OUT.mkdir(exist_ok=True)
W, H = 1600, 900
app = QApplication(sys.argv)


def font(px, bold=False):
    f = QFont("Segoe UI")
    f.setPixelSize(px)
    f.setBold(bold)
    return f


def demo_desktop():
    img = QImage(W, H, QImage.Format_RGB32)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    g = QLinearGradient(0, 0, W, H)
    g.setColorAt(0, QColor("#7aa7e8"))
    g.setColorAt(1, QColor("#b9a4e6"))
    p.fillRect(img.rect(), g)
    # окно «браузера»
    win = QRectF(170, 70, 1260, 760)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(0, 0, 0, 40))
    p.drawRoundedRect(win.adjusted(4, 8, 4, 8), 12, 12)
    p.setBrush(QColor("#ffffff"))
    p.drawRoundedRect(win, 12, 12)
    p.setBrush(QColor("#eef1f6"))
    p.drawRoundedRect(QRectF(win.x(), win.y(), win.width(), 52), 12, 12)
    p.drawRect(QRectF(win.x(), win.y() + 30, win.width(), 22))
    for i, c in enumerate(("#ff5f57", "#febc2e", "#28c840")):
        p.setBrush(QColor(c))
        p.drawEllipse(QPointF(win.x() + 24 + i * 22, win.y() + 26), 7, 7)
    p.setBrush(QColor("#ffffff"))
    p.drawRoundedRect(QRectF(win.x() + 110, win.y() + 12, 640, 28), 14, 14)
    p.setPen(QColor("#667085"))
    p.setFont(font(14))
    p.drawText(QRectF(win.x() + 128, win.y() + 12, 600, 28), Qt.AlignVCenter, "crm.example.ru/otchet/noyabr")
    x0, y0 = win.x() + 50, win.y() + 90
    p.setPen(QColor("#101828"))
    p.setFont(font(30, True))
    p.drawText(QPointF(x0, y0 + 20), "Продажи за ноябрь")
    p.setPen(QColor("#475467"))
    p.setFont(font(16))
    p.drawText(QPointF(x0, y0 + 56), "Сводка по магазину «Ромашка» · обновлено сегодня в 10:15")
    # плитки
    for i, (t, v, c) in enumerate((("Заказы", "1 284", "#2f80ff"), ("Выручка", "2,4 млн ₽", "#22c55e"),
                                  ("Средний чек", "1 870 ₽", "#f59e0b"))):
        r = QRectF(x0 + i * 260, y0 + 90, 240, 100)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#f5f7fb"))
        p.drawRoundedRect(r, 10, 10)
        p.setPen(QColor("#667085"))
        p.setFont(font(15))
        p.drawText(r.adjusted(18, 14, 0, 0), Qt.AlignLeft | Qt.AlignTop, t)
        p.setPen(QColor(c))
        p.setFont(font(28, True))
        p.drawText(r.adjusted(18, 44, 0, 0), Qt.AlignLeft | Qt.AlignTop, v)
    # график
    cr = QRectF(x0, y0 + 220, 760, 300)
    p.setPen(QPen(QColor("#e4e7ec"), 1))
    for i in range(5):
        p.drawLine(QPointF(cr.left(), cr.top() + i * 70), QPointF(cr.right(), cr.top() + i * 70))
    vals = [42, 55, 48, 63, 71, 58, 80, 92, 76, 88, 97, 110]
    bw = cr.width() / len(vals)
    for i, v in enumerate(vals):
        h = v / 115 * 270
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#2f80ff") if i != 10 else QColor("#1d4ed8"))
        p.drawRoundedRect(QRectF(cr.left() + i * bw + 10, cr.top() + 280 - h, bw - 20, h), 5, 5)
    # форма справа
    fx = x0 + 820
    p.setPen(QColor("#101828"))
    p.setFont(font(20, True))
    p.drawText(QPointF(fx, y0 + 110), "Отправить отчет")
    for i, (lab, val) in enumerate((("Кому", "ivanov.sergey@example.ru"), ("Тема", "Продажи за ноябрь"))):
        yy = y0 + 140 + i * 86
        p.setPen(QColor("#475467"))
        p.setFont(font(14))
        p.drawText(QPointF(fx, yy + 14), lab)
        p.setPen(QPen(QColor("#d0d5dd"), 1))
        p.setBrush(QColor("#ffffff"))
        p.drawRoundedRect(QRectF(fx, yy + 24, 330, 42), 8, 8)
        p.setPen(QColor("#101828"))
        p.setFont(font(16))
        p.drawText(QRectF(fx + 14, yy + 24, 310, 42), Qt.AlignVCenter, val)
    br = QRectF(fx, y0 + 330, 160, 46)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#2f80ff"))
    p.drawRoundedRect(br, 8, 8)
    p.setPen(QColor("#ffffff"))
    p.setFont(font(16, True))
    p.drawText(br, Qt.AlignCenter, "Отправить")
    p.setPen(QColor("#475467"))
    p.setFont(font(15))
    for i, line in enumerate(("Отчет уйдет руководителю и бухгалтерии.",
                              "Копия сохранится в разделе «Архив».")):
        p.drawText(QPointF(fx, y0 + 420 + i * 26), line)
    p.end()
    return img


def save_webp(qimg, name, q=86):
    tmp = OUT / (name + ".png")
    qimg.save(str(tmp))
    im = Image.open(tmp).convert("RGB")
    im.save(OUT / (name + ".webp"), "WEBP", quality=q, method=6)
    tmp.unlink()
    return im


base = demo_desktop()
mon = [QRect(0, 0, W, H)]

# ---------- 1. редактор пометок ----------
from overlay import Overlay

cfg = config.defaults()
cfg.update(shot_dir=str(OUT / "_tmp"))
ov = Overlay(base, QPoint(0, 0), "shot", [], mon, cfg)


def ev(kind, x, y):
    t = {"press": QEvent.MouseButtonPress, "move": QEvent.MouseMove, "release": QEvent.MouseButtonRelease}[kind]
    btn = Qt.LeftButton
    QApplication.sendEvent(ov, QMouseEvent(t, QPointF(x, y), QPointF(x, y), btn if kind != "move" else Qt.NoButton,
                                           btn if kind != "release" else Qt.NoButton, Qt.NoModifier))


def drag(x1, y1, x2, y2):
    ev("press", x1, y1)
    for i in range(1, 7):
        ev("move", x1 + (x2 - x1) * i / 6, y1 + (y2 - y1) * i / 6)
    ev("release", x2, y2)


def click(x, y):
    ev("press", x, y)
    ev("release", x, y)


drag(195, 135, 1405, 735)                       # область
ov.set_tool("rect"); drag(212, 372, 990, 680)   # рамка вокруг графика
ov.set_tool("blur"); drag(1036, 320, 1396, 372)  # спрятать почту
ov.set_tool("number"); click(1015, 312); click(1015, 398)
ov.set_tool("arrow"); drag(1270, 600, 1160, 520)
ov.set_tool("text"); click(1180, 610)
ov.editor.insertPlainText("Нажмите сюда")
ov.commit_text()
ov.set_color("#ffd60a"); ov.set_tool("marker"); drag(220, 170, 482, 170)
ov.set_color("#ff2a2a"); ov.set_tool("arrow")
ov.selected = ov.last_drawn = None
app.processEvents()
g = ov.sel.united(ov.bar.geometry()).adjusted(-40, -40, 40, 30).intersected(QRect(0, 0, W, H))
shot = ov.grab(g).toImage()
im = save_webp(shot, "editor")
# картинка для соцсетей 1200×630
og = im.resize((1200, int(im.height * 1200 / im.width)))
canvas = Image.new("RGB", (1200, 630), (2, 6, 23))
canvas.paste(og.crop((0, 0, 1200, min(630, og.height))), (0, (630 - min(630, og.height)) // 2))
canvas.save(OUT / "og.png", optimize=True)
result = ov.render_result()
save_webp(result, "result")
ov.close()

# ---------- 2. запись видео: отсчёт и кнопка «Стоп» ----------
from recorder import Countdown, RecordPanel

area = QRect(260, 160, 1080, 600)
img = QImage(base)
p = QPainter(img)
cd = Countdown(area, 3, "Ctrl+Alt+PrtScn")
cd.render(p, cd.geometry().topLeft())
panel = RecordPanel(area, QRect(0, 0, W, H), "Ctrl+Alt+PrtScn")
panel._tick()
panel.render(p, panel.geometry().topLeft())
p.end()
save_webp(img.copy(QRect(200, 110, 1200, 740)), "video")

# ---------- 3. настройки: звук и микрофон, основное ----------
from recorder import Recorder
from settings import SettingsWindow


class FakeApp:
    def __init__(self):
        self.cfg = config.defaults()
        self.cfg.update(shot_dir=r"C:\Users\Иван\Desktop\Скриншоты", video_dir=r"C:\Users\Иван\Desktop\Скриншоты")
        self.tray = QSystemTrayIcon()
        self.recorder = Recorder()
        from updater import Updater
        self.updater = Updater()
        self.hk_failed_names = []

    def autostart_enabled(self):
        return True

    def apply_settings(self, c, a):
        pass

    def settings_closed(self, saved):
        pass

    def open_support(self):
        pass


fake = FakeApp()
fake.recorder.audio.ready.wait(60)
time.sleep(1.5)
w = SettingsWindow(fake)
w.show()
for _ in range(30):
    app.processEvents()
    time.sleep(0.03)
tabs = w.findChild(QTabWidget)
for idx, name in ((3, "settings-audio"), (0, "settings-main"), (2, "settings-video")):
    tabs.setCurrentIndex(idx)
    for _ in range(15):
        app.processEvents()
        time.sleep(0.03)
    save_webp(w.grab().toImage(), name, 90)
w.close()
print("готово:", sorted(p.name for p in OUT.iterdir()))
