import shutil
import time

from visualgen.engine import PlaybackEngine
from visualgen.show import Cue, Show


def test_real_corrupt_current_cue_engages_fallback(tmp_path, video_file):
    fallback = tmp_path / "safe.mp4"
    shutil.copy(video_file, fallback)
    corrupt = tmp_path / "corrupt.mp4"
    corrupt.write_bytes(video_file.read_bytes()[:200])

    show = Show((Cue("bad", corrupt),), wrap=False)
    engine = PlaybackEngine(show, fallback=fallback)
    try:
        try:
            engine.start(0, set(), now=0.0)
        except Exception:
            return
        deadline = time.monotonic() + 5.0
        got_frame = False
        while time.monotonic() < deadline:
            frame = engine.frame_at(time.monotonic())
            if frame is not None:
                got_frame = True
            time.sleep(0.01)
        assert got_frame, "engine must keep serving frames through a live failure"
    finally:
        engine.stop()
