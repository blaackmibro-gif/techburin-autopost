"""5-agent: postni sifat nazoratidan o‘tkazadi (qoidalar + Gemini tekshiruvi)."""
from __future__ import annotations

import html
import re

from ..gemini import Gemini

CYRILLIC = re.compile(r"[Ѐ-ӿ]")
PRICE = re.compile(
    r"(\$\s?\d|\d[\d\s.,]*\s?(\$|usd\b|dollar|so[‘’'`ʻ]?m\b|сум|mln\b|million so|ming so))", re.I)
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿⌀-⏿]")
TAG = re.compile(r"<[^>]+>")


def visible_text(caption_html: str) -> str:
    return html.unescape(TAG.sub("", caption_html))


def tg_len(text: str) -> int:
    """Telegram uzunlikni UTF-16 birliklarda hisoblaydi."""
    return len(text.encode("utf-16-le")) // 2


def rule_check(cfg: dict, post: dict, previous_titles: list[str]) -> tuple[list[str], list[str]]:
    """(jiddiy muammolar, ogohlantirishlar) qaytaradi."""
    from .topic import is_repeat

    p = cfg["post"]
    hard, soft = [], []
    caption_len = tg_len(visible_text(post["caption"]))
    if caption_len > p.get("caption_limit", 1024):
        hard.append(f"Caption is {caption_len} characters; Telegram limit is {p.get('caption_limit', 1024)}. Shorten the body.")
    main = f"{post['title']}\n{post['body']}"
    n = len(main)
    if n > p["body_max_chars"] * 1.15:
        hard.append(f"Title+body is {n} characters; target is {p['body_min_chars']}–{p['body_max_chars']}. Shorten it.")
    elif n < p["body_min_chars"] * 0.75:
        hard.append(f"Title+body is only {n} characters; target is {p['body_min_chars']}–{p['body_max_chars']}. Add one more useful point.")
    if p.get("script", "latin") == "latin":
        for field in ("title", "body", "audio_script"):
            if CYRILLIC.search(post[field]):
                hard.append(f"'{field}' contains Cyrillic letters; use Uzbek Latin only.")
    if PRICE.search(main) or PRICE.search(post["audio_script"]):
        hard.append("The text mentions a price or currency amount; prices are forbidden.")
    emojis = len(EMOJI.findall(main))
    if emojis > p.get("max_emoji", 4):
        hard.append(f"Too many emoji ({emojis}); use at most {p.get('max_emoji', 4)}.")
    if emojis == 0:
        soft.append("Sarlavhada emoji yo‘q")
    if re.search(r"\d", post["audio_script"]):
        hard.append("audio_script contains digits; write numbers as Uzbek words.")
    if not 250 <= len(post["audio_script"]) <= 700:
        hard.append(f"audio_script is {len(post['audio_script'])} characters; target 350–550.")
    if is_repeat(post["title"], previous_titles, threshold=0.8):
        hard.append("The title is almost identical to an earlier post; choose a different angle and title.")
    return hard, soft


REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "pass": {"type": "boolean"},
        "score": {"type": "integer"},
        "issues": {"type": "array", "items": {"type": "string"}},
        "summary_uz": {"type": "string"},
    },
    "required": ["pass", "score", "issues", "summary_uz"],
}

REVIEW_PROMPT = """You are the strict quality editor of a construction company's Telegram channel in Uzbekistan.
Review the draft below. Fail it if ANY rule is broken.

RULES
1. Forbidden content: {bans}
2. Every factual claim must be supported by the research notes. Claims with numbers, norms or standards
   that the notes do not clearly source are a failure. General, cautious advice is fine.
3. No invented clients, companies, projects, places or testimonials. Generic phrasing like «Mijozlar ko‘p so‘raydi» is fine.
4. Language: natural, grammatically correct Uzbek in Latin script (o‘, g‘ with ‘). No machine-translation feel,
   no unnecessary Russian words, no English words.
5. Useful: the reader gets at least one concrete, actionable piece of advice.
6. Tone: {tone}. Not salesy inside the body.
7. audio_script: spoken Uzbek, numbers in words, no emoji/links, starts with a greeting from Techburin Construct.
8. No dangerous advice (skipping geology, ignoring safety, unlicensed design changes).

DRAFT POST (as readers will see it):
---
{caption}
---
AUDIO SCRIPT:
---
{audio}
---
KEY CLAIMS (from the writer): {claims}

RESEARCH NOTES:
---
{notes}
---

Return JSON: pass (true only if all rules hold), score 1–10, issues (English, concrete, actionable fixes; empty if pass),
summary_uz (1–2 sentences in Uzbek Latin for the channel admin: what is good or what is wrong)."""


def llm_check(gemini: Gemini, cfg: dict, post: dict, notes: str) -> dict:
    q = cfg["quality"]
    bans = "; ".join(q["bans"] + ([q["extra_bans"]] if q.get("extra_bans") else []))
    prompt = REVIEW_PROMPT.format(
        bans=bans, tone=cfg["post"]["tone"], caption=visible_text(post["caption"]),
        audio=post["audio_script"], claims="; ".join(post.get("key_claims", [])) or "none", notes=notes,
    )
    res = gemini.json(prompt, REVIEW_SCHEMA, temperature=0.1)
    res["issues"] = [i for i in res.get("issues", []) if i]
    return res


IMAGE_SCHEMA = {
    "type": "object",
    "properties": {"pass": {"type": "boolean"}, "issues": {"type": "array", "items": {"type": "string"}}},
    "required": ["pass", "issues"],
}

IMAGE_PROMPT = """Check this image for a construction company's Telegram post about: "{title}".
Ignore the company logo in the bottom-right corner if there is one.
Fail it if ANY of these is true:
- visible text, letters, numbers, signs, watermarks or brand names (other than that logo);
- distorted people, hands, faces or physically impossible machinery;
- workers near machinery without hard hats, or clearly unsafe practice;
- it does not look related to construction / foundations / piling work;
- it looks like an obvious low-quality AI image.
Return JSON: pass, issues (short English phrases describing what to fix)."""


def image_check(gemini: Gemini, image: bytes, title: str) -> dict:
    return gemini.json(IMAGE_PROMPT.format(title=title), IMAGE_SCHEMA, temperature=0.1,
                       image=image, image_mime="image/jpeg")
