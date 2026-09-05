#!/usr/bin/env python3
"""Local web UI for slidecast. Run it, open http://localhost:8770, drop files in."""

import base64
import hashlib
import json
import threading
import time
import subprocess
import traceback
import wave
import webbrowser
from argparse import Namespace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import slidecast as d
import kokoro_docker as kokoro
import capcut_export as capcut

HERE = Path(__file__).parent
WORK = HERE / "workspace"
PORT = 8770

# Both survive a refresh, and a restart of this server: the inputs you picked
# and the last video that finished building.
SESSION = WORK / "session.json"
RESULT = WORK / "result.json"

# The voice is the slow part of a build. Generating it once lets the music
# preview and the build that follows reuse it instead of synthesizing twice.
CACHE = WORK / "voice_cache"
MUSIC = WORK / "music"
# Beds shipped with slidecast, plus anything you drop in beside them.
LIBRARY = HERE / "music_library"


def voice_key(payload):
    """Anything that changes the speech changes the key.

    Numbers are normalised: a speed of 1 and 1.0 are the same voice, and
    without this the cache misses and re-synthesizes for no reason.
    """
    def token(value):
        try:
            return f"{float(value):.6f}"
        except (TypeError, ValueError):
            return str(value)

    o = payload.get("options", {})
    parts = [payload.get("script", "")] + [token(o.get(k)) for k in
             ("voice", "speed", "lead_in", "tail", "gap_sentence", "gap_slide",
              "chunk")]
    return hashlib.sha1(json.dumps(parts).encode("utf-8")).hexdigest()


def cached_voice(key):
    meta, wav = CACHE / "meta.json", CACHE / "voice.wav"
    if not (meta.exists() and wav.exists()):
        return None
    info = json.loads(meta.read_text(encoding="utf-8"))
    if info.get("key") != key:
        return None
    with wave.open(str(wav), "rb") as w:
        frames = w.readframes(w.getnframes())
    return (frames, [tuple(c) for c in info["cues"]],
            info["slide_ends"], info["total"])


def store_voice(key, audio):
    frames, cues, slide_ends, total = audio
    CACHE.mkdir(parents=True, exist_ok=True)
    d.write_wav(CACHE / "voice.wav", frames)
    (CACHE / "meta.json").write_text(json.dumps(
        {"key": key, "cues": cues, "slide_ends": slide_ends, "total": total}),
        encoding="utf-8")

VOICES = ["af_sky", "af_heart", "af_bella", "af_nicole", "af_sarah", "af_nova",
          "af_aoede", "af_kore", "af_jessica", "af_river", "af_alloy",
          "am_adam", "am_michael", "am_echo", "am_eric", "am_liam", "am_onyx",
          "am_puck", "am_fenrir", "am_santa", "am_every",
          "bf_emma", "bf_isabella", "bf_alice", "bf_lily"]

JOB = {"running": False, "kind": None, "log": [], "error": None, "result": None}


def reset_job(kind="build"):
    JOB.update(running=True, kind=kind, log=[], error=None, result=None)


def log(message):
    JOB["log"].append(str(message))


def write_inputs(payload):
    WORK.mkdir(exist_ok=True)
    for stale in ("video-presentation.html", "voiceover.txt"):
        (WORK / stale).unlink(missing_ok=True)
    (WORK / "video-presentation.html").write_text(payload["deck"], encoding="utf-8")
    (WORK / "voiceover.txt").write_text(payload["script"], encoding="utf-8")
    assets_dir = WORK / "assets"
    assets_dir.mkdir(exist_ok=True)
    mapping = {}
    for name, b64 in payload.get("assets", {}).items():
        safe = name.replace("\\", "/").split("/")[-1]
        target = assets_dir / safe
        target.write_bytes(base64.b64decode(b64.split(",", 1)[-1]))
        mapping[name] = str(target.resolve())
    return mapping


def job(payload):
    try:
        mapping = write_inputs(payload)
        assets_file = WORK / "assets.json"
        assets_file.write_text(json.dumps(mapping), encoding="utf-8")
        o = payload.get("options", {})
        opts = Namespace(
            deck=str(WORK / "video-presentation.html"),
            script=str(WORK / "voiceover.txt"),
            out=str(WORK / "video.mp4"),
            build=str(WORK / "build"),
            assets=str(assets_file),
            voice=o.get("voice", "af_sky"),
            speed=float(o.get("speed", 1.0)),
            kokoro=o.get("kokoro", d.KOKORO_URL),
            lead_in=float(o.get("lead_in", 0.6)),
            tail=float(o.get("tail", 1.2)),
            gap_sentence=float(o.get("gap_sentence", 0.28)),
            gap_slide=float(o.get("gap_slide", 1.1)),
            fade=float(o.get("fade", 0.45)),
            fps=int(o.get("fps", 30)),
            font=o.get("font", "Arial"),
            font_size=int(o.get("font_size", 54)),
            outline=int(o.get("outline", 4)),
            margin_v=int(o.get("margin_v", 20)),
            max_chars=int(o.get("max_chars", 56)),
            min_sub=float(o.get("min_sub", 0.9)),
            bold=bool(o.get("bold", False)),
            text_colour=o.get("text_colour", "#ffffff"),
            outline_colour=o.get("outline_colour", "#000000"),
            align_words=bool(o.get("align_words", False)) or bool(o.get("highlight", False)),
            highlight=bool(o.get("highlight", False)),
            highlight_colour=o.get("highlight_colour", "#FFD400"),
            whisper=o.get("whisper", "base"),
            chunk=o.get("chunk", "slide"),
            no_subs=bool(o.get("no_subs", False)),
            no_fades=not bool(o.get("with_fades", True)),
            music=(str(next(iter(sorted(MUSIC.glob("*"))))) 
                   if MUSIC.exists() and any(MUSIC.glob("*")) else None),
            music_db=float(o.get("music_db", -20.0)),
            chrome=None,
            ffmpeg=o.get("ffmpeg", "ffmpeg"),
        )
        if opts.gap_slide < 2 * opts.fade:
            raise RuntimeError("Slide gap must be at least twice the fade length, "
                               "or the fade would cover speech.")
        # Bring Kokoro up rather than failing halfway through the build.
        state = kokoro.ensure(log)
        if not state["ok"]:
            raise RuntimeError(state["error"])
        key = voice_key(payload)
        audio = cached_voice(key)
        if audio:
            log("using the voice already generated, no need to synthesize again")
        else:
            log("generating speech")
            audio = d.build_audio(d.parse_script(opts.script), opts, log)
            store_voice(key, audio)
        result = d.run(opts, log, audio=audio)
        JOB["result"] = result
        RESULT.write_text(json.dumps({**result, "built_at": time.time(),
                                      "saved": False}), encoding="utf-8")
    except Exception as exc:
        JOB["error"] = f"{exc}"
        log("ERROR: " + str(exc))
        traceback.print_exc()
    finally:
        JOB["running"] = False


def voice_job(payload):
    """Generate only the speech, so the music can be judged against it."""
    try:
        WORK.mkdir(exist_ok=True)
        (WORK / "voiceover.txt").write_text(payload["script"], encoding="utf-8")
        o = payload.get("options", {})
        opts = Namespace(
            script=str(WORK / "voiceover.txt"),
            voice=o.get("voice", "af_sky"), speed=float(o.get("speed", 1.0)),
            kokoro=o.get("kokoro", d.KOKORO_URL),
            lead_in=float(o.get("lead_in", 0.6)), tail=float(o.get("tail", 1.2)),
            gap_sentence=float(o.get("gap_sentence", 0.28)),
            gap_slide=float(o.get("gap_slide", 1.1)),
            chunk=o.get("chunk", "slide"))
        key = voice_key(payload)
        if cached_voice(key):
            log("that voice is already generated")
            JOB["result"] = {"cached": True}
            return
        state = kokoro.ensure(log)
        if not state["ok"]:
            raise RuntimeError(state["error"])
        slides = d.parse_script(opts.script)
        sentences = sum(len(d.split_sentences(s["paragraph"])) for s in slides)
        log(f"{len(slides)} slides, {sentences} sentences" +
            (f", sent to Kokoro {len(slides)} slides at a time"
             if opts.chunk == "slide" else ", sent one sentence at a time"))
        audio = d.build_audio(slides, opts, log)
        store_voice(key, audio)
        JOB["result"] = {"cached": False, "total": audio[3]}
        log(f"voice ready: {audio[3]:.1f}s")
    except Exception as exc:
        JOB["error"] = str(exc)
        log("ERROR: " + str(exc))
        traceback.print_exc()
    finally:
        JOB["running"] = False


def media_seconds(path):
    """Length of an audio file, so it can be trimmed to the video."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def current_music():
    if MUSIC.is_dir():
        for track in sorted(MUSIC.glob("*")):
            return track
    return None


def mean_db(path):
    """Average level of a file, so the music can be reported relative to the voice."""
    result = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True)
    for line in result.stderr.splitlines():
        if "mean_volume:" in line:
            try:
                return float(line.split("mean_volume:")[1].split("dB")[0])
            except ValueError:
                return None
    return None


def measured(path, cache_file):
    """mean_db is a full decode, so remember it per file."""
    key = f"{path.name}:{path.stat().st_size}"
    if cache_file.exists():
        info = json.loads(cache_file.read_text(encoding="utf-8"))
        if info.get("key") == key:
            return info.get("mean")
    mean = mean_db(path)
    cache_file.write_text(json.dumps({"key": key, "mean": mean}), encoding="utf-8")
    return mean


def mix_preview(music_db):
    """Voice plus music at the chosen level, as an MP3 to listen to."""
    voice = CACHE / "voice.wav"
    if not voice.exists():
        raise RuntimeError("Generate the voice first.")
    track = next(iter(sorted(MUSIC.glob("*"))), None) if MUSIC.exists() else None
    out = WORK / "preview.mp3"
    command = ["ffmpeg", "-y", "-i", str(voice)]
    if track:
        command += ["-stream_loop", "-1", "-i", str(track),
                    "-filter_complex",
                    f"[1:a]volume={d.gain(music_db):.6f}[bed];"
                    f"[0:a][bed]amix=inputs=2:duration=first:normalize=0[out]",
                    "-map", "[out]"]
    command += ["-c:a", "libmp3lame", "-b:a", "192k", str(out)]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError("ffmpeg failed: " + result.stderr[-800:])

    under = None
    if track:
        voice_mean = measured(voice, CACHE / "voice_level.json")
        music_mean = measured(track, MUSIC.parent / "music_level.json")
        if voice_mean is not None and music_mean is not None:
            under = round(voice_mean - (music_mean + music_db), 1)
    return {"ok": True, "music": bool(track), "db": music_db, "under": under}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, code, body, ctype="application/json"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, ctype):
        if not Path(path).exists():
            return self.send(404, json.dumps({"error": "not built yet"}))
        data = Path(path).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Accept-Ranges", "none")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        route = self.path.split("?")[0]
        if route == "/":
            return self.send(200, (HERE / "ui.html").read_text(encoding="utf-8"),
                             "text/html; charset=utf-8")
        if route.endswith(".svg"):
            asset = HERE / Path(route).name
            return self.send_file(asset, "image/svg+xml")
        if route == "/voices":
            return self.send(200, json.dumps({"voices": VOICES}))
        if route == "/status":
            return self.send(200, json.dumps(JOB))
        if route == "/kokoro":
            return self.send(200, json.dumps(kokoro.status()))
        if route == "/session":
            return self.send(200, SESSION.read_text(encoding="utf-8")
                             if SESSION.exists() else json.dumps({}))
        if route == "/last":
            # Only claim a previous build if its MP4 is actually still there.
            if RESULT.exists() and (WORK / "video.mp4").exists():
                return self.send(200, RESULT.read_text(encoding="utf-8"))
            return self.send(200, json.dumps({}))
        if route == "/video":
            # The player also fetches this, so only an explicit download counts
            # as saved. ?save=1 is what the Download button uses.
            if "save=1" in self.path and RESULT.exists():
                try:
                    info = json.loads(RESULT.read_text(encoding="utf-8"))
                    info["saved"] = True
                    RESULT.write_text(json.dumps(info), encoding="utf-8")
                except (ValueError, OSError):
                    pass
            return self.send_file(WORK / "video.mp4", "video/mp4")
        if route == "/preview.mp3":
            return self.send_file(WORK / "preview.mp3", "audio/mpeg")
        if route == "/capcut/folder":
            return self.send(200, json.dumps(capcut.state()))
        if route == "/voice/file":
            return self.send_file(CACHE / "voice.wav", "audio/wav")
        if route == "/music/file":
            track = current_music()
            if not track:
                return self.send(404, json.dumps({"error": "no track loaded"}))
            return self.send_file(track, "audio/mpeg")
        if route == "/music/library":
            tracks = sorted(f.name for f in LIBRARY.glob("*")
                            if f.suffix.lower() in (".mp3", ".wav", ".m4a", ".ogg", ".flac"))                      if LIBRARY.is_dir() else []
            return self.send(200, json.dumps({"tracks": tracks, "folder": str(LIBRARY)}))
        if route == "/music/state":
            track = next(iter(sorted(MUSIC.glob("*"))), None) if MUSIC.exists() else None
            return self.send(200, json.dumps(
                {"name": track.name if track else None,
                 "voice_ready": (CACHE / "voice.wav").exists()}))
        if route == "/subs":
            return self.send_file(WORK / "build" / "subs.srt", "text/plain; charset=utf-8")
        return self.send(404, json.dumps({"error": "no such route"}))

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")
        route = self.path.split("?")[0]

        if route == "/inspect":
            WORK.mkdir(exist_ok=True)
            probe = WORK / "_probe.html"
            probe.write_text(payload.get("deck", ""), encoding="utf-8")
            slides = d.count_slides(payload.get("deck", ""))
            missing = d.missing_assets(probe)
            script = payload.get("script") or ""
            parsed = []
            if script.strip():
                tmp = WORK / "_probe.txt"
                tmp.write_text(script, encoding="utf-8")
                parsed = d.parse_script(tmp)
            return self.send(200, json.dumps({
                "slides": slides,
                "missing": missing,
                # No markup means the plain voiceover-script.md was uploaded by
                # mistake: it builds fine but Kokoro mispronounces dbt, AI, query.
                "has_markup": bool(d.MARKUP.search(script)),
                "script_slides": len(parsed),
                "sentences": [len(d.split_sentences(s["paragraph"])) for s in parsed],
                "labels": [s["label"] for s in parsed],
            }))

        if route == "/capcut/folder":
            # Opens the OS folder chooser; blocks until the user picks.
            return self.send(200, json.dumps(capcut.pick_folder()))

        if route == "/capcut":
            if not RESULT.exists():
                return self.send(400, json.dumps({"error": "Build a video first."}))
            r = json.loads(RESULT.read_text(encoding="utf-8"))
            if "pngs" not in r:
                return self.send(400, json.dumps(
                    {"error": "That build predates CapCut export. Build again."}))
            try:
                out = capcut.write(
                    payload.get("name") or "slidecast",
                    r["pngs"], r["slide_durations"],
                    [tuple(c) for c in r["voice_clips"]],
                    [tuple(e) for e in r["events"]],
                    r["duration"],
                    with_fades=bool(payload.get("with_fades", True)),
                    overwrite=bool(payload.get("overwrite", False)),
                    music=str(track) if (track := current_music()) else None,
                    music_duration=media_seconds(track) if track else 0.0,
                    music_volume=d.gain(float(payload.get("music_db", -20.0))),
                    log=lambda m: None)
                return self.send(200, json.dumps({"ok": True, **out}))
            except Exception as exc:
                traceback.print_exc()
                return self.send(200, json.dumps({"ok": False, "error": str(exc)}))

        if route == "/voice":
            if JOB["running"]:
                return self.send(409, json.dumps({"error": "something is already running"}))
            reset_job("voice")
            threading.Thread(target=voice_job, args=(payload,), daemon=True).start()
            return self.send(200, json.dumps({"started": True}))

        if route == "/music":
            MUSIC.mkdir(parents=True, exist_ok=True)
            for old in MUSIC.glob("*"):
                old.unlink()
            name = (payload.get("name") or "music.mp3").replace("\\", "/").split("/")[-1]
            (MUSIC / name).write_bytes(
                base64.b64decode(payload["data"].split(",", 1)[-1]))
            return self.send(200, json.dumps({"ok": True, "name": name}))

        if route == "/music/pick":
            name = (payload.get("name") or "").replace("\\", "/").split("/")[-1]
            source = LIBRARY / name
            if not name or not source.is_file():
                return self.send(200, json.dumps({"ok": False, "error": "No such track."}))
            MUSIC.mkdir(parents=True, exist_ok=True)
            for old in MUSIC.glob("*"):
                old.unlink()
            (MUSIC / source.name).write_bytes(source.read_bytes())
            (WORK / "music_level.json").unlink(missing_ok=True)
            return self.send(200, json.dumps({"ok": True, "name": source.name}))

        if route == "/music/clear":
            if MUSIC.exists():
                for old in MUSIC.glob("*"):
                    old.unlink()
            return self.send(200, json.dumps({"ok": True}))

        if route == "/preview":
            try:
                return self.send(200, json.dumps(
                    mix_preview(float(payload.get("music_db", -45)))))
            except Exception as exc:
                return self.send(200, json.dumps({"ok": False, "error": str(exc)}))

        if route == "/kokoro/start":
            # If the startup thread already holds the lock, wait for it rather
            # than telling the user their click failed.
            result = kokoro.ensure(log=lambda m: None)
            if not result.get("ok") and "already being started" in str(result.get("error")):
                for _ in range(60):
                    time.sleep(2)
                    if kokoro.api_alive():
                        result = {"ok": True, "action": "started"}
                        break
                else:
                    result = {"ok": False,
                              "error": "Kokoro was already being started but has "
                                       "not answered yet. Give it a moment."}
            return self.send(200, json.dumps(result))

        if route == "/session":
            WORK.mkdir(exist_ok=True)
            SESSION.write_text(json.dumps(payload), encoding="utf-8")
            return self.send(200, json.dumps({"saved": True}))

        if route == "/build":
            if JOB["running"]:
                return self.send(409, json.dumps({"error": "a build is already running"}))
            reset_job()
            threading.Thread(target=job, args=(payload,), daemon=True).start()
            return self.send(200, json.dumps({"started": True}))

        return self.send(404, json.dumps({"error": "no such route"}))


def main():
    # Warm Kokoro in the background so it is ready by the time files are picked.
    # Start a stopped container, but never launch Docker Desktop itself here.
    # Restarting this server should not drag a Docker the user deliberately
    # quit back up, and repeated launches race each other.
    threading.Thread(target=kokoro.ensure,
                     kwargs={"log": print, "may_start_desktop": False},
                     daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://localhost:{PORT}"
    print(f"slidecast UI on {url}   (Ctrl+C to stop)")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    server.serve_forever()


if __name__ == "__main__":
    main()
