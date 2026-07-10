# Transitions Framework — Design Spec (APPROVED)

**Status:** Approved. Framework-only scope for this implementation cycle.
**Date:** 2026-07-10
**Supersedes (in part):** `2026-07-09-transitions-design.md` (the earlier DRAFT). This spec
promotes that draft's approved Sections 1–3 to an implementable spec and adds the mid-transition
failure rule. The **morph** capability (that draft's Sections 4–5) is intentionally **out of
scope here** and remains a separate later cycle.

**Ground rule that governs everything below:** reliability over cleverness — this runs live
performances. A transition must never leave a broken or half-finished image on screen.

---

## Goal

Add **base transitions** between adjacent cues: instead of the current instant one-frame hard
cut, a NEXT/PREVIOUS switch plays a short, timed blend from the outgoing cue to the incoming cue.

Because switching is only NEXT/PREVIOUS, transitions only ever occur between **adjacent cues**.

This cycle delivers the *framework*: the render seam, the four base blend modes, timed
switching, config + live hotkeys, and failure handling. The morph-bridge type (a pre-rendered
ComfyUI clip played as a bridge) is deliberately deferred; the seam is designed so morph can be
added later as one more type **with no renderer changes**.

Non-goals (explicitly deferred):
- Morph-bridge clips, morph preloading, morph authoring contract.
- Snap-interrupt of an in-flight transition (mid-transition re-press). v1 ignores presses while
  switching, matching today's behavior.

---

## Decisions log (quick reference)

| Question | Decision |
|---|---|
| Scope this cycle | Framework only (base blends + timed switching + seam + failure rule). Morph deferred. |
| Base blend types | `cut`, `dip` (through black), `crossfade`, `wipe` |
| How types are selected | YAML default (repeatable show) **+** live keyboard hotkeys (session-only overrides, not written back) |
| Mid-transition re-press | v1 = ignore during `SWITCHING` (today's behavior). Snap-interrupt deferred. |
| Finalize position | Finalize to the incoming player's *actual* timeline position ("now"), not frame 0 |
| Both players during window | Yes — both decode for the ~duration window, then revert to single-decoder rule |
| Target dies mid-transition | Abort transition → `Single`, engage fallback ladder (today's dead-cue behavior) |
| Outgoing dies mid-transition | Finalize instantly to the incoming player (`Single(to)`); no fallback needed |

---

## Section 1 — The render seam

The engine decides *what* to show; the renderer just draws it. Replace the current single-frame
handoff with a small **render instruction** that is one of two shapes:

- `Single(frame)` — normal playback (and, later, the middle of a morph): one frame on screen.
- `Blend(from_frame, to_frame, t, mode)` — during a transition: two frames + progress `t`
  (0→1) + `mode` (`dip` / `crossfade` / `wipe`). (`cut` produces no `Blend` — see below.)

The renderer gains one method, `render(instruction)`, that either draws a single frame (as
today) or blends two frames according to `mode`. **The renderer stays pure** — no knowledge of
players, timing, or transitions; it only knows "blend these two textures by this much."

Blend semantics per mode (renderer-local, `t` in 0→1):
- `crossfade` — linear alpha dissolve: `out = (1−t)·from + t·to`.
- `dip` — fade through black: `from` fades to black over the first half (`t`: 0→0.5), `to`
  fades up from black over the second half (`t`: 0.5→1). At any instant at most one texture is
  partially visible over black.
- `wipe` — moving hard edge reveals `to` over `from` across the frame (direction fixed for v1;
  left-to-right).
- `cut` — not a blend. The engine emits `Single(to)` immediately with no window (duration is
  treated as 0). Included as a mode so "cut" is selectable via the same knob.

Module boundaries (unchanged in spirit):
- **CueManager** — still the pure index/state machine. Only behavioral change: *when*
  `complete_switch` fires (Section 3). It gains no rendering, timing, or blend knowledge.
- **PlaybackEngine** — owns the in-flight transition: keeps both players decoding during the
  window, computes `t` from the clock, and emits the right `Single` / `Blend` each frame.
- **Renderer** — gains two-texture blending, nothing else.

**Payoff for the deferred morph work:** a morph becomes just the engine orchestrating a
*sequence* of instructions it can already emit (a short `Blend(crossfade)` into the clip, then
`Single` frames of the clip, then `Single` frames of B). Building crossfade now delivers the
hardest part of morph for free — and confirms no renderer change is needed later.

Relevant current code (touch points): `visualgen/engine.py` `frame_at` (currently returns a
single `Frame`); `visualgen/render.py` `draw`. `frame_at` becomes the producer of a render
instruction; `render.py` gains the blend path.

---

## Section 2 — Types and the on/off model

**One knob this cycle — base blend** (applies to every switch):

| Mode | What | Cost during window |
|---|---|---|
| `cut` | instant hard cut (today's behavior) | free (no window) |
| `dip` | fade through black | 1 texture set |
| `crossfade` | dissolve A→B | 2 texture sets |
| `wipe` | moving-edge reveal | 2 texture sets |

(The second knob from the draft — morph on/off — is deferred with the morph work. Nothing in
this cycle references morph.)

Config (YAML default = repeatable show):

```yaml
# show.yaml
transition: crossfade   # base blend default: cut | dip | crossfade | wipe
duration: 0.8           # seconds; ignored when transition is cut
show:
  - id: a
    source: a.mp4
  - id: b
    source: b.mp4
```

Defaults when keys are absent: `transition: cut`, `duration: 0.8`. `cut` preserves today's exact
behavior, so an existing show with neither key is unchanged.

Validation at load:
- `transition` must be one of the four known modes; unknown → error at load (fail fast, before
  the show runs), consistent with existing show-parse validation.
- `duration` must be a positive number; non-positive or non-numeric → error at load.

Live keys (temporary keyboard adapter — same pattern as the MVP keyboard milestone; inputs emit
Commands only, no engine logic in the adapter):

```
t         cycle base blend   (cut → dip → crossfade → wipe → cut → …)
[  ]      duration  − / +  0.1s   (floored at 0.1s)
```

Live overrides are **session-only** — YAML stays the source of truth; keys are for experimenting
live. Find a combo you like, then edit the YAML. Overrides are not written back.

---

## Section 3 — Timed switching

Elapsed time drives completion instead of the current one-frame switch.

- On NEXT/PREV, `CueManager` enters `SWITCHING`; the engine starts a transition stamped with
  `start_time` and `duration` (and the resolved `mode`).
- Each frame, the engine computes `t = (now − start_time) / duration`, clamped to `[0, 1]`.
- While `t < 1`, the engine emits `Blend(from, to, t, mode)`.
- When `t` reaches 1, the transition **finalizes**: the destination becomes the sole live
  player, the outgoing player reverts to the paused/released state per the single-decoder rule,
  and the engine emits `Single(destination)`. `complete_switch()` fires → `PLAYING`.
- `cut` mode: duration is treated as 0, so the transition finalizes on the first frame — a hard
  cut, identical to today.

**Both players decode during the window.** Today the outgoing player is paused on switch (only
the incoming cue decodes continuously). During a transition, keep **both** decoding for the
window so the blend shows live motion on both sides, then revert to the single-decoder rule the
instant it finalizes. Extra cost is bounded to the ~duration window — safe for the flat-memory
goal.

**Finalize to "now," not frame 0.** The incoming player has been decoding the whole window, so
finalize to its actual timeline position. Correct regardless of when finalize happens.

**Mid-transition re-press — v1 = ignore.** Today `CueManager.handle()` returns `None` while
`SWITCHING`; keep that. Simplest, no half-finished states. Known limitation: with a long
duration, mashing NEXT feels laggy (presses drop for ~duration). Acceptable for v1.

**Snap-interrupt — deferred.** The eventual behavior is "finalize the current transition
instantly, then start the next toward the new target." The seam is built to allow it cheaply
later: a transition is a discrete, finalizable unit in the engine, so adding snap is a localized
change (`CueManager.handle()` snap-then-advance instead of `None`, plus one
`engine.finalize_now()` call). No seam rework. Out of scope now.

---

## Section 4 — Failure handling during a transition

A transition adds a failure window: for ~duration the engine decodes **two** players and emits
`Blend(from, to, t)`. Either player can die mid-window. The rule: **a transition never keeps a
partial blend alive through a failure — any player death during the window resolves in one frame
to a clean single source.** This reuses the existing `_engage_fallback` / `_last_frame`
machinery; it adds no new failure path.

- **Incoming (`to`) player dies mid-transition** (throws in `frame_at`, or failed to start) →
  abort the transition immediately, drop to a `Single` instruction, and engage the fallback
  ladder (fallback video if available, else freeze on `_last_frame`). This is exactly today's
  dead-cue behavior. The switch is already committed in `CueManager`, so we do **not** try to
  return to A.
- **Outgoing (`from`) player dies mid-transition** → it is the cue we're *leaving*, so finalize
  the transition instantly to the incoming player (`Single(to)`). No fallback needed — the
  destination is healthy. A hard cut of the blend is acceptable here (the outgoing side is going
  away anyway).

Net effect: after any failure during the window there is exactly one live source on screen —
the destination if it's alive, otherwise the fallback ladder — and `complete_switch` still fires
so `CueManager` reaches `PLAYING` rather than getting stuck in `SWITCHING`.

---

## Section 5 — Testing strategy

Pure-unit tests (no hardware), consistent with the MVP/cue-recall approach. A fake/stub player
that returns scripted frames and can be told to raise `PlayerError` on demand drives the failure
cases deterministically; the clock is injected (`now` is already a parameter), so `t`
progression is tested without real time.

- **`t` progression + clamping:** `t` computed correctly from `now − start_time`; clamped to
  `[0, 1]`; `cut` finalizes on frame one (duration treated as 0).
- **Finalize behavior:** finalize-to-now (destination position, not frame 0); `complete_switch`
  fires exactly when `t` reaches 1; single-decoder rule restored after finalize (outgoing paused
  /released).
- **Render-instruction selection:** `PLAYING` → `Single`; during the window → `Blend` with the
  correct `mode` and a `t` in range; after finalize → `Single(destination)`.
- **Renderer blend math** (renderer-local, no players): `crossfade` alpha at representative `t`;
  `dip` shows through-black at the midpoint; `wipe` edge position tracks `t`; `cut` never
  produces a `Blend`.
- **Config parsing/validation:** `transition` / `duration` defaults when absent; unknown
  `transition` and non-positive `duration` error at load; `cut` reproduces today's behavior.
- **Live-key handling:** `t` cycles modes in order; `[` / `]` adjust duration by 0.1s and floor
  at 0.1s; adapter emits Commands only.
- **Failure handling (Section 4):** incoming dies mid-window → abort to fallback ladder,
  `complete_switch` still fires; outgoing dies mid-window → instant finalize to `Single(to)`;
  no partial blend persists after either.

Manual milestone verification against real videos: visually confirm each base mode; confirm flat
memory across many transitions (both-players-decoding window opens and closes cleanly); confirm a
deliberately-broken target cue during a transition lands on the fallback with no torn frame.

---

## Deferred to a later cycle (recorded, not designed here)

- **`tail_dissolve` type (self-contained, zero-decode):** on switch, freeze the on-screen frame
  (A-current, already held in the engine as `_last_frame`) and crossfade it to A's own **last
  frame** (A-last, a single still fetched once — grab it at preload time so it's ready), then
  hard-cut to B. During the crossfade window **no video decodes** — both blend endpoints are held
  stills — so it is cheaper than the base `crossfade` (B starts only at the cut, like a normal
  cut). Fits the render seam with **no renderer changes** (`Blend(A_current, A_last, t,
  crossfade)` → `Single(B)`), but it is a *new type*, not one of the four base modes: it is a
  two-phase transition with its own engine orchestration (no live decode during the window; the
  `to` endpoint is A's own last frame, not B). Structurally it is the same multi-phase shape as
  morph (blend into a bridge, then hand off to B) with A-last standing in for the pre-rendered
  clip — so it is a natural stepping stone to build right after the multi-phase orchestration
  lands, validating that shape before the clip machinery exists. (Variant, not chosen: let A keep
  *playing* and dissolve live motion into its frozen last frame — one live stream instead of
  zero.)
- **Morph-bridge type:** pre-rendered ComfyUI clip played as a bridge between an A→B pair;
  `morph_next` / `morph_prev` YAML per direction; morph preloading; the crossfade-in / clip-body
  / handoff-to-B orchestration; the authoring contract (morph[0] = A.last, morph[last] = B.first;
  resolution/fps/codec expectations; load-time validation warning). See
  `2026-07-09-transitions-design.md` Sections 4 and "Open items" for the captured brainstorm.
- **Snap-interrupt** of an in-flight transition (mid-transition re-press), including morph
  snap-abort. Seam is built to accept it later without rework.
