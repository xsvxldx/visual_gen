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
        self._resume_pts: float = 0.0
        self._hold: Frame | None = None
        self._resuming: bool = False
        self.first_frame: Frame | None = None

    def preload(self) -> None:
        try:
            self._container = av.open(self._source)
            stream = self._container.streams.video[0]
            stream.thread_type = "AUTO"
            self._time_base = stream.time_base
            self._stream = stream
            decoder = self._container.decode(stream)
            first = next(decoder)
        except Exception as exc:
            raise PlayerError(f"{self._source}: {exc}") from exc
        self.first_frame = _convert(first, self._time_base)
        self._frames.put(self.first_frame)

    def start(self, now: float, resume: bool = False) -> None:
        """Begin (or restart) continuous decoding.

        resume=False (default): replay from the top of the clip.
        resume=True: seek back to the frame the operator left on (recorded by
        pause()) and resume there, holding that frame on screen until the
        decoder catches up.

        Restart-safe: any running decode thread is halted first, so a cue that is
        revisited never ends up with two threads racing on the same container.
        """
        if self.first_frame is None:
            raise PlayerError(f"{self._source}: start() before preload()")
        self._halt()
        self._drain()
        if self._container is not None:
            try:
                if resume:
                    self._container.seek(int(self._resume_pts * 1_000_000))
                else:
                    self._container.seek(0)  # replay from the start
            except Exception as exc:
                raise PlayerError(f"{self._source}: seek failed: {exc}") from exc
        self._current = None
        if not resume:
            self._hold = None
        self._resuming = resume
        self._error = None
        self._epoch = now - self._resume_pts if resume else now
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._decode_loop, daemon=True)
        self._thread.start()

    def pause(self) -> None:
        """Stop decoding but keep the container open so start() can resume instantly.

        Records the frame currently ON SCREEN so a later start(resume=True) picks up
        from exactly there. During a resume catch-up the on-screen frame is the held
        left-on frame (_hold), not _current -- which is the decoder's off-screen
        catch-up cursor. Recording _current there would resume from a position the
        operator never saw.
        """
        shown = self._hold if self._resuming else self._current
        self._resume_pts = shown.pts if shown is not None else 0.0
        self._hold = shown
        self._halt()

    def _halt(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            self._stop_event.set()
            self._thread.join(timeout=2.0)
        self._thread = None

    def _drain(self) -> None:
        while True:
            try:
                self._frames.get_nowait()
            except queue.Empty:
                return

    def _decode_loop(self) -> None:
        try:
            decoder = self._container.decode(self._stream)
            while not self._stop_event.is_set():
                try:
                    frame = next(decoder)
                except (StopIteration, av.error.EOFError):
                    self._container.seek(0)
                    decoder = self._container.decode(self._stream)
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
                self._resuming = False  # decoder looped before reaching resume -> go live
            if self._epoch + head.pts <= now:
                self._current = self._frames.get_nowait()
            else:
                break
        if self._resuming:
            if self._current is not None and self._current.pts >= self._resume_pts:
                self._resuming = False  # decoder reached the resume point -> go live
            else:
                # Still decoding forward from the keyframe. Keep the left-on frame
                # frozen instead of revealing the fast-forward catch-up frames.
                held = self._hold or self.first_frame
                assert held is not None, "frame_at() before preload()"
                return held
        result = self._current or self._hold or self.first_frame
        assert result is not None, "frame_at() before preload()"
        return result

    def stop(self) -> None:
        self._halt()
        if self._container is not None:
            self._container.close()
            self._container = None
