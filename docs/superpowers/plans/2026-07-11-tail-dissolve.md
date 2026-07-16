# tail_dissolve Transition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the `tail_dissolve` transition: on switch, the outgoing cue keeps playing while crossfading into a still of its own final frame, then hard-cuts to the incoming cue — one video decoder at any instant.

**Architecture:** Extends the merged transitions framework (spec: `docs/superpowers/specs/2026-07-11-tail-dissolve-design.md` — read it before starting). A 5th `TransitionMode` value routes `switch_to` down a new tail branch that defers the incoming player's `start()` to the finalize (the hard cut). `VideoPlayer` gains an eagerly-captured `last_frame` still. The renderer is untouched: tail blends carry `mode=CROSSFADE`.

**Tech Stack:** Python 3.12, PyAV (`av`), numpy, pytest. Dependencies via `uv` (`uv sync`, `uv run pytest`).

## Global Constraints

- Reliability over cleverness — this runs live performances. No exception may ever escape into the render loop; every failure resolves to a clean single source (fallback ladder: fallback video → freeze on last frame).
- Exactly **one video decoder runs at any instant** during a tail dissolve (A during the window, B after the cut).
- Module boundaries: inputs emit Commands only; CueManager has no rendering/MIDI; Renderer only draws textures. **This feature must not modify `render.py`, `cues.py`, `app.py`, or `commands.py`.**
- All tests run with: `uv run pytest` (full suite currently 91 tests, all green — keep it that way at every commit).
- Run all commands from the repo root: `/Users/osvaldo/projects/visual_generator`.

---

### Task 1: `TransitionMode.TAIL_DISSOLVE` — selectable, safe before the tail exists

The enum value must land first so YAML parsing and the live `t` key pick it up automatically (`cycle_mode` iterates `list(TransitionMode)`; `_parse_transition` accepts any enum value). Critically, this task also excludes the new mode from the base-blend path: without that, `_should_blend` (which only excludes `CUT`) would approve a two-live-player blend carrying the unknown mode, and the renderer's `_MODE_INT.get(mode, 2)` would silently draw it as a crossfade — violating the one-decoder rule. Until Task 3 lands, selecting `tail_dissolve` must behave exactly like a cut.

**Files:**
- Modify: `visualgen/instruction.py` (the `TransitionMode` enum, lines 7-13)
- Modify: `visualgen/engine.py` (`_should_blend`, lines 122-129; `cycle_mode` docstring, line 65)
- Test: `tests/test_show.py`, `tests/test_engine.py`

**Interfaces:**
- Consumes: existing `TransitionMode` enum, `_should_blend`.
- Produces: `TransitionMode.TAIL_DISSOLVE` (value `"tail_dissolve"`, declared **after** `WIPE` so the `t`-cycle order is `cut → dip → crossfade → wipe → tail_dissolve → cut`). Tasks 3-4 rely on `_should_blend` returning `False` for this mode.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_show.py`:

```python
def test_tail_dissolve_transition_parsed(tmp_path):
    make_video(tmp_path, "a.mp4")
    p = write_show(tmp_path, "transition: tail_dissolve\nshow:\n  - {id: a, source: a.mp4}\n")
    assert load_show(p).transition is TransitionMode.TAIL_DISSOLVE
```

In `tests/test_engine.py`, **replace** the existing `test_cycle_mode_advances_and_wraps` (lines 163-174) with:

```python
def test_cycle_mode_advances_and_wraps():
    engine, made = make_engine()  # default show -> CUT
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

Append to `tests/test_engine.py`:

```python
def test_tail_dissolve_mode_switches_as_a_cut_when_no_tail_is_possible():
    # TAIL_DISSOLVE must NEVER fall through to the two-live-player base-blend path:
    # the renderer silently draws unknown modes as a crossfade, which would break
    # the one-decoder rule. Anything short of a possible tail is a plain cut.
    show = Show(make_show().cues, transition=TransitionMode.TAIL_DISSOLVE, duration=1.0)
    engine, made = make_engine(show=show)
    engine.start(0, {1}, now=0.0)
    assert wait_ready(engine)
    engine.switch_to(1, {0, 2}, now=1.0)
    assert engine.transition_complete(), "no blend window may be recorded"
    assert isinstance(engine.instruction_at(1.0), Single)
    assert made[Path("/fake/0.mp4")].pause_count == 1  # outgoing paused instantly, like a cut
    engine.stop()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_show.py::test_tail_dissolve_transition_parsed tests/test_engine.py::test_cycle_mode_advances_and_wraps tests/test_engine.py::test_tail_dissolve_mode_switches_as_a_cut_when_no_tail_is_possible -v`

Expected: all three FAIL — the first two with `AttributeError: TAIL_DISSOLVE` (enum value missing), the third likewise at the `Show(...)` construction line.

- [ ] **Step 3: Implement**

In `visualgen/instruction.py`, replace the enum (lines 7-13) with:

```python
class TransitionMode(Enum):
    """The selectable transition set. CUT never produces a Blend; TAIL_DISSOLVE
    produces a crossfade Blend into a still, then a cut (see engine)."""

    CUT = "cut"
    DIP = "dip"
    CROSSFADE = "crossfade"
    WIPE = "wipe"
    TAIL_DISSOLVE = "tail_dissolve"
```

In `visualgen/engine.py`, update `cycle_mode`'s docstring (line 65) to:

```python
        """Advance the mode: cut -> dip -> crossfade -> wipe -> tail_dissolve -> cut. Session-only."""
```

In `visualgen/engine.py`, replace `_should_blend` (lines 122-129) with:

```python
    def _should_blend(self, from_player: VideoPlayer | None, to_player: VideoPlayer | None) -> bool:
        return (
            # TAIL_DISSOLVE has its own switch path; here it must degrade to a cut,
            # never to a two-live-player base blend.
            self._mode not in (TransitionMode.CUT, TransitionMode.TAIL_DISSOLVE)
            and self._duration > 0
            and from_player is not None
            and to_player is not None
            and not self._on_fallback  # target fell back -> nothing healthy to blend into
        )
```

- [ ] **Step 4: Run the full suite to verify everything passes**

Run: `uv run pytest`
Expected: all tests PASS (91 existing + 3 new/updated).

- [ ] **Step 5: Commit**

```bash
git add visualgen/instruction.py visualgen/engine.py tests/test_show.py tests/test_engine.py
git commit -m "feat: tail_dissolve mode is selectable; behaves as a cut until the tail lands"
```

---

### Task 2: `VideoPlayer.last_frame` — eager, isolated, exception-safe capture

At `preload()`, decode the clip's **final** frame into `last_frame` using a second, short-lived container (never the playback container). Any failure — no stream duration, bad seek, nothing decodable, any exception — yields `last_frame = None` and must never fail an otherwise playable preload. Note `preload()` sometimes runs on the main loop (initial start, lazy loads), so the capture must stay bounded: one seek + decoding forward from the last keyframe only; never scan a whole file.

**Files:**
- Modify: `visualgen/player.py` (`__init__` line 49 area, `preload()` lines 51-63, new `_capture_last_frame` method)
- Test: `tests/test_player.py` (uses the existing `video_file` fixture from `tests/conftest.py`: a real 15-frame, 30 fps, 64x48 H.264 clip where frame *i* is flat gray level *i*×16)

**Interfaces:**
- Consumes: existing `_convert(frame, time_base) -> Frame` helper, `av.open`.
- Produces: `VideoPlayer.last_frame: Frame | None` attribute — `None` until `preload()`, then the clip's final frame or `None` on any capture failure. Task 3's engine code reads exactly this attribute.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_player.py`:

```python
def test_preload_captures_the_clips_final_frame(video_file):
    p = VideoPlayer(video_file)
    p.preload()
    try:
        f = p.last_frame
        assert isinstance(f, Frame)
        assert (f.width, f.height) == (64, 48)
        # 15 frames at 30 fps -> the final frame sits at pts 14/30
        assert f.pts == pytest.approx(14 / 30, abs=1e-3)
        # frame i is flat gray level i*16: the final frame is far brighter than the
        # first (exact Y values depend on the codec's range conversion, so compare)
        assert f.y.mean() > p.first_frame.y.mean() + 100
    finally:
        p.stop()


def test_last_frame_capture_failure_never_fails_preload(video_file, monkeypatch):
    # The end-capture opens a second, isolated container. If that open explodes,
    # preload() must still succeed with last_frame None -- a broken capture must
    # never turn a playable clip into a failed cue.
    import visualgen.player as player_module

    real_open = player_module.av.open
    calls = {"n": 0}

    def flaky_open(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] >= 2:  # the playback container opens first; the capture second
            raise RuntimeError("capture container exploded")
        return real_open(*args, **kwargs)

    monkeypatch.setattr(player_module.av, "open", flaky_open)
    p = VideoPlayer(video_file)
    p.preload()  # must not raise
    try:
        assert p.first_frame is not None
        assert p.last_frame is None
    finally:
        p.stop()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_player.py::test_preload_captures_the_clips_final_frame tests/test_player.py::test_last_frame_capture_failure_never_fails_preload -v`

Expected: FAIL — the first with `AttributeError: 'VideoPlayer' object has no attribute 'last_frame'`; the second at the `p.last_frame is None` assert (same `AttributeError`).

- [ ] **Step 3: Implement**

In `visualgen/player.py` `__init__`, directly after `self.first_frame: Frame | None = None` (line 49), add:

```python
        self.last_frame: Frame | None = None
```

In `preload()`, directly after `self._frames.put(self.first_frame)` (line 63), add:

```python
        self.last_frame = self._capture_last_frame()
```

Add this method to `VideoPlayer` (after `preload`, before `start`):

```python
    def _capture_last_frame(self) -> Frame | None:
        """The clip's final frame, decoded in an isolated short-lived container.

        Never raises: any failure (no duration, bad seek, nothing decodable)
        yields None and the tail dissolve is treated as unavailable. Uses its
        own container so the playback container's decode state is untouched,
        and never scans a whole file -- one seek, then forward through the
        last keyframe group only.
        """
        try:
            with av.open(self._source) as container:
                stream = container.streams.video[0]
                if stream.duration is None:
                    return None
                container.seek(stream.duration, stream=stream)
                last = None
                for frame in container.decode(stream):
                    last = frame
                if last is None:
                    return None
                return _convert(last, stream.time_base)
        except Exception:
            return None
```

- [ ] **Step 4: Run the full suite to verify everything passes**

Run: `uv run pytest`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add visualgen/player.py tests/test_player.py
git commit -m "feat: VideoPlayer captures the clip's final frame eagerly at preload"
```

---

### Task 3: Engine tail path — dissolve live A into its still, then cut to B

The core orchestration. `_Transition` gains `tail_frame` (set ⇒ this is a tail dissolve) and `resume` (carries the cue-recall flag to the deferred start of B — without it, recalling a cue under tail_dissolve would silently restart it from the top, regressing the merged cue-recall feature). `switch_to` gets a tail branch that starts nothing and pauses nothing; `_blend_at` gets a tail path that never queries B; `_finalize_transition` gains a `now` argument and performs the hard cut (`to_player.start(now, resume=t.resume)`, then pause A).

**Files:**
- Modify: `visualgen/engine.py` (`_Transition` lines 14-22, `switch_to` lines 86-120, `_blend_at` lines 200-232, `_finalize_transition` lines 234-242)
- Test: `tests/test_engine.py` (`FakePlayer` gains a `last_frame` attribute; one Task 1 test gets a one-line forcing tweak)

**Interfaces:**
- Consumes: `VideoPlayer.last_frame` (Task 2), `TransitionMode.TAIL_DISSOLVE` and the `_should_blend` exclusion (Task 1), existing `start(now, resume=False)` / `pause()` / `frame_at(now)` player API.
- Produces: `_Transition(from_index: int, to_index: int, start: float, duration: float, mode: TransitionMode, tail_frame: Frame | None = None, resume: bool = False)`; `_tail_possible(from_player, to_player, was_on_fallback) -> bool`; `_finalize_transition(now: float) -> None`. Task 4 hardens exactly these.

- [ ] **Step 1: Write the failing tests**

In `tests/test_engine.py`, add to `FakePlayer.__init__` after the `own_frame` line (line 31):

```python
        self.last_frame = fake_frame()  # distinct still, so tail blends can be attributed to it
```

Update Task 1's `test_tail_dissolve_mode_switches_as_a_cut_when_no_tail_is_possible`: now that `FakePlayer` has a `last_frame` by default, the test must force the not-possible branch. Insert this line immediately after `assert wait_ready(engine)`:

```python
    made[Path("/fake/0.mp4")].last_frame = None  # force the not-possible branch
```

Append the tail tests:

```python
def _tail_engine(duration=1.0):
    show = Show(make_show().cues, transition=TransitionMode.TAIL_DISSOLVE, duration=duration)
    engine, made = make_engine(show=show)
    engine.start(0, {1}, now=0.0)
    assert wait_ready(engine)
    return engine, made


def test_tail_blends_live_outgoing_into_its_own_last_frame_still():
    engine, made = _tail_engine(duration=1.0)
    engine.switch_to(1, {0, 2}, now=1.0)
    instr = engine.instruction_at(1.5)  # halfway through the 1.0s window
    assert isinstance(instr, Blend)
    assert instr.mode is TransitionMode.CROSSFADE  # renders as an ordinary crossfade
    assert instr.from_frame is made[Path("/fake/0.mp4")].own_frame  # live A
    assert instr.to_frame is made[Path("/fake/0.mp4")].last_frame  # A's still -- NOT B
    assert instr.t == pytest.approx(0.5)
    engine.stop()


def test_tail_never_starts_incoming_during_the_window():
    engine, made = _tail_engine(duration=1.0)
    engine.switch_to(1, {0, 2}, now=1.0)
    engine.instruction_at(1.5)
    assert not made[Path("/fake/1.mp4")].started, "one decoder: B must not run during the dissolve"
    assert made[Path("/fake/0.mp4")].running, "A keeps decoding during the dissolve"
    assert made[Path("/fake/0.mp4")].pause_count == 0
    engine.stop()


def test_tail_finalize_cuts_to_incoming_and_pauses_outgoing():
    engine, made = _tail_engine(duration=1.0)
    engine.switch_to(1, {0, 2}, now=1.0)
    engine.instruction_at(1.5)
    assert not engine.transition_complete()
    instr = engine.instruction_at(2.0)  # t reaches 1 -> the hard cut
    assert isinstance(instr, Single), "past the window: a clean single source"
    assert instr.frame is made[Path("/fake/1.mp4")].own_frame
    assert made[Path("/fake/1.mp4")].started, "the cut starts B"
    assert made[Path("/fake/1.mp4")].resumed is False, "normal switch: B starts fresh from the top"
    assert made[Path("/fake/0.mp4")].pause_count == 1, "the cut pauses A"
    assert engine.transition_complete()
    engine.stop()


def test_tail_recall_starts_incoming_at_its_left_on_position():
    # Cue recall (DOWN) switches with resume=True. A tail switch defers B's start
    # to the cut, so the flag must ride the transition -- otherwise recall would
    # silently restart the recalled cue from the top.
    engine, made = _tail_engine(duration=1.0)
    engine.switch_to(1, {0, 2}, now=1.0)
    engine.instruction_at(2.5)  # finish the first dissolve (cut to cue 1)
    engine.switch_to(0, {1}, now=3.0, resume=True)  # recall the just-left cue
    p0 = made[Path("/fake/0.mp4")]
    engine.instruction_at(3.5)  # mid-dissolve: cue 0 must not be restarted yet
    assert p0.resumed is False
    engine.instruction_at(4.0)  # the cut
    assert p0.resumed is True, "recall must resume at the left-on position"
    assert engine.transition_complete()
    engine.stop()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_engine.py -v -k tail`

Expected: the four new tail tests FAIL (the switch takes the cut path, so `instruction_at(1.5)` returns `Single`, not `Blend`, and `transition_complete()` is already `True`). `test_tail_dissolve_mode_switches_as_a_cut_when_no_tail_is_possible` still PASSES.

- [ ] **Step 3: Implement**

In `visualgen/engine.py`, replace the `_Transition` dataclass (lines 14-22) with:

```python
@dataclass
class _Transition:
    """An in-flight blend from one cue to another, driven by the wall clock."""

    from_index: int
    to_index: int
    start: float
    duration: float
    mode: TransitionMode
    tail_frame: Frame | None = None  # set -> tail dissolve: live A fades into this still, then cuts
    resume: bool = False  # start the destination at its left-on position at the deferred cut (recall)
```

Replace `switch_to` (lines 86-120) with:

```python
    def switch_to(self, index: int, adjacent: set[int], now: float, resume: bool = False) -> None:
        self._collect_finished_preloads()
        prev = self._current
        self._current = index
        was_on_fallback = self._on_fallback
        self._on_fallback = False
        from_player = self._players.get(prev) if prev is not None and prev != index else None
        player = self._players.get(index)
        if player is None:
            try:
                player = self._factory(self._show.cues[index].source)
                player.preload()
                self._players[index] = player
            except PlayerError as exc:
                log.error("cue '%s' failed to load on switch: %s", self._show.cues[index].id, exc)
                self._failed.add(index)
                self._engage_fallback(now)
                player = None
        if self._tail_possible(from_player, player, was_on_fallback):
            # Tail dissolve: nothing starts and nothing pauses here. A keeps decoding
            # toward its own last-frame still; B's start is deferred to the cut
            # (_finalize_transition). Exactly one decoder runs throughout.
            self._transition = _Transition(
                prev, index, now, self._duration, TransitionMode.CROSSFADE,
                tail_frame=from_player.last_frame, resume=resume,
            )
        else:
            if player is not None:
                try:
                    player.start(now, resume=resume)
                except PlayerError as exc:
                    log.error("cue '%s' failed to start: %s", self._show.cues[index].id, exc)
                    self._failed.add(index)
                    self._engage_fallback(now)
            if self._should_blend(from_player, player):
                # Keep both players decoding for the window; the outgoing one is paused at finalize.
                self._transition = _Transition(prev, index, now, self._duration, self._mode)
            else:
                self._transition = None
                if from_player is not None:
                    from_player.pause()  # instant cut: only the incoming cue decodes continuously
        keep = {index} | adjacent
        for i in [i for i in self._players if i not in keep]:
            self._players.pop(i).stop()
        self._request_preloads(adjacent)

    def _tail_possible(
        self,
        from_player: VideoPlayer | None,
        to_player: VideoPlayer | None,
        was_on_fallback: bool,
    ) -> bool:
        """All preconditions for a tail dissolve; anything short of this is a plain cut."""
        return (
            self._mode is TransitionMode.TAIL_DISSOLVE
            and self._duration > 0
            and to_player is not None
            and from_player is not None
            and from_player.last_frame is not None
            and not was_on_fallback  # outgoing already dead -> nothing healthy to dissolve from
            and not self._on_fallback  # destination just failed to load -> fallback owns the screen
        )
```

In `_blend_at`, thread `now` into every finalize call and add the tail path. Replace `_blend_at` (lines 200-232) with:

```python
    def _blend_at(self, now: float) -> Blend | None:
        """Emit the blend for the active transition, or finalize it and return None."""
        t = self._transition
        progress = 1.0 if t.duration <= 0 else (now - t.start) / t.duration
        if progress >= 1.0:
            self._finalize_transition(now)
            return None
        from_player = self._players.get(t.from_index)
        to_player = self._players.get(t.to_index)
        if from_player is None or to_player is None:
            self._finalize_transition(now)
            return None
        if t.tail_frame is not None:
            # Tail dissolve: live A fades into its own last-frame still. B is never
            # queried and never decodes during the window.
            from_frame = from_player.frame_at(now)
            self._last_frame = t.tail_frame
            return Blend(from_frame, t.tail_frame, max(0.0, min(1.0, progress)), t.mode)
        try:
            to_frame = to_player.frame_at(now)
        except PlayerError as exc:
            # Incoming cue died: abort the blend and drop to the fallback ladder. The switch
            # is already committed, so we do not return to the outgoing cue.
            log.error("incoming cue '%s' failed mid-transition: %s", self._show.cues[t.to_index].id, exc)
            self._failed.add(t.to_index)
            self._finalize_transition(now)  # clears transition and pauses the outgoing decoder
            self._engage_fallback(now)
            return None
        try:
            from_frame = from_player.frame_at(now)
        except PlayerError as exc:
            # Outgoing cue died: it is the side we are leaving, so hard-cut the blend to the
            # healthy destination — no fallback needed.
            log.error("outgoing cue '%s' failed mid-transition: %s", self._show.cues[t.from_index].id, exc)
            self._finalize_transition(now)
            self._last_frame = to_frame
            return None
        self._last_frame = to_frame
        return Blend(from_frame, to_frame, max(0.0, min(1.0, progress)), t.mode)
```

Replace `_finalize_transition` (lines 234-242) with:

```python
    def _finalize_transition(self, now: float) -> None:
        """End the window and revert to the single-decoder rule.

        Base blend: the destination is already running -- just pause the outgoing
        player. Tail dissolve: the destination was never started, so this IS the
        hard cut -- start it here (fresh, or at its left-on position on a recall).
        """
        t = self._transition
        self._transition = None
        if t is None:
            return
        if t.tail_frame is not None:
            to_player = self._players.get(t.to_index)
            if to_player is not None:
                to_player.start(now, resume=t.resume)
        from_player = self._players.get(t.from_index)
        if from_player is not None:
            from_player.pause()
```

(Task 4 hardens this against `start()` failures; keep it minimal here so the failure tests drive that code.)

- [ ] **Step 4: Run the full suite to verify everything passes**

Run: `uv run pytest`
Expected: all PASS. Pay attention to the pre-existing base-blend and failure tests — this refactor must not change base-blend behaviour.

- [ ] **Step 5: Commit**

```bash
git add visualgen/engine.py tests/test_engine.py
git commit -m "feat: tail_dissolve engine path -- dissolve live A into its still, then cut to B"
```

---

### Task 4: Failure & fallback paths — nothing may escape into the render loop

Three hardening rules from the spec: outgoing A dying mid-dissolve finalizes immediately (the finalize IS the hard cut to B); B failing to start at the cut engages the fallback ladder **inside** `_finalize_transition` (it is called from four places in `_blend_at`, all inside the render loop — an escaped `PlayerError` would take down a live show); and the not-possible branches (no `last_frame`, engine on fallback) must be plain cuts — these last two are already guarded by Task 3's `_tail_possible` and get locked in with regression tests here.

**Files:**
- Modify: `visualgen/engine.py` (`_blend_at` tail path, `_finalize_transition`)
- Test: `tests/test_engine.py`

**Interfaces:**
- Consumes: Task 3's `_tail_possible`, `_finalize_transition(now)`, `FakePlayer.fail_on_frame` / `fail_on_start` flags, `_engage_fallback(now)`.
- Produces: the final hardened forms of `_blend_at` (tail branch wrapped in try/except) and `_finalize_transition` (catches `PlayerError`, engages fallback). No signature changes.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_engine.py`:

```python
def test_tail_without_last_frame_hard_cuts():
    # Odd/short/corrupt clip: the capture yielded no still -> plain cut, no window.
    engine, made = _tail_engine(duration=1.0)
    made[Path("/fake/0.mp4")].last_frame = None
    engine.switch_to(1, {0, 2}, now=1.0)
    assert engine.transition_complete()
    assert made[Path("/fake/1.mp4")].started, "cut: B starts immediately"
    assert made[Path("/fake/0.mp4")].pause_count == 1
    assert isinstance(engine.instruction_at(1.0), Single)
    engine.stop()


def test_tail_from_fallback_hard_cuts():
    # A died earlier and the fallback video owns the screen: nothing healthy to
    # dissolve from -> the switch must be a plain cut, not a tail.
    engine, made = _tail_engine(duration=1.0)
    made[Path("/fake/0.mp4")].fail_on_frame = True
    engine.instruction_at(0.5)  # engages the fallback
    engine.switch_to(1, {0, 2}, now=1.0)
    assert engine.transition_complete()
    assert made[Path("/fake/1.mp4")].started
    assert isinstance(engine.instruction_at(1.1), Single)
    engine.stop()


def test_tail_outgoing_death_mid_dissolve_cuts_to_incoming():
    engine, made = _tail_engine(duration=1.0)
    engine.switch_to(1, {0, 2}, now=1.0)
    engine.instruction_at(1.3)  # dissolve underway
    made[Path("/fake/0.mp4")].fail_on_frame = True  # the outgoing cue dies
    instr = engine.instruction_at(1.5)
    assert isinstance(instr, Single), "no partial blend may survive a failure"
    assert instr.frame is made[Path("/fake/1.mp4")].own_frame, "hard-cut to the healthy destination"
    assert made[Path("/fake/1.mp4")].started, "the death cut must start B"
    assert not made[Path("/fake/safe.mp4")].started, "destination healthy -> no fallback"
    assert engine.transition_complete()
    engine.stop()


def test_tail_incoming_start_failure_at_the_cut_engages_fallback():
    engine, made = _tail_engine(duration=1.0)
    engine.switch_to(1, {0, 2}, now=1.0)
    engine.instruction_at(1.5)  # dissolve underway
    made[Path("/fake/1.mp4")].fail_on_start = True  # B will fail at the cut
    instr = engine.instruction_at(2.0)  # must not raise into the render loop
    assert instr is not None
    assert made[Path("/fake/safe.mp4")].started, "start failure at the cut -> fallback ladder"
    assert made[Path("/fake/0.mp4")].pause_count == 1, "A is still paused: single-decoder rule holds"
    assert engine.transition_complete(), "must not stay stuck in a transition"
    engine.stop()
```

- [ ] **Step 2: Run the tests to verify the new code paths fail**

Run: `uv run pytest tests/test_engine.py -v -k tail`

Expected: `test_tail_outgoing_death_mid_dissolve_cuts_to_incoming` FAILS (`PlayerError` propagates out of `instruction_at`) and `test_tail_incoming_start_failure_at_the_cut_engages_fallback` FAILS (`PlayerError` propagates out of `_finalize_transition`). The two not-possible tests PASS already — Task 3's `_tail_possible` guards them; they are regression locks required by the spec.

- [ ] **Step 3: Implement the guards**

In `visualgen/engine.py` `_blend_at`, replace the tail branch from Task 3:

```python
        if t.tail_frame is not None:
            # Tail dissolve: live A fades into its own last-frame still. B is never
            # queried and never decodes during the window.
            from_frame = from_player.frame_at(now)
            self._last_frame = t.tail_frame
            return Blend(from_frame, t.tail_frame, max(0.0, min(1.0, progress)), t.mode)
```

with:

```python
        if t.tail_frame is not None:
            # Tail dissolve: live A fades into its own last-frame still. B is never
            # queried and never decodes during the window.
            try:
                from_frame = from_player.frame_at(now)
            except PlayerError as exc:
                # The outgoing cue died mid-dissolve: finalize immediately -- for a
                # tail, the finalize IS the hard cut to the healthy destination.
                log.error("outgoing cue '%s' failed mid-dissolve: %s", self._show.cues[t.from_index].id, exc)
                self._finalize_transition(now)
                return None
            self._last_frame = t.tail_frame
            return Blend(from_frame, t.tail_frame, max(0.0, min(1.0, progress)), t.mode)
```

Replace `_finalize_transition` with the hardened form:

```python
    def _finalize_transition(self, now: float) -> None:
        """End the window and revert to the single-decoder rule.

        Base blend: the destination is already running -- just pause the outgoing
        player. Tail dissolve: the destination was never started, so this IS the
        hard cut -- start it here (fresh, or at its left-on position on a recall).
        start() can raise and this runs inside the render loop, so failures drop
        to the fallback ladder instead of escaping.
        """
        t = self._transition
        self._transition = None
        if t is None:
            return
        if t.tail_frame is not None:
            to_player = self._players.get(t.to_index)
            try:
                if to_player is None:
                    raise PlayerError(f"player for cue '{self._show.cues[t.to_index].id}' missing at the cut")
                to_player.start(now, resume=t.resume)
            except PlayerError as exc:
                log.error("cue '%s' failed to start at the cut: %s", self._show.cues[t.to_index].id, exc)
                self._failed.add(t.to_index)
                self._engage_fallback(now)
        from_player = self._players.get(t.from_index)
        if from_player is not None:
            from_player.pause()
```

- [ ] **Step 4: Run the full suite to verify everything passes**

Run: `uv run pytest`
Expected: all PASS (~104 tests).

- [ ] **Step 5: Commit**

```bash
git add visualgen/engine.py tests/test_engine.py
git commit -m "feat: tail_dissolve failure paths -- death mid-dissolve and start failure at the cut"
```

---

### Task 5: Manual verification pass and docs

The spec requires a manual pass on real footage: the look (dissolve-then-cut), one-decoder behaviour, and the fallback-to-cut on a broken clip. This needs a human at the keyboard — prepare everything, run it, and report; do not claim the look is right without the operator seeing it.

**Files:**
- Modify: `CLAUDE.md` (the post-MVP design list)
- No source changes expected; fix-forward with a failing test first if the manual pass exposes a bug.

**Interfaces:**
- Consumes: the finished feature (Tasks 1-4), a show YAML with real video files.
- Produces: an operator-verified feature and updated project docs.

- [ ] **Step 1: Run the automated suite one final time**

Run: `uv run pytest`
Expected: all PASS. Report the exact count.

- [ ] **Step 2: Manual pass (operator at the keyboard)**

Using an existing show YAML with real footage (ask the operator which one they use for smoke tests if none is obvious in the repo):

```bash
uv run visualgen <show.yaml>
```

1. Press `t` until the terminal log reads `transition: tail_dissolve  duration: ...`.
2. Press `RIGHT`: the outgoing clip should keep moving while fading into a freeze of its final frame, then crisply cut to the next cue. Adjust the window with `[` / `]` and repeat.
3. Press `DOWN` (recall): same dissolve, and the recalled cue must resume where it was left, not restart.
4. Point one cue at a deliberately broken file (e.g. `cp show.yaml /tmp/broken-test.yaml` and edit a source to a truncated copy): switching away from / to it must degrade to a clean cut or the fallback video — never a stall or black flash.

- [ ] **Step 3: Update CLAUDE.md**

In `CLAUDE.md`, update the transitions bullet list: add a line marking tail_dissolve DONE with today's date, pointing at `docs/superpowers/specs/2026-07-11-tail-dissolve-design.md`, and remove `tail_dissolve` from the "still deferred" sentence in the morph bullet (morph + snap-interrupt remain deferred).

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: tail_dissolve done -- manual pass complete, CLAUDE.md updated"
```

Then use superpowers:finishing-a-development-branch to integrate.
