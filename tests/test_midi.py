import mido

from visualgen.commands import Command
from visualgen.config import Config, MidiTrigger
from visualgen.inputs.midi import message_to_command

CFG = Config(
    midi_port=None,
    next_trigger=MidiTrigger("note_on", note=60, channel=None),
    previous_trigger=MidiTrigger("note_on", note=61, channel=None),
    fallback=None,
)


def test_next_note_maps_to_next():
    msg = mido.Message("note_on", note=60, velocity=100)
    assert message_to_command(msg, CFG) is Command.NEXT


def test_previous_note_maps_to_previous():
    msg = mido.Message("note_on", note=61, velocity=100)
    assert message_to_command(msg, CFG) is Command.PREVIOUS


def test_other_note_ignored():
    msg = mido.Message("note_on", note=62, velocity=100)
    assert message_to_command(msg, CFG) is None


def test_note_off_ignored():
    msg = mido.Message("note_off", note=60)
    assert message_to_command(msg, CFG) is None


def test_note_on_velocity_zero_ignored():
    msg = mido.Message("note_on", note=60, velocity=0)
    assert message_to_command(msg, CFG) is None


def test_channel_filter():
    cfg = Config(
        midi_port=None,
        next_trigger=MidiTrigger("note_on", note=60, channel=2),
        previous_trigger=MidiTrigger("note_on", note=61, channel=None),
        fallback=None,
    )
    assert message_to_command(mido.Message("note_on", note=60, velocity=1, channel=2), cfg) is Command.NEXT
    assert message_to_command(mido.Message("note_on", note=60, velocity=1, channel=0), cfg) is None
