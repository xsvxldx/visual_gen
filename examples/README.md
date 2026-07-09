# examples/ — ready-to-edit run setup

Drop your clips into `clips/`, edit `show.yaml` to name them, then run the app.

## 1. Add clips + edit the cue list

Copy your videos into `examples/clips/` (H.264/HEVC `.mp4`/`.mov`, ProRes, etc.).
Edit `show.yaml` so each `source:` matches a real filename. Need at least 2 cues.
For the fallback, add a `clips/fallback.mp4` or edit/remove that line in `config.yaml`.

## 2. Run fullscreen

```bash
uv run visualgen examples/show.yaml
```

Controls: `→` next cue · `←` previous cue · `Esc` quit.
(Fullscreen on the primary monitor; `caffeinate` keeps the Mac awake, cleaned up on exit.)

## 3. MIDI soak (500 rapid switches)

First **uncomment** the `port: "visualgen-soak"` line in `config.yaml` (it's off by
default so normal runs don't warn about a missing port).

- **Terminal A:** `uv run python scripts/soak_switching.py 500`  (opens the port, then waits)
- **Terminal B:** `uv run visualgen examples/show.yaml`  (connects to the port)
- Back in **Terminal A**, press **Enter** to fire the switches.

The app should switch continuously without crashing, freezing, or leaking.

## Using a real controller instead

In `config.yaml` set `midi.port` to your device's name (or remove `port:` to use the
first input) and map pads to notes 60 (next) / 61 (previous). List device names with:

```bash
uv run python -c "import mido; print(mido.get_input_names())"
```
