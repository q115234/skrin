"""Пометки на скриншоте: стрелки, линии, рамки, овалы, карандаш, маркер, текст, номера, размытие."""
import math
from dataclasses import dataclass, field

from config import px
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath,
                           QPainterPathStroker, QPen, QPolygonF)

SIZES = [2, 4, 7, 11]
TOOLS = ["arrow", "line", "rect", "ellipse", "pen", "marker", "text", "number", "blur"]


@dataclass
class Shape:
    kind: str
    color: str
    width: int
    pts: list = field(default_factory=list)  # [(x, y), ...]
    text: str = ""
    num: int = 0

    def p(self, i):
        x, y = self.pts[i]
        return QPointF(x, y)

    def moved(self, dx, dy):
        self.pts = [(x + dx, y + dy) for x, y in self.pts]


def text_font(width):
    f = QFont("Segoe UI")
    f.setBold(True)
    f.setPixelSize(px({2: 16, 4: 22, 7: 30, 11: 42}.get(width, 22)))
    return f


def number_radius(width):
    return px({2: 12, 4: 16, 7: 21, 11: 28}.get(width, 16))


def contrast_for(color):
    c = QColor(color)
    lum = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
    return QColor(0, 0, 0, 200) if lum > 160 else QColor(255, 255, 255, 230)


def _rect(s):
    (x1, y1), (x2, y2) = s.pts[0], s.pts[-1]
    return QRectF(QPointF(x1, y1), QPointF(x2, y2)).normalized()


def _text_path(s):
    f = text_font(s.width)
    fm = QFontMetricsF(f)
    path = QPainterPath()
    x, y = s.pts[0]
    for i, line in enumerate(s.text.split("\n")):
        path.addText(QPointF(x, y + fm.ascent() + i * fm.lineSpacing()), f, line)
    return path


def text_box(s):
    f = text_font(s.width)
    fm = QFontMetricsF(f)
    lines = s.text.split("\n") or [""]
    w = max(fm.horizontalAdvance(l) for l in lines)
    x, y = s.pts[0]
    return QRectF(x, y, max(w, 4), fm.lineSpacing() * len(lines))


def pixelate(base: QImage, rect: QRectF):
    r = rect.toAlignedRect().intersected(base.rect())
    if r.width() < 2 or r.height() < 2:
        return None, r
    block = max(6, min(r.width(), r.height()) // 12, 10)
    piece = base.copy(r)
    small = piece.scaled(max(1, r.width() // block), max(1, r.height() // block),
                         Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    return small.scaled(r.width(), r.height(), Qt.IgnoreAspectRatio, Qt.FastTransformation), r


def draw_shape(p: QPainter, s: Shape, base: QImage = None):
    color = QColor(s.color)
    t = s.width
    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)
    k = s.kind
    if k == "arrow" and len(s.pts) >= 2:
        _draw_arrow(p, s.p(0), s.p(-1), t, color)
    elif k == "line" and len(s.pts) >= 2:
        p.setPen(QPen(color, t, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawLine(s.p(0), s.p(-1))
    elif k in ("rect", "ellipse") and len(s.pts) >= 2:
        p.setPen(QPen(color, t, Qt.SolidLine, Qt.SquareCap, Qt.MiterJoin))
        p.setBrush(Qt.NoBrush)
        r = _rect(s)
        if k == "rect":
            p.drawRect(r)
        else:
            p.drawEllipse(r)
    elif k in ("pen", "marker") and s.pts:
        path = QPainterPath(s.p(0))
        for i in range(1, len(s.pts)):
            path.lineTo(s.p(i))
        if k == "marker":
            c = QColor(color)
            c.setAlpha(110)
            p.setPen(QPen(c, t * 3 + 10, Qt.SolidLine, Qt.FlatCap if len(s.pts) > 1 else Qt.SquareCap, Qt.RoundJoin))
            p.setCompositionMode(QPainter.CompositionMode_Multiply if c.lightness() > 100 else QPainter.CompositionMode_SourceOver)
        else:
            p.setPen(QPen(color, t, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        if len(s.pts) == 1:
            p.drawPoint(s.p(0))
        else:
            p.drawPath(path)
    elif k == "text" and s.text:
        path = _text_path(s)
        p.setPen(QPen(contrast_for(s.color), max(3.0, text_font(t).pixelSize() / 7), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(color))
        p.drawPath(path)
    elif k == "number" and s.pts:
        r = number_radius(t)
        c = s.p(0)
        p.setPen(QPen(QColor(255, 255, 255), 2))
        p.setBrush(QBrush(color))
        p.drawEllipse(c, r, r)
        f = QFont("Segoe UI")
        f.setBold(True)
        f.setPixelSize(int(r * (1.15 if s.num < 10 else 0.95)))
        p.setFont(f)
        light = QColor(s.color).lightness() > 170
        p.setPen(QColor(0, 0, 0) if light else QColor(255, 255, 255))
        p.drawText(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), Qt.AlignCenter, str(s.num))
    elif k == "blur" and len(s.pts) >= 2 and base is not None:
        img, r = pixelate(base, _rect(s))
        if img is not None:
            p.drawImage(r.topLeft(), img)
    p.restore()


def _draw_arrow(p, a: QPointF, b: QPointF, t, color):
    dx, dy = b.x() - a.x(), b.y() - a.y()
    L = math.hypot(dx, dy)
    if L < 1:
        return
    ux, uy = dx / L, dy / L
    nx, ny = -uy, ux
    head = max(14.0, t * 4.0 + 8)
    half = max(8.0, t * 2.2 + 5)
    if head > L * 0.7:
        k = L * 0.7 / head
        head *= k
        half *= k
    base = QPointF(b.x() - ux * head, b.y() - uy * head)
    # стержень сужается от наконечника к началу
    w0, w1 = max(1.0, t * 0.35), t * 0.6
    shaft = QPolygonF([
        QPointF(a.x() + nx * w0, a.y() + ny * w0),
        QPointF(base.x() + nx * w1, base.y() + ny * w1),
        QPointF(base.x() - nx * w1, base.y() - ny * w1),
        QPointF(a.x() - nx * w0, a.y() - ny * w0),
    ])
    tip = QPolygonF([
        b,
        QPointF(base.x() + nx * half, base.y() + ny * half),
        QPointF(base.x() + ux * head * 0.12, base.y() + uy * head * 0.12),
        QPointF(base.x() - nx * half, base.y() - ny * half),
    ])
    path = QPainterPath()
    path.addPolygon(shaft)
    path.addPolygon(tip)
    path.setFillRule(Qt.WindingFill)
    path = path.simplified()
    p.setPen(QPen(QColor(255, 255, 255, 150), 1.2))
    p.setBrush(QBrush(color))
    p.drawPath(path)


def shape_bounds(s: Shape) -> QRectF:
    if s.kind == "text":
        return text_box(s)
    if s.kind == "number":
        r = number_radius(s.width)
        x, y = s.pts[0]
        return QRectF(x - r, y - r, 2 * r, 2 * r)
    xs = [x for x, _ in s.pts]
    ys = [y for _, y in s.pts]
    pad = s.width * 2 + 6 if s.kind != "marker" else s.width * 3 + 10
    return QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)).adjusted(-pad, -pad, pad, pad)


def hit_test(s: Shape, pt: QPointF) -> bool:
    k = s.kind
    if k in ("text", "number", "blur"):
        return shape_bounds(s).adjusted(-4, -4, 4, 4).contains(pt) if k != "blur" else _rect(s).contains(pt)
    path = QPainterPath()
    if k in ("arrow", "line"):
        path.moveTo(s.p(0))
        path.lineTo(s.p(-1))
    elif k == "rect":
        path.addRect(_rect(s))
    elif k == "ellipse":
        path.addEllipse(_rect(s))
    else:
        path.moveTo(s.p(0))
        for i in range(1, len(s.pts)):
            path.lineTo(s.p(i))
    st = QPainterPathStroker()
    st.setWidth((s.width * 3 + 10 if k == "marker" else s.width) + 10)
    return st.createStroke(path).contains(pt)
