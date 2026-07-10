import moderngl
import numpy as np

from visualgen.instruction import Blend, RenderInstruction, Single
from visualgen.player import Frame

_VERTEX = """
#version 330
in vec2 in_pos;
in vec2 in_uv;
out vec2 uv;
void main() {
    gl_Position = vec4(in_pos, 0.0, 1.0);
    uv = in_uv;
}
"""

_FRAGMENT = """
#version 330
uniform sampler2D tex_y;
uniform sampler2D tex_u;
uniform sampler2D tex_v;
in vec2 uv;
out vec4 fragColor;
void main() {
    float y = 1.1643 * (texture(tex_y, uv).r - 0.0625);
    float u = texture(tex_u, uv).r - 0.5;
    float v = texture(tex_v, uv).r - 0.5;
    vec3 rgb = vec3(
        y + 1.5958 * v,
        y - 0.39173 * u - 0.81290 * v,
        y + 2.017 * u
    );
    fragColor = vec4(rgb, 1.0);
}
"""


class Renderer:
    def __init__(self, ctx: moderngl.Context, window_size: tuple[int, int]):
        self._ctx = ctx
        self._window_size = window_size
        self._program = ctx.program(vertex_shader=_VERTEX, fragment_shader=_FRAGMENT)
        self._program["tex_y"].value = 0
        self._program["tex_u"].value = 1
        self._program["tex_v"].value = 2
        vertices = np.array(
            [
                -1.0, -1.0, 0.0, 1.0,
                 1.0, -1.0, 1.0, 1.0,
                -1.0,  1.0, 0.0, 0.0,
                 1.0,  1.0, 1.0, 0.0,
            ],
            dtype="f4",
        )
        vbo = ctx.buffer(vertices.tobytes())
        self._vao = ctx.vertex_array(self._program, [(vbo, "2f 2f", "in_pos", "in_uv")])
        self._textures: tuple[moderngl.Texture, ...] | None = None
        self._tex_size: tuple[int, int] | None = None

    def _ensure_textures(self, frame: Frame) -> None:
        if self._tex_size == (frame.width, frame.height):
            return
        if self._textures:
            for t in self._textures:
                t.release()
        w, h = frame.width, frame.height
        self._textures = (
            self._ctx.texture((w, h), 1, dtype="f1"),
            self._ctx.texture((w // 2, h // 2), 1, dtype="f1"),
            self._ctx.texture((w // 2, h // 2), 1, dtype="f1"),
        )
        for t in self._textures:
            t.filter = (moderngl.LINEAR, moderngl.LINEAR)
            t.swizzle = "RRR1"
        self._tex_size = (w, h)

    def _letterbox_viewport(self, frame: Frame) -> tuple[int, int, int, int]:
        ww, wh = self._window_size
        scale = min(ww / frame.width, wh / frame.height)
        vw, vh = int(frame.width * scale), int(frame.height * scale)
        return ((ww - vw) // 2, (wh - vh) // 2, vw, vh)

    def render(self, instruction: RenderInstruction) -> None:
        """Draw a render instruction. Single draws one frame; Blend mixes two."""
        if isinstance(instruction, Single):
            self.draw(instruction.frame)
        elif isinstance(instruction, Blend):
            self._draw_blend(instruction)

    def draw(self, frame: Frame) -> None:
        self._ensure_textures(frame)
        assert self._textures is not None
        self._textures[0].write(frame.y.tobytes())
        self._textures[1].write(frame.u.tobytes())
        self._textures[2].write(frame.v.tobytes())
        self._ctx.viewport = (0, 0, *self._window_size)
        self._ctx.clear(0.0, 0.0, 0.0)
        self._ctx.viewport = self._letterbox_viewport(frame)
        for unit, tex in enumerate(self._textures):
            tex.use(location=unit)
        self._vao.render(moderngl.TRIANGLE_STRIP)

    def _draw_blend(self, blend: Blend) -> None:
        raise NotImplementedError("two-frame blending arrives in the crossfade milestone")

    def draw_clear(self, rgb: tuple[float, float, float]) -> None:
        self._ctx.viewport = (0, 0, *self._window_size)
        self._ctx.clear(*rgb)
