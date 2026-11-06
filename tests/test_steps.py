import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import slidecast as d


class TakeStepsTest(unittest.TestCase):
    def test_markers_are_removed_and_located(self):
        text, steps = d.take_steps("Intro here. [show] First point. [show] Second point.")
        self.assertEqual(text, "Intro here. First point. Second point.")
        self.assertEqual(steps, [1, 2])

    def test_marker_on_the_first_sentence(self):
        self.assertEqual(d.take_steps("[show] Right away. Then more.")[1], [0])

    def test_two_markers_on_one_sentence(self):
        self.assertEqual(d.take_steps("A. [show][show] B.")[1], [1, 1])

    def test_marker_left_at_the_end_joins_the_last_sentence(self):
        text, steps = d.take_steps("A. B. [show]")
        self.assertEqual((text, steps), ("A. B.", [1]))

    def test_no_markers(self):
        self.assertEqual(d.take_steps("Just talking."), ("Just talking.", []))

    def test_case_does_not_matter(self):
        self.assertEqual(d.take_steps("A. [SHOW] B.")[1], [1])

    def test_parse_script_keeps_steps(self):
        path = Path(tempfile.mkdtemp()) / "s.txt"
        path.write_text("Slide 1 - Hook\n\nHello. [show] One.\n\nSlide 2\n\nBye.\n",
                        encoding="utf-8")
        slides = d.parse_script(path)
        self.assertEqual(slides[0]["paragraph"], "Hello. One.")
        self.assertEqual(slides[0]["steps"], [1])
        self.assertEqual(slides[1]["steps"], [])


class StepCssTest(unittest.TestCase):
    def test_hides_only_later_steps(self):
        css = d.step_css(1, 3)
        self.assertIn('[data-step="2"]', css)
        self.assertIn('[data-step="3"]', css)
        self.assertNotIn('[data-step="1"]', css)

    def test_last_state_hides_nothing(self):
        self.assertEqual(d.step_css(3, 3), "")


class SegmentsTest(unittest.TestCase):
    def test_slide_without_steps_is_one_faded_picture(self):
        segs = d.picture_segments([["1.png"], ["2.png"]], [4.0, 5.0],
                                  [{"steps": []}, {"steps": []}], [[0.6], [4.6]])
        self.assertEqual(segs, [("1.png", 4.0, True, True), ("2.png", 5.0, True, True)])

    def test_steps_switch_picture_at_their_sentence(self):
        segs = d.picture_segments([["1-0.png", "1-1.png", "1-2.png"]], [10.0],
                                  [{"steps": [1, 2]}], [[0.6, 3.0, 7.0]])
        self.assertEqual(segs, [("1-0.png", 3.0, True, False),
                                ("1-1.png", 4.0, False, False),
                                ("1-2.png", 3.0, False, True)])

    def test_step_on_the_first_word_drops_the_empty_picture(self):
        segs = d.picture_segments([["a.png", "b.png"]], [5.0],
                                  [{"steps": [0]}], [[0.0, 2.0]])
        self.assertEqual(segs, [("b.png", 5.0, True, True)])

    def test_times_are_measured_from_the_slide_start(self):
        segs = d.picture_segments([["1.png"], ["2-0.png", "2-1.png"]], [4.0, 6.0],
                                  [{"steps": []}, {"steps": [1]}], [[0.6], [4.5, 7.0]])
        self.assertAlmostEqual(segs[1][1], 3.0)   # 4.0 -> 7.0
        self.assertAlmostEqual(segs[2][1], 3.0)   # 7.0 -> 10.0

    def test_sentences_are_grouped_by_slide(self):
        cues = [(0.6, 2, "a"), (2.3, 3, "b"), (4.1, 5, "c")]
        ranges = [(0.6, 3.0), (4.1, 5.0)]
        self.assertEqual(d.sentence_starts_per_slide(cues, ranges), [[0.6, 2.3], [4.1]])

    def test_fades_only_at_slide_edges(self):
        o = Namespace(format="video", fade=0.45, fps=30, no_fades=False, no_subs=True)
        graph, _ = d.build_filtergraph([("a", 3.0, True, False), ("b", 3.0, False, True)], o)
        first, second = graph.split(";")[:2]
        self.assertIn("fade=t=in", first)
        self.assertNotIn("fade=t=out", first)
        self.assertNotIn("fade=t=in", second)
        self.assertIn("fade=t=out", second)


if __name__ == "__main__":
    unittest.main()
