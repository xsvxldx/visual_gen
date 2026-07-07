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


def test_stop_is_idempotent(video_file):
    p = VideoPlayer(video_file)
    p.preload()
    p.start(now=0.0)
    p.stop()
    p.stop()
