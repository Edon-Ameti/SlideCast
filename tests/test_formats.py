import unittest
from argparse import Namespace

import slidecast as d


def opts(fmt, **extra):
    base = dict(format=fmt, fade=0.45, fps=30, no_fades=False, no_subs=False,
                bold=False, font="Arial", font_size=54, outline=4, margin_v=20)
    base.update(extra)
    return Namespace(**base)


class FormatTest(unittest.TestCase):
    def test_sizes(self):
        self.assertEqual(d.frame_size(opts("video")), (1920, 1080))
        self.assertEqual(d.frame_size(opts("short")), (1080, 1920))
        self.assertEqual(d.frame_size(opts("square")), (1080, 1080))
        self.assertEqual(d.frame_size(opts("portrait")), (1080, 1350))

    def test_missing_format_means_video(self):
        self.assertEqual(d.frame_size(Namespace()), (1920, 1080))

    def test_filtergraph_scales_to_the_frame(self):
        graph, _ = d.build_filtergraph([2.0, 3.0], opts("short"))
        self.assertIn("scale=1080:1920", graph)
        self.assertNotIn("1920:1080", graph)

    def test_subtitles_use_the_real_frame(self):
        import tempfile
        from pathlib import Path
        path = Path(tempfile.mkdtemp()) / "s.ass"
        d.write_ass(path, [(0, 1, "hello", None)], opts("short"))
        text = path.read_text(encoding="utf-8")
        self.assertIn("PlayResX: 1080", text)
        self.assertIn("PlayResY: 1920", text)

    def test_command_line_fills_format_defaults(self):
        parser = d.build_parser()
        args = parser.parse_args(["deck.html", "script.txt", "--format", "short"])
        self.assertIsNone(args.font_size)   # filled in by main() from FORMATS
        self.assertEqual(d.FORMATS["short"]["max_chars"], 26)


if __name__ == "__main__":
    unittest.main()
