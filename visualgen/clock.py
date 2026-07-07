import time
from typing import Callable, Protocol


class Clock(Protocol):
    def now(self) -> float: ...


class VsyncClock:
    """Wall-time clock driven by the render loop. Future: AudioClock behind the same protocol."""

    def __init__(self, time_fn: Callable[[], float] = time.monotonic):
        self._time_fn = time_fn

    def now(self) -> float:
        return self._time_fn()
