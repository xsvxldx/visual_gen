import pytest

from visualgen.commands import Command
from visualgen.cues import CueManager, State


def test_starts_playing_at_zero():
    cm = CueManager(3)
    assert cm.index == 0
    assert cm.state is State.PLAYING


def test_next_enters_switching_and_moves_index():
    cm = CueManager(3)
    assert cm.handle(Command.NEXT) == 1
    assert cm.index == 1
    assert cm.state is State.SWITCHING


def test_commands_dropped_while_switching():
    cm = CueManager(3)
    cm.handle(Command.NEXT)
    assert cm.handle(Command.NEXT) is None
    assert cm.handle(Command.PREVIOUS) is None
    assert cm.index == 1


def test_complete_switch_returns_to_playing():
    cm = CueManager(3)
    cm.handle(Command.NEXT)
    cm.complete_switch()
    assert cm.state is State.PLAYING
    assert cm.handle(Command.NEXT) == 2


def test_edges_ignored_without_wrap():
    cm = CueManager(2)
    assert cm.handle(Command.PREVIOUS) is None
    assert cm.state is State.PLAYING
    cm.handle(Command.NEXT)
    cm.complete_switch()
    assert cm.handle(Command.NEXT) is None
    assert cm.index == 1


def test_edges_wrap_with_wrap():
    cm = CueManager(3, wrap=True)
    assert cm.handle(Command.PREVIOUS) == 2
    cm.complete_switch()
    assert cm.handle(Command.NEXT) == 0


def test_adjacent_middle():
    cm = CueManager(5)
    cm.handle(Command.NEXT)
    cm.complete_switch()
    cm.handle(Command.NEXT)  # index 2
    assert cm.adjacent() == {1, 3}


def test_adjacent_at_edges_without_wrap():
    assert CueManager(3).adjacent() == {1}


def test_adjacent_wraps():
    assert CueManager(3, wrap=True).adjacent() == {1, 2}


def test_adjacent_single_cue():
    assert CueManager(1).adjacent() == set()
    assert CueManager(1, wrap=True).adjacent() == set()


def test_requires_at_least_one_cue():
    with pytest.raises(ValueError):
        CueManager(0)
