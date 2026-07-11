from enum import Enum, auto

_DURATION_STEP = 0.1


class Command(Enum):
    NEXT = auto()
    PREVIOUS = auto()
    RECALL = auto()
    CYCLE_TRANSITION = auto()  # live: cut -> dip -> crossfade -> wipe -> cut
    DURATION_UP = auto()  # live: transition duration + step
    DURATION_DOWN = auto()  # live: transition duration - step


def apply_transition_command(engine, command: Command) -> bool:
    """Apply a live transition-parameter command to the engine (session-only).

    Returns True if it was a parameter command and was handled, False otherwise —
    so the caller can fall through to the cue-position path for NEXT/PREVIOUS/RECALL.
    """
    if command is Command.CYCLE_TRANSITION:
        engine.cycle_mode()
    elif command is Command.DURATION_UP:
        engine.adjust_duration(_DURATION_STEP)
    elif command is Command.DURATION_DOWN:
        engine.adjust_duration(-_DURATION_STEP)
    else:
        return False
    return True
