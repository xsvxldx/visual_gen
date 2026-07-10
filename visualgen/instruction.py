from dataclasses import dataclass
from enum import Enum

from visualgen.player import Frame


class TransitionMode(Enum):
    """The selectable base-blend set. CUT never produces a Blend (see engine)."""

    CUT = "cut"
    DIP = "dip"
    CROSSFADE = "crossfade"
    WIPE = "wipe"


@dataclass(frozen=True)
class Single:
    """Draw one frame — normal playback (and, later, the middle of a morph)."""

    frame: Frame


@dataclass(frozen=True)
class Blend:
    """Blend two frames during a transition: progress t in [0, 1] under mode."""

    from_frame: Frame
    to_frame: Frame
    t: float
    mode: TransitionMode


RenderInstruction = Single | Blend
