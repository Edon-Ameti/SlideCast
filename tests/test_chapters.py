import unittest

import slidecast as d


class ChapterTest(unittest.TestCase):
    def test_time_format(self):
        self.assertEqual(d.chapter_time(0), "0:00")
        self.assertEqual(d.chapter_time(65.9), "1:05")
        self.assertEqual(d.chapter_time(3723), "1:02:03")

    def test_lines_start_where_each_slide_appears(self):
        slides = [{"n": 1, "label": "Hook"}, {"n": 2, "label": ""}, {"n": 3, "label": "End"}]
        self.assertEqual(d.chapter_lines(slides, [42.4, 30.0, 12.0]),
                         ["0:00 Hook", "0:42 Slide 2", "1:12 End"])

    def test_good_video_has_no_problems(self):
        self.assertEqual(d.chapter_problems([12, 15, 30]), [])

    def test_too_few_chapters(self):
        problems = d.chapter_problems([20, 20])
        self.assertEqual(len(problems), 1)
        self.assertIn("at least 3", problems[0])

    def test_short_chapters_are_named(self):
        problems = d.chapter_problems([12, 8, 30, 5])
        self.assertIn("slide 2, 4 are shorter", problems[0])


if __name__ == "__main__":
    unittest.main()
