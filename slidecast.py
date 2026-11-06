#!/usr/bin/env python3
"""SlideCast - HTML slide deck + Kokoro voiceover script -> finished MP4 with burned subtitles.

Each slide is held on screen for exactly as long as its narration, with a fade
through black between slides. Subtitle text comes from the voiceover script
itself, so it carries real capitalisation and punctuation.
"""

import argparse
import array
import hashlib
import io
import json
import math
import re
import shutil
import subprocess
import wave
from pathlib import Path
from urllib import request as urlrequest

KOKORO_URL = "http://localhost:7860/tts/convert"
SAMPLE_RATE = 24000

# The shapes a video can be made in. Slides are rendered at the shape itself,
# so each fills its frame with no bars. The subtitle defaults suit the frame:
# a Short is narrow, and its bottom is covered by the app's own buttons and
# caption, so its subtitles sit higher.
FORMATS = {
    "video":    {"size": (1920, 1080), "font_size": 54, "max_chars": 56, "margin_v": 20,
                 "label": "Regular video: YouTube, websites, presentations"},
    "short":    {"size": (1080, 1920), "font_size": 62, "max_chars": 26, "margin_v": 380,
                 "label": "Vertical: YouTube Shorts, TikTok, Instagram Reels"},
    "square":   {"size": (1080, 1080), "font_size": 50, "max_chars": 34, "margin_v": 40,
                 "label": "Square: Instagram and LinkedIn feed posts"},
    "portrait": {"size": (1080, 1350), "font_size": 52, "max_chars": 32, "margin_v": 60,
                 "label": "Tall feed post: Instagram, Facebook"},
}
# Non-video formats are laid out against a CSS width of 540 and rendered at 2x.
# A wide deck keeps its own design width setting.
NARROW_DESIGN_WIDTH = 540


def frame_size(opts):
    return FORMATS[getattr(opts, "format", "video") or "video"]["size"]
CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    # Chrome installed without administrator rights goes into the user's own
    # AppData rather than Program Files, and nothing puts it on PATH.
    str(Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe"),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]

# Nothing on a mac puts Chrome on PATH, hence the .app paths above. These are
# for Linux, where the opposite is true and the binary is named half a dozen
# different things.
CHROME_ON_PATH = ["chrome", "google-chrome", "google-chrome-stable",
                  "chromium", "chromium-browser", "msedge"]

# --------------------------------------------------------------------------
# script parsing
# --------------------------------------------------------------------------

MARKUP = re.compile(r"\[([^\]]+)\]\((?:/[^)]*/|[+-]\d)\)")
SLIDE_HDR = re.compile(r"^Slide\s+(\d+)\s*(?:-\s*(.*))?$", re.I)
SENT_SPLIT = re.compile(r"(?<=[.!?\u2026])\s+")


def strip_markup(text):
    """Turn Kokoro markup back into plain words. Markup changes sound, never wording."""
    return MARKUP.sub(r"\1", text)


PRONUNCIATIONS = Path(__file__).parent / "pronunciations.json"


def load_pronunciations(path=PRONUNCIATIONS):
    """{word: sound}. A missing file is an empty dictionary, not an error."""
    if not path or not Path(path).exists():
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def is_english_voice(voice):
    """Kokoro's English voices are af_/am_ (American) and bf_/bm_ (British)."""
    return voice[:1] in ("a", "b")


def apply_pronunciations(text, dictionary):
    """Add Kokoro markup to every whole-word match, so a plain script is enough.

    Matching ignores case but keeps the spelling as written, which is what the
    subtitles show. Words that already carry markup are left alone. Longer
    entries win, so "VS Code" is matched before "VS".
    """
    if not dictionary:
        return text
    sounds = {word.lower(): sound if sound.startswith("/") else f"/{sound.strip('/')}/"
              for word, sound in dictionary.items() if word.strip() and sound.strip()}
    if not sounds:
        return text
    words = sorted(sounds, key=len, reverse=True)
    pattern = re.compile(r"(?<![\w\[])(" + "|".join(map(re.escape, words)) + r")(?![\w\]])",
                         re.I)

    def mark(match):
        return f"[{match.group(1)}]({sounds[match.group(1).lower()]})"

    pieces, last = [], 0
    for existing in MARKUP.finditer(text):
        pieces.append(pattern.sub(mark, text[last:existing.start()]))
        pieces.append(existing.group(0))
        last = existing.end()
    pieces.append(pattern.sub(mark, text[last:]))
    return "".join(pieces)


def parse_script(path):
    """Return [{n, label, paragraph}], one entry per slide, in file order."""
    slides, current = [], None
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        header = SLIDE_HDR.match(line)
        if header:
            current = {"n": int(header.group(1)),
                       "label": (header.group(2) or "").strip(),
                       "parts": []}
            slides.append(current)
        elif current is not None:
            current["parts"].append(line)
    for slide in slides:
        slide["paragraph"], slide["steps"] = take_steps(" ".join(slide.pop("parts")))
    return [s for s in slides if s["paragraph"]]


def split_sentences(paragraph):
    return [s.strip() for s in SENT_SPLIT.split(paragraph) if s.strip()]


SHOW = re.compile(r"\[show\]\s*", re.I)


def take_steps(paragraph):
    """Remove the [show] markers. Returns the clean paragraph, and for each
    marker the index of the sentence it starts, so the deck's next data-step
    element appears as that sentence begins. Never spoken, never shown."""
    kept, steps, pending = [], [], 0
    for sentence in split_sentences(paragraph):
        count = len(SHOW.findall(sentence))
        clean = SHOW.sub("", sentence).strip()
        if not clean:                       # a marker on its own, before the next sentence
            pending += count
            continue
        steps += [len(kept)] * (pending + count)
        pending = 0
        kept.append(clean)
    steps += [max(len(kept) - 1, 0)] * pending
    return " ".join(kept), steps


# Ending a subtitle line on one of these leaves it dangling into the next line.
WEAK_ENDINGS = {
    "a", "an", "the", "and", "or", "but", "so", "of", "to", "in", "on", "at",
    "by", "for", "from", "with", "as", "into", "than", "then", "that", "which",
    "is", "are", "was", "were", "be", "been", "its", "their", "your", "our",
    "both", "if", "when", "while", "no", "not", "you", "it", "they", "we",
}


def _line_cost(words, i, j, target, max_chars, total_words):
    """Lower is better. Punctuation earns a break, dangling words are punished."""
    text = " ".join(words[i:j])
    if len(text) > max_chars:
        return math.inf, text
    cost = ((len(text) - target) / max(target, 1)) ** 2 * 100
    last = words[j - 1]
    if last.endswith((",", ";", ":", "—", "–")):
        cost -= 38
    elif last.endswith((".", "!", "?")):
        cost -= 20
    if last.strip(",.;:!?\"')—–").lower() in WEAK_ENDINGS:
        cost += 65
    if j - i == 1 and total_words > 2:
        cost += 35
    return cost, text


def split_lines(text, max_chars):
    """Break one sentence into display lines, preferring clause boundaries.

    A plain character-count wrap orphans conjunctions ("...project, both" /
    "of them...") and reads badly. This scores every possible set of breaks and
    takes the cheapest, so lines end where the sentence pauses.
    """
    words = text.split()
    if len(text) <= max_chars or len(words) == 1:
        return [text]
    count = math.ceil(len(text) / max_chars)
    target = len(text) / count
    n = len(words)

    best = [math.inf] * (n + 1)
    back = [0] * (n + 1)
    best[0] = 0
    for j in range(1, n + 1):
        for i in range(j):
            if best[i] == math.inf:
                continue
            cost, _ = _line_cost(words, i, j, target, max_chars, n)
            if cost is math.inf:
                continue
            if best[i] + cost < best[j]:
                best[j] = best[i] + cost
                back[j] = i

    if best[n] == math.inf:      # a single word longer than max_chars
        lines, current = [], ""
        for word in words:
            candidate = (current + " " + word).strip()
            if current and len(candidate) > max_chars:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        return lines

    lines, j = [], n
    while j > 0:
        i = back[j]
        lines.append(" ".join(words[i:j]))
        j = i
    return lines[::-1]


def allocate(start, end, lines, min_dur):
    """Share a sentence's exact window across its lines, with a duration floor.

    Without a floor a short trailing line can flash up for a fifth of a second.
    """
    span = end - start
    while len(lines) > 1 and span < len(lines) * min_dur:
        shortest, where = None, 0
        for i in range(len(lines) - 1):
            merged = len(lines[i]) + 1 + len(lines[i + 1])
            if shortest is None or merged < shortest:
                shortest, where = merged, i
        lines = (lines[:where] + [lines[where] + " " + lines[where + 1]]
                 + lines[where + 2:])

    weights = [len(line) for line in lines]
    total = sum(weights) or 1
    floor = min(min_dur, span / len(lines))
    spare = span - floor * len(lines)
    events, cursor = [], start
    for line, weight in zip(lines, weights):
        duration = floor + spare * weight / total
        events.append((cursor, cursor + duration, line))
        cursor += duration
    return events


# --------------------------------------------------------------------------
# speech
# --------------------------------------------------------------------------

def kokoro_reachable(url, timeout=4):
    ping = url.replace("/tts/convert", "/tts/ping")
    try:
        with urlrequest.urlopen(ping, timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False


def synthesize(text, voice, speed, url):
    payload = json.dumps({"text": text, "voice": voice, "speed": speed,
                          "output_format": "wav"}).encode("utf-8")
    req = urlrequest.Request(url, data=payload,
                             headers={"Content-Type": "application/json"})
    with urlrequest.urlopen(req, timeout=300) as response:
        return response.read()


def decode_wav(data):
    with wave.open(io.BytesIO(data), "rb") as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise RuntimeError("expected 16-bit mono from Kokoro")
        return w.readframes(w.getnframes()), w.getframerate()


def trim_silence(frames, rate, threshold=300, keep_ms=30):
    """Strip Kokoro's own leading/trailing padding so the gaps are ours to control."""
    samples = array.array("h")
    samples.frombytes(frames)
    n = len(samples)
    start, end = 0, n
    while start < n and abs(samples[start]) < threshold:
        start += 1
    while end > start and abs(samples[end - 1]) < threshold:
        end -= 1
    if start >= end:
        return frames
    keep = int(rate * keep_ms / 1000)
    return samples[max(0, start - keep):min(n, end + keep)].tobytes()


def silence(seconds):
    return b"\x00\x00" * int(SAMPLE_RATE * seconds)


def voice_piece_key(text, voice, speed):
    """Only what changes the sound of one piece. Pauses are added around the
    pieces afterwards, so changing a gap never re-records anything."""
    parts = [text, voice, f"{float(speed):.6f}"]
    return hashlib.sha1(json.dumps(parts).encode("utf-8")).hexdigest()


def speak_piece(text, opts, cache_dir, used_keys):
    """Kokoro's audio for one piece, trimmed, from the cache when it is there."""
    key = voice_piece_key(text, opts.voice, opts.speed)
    used_keys.add(key)
    cached = cache_dir / f"{key}.wav" if cache_dir else None
    if cached and cached.exists():
        with wave.open(str(cached), "rb") as w:
            return w.readframes(w.getnframes()), True
    frames, rate = decode_wav(synthesize(text, opts.voice, opts.speed, opts.kokoro))
    if rate != SAMPLE_RATE:
        raise RuntimeError(f"Kokoro returned {rate} Hz, expected {SAMPLE_RATE}")
    frames = trim_silence(frames, rate)
    if cached:
        cache_dir.mkdir(parents=True, exist_ok=True)
        write_wav(cached, frames)
    return frames, False


def build_audio(slides, opts, log, cache_dir=None):
    """Speak the script. Returns frames, cues, slide end times, total.

    A whole slide per call lets Kokoro carry phrasing across sentences, which is
    how it sounds when you paste a paragraph into its own UI. Sentence by
    sentence gives exact sentence boundaries with no alignment, at the cost of
    every sentence starting cold.

    With a cache_dir every piece is kept, so editing one slide re-records that
    slide only. Pieces this build did not use are deleted afterwards.
    """
    per_slide = getattr(opts, "chunk", "slide") == "slide"
    cache_dir = Path(cache_dir) if cache_dir else None
    used_keys = set()
    dictionary = (load_pronunciations(getattr(opts, "pronunciations", None))
                  if is_english_voice(opts.voice) else {})
    track = bytearray()
    cues, slide_ends = [], []
    track += silence(opts.lead_in)
    for index, slide in enumerate(slides):
        units = ([slide["paragraph"]] if per_slide
                 else split_sentences(slide["paragraph"]))
        for position, unit in enumerate(units):
            where = f"  slide {index + 1}/{len(slides)}"
            if not per_slide:
                where += f", sentence {position + 1}/{len(units)}"
            frames, from_cache = speak_piece(apply_pronunciations(unit, dictionary),
                                             opts, cache_dir, used_keys)
            log(where + (" (unchanged, reused)" if from_cache else ""))
            start = len(track) / 2 / SAMPLE_RATE
            track += frames
            end = len(track) / 2 / SAMPLE_RATE
            cues.append((start, end, strip_markup(unit)))
            if position < len(units) - 1:
                track += silence(opts.gap_sentence)
        slide_ends.append(len(track) / 2 / SAMPLE_RATE)
        if index < len(slides) - 1:
            track += silence(opts.gap_slide)
    track += silence(opts.tail)
    if cache_dir and cache_dir.exists():
        for old in cache_dir.glob("*.wav"):
            if old.stem not in used_keys:
                old.unlink()
    return bytes(track), cues, slide_ends, len(track) / 2 / SAMPLE_RATE


def slide_ranges(slide_ends, lead_in, gap_slide):
    """Start and end second of each slide's own narration inside the full track."""
    ranges, start = [], lead_in
    for end in slide_ends:
        ranges.append((start, end))
        start = end + gap_slide
    return ranges


def write_slide_audio(frames, ranges, outdir):
    """One WAV per slide, sliced from the finished track. Used by the CapCut export."""
    outdir.mkdir(parents=True, exist_ok=True)
    clips = []
    for index, (start, end) in enumerate(ranges, 1):
        first = int(start * SAMPLE_RATE) * 2
        last = int(end * SAMPLE_RATE) * 2
        path = outdir / f"slide-{index}.wav"
        write_wav(path, frames[first:last])
        clips.append((str(path.resolve()), start, end - start))
    return clips


def write_wav(path, frames):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(frames)


# --------------------------------------------------------------------------
# slide rendering
# --------------------------------------------------------------------------

def find_chrome():
    for candidate in CHROME_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    for name in CHROME_ON_PATH:
        found = shutil.which(name)
        if found:
            return found
    raise RuntimeError("Chrome not found; pass --chrome")


def absolutize(html, base, assets):
    """Point every relative asset at a file:/// URL so a temp copy still renders."""
    def resolve(name):
        if name in assets:
            return Path(assets[name]).resolve().as_uri()
        target = base / name
        return target.resolve().as_uri() if target.exists() else None

    def fix_src(match):
        name = match.group(1)
        if name.startswith(("http:", "https:", "data:", "file:", "#")):
            return match.group(0)
        uri = resolve(name)
        return f'src="{uri}"' if uri else match.group(0)

    def fix_url(match):
        name = match.group(1).strip("'\"")
        if name.startswith(("http:", "https:", "data:", "file:", "#")):
            return match.group(0)
        uri = resolve(name)
        return f"url({uri})" if uri else match.group(0)

    html = re.sub(r'src="([^"]+)"', fix_src, html)
    return re.sub(r"url\(([^)]+)\)", fix_url, html)


def missing_assets(html_path):
    """Relative src/url() targets that do not exist next to the deck."""
    source = Path(html_path)
    html = source.read_text(encoding="utf-8")
    names = re.findall(r'src="([^"]+)"', html) + [
        m.strip("'\"") for m in re.findall(r"url\(([^)]+)\)", html)]
    missing = []
    for name in names:
        if name.startswith(("http:", "https:", "data:", "file:", "#")):
            continue
        if not (source.parent / name).exists() and name not in missing:
            missing.append(name)
    return missing


def count_slides(html):
    return len(re.findall(r'<section[^>]*class="[^"]*\bslide\b', html))


def step_css(state, steps):
    """Hide the data-step elements that have not appeared yet. visibility keeps
    their space, so nothing else on the slide moves when one appears."""
    hidden = [f'[data-step="{k}"]' for k in range(state + 1, steps + 1)]
    return f"<style>{','.join(hidden)}{{visibility:hidden!important}}</style>" if hidden else ""


def render_slides(html_path, assets, outdir, chrome, log, design_width=1536,
                  size=(1920, 1080), steps_per_slide=None):
    """PNGs at the frame size: one list per slide, holding one picture per step
    (just one picture for a slide with no steps)."""
    width, height = size
    if width <= height:
        design_width = NARROW_DESIGN_WIDTH
    viewport = (design_width, round(design_width * height / width))
    source = Path(html_path)
    html = absolutize(source.read_text(encoding="utf-8"), source.parent, assets)
    total = count_slides(html)
    if not total:
        raise RuntimeError("no <section class='slide'> found in the deck")
    # Kill the entrance transition, or a screenshot can land mid-fade.
    html = html.replace(
        "</head>",
        "<style>*{transition:none!important;animation:none!important}</style></head>", 1)
    if "let currentSlide = 0;" not in html:
        raise RuntimeError("deck script does not contain 'let currentSlide = 0;'")

    outdir.mkdir(parents=True, exist_ok=True)
    work = outdir / "_html"
    work.mkdir(exist_ok=True)
    # Without its own profile dir, a headless launch is swallowed by an
    # already-running Chrome: it exits 0 and writes no PNG.
    profile = (outdir / "_chrome").resolve()
    for stale in outdir.glob("*.png"):
        stale.unlink()
    steps_per_slide = steps_per_slide or [0] * total
    paths = []
    for index in range(total):
        steps = steps_per_slide[index] if index < len(steps_per_slide) else 0
        paths.append([])
        for state in range(steps + 1):
            log(f"  rendering slide {index + 1}/{total}"
                + (f", step {state}/{steps}" if steps else ""))
            paths[-1].append(render_one(html, index, state, steps, work, outdir, chrome,
                                        profile, design_width, width, viewport))
    return paths


def render_one(html, index, state, steps, work, outdir, chrome, profile,
               design_width, width, viewport):
    name = f"{index + 1}" + (f"-{state}" if steps else "")
    page = work / f"slide-{name}.html"
    page.write_text(
        html.replace("let currentSlide = 0;", f"let currentSlide = {index};", 1)
            .replace("</head>", step_css(state, steps) + "</head>", 1),
        encoding="utf-8")
    # Chrome refuses a relative --screenshot path ("Access is denied") but
    # still exits 0, so the path must be absolute and the result checked.
    png = (outdir / f"{name}.png").resolve()
    # The '#1' is required: the deck hides its counter only when the hash is non-empty.
    # The deck is laid out against a CSS viewport, and how big its text
    # looks depends on that width, not on the output size. A 1920 screen at
    # 125% Windows scaling gives the browser a 1536 viewport, so a deck
    # designed by eye there renders smaller if captured at 1920. Render at
    # the width it was designed for and scale up to the frame.
    subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    f"--force-device-scale-factor={width / design_width:.6f}",
                    f"--window-size={viewport[0]},{viewport[1]}",
                    f"--user-data-dir={profile}",
                    f"--screenshot={png}", page.resolve().as_uri() + "#1"],
                   check=True, capture_output=True)
    if not png.exists():
        raise RuntimeError(f"Chrome wrote no PNG for slide {index + 1}")
    return png


# --------------------------------------------------------------------------
# subtitles
# --------------------------------------------------------------------------

def remap(words, start, end):
    """Fit recognised word times into the sentence window Kokoro gave us.

    The recogniser's absolute times drift - it puts the first word at 0.00 when
    the audio actually starts later - but its relative spacing is good. The
    sentence boundaries are exact, so stretch one onto the other.
    """
    if not words:
        return []
    low, high = words[0][1], words[-1][2]
    if high - low <= 0:
        step = (end - start) / len(words)
        return [(w, start + i * step, start + (i + 1) * step)
                for i, (w, _, _) in enumerate(words)]
    scale = (end - start) / (high - low)
    return [(w, start + (a - low) * scale, start + (b - low) * scale)
            for w, a, b in words]


def allocate_by_words(lines, words, min_dur):
    """Line timing straight off the words, so a line appears as it is spoken."""
    events, cursor = [], 0
    for line in lines:
        count = len(line.split())
        chunk = words[cursor:cursor + count]
        cursor += count
        if not chunk:
            continue
        events.append([chunk[0][1], chunk[-1][2], line, chunk])
    for i in range(len(events) - 1):          # no dead air between lines
        events[i][1] = max(events[i][1], events[i + 1][0])
    for event in events:                      # honour the duration floor
        if event[1] - event[0] < min_dur:
            event[1] = event[0] + min_dur
    return [tuple(e) for e in events]


def expand_slides(cues, word_times):
    """Split slide-level cues into sentence-level ones.

    Word timings put each sentence boundary where it actually falls; without
    them the slide's window is shared out by character count, which is close
    enough for line breaks but not exact.
    """
    new_cues, new_words = [], []
    for index, (start, end, text) in enumerate(cues):
        sentences = split_sentences(text)
        words = None
        if word_times and index < len(word_times) and word_times[index]:
            words = remap(word_times[index], start, end)
        if len(sentences) <= 1:
            new_cues.append((start, end, text))
            new_words.append(words)
            continue
        if words:
            cursor = 0
            for sentence in sentences:
                count = len(sentence.split())
                chunk = words[cursor:cursor + count]
                cursor += count
                if not chunk:
                    continue
                new_cues.append((chunk[0][1], chunk[-1][2], sentence))
                new_words.append(chunk)
        else:
            total = sum(len(s) for s in sentences) or 1
            cursor, span = start, end - start
            for sentence in sentences:
                share = span * len(sentence) / total
                new_cues.append((cursor, cursor + share, sentence))
                new_words.append(None)
                cursor += share
    return new_cues, (new_words if any(new_words) else None)


def make_events(cues, max_chars, min_dur, word_times=None):
    """Sentence windows are exact; lines inside one sentence share that window."""
    events = []
    for index, (start, end, text) in enumerate(cues):
        lines = split_lines(text, max_chars)
        words = word_times[index] if word_times and index < len(word_times) else None
        if words:
            events.extend(allocate_by_words(lines, remap(words, start, end), min_dur))
        elif len(lines) == 1:
            events.append((start, end, lines[0], None))
        else:
            events.extend((a, b, s, None) for a, b, s in allocate(start, end, lines, min_dur))
    return events


def srt_time(seconds):
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def ass_time(seconds):
    cs = int(round(seconds * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


NL = chr(10)


def ass_style_colour(hex_rgb):
    """Style-field form, with the alpha byte in front."""
    h = hex_rgb.lstrip("#")
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def ass_colour(hex_rgb):
    """ASS wants &HBBGGRR&, people write #RRGGBB."""
    h = hex_rgb.lstrip("#")
    return f"&H{h[4:6]}{h[2:4]}{h[0:2]}&".upper()


def write_srt(path, events):
    blocks = [f"{i}" + NL + f"{srt_time(e[0])} --> {srt_time(e[1])}" +
                  NL + e[2] + NL
              for i, e in enumerate(events, 1)]
    path.write_text("\n".join(blocks), encoding="utf-8")


def dialogue_lines(events, opts):
    """One Dialogue per subtitle line, or one per word when highlighting."""
    colour = ass_colour(getattr(opts, "highlight_colour", "#FFD400"))
    out = []
    for event in events:
        start, end, text = event[0], event[1], event[2]
        words = event[3] if len(event) > 3 else None
        if not (getattr(opts, "highlight", False) and words):
            out.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Sub,,0,0,0,,{text}")
            continue
        # A separate line per word, each drawing the whole caption with one
        # word recoloured, and a reset tag puts the rest back to the style.
        pieces = [w for w, _, _ in words]
        for index, (_, first, _) in enumerate(words):
            last = words[index + 1][1] if index + 1 < len(words) else end
            if last <= first:
                continue
            shown = " ".join(
                (chr(123) + chr(92) + "c" + colour + chr(125) + piece +
                 chr(123) + chr(92) + "r" + chr(125)) if i == index else piece
                for i, piece in enumerate(pieces))
            out.append(
                f"Dialogue: 0,{ass_time(first)},{ass_time(last)},Sub,,0,0,0,,{shown}")
    return out


def write_ass(path, events, opts):
    """PlayRes is the real frame size, so Fontsize is genuine pixels."""
    bold = -1 if opts.bold else 0
    width, height = frame_size(opts)
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {width}\n"
        f"PlayResY: {height}\n"
        "WrapStyle: 2\n"
        "ScaledBorderAndShadow: yes\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
        "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Sub,{opts.font},{opts.font_size},"
        f"{ass_style_colour(getattr(opts, 'text_colour', '#ffffff'))},"
        f"&H000000FF,"
        f"{ass_style_colour(getattr(opts, 'outline_colour', '#000000'))},"
        f"&H00000000,{bold},0,0,0,100,100,0,0,1,{opts.outline},0,2,"
        f"{60 if width < 1920 else 80},{60 if width < 1920 else 80},{opts.margin_v},1\n"
        "\n"
        "[Events]\n"
        # MarginV belongs in this list. Leaving it out shifts every field and
        # the spare comma ends up printed at the front of the subtitle.
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n")
    body = dialogue_lines(events, opts)
    path.write_text(header + NL.join(body) + NL, encoding="utf-8")


# --------------------------------------------------------------------------
# assembly
# --------------------------------------------------------------------------

def slide_durations(slide_ends, total, gap_slide):
    """Cut between slides mid-gap, so the fade never covers a spoken word."""
    cuts = [end + gap_slide / 2 for end in slide_ends[:-1]] + [total]
    durations, previous = [], 0.0
    for cut in cuts:
        durations.append(cut - previous)
        previous = cut
    return durations


def sentence_starts_per_slide(cues, ranges):
    """When each sentence starts, grouped by the slide it is spoken on."""
    starts = [[] for _ in ranges]
    for start, _, _ in cues:
        slide = max((i for i, (a, _) in enumerate(ranges) if a <= start + 1e-6), default=0)
        starts[slide].append(start)
    return starts


def picture_segments(pngs, durations, slides, sentence_starts):
    """(png, seconds, fade_in, fade_out) for every picture on the timeline.

    A slide with steps is several pictures: the next one replaces the last as
    its sentence starts. The black fade belongs to the slide, so it goes in at
    its first picture and out at its last.
    """
    segments, slide_start = [], 0.0
    for index, (images, duration) in enumerate(zip(pngs, durations)):
        slide_end = slide_start + duration
        starts = sentence_starts[index] if index < len(sentence_starts) else []
        times = sorted(
            min(max(starts[min(at, len(starts) - 1)] if starts else slide_start,
                    slide_start), slide_end)
            for at in slides[index].get("steps", [])[:len(images) - 1])
        bounds = [slide_start] + times + [slide_end]
        pieces = [(image, bounds[k + 1] - bounds[k]) for k, image in enumerate(images)]
        # A step on the first word leaves its "before" picture zero seconds long.
        pieces = [p for p in pieces if p[1] > 0.01] or pieces[-1:]
        for k, (image, length) in enumerate(pieces):
            segments.append((image, length, k == 0, k == len(pieces) - 1))
        slide_start = slide_end
    return segments


def build_filtergraph(segments, opts):
    """One segment per picture, fades where a slide starts and ends, then concat.

    Fades must be local to each segment. Chaining fades on a single timeline
    does not work: fade=t=in:st=X blacks out everything before X, and
    fade=t=out leaves everything after it black.
    """
    fade = opts.fade
    width, height = frame_size(opts)
    chains = []
    for index, (_, duration, fade_in, fade_out) in enumerate(segments):
        fades = ""
        if not opts.no_fades:
            if fade_in:
                fades += f",fade=t=in:st=0:d={fade}"
            if fade_out:
                fades += f",fade=t=out:st={max(duration - fade, 0.0):.3f}:d={fade}"
        # The scale only guards against Chrome rounding the PNG a pixel off,
        # which concat would refuse.
        chains.append(f"[{index}:v]scale={width}:{height},fps={opts.fps},setsar=1"
                      f"{fades}[v{index}]")
    labels = "".join(f"[v{i}]" for i in range(len(segments)))
    chains.append(f"{labels}concat=n={len(segments)}:v=1:a=0[vc]")
    last = "vc"
    if not opts.no_subs:
        # ffmpeg runs from the build dir, so no Windows path escaping is needed.
        chains.append("[vc]subtitles=subs.ass[vs]")
        last = "vs"
    return ";".join(chains), last


def gain(db):
    """CapCut stores linear gain; people think in dB."""
    return 10 ** (float(db) / 20.0)


def assemble(build, segments, total, opts, log):
    command = [opts.ffmpeg, "-y"]
    for png, duration, _, _ in segments:
        command += ["-loop", "1", "-t", f"{duration:.3f}", "-i", str(Path(png).resolve())]
    command += ["-i", "audio.wav"]
    voice = len(segments)

    graph, last = build_filtergraph(segments, opts)
    audio_map = f"{voice}:a"
    if getattr(opts, "music", None):
        # Looped so a short track still covers the video; amix ends with the
        # voice, and normalize=0 leaves the voice at its own level.
        command += ["-stream_loop", "-1", "-i", str(Path(opts.music).resolve())]
        graph += (f";[{voice + 1}:a]volume={gain(opts.music_db):.6f}[bed];"
                  f"[{voice}:a][bed]amix=inputs=2:duration=first:normalize=0[mixed]")
        audio_map = "[mixed]"

    command += ["-filter_complex", graph,
                "-map", f"[{last}]", "-map", audio_map,
                "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k",
                "-t", f"{total:.3f}",
                str(Path(opts.out).resolve())]
    log("  encoding")
    result = subprocess.run(command, cwd=build, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError("ffmpeg failed:\n" + result.stderr[-3000:])


# --------------------------------------------------------------------------

def run(opts, log=print, audio=None):
    """audio is an already-built (frames, cues, slide_ends, total), so a music
    preview and the build after it do not synthesize the voice twice."""
    build = Path(opts.build)
    build.mkdir(parents=True, exist_ok=True)
    assets = json.loads(Path(opts.assets).read_text(encoding="utf-8")) if opts.assets else {}

    slides = parse_script(opts.script)
    log(f"script: {len(slides)} slides")

    # Check before rendering. Otherwise the failure lands minutes later, after
    # every slide is done, as a bare socket error.
    if audio is None and not kokoro_reachable(opts.kokoro):
        raise RuntimeError(
            f"Kokoro is not answering at {opts.kokoro}.\n"
            "Start it with:  docker start kokoro-ui\n"
            "(if Docker itself is closed, open Docker Desktop first)")

    log("rendering slides")
    pngs = render_slides(opts.deck, assets, build / "slides",
                         opts.chrome or find_chrome(), log,
                         getattr(opts, "design_width", 1536), frame_size(opts),
                         [len(s["steps"]) for s in slides])
    if len(pngs) != len(slides):
        raise RuntimeError(
            f"deck has {len(pngs)} slides but the script has {len(slides)}")

    if audio is None:
        log("generating speech")
        audio = build_audio(slides, opts, log, build / "voice_cache")
    else:
        log("reusing the voice already generated")
    frames, cues, slide_ends, total = audio
    write_wav(build / "audio.wav", frames)
    log(f"audio: {total:.1f}s")

    word_times = None
    if getattr(opts, "align_words", False):
        import align
        units = [text for _, _, text in cues]
        key = align.cache_key(units, total)
        word_times = align.load_cached(build, key)
        if word_times is None:
            log("aligning words to the audio")
            word_times = align.word_times(
                build / "audio.wav", units, getattr(opts, "whisper", "base"), log)
            if word_times:
                align.save(build, word_times, key)
        else:
            log("reusing the word alignment")

    if getattr(opts, "chunk", "slide") == "slide":
        cues, word_times = expand_slides(cues, word_times)

    events = make_events(cues, opts.max_chars, opts.min_sub, word_times)
    write_srt(build / "subs.srt", events)
    write_ass(build / "subs.ass", events, opts)
    log(f"subtitles: {len(events)} lines")

    ranges = slide_ranges(slide_ends, opts.lead_in, opts.gap_slide)
    clips = write_slide_audio(frames, ranges, build / "voice")

    durations = slide_durations(slide_ends, total, opts.gap_slide)
    segments = picture_segments(pngs, durations, slides,
                                sentence_starts_per_slide(cues, ranges))
    assemble(build, segments, total, opts, log)
    log(f"done: {opts.out}")
    # pngs and slide_durations are per picture, so the CapCut draft gets every
    # step too; fade_after says which pictures end a slide.
    return {"duration": total, "slides": len(pngs), "subtitles": len(events),
            "format": getattr(opts, "format", "video") or "video",
            "size": list(frame_size(opts)), "margin_v": opts.margin_v,
            "slide_durations": [s[1] for s in segments],
            "fade_after": [s[3] for s in segments],
            "out": str(Path(opts.out).resolve()),
            "pngs": [str(s[0]) for s in segments],
            "voice_clips": clips,
            "events": [[e[0], e[1], e[2]] for e in events]}


def build_parser():
    p = argparse.ArgumentParser(description="Slide deck + voiceover script -> MP4")
    p.add_argument("deck", help="video-presentation.html")
    p.add_argument("script", help="voiceover-kokoro.txt")
    p.add_argument("-o", "--out", default="video.mp4")
    p.add_argument("--build", default="build", help="working directory")
    p.add_argument("--assets", help="JSON map of {relative src: absolute path}")
    p.add_argument("--voice", default="af_sky")
    p.add_argument("--speed", type=float, default=1.0)
    p.add_argument("--kokoro", default=KOKORO_URL)
    p.add_argument("--pronunciations", default=str(PRONUNCIATIONS),
                   help="JSON of {word: sound}; matching words get Kokoro markup "
                        "automatically (English voices only)")
    p.add_argument("--lead-in", type=float, default=0.6, dest="lead_in")
    p.add_argument("--tail", type=float, default=1.2)
    p.add_argument("--gap-sentence", type=float, default=0.28, dest="gap_sentence")
    p.add_argument("--gap-slide", type=float, default=1.1, dest="gap_slide")
    p.add_argument("--fade", type=float, default=0.45)
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--font", default="Arial")
    p.add_argument("--format", choices=tuple(FORMATS), default="video",
                   help="; ".join(f"{name}: {f['size'][0]}x{f['size'][1]}, {f['label']}"
                                  for name, f in FORMATS.items()))
    # These three default to whatever suits the chosen format.
    p.add_argument("--font-size", type=int, dest="font_size")
    p.add_argument("--outline", type=int, default=4)
    p.add_argument("--margin-v", type=int, dest="margin_v")
    p.add_argument("--max-chars", type=int, dest="max_chars")
    p.add_argument("--min-sub", type=float, default=0.9, dest="min_sub",
                   help="shortest time a subtitle line may stay on screen")
    p.add_argument("--bold", action="store_true", help="CapCut subtitles are not bold, so this is off by default")
    p.add_argument("--no-subs", action="store_true")
    p.add_argument("--design-width", type=int, default=1536, dest="design_width",
                   help="CSS width the deck was designed against; 1536 is a "
                        "1920 screen at 125%% Windows scaling, 1920 is 1:1")
    p.add_argument("--chunk", choices=("slide", "sentence"), default="slide",
                   help="send Kokoro a whole slide, or one sentence at a time")
    p.add_argument("--text-colour", default="#ffffff", dest="text_colour")
    p.add_argument("--outline-colour", default="#000000", dest="outline_colour")
    p.add_argument("--align-words", action="store_true", dest="align_words",
                   help="recover word timings so lines follow the voice exactly")
    p.add_argument("--highlight", action="store_true",
                   help="colour the word being spoken (implies --align-words)")
    p.add_argument("--highlight-colour", default="#FFD400", dest="highlight_colour")
    p.add_argument("--whisper", default="base",
                   help="alignment model size: tiny, base, small")
    p.add_argument("--music", help="audio file to sit under the voice")
    p.add_argument("--music-db", type=float, default=-20.0, dest="music_db",
                   help="music level under the voice, in dB")
    p.add_argument("--no-fades", action="store_true",
                   help="leave the black fades out, e.g. to add them in CapCut")
    p.add_argument("--chrome")
    p.add_argument("--ffmpeg", default="ffmpeg")
    return p


def main():
    parser = build_parser()
    opts = parser.parse_args()
    for key in ("font_size", "max_chars", "margin_v"):
        if getattr(opts, key) is None:
            setattr(opts, key, FORMATS[opts.format][key])
    if opts.highlight:
        opts.align_words = True
    if opts.gap_slide < 2 * opts.fade:
        parser.error(f"--gap-slide must be at least twice --fade "
                     f"({2 * opts.fade}) or the fade would cover speech")
    run(opts)


if __name__ == "__main__":
    main()
