"""Запись видео области экрана: ffmpeg ddagrab + кодировщик видеокарты (NVENC/AMF) или x264,
звук ПК и микрофон через WASAPI, сведение в mp4."""
import logging
import re
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QWidget

import winapi
from audio import AudioCapture, AudioHost
from config import FFMPEG, px, scale_for

NOWIN = subprocess.CREATE_NO_WINDOW
log = logging.getLogger("skrin")

ENCODER_NAMES = {"nvenc": "видеокарта NVIDIA (NVENC)", "amf": "видеокарта AMD (AMF)",
                 "x264": "процессор (x264)"}
QUALITY_Q = {"normal": 28, "high": 23, "max": 19}


def detect_encoder():
    """Какой кодировщик видеокарты работает на этом ПК (проба 3 кадра)."""
    for name, codec in (("nvenc", "h264_nvenc"), ("amf", "h264_amf")):
        try:
            r = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                                "color=black:size=320x240:rate=30", "-frames:v", "3", "-c:v", codec, "-f", "null", "-"],
                               capture_output=True, creationflags=NOWIN, timeout=20)
            if r.returncode == 0:
                return name
        except Exception:
            pass
    return "x264"


def media_duration(path):
    r = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", creationflags=NOWIN)
    m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr)
    if not m:
        return None
    h, mnt, s = m.groups()
    return int(h) * 3600 + int(mnt) * 60 + float(s)


class Recorder(QObject):
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self.proc = None
        self.active = False
        self.stopping = False
        self.encoder = None
        self.audio = AudioHost()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.audio.refresh_if_stale)
        self._timer.start(60_000)
        threading.Thread(target=self._detect, daemon=True).start()

    def _detect(self):
        self.encoder = detect_encoder()
        log.info("кодировщик видео: %s", self.encoder)

    def start(self, rect: QRect, mic: bool, system: bool, cfg):
        outputs = winapi.dxgi_outputs()
        if not outputs:
            self.failed.emit("Не удалось получить список мониторов")
            return None

        def overlap(o):
            l, t, r, b = o[1]
            i = rect.intersected(QRect(QPoint(l, t), QPoint(r - 1, b - 1)))
            return i.width() * i.height() if not i.isEmpty() else 0

        idx, (ol, ot, orr, ob) = max(outputs, key=overlap)
        area = rect.intersected(QRect(QPoint(ol, ot), QPoint(orr - 1, ob - 1)))
        w, h = area.width() & ~1, area.height() & ~1
        if w < 16 or h < 16:
            self.failed.emit("Слишком маленькая область для видео")
            return None
        fps = int(cfg.get("fps", 30))
        self.cfg = dict(cfg)
        self.area = QRect(area.left(), area.top(), w, h)
        self.src = (f"ddagrab=output_idx={idx}:framerate={fps}:offset_x={area.left() - ol}:"
                    f"offset_y={area.top() - ot}:video_size={w}x{h}:draw_mouse={1 if cfg.get('draw_mouse', True) else 0}")
        self.fps = fps
        self.q = QUALITY_Q.get(cfg.get("quality", "high"), 23)
        self.out_dir = Path(cfg["video_dir"])
        self.tmp = Path(tempfile.mkdtemp(prefix="skrin-"))
        self.video = self.tmp / "video.mkv"
        self.caps = []
        self.stopping = False
        self.audio.busy = True
        self.t_launch = time.perf_counter()
        self._launch(self.encoder or "nvenc")
        self.active = True
        # звук подключается в фоне: видео не ждёт (сдвиг звука потом учтётся при сведении)
        self.audio_cancel = threading.Event()
        self.audio_thread = threading.Thread(target=self._start_audio, args=(mic, system), daemon=True)
        self.audio_thread.start()
        QTimer.singleShot(2500, self._check_alive)
        log.info("запись: %s, %s, q=%s", self.src, self.enc, self.q)
        return QRect(self.area)

    def _start_audio(self, mic, system):
        if self.audio.get() is None or self.audio_cancel.is_set():
            return
        if system:
            try:
                self._add_cap(self.audio.find_loopback(self.cfg.get("sys_device", "")), "system")
            except Exception:
                log.exception("нет звука ПК")
        if mic:
            try:
                self._add_cap(self.audio.find_input(self.cfg.get("mic_device", "")), "mic")
            except Exception:
                log.exception("нет микрофона")
        log.info("звук: %s", [(c.name, c.info.get("name")) for c in self.caps])

    def _stop_audio(self, t_end):
        self.audio_cancel.set()
        # звук ещё не успел подготовиться — не ждём его, видео сохранится без звука
        self.audio_thread.join(45 if self.audio.ready.is_set() else 0.2)
        for c in self.caps:
            c.stop(t_end)

    def _add_cap(self, info, name):
        cap = AudioCapture(self.audio.p, info, self.tmp / f"{name}.wav", name)
        try:
            cap.start()
            self.caps.append(cap)
        except Exception:
            log.exception("не открылся звук %s (%s)", name, info.get("name"))
            cap.closed = True
            cap.wav.close()
            self.audio.born = 0  # устройства поменялись — обновить список после записи

    def _launch(self, enc):
        self.enc = enc
        q = self.q
        if enc == "nvenc":
            vargs = ["-c:v", "h264_nvenc", "-preset", "p5", "-tune", "hq", "-rc", "vbr", "-cq", str(q), "-b:v", "0"]
        elif enc == "amf":
            vargs = ["-c:v", "h264_amf", "-quality", "quality", "-rc", "cqp", "-qp_i", str(q), "-qp_p", str(q)]
        else:
            vargs = ["-vf", "hwdownload,format=bgra", "-c:v", "libx264", "-preset", "veryfast", "-crf", str(q - 1),
                     "-pix_fmt", "yuv420p"]
        cmd = [FFMPEG, "-hide_banner", "-nostats", "-loglevel", "warning", "-y", "-f", "lavfi", "-i", self.src,
               *vargs, "-g", str(self.fps * 2), str(self.video)]
        self.logf = open(self.tmp / f"ffmpeg-{enc}.log", "wb")
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=self.logf,
                                     creationflags=NOWIN)

    def _check_alive(self):
        if not self.active or self.stopping or self.proc is None:
            return
        if self.proc.poll() is not None:
            self.logf.close()
            err = (self.tmp / f"ffmpeg-{self.enc}.log").read_text("utf-8", "replace")[-600:]
            log.warning("ffmpeg %s упал: %s", self.enc, err)
            if self.enc != "x264":
                self.encoder = "x264"
                self._launch("x264")
                QTimer.singleShot(2500, self._check_alive)
            else:
                self.active = False
                self.stopping = True
                t = time.perf_counter()
                threading.Thread(target=self._fail_cleanup, args=(t,), daemon=True).start()
                self.failed.emit("ffmpeg не смог записать экран:\n" + err[-300:])

    def _fail_cleanup(self, t):
        self._stop_audio(t)
        self.stopping = False
        self.audio.busy = False

    def stop(self):
        if not self.active or self.stopping:
            return
        self.stopping = True
        t_stop = time.perf_counter()
        try:
            self.proc.stdin.write(b"q")
            self.proc.stdin.flush()
            self.proc.stdin.close()
        except Exception:
            pass
        threading.Thread(target=self._finish, args=(t_stop,), daemon=True).start()

    def _finish(self, t_stop):
        try:
            try:
                self.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.logf.close()
            self._stop_audio(t_stop)
            if not self.video.exists() or self.video.stat().st_size == 0:
                raise RuntimeError("ffmpeg не записал видео")
            dur = media_duration(self.video) or (t_stop - self.t_launch)
            video_start = t_stop - dur
            self.out_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
            out = self.out_dir / f"Видео {stamp}.mp4"
            cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", str(self.video)]
            chains, labels = [], []
            vols = {"mic": self.cfg.get("mic_volume", 100), "system": self.cfg.get("sys_volume", 100)}
            for i, c in enumerate([c for c in self.caps if c.written > 0], start=1):
                off = video_start - c.t0
                vol = f"volume={vols.get(c.name, 100) / 100:.2f}," if vols.get(c.name, 100) != 100 else ""
                if off >= 0:
                    cmd += ["-ss", f"{off:.3f}", "-i", str(c.path)]
                    pre = ""
                else:
                    cmd += ["-i", str(c.path)]
                    pre = f"adelay={int(-off * 1000)}:all=1,"
                chains.append(f"[{i}:a]{pre}{vol}aresample=48000,aformat=channel_layouts=stereo[a{i}]")
                labels.append(f"[a{i}]")
            if labels:
                mix = (f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=longest[aout]"
                       if len(labels) > 1 else f"{labels[0]}anull[aout]")
                cmd += ["-filter_complex", ";".join(chains + [mix]), "-map", "0:v", "-map", "[aout]",
                        "-c:a", "aac", "-b:a", "160k"]
            else:
                cmd += ["-map", "0:v"]
            cmd += ["-c:v", "copy", "-t", f"{dur:.3f}", "-movflags", "+faststart", str(out)]
            r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                               creationflags=NOWIN)
            if r.returncode != 0 or not out.exists():
                log.error("сведение: %s", r.stderr[-1000:])
                fallback = self.out_dir / f"Видео {stamp} (без звука).mkv"
                shutil.copy2(self.video, fallback)
                self.finished.emit(str(fallback))
            else:
                log.info("готово: %s (%.1f с, %s, звук: %s)", out, dur, self.enc, [c.name for c in self.caps])
                self.finished.emit(str(out))
                shutil.rmtree(self.tmp, ignore_errors=True)
        except Exception as e:
            log.exception("ошибка завершения записи")
            self.failed.emit(f"Не удалось сохранить видео: {e}\nВременные файлы: {self.tmp}")
        finally:
            self.active = False
            self.stopping = False
            self.audio.busy = False


class RecordFrame(QWidget):
    """Красная рамка вокруг записываемой области. Не мешает щелчкам и не попадает в запись."""

    def __init__(self, rect: QRect):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool |
                         Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setGeometry(rect.adjusted(-3, -3, 3, 3))

    def showEvent(self, e):
        super().showEvent(e)
        winapi.exclude_from_capture(self.winId())

    def paintEvent(self, e):
        p = QPainter(self)
        p.setPen(QPen(QColor(229, 51, 58), 2))
        p.drawRect(QRectF(1, 1, self.width() - 2, self.height() - 2))


class Countdown(QWidget):
    """Рамка будущей записи с крупным отсчётом 3-2-1 в центре. В запись не попадает."""
    done = Signal()

    def __init__(self, rect: QRect, seconds=3, cancel_hint=""):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool |
                         Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setGeometry(rect.adjusted(-3, -3, 3, 3))
        self.k = scale_for(rect)  # масштаб монитора, где будет запись
        self.left = seconds
        self.hint = f"Отмена — {cancel_hint}" if cancel_hint else ""
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1000)

    def showEvent(self, e):
        super().showEvent(e)
        winapi.exclude_from_capture(self.winId())

    def _tick(self):
        self.left -= 1
        if self.left <= 0:
            self.timer.stop()
            self.close()
            self.deleteLater()
            self.done.emit()
        else:
            self.update()

    def cancel(self):
        self.timer.stop()
        self.close()
        self.deleteLater()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(QPen(QColor(229, 51, 58), 2))
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(1, 1, w - 2, h - 2))
        k = self.k
        r = max(28, min(px(90, k), int(min(w, h) * 0.22)))
        cx, cy = w / 2, h / 2
        p.setPen(QPen(QColor(255, 255, 255, 200), 3))
        p.setBrush(QColor(229, 51, 58, 225))
        p.drawEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))
        f = QFont("Segoe UI")
        f.setBold(True)
        f.setPixelSize(int(r * 1.2))
        p.setFont(f)
        p.setPen(QColor(255, 255, 255))
        p.drawText(QRectF(cx - r, cy - r, 2 * r, 2 * r), Qt.AlignCenter, str(self.left))
        if self.hint and h > 2 * r + px(60, k):
            f.setPixelSize(px(14, k))
            f.setBold(False)
            p.setFont(f)
            tw = QFontMetricsF(f).horizontalAdvance(self.hint) + px(20, k)
            box = QRectF(cx - tw / 2, cy + r + px(10, k), tw, px(26, k))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(20, 20, 24, 200))
            p.drawRoundedRect(box, 6, 6)
            p.setPen(QColor(240, 240, 240))
            p.drawText(box, Qt.AlignCenter, self.hint)


class RecordPanel(QWidget):
    stop_clicked = Signal()

    def __init__(self, rect: QRect, screen_rect: QRect, stop_hint=""):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool |
                         Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.t0 = time.time()
        k = scale_for(rect)  # масштаб монитора, где идёт запись
        lay = QHBoxLayout(self)
        lay.setContentsMargins(px(12, k), px(6, k), px(6, k), px(6, k))
        lay.setSpacing(px(10, k))
        self.label = QLabel("● 00:00", self)
        self.label.setStyleSheet(f"color: #ff4d55; font: 600 {px(14, k)}px 'Segoe UI';")
        lay.addWidget(self.label)
        b = QToolButton(self)
        b.setText("■  Стоп")
        b.setToolTip(f"Остановить запись ({stop_hint})" if stop_hint else "Остановить запись")
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet("QToolButton { background: #e5333a; color: white; border: none; border-radius: 6px;"
                        f" padding: {px(5, k)}px {px(12, k)}px; font: 600 {px(13, k)}px 'Segoe UI'; }}"
                        " QToolButton:hover { background: #f2545a; }")
        b.clicked.connect(self.stop_clicked.emit)
        lay.addWidget(b)
        self.adjustSize()
        s = self.sizeHint()
        x = min(rect.right() - s.width(), screen_rect.right() - s.width() - 4)
        x = max(x, screen_rect.left() + 4)
        y = rect.bottom() + 8
        if y + s.height() > screen_rect.bottom():
            y = rect.top() - s.height() - 8
        if y < screen_rect.top():
            y = rect.bottom() - s.height() - 8
        self.setGeometry(x, y, s.width(), s.height())
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(500)

    def showEvent(self, e):
        super().showEvent(e)
        winapi.exclude_from_capture(self.winId())

    def _tick(self):
        sec = int(time.time() - self.t0)
        dot = "●" if sec % 2 == 0 else "○"
        self.label.setText(f"{dot} {sec // 60:02d}:{sec % 60:02d}")

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(255, 255, 255, 45), 1))
        p.setBrush(QColor(30, 31, 36, 240))
        p.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 9, 9)
