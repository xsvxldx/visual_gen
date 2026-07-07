# CLAUDE.md

**Read `AGENTS.md` first — it is the lead document for this project** (vision, MVP scope, guiding principles, architecture boundaries, roadmap). Everything else derives from it:

- Approved design spec: `docs/superpowers/specs/2026-07-05-visual-engine-mvp-design.md`
- Implementation plan: `docs/superpowers/plans/2026-07-05-visual-engine-mvp.md`

Ground rules from AGENTS.md that always apply:

- Reliability over cleverness — this runs live performances.
- Do not implement roadmap items (transitions, effects, OSC, UI) before the MVP is stable unless explicitly requested.
- Respect module boundaries: inputs emit Commands only; CueManager has no rendering/MIDI; Renderer only draws textures.
- Python 3.12, dependencies managed with `uv` (`uv sync`, `uv run pytest`).
