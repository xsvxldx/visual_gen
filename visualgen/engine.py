import logging
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from visualgen.instruction import Blend, RenderInstruction, Single, TransitionMode
from visualgen.player import Frame, PlayerError, VideoPlayer
from visualgen.show import Show

log = logging.getLogger(__name__)


@dataclass
class _Transition:
    """An in-flight blend from one cue to another, driven by the wall clock."""

    from_index: int
    to_index: int
    start: float
    duration: float
    mode: TransitionMode
    tail_frame: Frame | None = None  # set -> tail dissolve: live A fades into this still, then cuts
    resume: bool = False  # start the destination at its left-on position at the deferred cut (recall)


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
        self._transition: _Transition | None = None
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
        """Advance the mode: cut -> dip -> crossfade -> wipe -> tail_dissolve -> cut. Session-only."""
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
        was_on_fallback = self._on_fallback
        self._on_fallback = False
        from_player = self._players.get(prev) if prev is not None and prev != index else None
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
        if self._tail_possible(from_player, player, was_on_fallback):
            # Tail dissolve: nothing starts and nothing pauses here. A keeps decoding
            # toward its own last-frame still; B's start is deferred to the cut
            # (_finalize_transition). Exactly one decoder runs throughout.
            self._transition = _Transition(
                prev, index, now, self._duration, TransitionMode.CROSSFADE,
                tail_frame=from_player.last_frame, resume=resume,
            )
        else:
            if player is not None:
                try:
                    player.start(now, resume=resume)
                except PlayerError as exc:
                    log.error("cue '%s' failed to start: %s", self._show.cues[index].id, exc)
                    self._failed.add(index)
                    self._engage_fallback(now)
            if self._should_blend(from_player, player):
                # Keep both players decoding for the window; the outgoing one is paused at finalize.
                self._transition = _Transition(prev, index, now, self._duration, self._mode)
            else:
                self._transition = None
                if from_player is not None:
                    from_player.pause()  # instant cut: only the incoming cue decodes continuously
        keep = {index} | adjacent
        for i in [i for i in self._players if i not in keep]:
            self._players.pop(i).stop()
        self._request_preloads(adjacent)

    def _tail_possible(
        self,
        from_player: VideoPlayer | None,
        to_player: VideoPlayer | None,
        was_on_fallback: bool,
    ) -> bool:
        """All preconditions for a tail dissolve; anything short of this is a plain cut."""
        return (
            self._mode is TransitionMode.TAIL_DISSOLVE
            and self._duration > 0
            and to_player is not None
            and from_player is not None
            and from_player.last_frame is not None
            and not was_on_fallback  # outgoing already dead -> nothing healthy to dissolve from
            and not self._on_fallback  # destination just failed to load -> fallback owns the screen
        )

    def _should_blend(self, from_player: VideoPlayer | None, to_player: VideoPlayer | None) -> bool:
        return (
            # TAIL_DISSOLVE has its own switch path; here it must degrade to a cut,
            # never to a two-live-player base blend.
            self._mode not in (TransitionMode.CUT, TransitionMode.TAIL_DISSOLVE)
            and self._duration > 0
            and from_player is not None
            and to_player is not None
            and not self._on_fallback  # target fell back -> nothing healthy to blend into
        )

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
        self._collect_finished_preloads()  # keep neighbour preloads landing during the window
        if self._transition is not None and not self._on_fallback:
            blend = self._blend_at(now)
            if blend is not None:
                return blend
        frame = self.frame_at(now)
        return Single(frame) if frame is not None else None

    def _blend_at(self, now: float) -> Blend | None:
        """Emit the blend for the active transition, or finalize it and return None."""
        t = self._transition
        progress = 1.0 if t.duration <= 0 else (now - t.start) / t.duration
        if progress >= 1.0:
            self._finalize_transition(now)
            return None
        from_player = self._players.get(t.from_index)
        to_player = self._players.get(t.to_index)
        if from_player is None or to_player is None:
            self._finalize_transition(now)
            return None
        if t.tail_frame is not None:
            # Tail dissolve: live A fades into its own last-frame still. B is never
            # queried and never decodes during the window.
            try:
                from_frame = from_player.frame_at(now)
            except PlayerError as exc:
                # The outgoing cue died mid-dissolve: finalize immediately -- for a
                # tail, the finalize IS the hard cut to the healthy destination.
                log.error("outgoing cue '%s' failed mid-dissolve: %s", self._show.cues[t.from_index].id, exc)
                self._finalize_transition(now)
                return None
            self._last_frame = t.tail_frame
            return Blend(from_frame, t.tail_frame, max(0.0, min(1.0, progress)), t.mode)
        try:
            to_frame = to_player.frame_at(now)
        except PlayerError as exc:
            # Incoming cue died: abort the blend and drop to the fallback ladder. The switch
            # is already committed, so we do not return to the outgoing cue.
            log.error("incoming cue '%s' failed mid-transition: %s", self._show.cues[t.to_index].id, exc)
            self._failed.add(t.to_index)
            self._finalize_transition(now)  # clears transition and pauses the outgoing decoder
            self._engage_fallback(now)
            return None
        try:
            from_frame = from_player.frame_at(now)
        except PlayerError as exc:
            # Outgoing cue died: it is the side we are leaving, so hard-cut the blend to the
            # healthy destination — no fallback needed.
            log.error("outgoing cue '%s' failed mid-transition: %s", self._show.cues[t.from_index].id, exc)
            self._finalize_transition(now)
            self._last_frame = to_frame
            return None
        self._last_frame = to_frame
        return Blend(from_frame, to_frame, max(0.0, min(1.0, progress)), t.mode)

    def _finalize_transition(self, now: float) -> None:
        """End the window and revert to the single-decoder rule.

        Base blend: the destination is already running -- just pause the outgoing
        player. Tail dissolve: the destination was never started, so this IS the
        hard cut -- start it here (fresh, or at its left-on position on a recall).
        start() can raise and this runs inside the render loop, so failures drop
        to the fallback ladder instead of escaping.
        """
        t = self._transition
        self._transition = None
        if t is None:
            return
        if t.tail_frame is not None:
            to_player = self._players.get(t.to_index)
            try:
                if to_player is None:
                    raise PlayerError(f"player for cue '{self._show.cues[t.to_index].id}' missing at the cut")
                to_player.start(now, resume=t.resume)
            except PlayerError as exc:
                log.error("cue '%s' failed to start at the cut: %s", self._show.cues[t.to_index].id, exc)
                self._failed.add(t.to_index)
                self._engage_fallback(now)
        from_player = self._players.get(t.from_index)
        if from_player is not None:
            from_player.pause()

    def transition_complete(self) -> bool:
        return self._transition is None

    def stop(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
        for player in self._players.values():
            player.stop()
        self._players.clear()
        if self._fallback_player is not None:
            self._fallback_player.stop()
