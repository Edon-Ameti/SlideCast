import tempfile
import unittest
from pathlib import Path
from unittest import mock

import slidecast as d
from tests.helpers import FakeKokoro, options


def slides(*paragraphs):
    return [{"n": i + 1, "label": "", "paragraph": p} for i, p in enumerate(paragraphs)]


class VoiceCacheTest(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.kokoro = FakeKokoro()
        patcher = mock.patch.object(d, "synthesize", self.kokoro)
        patcher.start()
        self.addCleanup(patcher.stop)

    def build(self, deck, **overrides):
        return d.build_audio(deck, options(**overrides), lambda m: None, self.folder)

    def test_second_build_records_nothing(self):
        deck = slides("One. Two.", "Three.", "Four.")
        first = self.build(deck)
        self.assertEqual(len(self.kokoro.calls), 3)
        second = self.build(deck)
        self.assertEqual(len(self.kokoro.calls), 3)
        self.assertEqual(first, second)

    def test_editing_one_slide_records_only_that_slide(self):
        self.build(slides("One.", "Two.", "Three."))
        self.kokoro.calls.clear()
        self.build(slides("One.", "Two, edited.", "Three."))
        self.assertEqual(self.kokoro.calls, ["Two, edited."])

    def test_changing_a_pause_records_nothing(self):
        deck = slides("One.", "Two.")
        self.build(deck)
        self.kokoro.calls.clear()
        self.build(deck, gap_slide=2.0, lead_in=1.0)
        self.assertEqual(self.kokoro.calls, [])

    def test_changing_the_voice_records_again(self):
        deck = slides("One.")
        self.build(deck)
        self.build(deck, voice="am_adam")
        self.assertEqual(len(self.kokoro.calls), 2)

    def test_sentence_mode_caches_each_sentence(self):
        self.build(slides("One. Two."), chunk="sentence")
        self.kokoro.calls.clear()
        self.build(slides("One. Two changed."), chunk="sentence")
        self.assertEqual(self.kokoro.calls, ["Two changed."])

    def test_unused_pieces_are_deleted(self):
        self.build(slides("One.", "Two."))
        self.assertEqual(len(list(self.folder.glob("*.wav"))), 2)
        self.build(slides("One."))
        self.assertEqual(len(list(self.folder.glob("*.wav"))), 1)

    def test_no_cache_folder_still_works(self):
        d.build_audio(slides("One."), options(), lambda m: None)
        d.build_audio(slides("One."), options(), lambda m: None)
        self.assertEqual(len(self.kokoro.calls), 2)


if __name__ == "__main__":
    unittest.main()
