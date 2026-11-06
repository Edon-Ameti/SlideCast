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


# --------------------------------------------------------------------------
# translating
# --------------------------------------------------------------------------

TRANSLATE_SYSTEM = """You translate narrated videos. Reply with JSON only, no other text.

Translate every piece of text into {language}. Keep exactly the same structure,
and the same number of items in every list. Each sentence stays one sentence:
never split or merge sentences, and never put a full stop inside one. Keep the
names of products, people and code as they are. Write numbers and symbols the
way they should be spoken."""


def _same_shape(data, original, key):
    if not isinstance(data, dict) or not isinstance(data.get(key), list):
        return f'it needs an object with a "{key}" list'
    if len(data[key]) != len(original):
        return f"it has {len(data[key])} {key} but the original has {len(original)}"
    return None


def translate_script(settings, slides, language, count_sentences):
    """slides: [{"label", "sentences": [...]}]. Returns the same shape translated,
    with one sentence for each sentence, so subtitles in either language line
    up with the voice. count_sentences says how many sentences SlideCast sees in
    a text, which catches a translation that sneaks a full stop into one."""
    def check(data):
        problem = _same_shape(data, slides, "slides")
        if problem:
            return problem
        for number, (mine, theirs) in enumerate(zip(slides, data["slides"]), 1):
            got = theirs.get("sentences") if isinstance(theirs, dict) else None
            if not isinstance(got, list) or len(got) != len(mine["sentences"]):
                return (f"slide {number} needs exactly {len(mine['sentences'])} sentences "
                        f"in its sentences list")
            for index, sentence in enumerate(got, 1):
                if count_sentences(str(sentence)) != 1:
                    return (f"sentence {index} of slide {number} reads as more than one "
                            f"sentence; join it into one")
        return None

    system = TRANSLATE_SYSTEM.format(language=language)
    return ask_json(settings, system, json.dumps({"slides": slides}, ensure_ascii=False), check)


def translated_script(original, translated):
    """The translation as a script, with each [show] back on its sentence."""
    lines = []
    for slide, done in zip(original, translated["slides"]):
        sentences = [("[show] " * slide["steps"].count(i)) + str(s).strip()
                     for i, s in enumerate(done["sentences"])]
        label = str(done.get("label") or "").strip()
        lines += [f"Slide {slide['n']}" + (f" - {label}" if label else ""), "",
                  " ".join(sentences), ""]
    return "\n".join(lines)


def translate_texts(settings, texts, language):
    """A list of strings in, the same number of strings out."""
    def check(data):
        problem = _same_shape(data, texts, "texts")
        return problem or (None if all(isinstance(t, str) for t in data["texts"])
                           else "every item in texts must be a string")

    system = TRANSLATE_SYSTEM.format(language=language)
    return ask_json(settings, system, json.dumps({"texts": texts}, ensure_ascii=False),
                    check)["texts"]


def translate_deck(settings, deck, language):
    """The words on an AI-written deck's slides, translated. Kinds and the
    number of bullets are kept from the original, so the design cannot break."""
    fields = [{"label": s.get("label", ""), "heading": s.get("heading", ""),
               "subheading": s.get("subheading", ""), "bullets": s.get("bullets") or []}
              for s in deck["slides"]]

    def check(data):
        problem = _same_shape(data, fields, "slides")
        if problem:
            return problem
        for number, (mine, theirs) in enumerate(zip(fields, data["slides"]), 1):
            if not isinstance(theirs, dict) or len(theirs.get("bullets") or []) != len(mine["bullets"]):
                return f"slide {number} needs exactly {len(mine['bullets'])} bullets"
        return None

    system = TRANSLATE_SYSTEM.format(language=language)
    done = ask_json(settings, system, json.dumps({"slides": fields}, ensure_ascii=False), check)
    slides = [{**original, **{k: theirs.get(k, original.get(k)) for k in
                              ("label", "heading", "subheading", "bullets")}}
              for original, theirs in zip(deck["slides"], done["slides"])]
    return {**deck, "slides": slides}
