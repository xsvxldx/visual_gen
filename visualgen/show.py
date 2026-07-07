from dataclasses import dataclass
from pathlib import Path

import yaml


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
    return Show(tuple(cues), wrap)
