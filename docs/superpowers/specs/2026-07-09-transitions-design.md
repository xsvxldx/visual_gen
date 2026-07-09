# Transitions — Design Notes (DRAFT / DEFERRED)

**Status:** Draft. Brainstorm captured 2026-07-09, paused before completion.
**Priority:** Roadmap #1, but **deferred until the MVP is stable** (per `AGENTS.md` — no
transitions/effects/UI before MVP soak passes). This document exists so the work can be
resumed cold when the moment comes; it is *not* an approved spec and has no implementation
plan yet.

**What's still open:** Section 4 (morph specifics: preloading, snap-abort of a morph clip)
and Section 5 (testing strategy) were not finished. See "Open items" at the end.

---

## Goal

Add transitions between adjacent cues. Two related capabilities:

1. A **pluggable transition framework** with several selectable types you can toggle on/off
   to experiment live and settle on what works.
2. A **morph-bridge type** where the morph itself is a short video pre-rendered externally
   (ComfyUI), authored to run from cue A's last frame to cue B's first frame. The app plays
   it as a bridge clip between the two cues.

**Build order (decided): framework first, morph as one type added last.** The simple blend
types de-risk the plumbing, and — importantly — the morph type needs *no new renderer code*;
it's the engine orchestrating instructions the framework already emits (see Section 1).

Because switching is only NEXT/PREVIOUS, transitions only ever occur between **adjacent
cues**. The set of A→B pairs is therefore small and known ahead of time from the fixed show
order — which is what makes pre-rendered morph clips practical.

---

## Decisions log (quick reference)

| Question | Decision |
|---|---|
| Build order | Framework first; morph added as one type last |
| How types are selected | Live keyboard hotkey **+** YAML default (session overrides not written back) |
| Mid-transition re-press | **Deferred.** v1 = ignore during `SWITCHING` (today's behavior). Snap-interrupt is a noted follow-up. |
| Morph handoff (A mid-loop → clip) | Short crossfade (~0.3s) from live-A into the morph clip (reuses crossfade) |
| Morph clip mapping | Explicit in YAML (`morph_next` / `morph_prev`), opt-in per pair; missing → fall back to base blend |

---

## Section 1 — The seam (approved)

The engine decides *what* to show; the renderer just draws it. Replace the single-frame
handoff with a small **render instruction** that is one of two shapes:

- `Single(frame)` — normal playback, and the middle of a morph (only the clip on screen).
- `Blend(from_frame, to_frame, t, mode)` — during a transition: two frames + progress
  `t` (0→1) + `mode` (`dip` / `crossfade` / `wipe`).

The renderer gains one method, `render(instruction)`, that either draws a single frame (as
today) or blends two frames per `mode`. **The renderer stays pure** — no knowledge of
players, timing, or morph clips; it only knows "blend these two textures by this much."

Module boundaries (unchanged in spirit):
- **CueManager** — still the pure index/state machine. Only change: *when* `complete_switch`
  fires (Section 3).
- **PlaybackEngine** — owns the in-flight transition: keeps both players decoding during the
  window, computes `t` from the clock, emits the right `Single`/`Blend` each frame.
- **Renderer** — gains two-texture blending, nothing else.

**Payoff:** a morph is just the engine orchestrating a *sequence* of instructions it can
already emit — short `Blend(crossfade)` from live-A into the morph clip, then `Single`
frames of the morph clip, then `Single` frames of B. Building crossfade first delivers the
hardest part of morph for free.

Relevant current code: `visualgen/engine.py:119` (`frame_at`), `visualgen/render.py:83`
(`draw`) — these are the two touch points.

---

## Section 2 — Types & the on/off model (approved)

Two independent knobs (matches "not every pair needs a morph"):

**Knob A — base blend** (always applies to every switch):

| Mode | What | Cost |
|---|---|---|
| `cut` | instant hard cut (today's behavior) | free |
| `dip` | fade through black | 1 texture set |
| `crossfade` | dissolve A→B | 2 texture sets |
| `wipe` | moving-edge reveal | 2 texture sets |

**Knob B — morph (on/off):** when **on**, if the current pair has a morph clip, play the
morph bridge; otherwise fall back to the base blend. When **off**, always use the base blend.
One switch turns all morph behavior off so you can A/B compare.

Config (YAML default = repeatable show):

```yaml
# show.yaml
transition: crossfade   # base blend default
duration: 0.8           # seconds
morph: on               # use morph clips where they exist
show:
  - id: a
    source: a.mp4
    morph_next: morphs/a_to_b.mp4   # optional, per direction
  - id: b
    source: b.mp4
    morph_prev: morphs/b_to_a.mp4   # optional
```

Live keys (temporary keyboard adapter — same pattern as MVP milestone 4):

```
t         cycle base blend   (cut → dip → crossfade → wipe → …)
m         toggle morph on/off
[  ]      duration −/+ 0.1s
```

Folded-in decisions:
- Morph clips **declared explicitly** in YAML (`morph_next` / `morph_prev`), not filename
  auto-discovery — self-documenting; missing = fall back to base blend, never an error.
- Live overrides are **session-only** — YAML stays the source of truth; keys are for
  experimenting. Find a combo you like, then edit the YAML.

---

## Section 3 — Timed switching (approved, with snap deferred)

Elapsed time drives completion instead of the current one-frame switch:

- On NEXT/PREV, `CueManager` enters `SWITCHING`; the engine starts a transition stamped with
  `start_time` and `duration`.
- Each frame, engine computes `t = (now − start_time) / duration`, clamped to 1.
- When `t` reaches 1, the transition finalizes: destination becomes the sole live player,
  outgoing player released, `complete_switch()` fires → `PLAYING`.

**Both players decode during the window** (today the outgoing player is paused —
`engine.py:57`, "only the incoming cue decodes continuously"). Keep both decoding during the
transition so the blend is live motion, then revert to the single-decoder rule the instant it
completes. Extra cost bounded to the ~0.8s window — safe for the flat-memory goal.

**Finalize to "now," not frame 0.** The incoming player has been decoding the whole window,
so finalize to its actual timeline position. Correct regardless of interrupts.

**Mid-transition re-press — v1 behavior = ignore** (today's `CueManager.handle()` returns
`None` while `SWITCHING`). Simplest, no half-finished states. Known limitation: with a long
duration, mashing NEXT feels laggy (presses drop for ~duration). Acceptable for v1.

**Snap-interrupt — deferred follow-up.** The chosen eventual behavior is "finalize current
transition instantly, then start the next toward the new target." The seam is built to allow
it: because a transition is a discrete, finalizable unit in the engine, adding snap later is a
localized change — `CueManager.handle()` (snap-then-advance instead of `None`) + one
`engine.finalize_now()` call. No seam rework. For a morph mid-flight, snap = abort the clip,
drop its player, hard-cut to destination, start next. (Reliability over polish.)

---

## Open items (not yet designed — resume here)

### Section 4 — Morph specifics (unfinished)
- **Preloading morph clips.** The engine already preloads adjacent cues; extend it to also
  preload the morph clips for the adjacent pairs (from cue `i`: the `morph_next` for `i→i+1`
  and `morph_prev` for `i→i-1`) so the bridge is ready instantly on NEXT/PREV. Where does the
  morph player live — reuse `VideoPlayer` behind the existing preload machinery?
- **Morph orchestration state machine** inside the engine: phase 1 crossfade-in (~0.3s,
  live-A → clip), phase 2 clip body (`Single`), phase 3 handoff to B (clip.last = B.first, so
  a clean cut; confirm whether a tiny crossfade-out is wanted or a hard cut suffices).
- **Authoring contract for ComfyUI clips:** morph[0] must equal A's last frame; morph[last]
  must equal B's first frame. Document resolution/fps/codec expectations so clips drop in
  seamlessly. Consider a validation warning at load if a declared clip is missing/unreadable.
- **Snap-abort of a morph** (only if/when snap-interrupt is built): releasing the clip player
  cleanly mid-play.

### Section 5 — Testing strategy (unfinished)
- Pure-unit tests (no hardware), consistent with the MVP approach:
  - `t` progression + clamping; finalize-to-now; `complete_switch` timing.
  - Render-instruction selection: PLAYING → `Single`; during window → `Blend` with correct
    `mode`; morph phases emit the right sequence.
  - Config parsing/validation for `transition` / `duration` / `morph` / `morph_next` /
    `morph_prev`; fallback-to-base-blend when a clip is absent.
  - Live-key handling maps to the right knob changes.
- Manual milestone verification against real videos + a real ComfyUI morph clip (seam of the
  clip endpoints; flat memory across many transitions).

### Also revisit before implementing
- Confirm whether a tiny crossfade-*out* of the morph clip is wanted, or a hard cut suffices
  (clip.last = B.first should make a cut seamless).
- Decide the exact crossfade-in duration for morph (proposed ~0.3s) and whether it's
  configurable.
- Interaction with the existing **fallback video** path (`engine.py:104`) — what a transition
  does if a target cue dies mid-transition.
