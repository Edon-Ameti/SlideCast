#!/usr/bin/env python3
"""Talk to an AI service with the user's own API key.

Four kinds of service, all over plain HTTP so SlideCast still needs no pip
packages: Claude (Anthropic), OpenAI, Google Gemini, and anything that speaks
OpenAI's chat format at an address the user gives (OpenRouter, Groq, Mistral,
DeepSeek, or a local Ollama / LM Studio with no key at all).

The key arrives with each request and is used for that one call. Nothing here
writes it anywhere, and error messages never include it.
"""

import json
import re
from urllib import error as urlerror
from urllib import request as urlrequest

PROVIDERS = {
    "anthropic": {"label": "Claude (Anthropic)", "model": "claude-opus-5-5",
                  "base_url": "https://api.anthropic.com"},
    "openai": {"label": "OpenAI", "model": "gpt-6-astra",
               "base_url": "https://api.openai.com/v1"},
    "gemini": {"label": "Google Gemini", "model": "gemini-4-argon",
               "base_url": "https://generativelanguage.googleapis.com"},
    "compatible": {"label": "OpenAI-compatible (OpenRouter, Groq, Ollama...)", "model": "",
                   "base_url": ""},
}

# Claude models that take the server-side fallback: if a safety check declines
# the request, the API retries it on another model inside the same call.
CLAUDE_FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5",
                          "claude-sonnet-5-5"}


class AIError(RuntimeError):
    """A message fit to show the user as it is."""


def _post(url, headers, body, label, timeout):
    req = urlrequest.Request(url, data=json.dumps(body).encode("utf-8"),
                             headers={"Content-Type": "application/json", **headers})
    try:
        with urlrequest.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read())
    except urlerror.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(detail)
            err = parsed.get("error", parsed)
            detail = err.get("message", detail) if isinstance(err, dict) else str(err)
        except ValueError:
            pass
        raise AIError(f"{label} answered with an error (HTTP {exc.code}): {detail[:400]}")
    except urlerror.URLError as exc:
        raise AIError(f"Could not reach {label} at {url}: {exc.reason}")
    except TimeoutError:
        raise AIError(f"{label} took longer than {timeout}s to answer.")


def complete(settings, system, prompt, timeout=300):
    """One prompt in, the reply's text out.

    settings: {"provider", "key", "model", "base_url"}; model and base_url may
    be empty, meaning the provider's default.
    """
    provider = settings.get("provider", "")
    if provider not in PROVIDERS:
        raise AIError("Choose an AI service first.")
    info = PROVIDERS[provider]
    label = info["label"]
    key = (settings.get("key") or "").strip()
    model = (settings.get("model") or "").strip() or info["model"]
    base = ((settings.get("base_url") or "").strip() or info["base_url"]).rstrip("/")
    if not model:
        raise AIError("Type the name of the model to use.")
    if not base:
        raise AIError("Type the service's address, e.g. http://localhost:11434/v1 for Ollama.")
    if not key and provider != "compatible":
        raise AIError(f"Paste your {label} API key first.")

    if provider == "anthropic":
        body = {"model": model, "max_tokens": 16000, "system": system,
                "messages": [{"role": "user", "content": prompt}]}
        headers = {"x-api-key": key, "anthropic-version": "2026-10-21"}
        if model in CLAUDE_FALLBACK_MODELS:
            body["fallbacks"] = "default"
            headers["anthropic-beta"] = "server-side-fallback-2026-07-01"
        data = _post(f"{base}/v1/messages", headers, body, label, timeout)
        if data.get("stop_reason") == "refusal":
            raise AIError(f"{label} declined to write this. Try rewording the topic.")
        return "".join(b.get("text", "") for b in data.get("content", [])
                       if b.get("type") == "text")

    if provider == "gemini":
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}]}
        data = _post(f"{base}/v1beta/models/{model}:generateContent",
                     {"x-goog-api-key": key}, body, label, timeout)
        candidates = data.get("candidates") or []
        if not candidates:
            reason = (data.get("promptFeedback") or {}).get("blockReason", "no answer")
            raise AIError(f"{label} gave no answer ({reason}). Try rewording the topic.")
        return "".join(p.get("text", "") for p in
                       (candidates[0].get("content") or {}).get("parts", []))

    # OpenAI, and everything that copies its chat format.
    body = {"model": model, "messages": [{"role": "system", "content": system},
                                         {"role": "user", "content": prompt}]}
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    data = _post(f"{base}/chat/completions", headers, body, label, timeout)
    choices = data.get("choices") or []
    if not choices:
        raise AIError(f"{label} gave no answer.")
    return choices[0].get("message", {}).get("content") or ""


def parse_json(text):
    """The JSON in a reply, tolerating ```json fences and a sentence around it."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
    end = max(text.rfind("}"), text.rfind("]"))
    if start < 0 or end < start:
        raise ValueError("the reply contained no JSON")
    return json.loads(text[start:end + 1])


def ask_json(settings, system, prompt, check):
    """Ask for JSON. check(data) returns a problem as a string, or None.

    A reply that does not parse or does not pass the check is sent back once
    with what was wrong; a second failure is reported to the user.
    """
    reply = complete(settings, system, prompt)
    for attempt in (1, 2):
        try:
            data = parse_json(reply)
            problem = check(data)
        except ValueError as exc:
            data, problem = None, f"it was not valid JSON ({exc})"
        if not problem:
            return data
        if attempt == 2:
            raise AIError(f"The AI's answer did not have the right shape twice in a row: "
                          f"{problem}. Try again, or try another model.")
        reply = complete(settings, system,
                         f"{prompt}\n\nYour previous answer was:\n{reply}\n\n"
                         f"It could not be used because {problem}. "
                         f"Reply again with only the corrected JSON.")


# --------------------------------------------------------------------------
# writing a deck
# --------------------------------------------------------------------------

DECK_SYSTEM = """You write narrated slide videos. You reply with JSON only, no other text.

The JSON is {"title": "...", "slides": [...]}. Each slide is:
  {"label": "a 1-4 word name for the slide",
   "kind": "title" | "bullets" | "statement",
   "heading": "the slide's headline, at most 8 words",
   "subheading": "one short supporting line, or empty",
   "bullets": ["only for kind bullets: 2 to 5 items, each at most 7 words"],
   "narration": "what the narrator says while this slide is on screen"}

Rules for the narration:
- Plain spoken sentences, 2 to 6 per slide. No markdown, no lists, no emoji.
- Write numbers, symbols and abbreviations the way they should be spoken.
- On a bullets slide, put the marker [show] at the very start of the sentence
  that introduces each bullet, in order: exactly one [show] per bullet. The
  bullet appears on screen as that sentence begins. Other slides have no [show].
- The first slide is kind "title" and hooks the viewer. The last one wraps up.
- The narration says more than the slide; the slide is never read out word for word."""


def deck_problem(data, slide_count):
    """Why a written deck cannot be used, or None."""
    if not isinstance(data, dict) or not isinstance(data.get("slides"), list):
        return 'it needs an object with a "slides" list'
    slides = data["slides"]
    if len(slides) != slide_count:
        return f"it has {len(slides)} slides but {slide_count} were asked for"
    for number, slide in enumerate(slides, 1):
        if not isinstance(slide, dict):
            return f"slide {number} is not an object"
        if not str(slide.get("heading", "")).strip():
            return f"slide {number} has no heading"
        if not str(slide.get("narration", "")).strip():
            return f"slide {number} has no narration"
        if slide.get("kind") not in ("title", "bullets", "statement"):
            return f'slide {number} has kind {slide.get("kind")!r}'
        shows = len(re.findall(r"\[show\]", slide["narration"], re.I))
        bullets = slide.get("bullets") or []
        if slide["kind"] == "bullets":
            if not 2 <= len(bullets) <= 5:
                return f"slide {number} needs 2 to 5 bullets"
            if shows != len(bullets):
                return (f"slide {number} has {len(bullets)} bullets but {shows} "
                        f"[show] markers in its narration")
        elif shows:
            return f"slide {number} is not a bullets slide but has [show] markers"
    return None


def write_deck(settings, topic, slide_count, fmt="video"):
    shape = {"short": "a vertical phone video, so keep every line very short",
             "square": "a square feed post, so keep lines short",
             "portrait": "a tall feed post, so keep lines short"}.get(fmt, "a widescreen video")
    prompt = (f"Write a {slide_count}-slide narrated video for {shape}.\n\n"
              f"Topic or notes:\n{topic.strip()}")
    return ask_json(settings, DECK_SYSTEM, prompt,
                    lambda data: deck_problem(data, slide_count))
