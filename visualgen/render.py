import moderngl
import numpy as np

from visualgen.instruction import Blend, RenderInstruction, Single, TransitionMode
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

# Two-frame blend. uv spans the whole window; each frame is letterboxed independently
# into its own centered rect (from_rect / to_rect, in window uv), so a frame keeps its own
# aspect throughout the transition — never squished into the other's shape. Outside a frame's
# rect it reads black (the letterbox bars). Then the two are mixed per mode: dip=1 (through
# black), crossfade=2 (dissolve), wipe=3 (moving left-to-right edge). cut never reaches here.
_BLEND_FRAGMENT = """
#version 330
uniform sampler2D from_y;
uniform sampler2D from_u;
uniform sampler2D from_v;
uniform sampler2D to_y;
uniform sampler2D to_u;
uniform sampler2D to_v;
uniform float u_t;
uniform int u_mode;
uniform vec4 from_rect;  // x, y, w, h in window uv (0..1)
uniform vec4 to_rect;
in vec2 uv;
out vec4 fragColor;
vec3 yuv2rgb(sampler2D ty, sampler2D tu, sampler2D tv, vec2 st) {
    float y = 1.1643 * (texture(ty, st).r - 0.0625);
    float u = texture(tu, st).r - 0.5;
    float v = texture(tv, st).r - 0.5;
    return vec3(
        y + 1.5958 * v,
        y - 0.39173 * u - 0.81290 * v,
        y + 2.017 * u
    );
}
vec3 sample_boxed(sampler2D ty, sampler2D tu, sampler2D tv, vec4 rect) {
    vec2 st = (uv - rect.xy) / rect.zw;
    if (st.x < 0.0 || st.x > 1.0 || st.y < 0.0 || st.y > 1.0) {
        return vec3(0.0);  // outside this frame's rect -> letterbox bar
    }
    return yuv2rgb(ty, tu, tv, st);
}
void main() {
    vec3 a = sample_boxed(from_y, from_u, from_v, from_rect);
    vec3 b = sample_boxed(to_y, to_u, to_v, to_rect);
    vec3 rgb;
    if (u_mode == 1) {
        // dip through black: a fades out over the first half, b fades up over the second
        rgb = u_t < 0.5 ? a * (1.0 - 2.0 * u_t) : b * (2.0 * u_t - 1.0);
    } else if (u_mode == 3) {
        // wipe: hard left-to-right edge reveals b over a
        rgb = uv.x < u_t ? b : a;
    } else {
        // crossfade: linear dissolve
        rgb = mix(a, b, u_t);
    }
    fragColor = vec4(rgb, 1.0);
}
"""

_MODE_INT = {TransitionMode.DIP: 1, TransitionMode.CROSSFADE: 2, TransitionMode.WIPE: 3}


class Renderer:
    def __init__(self, ctx: moderngl.Context, window_size: tuple[int, int]):
        self._ctx = ctx
        self._window_size = window_size
        self._program = ctx.program(vertex_shader=_VERTEX, fragment_shader=_FRAGMENT)
        self._program["tex_y"].value = 0
        self._program["tex_u"].value = 1
        self._program["tex_v"].value = 2
        self._blend_program = ctx.program(vertex_shader=_VERTEX, fragment_shader=_BLEND_FRAGMENT)
        for name, unit in (
            ("from_y", 0), ("from_u", 1), ("from_v", 2),
            ("to_y", 3), ("to_u", 4), ("to_v", 5),
        ):
            self._blend_program[name].value = unit
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
        self._blend_vao = ctx.vertex_array(self._blend_program, [(vbo, "2f 2f", "in_pos", "in_uv")])
        # Two YUV texture triples: slot 0 is the single frame / blend "from"; slot 1 is blend "to".
        self._textures: list[tuple[moderngl.Texture, ...] | None] = [None, None]
        self._tex_size: list[tuple[int, int] | None] = [None, None]

    def _ensure_textures(self, slot: int, frame: Frame) -> None:
        if self._tex_size[slot] == (frame.width, frame.height):
            return
        if self._textures[slot]:
            for t in self._textures[slot]:
                t.release()
        w, h = frame.width, frame.height
        triple = (
            self._ctx.texture((w, h), 1, dtype="f1"),
            self._ctx.texture((w // 2, h // 2), 1, dtype="f1"),
            self._ctx.texture((w // 2, h // 2), 1, dtype="f1"),
        )
        for t in triple:
            t.filter = (moderngl.LINEAR, moderngl.LINEAR)
            t.swizzle = "RRR1"
        self._textures[slot] = triple
        self._tex_size[slot] = (w, h)

    def _upload(self, slot: int, frame: Frame) -> None:
        self._ensure_textures(slot, frame)
        triple = self._textures[slot]
        assert triple is not None
        triple[0].write(frame.y.tobytes())
        triple[1].write(frame.u.tobytes())
        triple[2].write(frame.v.tobytes())

    def _letterbox_viewport(self, frame: Frame) -> tuple[int, int, int, int]:
        ww, wh = self._window_size
        scale = min(ww / frame.width, wh / frame.height)
        vw, vh = int(frame.width * scale), int(frame.height * scale)
        return ((ww - vw) // 2, (wh - vh) // 2, vw, vh)

    def _letterbox_rect(self, frame: Frame) -> tuple[float, float, float, float]:
        # The frame's centered letterbox as a rect in window uv (0..1), for the blend shader.
        ww, wh = self._window_size
        scale = min(ww / frame.width, wh / frame.height)
        vw, vh = frame.width * scale, frame.height * scale
        return ((ww - vw) / 2 / ww, (wh - vh) / 2 / wh, vw / ww, vh / wh)

    def render(self, instruction: RenderInstruction) -> None:
        """Draw a render instruction. Single draws one frame; Blend mixes two."""
        if isinstance(instruction, Single):
            self.draw(instruction.frame)
        elif isinstance(instruction, Blend):
            self._draw_blend(instruction)

    def draw(self, frame: Frame) -> None:
        self._upload(0, frame)
        triple = self._textures[0]
        assert triple is not None
        self._ctx.viewport = (0, 0, *self._window_size)
        self._ctx.clear(0.0, 0.0, 0.0)
        self._ctx.viewport = self._letterbox_viewport(frame)
        for unit, tex in enumerate(triple):
            tex.use(location=unit)
        self._vao.render(moderngl.TRIANGLE_STRIP)

    def _draw_blend(self, blend: Blend) -> None:
        # Each frame is letterboxed independently in the shader (from_rect / to_rect), so both
        # keep their own aspect for the whole transition regardless of differing resolutions.
        self._upload(0, blend.from_frame)
        self._upload(1, blend.to_frame)
        self._blend_program["u_t"].value = blend.t
        self._blend_program["from_rect"].value = self._letterbox_rect(blend.from_frame)
        self._blend_program["to_rect"].value = self._letterbox_rect(blend.to_frame)
        self._blend_program["u_mode"].value = _MODE_INT.get(blend.mode, 2)
        self._ctx.viewport = (0, 0, *self._window_size)  # full window; shader draws the bars black
        self._ctx.clear(0.0, 0.0, 0.0)
        for unit, tex in enumerate((*self._textures[0], *self._textures[1])):
            tex.use(location=unit)
        self._blend_vao.render(moderngl.TRIANGLE_STRIP)

    def draw_clear(self, rgb: tuple[float, float, float]) -> None:
        self._ctx.viewport = (0, 0, *self._window_size)
        self._ctx.clear(*rgb)
