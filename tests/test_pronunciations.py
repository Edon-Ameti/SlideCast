import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import slidecast as d
from tests.helpers import FakeKokoro, options

WORDS = {"dbt": "/dˌibˌitˈi/", "AI": "/ˌAˈI/", "VS Code": "/vˌiˈɛs kˈOd/", "S3": "ˈɛsˌθri"}


class ApplyTest(unittest.TestCase):
    def test_whole_word_and_any_case(self):
        self.assertEqual(d.apply_pronunciations("Run DBT and dbt.", WORDS),
                         "Run [DBT](/dˌibˌitˈi/) and [dbt](/dˌibˌitˈi/).")

    def test_not_inside_another_word(self):
        self.assertEqual(d.apply_pronunciations("OpenAI said hi", WORDS), "OpenAI said hi")
        self.assertEqual(d.apply_pronunciations("dbtx", WORDS), "dbtx")

    def test_punctuation_next_to_the_word(self):
        self.assertEqual(d.apply_pronunciations("(AI), AI!", WORDS),
                         "([AI](/ˌAˈI/)), [AI](/ˌAˈI/)!")

    def test_existing_markup_is_left_alone(self):
        text = "[dbt](/other/) and dbt"
        self.assertEqual(d.apply_pronunciations(text, WORDS),
                         "[dbt](/other/) and [dbt](/dˌibˌitˈi/)")

    def test_longer_entry_wins(self):
        self.assertEqual(d.apply_pronunciations("Open VS Code", WORDS),
                         "Open [VS Code](/vˌiˈɛs kˈOd/)")

    def test_sound_without_slashes_gets_them(self):
        self.assertEqual(d.apply_pronunciations("S3", WORDS), "[S3](/ˈɛsˌθri/)")

    def test_subtitles_show_the_original_spelling(self):
        marked = d.apply_pronunciations("We use DBT here.", WORDS)
        self.assertEqual(d.strip_markup(marked), "We use DBT here.")

    def test_empty_dictionary_changes_nothing(self):
        self.assertEqual(d.apply_pronunciations("dbt", {}), "dbt")
        self.assertEqual(d.apply_pronunciations("dbt", {"": "", "x": " "}), "dbt")


class BuildAudioTest(unittest.TestCase):
    def setUp(self):
        self.kokoro = FakeKokoro()
        patcher = mock.patch.object(d, "synthesize", self.kokoro)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.file = Path(tempfile.mkdtemp()) / "p.json"
        self.file.write_text(json.dumps(WORDS), encoding="utf-8")

    def speak(self, voice):
        deck = [{"n": 1, "label": "", "paragraph": "We use dbt."}]
        return d.build_audio(deck, options(voice=voice, pronunciations=str(self.file)),
                             lambda m: None)

    def test_kokoro_gets_markup_subtitles_do_not(self):
        _, cues, _, _ = self.speak("af_sky")
        self.assertEqual(self.kokoro.calls, ["We use [dbt](/dˌibˌitˈi/)."])
        self.assertEqual(cues[0][2], "We use dbt.")

    def test_not_applied_to_other_languages(self):
        self.speak("ef_dora")
        self.assertEqual(self.kokoro.calls, ["We use dbt."])


if __name__ == "__main__":
    unittest.main()
