"""Fires rapid NEXT/PREVIOUS MIDI notes at visualgen through a virtual port.

Usage: run `uv run visualgen <show.yaml>` with config.yaml naming port
"visualgen-soak", then run `uv run python scripts/soak_switching.py 500`.
"""

import random
import sys
import time

import mido


def main() -> int:
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 500
    with mido.open_output("visualgen-soak", virtual=True) as port:
        print("virtual port 'visualgen-soak' open; start visualgen now, then press Enter")
        input()
        for i in range(count):
            note = random.choice([60, 61])
            port.send(mido.Message("note_on", note=note, velocity=100))
            time.sleep(random.uniform(0.02, 0.4))
            if (i + 1) % 50 == 0:
                print(f"{i + 1}/{count} switches sent")
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
