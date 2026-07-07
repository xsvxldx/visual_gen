from visualgen.commands import Command


def test_commands_exist():
    assert Command.NEXT is not Command.PREVIOUS
    assert {c.name for c in Command} == {"NEXT", "PREVIOUS"}
