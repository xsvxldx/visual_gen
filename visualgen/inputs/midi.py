import logging
import queue
import threading
import time

import mido

from visualgen.commands import Command
from visualgen.config import Config, MidiTrigger

log = logging.getLogger(__name__)

_RETRY_SECONDS = 2.0


def _matches(msg: "mido.Message", trigger: MidiTrigger) -> bool:
    if msg.type != "note_on" or trigger.type != "note_on":
        return False
    if msg.velocity == 0:
        return False
    if msg.note != trigger.note:
        return False
    if trigger.channel is not None and msg.channel != trigger.channel:
        return False
    return True


def message_to_command(msg: "mido.Message", config: Config) -> Command | None:
    if _matches(msg, config.next_trigger):
        return Command.NEXT
    if _matches(msg, config.previous_trigger):
        return Command.PREVIOUS
    return None


class MidiAdapter:
    def __init__(self, config: Config, commands: queue.Queue):
        self._config = config
        self._commands = commands
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _open_port(self):
        names = mido.get_input_names()
        if self._config.midi_port is not None:
            if self._config.midi_port not in names:
                raise OSError(f"MIDI port not found: {self._config.midi_port!r} (available: {names})")
            return mido.open_input(self._config.midi_port)
        if not names:
            raise OSError("no MIDI input ports available")
        return mido.open_input(names[0])

    def _run(self) -> None:
        port = None
        while not self._stop_event.is_set():
            if port is None:
                try:
                    port = self._open_port()
                    log.info("MIDI connected: %s", port.name)
                except Exception as exc:
                    log.warning("MIDI unavailable (%s); retrying in %.0fs", exc, _RETRY_SECONDS)
                    self._stop_event.wait(_RETRY_SECONDS)
                    continue
            try:
                for msg in port.iter_pending():
                    command = message_to_command(msg, self._config)
                    if command is not None:
                        self._commands.put(command)
                time.sleep(0.002)
            except Exception as exc:
                log.warning("MIDI port error (%s); reconnecting", exc)
                try:
                    port.close()
                except Exception:
                    pass
                port = None
        if port is not None:
            port.close()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
