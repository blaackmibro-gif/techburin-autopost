"""2-agent: mavzu bo‘yicha maslahatni topadi va postni berilgan stilda yozadi."""
from __future__ import annotations

import html
import json
import logging

from ..gemini import Gemini

log = logging.getLogger(__name__)

RESEARCH_PROMPT = """Research this topic for a short practical Telegram post for clients of a piling company in Uzbekistan.

Topic (Uzbek): {title}
Planned advice: {angle}
Suggested search: {query}

Use Google Search. Write concise research notes in English (max 400 words):
1. CORE ADVICE: the one practical recommendation the reader should take away.
2. SUPPORTING FACTS: 3–6 facts, each followed by the source name in brackets.
3. COMMON MISTAKES: 2–3 items.
4. NUMBERS / NORMS: only figures that a named source states; otherwise write "none".
5. DO NOT CLAIM: things that are uncertain, disputed or depend on the specific site.
Do not include prices."""

WRITER_SYSTEM = """You write posts for the Telegram channel of {company} ({about}).
Rubric: "{rubric}" — {direction}. Readers: {audience}.

OUTPUT LANGUAGE: Uzbek, Latin script only. Use ‘ (U+2018) in o‘ and g‘, and ’ (U+2019) for the tutuq belgisi (e’tibor, ta’mir).
Write naturally, like an experienced Uzbek site engineer explaining to a client. No Russian words where a common Uzbek word exists.

TONE: {tone}.

STRUCTURE of "title" + "body" (follow the style example closely):
- "title": one line, starts with ONE fitting emoji, then a clear question or promise, max 70 characters.
- "body": 1–2 sentences on the problem and why it matters, then 2–4 numbered points or short paragraphs with concrete advice, then one closing sentence.
- Sometimes (not every time) you may open the body with a common client question in « » quotes, like the hook example. Never invent a specific client, company, project or place.
- title + body together: {min_chars}–{max_chars} characters.
- At most 1 extra emoji inside the body (plus the one in the title).
- Do NOT add a call to action, phone, website, username or hashtags: they are added automatically.

FORBIDDEN in all text:
{bans}
- Facts that are not supported by the research notes. If a number or norm is not clearly sourced in the notes, give the advice without the number.
- Promises like "100% kafolat", "eng arzon", "eng yaxshi".

STYLE EXAMPLE (main style):
{style_example}

HOOK EXAMPLE (optional opening):
{hook_example}

ALSO PRODUCE:
- "audio_script": a spoken Uzbek (Latin) version for a voice message, {audio_scope}, 350–550 characters (≈30–45 seconds).
  Start with "Assalomu alaykum! Techburin Construct’dan foydali maslahat." End with "Batafsil — kanalimizdagi postda."
  Write every number in words, expand abbreviations (metr, millimetr), no emoji, no links, no hashtags, short sentences.
- "image_prompt": an English prompt for a {image_style_en} image that matches this post's topic.
  Setting: a real construction site in Uzbekistan (dusty ground, clear sky, modern residential blocks or infrastructure in the background).
  Show the relevant equipment or situation from the post (e.g. a bored piling rig, pile driver, rebar cage, drilling auger, soil layers).
  Workers wear safety gear. Brand colours as accents only: {brand_colors}.
  Natural daylight, sharp, realistic, professional photography, 1:1 composition, keep the bottom-right corner visually calm.
  Absolutely NO text, letters, numbers, signs, logos, watermarks or brand names anywhere in the image.
- "key_claims": the factual claims made in the post (in English), so a reviewer can check them.

Return ONLY JSON matching the schema."""

POST_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "body": {"type": "string"},
        "audio_script": {"type": "string"},
        "image_prompt": {"type": "string"},
        "key_claims": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "body", "audio_script", "image_prompt", "key_claims"],
}

IMAGE_STYLE_EN = {
    "Real foto": "photorealistic documentary-style photo",
    "Texnik grafika": "clean technical illustration / cross-section diagram style (still with no text)",
    "3D": "high-quality 3D render",
}


def _image_style(cfg: dict) -> str:
    style = cfg["image"].get("style", "")
    for key, val in IMAGE_STYLE_EN.items():
        if style.startswith(key):
            return val
    return "photorealistic documentary-style photo"


def _system(cfg: dict) -> str:
    p, q, r = cfg["post"], cfg["quality"], cfg["rubric"]
    bans = "\n".join(f"- {b}" for b in q["bans"])
    if q.get("extra_bans"):
        bans += f"\n- {q['extra_bans']}"
    return WRITER_SYSTEM.format(
        company=cfg["company"]["name"], about=cfg["company"]["about"], rubric=r["name"],
        direction=r["direction"], audience=", ".join(r["audience"]), tone=p["tone"],
        min_chars=p["body_min_chars"], max_chars=p["body_max_chars"], bans=bans,
        style_example=p["style_example"].strip(), hook_example=p.get("hook_example", "").strip(),
        audio_scope=cfg["audio"].get("scope", ""), image_style_en=_image_style(cfg),
        brand_colors=cfg["image"].get("brand_colors", ""),
    )


def research(gemini: Gemini, topic: dict) -> dict:
    res = gemini.text(
        RESEARCH_PROMPT.format(title=topic["title_uz"], angle=topic.get("angle", ""),
                               query=topic.get("search_query", topic["title_uz"])),
        search=True, temperature=0.3,
    )
    sources = res.sources or topic.get("discovery_sources", [])
    return {"notes": res.text.strip(), "sources": sources[:8]}


def write(gemini: Gemini, cfg: dict, topic: dict, notes: str) -> dict:
    prompt = (f"Topic: {topic['title_uz']}\nPlanned advice: {topic.get('angle', '')}\n\n"
              f"RESEARCH NOTES:\n{notes}\n\nWrite the post now.")
    data = gemini.json(prompt, POST_SCHEMA, system=_system(cfg), temperature=0.8)
    return finalize(cfg, data)


def rewrite(gemini: Gemini, cfg: dict, post: dict, notes: str, issues: list[str]) -> dict:
    draft = {k: post[k] for k in ("title", "body", "audio_script", "image_prompt", "key_claims")}
    prompt = ("A reviewer rejected this draft. Fix EVERY issue below, keep what is good, and return the full JSON again.\n\n"
              "ISSUES:\n" + "\n".join(f"- {i}" for i in issues) +
              f"\n\nDRAFT:\n{json.dumps(draft, ensure_ascii=False, indent=2)}\n\nRESEARCH NOTES:\n{notes}")
    data = gemini.json(prompt, POST_SCHEMA, system=_system(cfg), temperature=0.6)
    return finalize(cfg, data)


def finalize(cfg: dict, data: dict) -> dict:
    title = " ".join(data["title"].split())
    body = data["body"].strip()
    data["title"], data["body"] = title, body
    data["caption"] = build_caption(cfg, title, body)
    return data


def build_caption(cfg: dict, title: str, body: str) -> str:
    p = cfg["post"]
    contact_lines = [html.escape(p["cta"])]
    line = f"📞 {html.escape(p['phone'])}"
    if p.get("site"):
        line += f"  |  {html.escape(p['site'])}"
    contact_lines.append(line)
    if p.get("contact"):
        contact_lines.append(f"✍️ {html.escape(p['contact'])}")
    parts = [f"<b>{html.escape(title)}</b>", html.escape(body), "\n".join(contact_lines)]
    if p.get("hashtags"):
        parts.append(html.escape(p["hashtags"]))
    return "\n\n".join(parts)
