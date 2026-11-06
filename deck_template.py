#!/usr/bin/env python3
"""Turn a deck the AI wrote (titles, bullets, narration) into SlideCast's two
inputs: a slide deck in HTML and a voiceover script.

One built-in design. Every size is measured in --u, a hundredth of the frame's
shorter side, so the same deck fills a wide video, a Short, a square or a tall
post without bars. It keeps the 'let currentSlide = 0;' line the renderer
switches slides with, and bullets carry data-step so they appear as spoken.
"""

import re
from html import escape, unescape

STYLE = """
:root{--u:min(1vw,1vh);--bg:#0b0d14;--text:#f2f4f8;--muted:#a3abbd;--accent:#ff7a1a}
*{box-sizing:border-box;margin:0}
html,body{height:100%;background:var(--bg);color:var(--text);
  font-family:"Segoe UI",system-ui,-apple-system,sans-serif;overflow:hidden}
.slide{position:fixed;inset:0;display:none;flex-direction:column;justify-content:center;
  padding:calc(var(--u)*9);gap:calc(var(--u)*3.2);
  background:radial-gradient(120% 90% at 0% 0%,#1a2033 0%,var(--bg) 60%),var(--bg)}
.slide.active{display:flex}
.slide::after{content:"";position:absolute;right:calc(var(--u)*-18);bottom:calc(var(--u)*-18);
  width:calc(var(--u)*55);height:calc(var(--u)*55);border-radius:50%;
  background:radial-gradient(circle,rgba(255,122,26,.18),transparent 70%)}
.bar{width:calc(var(--u)*10);height:calc(var(--u)*1.2);border-radius:99px;background:var(--accent)}
h1{font-size:calc(var(--u)*11);line-height:1.05;font-weight:800;letter-spacing:-.02em}
h2{font-size:calc(var(--u)*8.4);line-height:1.1;font-weight:800;letter-spacing:-.01em}
p.sub{font-size:calc(var(--u)*4.6);line-height:1.35;color:var(--muted);max-width:30em}
ul{list-style:none;padding:0;display:flex;flex-direction:column;gap:calc(var(--u)*3);
  margin-top:calc(var(--u)*1.5)}
li{display:flex;gap:calc(var(--u)*2.6);align-items:baseline;
  font-size:calc(var(--u)*6);line-height:1.25;font-weight:600}
li::before{content:"";flex:none;width:calc(var(--u)*2);height:calc(var(--u)*2);
  border-radius:50%;background:var(--accent);transform:translateY(-.15em)}
.statement{align-items:center;text-align:center}
.statement h2{font-size:calc(var(--u)*10);max-width:14em}
.statement .bar{order:-1}
/* On a tall frame the width is what limits the text, and a phone screen is
   read up close, so measure from the width and let lines wrap. */
@media (orientation:portrait){:root{--u:1.25vw}.slide{padding:calc(var(--u)*8)}}
"""

SCRIPT = """
const slides = [...document.querySelectorAll(".slide")];
let currentSlide = 0;
function updateDeck() {
  slides.forEach((s, i) => s.classList.toggle("active", i === currentSlide));
}
document.addEventListener("keydown", e => {
  if (["ArrowRight", " ", "Enter"].includes(e.key)) currentSlide = Math.min(currentSlide + 1, slides.length - 1);
  if (["ArrowLeft", "Backspace"].includes(e.key)) currentSlide = Math.max(currentSlide - 1, 0);
  updateDeck();
});
updateDeck();
"""


def slide_html(slide):
    kind = slide.get("kind", "statement")
    heading = escape(str(slide.get("heading", "")))
    sub = str(slide.get("subheading") or "").strip()
    sub_html = f'<p class="sub">{escape(sub)}</p>' if sub else ""
    if kind == "title":
        body = f'<div class="bar"></div><h1>{heading}</h1>{sub_html}'
    elif kind == "bullets":
        items = "".join(f'<li data-step="{n}">{escape(str(text))}</li>'
                        for n, text in enumerate(slide.get("bullets") or [], 1))
        body = f'<div class="bar"></div><h2>{heading}</h2>{sub_html}<ul>{items}</ul>'
    else:
        body = f'<h2>{heading}</h2>{sub_html}<div class="bar"></div>'
    return f'<section class="slide {escape(kind)}">{body}</section>'


def render_deck(deck, lang="en"):
    title = escape(str(deck.get("title") or "SlideCast deck"))
    sections = "\n".join(slide_html(s) for s in deck["slides"])
    return (f'<!DOCTYPE html>\n<html lang="{escape(lang)}">\n<head>\n<meta charset="UTF-8">\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f"<title>{title}</title>\n<style>{STYLE}</style>\n</head>\n<body>\n"
            f"{sections}\n<script>{SCRIPT}</script>\n</body>\n</html>\n")


def render_script(deck):
    """The voiceover in the 'Slide N - Label' format parse_script reads."""
    lines = [f"# {deck.get('title') or 'SlideCast deck'}", ""]
    for number, slide in enumerate(deck["slides"], 1):
        label = str(slide.get("label") or "").strip()
        lines += [f"Slide {number}" + (f" - {label}" if label else ""), "",
                  " ".join(str(slide["narration"]).split()), ""]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# translating a deck someone made by hand
# --------------------------------------------------------------------------

# Tags (and comments) at the odd positions of a split, text at the even ones.
TAG_SPLIT = re.compile(r"(<!--.*?-->|<[^>]+>)", re.S)
HIDDEN = re.compile(r"<\s*(/?)\s*(script|style|title)\b", re.I)


def visible_texts(html):
    """The HTML split into pieces, and which pieces are text a viewer sees."""
    parts, inside, where = TAG_SPLIT.split(html), None, []
    for index, part in enumerate(parts):
        if index % 2:
            tag = HIDDEN.match(part)
            if tag:
                inside = None if tag.group(1) else tag.group(2).lower()
        elif not inside and part.strip():
            where.append(index)
    return parts, where


def translate_html(html, translate):
    """Swap every piece of visible text for its translation. Tags, styles,
    scripts and the spacing around each piece stay exactly as they were.
    translate takes a list of strings and returns the same number back."""
    parts, where = visible_texts(html)
    texts = [" ".join(unescape(parts[i]).split()) for i in where]
    for index, text in zip(where, translate(texts)):
        piece = parts[index]
        lead = piece[:len(piece) - len(piece.lstrip())]
        trail = piece[len(piece.rstrip()):]
        parts[index] = lead + escape(text, quote=False) + trail
    return "".join(parts)
