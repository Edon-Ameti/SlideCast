import json
import os
import tempfile
import time
import unittest
from pathlib import Path

import watch


def make(inbox, name, files, age=60):
    folder = inbox / name
    folder.mkdir()
    old = time.time() - age
    for file, text in files.items():
        (folder / file).write_text(text, encoding="utf-8")
        os.utime(folder / file, (old, old))
    return folder


class ReadyFoldersTest(unittest.TestCase):
    def setUp(self):
        self.inbox = Path(tempfile.mkdtemp())

    def ready(self):
        return [f.name for f, _, _ in watch.ready_folders(self.inbox)]

    def test_deck_and_script_is_ready(self):
        make(self.inbox, "a", {"deck.html": "", "voice.txt": ""})
        self.assertEqual(self.ready(), ["a"])

    def test_done_and_failed_are_skipped(self):
        make(self.inbox, "done", {"deck.html": "", "voice.txt": "", "video.mp4": ""})
        make(self.inbox, "failed", {"deck.html": "", "voice.txt": "", "error.txt": ""})
        self.assertEqual(self.ready(), [])

    def test_half_copied_is_skipped(self):
        make(self.inbox, "fresh", {"deck.html": "", "voice.txt": ""}, age=1)
        self.assertEqual(self.ready(), [])

    def test_missing_or_extra_files_are_skipped(self):
        make(self.inbox, "no-script", {"deck.html": ""})
        make(self.inbox, "two-decks", {"a.html": "", "b.html": "", "v.txt": ""})
        self.assertEqual(self.ready(), [])


class OptionsTest(unittest.TestCase):
    def test_settings_override_and_paths_are_relative_to_the_folder(self):
        inbox = Path(tempfile.mkdtemp())
        folder = make(inbox, "a", {"deck.html": "", "voice.txt": "", "settings.json":
                                   json.dumps({"voice": "am_adam", "format": "short",
                                               "music": "bed.mp3"})})
        opts = watch.options_for(folder, folder / "deck.html", folder / "voice.txt")
        self.assertEqual(opts.voice, "am_adam")
        self.assertEqual(opts.max_chars, 26)          # the Short default
        self.assertEqual(Path(opts.music), folder / "bed.mp3")
        self.assertEqual(Path(opts.out), folder / "video.mp4")

    def test_unknown_setting_is_refused(self):
        inbox = Path(tempfile.mkdtemp())
        folder = make(inbox, "a", {"deck.html": "", "voice.txt": "",
                                   "settings.json": json.dumps({"colour": "red"})})
        with self.assertRaises(ValueError):
            watch.options_for(folder, folder / "deck.html", folder / "voice.txt")


if __name__ == "__main__":
    unittest.main()
