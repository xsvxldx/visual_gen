import queue
import threading
from dataclasses import dataclass
from pathlib import Path

import av
import numpy as np


class PlayerError(Exception):
    """Decode or file failure. The engine reacts by engaging the fallback."""


@dataclass
class Frame:
    pts: float
    width: int
    height: int
    y: np.ndarray
    u: np.ndarray
    v: np.ndarray


def _convert(frame: av.VideoFrame, time_base) -> Frame:
    h, w = frame.height, frame.width
    arr = frame.reformat(format="yuv420p").to_ndarray()
    y = np.ascontiguousarray(arr[:h])
    u = np.ascontiguousarray(arr[h : h + h // 4].reshape(h // 2, w // 2))
    v = np.ascontiguousarray(arr[h + h // 4 :].reshape(h // 2, w // 2))
    pts = 0.0 if frame.pts is None else float(frame.pts * time_base)
    return Frame(pts, w, h, y, u, v)


class VideoPlayer:
    def __init__(self, source: str | Path, buffer_size: int = 3):
        self._source = str(source)
        self._frames: queue.Queue[Frame] = queue.Queue(maxsize=buffer_size)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._error: Exception | None = None
        self._container = None
        self._decoder = None
        self._time_base = None
        self._epoch: float = 0.0
        self._current: Frame | None = None
        self.first_frame: Frame | None = None

    def preload(self) -> None:
        try:
            self._container = av.open(self._source)
            stream = self._container.streams.video[0]
            stream.thread_type = "AUTO"
            self._time_base = stream.time_base
            self._stream = stream
            self._decoder = self._container.decode(stream)
            first = next(self._decoder)
        except Exception as exc:
            raise PlayerError(f"{self._source}: {exc}") from exc
        self.first_frame = _convert(first, self._time_base)
        self._frames.put(self.first_frame)

    def start(self, now: float) -> None:
        if self.first_frame is None:
            raise PlayerError(f"{self._source}: start() before preload()")
        self._epoch = now
        self._thread = threading.Thread(target=self._decode_loop, daemon=True)
        self._thread.start()

    def _decode_loop(self) -> None:
        try:
            while not self._stop_event.is_set():
                try:
                    frame = next(self._decoder)
                except (StopIteration, av.error.EOFError):
                    self._container.seek(0)
                    self._decoder = self._container.decode(self._stream)
                    continue
                converted = _convert(frame, self._time_base)
                while not self._stop_event.is_set():
                    try:
                        self._frames.put(converted, timeout=0.1)
                        break
                    except queue.Full:
                        continue
        except Exception as exc:
            self._error = exc

    def frame_at(self, now: float) -> Frame:
        if self._error is not None:
            raise PlayerError(f"{self._source}: {self._error}")
        while True:
            try:
                head: Frame = self._frames.queue[0]
            except IndexError:
                break
            if self._current is not None and head.pts < self._current.pts:
                self._epoch = now
            if self._epoch + head.pts <= now:
                self._current = self._frames.get_nowait()
            else:
                break
        result = self._current or self.first_frame
        assert result is not None, "frame_at() before preload()"
        return result

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._container is not None:
            self._container.close()
            self._container = None
