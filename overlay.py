"""Окно выделения области: скриншот с пометками или выбор области для записи видео."""
import copy
import math
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QCursor, QFont, QFontDatabase, QFontMetricsF, QGuiApplication, QIcon, QImage,
                           QPainter, QPen, QPixmap, QRegion)
from PySide6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QPlainTextEdit, QToolButton, QWidget)

import winapi
from config import hotkey_text, px
from shapes import SIZES, Shape, draw_shape, hit_test, shape_bounds, text_box, text_font

ACCENT = QColor(0, 160, 255)
COLORS = ["#ff2a2a", "#ff9500", "#ffd60a", "#22c55e", "#2f80ff", "#a855f7", "#111111", "#ffffff"]
TOOL_NAMES = {
    "arrow": ("Стрелка", "A"), "line": ("Линия", "L"), "rect": ("Прямоугольник", "R"),
    "ellipse": ("Овал", "E"), "pen": ("Карандаш", "P"), "marker": ("Маркер", "M"),
    "text": ("Текст", "T"), "number": ("Номер 1, 2, 3…", "N"),
    "blur": ("Размытие — спрятать почту, телефон, пароль: обведите область", "B"),
}
TOOL_VK = {0x41: "arrow", 0x4C: "line", 0x52: "rect", 0x45: "ellipse", 0x50: "pen",
           0x4D: "marker", 0x54: "text", 0x4E: "number", 0x42: "blur"}
VK_C, VK_S, VK_Z, VK_Y = 0x43, 0x53, 0x5A, 0x59

BAR_CSS = """
QFrame#bar { background: rgba(30,31,36,242); border: 1px solid rgba(255,255,255,45); border-radius: 9px; }
QToolButton { color: #f0f0f0; background: transparent; border: none; border-radius: 7px;
              padding: 4px; min-width: %(btn)spx; min-height: %(btn)spx; font: %(font)spx 'Segoe UI'; }
QToolButton:hover { background: rgba(255,255,255,32); }
QToolButton:checked { background: rgba(0,150,255,110); }
QToolButton#accent { background: #0a84ff; color: white; padding: 3px 10px; font-weight: 600; }
QToolButton#accent:hover { background: #3b9bff; }
QToolButton#rec { background: #e5333a; color: white; padding: 3px 12px; font-weight: 600; }
QToolButton#rec:hover { background: #f2545a; }
QToolButton#toggle { padding: 3px 10px; }
QFrame#sep { background: rgba(255,255,255,40); min-width: 1px; max-width: 1px; margin: 6px 3px; }
""" % {"btn": px(42), "font": px(14)}


def glyph_icon(code, color="#f0f0f0", size=20):
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    # «Segoe Fluent Icons» есть только в Windows 11; без неё QFont подставляет обычный шрифт,
    # у которого в той же области кодов бывают свои знаки — поэтому проверяем само семейство
    f = QFont("Segoe Fluent Icons")
    if "Segoe Fluent Icons" not in QFontDatabase.families() or not QFontMetricsF(f).inFont(chr(code)):
        f = QFont("Segoe MDL2 Assets")
    f.setPixelSize(int(size * 1.6))
    p.setFont(f)
    p.setPen(QColor(color))
    p.drawText(pm.rect(), Qt.AlignCenter, chr(code))
    p.end()
    return QIcon(pm)


def tool_icon(kind):
    s = 48
    pm = QPixmap(s, s)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    c = "#f0f0f0"
    if kind == "arrow":
        draw_shape(p, Shape("arrow", c, 5, [(9, 39), (39, 9)]))
    elif kind == "line":
        draw_shape(p, Shape("line", c, 4, [(9, 39), (39, 9)]))
    elif kind == "rect":
        draw_shape(p, Shape("rect", c, 4, [(8, 12), (40, 36)]))
    elif kind == "ellipse":
        draw_shape(p, Shape("ellipse", c, 4, [(7, 11), (41, 37)]))
    elif kind == "pen":
        pts = [(8 + i, 30 - 12 * math.sin(i / 6.0)) for i in range(0, 33, 2)]
        draw_shape(p, Shape("pen", c, 4, pts))
    elif kind == "marker":
        p.setPen(QPen(QColor(255, 214, 10, 200), 14, Qt.SolidLine, Qt.FlatCap))
        p.drawLine(8, 30, 40, 18)
    elif kind == "text":
        f = QFont("Segoe UI")
        f.setBold(True)
        f.setPixelSize(34)
        p.setFont(f)
        p.setPen(QColor(c))
        p.drawText(pm.rect(), Qt.AlignCenter, "A")
    elif kind == "number":
        draw_shape(p, Shape("number", "#ff2a2a", 7 if px(21) <= 22 else 4, [(24, 24)], num=1))
    elif kind == "blur":  # картинка: левая половина чёткая, правая — та же, но мозаикой
        pic = QImage(36, 28, QImage.Format_ARGB32)
        pic.fill(QColor("#8fd0ff"))  # небо
        q = QPainter(pic)
        q.setRenderHint(QPainter.Antialiasing)
        q.setPen(Qt.NoPen)
        q.setBrush(QColor("#ffd60a"))
        q.drawEllipse(QPointF(27, 8), 5, 5)  # солнце — на размытой половине
        q.setBrush(QColor("#22a559"))
        q.drawPolygon([QPointF(-2, 29), QPointF(11, 11), QPointF(21, 22), QPointF(28, 15),
                       QPointF(38, 29)])  # горы через обе половины
        q.end()
        x0, y0 = 6, 10
        p.drawImage(x0, y0, pic)
        half = pic.copy(18, 0, 18, 28)
        p.drawImage(x0 + 18, y0, half.scaled(4, 5, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                    .scaled(18, 28, Qt.IgnoreAspectRatio, Qt.FastTransformation))
        p.setPen(QPen(QColor(c), 2))
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(x0 - 1, y0 - 1, 38, 30))
        p.setPen(QPen(QColor("#0a84ff"), 2.5))
        p.drawLine(QPointF(x0 + 18, y0 - 4), QPointF(x0 + 18, y0 + 32))  # граница чёткого и размытого
    p.end()
    return QIcon(pm)


def blur_frames(p, shapes):
    """Пунктирная рамка вокруг размытий — только на экране, в готовую картинку не попадает.
    Без неё на однотонном фоне размытие не видно и непонятно, какую область оно закрывает."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing, False)
    p.setBrush(Qt.NoBrush)
    for s in shapes:
        if s is None or s.kind != "blur" or len(s.pts) < 2:
            continue
        r = QRectF(QPointF(*s.pts[0]), QPointF(*s.pts[-1])).normalized()
        for color, style in ((QColor(0, 0, 0, 170), Qt.SolidLine), (QColor(255, 255, 255, 240), Qt.DashLine)):
            pen = QPen(color, 1, style)
            pen.setCosmetic(True)
            p.setPen(pen)
            p.drawRect(r)
    p.restore()


def color_icon(color, size_px=None):
    s = 40
    pm = QPixmap(s, s)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(255, 255, 255, 120), 2))
    p.setBrush(QColor(color))
    r = 13 if size_px is None else size_px
    p.drawEllipse(QPointF(s / 2, s / 2), r, r)
    p.end()
    return QIcon(pm)


def size_icon(width):
    s = 40
    pm = QPixmap(s, s)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#f0f0f0"))
    r = {2: 3, 4: 5.5, 7: 8.5, 11: 12}[width]
    p.drawEllipse(QPointF(s / 2, s / 2), r, r)
    p.end()
    return QIcon(pm)


def _btn(parent, icon=None, tip="", text="", checkable=False, name=None):
    b = QToolButton(parent)
    b.setFocusPolicy(Qt.NoFocus)
    b.setCursor(Qt.PointingHandCursor)
    if icon is not None:
        b.setIcon(icon)
        b.setIconSize(QSize(px(32), px(32)))
    if text:
        b.setText(text)
        b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon if icon is not None else Qt.ToolButtonTextOnly)
    b.setToolTip(tip)
    b.setCheckable(checkable)
    if name:
        b.setObjectName(name)
    return b


def _sep(parent):
    f = QFrame(parent)
    f.setObjectName("sep")
    return f


class ShotBar(QFrame):
    def __init__(self, ov):
        super().__init__(ov)
        self.ov = ov
        self.setObjectName("bar")
        self.setStyleSheet(BAR_CSS)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(5, 4, 5, 4)
        lay.setSpacing(2)
        self.tool_btns = {}
        for kind, (name, key) in TOOL_NAMES.items():
            b = _btn(self, tool_icon(kind), f"{name}  ({key})", checkable=True)
            b.clicked.connect(lambda _=False, k=kind: ov.set_tool(k))
            lay.addWidget(b)
            self.tool_btns[kind] = b
        lay.addWidget(_sep(self))
        self.color_btns = {}
        for c in COLORS:
            b = _btn(self, color_icon(c), "Цвет", checkable=True)
            b.clicked.connect(lambda _=False, cc=c: ov.set_color(cc))
            lay.addWidget(b)
            self.color_btns[c] = b
        self.size_btn = _btn(self, size_icon(ov.width), "Толщина (колесо мыши)")
        self.size_btn.clicked.connect(ov.cycle_size)
        lay.addWidget(self.size_btn)
        lay.addWidget(_sep(self))
        b = _btn(self, glyph_icon(0xE7A7), "Отменить  (Ctrl+Z)")
        b.clicked.connect(ov.undo)
        lay.addWidget(b)
        b = _btn(self, glyph_icon(0xE7A6), "Вернуть  (Ctrl+Y)")
        b.clicked.connect(ov.redo)
        lay.addWidget(b)
        lay.addWidget(_sep(self))
        b = _btn(self, glyph_icon(0xE714, "#ff6b70"), "Записать видео этой области  (V)\n"
                 f"Стоп — кнопкой «Стоп» или {hotkey_text(ov.cfg.get('hk_video', [3, 0x2C]))}")
        b.clicked.connect(ov.record_area)
        lay.addWidget(b)
        b = _btn(self, glyph_icon(0xE8A7), "Открыть в редакторе — отдельное окно: смотреть рядом с другой "
                 "работой, дорисовать, скопировать  (O)")
        b.clicked.connect(ov.open_editor)
        lay.addWidget(b)
        b = _btn(self, glyph_icon(0xE74E), "Сохранить как…  (Ctrl+S)")
        b.clicked.connect(ov.save_as)
        lay.addWidget(b)
        b = _btn(self, glyph_icon(0xE8C8, "#ffffff"), "Скопировать в буфер и сохранить в папку  (Ctrl+C или Enter)",
                 text="Ctrl+C", name="accent")
        b.clicked.connect(ov.finish)
        lay.addWidget(b)
        b = _btn(self, glyph_icon(0xE711), "Закрыть  (Esc)")
        b.clicked.connect(ov.cancel)
        lay.addWidget(b)
        self.sync()

    def sync(self):
        for k, b in self.tool_btns.items():
            b.setChecked(k == self.ov.tool)
        for c, b in self.color_btns.items():
            b.setChecked(c == self.ov.color)
        self.size_btn.setIcon(size_icon(self.ov.width))


class VideoBar(QFrame):
    def __init__(self, ov):
        super().__init__(ov)
        self.ov = ov
        self.setObjectName("bar")
        self.setStyleSheet(BAR_CSS)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(5, 4, 5, 4)
        lay.setSpacing(4)
        b = _btn(self, glyph_icon(0xE7C8, "#ffffff"), "Начать запись  (Enter)", text="Записать", name="rec")
        b.clicked.connect(ov.start_record)
        lay.addWidget(b)
        self.mic = _btn(self, glyph_icon(0xE720), "Записывать микрофон", text="Микрофон", checkable=True, name="toggle")
        self.mic.setChecked(ov.cfg.get("mic", True))
        lay.addWidget(self.mic)
        self.sys = _btn(self, glyph_icon(0xE767), "Записывать звук компьютера", text="Звук ПК", checkable=True,
                        name="toggle")
        self.sys.setChecked(ov.cfg.get("system_audio", True))
        lay.addWidget(self.sys)
        lay.addWidget(_sep(self))
        b = _btn(self, glyph_icon(0xE711), "Отмена  (Esc)")
        b.clicked.connect(ov.cancel)
        lay.addWidget(b)


class TextEditor(QPlainTextEdit):
    def __init__(self, ov, shape):
        super().__init__(ov)
        self.ov = ov
        self.shape = shape
        self.setFrameStyle(0)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.document().setDocumentMargin(0)
        self.setContentsMargins(0, 0, 0, 0)
        self.setViewportMargins(0, 0, 0, 0)
        self.restyle()
        self.setPlainText(shape.text)
        self.moveCursor(self.textCursor().MoveOperation.End)
        self.textChanged.connect(self._changed)
        self._changed()

    def restyle(self):
        self.setFont(text_font(self.shape.width))
        self.setStyleSheet(f"QPlainTextEdit {{ background: transparent; color: {self.shape.color}; border: none; }}")

    def _changed(self):
        self.shape.text = self.toPlainText()
        box = text_box(self.shape)
        self.move(int(box.x()), int(box.y()))
        self.setFixedSize(int(box.width()) + 40, int(box.height()) + 6)
        self.ov.update()

    def keyPressEvent(self, e):
        ctrl = bool(e.modifiers() & Qt.ControlModifier)
        vk = e.nativeVirtualKey()
        if e.key() == Qt.Key_Escape:
            self.ov.commit_text()
            return
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            if ctrl:
                self.ov.commit_text()
                self.ov.finish()
            elif e.modifiers() & Qt.ShiftModifier:
                self.insertPlainText("\n")
            else:
                self.ov.commit_text()
            return
        if ctrl and vk == VK_C and not self.textCursor().hasSelection():
            self.ov.commit_text()
            self.ov.finish()
            return
        super().keyPressEvent(e)


class Overlay(QWidget):
    closed = Signal()
    record = Signal(QRect, bool, bool)  # область в экранных координатах, микрофон, звук ПК
    copied = Signal(str, QRect)  # путь сохранённого файла ("" — только буфер), область на экране
    to_editor = Signal(QImage, object, QRect)  # картинка области, пометки в её координатах, область на экране

    def __init__(self, image: QImage, origin: QPoint, mode, windows, monitors, cfg):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.mode = mode
        self.cfg = cfg
        self.origin = origin
        self.base = image
        self.base_pm = QPixmap.fromImage(image)
        dim = QImage(image)
        p = QPainter(dim)
        p.fillRect(dim.rect(), QColor(0, 0, 0, 170))
        p.end()
        self.dim_pm = QPixmap.fromImage(dim)
        self.bounds = QRect(0, 0, image.width(), image.height())
        self.windows = [QRect(QPoint(l, t) - origin, QPoint(r - 1, b - 1) - origin) for l, t, r, b in windows]
        self.monitors = [m.translated(-origin) for m in monitors]

        self.state = "select"
        self.sel = None
        self.hover = None
        self.drag_from = None
        self.drag_rect = None
        self.mouse = QPoint(-1000, -1000)
        self.tool = cfg.get("tool", "arrow")
        self.color = cfg.get("color", COLORS[0])
        self.width = cfg.get("width", 4)
        self.shapes = []
        self.undo_stack, self.redo_stack = [], []
        self.current = None
        self.selected = None
        self.action = None  # ('draw'|'move'|'resize'|'movesel', ...)
        self.editor = None
        self.bar = None
        self._width_target = None
        self.last_drawn = None

        self.setGeometry(QRect(origin, image.size()))
        self.setCursor(Qt.CrossCursor)

    # ---------- показ ----------
    def present(self):
        self.show()
        self.raise_()
        self.activateWindow()
        winapi.force_foreground(self.winId())
        self.setFocus()
        self._update_hover(self.mapFromGlobal(QCursor.pos()))

    def cancel(self):
        self.close()

    def closeEvent(self, e):
        self.cfg["tool"], self.cfg["color"], self.cfg["width"] = self.tool, self.color, self.width
        if self.mode == "video" and isinstance(self.bar, VideoBar):
            self.cfg["mic"], self.cfg["system_audio"] = self.bar.mic.isChecked(), self.bar.sys.isChecked()
        self.closed.emit()
        super().closeEvent(e)
        # Утечка памяти 1.3.0 (25.11.2026): окно и панель кнопок ссылаются друг на друга (bar.ov, лямбды
        # кнопок), такую петлю освобождает только редкий полный проход сборщика мусора Python — и до него
        # в памяти висели три копии всего экрана (на 3 мониторах по ~77 МБ), +75–150 МБ на каждый
        # скриншот с панелью; за полтора дня Скрин дорос до 2,5 ГБ. Всё нужное считается до close(),
        # поэтому картинки отпускаем сразу, а петлю рвём.
        self.base = self.base_pm = self.dim_pm = None
        if self.bar is not None:
            self.bar.ov = None
        self.bar = None

    # ---------- геометрия ----------
    def _monitor_at(self, pt):
        for m in self.monitors:
            if m.contains(pt):
                return m
        return min(self.monitors, key=lambda m: (m.center() - pt).manhattanLength())

    def _monitor_for(self, r: QRect):
        return max(self.monitors, key=lambda m: m.intersected(r).width() * m.intersected(r).height())

    def _candidate(self, pt):
        for w in self.windows:
            if w.contains(pt):
                return w.intersected(self._monitor_at(pt)) if self.mode == "video" else w.intersected(self.bounds)
        return self._monitor_at(pt)

    def _handles(self):
        r = QRectF(self.sel)
        pts = [r.topLeft(), QPointF(r.center().x(), r.top()), r.topRight(), QPointF(r.right(), r.center().y()),
               r.bottomRight(), QPointF(r.center().x(), r.bottom()), r.bottomLeft(), QPointF(r.left(), r.center().y())]
        return pts

    def _handle_at(self, pos):
        if not self.sel:
            return None
        for i, h in enumerate(self._handles()):
            if abs(h.x() - pos.x()) <= px(7) and abs(h.y() - pos.y()) <= px(7):
                return i
        return None

    def _upd(self, *rects):
        reg = QRegion()
        for r in rects:
            if r is not None:
                reg = reg.united(QRegion(r.adjusted(-60, -40, 60, 40)))
        self.update(reg)

    # ---------- состояние ----------
    def enter_edit(self, rect: QRect):
        rect = rect.normalized().intersected(self.bounds)
        if self.mode == "video":
            rect = rect.intersected(self._monitor_for(rect))
        if rect.width() < 4 or rect.height() < 4:
            self.state = "select"
            return
        self.sel = rect
        self.state = "edit"
        self.hover = None
        if self.mode == "shot" and self.cfg.get("open_editor"):  # в настройках: выделил — сразу в редактор
            self.open_editor()
            return
        if self.bar is None:
            self.bar = ShotBar(self) if self.mode == "shot" else VideoBar(self)
            self.bar.show()
            self.bar.adjustSize()
            QTimer.singleShot(0, self.place_bar)  # после применения стилей размер панели уточняется
        self.place_bar()
        self.update()

    def place_bar(self):
        if not self.bar or not self.sel:
            return
        self.bar.adjustSize()
        b = self.bar.size()
        mon = self._monitor_for(self.sel)
        x = max(mon.left() + 4, min(self.sel.right() - b.width(), mon.right() - b.width() - 4))
        for y in (self.sel.bottom() + 10, self.sel.top() - b.height() - 10, self.sel.bottom() - b.height() - 10):
            if mon.top() + 2 <= y and y + b.height() <= mon.bottom() - 2:
                break
        self.bar.setGeometry(x, y, b.width(), b.height())

    def set_tool(self, t):
        self.commit_text()
        self.tool = t
        self.selected = self.last_drawn = None
        if self.bar and self.mode == "shot":
            self.bar.sync()
        self.update()

    def set_color(self, c):
        self.color = c
        target = self.editor.shape if self.editor else self.selected
        if target is not None:
            if not self.editor:
                self.push_undo()
            target.color = c
            if self.editor:
                self.editor.restyle()
        self.bar.sync()
        self.update()

    def set_width(self, w):
        self.width = w
        if self.current is not None:  # рисуем прямо сейчас — меняем на лету
            self.current.width = w
        target = self.editor.shape if self.editor else (self.selected or self.last_drawn)
        if target is not None:
            if not self.editor and target is not self._width_target:
                self.push_undo()  # серия прокруток колеса — один шаг отмены
                self._width_target = target
            target.width = w
            if self.editor:
                self.editor.restyle()
                self.editor._changed()
        if self.bar and self.mode == "shot":
            self.bar.sync()
        self.update()

    def cycle_size(self):
        i = SIZES.index(self.width) if self.width in SIZES else 1
        self.set_width(SIZES[(i + 1) % len(SIZES)])

    # ---------- отмена ----------
    def push_undo(self):
        self.undo_stack.append(copy.deepcopy(self.shapes))
        self.redo_stack.clear()
        self._width_target = None

    def undo(self):
        self.commit_text()
        if self.undo_stack:
            self.redo_stack.append(copy.deepcopy(self.shapes))
            self.shapes = self.undo_stack.pop()
            self.selected = self.last_drawn = None
            self.update()

    def redo(self):
        self.commit_text()
        if self.redo_stack:
            self.undo_stack.append(copy.deepcopy(self.shapes))
            self.shapes = self.redo_stack.pop()
            self.selected = self.last_drawn = None
            self.update()

    # ---------- текст ----------
    def start_text(self, shape, new):
        if new:
            self.push_undo()
            self.shapes.append(shape)
        else:
            self.push_undo()
        self.selected = None
        self.editor = TextEditor(self, shape)
        self.editor.show()
        self.editor.setFocus()
        self.update()

    def commit_text(self):
        if not self.editor:
            return
        ed, self.editor = self.editor, None
        s = ed.shape
        s.text = ed.toPlainText().rstrip()
        if not s.text.strip():
            if s in self.shapes:
                self.shapes.remove(s)
            if self.undo_stack:
                self.undo_stack.pop()
        else:
            self.last_drawn = s  # колесо сразу меняет этот текст
        ed.hide()
        ed.deleteLater()
        self.setFocus()
        self.update()

    def _next_number(self):
        return max([s.num for s in self.shapes if s.kind == "number"], default=0) + 1

    # ---------- мышь ----------
    def mousePressEvent(self, e):
        pos = e.position().toPoint()
        posf = e.position()
        if e.button() == Qt.RightButton:
            if self.editor:
                self.commit_text()
            elif self.state == "edit" and not self.shapes and self.action is None:
                self.state, self.sel = "select", None
                if self.bar:
                    self.bar.deleteLater()
                    self.bar = None
                self._update_hover(pos)
                self.update()
            return
        if e.button() != Qt.LeftButton:
            return
        self.last_drawn = None
        if self.state == "select":
            self.drag_from = pos
            self.drag_rect = None
            return
        if self.editor:
            self.commit_text()
            return
        h = self._handle_at(pos)
        if h is not None:
            self.action = ("resize", h, QRect(self.sel))
            return
        if self.mode == "video":
            if self.sel.contains(pos):
                self.action = ("movesel", pos, QRect(self.sel))
            return
        if not self.sel.contains(pos):
            self.selected = None
            self.update()
            return
        hit = next((s for s in reversed(self.shapes) if hit_test(s, posf)), None)
        if hit is not None:
            if hit.kind == "text" and (self.tool == "text" or e.type() == QEvent.Type.MouseButtonDblClick):
                self.start_text(hit, new=False)
                return
            self.selected = hit
            self.push_undo()
            self.action = ("move", posf, False)
            self.update()
            return
        self.selected = None
        pt = (posf.x(), posf.y())
        if self.tool == "text":
            self.start_text(Shape("text", self.color, self.width, [pt]), new=True)
            return
        if self.tool == "number":
            self.push_undo()
            self.last_drawn = Shape("number", self.color, self.width, [pt], num=self._next_number())
            self.shapes.append(self.last_drawn)
            self.update()
            return
        self.current = Shape(self.tool, self.color, self.width, [pt] if self.tool in ("pen", "marker") else [pt, pt])
        self.action = ("draw",)

    def mouseDoubleClickEvent(self, e):
        posf = e.position()
        if self.state == "edit" and self.mode == "shot" and e.button() == Qt.LeftButton:
            hit = next((s for s in reversed(self.shapes) if s.kind == "text" and hit_test(s, posf)), None)
            if hit is not None:
                if self.action and self.action[0] == "move":
                    self.action = None
                    if self.undo_stack:
                        self.undo_stack.pop()
                self.start_text(hit, new=False)
                return
        self.mousePressEvent(e)

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()
        posf = e.position()
        old_mouse, self.mouse = self.mouse, pos
        if self.state == "select":
            if self.drag_from is not None and e.buttons() & Qt.LeftButton:
                if self.drag_rect is not None or (pos - self.drag_from).manhattanLength() > 4:
                    old = self.drag_rect
                    self.drag_rect = QRect(self.drag_from, pos).normalized()
                    # Подсвеченное окно гаснет в момент начала выделения — его место тоже перерисовать.
                    # Иначе окно оставалось светлым, а затемнение дорисовывалось только полосой вокруг
                    # растущей рамки и «расползалось» ступеньками, как тень (баг 1.3.0, 25.11.2026).
                    old_hover, self.hover = self.hover, None
                    self._upd(old, old_hover, self.drag_rect, self._hint_rect(old_mouse), self._hint_rect(pos))
            else:
                self._update_hover(pos, old_mouse)
            return
        a = self.action
        if a is None:
            self._update_cursor(pos)
            return
        if a[0] == "resize":
            _, h, r0 = a
            r = QRect(r0)
            if h in (0, 6, 7):
                r.setLeft(pos.x())
            if h in (2, 3, 4):
                r.setRight(pos.x())
            if h in (0, 1, 2):
                r.setTop(pos.y())
            if h in (4, 5, 6):
                r.setBottom(pos.y())
            r = r.normalized().intersected(self.bounds)
            if self.mode == "video":
                r = r.intersected(self._monitor_for(r0))
            if r.width() >= 4 and r.height() >= 4:
                self.sel = r
                self.place_bar()
                self.update()
        elif a[0] == "movesel":
            _, start, r0 = a
            r = r0.translated(pos - start)
            mon = self._monitor_for(r0)
            r.moveLeft(max(mon.left(), min(r.left(), mon.right() - r.width() + 1)))
            r.moveTop(max(mon.top(), min(r.top(), mon.bottom() - r.height() + 1)))
            self.sel = r
            self.place_bar()
            self.update()
        elif a[0] == "move":
            _, last, moved = a
            d = posf - last
            self.selected.moved(d.x(), d.y())
            self.action = ("move", posf, True)
            self.update()
        elif a[0] == "draw":
            s = self.current
            if s.kind in ("pen", "marker"):
                lx, ly = s.pts[-1]
                if abs(posf.x() - lx) + abs(posf.y() - ly) >= 1.5:
                    s.pts.append((posf.x(), posf.y()))
            else:
                x0, y0 = s.pts[0]
                x, y = posf.x(), posf.y()
                if e.modifiers() & Qt.ShiftModifier:
                    dx, dy = x - x0, y - y0
                    if s.kind in ("rect", "ellipse", "blur"):
                        m = max(abs(dx), abs(dy))
                        x, y = x0 + math.copysign(m, dx or 1), y0 + math.copysign(m, dy or 1)
                    else:
                        ang = round(math.atan2(dy, dx) / (math.pi / 4)) * (math.pi / 4)
                        L = math.hypot(dx, dy)
                        x, y = x0 + L * math.cos(ang), y0 + L * math.sin(ang)
                s.pts[-1] = (x, y)
            self.update(self.sel)

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        pos = e.position().toPoint()
        if self.state == "select":
            if self.drag_from is None:
                return
            r = self.drag_rect if self.drag_rect is not None else self._candidate(pos)
            self.drag_from = self.drag_rect = None
            self.enter_edit(r)
            return
        a, self.action = self.action, None
        if a is None:
            return
        if a[0] == "draw":
            s, self.current = self.current, None
            ok = True
            if s.kind not in ("pen", "marker"):
                (x0, y0), (x1, y1) = s.pts[0], s.pts[-1]
                ok = math.hypot(x1 - x0, y1 - y0) >= 4
            if ok:
                self.push_undo()
                self.shapes.append(s)
                self.last_drawn = s  # колесо сразу меняет только что нарисованное
            self.update(self.sel)
        elif a[0] == "move" and not a[2]:
            if self.undo_stack:
                self.undo_stack.pop()

    def wheelEvent(self, e):
        if self.state == "edit" and self.mode == "shot":
            i = SIZES.index(self.width) if self.width in SIZES else 1
            i = min(len(SIZES) - 1, i + 1) if e.angleDelta().y() > 0 else max(0, i - 1)
            if SIZES[i] != self.width:
                self.set_width(SIZES[i])

    @staticmethod
    def _hint_rect(pt):
        return QRect(pt + QPoint(10, 20), QSize(px(700), px(44)))

    def _update_hover(self, pos, old_mouse=None):
        old = self.hover
        self.hover = self._candidate(pos)
        self.mouse = pos
        hints = (self._hint_rect(pos), self._hint_rect(old_mouse or pos))
        if old != self.hover:
            self._upd(old, self.hover, *hints)
        else:
            self._upd(*hints)

    def _update_cursor(self, pos):
        h = self._handle_at(pos)
        if h is not None:
            self.setCursor([Qt.SizeFDiagCursor, Qt.SizeVerCursor, Qt.SizeBDiagCursor, Qt.SizeHorCursor] [h % 4])
        elif self.sel.contains(pos):
            if self.mode == "video":
                self.setCursor(Qt.SizeAllCursor)
            elif any(hit_test(s, QPointF(pos)) for s in self.shapes):
                self.setCursor(Qt.SizeAllCursor)
            else:
                self.setCursor(Qt.IBeamCursor if self.tool == "text" else Qt.CrossCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

    # ---------- клавиатура ----------
    def keyPressEvent(self, e):
        k = e.key()
        vk = e.nativeVirtualKey()
        mods = e.modifiers()
        ctrl = bool(mods & Qt.ControlModifier)
        if k == Qt.Key_Escape:
            if self.action and self.action[0] == "draw":
                self.current, self.action = None, None
                self.update()
            else:
                self.cancel()
            return
        if self.state != "edit":
            return
        if self.mode == "video":
            if k in (Qt.Key_Return, Qt.Key_Enter):
                self.start_record()
            return
        if k in (Qt.Key_Return, Qt.Key_Enter) or (ctrl and vk == VK_C):
            self.finish()
        elif ctrl and vk == VK_S:
            self.save_as()
        elif ctrl and (vk == VK_Y or (vk == VK_Z and mods & Qt.ShiftModifier)):
            self.redo()
        elif ctrl and vk == VK_Z:
            self.undo()
        elif k in (Qt.Key_Delete, Qt.Key_Backspace) and self.selected is not None:
            self.push_undo()
            self.shapes.remove(self.selected)
            self.selected = None
            self.update()
        elif not ctrl and vk == 0x56:  # V
            self.record_area()
        elif not ctrl and vk == 0x4F:  # O
            self.open_editor()
        elif not ctrl and vk in TOOL_VK:
            self.set_tool(TOOL_VK[vk])
        elif not ctrl and 0x31 <= vk <= 0x38:
            self.set_color(COLORS[vk - 0x31])

    # ---------- результат ----------
    def render_result(self) -> QImage:
        out = self.base.copy(self.sel)
        p = QPainter(out)
        p.translate(-self.sel.x(), -self.sel.y())
        for s in self.shapes:
            draw_shape(p, s, self.base)
        p.end()
        return out

    def _ext(self):
        return "jpg" if self.cfg.get("shot_format") == "jpg" else "png"

    def _auto_path(self):
        folder = Path(self.cfg["shot_dir"])
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
        ext = self._ext()
        path = folder / f"Скриншот {stamp}.{ext}"
        n = 2
        while path.exists():
            path = folder / f"Скриншот {stamp} ({n}).{ext}"
            n += 1
        return path

    def _save(self, img, path):
        if str(path).lower().endswith((".jpg", ".jpeg")):
            return img.save(str(path), "JPG", int(self.cfg.get("jpg_quality", 90)))
        return img.save(str(path), "PNG")

    def finish(self):
        self.commit_text()
        if self.state != "edit":
            return
        img = self.render_result()
        QGuiApplication.clipboard().setImage(img)
        saved = ""
        if self.cfg.get("save_on_copy", True):
            try:
                path = self._auto_path()
                if self._save(img, path):
                    saved = str(path)
            except Exception:
                pass
        area = QRect(self.sel).translated(self.origin)
        self.close()
        self.copied.emit(saved, area)

    def save_as(self):
        self.commit_text()
        img = self.render_result()
        self.hide()
        path, _ = QFileDialog.getSaveFileName(None, "Сохранить скриншот", str(self._auto_path()),
                                              "PNG (*.png);;JPEG (*.jpg)" if self._ext() == "png"
                                              else "JPEG (*.jpg);;PNG (*.png)")
        if not path:
            self.present()
            return
        self._save(img, path)
        QGuiApplication.clipboard().setImage(img)
        self.close()

    def open_editor(self):
        """Выделенную область с пометками — в отдельное окно редактора (editor.py)."""
        self.commit_text()
        if self.state != "edit" or self.mode != "shot":
            return
        img = self.base.copy(self.sel)
        shapes = copy.deepcopy(self.shapes)
        for s in shapes:
            s.moved(-self.sel.x(), -self.sel.y())
        area = QRect(self.sel).translated(self.origin)
        self.close()
        self.to_editor.emit(img, shapes, area)

    def record_area(self):
        """Кнопка камеры на панели скриншота: сразу записать видео выделенной области."""
        self.commit_text()
        if self.state != "edit":
            return
        r = QRect(self.sel)
        r.translate(self.origin)
        mic, system = self.cfg.get("mic", True), self.cfg.get("system_audio", True)
        self.close()
        self.record.emit(r, mic, system)

    def start_record(self):
        if self.state != "edit":
            return
        r = QRect(self.sel)
        r.translate(self.origin)
        mic, system = self.bar.mic.isChecked(), self.bar.sys.isChecked()
        self.close()
        self.record.emit(r, mic, system)

    # ---------- рисование ----------
    def paintEvent(self, e):
        if self.base_pm is None:  # окно уже закрыто, картинки отпущены (у холста редактора свой paintEvent)
            return
        p = QPainter(self)
        for r in e.region():
            p.drawPixmap(r, self.dim_pm, r)
        bright = self.sel or self.drag_rect or self.hover
        if bright is not None:
            for r in e.region():
                ir = bright.intersected(r)
                if not ir.isEmpty():
                    p.drawPixmap(ir, self.base_pm, ir)
        if self.state == "edit" and self.mode == "shot":
            p.save()
            p.setClipRect(self.sel)
            for s in self.shapes:
                draw_shape(p, s, self.base)
            if self.current is not None:
                draw_shape(p, self.current, self.base)
            blur_frames(p, self.shapes + [self.current])
            p.restore()
            p.setRenderHint(QPainter.Antialiasing, False)
            target = self.editor.shape if self.editor else self.selected
            if target is not None:
                p.setPen(QPen(QColor(255, 255, 255, 220), 1, Qt.DashLine))
                p.setBrush(Qt.NoBrush)
                p.drawRect(shape_bounds(target).adjusted(-4, -3, 4, 3).toAlignedRect())
        if bright is not None:
            p.setRenderHint(QPainter.Antialiasing, False)
            if self.mode == "video" and self.state == "edit":
                p.setPen(QPen(QColor(229, 51, 58), 2, Qt.DashLine))
            else:
                p.setPen(QPen(ACCENT, 2 if bright is self.hover else 1))
            p.setBrush(Qt.NoBrush)
            p.drawRect(bright.adjusted(0, 0, -1, -1))
            if self.sel is not None:
                p.setPen(QPen(QColor(255, 255, 255), 1))
                p.setBrush(ACCENT)
                for h in self._handles():
                    hs = px(7)
                    p.drawRect(QRectF(h.x() - hs / 2, h.y() - hs / 2, hs, hs))
            self._draw_label(p, bright, f"{bright.width()} × {bright.height()}")
        if self.state == "select":
            hint = ("Выделите область или щёлкните по окну · Esc — отмена" if self.mode == "shot"
                    else "Запись видео: выделите область, щёлкните по окну или по экрану · Esc — отмена")
            self._draw_label(p, QRect(self.mouse + QPoint(18, 26), QSize(1, 1)), hint, below=True)

    def _draw_label(self, p, r, text, below=False):
        f = QFont("Segoe UI")
        f.setPixelSize(px(13))
        p.setFont(f)
        fm = QFontMetricsF(f)
        w, h = fm.horizontalAdvance(text) + 16, fm.height() + 8
        if below:
            x, y = r.left(), r.top()
        else:
            x, y = r.left(), r.top() - h - 6
            if y < self._monitor_at(r.topLeft()).top():
                x, y = r.left() + 6, r.top() + 6
        box = QRectF(x, y, w, h)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(20, 20, 24, 215))
        p.drawRoundedRect(box, 5, 5)
        p.setPen(QColor(240, 240, 240))
        p.drawText(box, Qt.AlignCenter, text)
