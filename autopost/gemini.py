"""Gemini API bilan ishlash: matn, internet qidiruvi, JSON, rasm ko‘rish va rasm yaratish."""
from __future__ import annotations

import base64
import json
import logging
import re
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

_TRANSIENT = ("429", "500", "502", "503", "504", "RESOURCE_EXHAUSTED", "UNAVAILABLE", "DEADLINE")


@dataclass
class TextResult:
    text: str
    sources: list[dict] = field(default_factory=list)  # [{"title":..., "url":...}]
    model: str = ""


class GeminiError(RuntimeError):
    pass


def extract_json(text: str):
    """Model javobidan JSON obyektni ajratib olish (```json bloklari ham hisobga olinadi)."""
    if text is None:
        raise GeminiError("Model bo‘sh javob qaytardi")
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    start = min([i for i in (t.find("{"), t.find("[")) if i >= 0], default=-1)
    if start < 0:
        raise GeminiError(f"Javobda JSON topilmadi: {text[:200]}")
    opener = t[start]
    closer = "}" if opener == "{" else "]"
    end = t.rfind(closer)
    if end <= start:
        raise GeminiError(f"Javobda JSON topilmadi: {text[:200]}")
    return json.loads(t[start : end + 1])


class Gemini:
    def __init__(self, api_key: str, text_models: list[str], image_models: list[str]):
        from google import genai  # kutubxona faqat kerak bo‘lganda yuklanadi

        self.client = genai.Client(api_key=api_key)
        self.text_models = [m for m in text_models if m]
        self.image_models = [m for m in image_models if m]

    # ---------- umumiy ----------
    def _call(self, models: list[str], fn, what: str):
        errors = []
        for model in models:
            for attempt in range(2):
                try:
                    return fn(model)
                except Exception as e:  # noqa: BLE001
                    msg = str(e)
                    errors.append(f"{model}: {msg[:300]}")
                    if attempt == 0 and any(code in msg for code in _TRANSIENT):
                        log.warning("%s: %s vaqtincha xato, qayta urinish: %s", what, model, msg[:200])
                        time.sleep(8)
                        continue
                    log.warning("%s: %s ishlamadi: %s", what, model, msg[:300])
                    break
        raise GeminiError(f"{what} bajarilmadi. " + " | ".join(errors[-3:]))

    # ---------- matn ----------
    def text(self, prompt: str, system: str | None = None, search: bool = False,
             temperature: float = 0.7) -> TextResult:
        from google.genai import types

        def run(model):
            cfg = types.GenerateContentConfig(
                system_instruction=system,
                temperature=temperature,
                tools=[types.Tool(google_search=types.GoogleSearch())] if search else None,
            )
            resp = self.client.models.generate_content(model=model, contents=prompt, config=cfg)
            text = resp.text
            if not text:
                raise GeminiError("bo‘sh javob")
            return TextResult(text=text, sources=_sources(resp), model=model)

        return self._call(self.text_models, run, "Matn yaratish")

    def json(self, prompt: str, schema: dict, system: str | None = None,
             temperature: float = 0.5, image: bytes | None = None, image_mime: str = "image/png"):
        from google.genai import types

        def run(model):
            cfg = types.GenerateContentConfig(
                system_instruction=system,
                temperature=temperature,
                response_mime_type="application/json",
                response_json_schema=schema,
            )
            contents = prompt
            if image is not None:
                contents = [types.Part.from_bytes(data=image, mime_type=image_mime), prompt]
            resp = self.client.models.generate_content(model=model, contents=contents, config=cfg)
            return extract_json(resp.text)

        return self._call(self.text_models, run, "JSON javob olish")

    # ---------- rasm ----------
    def image(self, prompt: str, aspect_ratio: str = "1:1") -> bytes:
        from google.genai import types

        def via_generate_content(model, modalities):
            cfg = types.GenerateContentConfig(
                response_modalities=modalities,
                image_config=types.ImageConfig(aspect_ratio=aspect_ratio),
            )
            resp = self.client.models.generate_content(model=model, contents=prompt, config=cfg)
            for cand in resp.candidates or []:
                for part in (cand.content.parts if cand.content else []) or []:
                    data = getattr(getattr(part, "inline_data", None), "data", None)
                    if data:
                        return data if isinstance(data, bytes) else base64.b64decode(data)
            raise GeminiError("javobda rasm yo‘q")

        def via_interactions(model):
            inter = self.client.interactions.create(
                model=model,
                input=prompt,
                response_format={"type": "image", "mime_type": "image/png", "aspect_ratio": aspect_ratio},
            )
            img = getattr(inter, "output_image", None)
            if not img or not getattr(img, "data", None):
                raise GeminiError("javobda rasm yo‘q")
            return base64.b64decode(img.data)

        def run(model):
            errors = []
            for strategy in (
                lambda: via_generate_content(model, ["IMAGE"]),
                lambda: via_generate_content(model, ["TEXT", "IMAGE"]),
                lambda: via_interactions(model),
            ):
                try:
                    return strategy()
                except Exception as e:  # noqa: BLE001
                    errors.append(str(e)[:200])
            raise GeminiError(" / ".join(errors))

        return self._call(self.image_models, run, "Rasm yaratish")


def _sources(resp) -> list[dict]:
    out, seen = [], set()
    try:
        meta = resp.candidates[0].grounding_metadata
        chunks = getattr(meta, "grounding_chunks", None) or []
    except (AttributeError, IndexError, TypeError):
        return out
    for ch in chunks:
        web = getattr(ch, "web", None)
        if not web or not getattr(web, "uri", None):
            continue
        if web.uri in seen:
            continue
        seen.add(web.uri)
        out.append({"title": getattr(web, "title", "") or "", "url": web.uri})
    return out
