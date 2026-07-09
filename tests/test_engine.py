import time
from pathlib import Path

from visualgen.engine import PlaybackEngine
from visualgen.player import Frame, PlayerError
from visualgen.show import Cue, Show


def fake_frame(pts=0.0):
    import numpy as np

    z = np.zeros((2, 2), dtype=np.uint8)
    return Frame(pts, 2, 2, z, z, z)


class FakePlayer:
    def __init__(self, source):
        self.source = Path(source)
        self.preloaded = False
        self.started = False
        self.stopped = False
        self.fail_on_frame = False

    def preload(self):
        if self.source.name == "explodes-on-preload.mp4":
            raise PlayerError("boom")
        self.preloaded = True

    def start(self, now):
        self.started = True

    def frame_at(self, now):
        if self.fail_on_frame:
            raise PlayerError("decode died")
        return fake_frame()

    def stop(self):
        self.stopped = True


def make_show(n=4):
    cues = tuple(Cue(f"c{i}", Path(f"/fake/{i}.mp4")) for i in range(n))
    return Show(cues, wrap=False)


def make_engine(show=None, fallback=Path("/fake/safe.mp4")):
    made = {}

    def factory(source):
        p = FakePlayer(source)
        made[Path(source)] = p
        return p

    engine = PlaybackEngine(show or make_show(), fallback=fallback, player_factory=factory)
    return engine, made


def wait_ready(engine, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if engine.preloads_ready():
            return True
        time.sleep(0.01)
    return False


def test_start_plays_current_and_preloads_adjacent():
    engine, made = make_engine()
    engine.start(0, {1}, now=0.0)
    assert wait_ready(engine)
    assert made[Path("/fake/0.mp4")].started
    assert made[Path("/fake/1.mp4")].preloaded
    assert not made[Path("/fake/1.mp4")].started
    engine.stop()


def test_start_preloads_fallback():
    engine, made = make_engine()
    engine.start(0, set(), now=0.0)
    assert made[Path("/fake/safe.mp4")].preloaded
    engine.stop()


def test_switch_swaps_instantly_and_drops_far_players():
    engine, made = make_engine()
    engine.start(0, {1}, now=0.0)
    assert wait_ready(engine)
    engine.switch_to(1, {0, 2}, now=1.0)
    assert made[Path("/fake/1.mp4")].started
    assert wait_ready(engine)
    engine.switch_to(2, {1, 3}, now=2.0)
    assert wait_ready(engine)
    assert made[Path("/fake/0.mp4")].stopped
    engine.stop()


def test_frame_at_returns_current_frame():
    engine, made = make_engine()
    engine.start(0, set(), now=0.0)
    assert engine.frame_at(0.1) is not None
    engine.stop()


def test_player_error_engages_fallback():
    engine, made = make_engine()
    engine.start(0, set(), now=0.0)
    engine.frame_at(0.1)
    made[Path("/fake/0.mp4")].fail_on_frame = True
    frame = engine.frame_at(0.2)
    assert frame is not None
    assert made[Path("/fake/safe.mp4")].started
    engine.stop()


def test_no_fallback_freezes_last_frame():
    engine, made = make_engine(fallback=None)
    engine.start(0, set(), now=0.0)
    good = engine.frame_at(0.1)
    made[Path("/fake/0.mp4")].fail_on_frame = True
    assert engine.frame_at(0.2) is good
    engine.stop()


def test_failed_async_preload_never_blocks_readiness():
    cues = (
        Cue("ok", Path("/fake/0.mp4")),
        Cue("bad", Path("/fake/explodes-on-preload.mp4")),
    )
    engine, made = make_engine(show=Show(cues))
    engine.start(0, {1}, now=0.0)
    assert wait_ready(engine), "a failed preload must not leave the FSM stuck in SWITCHING"
    engine.stop()


def test_bad_first_cue_engages_fallback_not_fatal():
    cues = (
        Cue("bad", Path("/fake/explodes-on-preload.mp4")),
        Cue("ok", Path("/fake/1.mp4")),
    )
    engine, made = make_engine(show=Show(cues))
    engine.start(0, {1}, now=0.0)  # must not raise
    frame = engine.frame_at(0.1)
    assert frame is not None, "a failed opening cue must fall back, not go black"
    assert made[Path("/fake/safe.mp4")].started
    engine.stop()


def test_bad_first_cue_without_fallback_returns_none_not_fatal():
    cues = (
        Cue("bad", Path("/fake/explodes-on-preload.mp4")),
        Cue("ok", Path("/fake/1.mp4")),
    )
    engine, made = make_engine(show=Show(cues), fallback=None)
    engine.start(0, {1}, now=0.0)  # must not raise
    assert engine.frame_at(0.1) is None  # nothing to show yet -> app clears to black
    engine.stop()


def test_switch_to_failing_cue_engages_fallback_not_fatal():
    cues = (
        Cue("ok", Path("/fake/0.mp4")),
        Cue("bad", Path("/fake/explodes-on-preload.mp4")),
    )
    engine, made = make_engine(show=Show(cues))
    engine.start(0, {1}, now=0.0)
    wait_ready(engine)
    engine.frame_at(0.1)
    engine.switch_to(1, {0}, now=1.0)  # must not raise even though cue 1 is broken
    frame = engine.frame_at(0.2)
    assert frame is not None
    assert made[Path("/fake/safe.mp4")].started
    engine.stop()


def test_recovers_from_fallback_when_switching_to_good_cue():
    cues = (
        Cue("bad", Path("/fake/explodes-on-preload.mp4")),
        Cue("ok", Path("/fake/1.mp4")),
    )
    engine, made = make_engine(show=Show(cues))
    engine.start(0, {1}, now=0.0)  # engages fallback
    wait_ready(engine)
    engine.switch_to(1, {0}, now=1.0)  # switch to the healthy cue
    frame = engine.frame_at(1.1)
    assert frame is not None
    assert made[Path("/fake/1.mp4")].started, "must leave fallback and play the good cue"
    engine.stop()
