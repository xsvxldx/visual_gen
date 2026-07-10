# Cue Recall (undo-last-switch) — Design

**Date:** 2026-07-09
**Status:** Implemented & merged to `main` (2026-07-10) — plan `docs/superpowers/plans/2026-07-09-cue-recall.md`
**Related:** `AGENTS.md`, MVP design `docs/superpowers/specs/2026-07-05-visual-engine-mvp-design.md`

## Problem

Switching cues with `NEXT` / `PREVIOUS` always restarts the target cue from the top
(fast, because the first frame is preloaded). If the operator advances by accident,
there is no way to get back to where they were — the previous cue would restart from
frame 0, losing the position.

## Goal

Add a **recall** control that returns to the cue the operator was just on, **resumed at
the frame it was showing when they left it**. Pressing recall again bounces back the other
way (A/B toggle), each side resuming where it was last left.

Non-goals (deliberately out of scope):
- MIDI trigger for recall (keyboard only for now; MIDI deferred).
- Remembering positions for more than the immediate A/B pair.
- Transitions/effects of any kind.

## Behavior

- `NEXT` / `PREVIOUS` (arrows / MIDI 60 / 61): **unchanged** — switch to the cue from the
  top, zero latency (first frame preloaded).
- `RECALL` (keyboard `DOWN`):
  - Switch to the **previously-left cue**, resumed at the frame it was on when left.
  - Pressing recall again returns to the other cue, also at its last-left position (toggle).
  - No effect if there is no prior cue (e.g. at startup) or while a switch is in progress
    (`SWITCHING` state), consistent with how `NEXT`/`PREVIOUS` are dropped during a switch.

### Perceived latency

- `NEXT`/`PREVIOUS`: zero — unchanged preloaded path.
- `RECALL`: visually instant. The exact frame the operator left on is held in memory and
  shown immediately (no black, no jump). Motion resumes within a few tens of ms as the
  decoder seeks to the resume point and catches up. Only recall pays this small one-time
  catch-up; the normal switch path keeps its zero-latency preloaded behavior.

## Architecture

Follows the existing flow — **Input Adapter → `Command` → `CueManager` → `PlaybackEngine`
→ `Renderer`** — and respects module boundaries: inputs only emit `Command`s, `CueManager`
stays a pure position FSM (no playback-time knowledge), only the player learns to resume.

The "where I left it" position lives with the **player** that owns the video stream
(chosen over an engine-owned position map or putting it in `CueManager`, which would leak
playback-time concerns into a pure FSM).

### Components & changes

1. **`visualgen/commands.py`** — add `RECALL` to the `Command` enum.

2. **`visualgen/cues.py`** — `CueManager` gains `_previous: int | None` (the index it was on
   before the last switch).
   - `NEXT`/`PREVIOUS`: on a successful move, set `_previous = <old index>` before updating
     `_index`.
   - `RECALL`: if `_state is SWITCHING` or `_previous is None` → return `None`. Otherwise set
     `target = _previous`, swap `_previous ↔ _index` (this is what makes recall toggle), set
     `_state = SWITCHING`, return `target`.

3. **`visualgen/player.py`** — resume support on `VideoPlayer`:
   - New fields: `_resume_pts: float = 0.0`, `_hold: Frame | None = None`.
   - `pause()`: before halting, record `_resume_pts = self._current.pts` (0.0 if nothing
     shown yet) and `_hold = self._current` (the exact frame left on).
   - `start(now, resume=False)`:
     - `resume=False` (default, unchanged behaviour): seek to 0, `_epoch = now`,
       `_current = None`, `_hold = None`.
     - `resume=True`: seek to the keyframe at/before `_resume_pts`
       (`container.seek(int(_resume_pts * 1_000_000))`), set `_epoch = now - _resume_pts`,
       `_current = None`, keep `_hold` for display during catch-up.
   - `frame_at()` returns `self._current or self._hold or self.first_frame`, so the held
     frame is shown until the decoder produces the resume frame.
   - The existing catch-up loop in `frame_at` (consume frames while `_epoch + pts <= now`)
     naturally skips from the keyframe forward to the resume point — **no decode-loop
     changes needed.**

4. **`visualgen/engine.py`** — `switch_to(index, adjacent, now, resume=False)` passes
   `resume` through to `player.start(now, resume=resume)`. Everything else (pause outgoing,
   drop far players, request preloads, fallback ladder) is unchanged.

5. **`visualgen/app.py`** — `DOWN` → `commands.put(Command.RECALL)`. In the drain loop:
   `resume = command is Command.RECALL`, then
   `engine.switch_to(target, cue_manager.adjacent(), clock.now(), resume=resume)`.

## Data flow (recall)

```
DOWN key -> Command.RECALL -> CueManager.handle():
    target = _previous;  swap _previous<->_index;  state=SWITCHING
  -> app: engine.switch_to(target, adjacent, now, resume=True)
       -> pause current player (records its _resume_pts + _hold)
       -> target player.start(now, resume=True)
            seek to keyframe <= _resume_pts; epoch = now - _resume_pts; show _hold
       -> frame_at: show held frame, then skip forward to the resume frame, resume motion
```

## Error handling / reliability

- A resume seek that fails raises `PlayerError` from `start()`, which `switch_to` catches
  and routes to the existing fallback → freeze-frame ladder — on both the resume and
  normal switch paths. No new failure surface.
- `start()` is already restart-safe (halts any running decode thread first), so recall
  introduces no new thread/race concerns.
- Resume near end-of-clip is fine: catch-up reaches the target, then the normal EOF→seek(0)
  loop takes over.

## Testing

- **`test_commands`**: `Command.RECALL` exists.
- **`test_cues`**: recall with no history → `None`; `NEXT` then `RECALL` returns the original
  index; `RECALL` toggles A/B; `RECALL` ignored while `SWITCHING`.
- **`test_player`**: after playing then `pause()`, `start(resume=True)` yields a frame at
  ~`_resume_pts` (not 0) and shows the held frame immediately; `start(resume=False)` still
  yields pts 0 from the top.
- **`test_engine`**: `switch_to(resume=True)` resumes the target from its paused position
  (via a `FakePlayer` that records the `resume` flag / seek target).

## Scope

~40 lines across five files plus tests. Beyond the strict MVP spec but explicitly
requested; respects all module boundaries.
