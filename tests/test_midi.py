import logging
import queue
import time

import mido

from visualgen.commands import Command
from visualgen.config import Config, MidiTrigger
from visualgen.inputs.midi import MidiAdapter, message_to_command

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


def test_unavailable_port_warns_once_not_on_every_retry(caplog):
    adapter = MidiAdapter(CFG, queue.Queue())
    adapter._retry_seconds = 0.001  # spin the reconnect loop fast

    def always_fails():
        raise OSError("no MIDI port")

    adapter._open_port = always_fails  # fail fast, deterministically, on every retry
    with caplog.at_level(logging.WARNING, logger="visualgen.inputs.midi"):
        adapter.start()
        time.sleep(0.1)  # ~100 reconnect iterations
        adapter.stop()
    warnings = [r for r in caplog.records if "MIDI unavailable" in r.getMessage()]
    assert len(warnings) == 1, f"repeated identical MIDI failures should warn once, got {len(warnings)}"


def test_channel_filter():
    cfg = Config(
        midi_port=None,
        next_trigger=MidiTrigger("note_on", note=60, channel=2),
        previous_trigger=MidiTrigger("note_on", note=61, channel=None),
        fallback=None,
    )
    assert message_to_command(mido.Message("note_on", note=60, velocity=1, channel=2), cfg) is Command.NEXT
    assert message_to_command(mido.Message("note_on", note=60, velocity=1, channel=0), cfg) is None
