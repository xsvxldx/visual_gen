# visualgen

Lightweight MIDI-controlled fullscreen video engine for live performance on macOS.

## Install

    uv sync

## Run

    uv run visualgen path/to/show.yaml [--config path/to/config.yaml]

ESC quits. RIGHT/LEFT arrows switch cues (rehearsal convenience); MIDI is the
primary control surface. `--config` defaults to `config.yaml` next to the show file.

## Show file

    wrap: false          # optional: true wraps NEXT/PREVIOUS at the show edges
    show:
      - id: intro
        source: videos/intro.mp4
      - id: verse
        source: videos/verse.mp4

Paths are relative to the show file. All files are validated at startup.

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
