from enum import Enum, auto

from visualgen.commands import Command


class State(Enum):
    PLAYING = auto()
    SWITCHING = auto()


class CueManager:
    """Pure cue-position state machine. No rendering, no MIDI, no file I/O."""

    def __init__(self, cue_count: int, wrap: bool = False):
        if cue_count < 1:
            raise ValueError("a show needs at least one cue")
        self._count = cue_count
        self._wrap = wrap
        self._index = 0
        self._state = State.PLAYING

    @property
    def index(self) -> int:
        return self._index

    @property
    def state(self) -> State:
        return self._state

    def handle(self, command: Command) -> int | None:
        if self._state is State.SWITCHING:
            return None
        delta = 1 if command is Command.NEXT else -1
        target = self._index + delta
        if self._wrap:
            target %= self._count
        elif not 0 <= target < self._count:
            return None
        if target == self._index:
            return None
        self._index = target
        self._state = State.SWITCHING
        return target

    def complete_switch(self) -> None:
        self._state = State.PLAYING

    def adjacent(self) -> set[int]:
        candidates = (self._index - 1, self._index + 1)
        if self._wrap:
            return {c % self._count for c in candidates} - {self._index}
        return {c for c in candidates if 0 <= c < self._count}
