#!/usr/bin/env python3
"""Generate the built-in music beds.

These are synthesised here rather than downloaded. A web page calling a track
"royalty free" is not a licence check, and slidecast is not going to hand you a
copyright risk on something you publish. Everything this writes is original and
free to use.

They are deliberately plain: slow, quiet, loopable pads meant to sit 20-30 dB
under a voice, not music anyone would listen to on its own. Drop your own
tracks into the same folder and they show up in the dropdown beside these.
"""

import subprocess
import sys
from pathlib import Path

LIBRARY = Path(__file__).parent / "music_library"
SECONDS = 60

# name -> (chord in Hz with relative levels, lowpass, tremolo rate/depth).
# ffmpeg will not accept a tremolo rate below 0.1 Hz.
BEDS = {
    "Calm pad": ([(130.81, 0.9), (196.00, 0.5), (261.63, 0.30), (329.63, 0.16)],
                 900, (0.11, 0.30)),
    "Warm drone": ([(110.00, 1.0), (164.81, 0.5), (220.00, 0.28), (261.63, 0.14)],
                   650, (0.10, 0.22)),
    "Soft pulse": ([(98.00, 1.0), (146.83, 0.45), (196.00, 0.26), (293.66, 0.12)],
                   1100, (0.75, 0.55)),
    "Open air": ([(174.61, 0.7), (261.63, 0.45), (349.23, 0.28), (523.25, 0.14)],
                 1800, (0.16, 0.26)),
    "Low hum": ([(87.31, 1.0), (130.81, 0.42), (174.61, 0.22), (220.00, 0.10)],
                500, (0.10, 0.18)),
}


def build(name, spec, ffmpeg="ffmpeg"):
    tones, cutoff, (rate, depth) = spec
    command = [ffmpeg, "-v", "error", "-y"]
    for freq, _ in tones:
        command += ["-f", "lavfi", "-i", f"sine=frequency={freq}:duration={SECONDS}"]
    parts = [f"[{i}]volume={level}[t{i}]" for i, (_, level) in enumerate(tones)]
    labels = "".join(f"[t{i}]" for i in range(len(tones)))
    # No fades: the bed is looped under the voice, and a fade would dip to
    # silence every minute.
    parts.append(
        f"{labels}amix=inputs={len(tones)}:normalize=0,"
        f"tremolo=f={rate}:d={depth},lowpass=f={cutoff},"
        f"aecho=0.8:0.85:420:0.25,"
        # Normalised to a normal music level, so the dB setting in the Music
        # panel means the same thing for these as for a commercial track.
        f"loudnorm=I=-16:TP=-1.5:LRA=7")
    out = LIBRARY / f"{name}.mp3"
    command += ["-filter_complex", ";".join(parts), "-c:a", "libmp3lame",
                "-b:a", "160k", str(out)]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"{name}: {result.stderr[-300:]}")
    return out


def main():
    LIBRARY.mkdir(exist_ok=True)
    ffmpeg = sys.argv[1] if len(sys.argv) > 1 else "ffmpeg"
    for name, spec in BEDS.items():
        path = build(name, spec, ffmpeg)
        print(f"  {name:12} {path.stat().st_size // 1024} KB")
    print(f"written to {LIBRARY}")


if __name__ == "__main__":
    main()
