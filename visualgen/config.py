from dataclasses import dataclass
from pathlib import Path

import yaml


class ConfigError(Exception):
    """A problem with the config file. Message is operator-readable."""


@dataclass(frozen=True)
class MidiTrigger:
    type: str
    note: int
    channel: int | None = None


@dataclass(frozen=True)
class Config:
    midi_port: str | None
    next_trigger: MidiTrigger
    previous_trigger: MidiTrigger
    fallback: Path | None


DEFAULT_NEXT = MidiTrigger("note_on", note=60, channel=None)
DEFAULT_PREVIOUS = MidiTrigger("note_on", note=61, channel=None)


def _parse_trigger(raw: object, key: str, default: MidiTrigger, path: Path) -> MidiTrigger:
    if raw is None:
        return default
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: 'midi.{key}' must be a mapping")
    trig_type = str(raw.get("type", "note_on"))
    if trig_type != "note_on":
        raise ConfigError(
            f"{path}: 'midi.{key}': only type 'note_on' is supported in the MVP, got '{trig_type}'"
        )
    if "note" not in raw:
        raise ConfigError(f"{path}: 'midi.{key}' needs a 'note'")
    channel = raw.get("channel")
    return MidiTrigger("note_on", note=int(raw["note"]), channel=None if channel is None else int(channel))


def load_config(path: str | Path) -> Config:
    path = Path(path)
    try:
        text = path.read_text()
    except FileNotFoundError:
        return Config(None, DEFAULT_NEXT, DEFAULT_PREVIOUS, None)
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from None
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: config must be a mapping")

    midi = data.get("midi") or {}
    if not isinstance(midi, dict):
        raise ConfigError(f"{path}: 'midi:' must be a mapping")
    port = midi.get("port")

    fallback = None
    if data.get("fallback") is not None:
        fallback = (path.parent / str(data["fallback"])).resolve()
        if not fallback.is_file():
            raise ConfigError(f"{path}: fallback video not found: {fallback}")

    return Config(
        midi_port=None if port is None else str(port),
        next_trigger=_parse_trigger(midi.get("next"), "next", DEFAULT_NEXT, path),
        previous_trigger=_parse_trigger(midi.get("previous"), "previous", DEFAULT_PREVIOUS, path),
        fallback=fallback,
    )
