#!/usr/bin/env python3
"""Word-level timings for the generated voice.

Kokoro returns audio and nothing else, so SlideCast knows exactly when each
sentence starts and ends but not where the words fall inside it. This runs
faster-whisper over the finished track to recover word timings, then maps them
back onto the script we already know, which is far more reliable than trusting
the transcript: the words are given, only the times are missing.
"""

import difflib
import json
import re
from pathlib import Path

_model = None
WORD = re.compile(r"[^a-z0-9']")


def load(size="base"):
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        _model = WhisperModel(size, device="cpu", compute_type="int8")
    return _model


def heard(wav, size="base", log=print):
    """Every word faster-whisper thinks it hears, with its timing."""
    log("  listening back to the voice")
    segments, _ = load(size).transcribe(
        str(wav), word_timestamps=True, language="en",
        vad_filter=False, beam_size=1, condition_on_previous_text=False)
    words = []
    for segment in segments:
        for word in (segment.words or []):
            text = word.word.strip()
            if text:
                words.append((float(word.start), float(word.end), text))
    log(f"  heard {len(words)} words")
    return words


def key(text):
    return WORD.sub("", text.lower())


def align(known, listened):
    """Give every known word a (start, end), interpolating what was not matched.

    `known` is the word list we are certain about; `listened` is what the
    recogniser produced. Anything it misheard still gets a sensible time from
    the confident words either side.
    """
    ours = [key(w) for w in known]
    theirs = [key(w) for _, _, w in listened]
    times = [None] * len(known)

    matcher = difflib.SequenceMatcher(a=ours, b=theirs, autojunk=False)
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            for offset in range(i2 - i1):
                start, end, _ = listened[j1 + offset]
                times[i1 + offset] = (start, end)

    anchors = [i for i, t in enumerate(times) if t]
    if not anchors:
        return None
    # Stretch the first and last anchors outwards, and share unmatched runs
    # evenly between the anchors on either side.
    for i in range(anchors[0]):
        times[i] = times[anchors[0]]
    for i in range(anchors[-1] + 1, len(times)):
        times[i] = times[anchors[-1]]
    for left, right in zip(anchors, anchors[1:]):
        gap = right - left
        if gap < 2:
            continue
        begin, finish = times[left][1], times[right][0]
        step = (finish - begin) / gap
        for k in range(1, gap):
            times[left + k] = (begin + step * (k - 1), begin + step * k)
    return times


def word_times(wav, sentences, size="base", log=print):
    """[[(word, start, end), ...], ...] one list per sentence, or None if it fails."""
    try:
        listened = heard(wav, size, log)
    except Exception as exc:
        log(f"  alignment unavailable ({exc})")
        return None
    if not listened:
        log("  nothing was recognised, keeping the estimated timing")
        return None

    flat = []
    for index, sentence in enumerate(sentences):
        for word in sentence.split():
            flat.append((index, word))
    times = align([w for _, w in flat], listened)
    if not times:
        log("  could not match the transcript, keeping the estimated timing")
        return None

    grouped = [[] for _ in sentences]
    for (index, word), span in zip(flat, times):
        grouped[index].append((word, span[0], span[1]))
    matched = sum(1 for t in times if t)
    log(f"  aligned {matched}/{len(times)} words")
    return grouped


def cache_path(build):
    return Path(build) / "word_times.json"


def cache_key(sentences, total):
    """Alignment belongs to one particular audio track.

    Without this a cached alignment from a different chunking mode gets applied
    to new audio: the units no longer line up and most subtitles vanish.
    """
    import hashlib
    material = json.dumps([list(sentences), round(float(total), 3)])
    return hashlib.sha1(material.encode("utf-8")).hexdigest()


def save(build, grouped, key):
    cache_path(build).write_text(
        json.dumps({"key": key, "words": grouped}), encoding="utf-8")


def load_cached(build, key):
    path = cache_path(build)
    if not path.exists():
        return None
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    if not isinstance(stored, dict) or stored.get("key") != key:
        return None
    return stored.get("words")
