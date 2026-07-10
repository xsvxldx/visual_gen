import time

import pytest

from visualgen.player import Frame, PlayerError, VideoPlayer


def test_preload_decodes_first_frame(video_file):
    p = VideoPlayer(video_file)
    p.preload()
    try:
        f = p.first_frame
        assert isinstance(f, Frame)
        assert (f.width, f.height) == (64, 48)
        assert f.y.shape == (48, 64)
        assert f.u.shape == (24, 32)
        assert f.v.shape == (24, 32)
        assert f.pts == 0.0
    finally:
        p.stop()


def test_frame_at_advances_with_time(video_file):
    p = VideoPlayer(video_file)
    p.preload()
    p.start(now=0.0)
    try:
        first = p.frame_at(0.0)
        assert first.pts == 0.0
        deadline = time.monotonic() + 2.0
        advanced = None
        while time.monotonic() < deadline:
            advanced = p.frame_at(0.2)
            if advanced.pts > 0.0:
                break
            time.sleep(0.01)
        assert advanced is not None and advanced.pts > 0.0
    finally:
        p.stop()


def test_frame_at_repeats_last_frame_when_behind(video_file):
    p = VideoPlayer(video_file)
    p.preload()
    p.start(now=0.0)
    try:
        a = p.frame_at(0.0)
        b = p.frame_at(0.0)
        assert a.pts == b.pts
    finally:
        p.stop()


def test_loops_past_end_of_file(video_file):
    p = VideoPlayer(video_file)
    p.preload()
    start = time.monotonic()
    p.start(now=start)
    try:
        seen_wrap = False
        last_pts = -1.0
        while time.monotonic() - start < 1.6:
            f = p.frame_at(time.monotonic())
            if f.pts < last_pts:
                seen_wrap = True
                break
            last_pts = f.pts
            time.sleep(0.01)
        assert seen_wrap, "player never looped back to the start"
    finally:
        p.stop()


def test_preload_bad_file_raises(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"this is not a video")
    p = VideoPlayer(bad)
    with pytest.raises(PlayerError):
        p.preload()


def test_pause_stops_the_decode_thread(video_file):
    p = VideoPlayer(video_file)
    p.preload()
    p.start(now=0.0)
    thread = p._thread
    assert thread.is_alive()
    try:
        p.pause()
        assert not thread.is_alive(), "pause() must stop the decode thread"
        assert p._thread is None
    finally:
        p.stop()


def test_restart_halts_previous_thread_not_orphans_it(video_file):
    # Calling start() again must not leave a second decode thread racing on the container.
    p = VideoPlayer(video_file)
    p.preload()
    p.start(now=0.0)
    first = p._thread
    try:
        p.start(now=0.0)  # restart
        assert p._thread is not first, "restart should spawn a fresh thread"
        assert not first.is_alive(), "the previous decode thread must be halted, not orphaned"
    finally:
        p.stop()


def test_start_after_pause_replays_from_top(video_file):
    p = VideoPlayer(video_file)
    p.preload()
    p.start(now=0.0)
    try:
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if p.frame_at(0.5).pts > 0.0:
                break
            time.sleep(0.01)
        assert p.frame_at(0.5).pts > 0.0, "precondition: playback advanced past the first frame"
        p.pause()
        p.start(now=100.0)  # revisit the cue -> replay from the beginning
        assert p.frame_at(100.0).pts == 0.0
    finally:
        p.stop()


def test_start_surfaces_seek_failure_as_player_error(video_file):
    p = VideoPlayer(video_file)
    p.preload()
    p._container.close()  # container is now unusable -> the seek in start() must fail
    with pytest.raises(PlayerError):
        p.start(now=0.0)
    # start() raised before spawning a decode thread, and the container is already
    # closed, so there is nothing for stop() to do here.


def test_stop_is_idempotent(video_file):
    p = VideoPlayer(video_file)
    p.preload()
    p.start(now=0.0)
    p.stop()
    p.stop()


def test_start_resume_replays_from_left_position(video_file):
    p = VideoPlayer(video_file)
    p.preload()
    p.start(now=0.0)
    try:
        # advance past the first frame so there is a non-zero position to resume from
        deadline = time.monotonic() + 2.0
        left = None
        while time.monotonic() < deadline:
            f = p.frame_at(0.2)
            if f.pts > 0.0:
                left = f
                break
            time.sleep(0.01)
        assert left is not None and left.pts > 0.0, "precondition: playback advanced"

        p.pause()
        assert p._resume_pts == left.pts, "pause() records the frame it was left on"
        assert p._hold is left, "pause() holds the exact frame for display during catch-up"

        p.start(now=100.0, resume=True)
        # the held frame is shown immediately at the resume position (not from the top),
        # even before the decoder produces the resume frame
        shown = p.frame_at(100.0)
        assert shown.pts == left.pts
    finally:
        p.stop()


def test_resume_holds_left_frame_until_decoder_reaches_it(video_file):
    # Recall must NOT show the fast-forward catch-up frames. The decoder seeks to the
    # keyframe at/before the resume point and walks forward; while it does, the operator
    # should keep seeing the exact frame they left on, then playback goes live AT the
    # resume point. Driven deterministically (frames injected, no decode thread running)
    # so it does not depend on decode timing.
    import numpy as np

    def synth(pts):
        z = np.zeros((2, 2), dtype=np.uint8)
        return Frame(pts, 2, 2, z, z, z)

    p = VideoPlayer(video_file)
    p.preload()
    # Operator left the cue on the frame at pts 0.40.
    left = synth(0.40)
    p._hold = left
    p._resume_pts = 0.40
    p._resuming = True
    p._current = None
    now = 100.0
    p._epoch = now - 0.40  # as start(resume=True) sets it

    # The decoder has only produced an early catch-up frame so far (0.10, well before 0.40).
    p._frames.put(synth(0.10))
    shown = p.frame_at(now)
    assert shown.pts == 0.40, "must hold the left-on frame, not reveal a catch-up frame"
    assert p._resuming, "still catching up"

    # The decoder reaches the resume point.
    p._frames.put(synth(0.40))
    live = p.frame_at(now)
    assert live.pts == 0.40, "reveals live playback at the resume point"
    assert not p._resuming, "catch-up complete -> live"
