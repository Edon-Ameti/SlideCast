"""Shared bits for the tests: a fake Kokoro and default options."""

import io
import wave
from argparse import Namespace

import slidecast as d


def tone_wav(seconds=0.5, rate=d.SAMPLE_RATE):
    """A loud constant tone, so trim_silence keeps all of it."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\xe8\x03" * int(rate * seconds))
    return buffer.getvalue()


class FakeKokoro:
    """Stands in for slidecast.synthesize and remembers what it was asked."""

    def __init__(self):
        self.calls = []

    def __call__(self, text, voice, speed, url, **kwargs):
        self.calls.append(text)
        return tone_wav()


def options(**overrides):
    base = dict(voice="af_sky", speed=1.0, kokoro="http://fake/tts/convert",
                lead_in=0.6, tail=1.2, gap_sentence=0.28, gap_slide=1.1,
                chunk="slide")
    base.update(overrides)
    return Namespace(**base)
