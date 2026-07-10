import logging
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from visualgen.instruction import RenderInstruction, Single, TransitionMode
from visualgen.player import Frame, PlayerError, VideoPlayer
from visualgen.show import Show

log = logging.getLogger(__name__)


class PlaybackEngine:
    def __init__(
        self,
        show: Show,
        fallback: Path | None = None,
        player_factory: Callable[[Path], VideoPlayer] = VideoPlayer,
    ):
        self._show = show
        self._factory = player_factory
        self._mode = show.transition  # session state, seeded from YAML; live keys mutate it
        self._duration = show.duration
        self._players: dict[int, VideoPlayer] = {}
        self._pending: dict[int, Future] = {}
        self._failed: set[int] = set()
        self._pool = ThreadPoolExecutor(max_workers=2)
        self._current: int | None = None
        self._last_frame: Frame | None = None
        self._fallback_player: VideoPlayer | None = None
        self._fallback_started = False
        self._on_fallback = False
        if fallback is not None:
            self._fallback_player = self._factory(fallback)
            try:
                self._fallback_player.preload()
            except PlayerError as exc:
                log.error("fallback video failed to preload, freeze-frame only: %s", exc)
                self._fallback_player = None

    _MIN_DURATION = 0.1

    @property
    def mode(self) -> TransitionMode:
        return self._mode

    @property
    def duration(self) -> float:
        return self._duration

    def cycle_mode(self) -> None:
        """Advance the base blend: cut -> dip -> crossfade -> wipe -> cut. Session-only."""
        modes = list(TransitionMode)
        self._mode = modes[(modes.index(self._mode) + 1) % len(modes)]

    def adjust_duration(self, delta: float) -> None:
        """Nudge the transition duration, floored at _MIN_DURATION. Session-only."""
        self._duration = round(max(self._MIN_DURATION, self._duration + delta), 3)

    def start(self, index: int, adjacent: set[int], now: float) -> None:
        self._current = index
        try:
            player = self._factory(self._show.cues[index].source)
            player.preload()
            player.start(now)
            self._players[index] = player
        except PlayerError as exc:
            log.error("opening cue '%s' failed: %s", self._show.cues[index].id, exc)
            self._failed.add(index)
            self._engage_fallback(now)
        self._request_preloads(adjacent)

    def switch_to(self, index: int, adjacent: set[int], now: float, resume: bool = False) -> None:
        self._collect_finished_preloads()
        prev = self._current
        self._current = index
        self._on_fallback = False
        if prev is not None and prev != index and prev in self._players:
            self._players[prev].pause()  # only the incoming cue decodes continuously
        player = self._players.get(index)
        if player is None:
            try:
                player = self._factory(self._show.cues[index].source)
                player.preload()
                self._players[index] = player
            except PlayerError as exc:
                log.error("cue '%s' failed to load on switch: %s", self._show.cues[index].id, exc)
                self._failed.add(index)
                self._engage_fallback(now)
                player = None
        if player is not None:
            try:
                player.start(now, resume=resume)
            except PlayerError as exc:
                log.error("cue '%s' failed to start: %s", self._show.cues[index].id, exc)
                self._failed.add(index)
                self._engage_fallback(now)
        keep = {index} | adjacent
        for i in [i for i in self._players if i not in keep]:
            self._players.pop(i).stop()
        self._request_preloads(adjacent)

    def _request_preloads(self, indices: set[int]) -> None:
        for i in indices:
            if i in self._players or i in self._pending or i in self._failed:
                continue
            player = self._factory(self._show.cues[i].source)

            def job(p=player):
                p.preload()
                return p

            self._pending[i] = self._pool.submit(job)

    def _collect_finished_preloads(self) -> None:
        for i in [i for i, f in self._pending.items() if f.done()]:
            future = self._pending.pop(i)
            if i in self._players:
                future.result().stop()
                continue
            try:
                self._players[i] = future.result()
            except PlayerError as exc:
                log.error("cue '%s' failed to preload: %s", self._show.cues[i].id, exc)
                self._failed.add(i)

    def preloads_ready(self) -> bool:
        self._collect_finished_preloads()
        return not self._pending

    def _engage_fallback(self, now: float) -> bool:
        """Switch playback to the fallback video. Returns True if it engaged."""
        if self._fallback_player is None:
            return False
        if not self._fallback_started:
            try:
                self._fallback_player.start(now)
            except PlayerError as exc:
                log.error("fallback video failed to start, freeze-frame only: %s", exc)
                self._fallback_player = None
                return False
            self._fallback_started = True
        self._on_fallback = True
        return True

    def frame_at(self, now: float) -> Frame | None:
        source = None
        if self._on_fallback and self._fallback_player is not None:
            source = self._fallback_player
        elif self._current is not None:
            source = self._players.get(self._current)
        if source is not None:
            try:
                self._last_frame = source.frame_at(now)
                return self._last_frame
            except PlayerError as exc:
                log.error("live playback failure: %s", exc)
                if not self._on_fallback and self._engage_fallback(now):
                    return self.frame_at(now)
        return self._last_frame

    def instruction_at(self, now: float) -> RenderInstruction | None:
        """The render seam: what the renderer should draw this frame."""
        frame = self.frame_at(now)
        return Single(frame) if frame is not None else None

    def stop(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
        for player in self._players.values():
            player.stop()
        self._players.clear()
        if self._fallback_player is not None:
            self._fallback_player.stop()
