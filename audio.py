"""Звук: готовый экземпляр PortAudio, список устройств, запись в wav, индикатор уровня, проверка микрофона."""
import array
import logging
import math
import tempfile
import threading
import time
import wave
from pathlib import Path

import pyaudiowpatch as pa

log = logging.getLogger("skrin")
LOOPBACK_SUFFIX = " [Loopback]"


class AudioHost:
    """PortAudio при запуске перебирает все звуковые устройства — это 5–15 секунд.
    Поэтому держим готовый экземпляр и обновляем его в фоне, пока запись не идёт."""

    REFRESH_SEC = 20 * 60

    def __init__(self):
        self.p = None
        self.ready = threading.Event()
        self.busy = False  # идёт запись или проверка — обновлять нельзя
        self.born = 0.0
        self.listeners = []  # вызываются (из фонового потока) после обновления
        self._lock = threading.Lock()
        self.refresh()

    def refresh(self):
        def work():
            with self._lock:
                self.ready.clear()
                old, self.p = self.p, None
                try:
                    if old is not None:
                        old.terminate()
                except Exception:
                    log.exception("pa terminate")
                t = time.perf_counter()
                try:
                    self.p = pa.PyAudio()
                except Exception:
                    log.exception("PortAudio не запустился")
                self.born = time.time()
                log.info("звук готов за %.1f с", time.perf_counter() - t)
                self.ready.set()
            for cb in list(self.listeners):
                try:
                    cb()
                except Exception:
                    pass
        threading.Thread(target=work, daemon=True, name="audio-init").start()

    def refresh_if_stale(self):
        if not self.busy and self.ready.is_set() and time.time() - self.born > self.REFRESH_SEC:
            self.refresh()

    def get(self, timeout=40):
        self.ready.wait(timeout)
        return self.p

    # ---------- устройства (только WASAPI) ----------
    def _wasapi(self):
        return self.p.get_host_api_info_by_type(pa.paWASAPI)

    def inputs(self):
        """Микрофоны: [(имя, info)]."""
        if not self.ready.is_set() or self.p is None:
            return []
        api = self._wasapi()["index"]
        out = []
        for i in range(self.p.get_device_count()):
            d = self.p.get_device_info_by_index(i)
            if d["hostApi"] == api and d["maxInputChannels"] > 0 and not d.get("isLoopbackDevice"):
                out.append((d["name"], d))
        return out

    def loopbacks(self):
        """Звук ПК (что играет в динамиках): [(имя динамиков, info loopback)]."""
        if not self.ready.is_set() or self.p is None:
            return []
        return [(d["name"].replace(LOOPBACK_SUFFIX, ""), d) for d in self.p.get_loopback_device_info_generator()]

    def default_input(self):
        return self.p.get_device_info_by_index(self._wasapi()["defaultInputDevice"])

    def default_loopback(self):
        return self.p.get_default_wasapi_loopback()

    def find_input(self, name):
        if name:
            for n, d in self.inputs():
                if n == name:
                    return d
            log.warning("микрофон «%s» не найден — беру по умолчанию", name)
        return self.default_input()

    def find_loopback(self, name):
        if name:
            for n, d in self.loopbacks():
                if n == name:
                    return d
            log.warning("динамики «%s» не найдены — беру по умолчанию", name)
        return self.default_loopback()


class AudioCapture:
    """Пишет поток WASAPI в wav. Пропуски (у звука ПК, когда тишина) заполняет нулями по часам."""

    def __init__(self, p, info, path, name):
        self.p, self.info, self.path, self.name = p, info, Path(path), name
        self.rate = int(info["defaultSampleRate"])
        self.ch = max(1, min(2, int(info["maxInputChannels"])))
        self.bpf = 2 * self.ch
        self.wav = wave.open(str(self.path), "wb")
        self.wav.setnchannels(self.ch)
        self.wav.setsampwidth(2)
        self.wav.setframerate(self.rate)
        self.written = 0
        self.t0 = None
        self.stream = None
        self.lock = threading.Lock()
        self.closed = False

    def start(self):
        self.t0 = time.perf_counter()
        self.stream = self.p.open(format=pa.paInt16, channels=self.ch, rate=self.rate, input=True,
                                  input_device_index=self.info["index"], frames_per_buffer=1024,
                                  stream_callback=self._cb)

    def _pad_to(self, total):
        gap = int(total - self.written)
        if gap > 0:
            self.wav.writeframes(b"\0" * (gap * self.bpf))
            self.written += gap

    def _cb(self, data, n, _ti, _st):
        with self.lock:
            if self.closed:
                return None, pa.paComplete
            expected = (time.perf_counter() - self.t0) * self.rate - n
            if expected - self.written > self.rate * 0.06:
                self._pad_to(expected)
            self.wav.writeframes(data)
            self.written += n
        return None, pa.paContinue

    def stop(self, t_end):
        try:
            if self.stream:
                self.stream.stop_stream()
                self.stream.close()
        except Exception:
            log.exception("audio stop %s", self.name)
        with self.lock:
            if self.t0 is not None:
                self._pad_to((t_end - self.t0) * self.rate)
            self.closed = True
            self.wav.close()


class LevelMeter:
    """Слушает устройство и отдаёт уровень 0..1 (для шкалы в настройках). Может записать пробу в wav."""

    def __init__(self, p, info):
        self.p, self.info = p, info
        self.rate = int(info["defaultSampleRate"])
        self.ch = max(1, min(2, int(info["maxInputChannels"])))
        self.level = 0.0
        self.peak_time = 0.0
        self._rec = None
        self._rec_until = 0.0
        self.stream = p.open(format=pa.paInt16, channels=self.ch, rate=self.rate, input=True,
                             input_device_index=info["index"], frames_per_buffer=1024, stream_callback=self._cb)

    def _cb(self, data, n, _ti, _st):
        a = array.array("h", data)
        peak = max(max(a), -min(a)) if a else 0
        db = 20 * math.log10(max(peak, 1) / 32768.0)
        self.level = max(0.0, min(1.0, (db + 60) / 60))
        self.peak_time = time.time()
        if self._rec is not None:
            self._rec.append(data)
            if time.time() >= self._rec_until:
                self._finish_rec()
        return None, pa.paContinue

    def current(self):
        # у звука ПК при тишине данные не приходят — уровень гаснет сам
        return self.level if time.time() - self.peak_time < 0.3 else 0.0

    def record_test(self, seconds, done_cb):
        self._done_cb = done_cb
        self._rec = []
        self._rec_until = time.time() + seconds

    def _finish_rec(self):
        chunks, self._rec = self._rec, None
        path = Path(tempfile.gettempdir()) / "skrin-mic-test.wav"
        with wave.open(str(path), "wb") as w:
            w.setnchannels(self.ch)
            w.setsampwidth(2)
            w.setframerate(self.rate)
            w.writeframes(b"".join(chunks))
        threading.Thread(target=self._done_cb, args=(str(path),), daemon=True).start()

    def close(self):
        try:
            self.stream.stop_stream()
            self.stream.close()
        except Exception:
            pass
