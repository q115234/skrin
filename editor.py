"""Окно редактора: скриншот в обычном окне — смотреть рядом с другой работой, дорисовывать, копировать, сохранять.

Открывается кнопкой «Открыть в редакторе» (O) на панели скриншота, сразу после выделения (если так выбрано
в настройках) или из меню значка в трее — картинка из файла или из буфера обмена.
Рисование — тот же код, что и поверх экрана (Overlay), только в масштабе и внутри окна.
"""
import logging
import os
import subprocess
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QImage, QMouseEvent, QPainter, QPalette, QPen
from PySide6.QtWidgets import (QFileDialog, QFrame, QMenu, QMessageBox, QScrollArea, QToolBar, QToolButton,
                               QVBoxLayout, QWidget)

import winapi
from config import Rescaler, px, scale_for, screen_scale, ui_scale
from overlay import (COLORS, TOOL_NAMES, Overlay, TextEditor, _btn, color_icon, glyph_icon, size_icon,
                     tool_icon)
from shapes import draw_shape, hit_test, shape_bounds, text_box, text_font

log = logging.getLogger("skrin")

ZOOMS = [0.1, 0.25, 0.33, 0.5, 0.67, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0]
COLOR_NAMES = ["красный", "оранжевый", "жёлтый", "зелёный", "синий", "фиолетовый", "чёрный", "белый"]
VK_PLUS, VK_MINUS, VK_ADD, VK_SUB = 0xBB, 0xBD, 0x6B, 0x6D

EDITOR_CSS = """
QToolBar { background: #1e1f24; border: none; border-bottom: 1px solid rgba(255,255,255,30);
           padding: 3px; spacing: 2px; }
QToolBar::separator { background: rgba(255,255,255,40); width: 1px; margin: 6px 4px; }
QToolButton { color: #f0f0f0; background: transparent; border: none; border-radius: 6px;
              padding: 3px; min-width: %(btn)spx; min-height: %(btn)spx; font: %(font)spx 'Segoe UI'; }
QToolButton:hover { background: rgba(255,255,255,32); }
QToolButton:checked { background: rgba(0,150,255,110); }
QToolButton#accent { background: #0a84ff; color: white; padding: 3px 10px; font-weight: 600; }
QToolButton#accent:hover { background: #3b9bff; }
QToolButton#zoom { padding: 3px 6px; min-width: %(zw)spx; }
QToolButton#qt_toolbar_ext_button { background: rgba(255,255,255,40); min-width: %(ext)spx; }
QToolButton::menu-indicator { image: none; width: 0px; }
QMenu { background: #26272c; color: #f0f0f0; border: 1px solid rgba(255,255,255,40); font: %(font)spx 'Segoe UI'; }
QMenu::item { padding: 5px 18px 5px 8px; }
QMenu::item:selected { background: rgba(0,150,255,110); }
"""


def editor_css():
    return EDITOR_CSS % {"btn": px(34), "font": px(13), "zw": px(54), "ext": px(16)}


class ZoomTextEditor(TextEditor):
    """Поле ввода текста поверх холста с учётом масштаба."""

    def restyle(self):
        f = text_font(self.shape.width, self.shape.k)
        f.setPixelSize(max(1, round(f.pixelSize() * self.ov.zoom)))
        self.setFont(f)
        self.setStyleSheet(f"QPlainTextEdit {{ background: transparent; color: {self.shape.color}; border: none; }}")

    def _changed(self):
        z = self.ov.zoom
        self.shape.text = self.toPlainText()
        box = text_box(self.shape)
        self.move(round(box.x() * z), round(box.y() * z))
        self.setFixedSize(round(box.width() * z) + 40, round(box.height() * z) + 6)
        self.ov.update()


class Canvas(Overlay):
    """Холст редактора: Overlay, у которого выделена вся картинка, без затемнения, рамки и выхода по Esc."""

    def __init__(self, win, image: QImage, shapes, cfg, doc_k):
        rect = QRect(0, 0, image.width(), image.height())
        super().__init__(image, QPoint(0, 0), "shot", [], [rect], cfg)
        self.setWindowFlags(Qt.Widget)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.dim_pm = None
        self.win = win
        self._doc_k = doc_k  # масштаб монитора, откуда скриншот: текст и номера такого же размера, как там
        self.shapes = list(shapes)
        self.sel = rect
        self.state = "edit"
        self.zoom = 1.0
        self._scaled = None  # картинка в текущем масштабе
        self.setCursor(Qt.CrossCursor)
        self.set_zoom(1.0)

    # ---------- масштаб ----------
    def set_zoom(self, z):
        self.zoom = z
        self._scaled = None
        self.setFixedSize(QSize(max(1, round(self.base.width() * z)), max(1, round(self.base.height() * z))))
        if self.editor:
            self.editor.restyle()
            self.editor._changed()
        self.update()

    def update(self, *_):  # пометки рисуются в масштабе — перерисовываем холст целиком
        QWidget.update(self)

    def _map(self, e):
        if self.zoom == 1:
            return e
        return QMouseEvent(e.type(), e.position() / self.zoom, e.globalPosition(), e.button(), e.buttons(),
                           e.modifiers())

    # ---------- масштаб монитора: окно, а не экран целиком ----------
    def ui_k(self, pt):
        return self.win.sk.k

    def doc_k(self):
        return self._doc_k

    # ---------- то, чего в окне нет ----------
    def present(self):
        pass

    def place_bar(self):
        pass

    def _handle_at(self, pos):
        return None  # край картинки не тянется

    def record_area(self):
        pass

    def cancel(self):
        self.win.close()

    # ---------- результат: в окне, а не закрытием ----------
    def finish(self):
        self.commit_text()
        self.win.copy_out()

    def save_as(self):
        self.commit_text()
        self.win.save_as()

    # ---------- правки ----------
    def push_undo(self):
        super().push_undo()
        self.win.mark_dirty()

    def undo(self):
        super().undo()
        self.win.mark_dirty()

    def redo(self):
        super().redo()
        self.win.mark_dirty()

    def start_text(self, shape, new):
        self.push_undo()
        if new:
            self.shapes.append(shape)
        self.selected = None
        self.editor = ZoomTextEditor(self, shape)
        self.editor.show()
        self.editor.setFocus()
        self.update()

    # ---------- мышь ----------
    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            self.commit_text()
            return
        super().mousePressEvent(self._map(e))

    def mouseDoubleClickEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        m = self._map(e)
        hit = next((s for s in reversed(self.shapes) if s.kind == "text" and hit_test(s, m.position())), None)
        if hit is not None:
            if self.action and self.action[0] == "move":
                self.action = None
                if self.undo_stack:
                    self.undo_stack.pop()
            self.start_text(hit, new=False)
            return
        Overlay.mousePressEvent(self, m)

    def mouseMoveEvent(self, e):
        super().mouseMoveEvent(self._map(e))

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(self._map(e))

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            self.win.zoom_step(1 if e.angleDelta().y() > 0 else -1)
        elif self.win.scrollable():
            e.ignore()  # картинка не помещается — колесо прокручивает
        else:
            super().wheelEvent(e)  # помещается — колесо меняет толщину, как поверх экрана

    # ---------- клавиатура ----------
    def keyPressEvent(self, e):
        vk = e.nativeVirtualKey()
        ctrl = bool(e.modifiers() & Qt.ControlModifier)
        if e.key() == Qt.Key_Escape:
            if self.action and self.action[0] == "draw":
                self.current, self.action = None, None
                self.update()
            elif self.selected is not None:
                self.selected = None
                self.update()
            else:
                self.win.close()
            return
        if ctrl and vk in (VK_PLUS, VK_ADD):
            self.win.zoom_step(1)
        elif ctrl and vk in (VK_MINUS, VK_SUB):
            self.win.zoom_step(-1)
        elif ctrl and vk in (0x30, 0x60):  # Ctrl+0 — по размеру окна
            self.win.set_fit(True)
        elif ctrl and vk in (0x31, 0x61):  # Ctrl+1 — 100 %
            self.win.set_fit(False, 1.0)
        elif not ctrl and vk in (0x56, 0x4F):  # V (видео) и O (в редактор) здесь не нужны
            pass
        else:
            super().keyPressEvent(e)

    # ---------- рисование ----------
    def paintEvent(self, e):
        p = QPainter(self)
        z = self.zoom
        if z == 1:
            p.drawPixmap(0, 0, self.base_pm)
        else:
            if self._scaled is None or self._scaled.size() != self.size():
                self._scaled = self.base_pm.scaled(self.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            p.drawPixmap(0, 0, self._scaled)
            p.scale(z, z)
        for s in self.shapes:
            draw_shape(p, s, self.base)
        if self.current is not None:
            draw_shape(p, self.current, self.base)
        p.setRenderHint(QPainter.Antialiasing, False)
        p.setBrush(Qt.NoBrush)
        # рамка вокруг размытий — только на экране: на однотонном фоне мозаику не видно
        for s in self.shapes + [self.current]:
            if s is not None and s.kind == "blur" and len(s.pts) >= 2:
                self._dashed(p, QRectF(QPointF(*s.pts[0]), QPointF(*s.pts[-1])).normalized())
        target = self.editor.shape if self.editor else self.selected
        if target is not None:
            self._dashed(p, shape_bounds(target).adjusted(-4, -3, 4, 3))

    @staticmethod
    def _dashed(p, r):
        """Чёрно-белый пунктир толщиной в пиксель экрана при любом масштабе — виден на любом фоне."""
        for color, style in ((QColor(0, 0, 0, 160), Qt.SolidLine), (QColor(255, 255, 255, 235), Qt.DashLine)):
            pen = QPen(color, 1, style)
            pen.setCosmetic(True)
            p.setPen(pen)
            p.drawRect(r)


class EditorBar(QToolBar):
    """Панель редактора. Не помещается в узкое окно — лишнее уходит под кнопку «»» справа."""

    def __init__(self, win, cv):
        super().__init__(win)
        self.win, self.cv = win, cv
        self.setMovable(False)
        self.setFloatable(False)
        self._icon_btns = []
        self.rescale()
        # сначала действия — в узком окне они остаются на виду, а инструменты уходят под «»»
        self._b(glyph_icon(0xE8C8, "#ffffff"), "Скопировать в буфер обмена (и сохранить в папку, если так "
                "в настройках)  (Ctrl+C или Enter)", text="Ctrl+C", name="accent").clicked.connect(cv.finish)
        self._b(glyph_icon(0xE74E), "Сохранить как…  (Ctrl+S)").clicked.connect(cv.save_as)
        self._b(glyph_icon(0xE838), "Показать файл в папке (или открыть папку со скриншотами)").clicked.connect(
            win.open_folder)
        self.pin_btn = self._b(glyph_icon(0xE718), "Поверх всех окон — смотреть на скриншот, работая "
                               "в другой программе", checkable=True)
        self.pin_btn.toggled.connect(win.set_pinned)
        self.addSeparator()
        self.tool_btns = {}
        for kind, (name, key) in TOOL_NAMES.items():
            b = self._b(tool_icon(kind), f"{name}  ({key})", checkable=True)
            b.clicked.connect(lambda _=False, k=kind: cv.set_tool(k))
            self.tool_btns[kind] = b
        self.addSeparator()
        self.color_btn = self._b(color_icon(cv.color), "Цвет  (клавиши 1–8)")
        menu = QMenu(self)
        for i, c in enumerate(COLORS):
            a = menu.addAction(color_icon(c), f"{i + 1}   {COLOR_NAMES[i]}")
            a.triggered.connect(lambda _=False, cc=c: cv.set_color(cc))
        self.color_btn.setMenu(menu)
        self.color_btn.setPopupMode(QToolButton.InstantPopup)
        self.size_btn = self._b(size_icon(cv.width), "Толщина  (щелчок или колесо мыши)")
        self.size_btn.clicked.connect(cv.cycle_size)
        self.addSeparator()
        self._b(glyph_icon(0xE7A7), "Отменить  (Ctrl+Z)").clicked.connect(cv.undo)
        self._b(glyph_icon(0xE7A6), "Вернуть  (Ctrl+Y)").clicked.connect(cv.redo)
        self.addSeparator()
        self._b(glyph_icon(0xE71F), "Уменьшить  (Ctrl+колесо, Ctrl+−)").clicked.connect(lambda: win.zoom_step(-1))
        self.zoom_btn = self._b(None, "Масштаб: щелчок — по размеру окна (Ctrl+0) или 100 % (Ctrl+1)",
                                text="100 %", name="zoom")
        self.zoom_btn.clicked.connect(win.toggle_fit)
        self._b(glyph_icon(0xE8A3), "Увеличить  (Ctrl+колесо, Ctrl++)").clicked.connect(lambda: win.zoom_step(1))
        self.sync()

    def _b(self, icon, tip, text="", checkable=False, name=None):
        b = _btn(self, icon, tip, text, checkable, name)
        if icon is not None:
            b.setIconSize(QSize(px(24), px(24)))
            self._icon_btns.append(b)
        self.addWidget(b)
        return b

    def rescale(self):
        """Размеры кнопок под масштаб монитора (внутри ui_scale): окно перетащили на другой монитор."""
        icon = QSize(px(24), px(24))
        self.setIconSize(icon)
        self.setStyleSheet(editor_css())
        for b in self._icon_btns:
            b.setIconSize(icon)

    def sync(self):
        for k, b in self.tool_btns.items():
            b.setChecked(k == self.cv.tool)
        self.color_btn.setIcon(color_icon(self.cv.color))
        self.size_btn.setIcon(size_icon(self.cv.width))
        self.zoom_btn.setText(f"{round(self.cv.zoom * 100)} %")


class EditorWindow(QWidget):
    copied = Signal(str, QRect)  # путь сохранённого файла ("" — только буфер), где показать «Скопировано»
    closing = Signal(object)

    def __init__(self, image: QImage, shapes, cfg, area: QRect = None, path=None):
        super().__init__(None, Qt.Window)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.cfg = cfg
        self.path = Path(path) if path else None      # файл, откуда открыли или куда сохранили
        self.auto_path = None                         # файл, который сохранил Ctrl+C из этого окна
        self.dirty = bool(shapes)                     # есть пометки, которые нигде не сохранены
        self.fit = False
        pal = self.palette()
        pal.setColor(QPalette.Window, QColor(30, 31, 36))
        self.setPalette(pal)
        self.setAutoFillBackground(True)

        # окно — на мониторе выделенной области (картинка из файла или буфера — где мышь), и размеры — под него
        scr = (QGuiApplication.screenAt(area.center()) if area is not None else None) or \
            QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        self.sk = Rescaler(self, screen_scale(scr), resize=False)  # картинка — в пикселях экрана, окно не тянем
        self.canvas = Canvas(self, image, shapes, cfg, scale_for(area) if area is not None else self.sk.k)
        with ui_scale(self.sk.k):
            self.bar = EditorBar(self, self.canvas)
        self.canvas.bar = self.bar
        self.scroll = QScrollArea(self)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setAlignment(Qt.AlignCenter)
        self.scroll.setFocusPolicy(Qt.NoFocus)
        self.scroll.setWidget(self.canvas)
        vp = self.scroll.viewport()
        vpal = vp.palette()
        for role in (QPalette.Window, QPalette.Base):
            vpal.setColor(role, QColor(42, 43, 48))
        vp.setPalette(vpal)
        vp.setAutoFillBackground(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.bar)
        lay.addWidget(self.scroll, 1)

        ag = scr.availableGeometry()
        bar = self.bar.sizeHint()
        title_h = px(32, self.sk.k)
        w = min(max(bar.width(), image.width() + 2), int(ag.width() * 0.9))
        h = min(image.height() + bar.height() + 2, int(ag.height() * 0.9) - title_h)
        h = max(h, px(240, self.sk.k))
        self.sk.fit(self._fit_ui)
        self.resize(w, h)
        self.move(ag.center().x() - w // 2, max(ag.top(), ag.center().y() - (h + title_h) // 2))
        self._fits = image.width() + 2 <= w and image.height() + bar.height() + 2 <= h
        self._title()

    def _fit_ui(self):
        self.setMinimumSize(px(360), px(200))
        self.bar.rescale()
        if self.fit:
            QTimer.singleShot(0, lambda: self.fit and self._apply_zoom(self._fit_zoom()))

    def showEvent(self, e):
        super().showEvent(e)
        self.sk.follow()

    # ---------- показ ----------
    def present(self):
        self.show()
        self.raise_()
        self.activateWindow()
        winapi.force_foreground(self.winId())
        self.canvas.setFocus()
        if not self._fits:  # большая картинка — сразу целиком в окне
            QTimer.singleShot(0, lambda: self.set_fit(True))

    def _title(self):
        b = self.canvas.base
        name = self.path.name if self.path else "скриншот"
        self.setWindowTitle(f"{'• ' if self.dirty else ''}{name} — {b.width()}×{b.height()}, "
                            f"{round(self.canvas.zoom * 100)} % — Скрин")

    def mark_dirty(self):
        if not self.dirty:
            self.dirty = True
            self._title()

    # ---------- масштаб ----------
    def scrollable(self):
        return self.scroll.horizontalScrollBar().maximum() > 0 or self.scroll.verticalScrollBar().maximum() > 0

    def _fit_zoom(self):
        vp = self.scroll.viewport().size()
        b = self.canvas.base
        return min(1.0, vp.width() / max(1, b.width()), vp.height() / max(1, b.height()))

    def set_fit(self, on, zoom=None):
        self.fit = on
        policy = Qt.ScrollBarAlwaysOff if on else Qt.ScrollBarAsNeeded
        self.scroll.setHorizontalScrollBarPolicy(policy)
        self.scroll.setVerticalScrollBarPolicy(policy)
        self._apply_zoom(self._fit_zoom() if on else (zoom or self.canvas.zoom))

    def toggle_fit(self):
        if self.fit or abs(self._fit_zoom() - 1.0) < 0.001:
            self.set_fit(False, 1.0)
        else:
            self.set_fit(True)

    def zoom_step(self, d):
        z = self.canvas.zoom
        if d > 0:
            nz = next((v for v in ZOOMS if v > z + 0.001), ZOOMS[-1])
        else:
            nz = next((v for v in reversed(ZOOMS) if v < z - 0.001), ZOOMS[0])
        self.set_fit(False, nz)

    def _apply_zoom(self, z):
        if abs(z - self.canvas.zoom) > 0.0005:
            self.canvas.set_zoom(z)
        self.bar.sync()
        self._title()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.fit:
            QTimer.singleShot(0, lambda: self.fit and self._apply_zoom(self._fit_zoom()))

    # ---------- поверх всех окон ----------
    def set_pinned(self, on):
        geo = self.geometry()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, on)
        self.setGeometry(geo)
        self.show()
        self.canvas.setFocus()

    # ---------- результат ----------
    def copy_out(self):
        img = self.canvas.render_result()
        QGuiApplication.clipboard().setImage(img)
        saved = ""
        if self.cfg.get("save_on_copy", True):
            try:
                path = self.auto_path or self.canvas._auto_path()  # повторный Ctrl+C — тот же файл
                if self.canvas._save(img, path):
                    saved = str(path)
                    self.auto_path = self.path = Path(path)
            except Exception:
                log.exception("редактор: сохранение по Ctrl+C")
        self.dirty = False
        self._title()
        self.copied.emit(saved, self.frameGeometry())

    def save_as(self):
        img = self.canvas.render_result()
        start = str(self.path) if self.path else str(self.canvas._auto_path())
        filters = "PNG (*.png);;JPEG (*.jpg)" if not start.lower().endswith((".jpg", ".jpeg")) \
            else "JPEG (*.jpg);;PNG (*.png)"
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить скриншот", start, filters)
        if not path:
            return
        if not self.canvas._save(img, path):
            QMessageBox.warning(self, "Скрин", f"Не удалось сохранить файл:\n{path}")
            return
        self.path = Path(path)
        self.dirty = False
        self._title()

    def open_folder(self):
        if self.path and self.path.exists():
            subprocess.Popen(["explorer", "/select,", str(self.path)])
        else:
            folder = Path(self.cfg["shot_dir"])
            folder.mkdir(parents=True, exist_ok=True)
            os.startfile(str(folder))

    def closeEvent(self, e):
        self.canvas.commit_text()
        if self.dirty:
            box = QMessageBox(QMessageBox.Question, "Скрин",
                              "Пометки на скриншоте нигде не сохранены.\nСкопировать в буфер и сохранить в папку?",
                              parent=self)
            yes = box.addButton("Сохранить", QMessageBox.AcceptRole)
            box.addButton("Не сохранять", QMessageBox.DestructiveRole)
            cancel = box.addButton("Отмена", QMessageBox.RejectRole)
            box.setDefaultButton(yes)
            box.exec()
            if box.clickedButton() is cancel or box.clickedButton() is None:
                e.ignore()
                return
            if box.clickedButton() is yes:
                self.copy_out()
        cv = self.canvas
        self.cfg["tool"], self.cfg["color"], self.cfg["width"] = cv.tool, cv.color, cv.width
        self.closing.emit(self)
        super().closeEvent(e)


def load_image(path):
    img = QImage(str(path))
    if img.isNull():
        return None
    return img.convertToFormat(QImage.Format_RGB32)
