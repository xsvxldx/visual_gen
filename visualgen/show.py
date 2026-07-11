from dataclasses import dataclass
from pathlib import Path

import yaml

from visualgen.instruction import TransitionMode


class ShowError(Exception):
    """A problem with the show file. Message is operator-readable."""


@dataclass(frozen=True)
class Cue:
    id: str
    source: Path


@dataclass(frozen=True)
class Show:
    cues: tuple[Cue, ...]
    wrap: bool = False
    transition: TransitionMode = TransitionMode.CUT
    duration: float = 0.8


def load_show(path: str | Path) -> Show:
    path = Path(path)
    try:
        text = path.read_text()
    except FileNotFoundError:
        raise ShowError(f"show file not found: {path}") from None
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ShowError(f"invalid YAML in {path}: {exc}") from None

    if not isinstance(data, dict) or "show" not in data:
        raise ShowError(f"{path}: expected a top-level 'show:' list")
    entries = data["show"]
    if not isinstance(entries, list) or not entries:
        raise ShowError(f"{path}: 'show:' must be a non-empty list of cues")

    wrap = bool(data.get("wrap", False))
    transition = _parse_transition(path, data.get("transition", "cut"))
    duration = _parse_duration(path, data.get("duration", 0.8))
    base = path.parent
    cues: list[Cue] = []
    seen: set[str] = set()
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict) or "id" not in entry or "source" not in entry:
            raise ShowError(f"{path}: cue #{i + 1} must have 'id' and 'source'")
        cue_id = str(entry["id"])
        if cue_id in seen:
            raise ShowError(f"{path}: duplicate cue id: {cue_id}")
        seen.add(cue_id)
        source = (base / str(entry["source"])).resolve()
        if not source.is_file():
            raise ShowError(f"{path}: cue '{cue_id}': source not found: {source}")
        cues.append(Cue(cue_id, source))
    return Show(tuple(cues), wrap, transition, duration)


def _parse_transition(path: Path, raw) -> TransitionMode:
    try:
        return TransitionMode(str(raw).lower())
    except ValueError:
        allowed = ", ".join(m.value for m in TransitionMode)
        raise ShowError(f"{path}: 'transition': got '{raw}', expected one of: {allowed}") from None


def _parse_duration(path: Path, raw) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ShowError(f"{path}: 'duration': must be a positive number, got '{raw}'") from None
    if value <= 0:
        raise ShowError(f"{path}: 'duration': must be a positive number, got {value}")
    return value
