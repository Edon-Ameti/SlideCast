#!/usr/bin/env python3
"""Drop folder: every folder put in inbox/ is built without opening the UI.

A folder is ready when it holds one deck (.html) and one script (.txt) and
nothing in it has changed for a few seconds, so a copy still in progress is
not built half-finished. The video, subtitles, chapters and thumbnail are
written into that same folder. A failure writes error.txt instead. Either way
the folder is not built again; delete video.mp4 or error.txt to rebuild it.

An optional settings.json changes any setting, using the command line's
names: {"voice": "am_adam", "format": "short", "music": "bed.mp3"}.
"""

import json
import shutil
import sys
import time
from pathlib import Path

import kokoro_docker as kokoro
import slidecast as d

INBOX = Path(__file__).parent / "inbox"
SETTLE_SECONDS = 5
POLL_SECONDS = 5
# Settings that name a file, read relative to the folder they sit in.
PATH_SETTINGS = ("music", "assets", "pronunciations")
OUTPUTS = ("error.txt", "video-chapters.txt")


def ready_folders(inbox, now=None, settle=SETTLE_SECONDS):
    """(folder, deck, script) for each folder waiting to be built."""
    now = now or time.time()
    for folder in sorted(p for p in inbox.iterdir() if p.is_dir()):
        if (folder / "video.mp4").exists() or (folder / "error.txt").exists():
            continue
        decks = list(folder.glob("*.html"))
        scripts = [s for s in folder.glob("*.txt") if s.name not in OUTPUTS]
        if len(decks) != 1 or len(scripts) != 1:
            continue
        newest = max(f.stat().st_mtime for f in folder.rglob("*") if f.is_file())
        if now - newest < settle:
            continue
        yield folder, decks[0], scripts[0]


def options_for(folder, deck, script):
    opts = d.build_parser().parse_args(
        [str(deck), str(script), "-o", str(folder / "video.mp4"),
         "--build", str(folder / "build"), "--kokoro", kokoro.convert_url()])
    settings = folder / "settings.json"
    if settings.exists():
        for key, value in json.loads(settings.read_text(encoding="utf-8")).items():
            name = key.lstrip("-").replace("-", "_")
            if not hasattr(opts, name) or name in ("deck", "script", "out", "build"):
                raise ValueError(f"settings.json: there is no setting called {key!r}")
            if name in PATH_SETTINGS and value and not Path(value).is_absolute():
                value = str(folder / value)
            setattr(opts, name, value)
    return d.finish_options(opts)


def build_folder(folder, deck, script, log=print):
    say = lambda message: log(f"[{folder.name}] {message}")
    try:
        state = kokoro.ensure(say)
        if not state["ok"]:
            raise RuntimeError(state["error"])
        d.run(options_for(folder, deck, script), say)
        shutil.copyfile(folder / "build" / "subs.srt", folder / "video.srt")
        say("finished")
    except Exception as exc:
        (folder / "error.txt").write_text(f"{exc}\n", encoding="utf-8")
        say(f"failed, see error.txt: {exc}")


def main():
    once = "--once" in sys.argv[1:]
    INBOX.mkdir(exist_ok=True)
    print(f"Watching {INBOX}" + ("" if once else "   (Ctrl+C to stop)"))
    while True:
        for folder, deck, script in ready_folders(INBOX):
            build_folder(folder, deck, script)
        if once:
            return
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
