import json
import re
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import ai
import deck_template
import slidecast as d


class FakeService(BaseHTTPRequestHandler):
    """Answers like each provider would, and remembers what it was sent."""
    seen = []
    replies = []          # texts to answer with, in order
    status = 200

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        # Header names are case-insensitive, and urllib sends "X-api-key".
        FakeService.seen.append({"path": self.path, "body": body,
                                 "headers": {k.lower(): v for k, v in self.headers.items()}})
        if FakeService.status != 200:
            out = {"error": {"message": "invalid x-api-key"}}
            self.send_response(FakeService.status)
        else:
            text = FakeService.replies.pop(0) if FakeService.replies else "OK"
            if self.path.endswith("/v1/messages"):
                out = {"stop_reason": "end_turn",
                       "content": [{"type": "thinking", "thinking": ""},
                                   {"type": "text", "text": text}]}
            elif ":generateContent" in self.path:
                out = {"candidates": [{"content": {"parts": [{"text": text}]}}]}
            else:
                out = {"choices": [{"message": {"content": text}}]}
            self.send_response(200)
        data = json.dumps(out).encode()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class ProviderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeService)
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        FakeService.seen, FakeService.replies, FakeService.status = [], [], 200

    def ask(self, provider, **extra):
        settings = {"provider": provider, "key": "sk-test", "base_url": self.base, **extra}
        return ai.complete(settings, "be brief", "hello")

    def test_claude(self):
        self.assertEqual(self.ask("anthropic"), "OK")
        sent = FakeService.seen[0]
        self.assertEqual(sent["path"], "/v1/messages")
        self.assertEqual(sent["headers"]["x-api-key"], "sk-test")
        self.assertEqual(sent["headers"]["anthropic-version"], "2026-10-21")
        self.assertEqual(sent["body"]["model"], "claude-opus-5-5")
        self.assertEqual(sent["body"]["system"], "be brief")
        self.assertEqual(sent["body"]["messages"], [{"role": "user", "content": "hello"}])
        self.assertEqual(sent["body"]["fallbacks"], "default")
        self.assertNotIn("temperature", sent["body"])

    def test_claude_model_without_fallback(self):
        self.ask("anthropic", model="claude-haiku-5-5")
        sent = FakeService.seen[0]
        self.assertNotIn("fallbacks", sent["body"])
        self.assertNotIn("anthropic-beta", sent["headers"])

    def test_openai(self):
        self.assertEqual(self.ask("openai"), "OK")
        sent = FakeService.seen[0]
        self.assertEqual(sent["path"], "/chat/completions")
        self.assertEqual(sent["headers"]["authorization"], "Bearer sk-test")
        self.assertEqual(sent["body"]["messages"][0], {"role": "system", "content": "be brief"})

    def test_gemini(self):
        self.assertEqual(self.ask("gemini", model="gemini-test"), "OK")
        sent = FakeService.seen[0]
        self.assertEqual(sent["path"], "/v1beta/models/gemini-test:generateContent")
        self.assertEqual(sent["headers"]["x-goog-api-key"], "sk-test")
        self.assertEqual(sent["body"]["systemInstruction"]["parts"][0]["text"], "be brief")

    def test_compatible_without_a_key(self):
        settings = {"provider": "compatible", "key": "", "model": "llama3",
                    "base_url": self.base + "/v1"}
        self.assertEqual(ai.complete(settings, "s", "p"), "OK")
        sent = FakeService.seen[0]
        self.assertEqual(sent["path"], "/v1/chat/completions")
        self.assertNotIn("authorization", sent["headers"])

    def test_missing_key_is_explained(self):
        with self.assertRaises(ai.AIError) as caught:
            ai.complete({"provider": "openai", "key": ""}, "s", "p")
        self.assertIn("API key", str(caught.exception))

    def test_service_error_is_shown_without_the_key(self):
        FakeService.status = 401
        with self.assertRaises(ai.AIError) as caught:
            self.ask("anthropic")
        self.assertIn("invalid x-api-key", str(caught.exception))
        self.assertNotIn("sk-test", str(caught.exception))

    def test_bad_answer_is_retried_once(self):
        FakeService.replies = ["not json at all", json.dumps({"ok": 1})]
        data = ai.ask_json({"provider": "openai", "key": "k", "base_url": self.base},
                           "s", "p", lambda x: None)
        self.assertEqual(data, {"ok": 1})
        self.assertEqual(len(FakeService.seen), 2)
        self.assertIn("could not be used", FakeService.seen[1]["body"]["messages"][1]["content"])

    def test_two_bad_answers_give_up(self):
        FakeService.replies = ["nope", "still nope"]
        with self.assertRaises(ai.AIError):
            ai.ask_json({"provider": "openai", "key": "k", "base_url": self.base},
                        "s", "p", lambda x: None)


DECK = {"title": "Local first", "slides": [
    {"label": "Hook", "kind": "title", "heading": "Local-first is back",
     "subheading": "Three reasons", "narration": "Apps are moving home. Here is why."},
    {"label": "Why", "kind": "bullets", "heading": "Why it matters", "subheading": "",
     "bullets": ["Speed", "Privacy & control"],
     "narration": "Two things stand out. [show] First, speed. [show] Second, privacy."},
    {"label": "End", "kind": "statement", "heading": "Your data, your device",
     "subheading": "", "narration": "That is the case for local-first."}]}


class DeckTest(unittest.TestCase):
    def test_json_with_fences_and_chatter(self):
        self.assertEqual(ai.parse_json('Sure!\n```json\n{"a": [1]}\n```'), {"a": [1]})

    def test_good_deck_passes(self):
        self.assertIsNone(ai.deck_problem(DECK, 3))

    def test_problems_are_named(self):
        self.assertIn("2 were asked for", ai.deck_problem(DECK, 2))
        broken = json.loads(json.dumps(DECK))
        broken["slides"][1]["narration"] = "No markers here."
        self.assertIn("2 bullets but 0 [show]", ai.deck_problem(broken, 3))

    def test_rendered_deck_works_with_the_renderer(self):
        html = deck_template.render_deck(DECK)
        self.assertEqual(d.count_slides(html), 3)
        self.assertIn("let currentSlide = 0;", html)
        self.assertIn('data-step="2"', html)
        self.assertIn("Privacy &amp; control", html)

    def test_rendered_script_parses_with_its_steps(self):
        import tempfile
        from pathlib import Path
        path = Path(tempfile.mkdtemp()) / "s.txt"
        path.write_text(deck_template.render_script(DECK), encoding="utf-8")
        slides = d.parse_script(path)
        self.assertEqual([s["label"] for s in slides], ["Hook", "Why", "End"])
        self.assertEqual(slides[1]["steps"], [1, 2])
        self.assertNotIn("[show]", slides[1]["paragraph"])


if __name__ == "__main__":
    unittest.main()
