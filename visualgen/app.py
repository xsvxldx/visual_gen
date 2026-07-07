import subprocess
import sys

import glfw
import moderngl

from visualgen import window
from visualgen.clock import VsyncClock
from visualgen.player import VideoPlayer
from visualgen.render import Renderer


def _prevent_sleep() -> subprocess.Popen:
    return subprocess.Popen(["caffeinate", "-dis"])


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] != "--file":
        print("usage: visualgen --file <video>", file=sys.stderr)
        return 2
    source = sys.argv[2]

    caffeinate = _prevent_sleep()
    player = None
    try:
        win, size = window.create_fullscreen("visualgen")
        ctx = moderngl.create_context()
        renderer = Renderer(ctx, size)
        clock = VsyncClock()

        player = VideoPlayer(source)
        player.preload()
        player.start(clock.now())

        def on_key(w, key, scancode, action, mods):
            if key == glfw.KEY_ESCAPE and action == glfw.PRESS:
                window.close(w)

        glfw.set_key_callback(win, on_key)

        while not window.should_close(win):
            glfw.poll_events()
            renderer.draw(player.frame_at(clock.now()))
            glfw.swap_buffers(win)
        return 0
    finally:
        if player is not None:
            player.stop()
        caffeinate.terminate()
        window.terminate()


if __name__ == "__main__":
    sys.exit(main())
