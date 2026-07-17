# Per-clip loop / auto-advance + per-cue transitions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let each cue in the show file choose whether it loops forever (default, current behaviour) or plays once and auto-advances to the next cue, and give each cue its own transition (used when switching away from it), with `loop: false` cues always hard-cutting.

**Architecture:** Read the spec first: `docs/superpowers/specs/2026-07-16-per-clip-loop-design.md`. A `loop` flag on `Cue` flows into `VideoPlayer`, which stops-and-signals at EOF (a `threading.Event`) instead of silently rewinding. The engine builds per-cue transition/duration tables (inheriting the show-global when a cue omits its own, forcing `cut` for `loop: false` cues), and `switch_to` uses the **from-cue's** entry. A four-line block in the app render loop watches for the current cue ending and synthesises a `NEXT`, reusing the entire existing switch path.

**Tech Stack:** Python 3.12, PyAV (`av`), numpy, pytest. Dependencies via `uv` (`uv sync`, `uv run pytest`).

## Global Constraints

- Reliability over cleverness — this runs live performances. No exception may ever escape into the render loop; every failure resolves to a clean single source (fallback ladder: fallback video → freeze on last frame).
- **Backward compatibility:** `loop` defaults to `true` and per-cue `transition`/`duration` default to inherit the show-global. Every existing show file and every existing test must behave identically. The full suite is **103 tests, all green** — keep it green at every commit.
- Module boundaries: inputs emit Commands only; CueManager has no rendering/MIDI/file-I/O; Renderer only draws textures. This feature must not modify `render.py` or `cues.py`. It does modify `app.py` (one new call + one small extracted function) and touches `commands.py` not at all.
- `loop: false` cues **always** hard-cut — on natural end (auto-advance) and on manual NEXT. Enforced once, in the engine's per-cue table build.
- Transitions belong to the cue you leave (the "from" cue).
- All tests run with `uv run pytest`. Run all commands from the repo root: `/Users/osvaldo/projects/visual_generator`.

---

### Task 1: Per-cue `loop` / `transition` / `duration` in the show file

`Cue` gains three optional fields. `transition`/`duration` store the raw per-cue override where `None` means "inherit the show-global" (the engine resolves inheritance in Task 3). `load_show` parses the new per-cue keys, and warns when a `loop: false` cue also names a transition (it will be ignored).

**Files:**
- Modify: `visualgen/show.py` (`Cue` dataclass, lines 13-16; `load_show` per-entry loop, lines 50-60)
- Test: `tests/test_show.py`

**Interfaces:**
- Consumes: existing `_parse_transition` / `_parse_duration` (`show.py:64-79`), `TransitionMode` (`instruction.py`).
- Produces: `Cue(id, source, loop: bool = True, transition: TransitionMode | None = None, duration: float | None = None)`. Tasks 3-5 rely on these field names and on `None` meaning "inherit".

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_show.py`:

```python
def test_cue_loop_defaults_true_and_overrides(tmp_path):
    make_video(tmp_path, "a.mp4")
    make_video(tmp_path, "b.mp4")
    p = write_show(
        tmp_path,
        "show:\n"
        "  - {id: a, source: a.mp4}\n"
        "  - {id: b, source: b.mp4, loop: false}\n",
    )
    cues = load_show(p).cues
    assert cues[0].loop is True   # default preserves current behaviour
    assert cues[1].loop is False


def test_cue_transition_and_duration_default_none(tmp_path):
    make_video(tmp_path, "a.mp4")
    p = write_show(tmp_path, "show:\n  - {id: a, source: a.mp4}\n")
    cue = load_show(p).cues[0]
    assert cue.transition is None   # None = inherit the show-global
    assert cue.duration is None


def test_cue_per_transition_and_duration_parsed(tmp_path):
    make_video(tmp_path, "a.mp4")
    p = write_show(
        tmp_path,
        "transition: crossfade\n"
        "show:\n"
        "  - {id: a, source: a.mp4, transition: wipe, duration: 0.4}\n",
    )
    cue = load_show(p).cues[0]
    assert cue.transition is TransitionMode.WIPE
    assert cue.duration == 0.4


def test_cue_bad_per_transition_raises(tmp_path):
    make_video(tmp_path, "a.mp4")
    p = write_show(tmp_path, "show:\n  - {id: a, source: a.mp4, transition: sparkle}\n")
    with pytest.raises(ShowError):
        load_show(p)


def test_loop_false_with_transition_warns(tmp_path, caplog):
    make_video(tmp_path, "a.mp4")
    p = write_show(
        tmp_path,
        "show:\n  - {id: a, source: a.mp4, loop: false, transition: crossfade}\n",
    )
    with caplog.at_level("WARNING"):
        cue = load_show(p).cues[0]
    assert cue.loop is False
    assert any("loop: false" in r.message and "a" in r.message for r in caplog.records)
```

(`tests/test_show.py` already imports `pytest`; the `caplog` fixture and its `at_level("WARNING")` string need no extra import.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_show.py -k "cue_loop or per_transition or default_none or bad_per_transition or loop_false_with_transition" -v`
Expected: FAIL — `Cue.__init__` got unexpected keyword argument `loop` (and friends).

- [ ] **Step 3: Add the fields to `Cue`**

In `visualgen/show.py`, replace the `Cue` dataclass (lines 13-16):

```python
@dataclass(frozen=True)
class Cue:
    id: str
    source: Path
    loop: bool = True
    transition: TransitionMode | None = None   # None = inherit the show-global
    duration: float | None = None              # None = inherit the show-global
```

- [ ] **Step 4: Parse the per-cue keys in `load_show`**

In `visualgen/show.py`, replace the per-entry loop body (lines 50-60, the `for i, entry ...` block) with:

```python
    log = logging.getLogger(__name__)
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
        loop = bool(entry.get("loop", True))
        cue_transition = (
            _parse_transition(path, entry["transition"]) if "transition" in entry else None
        )
        cue_duration = _parse_duration(path, entry["duration"]) if "duration" in entry else None
        if not loop and cue_transition is not None:
            log.warning(
                "%s: cue '%s' is loop: false, so its transition '%s' is ignored (always a hard cut)",
                path, cue_id, cue_transition.value,
            )
        cues.append(Cue(cue_id, source, loop, cue_transition, cue_duration))
```

Add `import logging` to the top of `visualgen/show.py` (after the existing imports).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_show.py -v`
Expected: PASS — all new tests plus the existing show tests stay green.

- [ ] **Step 6: Commit**

```bash
git add visualgen/show.py tests/test_show.py
git commit -m "feat: per-cue loop/transition/duration fields in show file"
```

---

### Task 2: `VideoPlayer` learns not to loop and to signal EOF

The player gains a `loop` flag (default `True`, preserving every current caller) and a thread-safe `ended` signal. A `loop=False` player, at end-of-file, sets `ended` and stops on its final frame instead of rewinding. `start()` clears `ended` so a restart re-arms it (needed for the dead-end re-loop in Task 4).

**Files:**
- Modify: `visualgen/player.py` (`__init__`, lines 34-50; `start`, lines 91-125 region; `_decode_loop`, lines 151-169)
- Test: `tests/test_player.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `VideoPlayer(source, buffer_size=3, loop=True)` and a read-only `ended: bool` property. Tasks 3-4 rely on `loop` as a keyword arg and on `ended`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_player.py`:

```python
def test_loop_false_signals_ended_and_holds_last_frame(video_file):
    p = VideoPlayer(video_file, loop=False)
    p.preload()
    start = time.monotonic()
    p.start(now=start)
    try:
        assert p.ended is False
        deadline = time.monotonic() + 3.0
        while time.monotonic() - start < 3.0:
            p.frame_at(time.monotonic())
            if p.ended:
                break
            time.sleep(0.01)
        assert p.ended, "loop=False player must signal ended at EOF"
        # Holds the final frame instead of wrapping to frame 0.
        held = p.frame_at(time.monotonic())
        again = p.frame_at(time.monotonic() + 0.5)
        assert again.pts == held.pts
        assert held.pts > 0.0, "should hold a late frame, not the first frame"
    finally:
        p.stop()


def test_start_clears_ended_flag(video_file):
    p = VideoPlayer(video_file, loop=False)
    p.preload()
    start = time.monotonic()
    p.start(now=start)
    try:
        while time.monotonic() - start < 3.0 and not p.ended:
            p.frame_at(time.monotonic())
            time.sleep(0.01)
        assert p.ended
        p.start(now=time.monotonic())   # restart re-arms
        assert p.ended is False
    finally:
        p.stop()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_player.py -k "loop_false_signals or clears_ended" -v`
Expected: FAIL — `VideoPlayer.__init__` got unexpected keyword argument `loop` (and no `ended`).

- [ ] **Step 3: Add the `loop` flag and `ended` event to `__init__`**

In `visualgen/player.py`, change the constructor signature and add the event. Replace line 35:

```python
    def __init__(self, source: str | Path, buffer_size: int = 3, loop: bool = True):
```

Immediately after `self._source = str(source)` (line 36), add:

```python
        self._loop = loop
        self._ended = threading.Event()
```

Add the property (place it just above `preload`, after `__init__`):

```python
    @property
    def ended(self) -> bool:
        """True once a loop=False clip has reached EOF and is holding its final frame."""
        return self._ended.is_set()
```

- [ ] **Step 4: Branch the decode loop on `loop`**

In `visualgen/player.py`, replace the EOF handler in `_decode_loop` (lines 157-160):

```python
                except (StopIteration, av.error.EOFError):
                    self._container.seek(0)
                    decoder = self._container.decode(self._stream)
                    continue
```

with:

```python
                except (StopIteration, av.error.EOFError):
                    if self._loop:
                        self._container.seek(0)
                        decoder = self._container.decode(self._stream)
                        continue
                    self._ended.set()   # loop=False: announce end, stop advancing
                    break               # thread exits; frame_at() holds the final frame
```

- [ ] **Step 5: Clear `ended` on (re)start**

In `visualgen/player.py`, `start()`, insert the clear immediately after the `self._halt()` call (line 104) and before `self._drain()`:

```python
        self._halt()
        self._ended.clear()   # re-arm: a restarted loop=False player can end again
        self._drain()
```

(Placed after the `first_frame is None` guard so a pre-preload failure leaves state untouched, and before the decode thread is (re)started so it can never race the clear.)

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_player.py -v`
Expected: PASS — the two new tests plus `test_loops_past_end_of_file` (default `loop=True`, unchanged) stay green.

- [ ] **Step 7: Commit**

```bash
git add visualgen/player.py tests/test_player.py
git commit -m "feat: VideoPlayer loop flag + ended signal (hold last frame at EOF)"
```

---

### Task 3: Per-cue transition tables in the engine

Replace the engine's single `self._mode` / `self._duration` with per-cue tables that inherit the show-global for cues that omit an override and force `cut` for `loop: false` cues. `switch_to` uses the **from-cue's** entry. The live keys and `mode`/`duration` properties retarget to the current cue. Players are created with their cue's `loop` flag.

**Files:**
- Modify: `visualgen/engine.py` (`__init__` 36-37; `mode`/`duration` props 58-64; `cycle_mode`/`adjust_duration` 66-73; `start` 78; `switch_to` 88-132; `_tail_possible` 134-149; `_should_blend` 151-160; `_request_preloads` 166)
- Test: `tests/test_engine.py` (update the shared `FakePlayer`/`factory`; revise three existing tests; add new ones)

**Interfaces:**
- Consumes: `Cue.loop` / `Cue.transition` / `Cue.duration` (Task 1); `VideoPlayer(..., loop=...)` (Task 2).
- Produces: `self._modes: list[TransitionMode]`, `self._durations: list[float]`; `mode`/`duration` properties current-cue-relative; `cycle_mode`/`adjust_duration` mutate the current cue's entry. Task 4 relies on the same table structures.

- [ ] **Step 1: Update the shared test harness (`FakePlayer` + factory)**

In `tests/test_engine.py`, update `FakePlayer.__init__` to accept `loop` and expose `ended`. Replace line 20 (`def __init__(self, source):`) and add two attributes:

```python
    def __init__(self, source, loop=True):
        self.source = Path(source)
        self.loop = loop
        self.ended = False
```

(Keep the rest of `__init__` unchanged below those lines.)

Update the factory inside `make_engine` (lines 70-73) to accept the `loop` kwarg:

```python
    def factory(source, loop=True):
        p = FakePlayer(source, loop=loop)
        made[Path(source)] = p
        return p
```

- [ ] **Step 2: Write/revise the failing tests**

**Replace** `test_engine_seeds_mode_and_duration_from_show` (lines 156-161) with a version that still reads the seeded global before any cue is current (property fallback), and one that reflects a current cue:

```python
def test_mode_and_duration_fall_back_to_show_global_before_start():
    show = Show(make_show().cues, transition=TransitionMode.CROSSFADE, duration=1.2)
    engine, made = make_engine(show=show)
    assert engine.mode is TransitionMode.CROSSFADE   # no current cue yet -> show-global
    assert engine.duration == 1.2
    engine.stop()
```

**Replace** `test_cycle_mode_advances_and_wraps` (lines 164-177) with a version that starts the engine first (cycling now targets the current cue):

```python
def test_cycle_mode_advances_current_cue_and_wraps():
    engine, made = make_engine()  # cues inherit show-global CUT
    engine.start(0, {1}, now=0.0)
    assert engine.mode is TransitionMode.CUT
    engine.cycle_mode()
    assert engine.mode is TransitionMode.DIP
    engine.cycle_mode()
    assert engine.mode is TransitionMode.CROSSFADE
    engine.cycle_mode()
    assert engine.mode is TransitionMode.WIPE
    engine.cycle_mode()
    assert engine.mode is TransitionMode.TAIL_DISSOLVE
    engine.cycle_mode()
    assert engine.mode is TransitionMode.CUT
    engine.stop()
```

**Replace** `test_adjust_duration_steps_and_floors_at_min` (lines 196-203) with a started-engine version:

```python
def test_adjust_duration_steps_and_floors_at_min():
    show = Show(make_show().cues, duration=0.5)
    engine, made = make_engine(show=show)
    engine.start(0, {1}, now=0.0)
    engine.adjust_duration(0.1)
    assert engine.duration == pytest.approx(0.6)
    engine.adjust_duration(-1.0)
    assert engine.duration == pytest.approx(0.1)  # floored, never <= 0
    engine.stop()
```

**Append** the new per-cue behaviour tests:

```python
def test_switch_uses_from_cue_transition():
    # Leaving cue 0 (crossfade) then leaving cue 1 (wipe) uses each cue's own mode.
    cues = (
        Cue("a", Path("/fake/0.mp4"), transition=TransitionMode.CROSSFADE, duration=1.0),
        Cue("b", Path("/fake/1.mp4"), transition=TransitionMode.WIPE, duration=1.0),
        Cue("c", Path("/fake/2.mp4")),
    )
    engine, made = make_engine(show=Show(cues, wrap=False))
    engine.start(0, {1}, now=0.0)
    assert wait_ready(engine)
    engine.switch_to(1, {0, 2}, now=1.0)
    assert isinstance(engine.instruction_at(1.5), Blend)
    assert engine.instruction_at(1.5).mode is TransitionMode.CROSSFADE  # left cue 0
    engine.instruction_at(3.0)  # finalize the first window
    assert wait_ready(engine)
    engine.switch_to(2, {1}, now=3.0)
    assert engine.instruction_at(3.5).mode is TransitionMode.WIPE       # left cue 1


def test_loop_false_from_cue_always_cuts():
    # Cue 0 is loop:false with a crossfade set -> must still hard-cut when left.
    cues = (
        Cue("a", Path("/fake/0.mp4"), loop=False, transition=TransitionMode.CROSSFADE, duration=1.0),
        Cue("b", Path("/fake/1.mp4")),
    )
    engine, made = make_engine(show=Show(cues, wrap=False))
    engine.start(0, {1}, now=0.0)
    assert wait_ready(engine)
    engine.switch_to(1, {0}, now=1.0)
    assert engine.transition_complete(), "loop:false cue must cut, not blend"
    assert isinstance(engine.instruction_at(1.0), Single)
    assert made[Path("/fake/0.mp4")].pause_count == 1  # paused instantly, like a cut


def test_loop_false_player_created_with_loop_flag():
    cues = (Cue("a", Path("/fake/0.mp4"), loop=False), Cue("b", Path("/fake/1.mp4")))
    engine, made = make_engine(show=Show(cues, wrap=False))
    engine.start(0, {1}, now=0.0)
    assert wait_ready(engine)
    assert made[Path("/fake/0.mp4")].loop is False
    assert made[Path("/fake/1.mp4")].loop is True
    engine.stop()


def test_live_keys_noop_on_loop_false_current_cue():
    cues = (Cue("a", Path("/fake/0.mp4"), loop=False), Cue("b", Path("/fake/1.mp4")))
    engine, made = make_engine(show=Show(cues, wrap=False))
    engine.start(0, {1}, now=0.0)
    assert engine.mode is TransitionMode.CUT
    engine.cycle_mode()               # loop:false current cue -> no-op
    assert engine.mode is TransitionMode.CUT
    engine.stop()


def test_live_keys_isolated_per_cue():
    engine, made = make_engine()  # 4 cues, all inherit CUT
    engine.start(0, {1}, now=0.0)
    engine.cycle_mode()               # cue 0 -> DIP
    assert engine.mode is TransitionMode.DIP
    assert wait_ready(engine)
    engine.switch_to(1, {0, 2}, now=1.0)   # current cue is now 1
    assert engine.mode is TransitionMode.CUT   # cue 1 untouched by cue 0's tweak
    engine.stop()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_engine.py -k "from_cue or loop_false or live_keys or fall_back_to_show_global or cycle_mode_advances_current or adjust_duration" -v`
Expected: FAIL — no `self._modes`; `cycle_mode` still mutates a global; players not created with `loop`.

- [ ] **Step 4: Build the per-cue tables in `__init__`**

In `visualgen/engine.py`, replace lines 36-37:

```python
        self._mode = show.transition  # session state, seeded from YAML; live keys mutate it
        self._duration = show.duration
```

with:

```python
        # Per-cue transition/duration, resolved from the show-global for cues that omit
        # their own, and forced to a hard cut for loop:false cues (which always cut).
        self._modes = [
            TransitionMode.CUT if not c.loop else (c.transition or show.transition)
            for c in show.cues
        ]
        self._durations = [
            c.duration if c.duration is not None else show.duration for c in show.cues
        ]
```

- [ ] **Step 5: Make the `mode`/`duration` properties current-cue-relative**

In `visualgen/engine.py`, replace the `mode` and `duration` properties (lines 58-64):

```python
    @property
    def mode(self) -> TransitionMode:
        if self._current is None:
            return self._show.transition
        return self._modes[self._current]

    @property
    def duration(self) -> float:
        if self._current is None:
            return self._show.duration
        return self._durations[self._current]
```

- [ ] **Step 6: Retarget `cycle_mode` / `adjust_duration` to the current cue**

In `visualgen/engine.py`, replace `cycle_mode` and `adjust_duration` (lines 66-73):

```python
    def cycle_mode(self) -> None:
        """Advance the current cue's transition: cut -> dip -> crossfade -> wipe ->
        tail_dissolve -> cut. Session-only. No-op with no current cue, or on a
        loop:false cue (which always cuts)."""
        if self._current is None or not self._show.cues[self._current].loop:
            return
        modes = list(TransitionMode)
        current = self._modes[self._current]
        self._modes[self._current] = modes[(modes.index(current) + 1) % len(modes)]

    def adjust_duration(self, delta: float) -> None:
        """Nudge the current cue's transition duration, floored at _MIN_DURATION.
        Session-only. No-op with no current cue, or on a loop:false cue."""
        if self._current is None or not self._show.cues[self._current].loop:
            return
        self._durations[self._current] = round(
            max(self._MIN_DURATION, self._durations[self._current] + delta), 3
        )
```

- [ ] **Step 7: Use the from-cue's entry in `switch_to` and thread `loop` into player creation**

In `visualgen/engine.py`, `switch_to`:

(a) After `player = self._players.get(index)` (line 95), insert the effective from-cue lookup:

```python
        mode = self._modes[prev] if prev is not None else TransitionMode.CUT
        duration = self._durations[prev] if prev is not None else 0.0
```

(b) Replace the player creation on switch (line 98):

```python
                player = self._factory(
                    self._show.cues[index].source, loop=self._show.cues[index].loop
                )
```

(c) Replace the tail-possible check and its `_Transition` (lines 106-113) so they use the local `mode`/`duration`:

```python
        if self._tail_possible(from_player, player, was_on_fallback, mode, duration):
            # Tail dissolve: nothing starts and nothing pauses here. A keeps decoding
            # toward its own last-frame still; B's start is deferred to the cut
            # (_finalize_transition). Exactly one decoder runs throughout.
            self._transition = _Transition(
                prev, index, now, duration, TransitionMode.CROSSFADE,
                tail_frame=from_player.last_frame, resume=resume,
            )
```

(d) Replace the base-blend check and its `_Transition` (lines 122-124):

```python
            if self._should_blend(from_player, player, mode, duration):
                # Keep both players decoding for the window; the outgoing one is paused at finalize.
                self._transition = _Transition(prev, index, now, duration, mode)
```

- [ ] **Step 8: Thread `loop` into the other two player-creation sites**

In `visualgen/engine.py`, `start` (line 78), replace:

```python
            player = self._factory(self._show.cues[index].source)
```

with:

```python
            player = self._factory(
                self._show.cues[index].source, loop=self._show.cues[index].loop
            )
```

In `_request_preloads` (line 166), replace:

```python
            player = self._factory(self._show.cues[i].source)
```

with:

```python
            player = self._factory(self._show.cues[i].source, loop=self._show.cues[i].loop)
```

- [ ] **Step 9: Add `mode`/`duration` params to the two helpers**

In `visualgen/engine.py`, replace `_tail_possible` (lines 134-149):

```python
    def _tail_possible(
        self,
        from_player: VideoPlayer | None,
        to_player: VideoPlayer | None,
        was_on_fallback: bool,
        mode: TransitionMode,
        duration: float,
    ) -> bool:
        """All preconditions for a tail dissolve; anything short of this is a plain cut."""
        return (
            mode is TransitionMode.TAIL_DISSOLVE
            and duration > 0
            and to_player is not None
            and from_player is not None
            and from_player.last_frame is not None
            and not was_on_fallback  # outgoing already dead -> nothing healthy to dissolve from
            and not self._on_fallback  # destination just failed to load -> fallback owns the screen
        )
```

Replace `_should_blend` (lines 151-160):

```python
    def _should_blend(
        self,
        from_player: VideoPlayer | None,
        to_player: VideoPlayer | None,
        mode: TransitionMode,
        duration: float,
    ) -> bool:
        return (
            # TAIL_DISSOLVE has its own switch path; here it must degrade to a cut,
            # never to a two-live-player base blend.
            mode not in (TransitionMode.CUT, TransitionMode.TAIL_DISSOLVE)
            and duration > 0
            and from_player is not None
            and to_player is not None
            and not self._on_fallback  # target fell back -> nothing healthy to blend into
        )
```

- [ ] **Step 10: Run the full engine suite**

Run: `uv run pytest tests/test_engine.py -v`
Expected: PASS — new per-cue tests, the three revised tests, and all existing blend/tail tests (their cues inherit the show-global, so behaviour is unchanged).

- [ ] **Step 11: Run the whole suite to catch cross-file breakage**

Run: `uv run pytest`
Expected: PASS — 103 existing (some revised) + new tests, all green.

- [ ] **Step 12: Commit**

```bash
git add visualgen/engine.py tests/test_engine.py
git commit -m "feat: per-cue transition tables; switch uses from-cue mode; live keys retarget"
```

---

### Task 4: `current_cue_ended()` and `hold_end_of_show()`

Two small engine methods that the app loop will call. `current_cue_ended()` reports whether the current (non-fallback, non-transitioning) cue's player has hit EOF. `hold_end_of_show()` handles the dead end — fallback looping if configured, otherwise re-loop the cue — and is idempotent per end.

**Files:**
- Modify: `visualgen/engine.py` (add two methods, e.g. after `transition_complete`, line 306)
- Test: `tests/test_engine.py`

**Interfaces:**
- Consumes: `player.ended` (Task 2 / `FakePlayer.ended` from Task 3), `_engage_fallback` (`engine.py:190`).
- Produces: `current_cue_ended() -> bool`, `hold_end_of_show(now: float) -> None`. Task 5 calls both.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_engine.py`:

```python
def test_current_cue_ended_reflects_player_flag():
    engine, made = make_engine()
    engine.start(0, {1}, now=0.0)
    assert engine.current_cue_ended() is False
    made[Path("/fake/0.mp4")].ended = True
    assert engine.current_cue_ended() is True


def test_current_cue_ended_false_during_transition_and_fallback():
    show = Show(make_show().cues, transition=TransitionMode.CROSSFADE, duration=1.0)
    engine, made = make_engine(show=show)
    engine.start(0, {1}, now=0.0)
    assert wait_ready(engine)
    made[Path("/fake/0.mp4")].ended = True
    engine.switch_to(1, {0, 2}, now=1.0)          # transition in flight
    assert engine.current_cue_ended() is False     # suppressed mid-transition


def test_hold_end_of_show_engages_fallback():
    engine, made = make_engine()  # fallback = /fake/safe.mp4
    engine.start(0, set(), now=0.0)
    engine.hold_end_of_show(now=1.0)
    assert engine.current_cue_ended() is False     # now on fallback -> idempotent
    assert made[Path("/fake/safe.mp4")].started
    # Fallback loops forever (default loop flag).
    assert made[Path("/fake/safe.mp4")].loop is True


def test_hold_end_of_show_reloops_cue_without_fallback():
    engine, made = make_engine(fallback=None)
    engine.start(0, set(), now=0.0)
    assert wait_ready(engine)
    made[Path("/fake/0.mp4")].ended = True
    engine.hold_end_of_show(now=1.0)               # no fallback -> restart the cue
    p = made[Path("/fake/0.mp4")]
    assert p.started
    assert engine.current_cue_ended() is False     # restart cleared ended (FakePlayer.start)
```

Note: `FakePlayer.start` must clear `ended` so the last assertion holds. Add that in Step 3.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_engine.py -k "current_cue_ended or hold_end_of_show" -v`
Expected: FAIL — `PlaybackEngine` has no attribute `current_cue_ended`.

- [ ] **Step 3: Make `FakePlayer.start` clear `ended`**

In `tests/test_engine.py`, `FakePlayer.start` (lines 39-46), add a line so a restart re-arms exactly like the real player:

```python
    def start(self, now, resume=False):
        if self.fail_on_start:
            raise PlayerError("seek failed")
        if self.running:
            self.double_started = True
        self.running = True
        self.started = True
        self.resumed = resume
        self.ended = False
```

- [ ] **Step 4: Add the two engine methods**

In `visualgen/engine.py`, after `transition_complete` (line 306), add:

```python
    def current_cue_ended(self) -> bool:
        """True when the current cue's player has hit EOF and is holding its last frame --
        the signal to auto-advance. False during a transition or while on the fallback, so
        the auto-advance never double-fires."""
        if self._on_fallback or self._transition is not None or self._current is None:
            return False
        player = self._players.get(self._current)
        return player is not None and player.ended

    def hold_end_of_show(self, now: float) -> None:
        """Dead end: a loop:false cue ended with nowhere to advance (last cue, wrap off).
        Engage the fallback looping if configured; otherwise re-loop the cue itself so the
        screen keeps moving. Idempotent: once on the fallback, current_cue_ended() is False,
        and the re-loop path clears the ended flag via start()."""
        if self._engage_fallback(now):
            return
        if self._current is None:
            return
        player = self._players.get(self._current)
        if player is None:
            return
        try:
            player.start(now)  # clears the ended flag and replays from the top
        except PlayerError as exc:
            log.error(
                "cue '%s' failed to re-loop at end of show: %s",
                self._show.cues[self._current].id, exc,
            )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_engine.py -k "current_cue_ended or hold_end_of_show" -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add visualgen/engine.py tests/test_engine.py
git commit -m "feat: engine current_cue_ended() + hold_end_of_show() (dead-end handling)"
```

---

### Task 5: Auto-advance in the render loop

Extract the auto-advance decision into a small testable function in `app.py` and call it once per frame, beside the existing `complete_switch()` check. Reusing `cue_manager.handle(Command.NEXT)` means auto-advance inherits wrapping, `previous` tracking (so recall works), and the `SWITCHING` re-entrancy guard, with no CueManager change.

**Files:**
- Modify: `visualgen/app.py` (add `_auto_advance`; call it in `run`'s loop after lines 106-111)
- Modify: `examples/show.yaml` (document the new per-cue keys)
- Test: `tests/test_engine.py` (drive `_auto_advance` against real engine + CueManager + FakePlayer — no GLFW needed)

**Interfaces:**
- Consumes: `engine.current_cue_ended()` / `engine.hold_end_of_show()` (Task 4); `CueManager.handle` / `.state` / `.adjacent` (`cues.py`); `Command.NEXT` (`commands.py`); `State.PLAYING` (`cues.py`).
- Produces: `_auto_advance(engine, cue_manager, now) -> None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_engine.py` (imports needed: add `from visualgen.app import _auto_advance`, `from visualgen.cues import CueManager, State`, `from visualgen.commands import Command` at the top of the file).

Note: this is the first test module to import `visualgen.app`, which imports `glfw` and `moderngl` at module load (no window is created at import time, so the import is safe headless). If collection errors on those imports in your environment, run `uv sync` first; do not move `_auto_advance` out of `app.py`.

```python
def test_auto_advance_switches_on_ended_loop_false_cue():
    cues = (
        Cue("a", Path("/fake/0.mp4"), loop=False),
        Cue("b", Path("/fake/1.mp4")),
    )
    show = Show(cues, wrap=False)
    engine, made = make_engine(show=show)
    cm = CueManager(len(cues), wrap=False)
    engine.start(0, {1}, now=0.0)
    assert wait_ready(engine)
    made[Path("/fake/0.mp4")].ended = True
    _auto_advance(engine, cm, now=1.0)
    assert cm.index == 1                       # advanced to the next cue
    assert cm.state is State.SWITCHING         # went through the normal switch path
    assert engine.transition_complete()        # loop:false -> hard cut, no blend window


def test_auto_advance_ignored_while_switching():
    engine, made = make_engine()
    cm = CueManager(4, wrap=False)
    engine.start(0, {1}, now=0.0)
    cm.handle(Command.NEXT)                     # cm now SWITCHING
    made[Path("/fake/0.mp4")].ended = True
    _auto_advance(engine, cm, now=1.0)         # must not fire a second switch
    assert cm.index == 1                        # unchanged from the manual NEXT


def test_auto_advance_wraps_on_last_cue_when_wrap_true():
    cues = (
        Cue("a", Path("/fake/0.mp4")),
        Cue("b", Path("/fake/1.mp4"), loop=False),
    )
    show = Show(cues, wrap=True)
    engine, made = make_engine(show=show)
    cm = CueManager(len(cues), wrap=True)
    cm.handle(Command.NEXT)                     # move the CueManager to the last cue...
    cm.complete_switch()                        # ...and land there (index 1)
    engine.start(1, {0}, now=0.0)              # engine starts on the last cue too
    assert wait_ready(engine)
    made[Path("/fake/1.mp4")].ended = True
    _auto_advance(engine, cm, now=1.0)
    assert cm.index == 0                        # wrapped to the first cue


def test_auto_advance_dead_end_holds_on_fallback():
    cues = (Cue("a", Path("/fake/0.mp4"), loop=False),)
    show = Show(cues, wrap=False)
    engine, made = make_engine(show=show)      # fallback = /fake/safe.mp4
    cm = CueManager(len(cues), wrap=False)
    engine.start(0, set(), now=0.0)
    made[Path("/fake/0.mp4")].ended = True
    _auto_advance(engine, cm, now=1.0)         # last cue, wrap off -> dead end
    assert cm.index == 0                        # no advance
    assert made[Path("/fake/safe.mp4")].started # fallback engaged
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_engine.py -k auto_advance -v`
Expected: FAIL — cannot import `_auto_advance` from `visualgen.app`.

- [ ] **Step 3: Add `_auto_advance` to `app.py`**

In `visualgen/app.py`, add a module-level function (e.g. just above `def run`):

```python
def _auto_advance(engine, cue_manager, now) -> None:
    """When the current loop:false cue has played out, advance to the next cue
    (a hard cut, since loop:false cues always cut). At a dead end -- the last cue
    with wrap off -- hold on the fallback, or re-loop the cue if none is configured.
    Reuses handle(NEXT), so wrapping, previous-tracking and the SWITCHING guard all
    apply exactly as for a manual NEXT."""
    if cue_manager.state is not State.PLAYING or not engine.current_cue_ended():
        return
    target = cue_manager.handle(Command.NEXT)
    if target is not None:
        engine.switch_to(target, cue_manager.adjacent(), now)
    else:
        engine.hold_end_of_show(now)
```

- [ ] **Step 4: Call it in the render loop**

In `visualgen/app.py`, `run`, immediately after the `complete_switch()` block (lines 106-111) and before `instruction = engine.instruction_at(...)` (line 113), add:

```python
            _auto_advance(engine, cue_manager, clock.now())
```

- [ ] **Step 5: Run the auto-advance tests**

Run: `uv run pytest tests/test_engine.py -k auto_advance -v`
Expected: PASS.

- [ ] **Step 6: Document the new keys in `examples/show.yaml`**

In `examples/show.yaml`, update the transitions comment block and the cue list to show the per-cue keys. Replace the comment block (lines 8-15) and cue entries with:

```yaml
# Per-cue options (all optional):
#   loop:       true (default) -> the clip rewinds forever until you advance.
#               false          -> the clip plays once, then HARD-CUTS to the next cue on its own.
#   transition: cut | dip | crossfade | wipe | tail_dissolve   (default: the show-global below)
#               -- used when you switch AWAY from this cue. Ignored for loop:false cues (always cut).
#   duration:   seconds the blend lasts   (default: the show-global below; ignored for cut)
# The show-global transition/duration below are the defaults for cues that omit their own.
# Live keys while running (session-only, edit the CURRENT on-screen cue; not written back):
#   t     cycle its transition:  cut -> dip -> crossfade -> wipe -> tail_dissolve -> cut
#   ]  [  lengthen / shorten its duration by 0.1s (floored at 0.1s)
transition: crossfade
duration: 0.8

show:
  - id: horse
    source: clips/horse.mp4
  - id: montecarlo
    source: clips/montecarlo.mp4
    transition: wipe        # leaving montecarlo uses a wipe
  - id: sting
    source: clips/onirofobia.mp4
    loop: false             # plays once, then hard-cuts to trinch
  - id: trinch
    source: clips/reel.mp4
```

(Adjust filenames to match whatever clips are present; keep the existing `wrap: true` line at the bottom.)

- [ ] **Step 7: Run the whole suite**

Run: `uv run pytest`
Expected: PASS — all tests green.

- [ ] **Step 8: Commit**

```bash
git add visualgen/app.py tests/test_engine.py examples/show.yaml
git commit -m "feat: auto-advance loop:false cues at end of clip; document per-cue keys"
```

---

## Manual verification (after all tasks)

Automated tests cover the logic; a live pass confirms the real decode path (the EOF signal and the visible cut) since the engine tests use `FakePlayer`. With a short real clip:

1. Set a cue to `loop: false` in `examples/show.yaml`. Run `uv run visualgen examples/show.yaml`.
2. Watch it play once and hard-cut to the next cue on its own — no freeze, no stutter at the seam.
3. Make the **last** cue `loop: false` with `wrap: false` and a fallback configured → confirm it holds on the looping fallback at the end. Remove the fallback → confirm it re-loops the last cue instead of freezing.
4. On a `loop: true` cue, press `t` a few times, then NEXT → confirm the tweaked transition plays and that a *different* cue is unaffected.

Record the outcome in the plan's Progress section and update CLAUDE.md / auto-memory, following the `tail_dissolve` precedent (operator-approved after a manual pass).

## Progress

- Not started. Spec: `docs/superpowers/specs/2026-07-16-per-clip-loop-design.md` (approved 2026-07-16).
