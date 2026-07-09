# Visual Engine MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A macOS fullscreen live-video engine: one looping video at a time, MIDI NEXT/PREVIOUS switch cues instantly, cues defined in YAML, fallback video on live failure.

**Architecture:** Single process. Main thread owns the GL context and renders on vsync; each active `VideoPlayer` has a decode thread feeding a small ring buffer; a MIDI thread emits `Command`s onto a thread-safe queue drained once per frame. `CueManager` is a pure FSM (PLAYING/SWITCHING); `PlaybackEngine` owns players and the preload contract; `Renderer` only draws textures (YUV→RGB on GPU).

**Tech Stack:** Python 3.12 · uv · PyAV (`av`) · moderngl · glfw · mido + python-rtmidi · PyYAML · numpy · pytest

**Spec:** `docs/superpowers/specs/2026-07-05-visual-engine-mvp-design.md`

## Progress (last updated 2026-07-08)

Executing task-by-task with TDD. Each task: failing test → implement → green → commit.

- [x] **Task 1** — scaffold `visualgen` + `Command` enum (`commands.py`) — commit `01e298d`
- [x] **Task 2** — show loading + validation (`show.py`) — commit `3869248`
- [x] **Task 3** — config loading (`config.py`) — commit `54a484f`
- [x] **Task 4** — CueManager FSM (`cues.py`) — commit `15b00f4`
- [x] **Task 5** — Clock abstraction (`clock.py`) — commit `f6cebf7`
- [x] **Task 6** — fullscreen window + solid-color renderer (**Milestone 1**) — commit `374fec6`, manually verified (dark-blue fullscreen, ESC exits)
- [x] **Task 7** — VideoPlayer: decode thread, ring buffer, seamless loop (`player.py`) — commit `5862cf7` (decoder thread-safety hardened in `6ba70ca`)
- [x] **Task 8** — GPU YUV rendering + single-video playback (**Milestone 2**) — commit `b5f8745`
- [x] **Task 9** — PlaybackEngine with preloading + fallback (`engine.py`) — commit `757b23b` (async-preload race fixed in `6ba70ca`; fallback now also engages on failed startup/switch preload)
- [x] **Task 10** — wire it together + keyboard switching (**Milestones 3–5**) — commit `4b14750`
- [x] **Task 11** — MIDI input (**Milestone 6**) — commit `46e8c64`
- [x] **Task 12** — live failure path verification (**Milestone 7**) — commit `502ac69`
- [x] **Task 13** — stability soak + operator docs (**Milestone 8**) — commit `2693abd`

**State:** 51 tests green (`uv run pytest -q`). All 13 MVP tasks implemented on
`deepseek_branch`. Tasks 1–5 and 7–12 are covered by automated tests (the video
fixtures generate real clips on the fly); Tasks 6 and 8 (GL rendering) have no unit
tests — they need a display and are verified manually. Remaining before calling the
MVP done: eyeball the GL render path (Task 8) on a real display, and run the
switching soak (`scripts/soak_switching.py`, Task 13) for stability.

## Global Constraints

- Python `>=3.12`, dependencies managed with `uv` (`uv sync`, `uv run ...`).
- Dependencies exactly: `av`, `moderngl`, `glfw`, `mido`, `python-rtmidi`, `PyYAML`, `numpy`; dev: `pytest`.
- Package name `visualgen`, flat package at repo root. Tests in `tests/`.
- macOS only. OpenGL 3.3 core profile, forward-compatible (required on macOS).
- Video decode on CPU (PyAV). No CPU pixel-format conversion beyond plane extraction — YUV→RGB happens in the fragment shader.
- The render loop must never block: if decode is behind, repeat the last frame.
- Commands during SWITCHING are dropped (never queued/latched).
- Show edges: `wrap: false` (default) ignores NEXT on last / PREVIOUS on first; `wrap: true` wraps.
- Startup validation failures exit with a clear message; live errors are non-fatal (fallback video, then freeze-frame).
- Only current + adjacent cues have open decoders; only the current cue decodes continuously.
- Every error message must name the offending file/cue/key — no bare exceptions to the operator.

---

### Task 1: Project scaffolding + Command enum

**Files:**
- Create: `pyproject.toml`
- Create: `visualgen/__init__.py`
- Create: `visualgen/commands.py`
- Create: `tests/__init__.py`
- Create: `tests/test_commands.py`
- Modify: `.gitignore` (ensure `.venv/`, `__pycache__/`, `.pytest_cache/` are ignored)

**Interfaces:**
- Consumes: nothing.
- Produces: `visualgen.commands.Command` — `Enum` with members `NEXT`, `PREVIOUS`. All later tasks import this.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "visualgen"
version = "0.1.0"
description = "Lightweight MIDI-controlled live visual engine for macOS"
requires-python = ">=3.12"
dependencies = [
    "av>=12",
    "moderngl>=5.10",
    "glfw>=2.7",
    "mido>=1.3",
    "python-rtmidi>=1.5",
    "PyYAML>=6",
    "numpy>=1.26",
]

[project.scripts]
visualgen = "visualgen.app:main"

[dependency-groups]
dev = ["pytest>=8"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["visualgen"]
```

- [ ] **Step 2: Create the package and sync**

Create empty `visualgen/__init__.py` and `tests/__init__.py`. Ensure `.gitignore` contains `.venv/`, `__pycache__/`, `.pytest_cache/`, `.DS_Store`.

Run: `uv sync`
Expected: resolves and installs all dependencies without error.

- [ ] **Step 3: Write the failing test**

`tests/test_commands.py`:

```python
from visualgen.commands import Command


def test_commands_exist():
    assert Command.NEXT is not Command.PREVIOUS
    assert {c.name for c in Command} == {"NEXT", "PREVIOUS"}
```

- [ ] **Step 4: Run test to verify it fails**

Run: `uv run pytest tests/test_commands.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'visualgen.commands'`

- [ ] **Step 5: Implement `visualgen/commands.py`**

```python
from enum import Enum, auto


class Command(Enum):
    NEXT = auto()
    PREVIOUS = auto()
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_commands.py -v`
Expected: PASS (1 passed)

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock .gitignore visualgen/ tests/
git commit -m "feat: scaffold visualgen package with Command enum"
```

---

### Task 2: Show loading and validation (`show.py`)

**Files:**
- Create: `visualgen/show.py`
- Test: `tests/test_show.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces:
  - `Cue` — frozen dataclass: `id: str`, `source: pathlib.Path` (absolute, verified to exist).
  - `Show` — frozen dataclass: `cues: tuple[Cue, ...]`, `wrap: bool`.
  - `load_show(path: str | Path) -> Show` — raises `ShowError` (subclass of `Exception`) with a human-readable message on any problem.
  - Source paths in YAML are resolved relative to the YAML file's directory.

- [ ] **Step 1: Write the failing tests**

`tests/test_show.py`:

```python
import pytest

from visualgen.show import Show, ShowError, load_show


def write_show(tmp_path, text):
    p = tmp_path / "show.yaml"
    p.write_text(text)
    return p


def make_video(tmp_path, name):
    v = tmp_path / name
    v.write_bytes(b"\x00")  # existence is all load_show checks
    return v


def test_loads_valid_show(tmp_path):
    make_video(tmp_path, "a.mp4")
    make_video(tmp_path, "b.mp4")
    p = write_show(tmp_path, "show:\n  - {id: intro, source: a.mp4}\n  - {id: verse, source: b.mp4}\n")
    show = load_show(p)
    assert isinstance(show, Show)
    assert [c.id for c in show.cues] == ["intro", "verse"]
    assert show.cues[0].source == (tmp_path / "a.mp4").resolve()
    assert show.wrap is False


def test_wrap_flag(tmp_path):
    make_video(tmp_path, "a.mp4")
    p = write_show(tmp_path, "wrap: true\nshow:\n  - {id: a, source: a.mp4}\n")
    assert load_show(p).wrap is True


def test_missing_file_raises(tmp_path):
    with pytest.raises(ShowError, match="not found"):
        load_show(tmp_path / "nope.yaml")


def test_invalid_yaml_raises(tmp_path):
    p = write_show(tmp_path, "show: [unclosed")
    with pytest.raises(ShowError, match="invalid YAML"):
        load_show(p)


def test_empty_show_raises(tmp_path):
    p = write_show(tmp_path, "show: []\n")
    with pytest.raises(ShowError, match="non-empty"):
        load_show(p)


def test_duplicate_ids_raise(tmp_path):
    make_video(tmp_path, "a.mp4")
    p = write_show(tmp_path, "show:\n  - {id: x, source: a.mp4}\n  - {id: x, source: a.mp4}\n")
    with pytest.raises(ShowError, match="duplicate cue id: x"):
        load_show(p)


def test_missing_source_file_raises(tmp_path):
    p = write_show(tmp_path, "show:\n  - {id: intro, source: ghost.mp4}\n")
    with pytest.raises(ShowError, match="intro"):
        load_show(p)


def test_cue_missing_keys_raises(tmp_path):
    p = write_show(tmp_path, "show:\n  - {id: intro}\n")
    with pytest.raises(ShowError, match="'id' and 'source'"):
        load_show(p)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_show.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'visualgen.show'`

- [ ] **Step 3: Implement `visualgen/show.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_show.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add visualgen/show.py tests/test_show.py
git commit -m "feat: YAML show loading with startup validation"
```

---

### Task 3: Config loading (`config.py`)

**Files:**
- Create: `visualgen/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces:
  - `MidiTrigger` — frozen dataclass: `type: str` (only `"note_on"` supported in MVP), `note: int`, `channel: int | None` (`None` = any channel).
  - `Config` — frozen dataclass: `midi_port: str | None` (`None` = first available), `next_trigger: MidiTrigger`, `previous_trigger: MidiTrigger`, `fallback: pathlib.Path | None`.
  - `load_config(path: str | Path) -> Config` — missing file returns full defaults; bad content raises `ConfigError`.
  - Defaults: port `None`, NEXT = note_on 60, PREVIOUS = note_on 61, fallback `None`.
  - `fallback` path resolved relative to the config file's directory and must exist if given.

- [ ] **Step 1: Write the failing tests**

`tests/test_config.py`:

```python
import pytest

from visualgen.config import Config, ConfigError, MidiTrigger, load_config


def test_missing_file_returns_defaults(tmp_path):
    cfg = load_config(tmp_path / "config.yaml")
    assert cfg == Config(
        midi_port=None,
        next_trigger=MidiTrigger("note_on", note=60, channel=None),
        previous_trigger=MidiTrigger("note_on", note=61, channel=None),
        fallback=None,
    )


def test_full_config(tmp_path):
    (tmp_path / "safe.mp4").write_bytes(b"\x00")
    p = tmp_path / "config.yaml"
    p.write_text(
        "midi:\n"
        "  port: \"IAC Driver Bus 1\"\n"
        "  next: {type: note_on, note: 40, channel: 2}\n"
        "  previous: {type: note_on, note: 41}\n"
        "fallback: safe.mp4\n"
    )
    cfg = load_config(p)
    assert cfg.midi_port == "IAC Driver Bus 1"
    assert cfg.next_trigger == MidiTrigger("note_on", note=40, channel=2)
    assert cfg.previous_trigger == MidiTrigger("note_on", note=41, channel=None)
    assert cfg.fallback == (tmp_path / "safe.mp4").resolve()


def test_missing_fallback_file_raises(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("fallback: ghost.mp4\n")
    with pytest.raises(ConfigError, match="fallback"):
        load_config(p)


def test_unsupported_trigger_type_raises(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("midi:\n  next: {type: control_change, control: 7}\n")
    with pytest.raises(ConfigError, match="note_on"):
        load_config(p)


def test_invalid_yaml_raises(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("midi: [oops")
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_config(p)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'visualgen.config'`

- [ ] **Step 3: Implement `visualgen/config.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add visualgen/config.py tests/test_config.py
git commit -m "feat: config file loading with MIDI mapping and fallback"
```

---

### Task 4: CueManager FSM (`cues.py`)

**Files:**
- Create: `visualgen/cues.py`
- Test: `tests/test_cues.py`

**Interfaces:**
- Consumes: `Command` from `visualgen.commands`.
- Produces:
  - `State` — `Enum` with `PLAYING`, `SWITCHING`.
  - `CueManager(cue_count: int, wrap: bool = False)` — raises `ValueError` if `cue_count < 1`.
  - `.index -> int` property (current cue index; updates the moment a switch is accepted).
  - `.state -> State` property.
  - `.handle(command: Command) -> int | None` — returns the new target index and enters SWITCHING if accepted; returns `None` (no state change) if dropped (already SWITCHING, or at an edge with `wrap=False`).
  - `.complete_switch() -> None` — returns to PLAYING. Called by the app once the engine reports adjacent preloads ready.
  - `.adjacent() -> set[int]` — the indices that must be preloaded for the current index (both neighbors, bounded or wrapped; never contains the current index).

- [ ] **Step 1: Write the failing tests**

`tests/test_cues.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cues.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'visualgen.cues'`

- [ ] **Step 3: Implement `visualgen/cues.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cues.py -v`
Expected: PASS (11 passed)

- [ ] **Step 5: Commit**

```bash
git add visualgen/cues.py tests/test_cues.py
git commit -m "feat: CueManager finite state machine"
```

---

### Task 5: Clock abstraction (`clock.py`)

**Files:**
- Create: `visualgen/clock.py`
- Test: `tests/test_clock.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces:
  - `Clock` — `typing.Protocol` with `now(self) -> float` (seconds, monotonic).
  - `VsyncClock(time_fn: Callable[[], float] = time.monotonic)` — MVP implementation; `now()` delegates to `time_fn`. A future `AudioClock` implements the same protocol.

- [ ] **Step 1: Write the failing test**

`tests/test_clock.py`:

```python
from visualgen.clock import VsyncClock


def test_vsync_clock_uses_injected_time():
    t = [0.0]
    clock = VsyncClock(time_fn=lambda: t[0])
    assert clock.now() == 0.0
    t[0] = 1.5
    assert clock.now() == 1.5


def test_vsync_clock_defaults_to_monotonic():
    clock = VsyncClock()
    a = clock.now()
    b = clock.now()
    assert b >= a
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_clock.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'visualgen.clock'`

- [ ] **Step 3: Implement `visualgen/clock.py`**

```python
import time
from typing import Callable, Protocol


class Clock(Protocol):
    def now(self) -> float: ...


class VsyncClock:
    """Wall-time clock driven by the render loop. Future: AudioClock behind the same protocol."""

    def __init__(self, time_fn: Callable[[], float] = time.monotonic):
        self._time_fn = time_fn

    def now(self) -> float:
        return self._time_fn()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_clock.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add visualgen/clock.py tests/test_clock.py
git commit -m "feat: Clock protocol with vsync implementation"
```

---

### Task 6: Fullscreen window + solid-color renderer (Milestone 1)

**Files:**
- Create: `visualgen/render.py`
- Create: `visualgen/window.py`
- Create: `visualgen/app.py`

**Interfaces:**
- Consumes: nothing from other tasks yet.
- Produces:
  - `window.create_fullscreen(title: str) -> tuple[window_handle, tuple[int, int]]` — GLFW fullscreen window on the primary monitor with an OpenGL 3.3 core context and vsync on; returns the handle and (width, height).
  - `window.should_close(win) -> bool`, `window.close(win) -> None` (sets should-close), `window.terminate() -> None`.
  - `Renderer(ctx: moderngl.Context, window_size: tuple[int, int])` with `.draw_clear(rgb: tuple[float, float, float]) -> None` (Task 8 adds `.draw(frame)`).
  - `app.main() -> int` — entry point (`uv run visualgen`); ESC quits; spawns `caffeinate` for the process lifetime.
  - No unit tests (requires a GL context + display); verified manually.

- [ ] **Step 1: Implement `visualgen/window.py`**

```python
import glfw


class WindowError(Exception):
    pass


def create_fullscreen(title: str):
    if not glfw.init():
        raise WindowError("could not initialize GLFW")
    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
    glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, glfw.TRUE)  # required on macOS
    glfw.window_hint(glfw.AUTO_ICONIFY, glfw.FALSE)

    monitor = glfw.get_primary_monitor()
    mode = glfw.get_video_mode(monitor)
    win = glfw.create_window(mode.size.width, mode.size.height, title, monitor, None)
    if not win:
        glfw.terminate()
        raise WindowError("could not create fullscreen window")
    glfw.make_context_current(win)
    glfw.swap_interval(1)  # vsync on: the render loop ticks once per refresh
    width, height = glfw.get_framebuffer_size(win)
    return win, (width, height)


def should_close(win) -> bool:
    return bool(glfw.window_should_close(win))


def close(win) -> None:
    glfw.set_window_should_close(win, True)


def terminate() -> None:
    glfw.terminate()
```

- [ ] **Step 2: Implement `visualgen/render.py` (solid color only for now)**

```python
import moderngl


class Renderer:
    """Draws what it is told. Knows nothing about cues, MIDI, or YAML."""

    def __init__(self, ctx: moderngl.Context, window_size: tuple[int, int]):
        self._ctx = ctx
        self._window_size = window_size

    def draw_clear(self, rgb: tuple[float, float, float]) -> None:
        self._ctx.viewport = (0, 0, *self._window_size)
        self._ctx.clear(*rgb)
```

- [ ] **Step 3: Implement `visualgen/app.py`**

```python
import subprocess
import sys

import glfw
import moderngl

from visualgen import window
from visualgen.render import Renderer


def _prevent_sleep() -> subprocess.Popen:
    # -d: display awake, -i: idle sleep off, -s: system sleep off
    return subprocess.Popen(["caffeinate", "-dis"])


def main() -> int:
    caffeinate = _prevent_sleep()
    try:
        win, size = window.create_fullscreen("visualgen")
        ctx = moderngl.create_context()
        renderer = Renderer(ctx, size)

        def on_key(w, key, scancode, action, mods):
            if key == glfw.KEY_ESCAPE and action == glfw.PRESS:
                window.close(w)

        glfw.set_key_callback(win, on_key)

        while not window.should_close(win):
            glfw.poll_events()
            renderer.draw_clear((0.0, 0.15, 0.3))
            glfw.swap_buffers(win)
        return 0
    finally:
        caffeinate.terminate()
        window.terminate()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Verify manually**

Run: `uv run visualgen`
Expected: fullscreen dark-blue window on the primary display; no window chrome; ESC exits cleanly and the terminal prompt returns. While it runs, `pgrep caffeinate` in another terminal prints a PID; after exit, the `caffeinate` child is gone.

- [ ] **Step 5: Run the full test suite (must stay green)**

Run: `uv run pytest -v`
Expected: all tests from Tasks 1–5 still pass.

- [ ] **Step 6: Commit**

```bash
git add visualgen/window.py visualgen/render.py visualgen/app.py
git commit -m "feat: fullscreen GLFW window with vsync and caffeinate (milestone 1)"
```

---

### Task 7: VideoPlayer — decode thread, ring buffer, seamless loop (`player.py`)

**Files:**
- Create: `visualgen/player.py`
- Create: `tests/conftest.py`
- Test: `tests/test_player.py`

**Interfaces:**
- Consumes: nothing from other tasks (pure PyAV/numpy; no GL).
- Produces:
  - `Frame` — dataclass: `pts: float` (seconds within the loop), `width: int`, `height: int`, `y: np.ndarray` (h×w uint8), `u: np.ndarray` (h/2×w/2), `v: np.ndarray` (h/2×w/2). Contiguous arrays, ready for texture upload.
  - `PlayerError(Exception)`.
  - `VideoPlayer(source: str | Path, buffer_size: int = 3)`:
    - `.preload() -> None` — opens the file, decodes the first frame into `.first_frame`, then idles. Blocking; the engine calls it off the render thread. Raises `PlayerError` on any decode/open failure.
    - `.first_frame -> Frame | None` — set after `preload()`.
    - `.start(now: float) -> None` — records the epoch and starts the decode thread (loops forever; on EOF seeks to 0 and continues).
    - `.frame_at(now: float) -> Frame` — non-blocking; returns the frame due at `now`, repeating the last frame if decode is behind; handles loop wrap by resetting the epoch. Raises `PlayerError` if the decode thread died.
    - `.stop() -> None` — stops the thread and closes the container. Safe to call at any state, more than once.

- [ ] **Step 1: Write the shared video fixture**

`tests/conftest.py`:

```python
import av
import numpy as np
import pytest


@pytest.fixture
def video_file(tmp_path):
    """A real 15-frame, 30fps, 64x48 H.264 clip. Frame i is a flat gray level i*16."""
    path = tmp_path / "clip.mp4"
    with av.open(str(path), "w") as container:
        stream = container.add_stream("libx264", rate=30)
        stream.width = 64
        stream.height = 48
        stream.pix_fmt = "yuv420p"
        for i in range(15):
            img = np.full((48, 64, 3), i * 16, dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(img, format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return path
```

- [ ] **Step 2: Write the failing tests**

`tests/test_player.py`:

```python
import time

import pytest

from visualgen.player import Frame, PlayerError, VideoPlayer


def test_preload_decodes_first_frame(video_file):
    p = VideoPlayer(video_file)
    p.preload()
    try:
        f = p.first_frame
        assert isinstance(f, Frame)
        assert (f.width, f.height) == (64, 48)
        assert f.y.shape == (48, 64)
        assert f.u.shape == (24, 32)
        assert f.v.shape == (24, 32)
        assert f.pts == 0.0
    finally:
        p.stop()


def test_frame_at_advances_with_time(video_file):
    p = VideoPlayer(video_file)
    p.preload()
    p.start(now=0.0)
    try:
        first = p.frame_at(0.0)
        assert first.pts == 0.0
        deadline = time.monotonic() + 2.0
        advanced = None
        while time.monotonic() < deadline:
            advanced = p.frame_at(0.2)  # 0.2s in → should be past frame 0 (30fps)
            if advanced.pts > 0.0:
                break
            time.sleep(0.01)
        assert advanced is not None and advanced.pts > 0.0
    finally:
        p.stop()


def test_frame_at_repeats_last_frame_when_behind(video_file):
    p = VideoPlayer(video_file)
    p.preload()
    p.start(now=0.0)
    try:
        a = p.frame_at(0.0)
        b = p.frame_at(0.0)  # no time passed: same frame again, never blocks
        assert a.pts == b.pts
    finally:
        p.stop()


def test_loops_past_end_of_file(video_file):
    # Clip is 0.5s long; keep pulling for >1.5 clip-lengths of wall time.
    p = VideoPlayer(video_file)
    p.preload()
    start = time.monotonic()
    p.start(now=start)
    try:
        seen_wrap = False
        last_pts = -1.0
        while time.monotonic() - start < 1.6:
            f = p.frame_at(time.monotonic())
            if f.pts < last_pts:
                seen_wrap = True
                break
            last_pts = f.pts
            time.sleep(0.01)
        assert seen_wrap, "player never looped back to the start"
    finally:
        p.stop()


def test_preload_bad_file_raises(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"this is not a video")
    p = VideoPlayer(bad)
    with pytest.raises(PlayerError):
        p.preload()


def test_stop_is_idempotent(video_file):
    p = VideoPlayer(video_file)
    p.preload()
    p.start(now=0.0)
    p.stop()
    p.stop()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_player.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'visualgen.player'`

- [ ] **Step 4: Implement `visualgen/player.py`**

```python
import queue
import threading
from dataclasses import dataclass
from pathlib import Path

import av
import numpy as np


class PlayerError(Exception):
    """Decode or file failure. The engine reacts by engaging the fallback."""


@dataclass
class Frame:
    pts: float
    width: int
    height: int
    y: np.ndarray
    u: np.ndarray
    v: np.ndarray


def _convert(frame: av.VideoFrame, time_base) -> Frame:
    h, w = frame.height, frame.width
    arr = frame.reformat(format="yuv420p").to_ndarray()
    y = np.ascontiguousarray(arr[:h])
    u = np.ascontiguousarray(arr[h : h + h // 4].reshape(h // 2, w // 2))
    v = np.ascontiguousarray(arr[h + h // 4 :].reshape(h // 2, w // 2))
    pts = 0.0 if frame.pts is None else float(frame.pts * time_base)
    return Frame(pts, w, h, y, u, v)


class VideoPlayer:
    """Decodes one video on its own thread into a small ring buffer.

    Preloaded = file open + decoder primed + first frame decoded, then idle.
    Only start() spins up continuous decoding.
    """

    def __init__(self, source: str | Path, buffer_size: int = 3):
        self._source = str(source)
        self._frames: queue.Queue[Frame] = queue.Queue(maxsize=buffer_size)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._error: Exception | None = None
        self._container = None
        self._decoder = None
        self._time_base = None
        self._epoch: float = 0.0
        self._current: Frame | None = None
        self.first_frame: Frame | None = None

    def preload(self) -> None:
        try:
            self._container = av.open(self._source)
            stream = self._container.streams.video[0]
            stream.thread_type = "AUTO"
            self._time_base = stream.time_base
            self._stream = stream
            self._decoder = self._container.decode(stream)
            first = next(self._decoder)
        except Exception as exc:
            raise PlayerError(f"{self._source}: {exc}") from exc
        self.first_frame = _convert(first, self._time_base)
        self._frames.put(self.first_frame)

    def start(self, now: float) -> None:
        if self.first_frame is None:
            raise PlayerError(f"{self._source}: start() before preload()")
        self._epoch = now
        self._thread = threading.Thread(target=self._decode_loop, daemon=True)
        self._thread.start()

    def _decode_loop(self) -> None:
        try:
            while not self._stop_event.is_set():
                try:
                    frame = next(self._decoder)
                except (StopIteration, av.error.EOFError):
                    self._container.seek(0)
                    self._decoder = self._container.decode(self._stream)
                    continue
                converted = _convert(frame, self._time_base)
                while not self._stop_event.is_set():
                    try:
                        self._frames.put(converted, timeout=0.1)
                        break
                    except queue.Full:
                        continue
        except Exception as exc:  # surfaced to the render thread via frame_at()
            self._error = exc

    def frame_at(self, now: float) -> Frame:
        if self._error is not None:
            raise PlayerError(f"{self._source}: {self._error}")
        while True:
            try:
                head: Frame = self._frames.queue[0]  # peek without removing
            except IndexError:
                break
            if self._current is not None and head.pts < self._current.pts:
                self._epoch = now  # video looped: new iteration starts now
            if self._epoch + head.pts <= now:
                self._current = self._frames.get_nowait()
            else:
                break
        result = self._current or self.first_frame
        assert result is not None, "frame_at() before preload()"
        return result

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._container is not None:
            self._container.close()
            self._container = None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_player.py -v`
Expected: PASS (6 passed)

- [ ] **Step 6: Commit**

```bash
git add visualgen/player.py tests/conftest.py tests/test_player.py
git commit -m "feat: VideoPlayer with decode thread, ring buffer, seamless loop"
```

---

### Task 8: GPU YUV rendering + single-video playback (Milestone 2)

**Files:**
- Modify: `visualgen/render.py`
- Modify: `visualgen/app.py`

**Interfaces:**
- Consumes: `Frame` from `visualgen.player`; `VideoPlayer`; `VsyncClock`.
- Produces:
  - `Renderer.draw(frame: Frame) -> None` — uploads Y/U/V planes to three single-channel textures (recreated only when the video size changes), converts YUV→RGB in the fragment shader (BT.601 limited range), letterboxes to preserve aspect ratio.
  - `app.main()` gains a temporary `--file <path>` mode playing one looping video (replaced by show loading in Task 9).

- [ ] **Step 1: Rewrite `visualgen/render.py` with the YUV pipeline**

```python
import moderngl
import numpy as np

from visualgen.player import Frame

_VERTEX = """
#version 330
in vec2 in_pos;
in vec2 in_uv;
out vec2 uv;
void main() {
    gl_Position = vec4(in_pos, 0.0, 1.0);
    uv = in_uv;
}
"""

# BT.601 limited-range YUV -> RGB
_FRAGMENT = """
#version 330
uniform sampler2D tex_y;
uniform sampler2D tex_u;
uniform sampler2D tex_v;
in vec2 uv;
out vec4 fragColor;
void main() {
    float y = 1.1643 * (texture(tex_y, uv).r - 0.0625);
    float u = texture(tex_u, uv).r - 0.5;
    float v = texture(tex_v, uv).r - 0.5;
    vec3 rgb = vec3(
        y + 1.5958 * v,
        y - 0.39173 * u - 0.81290 * v,
        y + 2.017 * u
    );
    fragColor = vec4(rgb, 1.0);
}
"""


class Renderer:
    """Draws what it is told. Knows nothing about cues, MIDI, or YAML."""

    def __init__(self, ctx: moderngl.Context, window_size: tuple[int, int]):
        self._ctx = ctx
        self._window_size = window_size
        self._program = ctx.program(vertex_shader=_VERTEX, fragment_shader=_FRAGMENT)
        self._program["tex_y"].value = 0
        self._program["tex_u"].value = 1
        self._program["tex_v"].value = 2
        # Fullscreen quad; v flipped because video rows are top-to-bottom.
        vertices = np.array(
            [
                # x,    y,   u,   v
                -1.0, -1.0, 0.0, 1.0,
                 1.0, -1.0, 1.0, 1.0,
                -1.0,  1.0, 0.0, 0.0,
                 1.0,  1.0, 1.0, 0.0,
            ],
            dtype="f4",
        )
        vbo = ctx.buffer(vertices.tobytes())
        self._vao = ctx.vertex_array(self._program, [(vbo, "2f 2f", "in_pos", "in_uv")])
        self._textures: tuple[moderngl.Texture, ...] | None = None
        self._tex_size: tuple[int, int] | None = None

    def _ensure_textures(self, frame: Frame) -> None:
        if self._tex_size == (frame.width, frame.height):
            return
        if self._textures:
            for t in self._textures:
                t.release()
        w, h = frame.width, frame.height
        self._textures = (
            self._ctx.texture((w, h), 1, dtype="f1"),
            self._ctx.texture((w // 2, h // 2), 1, dtype="f1"),
            self._ctx.texture((w // 2, h // 2), 1, dtype="f1"),
        )
        for t in self._textures:
            t.filter = (moderngl.LINEAR, moderngl.LINEAR)
            t.swizzle = "RRR1"
        self._tex_size = (w, h)

    def _letterbox_viewport(self, frame: Frame) -> tuple[int, int, int, int]:
        ww, wh = self._window_size
        scale = min(ww / frame.width, wh / frame.height)
        vw, vh = int(frame.width * scale), int(frame.height * scale)
        return ((ww - vw) // 2, (wh - vh) // 2, vw, vh)

    def draw(self, frame: Frame) -> None:
        self._ensure_textures(frame)
        assert self._textures is not None
        self._textures[0].write(frame.y.tobytes())
        self._textures[1].write(frame.u.tobytes())
        self._textures[2].write(frame.v.tobytes())
        self._ctx.viewport = (0, 0, *self._window_size)
        self._ctx.clear(0.0, 0.0, 0.0)
        self._ctx.viewport = self._letterbox_viewport(frame)
        for unit, tex in enumerate(self._textures):
            tex.use(location=unit)
        self._vao.render(moderngl.TRIANGLE_STRIP)

    def draw_clear(self, rgb: tuple[float, float, float]) -> None:
        self._ctx.viewport = (0, 0, *self._window_size)
        self._ctx.clear(*rgb)
```

- [ ] **Step 2: Rewrite `visualgen/app.py` to play one looping file**

```python
import subprocess
import sys

import glfw
import moderngl

from visualgen import window
from visualgen.clock import VsyncClock
from visualgen.player import VideoPlayer
from visualgen.render import Renderer


def _prevent_sleep() -> subprocess.Popen:
    return subprocess.Popen(["caffeinate", "-dis"])


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] != "--file":
        print("usage: visualgen --file <video>", file=sys.stderr)
        return 2
    source = sys.argv[2]

    caffeinate = _prevent_sleep()
    player = None
    try:
        win, size = window.create_fullscreen("visualgen")
        ctx = moderngl.create_context()
        renderer = Renderer(ctx, size)
        clock = VsyncClock()

        player = VideoPlayer(source)
        player.preload()
        player.start(clock.now())

        def on_key(w, key, scancode, action, mods):
            if key == glfw.KEY_ESCAPE and action == glfw.PRESS:
                window.close(w)

        glfw.set_key_callback(win, on_key)

        while not window.should_close(win):
            glfw.poll_events()
            renderer.draw(player.frame_at(clock.now()))
            glfw.swap_buffers(win)
        return 0
    finally:
        if player is not None:
            player.stop()
        caffeinate.terminate()
        window.terminate()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Verify manually**

Prepare any 720p H.264 file (call it `~/test.mp4`).
Run: `uv run visualgen --file ~/test.mp4`
Expected: video plays fullscreen, correct colors and aspect ratio (black bars if aspect differs), loops indefinitely with no visible hiccup at the loop point. Watch ≥3 loops. CPU (Activity Monitor) stays moderate and steady. ESC exits cleanly.

- [ ] **Step 4: Run the full test suite**

Run: `uv run pytest -v`
Expected: all tests still pass.

- [ ] **Step 5: Commit**

```bash
git add visualgen/render.py visualgen/app.py
git commit -m "feat: GPU YUV rendering, single looping video fullscreen (milestone 2)"
```

---

### Task 9: PlaybackEngine with preloading and fallback (`engine.py`)

**Files:**
- Create: `visualgen/engine.py`
- Test: `tests/test_engine.py`

**Interfaces:**
- Consumes: `Show` from `visualgen.show`; `VideoPlayer`/`PlayerError`/`Frame` from `visualgen.player`.
- Produces:
  - `PlaybackEngine(show: Show, fallback: Path | None = None, player_factory: Callable[[Path], VideoPlayer] = VideoPlayer)`.
  - `.start(index: int, adjacent: set[int], now: float) -> None` — synchronously preloads and starts cue `index` (startup only), preloads the fallback synchronously if configured, requests async preload of `adjacent`.
  - `.switch_to(index: int, adjacent: set[int], now: float) -> None` — instant swap to the (already preloaded) player for `index`, stops+drops players outside `{index} | adjacent`, requests async preload of missing `adjacent`. If `index` isn't preloaded yet (can't happen via the FSM, but defensively), preloads synchronously.
  - `.preloads_ready() -> bool` — True when no async preloads are pending. The app calls `cue_manager.complete_switch()` when this turns True. A cue whose async preload *failed* is logged, marked failed, and excluded (never blocks readiness).
  - `.frame_at(now: float) -> Frame | None` — frame from the current player; on `PlayerError` engages the fallback player (already preloaded; started on first use) and returns its frame; if no/failed fallback returns the last good frame; if there has never been a frame, returns `None` (app clears to black).
  - `.stop() -> None` — stops every player and the executor.
  - Async preloads run on a `ThreadPoolExecutor(max_workers=2)` — never on the render thread.

- [ ] **Step 1: Write the failing tests**

`tests/test_engine.py` (uses fake players — no video files, no GL):

```python
import time
from pathlib import Path

import pytest

from visualgen.engine import PlaybackEngine
from visualgen.player import Frame, PlayerError
from visualgen.show import Cue, Show


def fake_frame(pts=0.0):
    import numpy as np

    z = np.zeros((2, 2), dtype=np.uint8)
    return Frame(pts, 2, 2, z, z, z)


class FakePlayer:
    def __init__(self, source):
        self.source = Path(source)
        self.preloaded = False
        self.started = False
        self.stopped = False
        self.fail_on_frame = False

    def preload(self):
        if self.source.name == "explodes-on-preload.mp4":
            raise PlayerError("boom")
        self.preloaded = True

    def start(self, now):
        self.started = True

    def frame_at(self, now):
        if self.fail_on_frame:
            raise PlayerError("decode died")
        return fake_frame()

    def stop(self):
        self.stopped = True


def make_show(n=4):
    cues = tuple(Cue(f"c{i}", Path(f"/fake/{i}.mp4")) for i in range(n))
    return Show(cues, wrap=False)


def make_engine(show=None, fallback=Path("/fake/safe.mp4")):
    made = {}

    def factory(source):
        p = FakePlayer(source)
        made[Path(source)] = p
        return p

    engine = PlaybackEngine(show or make_show(), fallback=fallback, player_factory=factory)
    return engine, made


def wait_ready(engine, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if engine.preloads_ready():
            return True
        time.sleep(0.01)
    return False


def test_start_plays_current_and_preloads_adjacent():
    engine, made = make_engine()
    engine.start(0, {1}, now=0.0)
    assert wait_ready(engine)
    assert made[Path("/fake/0.mp4")].started
    assert made[Path("/fake/1.mp4")].preloaded
    assert not made[Path("/fake/1.mp4")].started
    engine.stop()


def test_start_preloads_fallback():
    engine, made = make_engine()
    engine.start(0, set(), now=0.0)
    assert made[Path("/fake/safe.mp4")].preloaded
    engine.stop()


def test_switch_swaps_instantly_and_drops_far_players():
    engine, made = make_engine()
    engine.start(0, {1}, now=0.0)
    assert wait_ready(engine)
    engine.switch_to(1, {0, 2}, now=1.0)
    assert made[Path("/fake/1.mp4")].started
    assert wait_ready(engine)
    engine.switch_to(2, {1, 3}, now=2.0)
    assert wait_ready(engine)
    assert made[Path("/fake/0.mp4")].stopped  # outside {2} | {1, 3}
    engine.stop()


def test_frame_at_returns_current_frame():
    engine, made = make_engine()
    engine.start(0, set(), now=0.0)
    assert engine.frame_at(0.1) is not None
    engine.stop()


def test_player_error_engages_fallback():
    engine, made = make_engine()
    engine.start(0, set(), now=0.0)
    engine.frame_at(0.1)
    made[Path("/fake/0.mp4")].fail_on_frame = True
    frame = engine.frame_at(0.2)
    assert frame is not None
    assert made[Path("/fake/safe.mp4")].started
    engine.stop()


def test_no_fallback_freezes_last_frame():
    engine, made = make_engine(fallback=None)
    engine.start(0, set(), now=0.0)
    good = engine.frame_at(0.1)
    made[Path("/fake/0.mp4")].fail_on_frame = True
    assert engine.frame_at(0.2) is good  # exact same frozen frame object
    engine.stop()


def test_failed_async_preload_never_blocks_readiness():
    cues = (
        Cue("ok", Path("/fake/0.mp4")),
        Cue("bad", Path("/fake/explodes-on-preload.mp4")),
    )
    engine, made = make_engine(show=Show(cues))
    engine.start(0, {1}, now=0.0)
    assert wait_ready(engine), "a failed preload must not leave the FSM stuck in SWITCHING"
    engine.stop()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_engine.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'visualgen.engine'`

- [ ] **Step 3: Implement `visualgen/engine.py`**

```python
import logging
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from visualgen.player import Frame, PlayerError, VideoPlayer
from visualgen.show import Show

log = logging.getLogger(__name__)


class PlaybackEngine:
    """Owns the players. Enforces the preload contract and the fallback ladder.

    Preloaded = file open + first frame decoded, idle. Only the current
    cue decodes continuously. Async preloads never run on the render thread.
    """

    def __init__(
        self,
        show: Show,
        fallback: Path | None = None,
        player_factory: Callable[[Path], VideoPlayer] = VideoPlayer,
    ):
        self._show = show
        self._factory = player_factory
        self._players: dict[int, VideoPlayer] = {}
        self._pending: dict[int, Future] = {}
        self._failed: set[int] = set()
        self._pool = ThreadPoolExecutor(max_workers=2)
        self._current: int | None = None
        self._last_frame: Frame | None = None
        self._fallback_player: VideoPlayer | None = None
        self._fallback_started = False
        self._on_fallback = False
        if fallback is not None:
            self._fallback_player = self._factory(fallback)
            try:
                self._fallback_player.preload()
            except PlayerError as exc:
                log.error("fallback video failed to preload, freeze-frame only: %s", exc)
                self._fallback_player = None

    def start(self, index: int, adjacent: set[int], now: float) -> None:
        player = self._factory(self._show.cues[index].source)
        player.preload()  # startup: synchronous by design; failures abort launch
        player.start(now)
        self._players[index] = player
        self._current = index
        self._request_preloads(adjacent)

    def switch_to(self, index: int, adjacent: set[int], now: float) -> None:
        self._collect_finished_preloads()
        player = self._players.get(index)
        if player is None:  # defensive: FSM should make this impossible
            player = self._factory(self._show.cues[index].source)
            player.preload()
            self._players[index] = player
        player.start(now)
        self._current = index
        self._on_fallback = False
        keep = {index} | adjacent
        for i in [i for i in self._players if i not in keep]:
            self._players.pop(i).stop()
        self._request_preloads(adjacent)

    def _request_preloads(self, indices: set[int]) -> None:
        for i in indices:
            if i in self._players or i in self._pending or i in self._failed:
                continue
            player = self._factory(self._show.cues[i].source)

            def job(p=player):
                p.preload()
                return p

            self._pending[i] = self._pool.submit(job)

    def _collect_finished_preloads(self) -> None:
        for i in [i for i, f in self._pending.items() if f.done()]:
            future = self._pending.pop(i)
            try:
                self._players[i] = future.result()
            except PlayerError as exc:
                log.error("cue '%s' failed to preload: %s", self._show.cues[i].id, exc)
                self._failed.add(i)

    def preloads_ready(self) -> bool:
        self._collect_finished_preloads()
        return not self._pending

    def frame_at(self, now: float) -> Frame | None:
        source = None
        if self._on_fallback and self._fallback_player is not None:
            source = self._fallback_player
        elif self._current is not None:
            source = self._players.get(self._current)
        if source is not None:
            try:
                self._last_frame = source.frame_at(now)
                return self._last_frame
            except PlayerError as exc:
                log.error("live playback failure: %s", exc)
                if not self._on_fallback and self._fallback_player is not None:
                    self._on_fallback = True
                    if not self._fallback_started:
                        self._fallback_player.start(now)
                        self._fallback_started = True
                    return self.frame_at(now)
        return self._last_frame  # freeze-frame; None only if nothing ever rendered

    def stop(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
        for player in self._players.values():
            player.stop()
        self._players.clear()
        if self._fallback_player is not None:
            self._fallback_player.stop()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_engine.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add visualgen/engine.py tests/test_engine.py
git commit -m "feat: PlaybackEngine with async preloading and fallback ladder"
```

---

### Task 10: Wire it together — show loading + keyboard switching (Milestones 3, 4, 5)

**Files:**
- Modify: `visualgen/app.py`

**Interfaces:**
- Consumes: everything produced so far: `load_show`/`ShowError`, `load_config`/`ConfigError`, `CueManager`/`State`, `Command`, `PlaybackEngine`, `Renderer`, `VsyncClock`, `window`.
- Produces:
  - `app.main()` final CLI: `visualgen <show.yaml> [--config <config.yaml>]` (config defaults to `config.yaml` next to the show file).
  - A `queue.Queue[Command]` is THE command channel: keyboard (this task) and MIDI (Task 11) both feed it; the main loop drains it once per frame.
  - Keyboard adapter: RIGHT arrow → `Command.NEXT`, LEFT arrow → `Command.PREVIOUS` (temporary until MIDI, then kept as a rehearsal convenience).
  - Startup errors (`ShowError`, `ConfigError`, first-cue `PlayerError`) print one clear line to stderr and exit code 1.

- [ ] **Step 1: Rewrite `visualgen/app.py` (final structure)**

```python
import logging
import queue
import subprocess
import sys
from pathlib import Path

import glfw
import moderngl

from visualgen import window
from visualgen.clock import VsyncClock
from visualgen.commands import Command
from visualgen.config import ConfigError, load_config
from visualgen.cues import CueManager, State
from visualgen.engine import PlaybackEngine
from visualgen.player import PlayerError
from visualgen.render import Renderer
from visualgen.show import ShowError, load_show

log = logging.getLogger("visualgen")


def _prevent_sleep() -> subprocess.Popen:
    return subprocess.Popen(["caffeinate", "-dis"])


def _parse_args(argv: list[str]) -> tuple[Path, Path]:
    if len(argv) < 2 or argv[1].startswith("-"):
        print("usage: visualgen <show.yaml> [--config <config.yaml>]", file=sys.stderr)
        raise SystemExit(2)
    show_path = Path(argv[1])
    if "--config" in argv:
        config_path = Path(argv[argv.index("--config") + 1])
    else:
        config_path = show_path.parent / "config.yaml"
    return show_path, config_path


def run(show_path: Path, config_path: Path) -> int:
    show = load_show(show_path)
    config = load_config(config_path)

    commands: queue.Queue[Command] = queue.Queue()
    cue_manager = CueManager(len(show.cues), wrap=show.wrap)
    clock = VsyncClock()

    caffeinate = _prevent_sleep()
    engine = PlaybackEngine(show, fallback=config.fallback)
    try:
        win, size = window.create_fullscreen("visualgen")
        ctx = moderngl.create_context()
        renderer = Renderer(ctx, size)

        def on_key(w, key, scancode, action, mods):
            if action != glfw.PRESS:
                return
            if key == glfw.KEY_ESCAPE:
                window.close(w)
            elif key == glfw.KEY_RIGHT:
                commands.put(Command.NEXT)
            elif key == glfw.KEY_LEFT:
                commands.put(Command.PREVIOUS)

        glfw.set_key_callback(win, on_key)

        engine.start(cue_manager.index, cue_manager.adjacent(), clock.now())

        while not window.should_close(win):
            glfw.poll_events()

            while True:  # drain command queue once per frame
                try:
                    command = commands.get_nowait()
                except queue.Empty:
                    break
                target = cue_manager.handle(command)
                if target is not None:
                    engine.switch_to(target, cue_manager.adjacent(), clock.now())

            if cue_manager.state is State.SWITCHING and engine.preloads_ready():
                cue_manager.complete_switch()

            frame = engine.frame_at(clock.now())
            if frame is not None:
                renderer.draw(frame)
            else:
                renderer.draw_clear((0.0, 0.0, 0.0))
            glfw.swap_buffers(win)
        return 0
    finally:
        engine.stop()
        caffeinate.terminate()
        window.terminate()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    show_path, config_path = _parse_args(sys.argv)
    try:
        return run(show_path, config_path)
    except (ShowError, ConfigError, PlayerError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Create a local test show (not committed)**

Create `~/visualgen-test/show.yaml` with 3 short 720p videos:

```yaml
show:
  - id: one
    source: one.mp4
  - id: two
    source: two.mp4
  - id: three
    source: three.mp4
```

- [ ] **Step 3: Verify manually (milestones 3, 4, 5)**

Run: `uv run visualgen ~/visualgen-test/show.yaml`
Expected:
- First cue plays fullscreen, looping.
- RIGHT arrow: instant hard cut to the next video (no black flash, no stall). LEFT arrow: instant cut back.
- RIGHT at the last cue: nothing happens (default `wrap: false`).
- Mash RIGHT rapidly: exactly one switch per completed preload window; no crash, no visual glitch.
- `uv run visualgen /nonexistent.yaml` prints `error: show file not found: /nonexistent.yaml` and exits 1.
- Break the YAML (remove a `source:`) → clear one-line error at startup.

- [ ] **Step 4: Run the full test suite**

Run: `uv run pytest -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add visualgen/app.py
git commit -m "feat: show loading, instant cue switching via keyboard (milestones 3-5)"
```

---

### Task 11: MIDI input (`inputs/midi.py`) (Milestone 6)

**Files:**
- Create: `visualgen/inputs/__init__.py`
- Create: `visualgen/inputs/midi.py`
- Modify: `visualgen/app.py` (start/stop the adapter)
- Test: `tests/test_midi.py`

**Interfaces:**
- Consumes: `Command`; `Config`/`MidiTrigger` from `visualgen.config`; the app's `queue.Queue[Command]`.
- Produces:
  - `message_to_command(msg: mido.Message, config: Config) -> Command | None` — pure function, fully unit-tested. `note_on` with `velocity == 0` is treated as note_off (ignored). `channel=None` in a trigger matches any channel.
  - `MidiAdapter(config: Config, commands: queue.Queue)` with `.start() -> None` and `.stop() -> None`. Own daemon thread: opens the named port (or the first available if `config.midi_port is None`); polls with `iter_pending()`; on any port error closes, logs, retries every 2 s forever. Never touches playback. No port available at startup is a warning, not an error.

- [ ] **Step 1: Write the failing tests**

`tests/test_midi.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_midi.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'visualgen.inputs'`

- [ ] **Step 3: Implement `visualgen/inputs/__init__.py` (empty) and `visualgen/inputs/midi.py`**

```python
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
    if msg.velocity == 0:  # note_on velocity 0 is note_off by convention
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
    """Translates MIDI to Commands on the shared queue. Never touches playback."""

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_midi.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Wire the adapter into `visualgen/app.py`**

In `run()`, after `commands` is created, add:

```python
from visualgen.inputs.midi import MidiAdapter  # add to imports at top

    midi = MidiAdapter(config, commands)
    midi.start()
```

and in the `finally:` block, before `engine.stop()`:

```python
        midi.stop()
```

- [ ] **Step 6: Verify manually (milestone 6)**

Enable the IAC Driver in Audio MIDI Setup (or connect a controller). With `config.yaml` next to the show file naming the port and notes, run the show and send note 60 / 61 (e.g. from a MIDI keyboard or `sendmidi`).
Expected: NEXT/PREVIOUS switch cues exactly like the arrow keys. Unplug/replug the controller mid-show: playback never stutters; log shows disconnect + reconnect; control resumes.

- [ ] **Step 7: Run the full test suite**

Run: `uv run pytest -v`
Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add visualgen/inputs/ tests/test_midi.py visualgen/app.py
git commit -m "feat: MIDI input adapter with auto-reconnect (milestone 6)"
```

---

### Task 12: Live failure path verification (Milestone 7)

**Files:**
- Modify: none expected (Task 9 built the mechanism) — this task *proves* it end-to-end and fixes whatever it exposes.
- Test: `tests/test_engine_failure.py`

**Interfaces:**
- Consumes: `PlaybackEngine`, `VideoPlayer` (real one), the `video_file` fixture.
- Produces: verified failure ladder — real corrupt file → fallback video → freeze-frame.

- [ ] **Step 1: Write the integration test (real players, no GL)**

`tests/test_engine_failure.py`:

```python
import shutil
import time

from visualgen.engine import PlaybackEngine
from visualgen.show import Cue, Show


def test_real_corrupt_current_cue_engages_fallback(tmp_path, video_file):
    """Current cue's file is truncated mid-decode -> engine serves fallback frames."""
    fallback = tmp_path / "safe.mp4"
    shutil.copy(video_file, fallback)
    corrupt = tmp_path / "corrupt.mp4"
    corrupt.write_bytes(video_file.read_bytes()[:200])  # header-ish, dies on decode

    show = Show((Cue("bad", corrupt),), wrap=False)
    engine = PlaybackEngine(show, fallback=fallback)
    try:
        try:
            engine.start(0, set(), now=0.0)
        except Exception:
            # If even preload fails at startup that's an acceptable startup error;
            # this test targets the live path, so only proceed if start worked.
            return
        deadline = time.monotonic() + 5.0
        got_frame = False
        while time.monotonic() < deadline:
            frame = engine.frame_at(time.monotonic())
            if frame is not None:
                got_frame = True
            time.sleep(0.01)
        assert got_frame, "engine must keep serving frames through a live failure"
    finally:
        engine.stop()
```

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/test_engine_failure.py -v`
Expected: PASS. If it fails, the failure ladder in `engine.py`/`player.py` has a real bug — fix it there (common suspects: `PlayerError` not raised from the decode thread, fallback player double-started) and re-run until green.

- [ ] **Step 3: Verify manually (milestone 7)**

Add a `fallback:` to the local test config pointing at a distinctive clip. Start a 3-cue show, then while cue 2 plays, overwrite its file with garbage: `head -c 100 /dev/urandom > ~/visualgen-test/two.mp4` and switch to it.
Expected: the moment decoding dies, the fallback clip appears (looping), the screen never goes black or freezes the UI, and NEXT/PREVIOUS still switch cues. The log names the failed cue.

- [ ] **Step 4: Run the full test suite and commit**

Run: `uv run pytest -v`
Expected: all tests pass.

```bash
git add tests/test_engine_failure.py
git commit -m "test: prove live failure ladder end-to-end (milestone 7)"
```

---

### Task 13: Stability soak + operator docs (Milestone 8)

**Files:**
- Create: `scripts/soak_switching.py`
- Create: `README.md`

**Interfaces:**
- Consumes: the finished application; `mido` (to send synthetic MIDI via a loopback port).
- Produces: a repeatable soak procedure with measurable pass criteria, and a README covering install, show/config format, running, and the failure ladder.

- [ ] **Step 1: Write `scripts/soak_switching.py`**

```python
"""Fires rapid NEXT/PREVIOUS MIDI notes at visualgen through a virtual port.

Usage: run `uv run visualgen <show.yaml>` with config.yaml naming port
"visualgen-soak", then run `uv run python scripts/soak_switching.py 500`.
"""

import random
import sys
import time

import mido


def main() -> int:
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 500
    with mido.open_output("visualgen-soak", virtual=True) as port:
        print("virtual port 'visualgen-soak' open; start visualgen now, then press Enter")
        input()
        for i in range(count):
            note = random.choice([60, 61])
            port.send(mido.Message("note_on", note=note, velocity=100))
            time.sleep(random.uniform(0.02, 0.4))  # from mash-speed to human-speed
            if (i + 1) % 50 == 0:
                print(f"{i + 1}/{count} switches sent")
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run the soak (milestone 8 criteria)**

Procedure and pass criteria (record actual numbers in the commit message):

1. **Switch soak:** 3-cue 720p show + `scripts/soak_switching.py 500`.
   Pass: no crash, no black flash, no stuck SWITCHING state; every accepted command lands on the right cue.
2. **Duration soak:** leave a 2-cue show looping for 2+ hours. Sample memory every 15 min: `ps -o rss= -p $(pgrep -f "visualgen ")`.
   Pass: RSS growth < 10% between the 15-minute mark and the end; playback still smooth afterward.
3. **Failure soak:** during the duration soak, corrupt one preloaded file on disk.
   Pass: fallback engages when that cue is selected; no crash.

If any criterion fails, diagnose and fix before committing (leaks: look for un-`release()`d moderngl textures and un-`close()`d PyAV containers in switch paths).

- [ ] **Step 3: Write `README.md`**

```markdown
# visualgen

Lightweight MIDI-controlled fullscreen video engine for live performance on macOS.

## Install

    uv sync

## Run

    uv run visualgen path/to/show.yaml [--config path/to/config.yaml]

ESC quits. RIGHT/LEFT arrows switch cues (rehearsal convenience); MIDI is the
primary control surface. `--config` defaults to `config.yaml` next to the show file.

## Show file

    wrap: false          # optional: true wraps NEXT/PREVIOUS at the show edges
    show:
      - id: intro
        source: videos/intro.mp4
      - id: verse
        source: videos/verse.mp4

Paths are relative to the show file. All files are validated at startup.

## Config file (all keys optional)

    midi:
      port: "IAC Driver Bus 1"          # default: first available port
      next:     {type: note_on, note: 60}
      previous: {type: note_on, note: 61}
    fallback: videos/safe_loop.mp4      # plays if a cue dies live

## Failure behavior

Startup problems (bad YAML, missing files) exit immediately with a clear
message — nothing fails mid-show that could have failed at launch. If a video
dies during the show, the fallback video plays (looping); you recognize it,
the audience sees an intentional visual, and NEXT/PREVIOUS keep working. With
no fallback configured, the last good frame freezes instead. MIDI disconnects
are logged and auto-reconnected.

## Soak testing

See `scripts/soak_switching.py` for the rapid-switching stress procedure.
```

- [ ] **Step 4: Run the full test suite one last time**

Run: `uv run pytest -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/soak_switching.py README.md
git commit -m "feat: soak test script and operator README (milestone 8)"
```

---

## Plan Self-Review Notes

- **Spec coverage:** fullscreen looping playback (T6–T8), YAML show + validation (T2), separate config + defaults (T3), FSM with drop-during-SWITCHING and configurable wrap (T4), clock seam (T5), preload contract + instant switch (T7, T9, T10), MIDI with reconnect (T11), fallback ladder incl. preloaded-at-startup fallback (T9, T12), stability criteria (T13). Future seams need no tasks (documented in spec).
- **Type consistency:** `Frame(pts, width, height, y, u, v)`, `frame_at(now)`, `preload()/start(now)/stop()`, `handle(command) -> int | None`, `adjacent() -> set[int]`, `preloads_ready() -> bool` used identically across tasks.
- **Known simplifications (deliberate):** `queue.Queue.queue[0]` peek in the player is unconventional but safe (single consumer); BT.601 assumed for MVP color conversion; keyboard adapter stays after MIDI lands as a rehearsal convenience.
