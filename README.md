# visualgen

Lightweight MIDI-controlled fullscreen video engine for live performance on macOS.  
Created for Interruptus.

## Install

    uv sync

## Run

    uv run visualgen path/to/show.yaml [--config path/to/config.yaml]

ESC quits. RIGHT/LEFT arrows switch cues (rehearsal convenience); MIDI is the
primary control surface. `--config` defaults to `config.yaml` next to the show file.

## Show file

    transition: crossfade   # optional show-wide default (see list below); default: cut
    duration: 0.8           # optional: blend length in seconds; default: 0.8 (ignored for cut)
    wrap: false             # optional: true wraps NEXT/PREVIOUS at the show edges
    show:
      - id: intro
        source: videos/intro.mp4
      - id: verse
        source: videos/verse.mp4
        transition: wipe    # optional per-cue override (used when switching AWAY from this cue)
        duration: 0.4       # optional per-cue override
      - id: sting
        source: videos/sting.mp4
        loop: false         # optional: play once, then hard-cut to the next cue (default: true = loop forever)

Paths are relative to the show file. All files are validated at startup.

### Transitions

The transition applied when you switch away from a cue. Set one show-wide with
the top-level `transition:` key, and/or override per cue. A cue without its own
`transition` inherits the show-wide default.

| name            | effect                                                            |
|-----------------|-------------------------------------------------------------------|
| `cut`           | instant hard cut (no blend); the default                          |
| `dip`           | dip through black between the two cues                            |
| `crossfade`     | fade the outgoing cue directly into the incoming one              |
| `wipe`          | wipe the incoming cue across over the outgoing one                |
| `tail_dissolve` | outgoing cue crossfades into a still of its own last frame, then hard-cuts to the incoming cue (one decoder throughout) |

`duration:` (show-wide or per cue) sets how long the blend lasts, in seconds; it
is ignored for `cut`.

A `loop: false` cue is **always** a hard cut, regardless of any `transition:` set
on it — it plays once and cuts to the next cue on its own.

### Live keys (rehearsal, session-only)

`t` cycles the current cue's transition (`cut → dip → crossfade → wipe →
tail_dissolve → cut`); `]` / `[` lengthen / shorten its duration by 0.1s. These
edits are not written back to the show file.

## Config file (all keys optional)

    midi:
      port: "IAC Driver Bus 1"          # default: first available port
      next:     {type: note_on, note: 60}
      previous: {type: note_on, note: 61}
    fallback: videos/safe_loop.mp4      # plays if a cue dies live

## Failure behavior

Startup problems (bad YAML, missing files) exit immediately with a clear
message — nothing fails mid-show that could have failed at launch. If a video
dies during the show, the fallback video plays (looping); you recognize it,
the audience sees an intentional visual, and NEXT/PREVIOUS keep working. With
no fallback configured, the last good frame freezes instead. MIDI disconnects
are logged and auto-reconnected.

## Soak testing

See `scripts/soak_switching.py` for the rapid-switching stress procedure.
