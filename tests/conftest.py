import av
import numpy as np
import pytest


@pytest.fixture
def video_file(tmp_path):
    """A real 15-frame, 30fps, 64x48 H.264 clip. Frame i is a flat gray level i*16."""
    path = tmp_path / "clip.mp4"
    with av.open(str(path), "w") as container:
        stream = container.add_stream("libx264", rate=30)
        stream.width = 64
        stream.height = 48
        stream.pix_fmt = "yuv420p"
        for i in range(15):
            img = np.full((48, 64, 3), i * 16, dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(img, format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return path
