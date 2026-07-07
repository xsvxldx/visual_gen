# AGENTS.md

This file is the lead document for the project. Design and planning documents derive from it:

- **Approved design spec:** `docs/superpowers/specs/2026-07-05-visual-engine-mvp-design.md`
- **Implementation plan:** `docs/superpowers/plans/2026-07-05-visual-engine-mvp.md`

Decisions validated on 2026-07-05 that refine this document:

- Silent MVP; timing behind a `Clock` abstraction so an audio master clock can be added later.
- Show edges configurable per show (`wrap: true|false`), default `false` (ignore at edges).
- MIDI port/mapping lives in a separate `config.yaml`, not the show file; defaults apply if absent.
- Live failure mode: a fallback video named in config plays on any cue failure (preloaded at startup); freeze last good frame as the final safety net.
- Stack: Python 3.12 · GLFW · moderngl · PyAV · mido/python-rtmidi · PyYAML · uv.

---

# Project Vision

This project is a lightweight, performance-oriented live visual engine for macOS.

The initial goal is to provide reliable fullscreen video playback for live performances, controlled via MIDI. The long-term vision is to evolve into a programmable visual engine capable of handling multiple media sources, GPU effects, and additional control protocols.

The system prioritizes reliability, deterministic behavior, and low resource usage over feature count.

---

# MVP

The first milestone must support:

- Fullscreen playback.
- One active video displayed at a time.
- Current video loops indefinitely.
- MIDI NEXT advances to the next cue.
- MIDI PREVIOUS returns to the previous cue.
- Switching is instantaneous (no transition yet).
- During a switch, additional commands are ignored.
- The next cue should always be preloaded.
- Videos are defined by a YAML show file.

Do not implement transitions, effects, or UI until the MVP is stable.

---

# Guiding Principles

## Reliability first

This application is intended for live performances.

Never sacrifice stability for architectural cleverness.

A simple, robust solution is preferred over a complex one.

---

## GPU after decoding

Video decoding happens on the CPU (PyAV / FFmpeg).

After decoding, all rendering should occur on the GPU.

Avoid unnecessary CPU image processing.

---

## Separation of Responsibilities

Each module should have a single responsibility.

Suggested architecture:

Input Adapters
    ↓
Commands
    ↓
Cue Manager
    ↓
Playback Engine
    ↓
Renderer
    ↓
OpenGL Output

Modules should communicate through well-defined interfaces.

Avoid tight coupling.

---

# Core Concepts

## Show

Represents an ordered collection of cues loaded from YAML.

A Show contains no playback logic.

---

## Cue

A Cue represents one playable source.

Initially this source is always a video file.

Future cue types may include:

- Image sequence
- Webcam
- Shader
- Syphon
- NDI
- Procedural generator

Do not design Cue around MP4-specific behavior.

---

## CueManager

Responsible for:

- Current cue
- Next cue
- Previous cue
- Preloading
- Ignoring commands while switching

No rendering logic.

No MIDI logic.

---

## Renderer

Responsible only for displaying frames.

Renderer must not know:

- playlists
- MIDI
- YAML
- cue ordering

It only renders textures.

---

## Input Layer

Input devices should never directly manipulate playback.

They emit Commands.

Initial commands:

- NEXT
- PREVIOUS

Possible future adapters:

- MIDI
- Keyboard
- OSC
- Web UI
- Stream Deck

---

# State Machine

Playback is modeled as a finite state machine.

States:

- PLAYING
- SWITCHING

Transitions are atomic.

While SWITCHING:

- ignore NEXT
- ignore PREVIOUS

---

# Show Configuration

Shows are defined by YAML.

Example:

show:
  - id: intro
    source: videos/intro.mp4

  - id: verse
    source: videos/verse.mp4

The YAML format should be extensible with future metadata such as:

- cue names
- transition types
- transition duration
- effects
- tags

---

# Performance Constraints

- Only the current cue and the adjacent cue(s) should be decoded.
- Avoid loading an entire show into memory.
- Minimize RAM usage.
- Minimize GPU uploads.
- Target smooth playback on a modern MacBook at 720p initially.
- Design to scale to 1080p later.

---

# Future Roadmap (Not MVP)

After the MVP is complete and stable:

1. GPU crossfades
2. Shader pipeline
3. Effect chaining
4. OSC input
5. Keyboard shortcuts
6. Live parameter control
7. Multiple media source types
8. Node-based processing graph

Do not implement roadmap items before the MVP is complete unless explicitly requested.

---

# Development Philosophy

Favor incremental development.

Each milestone should produce a working application.

Suggested milestones:

1. Fullscreen window
2. Single video playback
3. YAML show loading
4. CueManager
5. MIDI control
6. Cue preloading
7. Instant switching
8. Stability testing

Avoid building infrastructure that is not immediately needed.
