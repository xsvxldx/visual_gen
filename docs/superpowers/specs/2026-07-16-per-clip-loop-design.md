# Per-clip loop / auto-advance + per-cue transitions — design

**Status:** approved (operator-approved 2026-07-16), ready for implementation plan.
**Author:** brainstormed 2026-07-16.
**Precedent:** follows the `tail_dissolve` spec/plan format and TDD workflow.

## Summary

Give each cue in the show file control over two coupled things:

1. **`loop`** — whether the clip rewinds forever (default, current behaviour) or plays
   once and auto-advances to the next cue.
2. **`transition` / `duration`** — a per-cue transition, used when the operator switches
   *away* from that cue.

A `loop: false` cue plays once and then hard-cuts to the next cue on its own. A `loop: true`
cue plays forever until the operator advances, and when advanced it uses its own predefined
transition.

The default for every field preserves today's behaviour, so **existing show files run
identically** with no edits.

## Decisions (from brainstorming)

- **Transition belongs to the cue you leave (the "from" cue).** Pressing NEXT while `horse`
  is on screen uses `horse`'s transition. PREVIOUS and RECALL away from a cue likewise use
  that cue's transition.
- **`loop: false` ⇒ always a hard cut.** A non-looping cue cuts on advance whether it ends on
  its own (auto-advance) or the operator presses NEXT partway through. Any `transition` set on
  a `loop: false` cue is ignored (startup logs a warning, not an error).
- **Duration is per-cue with a global fallback.** A cue may set its own `duration`; if absent
  it inherits the show-global `duration`, which itself defaults to `0.8`.
- **Dead end** — a `loop: false` cue that is the last cue with `wrap: false`, so there is no
  next cue to advance to — engages the **fallback video and loops it**. If no fallback is
  configured, it **loops the cue itself** rather than freezing.
- **Live keys `t` / `[` / `]`** now edit the **current on-screen cue's** transition/duration
  for the session only (not written back to the file). On a `loop: false` current cue they
  no-op, because that cue always cuts.

## Config schema

Per-cue fields are additive; the YAML parser already ignores unknown keys, so this is
backward-compatible. `Cue` grows from two fields to five. `transition` / `duration` store the
**raw per-cue override**, where `None` means "inherit the show-global value." Inheritance is
resolved by the engine when it builds its per-cue tables (see Architecture), not baked into the
`Cue`, so a cue built without overrides transparently follows the show global:

```python
@dataclass(frozen=True)
class Cue:
    id: str
    source: Path
    loop: bool = True
    transition: TransitionMode | None = None   # None = inherit show-global
    duration: float | None = None              # None = inherit show-global
```

`load_show()` rules:

- `loop` defaults to `true`. This keeps `AGENTS.md:34` ("current video loops indefinitely")
  true by default.
- A cue's `transition` / `duration`, if present in YAML, are parsed and stored; if absent they
  stay `None` (inherit). Reuses the existing `_parse_transition` / `_parse_duration` validators,
  so a typo'd per-cue mode fails at startup with the same clear error.
- **`loop: false` cues always cut.** The engine forces their effective transition to `cut`
  regardless of the stored value (single enforcement point in the table build). If a
  `loop: false` cue *also* specifies a `transition` in YAML, `load_show` logs a warning at
  startup that it is ignored — an operator-visible heads-up, not a hard error.

Example `show.yaml`:

```yaml
transition: crossfade   # show-global defaults
duration: 0.8
wrap: true

show:
  - id: horse
    source: clips/horse.mp4          # inherits: crossfade, 0.8s, loop:true
  - id: montecarlo
    source: clips/montecarlo.mp4
    transition: wipe                 # leaving montecarlo = wipe
    duration: 0.4
  - id: interstitial
    source: clips/sting.mp4
    loop: false                      # plays once -> hard cut to onirofobia
  - id: onirofobia
    source: clips/onirofobia.mp4
```

## Architecture

### Core mechanism — the EOF signal (chosen: approach A)

Today the decode thread silently rewinds at end-of-file (`player.py:157-160`) and nothing
upstream ever learns a clip ended. The chosen fix gives the player a `loop` flag and an
explicit "ended" signal, holding the last frame on end:

- **Constructor:** `VideoPlayer(source, buffer_size=3, loop=True)`. Default `True` preserves
  today's behaviour for every existing caller.
- **New signal:** a `threading.Event` (`_ended`), exposed as a read-only `ended` property.
  Thread-safe by construction — set in the decode thread, read in the render loop.
- **Decode loop** (`player.py:151-160`) becomes one branch:

  ```python
  except (StopIteration, av.error.EOFError):
      if self._loop:
          self._container.seek(0)
          decoder = self._container.decode(self._stream)
          continue
      self._ended.set()      # loop=False: announce end, stop advancing
      break                  # thread exits; frame_at() keeps returning last frame
  ```

  When the thread exits, `frame_at()` naturally holds `self._current` (the final frame); no
  new holding logic is needed.
- **Restart re-arms:** `start()` is already restart-safe (`player.py:91-99`) — it halts any
  running thread and re-decodes. It additionally `self._ended.clear()`s on entry, so a
  restarted `loop: false` player can end again (needed for the dead-end re-loop).

Alternatives considered and rejected:

- **B — player always loops, pulses `ended` on each wrap.** Smaller thread change, but a
  one-frame flash of the restarted clip appears before the cut lands, and the flag must be
  carefully edge-triggered to avoid re-firing every loop.
- **C — infer end from clip duration/time.** No thread change, but `stream.duration` is not
  always available (read and discarded at `player.py:79` precisely because it is unreliable),
  making it fragile. Rejected.

Approach A gives a clean cut from the frozen last frame (no flash), an explicit rather than
inferred signal, and a single-branch decode-thread change — consistent with the project's
"reliability over cleverness" rule.

### Per-cue transitions (`engine.py`)

The engine currently holds one `self._mode` / `self._duration` used for every switch
(`engine.py:124`). These become per-cue tables built at construction, resolving `None`
overrides against the show global and forcing `loop: false` cues to `cut`:

```python
self._modes = [
    TransitionMode.CUT if not c.loop else (c.transition or show.transition)
    for c in show.cues
]
self._durations = [
    (c.duration if c.duration is not None else show.duration) for c in show.cues
]
```

- **`switch_to(A → B)` reads the from-cue's entry:** `mode = self._modes[prev]`,
  `duration = self._durations[prev]`, replacing the global `self._mode` / `self._duration`
  (also threaded into the `_should_blend` / `_tail_possible` helpers, which currently read the
  globals). Because the table forces `loop: false` cues to `cut`, such cues cut automatically on
  both manual and auto advance — no special-casing in the switch path.
- **Players are created with their cue's loop flag:** every `self._factory(cue.source)` call
  (in `start`, `switch_to`, `_request_preloads`) passes `loop=cue.loop`, so a `loop: false`
  cue's player stops-and-signals at EOF. The fallback player keeps the default `loop=True`.
- **Live keys retarget to the current cue:** `cycle_mode()` / `adjust_duration()` mutate
  `self._modes[self._current]` / `self._durations[self._current]` instead of a global, giving
  session-only per-cue overrides. They no-op when there is no current cue, and no-op on a
  `loop: false` current cue (it always cuts). The `mode` / `duration` properties return the
  current cue's table value, falling back to `show.transition` / `show.duration` when no cue is
  current yet (for the existing log line at `app.py:99`).

### Auto-advance (`app.py`)

One new block in the render loop, beside the existing `complete_switch()` check
(`app.py:106-111`), so it inherits the same `State.SWITCHING` re-entrancy guard:

```python
if cue_manager.state is State.PLAYING and engine.current_cue_ended():
    target = cue_manager.handle(Command.NEXT)   # reuses ALL existing switch logic
    if target is not None:
        engine.switch_to(target, cue_manager.adjacent(), clock.now())
    else:
        engine.hold_end_of_show(clock.now())    # dead end: fallback+loop, else re-loop cue
```

- **Reusing `handle(Command.NEXT)`** means auto-advance wraps when `wrap: true`, records
  `previous` (so DOWN/recall returns to the auto-advanced-from cue), and sets `SWITCHING` —
  identical to a manual NEXT. No new CueManager code.
- **`engine.current_cue_ended()`** reads the current player's `ended` flag.
- **`engine.hold_end_of_show()`** handles the dead end: engage the fallback player looping if
  one exists (reusing `_engage_fallback`), otherwise `start()` the current player again to
  re-loop it. It must be **idempotent per end**: the current player's `ended` flag stays set
  until the player is restarted or replaced, so the re-loop branch calls `start()` (which
  clears `ended`) and the fallback branch is a no-op when already on the fallback
  (`self._on_fallback` guards it). Without this, the block would re-fire every tick.

The command drain runs before this check, so a manual press in the same tick wins over
auto-advance, and the `SWITCHING` guard ensures only one switch fires.

## Data flow

1. `loop: false` clip reaches EOF → decode thread sets `_ended`, holds last frame.
2. Render loop, while `PLAYING`, sees `engine.current_cue_ended()` true.
3. `cue_manager.handle(Command.NEXT)` returns a target (or `None` at a dead end) and sets
   `SWITCHING`.
4. Target present → `engine.switch_to` cuts (from-cue is `loop: false` ⇒ `cut`). Dead end →
   `engine.hold_end_of_show` engages fallback (looping) or re-loops the cue.
5. `SWITCHING` clears via the existing `complete_switch()` path once the transition and
   preloads are ready.

## Error handling / degradation

- **No reliable duration** (`_capture_last_frame` returned `None`): unaffected. `ended` comes
  from the decode thread hitting EOF, not from duration, so auto-advance still works.
- **No fallback configured at a dead end:** re-loop the current cue (motion continues; never a
  frozen or black screen).
- **Manual NEXT during the same tick a cue ends:** command drain runs first, so the manual
  press wins; the `SWITCHING` guard prevents a double switch.

## Testing (TDD, per-behaviour)

- **Config (`test_show.py`):** per-cue `loop` / `transition` / `duration` parse and override
  globals; absent fields inherit globals; existing files with no new fields yield `loop=True` +
  global transition; `loop: false` forces `transition=cut` and warns if a transition was also
  set; invalid per-cue transition/duration fails at startup.
- **Player (`test_player.py`):** `loop=False` sets `ended` at EOF and holds the last frame;
  `loop=True` (default) still loops (existing `test_loops_past_end_of_file` unchanged);
  `start()` clears `ended` (restart re-arms).
- **Engine (`test_engine.py`):** `switch_to` uses the from-cue's mode/duration; a `loop: false`
  from-cue cuts regardless of any transition value; live keys mutate only the current cue and
  no-op on a `loop: false` cue; `current_cue_ended()` reflects the player flag.
- **Auto-advance (`test_engine.py` / app-level):** an ended `loop: false` cue advances to the
  next with a cut; auto-advance is ignored while `SWITCHING`; `wrap: true` last cue
  auto-advances to the first; dead end with fallback → fallback loops; dead end without
  fallback → cue re-loops.

## Scope note — MVP constraints renegotiated

This feature knowingly touches two `AGENTS.md` constraints, recorded here because CLAUDE.md
treats MVP constraints as explicit decisions:

- **`AGENTS.md:34` "current video loops indefinitely"** — still the default (`loop: true`);
  `loop: false` is opt-in per cue.
- **`AGENTS.md:216` "only the current cue and the adjacent cue(s) should be decoded"** —
  untouched. Auto-advance reuses the existing adjacent-cue preload; no additional decoding.

## Out of scope (YAGNI)

- Per-cue transition on auto-advance (auto-advance is always a cut by decision).
- Writing live-key overrides back to the show file.
- Timing an auto-advance transition to *finish* at clip end (only relevant for non-cut blends;
  the operator's use case is cuts, which have zero duration).
