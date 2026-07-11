# tail_dissolve Transition — Design Spec (APPROVED)

**Status:** Approved. A new transition type, built on the merged transitions framework
(`docs/superpowers/specs/2026-07-10-transitions-framework-design.md`).
**Date:** 2026-07-11

**Ground rule:** reliability over cleverness — this runs live performances. The switch must never
stall waiting to decode, and must always resolve to a clean single source.

---

## The effect

When you switch away from cue A, A keeps playing while it **dissolves into a still of its own
last frame** (the final frame of A's video file), then **hard-cuts to B**. Visually: A's motion
settles onto where the clip ends, then a crisp cut to the next cue.

Chosen behaviour (from brainstorming):
- **A stays live during the dissolve** — the outgoing cue keeps decoding and its live frame is
  crossfaded toward the frozen A-last still. Only **one video decodes at any instant** (A during
  the dissolve, B after the cut).
- **Target still = clip A's final frame**, not the on-screen frame at press. It shows "where A
  ends," which may be content the viewer hasn't seen.
- **Hard cut to B** at the end (no second crossfade). B starts decoding at the cut.

This is a distinct transition *shape* from the base blends (which crossfade two live players and
finalize to the incoming). It is also the same multi-phase shape morph will later use, with
A-last standing in for a pre-rendered clip — so it de-risks morph.

---

## Selection & config

`tail_dissolve` is the **5th value of `TransitionMode`**, selected exactly like the base blends:

- YAML: `transition: tail_dissolve`.
- Live key `t` cycles it in order: `cut → dip → crossfade → wipe → tail_dissolve → cut`.
- `duration` (and live `[` / `]`) sets how long the dissolve-into-the-still lasts; then it cuts.

No new keys, no new config fields. It reuses the framework's mode/duration session state.

---

## How A-last is obtained

Extend `VideoPlayer` with a `last_frame: Frame | None` attribute, captured **eagerly at preload**
on the background preload thread (never on the main loop):

- During `preload()`, after the existing first-frame capture, obtain the clip's final frame:
  open the source, seek to the end (by stream duration), decode forward through the last GOP, and
  keep the last decoded frame — converted via the existing `_convert` helper. Do this in an
  **isolated short-lived container** so it cannot disturb the playback container's state (which
  `start()` re-seeks anyway).
- If the stream has no usable duration, or seek-to-end / decode yields nothing, leave
  `last_frame = None` (→ fallback, below). Never decode a whole unknown-length file to find it.

Because preload runs for the current + adjacent cues before you switch, the outgoing cue's
`last_frame` is ready the instant you press switch — no stall.

**Cost / trade-off (accepted for v1):** every preload does this extra end-decode even in shows
that never use tail_dissolve. It is small and on a background thread. **Deferred optimization —
lazy capture:** only capture last-frames once tail_dissolve is armed (selected via `t` or YAML),
for the resident cues. Noted, not built now.

---

## Engine orchestration

`tail_dissolve` extends the existing in-flight `_Transition` rather than adding a parallel
mechanism. Add one optional field:

```
_Transition(from_index, to_index, start, duration, mode, tail_frame: Frame | None = None)
```

`tail_frame` set ⇒ this is a tail_dissolve. `to_index` is still B (the real destination).

**`switch_to(B, …, now)` — tail branch** (when `self._mode is TAIL_DISSOLVE` and the tail is
possible — see fallback): unlike a base switch, it does **not** start B and does **not** pause A:
- Keep A (the outgoing player) decoding.
- Ensure B's player is loaded (lazy-preload if missing) but **not started**.
- Record `_Transition(from=A, to=B, start=now, duration, mode=CROSSFADE, tail_frame=A.last_frame)`.
- Evict far players / request preloads as usual (A and B are both kept — A is adjacent to B).

**`instruction_at` / `_blend_at` — tail path:** while `t < 1`, emit
`Blend(from = A.frame_at(now) [live], to = tail_frame [A-last still], t, crossfade)`. B is never
queried and never decodes. The blend renders as an ordinary crossfade (no renderer change — the
renderer already letterboxes each frame by its own aspect, and A-last is A's own resolution).

**Finalize (t ≥ 1) — tail path:** hard cut to B. `_finalize_transition(now)` gains a `now`
argument; for a tail transition it **starts B** (`to_player.start(now)` — B begins fresh at the
cut) and **pauses A**. `_current` is already B. If B's player is missing it is lazily created;
if B fails to load or start, engage the existing fallback ladder. (Base-blend finalize is
unchanged except for threading `now`: it still just pauses the outgoing player.)

Result: exactly one decoder throughout, a clean crossfade-into-still, then a crisp cut to a
fresh B — and `transition_complete()` flips true so `CueManager` returns to `PLAYING`.

---

## Failure & fallback

- **A-last unavailable** (`last_frame is None` — odd/short/corrupt clip): do **not** attempt the
  tail. Fall back to a **hard cut** to B (today's default switch behaviour). Chosen for v1.
  *(Deferred: make the fallback a config choice between cut and crossfade.)*
- **Outgoing A dies mid-dissolve** (`frame_at` raises): finalize immediately — hard-cut to B
  (start B). Same spirit as the framework's outgoing-death rule.
- **B fails to load/start at the cut:** engage the fallback ladder (fallback video → freeze on
  last frame), reusing `_engage_fallback` / `_last_frame`. No new failure path.
- The target of the dissolve is a static still, so there is no "incoming dies mid-window" case
  during the dissolve itself.

Guarantee unchanged from the framework: no partial blend survives a failure, and the FSM never
gets stuck in `SWITCHING`.

---

## Testing

Unit tests mirror the framework's `FakePlayer` + float-`now` style. `FakePlayer` gains a
`last_frame` attribute so engine tests can drive the tail path deterministically.

- **Engine (tail path):** during the window emits `Blend(live-A, A-last-still, crossfade)` with
  the still as the `to` frame; **B is not started during the window**; at `t ≥ 1` B is started
  and A is paused (`pause_count`); `transition_complete()` flips true.
- **Fallback:** `last_frame is None` ⇒ no tail, hard-cut to B (B started immediately, no blend);
  A dies mid-dissolve ⇒ finalize/cut to B; B start-failure at the cut ⇒ fallback engaged.
- **last_frame capture (real clip):** a `VideoPlayer` preloaded on a short generated/real clip
  exposes a `last_frame` equal to the clip's final frame (test in `test_player.py` style;
  reuse the `video_file` fixture or a synthesized multi-frame clip).
- **Config / selection:** `transition: tail_dissolve` parses to `TransitionMode.TAIL_DISSOLVE`;
  the `t` cycle includes it in order.
- **Manual pass:** the look on real footage (dissolve-then-cut), one-stream memory behaviour,
  and the fallback-to-cut on a deliberately broken clip.

---

## Deferred (recorded, not built here)

- **Lazy last-frame capture** — only capture once tail_dissolve is armed.
- **Configurable fallback** — a knob to choose cut vs crossfade when A-last is unavailable.
- **Morph-bridge type** and **snap-interrupt** remain deferred as before; tail_dissolve is the
  stepping stone that introduces the multi-phase (blend-into-a-bridge, then hand off) shape morph
  will reuse.
