import moderngl


class Renderer:
    """Draws what it is told. Knows nothing about cues, MIDI, or YAML."""

    def __init__(self, ctx: moderngl.Context, window_size: tuple[int, int]):
        self._ctx = ctx
        self._window_size = window_size

    def draw_clear(self, rgb: tuple[float, float, float]) -> None:
        self._ctx.viewport = (0, 0, *self._window_size)
        self._ctx.clear(*rgb)
