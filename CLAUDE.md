# CLAUDE.md

**Read `AGENTS.md` first — it is the lead document for this project** (vision, MVP scope, guiding principles, architecture boundaries, roadmap). Everything else derives from it:

- Approved design spec: `docs/superpowers/specs/2026-07-05-visual-engine-mvp-design.md`
- Implementation plan: `docs/superpowers/plans/2026-07-05-visual-engine-mvp.md`

Post-MVP designs (see each file for status):
- Cue recall (undo-last-switch): `docs/superpowers/specs/2026-07-09-cue-recall-design.md` — **DONE & merged** (plan `docs/superpowers/plans/2026-07-09-cue-recall.md`); keyboard `DOWN` resumes the just-left cue at position, toggles A/B.
- Transitions **framework** (base blends): `docs/superpowers/specs/2026-07-10-transitions-framework-design.md` — **DONE & merged** (2026-07-10, operator-approved, 91 tests); `Single`/`Blend` render seam, cut/dip/crossfade/wipe, timed switching, YAML+live-key config, per-frame letterboxing. Live keys: `t` cycles mode, `[`/`]` adjust duration.
- Transitions **tail_dissolve**: `docs/superpowers/specs/2026-07-11-tail-dissolve-design.md` — **DONE & operator-approved** (2026-07-15, 103 tests, manual pass on real footage passed); 5th `TransitionMode`, live A crossfades into a still of its own last frame then hard-cuts to B, one decoder throughout. `t`-cycle order: cut → dip → crossfade → wipe → tail_dissolve → cut.
- Transitions **morph + snap-interrupt** (still deferred): `docs/superpowers/specs/2026-07-09-transitions-design.md` Sections 4–5 unfinished — ComfyUI pre-rendered bridge clips + mid-transition snap.

Current status lives in the plan's **Progress** section and in auto-memory `visualgen-mvp-progress`. MVP is complete and the switching soak passed; cue recall and the transitions framework are merged (91 tests).

Ground rules from AGENTS.md that always apply:

- Reliability over cleverness — this runs live performances.
- Do not implement roadmap items (transitions, effects, OSC, UI) before the MVP is stable unless explicitly requested.
- Respect module boundaries: inputs emit Commands only; CueManager has no rendering/MIDI; Renderer only draws textures.
- Python 3.12, dependencies managed with `uv` (`uv sync`, `uv run pytest`).
