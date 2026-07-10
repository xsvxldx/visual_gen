# Cue Recall (undo-last-switch) Implementation Plan

> **STATUS: DONE & merged to `main` (2026-07-10).** All 5 tasks implemented via subagent-driven TDD, then hardened with four review-driven fixes to the resume timing path (hold-during-catch-up, pause-records-on-screen-frame + loop-wrap release, seek-failure→fallback, `_epoch` re-anchor at reveal). 69 tests green; operator-confirmed on hardware. The task checkboxes below are left unchecked as the historical plan of record.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a keyboard `DOWN` "recall" control that returns to the cue the operator was just on, resumed at the exact frame it was showing when they left it, toggling A/B on repeated presses.

**Architecture:** Follows the existing flow — Input (`app.py`) → `Command` → `CueManager` (pure position FSM) → `PlaybackEngine` → `VideoPlayer`. `CueManager` gains a one-slot `_previous` index and a `RECALL` branch that swaps `_previous`↔`_index` (the toggle). The "where I left it" position lives with the `VideoPlayer` that owns the stream: `pause()` records the frame it was left on, `start(resume=True)` seeks back to it. The engine just threads a `resume` flag through; the decode loop is unchanged.

**Tech Stack:** Python 3.12, `uv`, `pytest`, PyAV (`av`), moderngl/glfw, mido.

**Spec:** `docs/superpowers/specs/2026-07-09-cue-recall-design.md` (approved).

## Global Constraints

- Python `>=3.12`, dependencies managed with `uv` (`uv sync`, `uv run pytest -q`).
- No new dependencies. Package name `visualgen`, flat package at repo root. Tests in `tests/`.
- macOS only. OpenGL 3.3 core profile.
- Respect module boundaries: inputs emit `Command`s only; `CueManager` is a pure position FSM with **no** rendering/MIDI/playback-time knowledge; only the player learns to resume; `Renderer` only draws.
- Reliability over cleverness — this runs live performances. A failed resume seek must route through the existing fallback ladder, adding no new failure surface.
- One commit per task; every commit message ends with the trailer:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- The operator is **not an expert Python dev** — after each task give a short, plain-language explanation of what was built and why.

---

### Task 1: Add `RECALL` to the `Command` enum

**Files:**
- Modify: `visualgen/commands.py`
- Test: `tests/test_commands.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Command.RECALL` (a third member of the existing `Command(Enum)`), used by `CueManager.handle` (Task 2) and `app.py` (Task 5).

- [ ] **Step 1: Update the failing test**

Replace the body of `tests/test_commands.py` so it requires the new member:

```python
from visualgen.commands import Command


def test_commands_exist():
    assert Command.NEXT is not Command.PREVIOUS
    assert {c.name for c in Command} == {"NEXT", "PREVIOUS", "RECALL"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_commands.py -q`
Expected: FAIL — the set comparison fails because `RECALL` does not exist yet (`{'NEXT', 'PREVIOUS'} != {'NEXT', 'PREVIOUS', 'RECALL'}`).

- [ ] **Step 3: Add the enum member**

Edit `visualgen/commands.py` to:

```python
from enum import Enum, auto


class Command(Enum):
    NEXT = auto()
    PREVIOUS = auto()
    RECALL = auto()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_commands.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add visualgen/commands.py tests/test_commands.py
git commit -m "feat: add RECALL command

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `CueManager` recall + A/B toggle

**Files:**
- Modify: `visualgen/cues.py`
- Test: `tests/test_cues.py`

**Interfaces:**
- Consumes: `Command.RECALL` (Task 1).
- Produces: `CueManager.handle(Command.RECALL) -> int | None`. Returns the index to switch to (the previously-left cue) and enters `State.SWITCHING`; returns `None` if there is no history (`_previous is None`) or a switch is already in progress (`state is SWITCHING`). Repeated `RECALL` toggles between the A/B pair. `NEXT`/`PREVIOUS` behaviour is otherwise unchanged. `app.py` (Task 5) relies on this signature; `adjacent()` and `complete_switch()` are unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cues.py`:

```python
def test_recall_with_no_history_returns_none():
    cm = CueManager(3)
    assert cm.handle(Command.RECALL) is None
    assert cm.index == 0
    assert cm.state is State.PLAYING


def test_recall_returns_the_previously_left_cue():
    cm = CueManager(3)
    cm.handle(Command.NEXT)  # 0 -> 1
    cm.complete_switch()
    assert cm.handle(Command.RECALL) == 0
    assert cm.index == 0
    assert cm.state is State.SWITCHING


def test_recall_toggles_between_the_ab_pair():
    cm = CueManager(3)
    cm.handle(Command.NEXT)  # 0 -> 1
    cm.complete_switch()
    assert cm.handle(Command.RECALL) == 0  # back to 0
    cm.complete_switch()
    assert cm.handle(Command.RECALL) == 1  # toggle back to 1
    cm.complete_switch()
    assert cm.handle(Command.RECALL) == 0  # and back again


def test_recall_ignored_while_switching():
    cm = CueManager(3)
    cm.handle(Command.NEXT)  # enters SWITCHING
    assert cm.handle(Command.RECALL) is None
    assert cm.index == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cues.py -q`
Expected: FAIL — `test_recall_with_no_history_returns_none` fails because `RECALL` currently falls into the `delta = -1` branch and moves the index (or returns a wrong value); the others fail because there is no `_previous` tracking or toggle.

- [ ] **Step 3: Implement `_previous` and the `RECALL` branch**

In `visualgen/cues.py`, add the field in `__init__` (right after `self._index = 0`):

```python
        self._index = 0
        self._previous: int | None = None
        self._state = State.PLAYING
```

Then replace the `handle` method with:

```python
    def handle(self, command: Command) -> int | None:
        if self._state is State.SWITCHING:
            return None
        if command is Command.RECALL:
            if self._previous is None:
                return None
            target = self._previous
            self._previous, self._index = self._index, self._previous
            self._state = State.SWITCHING
            return target
        delta = 1 if command is Command.NEXT else -1
        target = self._index + delta
        if self._wrap:
            target %= self._count
        elif not 0 <= target < self._count:
            return None
        if target == self._index:
            return None
        self._previous = self._index
        self._index = target
        self._state = State.SWITCHING
        return target
```

Note: the `RECALL` branch is checked **before** the `delta` computation so `RECALL` never gets mistaken for a `PREVIOUS`-style move; `NEXT`/`PREVIOUS` now record `_previous` on every successful move.

- [ ] **Step 4: Run the full cue suite to verify pass (and no regressions)**

Run: `uv run pytest tests/test_cues.py -q`
Expected: PASS — the four new tests plus all existing `test_cues` tests are green.

- [ ] **Step 5: Commit**

```bash
git add visualgen/cues.py tests/test_cues.py
git commit -m "feat: CueManager recall with A/B toggle

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `VideoPlayer` resume support

**Files:**
- Modify: `visualgen/player.py`
- Test: `tests/test_player.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `VideoPlayer.pause()` now records `self._resume_pts: float` (the pts of the frame it was left on, `0.0` if nothing was shown) and `self._hold: Frame | None` (that exact frame) before halting.
  - `VideoPlayer.start(now: float, resume: bool = False)` — `resume=False` is the existing top-of-clip behaviour; `resume=True` seeks to the keyframe at/before `_resume_pts`, sets `_epoch = now - _resume_pts`, and keeps `_hold` for display during catch-up.
  - `frame_at(now)` shows `_hold` while the decoder catches up. `PlaybackEngine` (Task 4) calls `start(now, resume=...)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_player.py`:

```python
def test_start_resume_replays_from_left_position(video_file):
    p = VideoPlayer(video_file)
    p.preload()
    p.start(now=0.0)
    try:
        # advance past the first frame so there is a non-zero position to resume from
        deadline = time.monotonic() + 2.0
        left = None
        while time.monotonic() < deadline:
            f = p.frame_at(0.2)
            if f.pts > 0.0:
                left = f
                break
            time.sleep(0.01)
        assert left is not None and left.pts > 0.0, "precondition: playback advanced"

        p.pause()
        assert p._resume_pts == left.pts, "pause() records the frame it was left on"
        assert p._hold is left, "pause() holds the exact frame for display during catch-up"

        p.start(now=100.0, resume=True)
        # the held frame is shown immediately at the resume position (not from the top),
        # even before the decoder produces the resume frame
        shown = p.frame_at(100.0)
        assert shown.pts == left.pts
    finally:
        p.stop()
```

Keep the existing `test_start_after_pause_replays_from_top` — it now doubles as the `resume=False` (default) regression: after `pause()`, `start(now=100.0)` still yields `pts == 0.0`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_player.py::test_start_resume_replays_from_left_position -q`
Expected: FAIL — `AttributeError` on `p._resume_pts` / `p._hold`, or `TypeError` because `start()` does not accept `resume`.

- [ ] **Step 3: Implement resume fields, `pause()` recording, and the `start(resume=...)` branch**

In `visualgen/player.py`, add two fields in `__init__` (right after `self._current: Frame | None = None`):

```python
        self._current: Frame | None = None
        self._resume_pts: float = 0.0
        self._hold: Frame | None = None
        self.first_frame: Frame | None = None
```

Replace `start` with the resume-aware version (keeps all existing restart-safe halt/drain logic; only the seek target, epoch, and `_hold` handling branch on `resume`):

```python
    def start(self, now: float, resume: bool = False) -> None:
        """Begin (or restart) continuous decoding.

        resume=False (default): replay from the top of the clip.
        resume=True: seek back to the frame the operator left on (recorded by
        pause()) and resume there, holding that frame on screen until the
        decoder catches up.

        Restart-safe: any running decode thread is halted first, so a cue that is
        revisited never ends up with two threads racing on the same container.
        """
        if self.first_frame is None:
            raise PlayerError(f"{self._source}: start() before preload()")
        self._halt()
        self._drain()
        if self._container is not None:
            if resume:
                self._container.seek(int(self._resume_pts * 1_000_000))
            else:
                self._container.seek(0)  # replay from the start
        self._current = None
        if not resume:
            self._hold = None
        self._error = None
        self._epoch = now - self._resume_pts if resume else now
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._decode_loop, daemon=True)
        self._thread.start()
```

Replace `pause` so it records the resume point before halting:

```python
    def pause(self) -> None:
        """Stop decoding but keep the container open so start() can resume instantly.

        Records where we were (the current frame and its pts) so a later
        start(resume=True) can pick up from exactly here.
        """
        self._resume_pts = self._current.pts if self._current is not None else 0.0
        self._hold = self._current
        self._halt()
```

Replace the `result` line in `frame_at` so the held frame is shown until the decoder produces the resume frame:

```python
        result = self._current or self._hold or self.first_frame
        assert result is not None, "frame_at() before preload()"
        return result
```

No changes to `_decode_loop`: after the resume seek it decodes forward from the keyframe, and `frame_at`'s existing catch-up loop (consume while `_epoch + pts <= now`) naturally skips from the keyframe to the resume point.

- [ ] **Step 4: Run the player suite to verify pass (and no regressions)**

Run: `uv run pytest tests/test_player.py -q`
Expected: PASS — the new resume test plus all existing player tests (including `test_start_after_pause_replays_from_top`, now exercising the `resume=False` default) are green.

- [ ] **Step 5: Commit**

```bash
git add visualgen/player.py tests/test_player.py
git commit -m "feat: VideoPlayer resume from left-on frame

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: `PlaybackEngine` threads the `resume` flag through

**Files:**
- Modify: `visualgen/engine.py`
- Test: `tests/test_engine.py`

**Interfaces:**
- Consumes: `VideoPlayer.start(now, resume=...)` (Task 3).
- Produces: `PlaybackEngine.switch_to(index: int, adjacent: set[int], now: float, resume: bool = False)` — passes `resume` through to the target player's `start`. All other behaviour (pause outgoing cue, drop far players, request preloads, fallback ladder, no-double-start) is unchanged. `app.py` (Task 5) relies on this signature.

- [ ] **Step 1: Update `FakePlayer` and write the failing test**

In `tests/test_engine.py`, update `FakePlayer` so its `start` accepts and records the `resume` flag (the engine will now call `start(now, resume=...)`, and without this every existing engine test would break with a `TypeError`). Change the `__init__` line and the `start` method:

```python
        self.pause_count = 0
        self.resumed = False  # last value of the resume flag passed to start()
```

```python
    def start(self, now, resume=False):
        if self.running:
            self.double_started = True
        self.running = True
        self.started = True
        self.resumed = resume
```

Then append a new test proving the flag reaches the target player:

```python
def test_switch_to_resume_passes_resume_flag_to_target():
    engine, made = make_engine(show=Show(make_show(3).cues, wrap=True))
    engine.start(0, {1, 2}, now=0.0)
    assert wait_ready(engine)
    engine.switch_to(1, {0, 2}, now=1.0)  # normal switch: from the top
    assert made[Path("/fake/1.mp4")].resumed is False
    assert wait_ready(engine)
    engine.switch_to(0, {1, 2}, now=2.0, resume=True)  # recall: resume cue 0
    assert made[Path("/fake/0.mp4")].resumed is True
    engine.stop()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_engine.py::test_switch_to_resume_passes_resume_flag_to_target -q`
Expected: FAIL — `switch_to()` does not accept `resume` (`TypeError: switch_to() got an unexpected keyword argument 'resume'`).

- [ ] **Step 3: Add the `resume` parameter and thread it to `start`**

In `visualgen/engine.py`, change the `switch_to` signature and the single `start` call. The signature line:

```python
    def switch_to(self, index: int, adjacent: set[int], now: float, resume: bool = False) -> None:
```

and the player-start line near the end of the method:

```python
        if player is not None:
            player.start(now, resume=resume)
```

Leave everything else in `switch_to` unchanged.

- [ ] **Step 4: Run the engine suite to verify pass (and no regressions)**

Run: `uv run pytest tests/test_engine.py -q`
Expected: PASS — the new test plus all existing engine tests are green (they all now go through the updated `FakePlayer.start`).

- [ ] **Step 5: Commit**

```bash
git add visualgen/engine.py tests/test_engine.py
git commit -m "feat: PlaybackEngine passes resume flag through switch_to

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Wire `DOWN` key to recall in the app

**Files:**
- Modify: `visualgen/app.py`

**Interfaces:**
- Consumes: `Command.RECALL` (Task 1), `CueManager.handle` recall (Task 2), `PlaybackEngine.switch_to(..., resume=...)` (Task 4).
- Produces: end-user behaviour — pressing `DOWN` recalls the previously-left cue, resumed at position, toggling A/B.

Note: `app.py` is the GL/glfw wiring layer and has no unit test in this project (consistent with how the window/key wiring was handled in the MVP). The logic it depends on is fully covered by the `cues`/`engine`/`player` suites; this task is verified by running the app.

- [ ] **Step 1: Map the `DOWN` key to `Command.RECALL`**

In `visualgen/app.py`, add a branch to the `on_key` callback, right after the `KEY_LEFT` branch:

```python
            elif key == glfw.KEY_LEFT:
                commands.put(Command.PREVIOUS)
            elif key == glfw.KEY_DOWN:
                commands.put(Command.RECALL)
```

- [ ] **Step 2: Pass the `resume` flag when draining a `RECALL`**

In `visualgen/app.py`, in the command-drain loop, replace:

```python
                target = cue_manager.handle(command)
                if target is not None:
                    engine.switch_to(target, cue_manager.adjacent(), clock.now())
```

with:

```python
                target = cue_manager.handle(command)
                if target is not None:
                    resume = command is Command.RECALL
                    engine.switch_to(target, cue_manager.adjacent(), clock.now(), resume=resume)
```

- [ ] **Step 3: Run the full test suite to confirm nothing regressed**

Run: `uv run pytest -q`
Expected: PASS — all tests green (was 57 before this plan; this plan adds 6 new tests → expect 63).

- [ ] **Step 4: Manual smoke test (operator, on real hardware)**

Run: `uv run visualgen examples/show.yaml`
Verify, using your clips:
1. `RIGHT` advances a cue from the top (unchanged, zero latency).
2. Let the new cue play a few seconds, then press `DOWN`: it returns to the previous cue **resumed where you left it** (the held frame appears instantly, motion resumes within a few tens of ms — no black, no jump to frame 0).
3. Press `DOWN` again: it toggles back to the other cue, also at its last-left position.
4. Press `DOWN` at startup (before any switch): nothing happens (no history).

- [ ] **Step 5: Commit**

```bash
git add visualgen/app.py
git commit -m "feat: DOWN key recalls the previously-left cue

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage** (against `2026-07-09-cue-recall-design.md`):
- §Components 1 (`commands.py` `RECALL`) → Task 1. ✓
- §Components 2 (`cues.py` `_previous`, RECALL branch, swap-toggle, SWITCHING/None guards) → Task 2. ✓
- §Components 3 (`player.py` `_resume_pts`/`_hold`, `pause()` recording, `start(resume=...)` seek + epoch, `frame_at` held-frame, no decode-loop change) → Task 3. ✓
- §Components 4 (`engine.py` `switch_to(..., resume=...)` passthrough) → Task 4. ✓
- §Components 5 (`app.py` `DOWN`→RECALL, `resume = command is Command.RECALL`) → Task 5. ✓
- §Testing bullets: `test_commands` RECALL (Task 1); `test_cues` no-history/returns-previous/toggle/ignored-while-switching (Task 2); `test_player` resume yields ~`_resume_pts` + held frame, and `resume=False` still pts 0 (Task 3, plus retained `test_start_after_pause_replays_from_top`); `test_engine` resume flag via FakePlayer (Task 4). ✓
- §Error handling: resume seek failure → existing `PlayerError` → fallback ladder in `PlaybackEngine.frame_at` (no new failure surface — no code needed beyond raising `PlayerError`, already the case); `start()` restart-safe (unchanged halt-first). ✓ Covered by design; no extra task required.
- §Non-goals (no MIDI recall, only immediate A/B pair, no transitions) → nothing implemented for these. ✓

**2. Placeholder scan:** No TBD/TODO/"add error handling"/"similar to Task N". Every code step shows complete code. ✓

**3. Type consistency:** `Command.RECALL` used identically in Tasks 1/2/5. `_previous: int | None`, `_resume_pts: float`, `_hold: Frame | None` consistent across Tasks 2/3. `start(now, resume=False)` signature identical in player (Task 3), FakePlayer (Task 4), engine call (Task 4); `switch_to(index, adjacent, now, resume=False)` identical in engine (Task 4) and app (Task 5). ✓
