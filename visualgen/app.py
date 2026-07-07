import subprocess
import sys

import glfw
import moderngl

from visualgen import window
from visualgen.render import Renderer


def _prevent_sleep() -> subprocess.Popen:
    # -d: display awake, -i: idle sleep off, -s: system sleep off
    return subprocess.Popen(["caffeinate", "-dis"])


def main() -> int:
    caffeinate = _prevent_sleep()
    try:
        win, size = window.create_fullscreen("visualgen")
        ctx = moderngl.create_context()
        renderer = Renderer(ctx, size)

        def on_key(w, key, scancode, action, mods):
            if key == glfw.KEY_ESCAPE and action == glfw.PRESS:
                window.close(w)

        glfw.set_key_callback(win, on_key)

        while not window.should_close(win):
            glfw.poll_events()
            renderer.draw_clear((0.0, 0.15, 0.3))
            glfw.swap_buffers(win)
        return 0
    finally:
        caffeinate.terminate()
        window.terminate()


if __name__ == "__main__":
    sys.exit(main())
