from visualgen.commands import Command, apply_transition_command


def test_commands_exist():
    assert Command.NEXT is not Command.PREVIOUS
    assert {c.name for c in Command} == {
        "NEXT",
        "PREVIOUS",
        "RECALL",
        "CYCLE_TRANSITION",
        "DURATION_UP",
        "DURATION_DOWN",
    }


class _FakeEngine:
    def __init__(self):
        self.cycles = 0
        self.deltas = []

    def cycle_mode(self):
        self.cycles += 1

    def adjust_duration(self, delta):
        self.deltas.append(delta)


def test_param_commands_route_to_engine():
    engine = _FakeEngine()
    assert apply_transition_command(engine, Command.CYCLE_TRANSITION) is True
    assert apply_transition_command(engine, Command.DURATION_UP) is True
    assert apply_transition_command(engine, Command.DURATION_DOWN) is True
    assert engine.cycles == 1
    assert engine.deltas == [0.1, -0.1]


def test_position_commands_are_not_handled_as_params():
    engine = _FakeEngine()
    for command in (Command.NEXT, Command.PREVIOUS, Command.RECALL):
        assert apply_transition_command(engine, command) is False
    assert engine.cycles == 0
    assert engine.deltas == []
