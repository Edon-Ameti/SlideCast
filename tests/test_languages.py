import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import ai
import deck_template
import slidecast as d


def count(text):
    return len(d.split_sentences(text))


SLIDES = [{"label": "Hook", "sentences": ["Hello there.", "This is a test."]},
          {"label": "End", "sentences": ["Goodbye."]}]
SPANISH = {"slides": [{"label": "Gancho", "sentences": ["Hola.", "Esto es una prueba."]},
                      {"label": "Fin", "sentences": ["Adiós."]}]}


class TranslateScriptTest(unittest.TestCase):
    def check(self, data):
        """Run translate_script's check on one answer."""
        with mock.patch.object(ai, "complete", return_value=json.dumps(data)):
            return ai.translate_script({}, SLIDES, "Spanish", count)

    def test_good_translation_passes(self):
        self.assertEqual(self.check(SPANISH), SPANISH)

    def test_wrong_sentence_count_is_retried_then_refused(self):
        bad = json.loads(json.dumps(SPANISH))
        bad["slides"][0]["sentences"] = ["Hola. Esto es una prueba."]
        with self.assertRaises(ai.AIError) as caught:
            self.check(bad)
        self.assertIn("exactly 2 sentences", str(caught.exception))

    def test_two_sentences_hidden_in_one_item_is_refused(self):
        bad = json.loads(json.dumps(SPANISH))
        bad["slides"][0]["sentences"] = ["Hola. Que tal.", "Esto es una prueba."]
        with self.assertRaises(ai.AIError) as caught:
            self.check(bad)
        self.assertIn("more than one sentence", str(caught.exception))

    def test_script_keeps_show_markers_on_their_sentence(self):
        original = [{"n": 1, "steps": [1]}, {"n": 2, "steps": []}]
        text = ai.translated_script(original, SPANISH)
        self.assertIn("Slide 1 - Gancho\n\nHola. [show] Esto es una prueba.", text)
        self.assertIn("Slide 2 - Fin\n\nAdiós.", text)

    def test_hindi_danda_ends_a_sentence(self):
        self.assertEqual(count("नमस्ते। यह एक परीक्षण है।"), 2)


class TranslateHtmlTest(unittest.TestCase):
    HTML = ('<html><head><title>T</title><style>.a{color:red}</style></head><body>'
            '<section class="slide"><h1>  Fast &amp; simple </h1><!-- note -->'
            '<p>Works <b>offline</b></p></section>'
            '<script>let currentSlide = 0; const x = "do not touch";</script></body></html>')

    def test_only_visible_text_changes(self):
        seen = []

        def upper(texts):
            seen.extend(texts)
            return [t.upper() for t in texts]

        out = deck_template.translate_html(self.HTML, upper)
        self.assertEqual(seen, ["Fast & simple", "Works", "offline"])
        self.assertIn("<h1>  FAST &amp; SIMPLE </h1>", out)
        self.assertIn("<p>WORKS <b>OFFLINE</b></p>", out)
        self.assertIn('const x = "do not touch";', out)
        self.assertIn(".a{color:red}", out)
        self.assertIn("<!-- note -->", out)
        self.assertIn("let currentSlide = 0;", out)


class SubtitleTextTest(unittest.TestCase):
    def test_original_sentences_replace_the_spoken_ones(self):
        cues = [(0.6, 1.5, "Hola."), (1.8, 3.0, "Esto es una prueba."), (4.1, 5.0, "Adiós.")]
        slides = [{"paragraph": "Hello [dbt](/x/). This is a test."},
                  {"paragraph": "Goodbye."}]
        self.assertEqual(d.with_subtitle_text(cues, slides),
                         [(0.6, 1.5, "Hello dbt."), (1.8, 3.0, "This is a test."),
                          (4.1, 5.0, "Goodbye.")])

    def test_mismatch_is_reported(self):
        with self.assertRaises(RuntimeError):
            d.with_subtitle_text([(0, 1, "Hola.")], [{"paragraph": "One. Two."}])

    def test_language_of_a_voice(self):
        self.assertEqual(d.language_of("ef_dora")["whisper"], "es")
        self.assertEqual(d.language_of("hm_omega")["name"], "Hindi")
        self.assertEqual(d.language_of("af_sky")["whisper"], "en")

    def test_voice_script_forces_sentence_recording(self):
        opts = d.build_parser().parse_args(["a.html", "b.txt", "--voice-script", "c.txt",
                                            "--highlight"])
        d.finish_options(opts)
        self.assertEqual(opts.chunk, "sentence")
        self.assertFalse(opts.highlight)
        self.assertFalse(opts.align_words)


if __name__ == "__main__":
    unittest.main()
