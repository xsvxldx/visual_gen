import logging
import queue
import subprocess
import sys
from pathlib import Path

import glfw
import moderngl

from visualgen import window
from visualgen.clock import VsyncClock
from visualgen.commands import Command
from visualgen.config import ConfigError, load_config
from visualgen.cues import CueManager, State
from visualgen.engine import PlaybackEngine
from visualgen.player import PlayerError
from visualgen.render import Renderer
from visualgen.show import ShowError, load_show

log = logging.getLogger("visualgen")


def _prevent_sleep() -> subprocess.Popen:
    return subprocess.Popen(["caffeinate", "-dis"])


def _parse_args(argv: list[str]) -> tuple[Path, Path]:
    if len(argv) < 2 or argv[1].startswith("-"):
        print("usage: visualgen <show.yaml> [--config <config.yaml>]", file=sys.stderr)
        raise SystemExit(2)
    show_path = Path(argv[1])
    if "--config" in argv:
        config_path = Path(argv[argv.index("--config") + 1])
    else:
        config_path = show_path.parent / "config.yaml"
    return show_path, config_path


def run(show_path: Path, config_path: Path) -> int:
    show = load_show(show_path)
    config = load_config(config_path)

    commands: queue.Queue[Command] = queue.Queue()
    cue_manager = CueManager(len(show.cues), wrap=show.wrap)
    clock = VsyncClock()

    caffeinate = _prevent_sleep()
    engine = PlaybackEngine(show, fallback=config.fallback)
    try:
        win, size = window.create_fullscreen("visualgen")
        ctx = moderngl.create_context()
        renderer = Renderer(ctx, size)

        def on_key(w, key, scancode, action, mods):
            if action != glfw.PRESS:
                return
            if key == glfw.KEY_ESCAPE:
                window.close(w)
            elif key == glfw.KEY_RIGHT:
                commands.put(Command.NEXT)
            elif key == glfw.KEY_LEFT:
                commands.put(Command.PREVIOUS)

        glfw.set_key_callback(win, on_key)

        engine.start(cue_manager.index, cue_manager.adjacent(), clock.now())

        while not window.should_close(win):
            glfw.poll_events()

            while True:
                try:
                    command = commands.get_nowait()
                except queue.Empty:
                    break
                target = cue_manager.handle(command)
                if target is not None:
                    engine.switch_to(target, cue_manager.adjacent(), clock.now())

            if cue_manager.state is State.SWITCHING and engine.preloads_ready():
                cue_manager.complete_switch()

            frame = engine.frame_at(clock.now())
            if frame is not None:
                renderer.draw(frame)
            else:
                renderer.draw_clear((0.0, 0.0, 0.0))
            glfw.swap_buffers(win)
        return 0
    finally:
        engine.stop()
        caffeinate.terminate()
        window.terminate()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    show_path, config_path = _parse_args(sys.argv)
    try:
        return run(show_path, config_path)
    except (ShowError, ConfigError, PlayerError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
