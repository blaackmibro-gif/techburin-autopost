"""1-agent: rubrika bo‘yicha internetdan yangi mavzu izlaydi."""
from __future__ import annotations

import difflib
import logging
import re

from ..gemini import Gemini, extract_json

log = logging.getLogger(__name__)

SYSTEM = """You are the topic researcher for the Telegram channel of {company}.
About the company: {about}
You find topics for the rubric "{rubric}" whose direction is: {direction}.
Readers: {audience}.
Readers are in Uzbekistan. Topics must be practical, help a reader make a better decision about
foundations, piles, drilling or site work, and naturally lead them to ask the company for advice.
Never propose topics about prices, discounts, competitors, politics or religion."""

PROMPT = """Use Google Search to find 6 fresh, concrete topic ideas for the next post.

Preferred source types:
{sources}

Topics already published or drafted (do NOT repeat or closely paraphrase them):
{history}

Rules:
- Each topic must be answerable with one clear, actionable piece of advice in a short post.
- Prefer evergreen client problems (choosing pile type, geology, neighbouring buildings, winter work,
  quality control, documents, mistakes to avoid) and use industry news only if it gives a practical tip.
- Mix angles over time: mistakes, checklists, comparisons, "how it works", myths vs facts.
- Write titles in Uzbek (Latin script), max 70 characters.

Return ONLY a JSON object, no other text:
{{"topics": [{{"title_uz": "...", "angle": "one sentence in English: what advice the post gives",
  "why_useful": "one sentence in English", "search_query": "short English or Russian query to research it"}}]}}"""


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9а-яё ]+", "", s.lower().replace("‘", "").replace("’", "").replace("'", ""))


def is_repeat(title: str, previous: list[str], threshold: float = 0.72) -> bool:
    t = _norm(title)
    return any(difflib.SequenceMatcher(None, t, _norm(p)).ratio() >= threshold for p in previous)


def find_topic(gemini: Gemini, cfg: dict, previous_titles: list[str]) -> dict:
    r = cfg["rubric"]
    system = SYSTEM.format(
        company=cfg["company"]["name"], about=cfg["company"]["about"], rubric=r["name"],
        direction=r["direction"], audience=", ".join(r["audience"]),
    )
    history = "\n".join(f"- {t}" for t in previous_titles[-80:]) or "- (hali yo‘q)"
    res = gemini.text(PROMPT.format(sources=r.get("sources", ""), history=history), system=system,
                      search=True, temperature=0.9)
    data = extract_json(res.text)
    topics = [t for t in data.get("topics", []) if t.get("title_uz")]
    if not topics:
        raise RuntimeError("1-agent mavzu topa olmadi")
    for t in topics:
        if not is_repeat(t["title_uz"], previous_titles):
            t["discovery_sources"] = res.sources[:6]
            log.info("Tanlangan mavzu: %s", t["title_uz"])
            return t
    log.warning("Hamma mavzular takror bo‘lib chiqdi, birinchisi olinadi")
    topics[0]["discovery_sources"] = res.sources[:6]
    return topics[0]
