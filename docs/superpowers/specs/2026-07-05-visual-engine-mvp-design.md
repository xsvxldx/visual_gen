# Visual Engine MVP — Architecture & Design

**Date:** 2026-07-05
**Status:** Approved design, pending implementation plan
**Source of truth for vision:** `AGENTS.md`

## Overview

A lightweight, performance-oriented live visual engine for macOS. The MVP delivers reliable fullscreen video playback controlled via MIDI: one video plays looping at a time, MIDI NEXT/PREVIOUS switch cues instantly, cues come from a YAML show file. No transitions, effects, or UI in the MVP.

This is a fresh design from `AGENTS.md`; it supersedes `docs/superpowers/specs/2026-07-04-video-engine-mvp-design.md` and `plan_gen.md`.

## Validated Decisions

| Topic | Decision |
|---|---|
| Starting point | Fresh design from `AGENTS.md` alone |
| Audio | Silent MVP. Clock is an abstraction (`Clock` interface) so an audio master clock can be added later without a rewrite. MVP clock = vsync-driven wall time. |
| Show boundaries | Configurable per show: `wrap: true\|false` in the show YAML. Default `false` (NEXT on last cue / PREVIOUS on first cue are ignored). |
| MIDI configuration | Separate config file (`config.yaml`), not the show file. Sensible defaults if absent. |
| Live failure mode | Play a **fallback video** (named in config) on any cue failure — recognizable to the operator, intentional-looking to the audience. If the fallback itself fails: freeze the last good frame. |
| Stack | Python 3.12 · GLFW · moderngl · PyAV · mido (python-rtmidi backend) · PyYAML · pytest |
| Switching semantics | Commands during SWITCHING are **dropped** (per AGENTS.md). SWITCHING lasts until the new adjacent cues are preloaded. |
| Transitions | Hard cut only in MVP. Architecture leaves the seam for GPU crossfades (see Future Seams). |

## Architecture

One process. Three kinds of threads:

- **Main thread** — owns the GL context, renders on vsync, runs the CueManager.
- **Decode threads** — one per active `VideoPlayer`.
- **MIDI listener thread** — translates MIDI messages to Commands.

Threads communicate only through queues and ring buffers; no shared mutable playback state.

```
MidiAdapter (mido, own thread)          [KeyboardAdapter — future]
        └── Command (NEXT | PREVIOUS) → thread-safe queue
                        ↓  drained once per frame by the main loop
                  CueManager        FSM: PLAYING | SWITCHING · edge policy · preload planning
                        ↓
                  PlaybackEngine    owns VideoPlayers: current (decoding) + adjacent (preloaded)
                        ↓  PTS-tagged frames via ring buffer
                  Renderer          moderngl: YUV planes → GPU shader → fullscreen quad
                        ↓
                  GLFW window       fullscreen, vsync on
```

### Modules (package `visualgen/`)

| Module | Single responsibility |
|---|---|
| `show.py` | `Show`/`Cue` dataclasses. YAML load + validation (unique ids, files exist, `wrap` flag). No playback logic. `Cue` is source-type agnostic (a `source` field; video is the only type for now). |
| `config.py` | Loads `config.yaml`: MIDI port + message mapping, fallback video path. Sane defaults if the file is absent. |
| `commands.py` | `Command` enum: `NEXT`, `PREVIOUS`. |
| `inputs/midi.py` | `MidiAdapter` thread: MIDI messages → Commands on a queue. Auto-reconnects on device drop. Never touches playback. |
| `cues.py` | `CueManager`: current index, FSM (`PLAYING`/`SWITCHING`), edge policy (wrap/ignore), decides which cues must be open/preloaded. No rendering, no MIDI, no file I/O. |
| `player.py` | `VideoPlayer`: PyAV decode thread → small ring buffer (2–3 frames). Seamless looping: seeks to 0 and pre-decodes the first frame before EOF is reached. |
| `engine.py` | `PlaybackEngine`: owns the players, enforces the preload contract, performs the atomic swap, activates the fallback player on failure. |
| `clock.py` | `Clock` interface. MVP ships `VsyncClock` (render-loop wall time). `AudioClock` can replace it later without touching players or renderer. |
| `render.py` | `Renderer`: moderngl context, uploads Y/U/V planes, YUV→RGB in the fragment shader (no CPU pixel conversion — "GPU after decoding"). Renders the texture it is given; knows nothing about cues, MIDI, or YAML. |
| `app.py` | Main loop wiring everything together. Spawns `caffeinate` so macOS never sleeps mid-show. |

### Preload contract

**Preloaded ≠ decoding.** A preloaded player has the file open, the decoder primed, and the **first frame already decoded** — then it sits idle. Only the current cue's decode thread runs continuously, so CPU load is ~1 decode stream even though up to 3 files are open (current + both neighbors, making PREVIOUS as instant as NEXT). This satisfies the AGENTS.md constraint that only the current and adjacent cue(s) are decoded.

### State machine

- **PLAYING** — normal playback; accepts `NEXT`/`PREVIOUS`.
- **SWITCHING** — swap in progress; **all commands dropped**. Entered on an accepted command; exited when the swap is done **and** the new adjacent cues are preloaded (~100–300 ms). Worst case for the operator: a very fast second press does nothing. The screen never degrades.

Transitions are atomic: the switch is a texture rebind between two vsync'd frames — frame N shows video A, frame N+1 shows video B's first frame. No black flash, no tearing, no partial state.

## Timing model

The render loop runs once per vsync (GLFW swap interval 1). Each tick:

1. Drain the command queue.
2. Tick the CueManager.
3. Ask the current player for the frame whose PTS matches the show clock.
4. Render it.

If decode falls behind, the last frame is repeated — the render loop **never blocks**. Looping is seamless: the player seeks to 0 and pre-decodes the first frame before EOF hits, so no hiccup at the loop point.

## File formats

### Show file (pure cue data)

```yaml
wrap: false        # optional, default false
show:
  - id: intro
    source: videos/intro.mp4
  - id: verse
    source: videos/verse.mp4
```

Extensible later with per-cue metadata (names, transition type/duration, effects, tags) without a format break.

### Config file (`config.yaml`)

```yaml
midi:
  port: "IAC Driver Bus 1"
  next:     {type: note_on, note: 60}
  previous: {type: note_on, note: 61}
fallback: videos/fallback_loop.mp4
```

All keys optional; defaults apply when absent (first available MIDI port, documented default notes, no fallback → freeze-frame only).

## Error handling

| Failure | Behavior |
|---|---|
| YAML parse error / missing cue file / bad config | Fail **at startup** with a clear message — never mid-show. |
| Cue dies live (decode error, unreadable file) | Switch to the **fallback video**, looping. Operator recognizes it; audience sees an intentional visual. NEXT/PREVIOUS keep working. The fallback player is opened and preloaded at startup (first frame ready), so the switchover is as instant as a normal cue switch. |
| Fallback missing or fails | Freeze the last good frame. |
| MIDI device disconnect | Log + auto-reconnect loop; playback unaffected. |

All live errors are non-fatal. The process only exits on startup validation failure or operator quit.

## Testing strategy

- **pytest units** (no hardware): Show/config parsing + validation, CueManager FSM (edges, wrap, drop-during-SWITCHING), MIDI→Command mapping with synthetic mido messages.
- **Manual milestone verification**: player/renderer verified by running each milestone against real videos.
- **Measurable stability criteria** (final milestone): multi-hour looped playback with flat memory usage; hundreds of rapid MIDI switches without a visual glitch; kill a file mid-show → fallback engages, no crash.

## Milestones (each one a runnable app)

1. **Fullscreen window** — GLFW + moderngl, solid color quad, vsync on, ESC quits, stable 60 fps, `caffeinate` active.
2. **Single video playback** — one hardcoded file, seamless indefinite loop, YUV→RGB on GPU.
3. **Show + config loading** — YAML parsing/validation, first cue plays, clear startup errors.
4. **CueManager + keyboard input** — FSM with a temporary keyboard adapter (arrow keys) to test switching without MIDI hardware.
5. **Preloading + instant switch** — adjacent cues preloaded (first frame ready); NEXT/PREVIOUS swap in ≤ 1 frame.
6. **MIDI control** — `MidiAdapter` with config mapping; live disconnect/reconnect works.
7. **Failure path** — fallback video on cue death; freeze-frame as final net.
8. **Stability soak** — the measurable criteria above.

## Future seams (designed for, not built)

- **Transitions (roadmap #1):** the SWITCHING state is the future transition window (today it is one frame long). Both players are already alive during a switch; a crossfade is a second sampler + one `mix()` uniform in the fragment shader. Touches two files, rewrites nothing.
- **Audio:** swap `VsyncClock` for an `AudioClock` behind the `Clock` interface.
- **New input adapters** (keyboard, OSC, Stream Deck): new emitters onto the same command queue.
- **Live effect control (roadmap #6):** multi-channel MIDI controllers (notes, CCs, any channel) map to future commands with payloads (e.g. `SET_PARAM(effect, value)`) flowing down the same queue to a renderer-side effect chain. `Command` grows from a plain enum to payload-carrying messages — additive, no rewrite.
- **New cue types** (image sequence, webcam, shader, Syphon, NDI): `Cue.source` is type-agnostic; new player implementations slot in behind the `PlaybackEngine`.

## Out of scope for MVP

Transitions, effects, shaders beyond YUV→RGB, OSC, UI, multiple simultaneous sources — per the AGENTS.md roadmap, none of these before the MVP is stable.

## Dependencies

`av`, `moderngl`, `glfw`, `mido`, `python-rtmidi`, `PyYAML`, `numpy` · Python 3.12 · managed with `uv`.
