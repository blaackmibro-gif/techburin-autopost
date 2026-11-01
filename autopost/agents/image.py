"""3-agent: Nano Banana (Gemini) orqali post uchun rasm yaratadi va logoni qo‘yadi."""
from __future__ import annotations

import io
import logging

from PIL import Image

from ..config import ROOT
from ..gemini import Gemini

log = logging.getLogger(__name__)

NO_TEXT = (" No text, no letters, no numbers, no signs, no logos, no watermarks, "
           "no brand names on machines or clothing.")


def generate(gemini: Gemini, cfg: dict, prompt: str, extra: str = "") -> bytes:
    ic = cfg["image"]
    full = prompt.strip()
    if not ic.get("text_on_image"):
        full += NO_TEXT
    if extra:
        full += " " + extra
    raw = gemini.image(full, aspect_ratio=ic.get("aspect_ratio", "1:1"))
    return postprocess(cfg, raw)


def postprocess(cfg: dict, raw: bytes) -> bytes:
    ic = cfg["image"]
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    img = _fit(img, ic.get("aspect_ratio", "1:1"), int(ic.get("size_px", 1080)))
    logo_path = ROOT / ic.get("logo_path", "assets/logo.png")
    if logo_path.exists():
        img = _add_logo(img, logo_path, float(ic.get("logo_width_ratio", 0.18)), ic.get("logo_position", "bottom-right"))
    else:
        log.info("Logo fayli topilmadi (%s), rasm logosiz yuboriladi", logo_path)
    out = io.BytesIO()
    img.save(out, "JPEG", quality=92, optimize=True)
    return out.getvalue()


def _fit(img: Image.Image, ratio: str, width: int) -> Image.Image:
    w_r, h_r = (int(x) for x in ratio.split(":"))
    target = w_r / h_r
    w, h = img.size
    if abs(w / h - target) > 0.01:  # markazdan kesish
        if w / h > target:
            nw = int(h * target)
            img = img.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
        else:
            nh = int(w / target)
            img = img.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
    return img.resize((width, int(width * h_r / w_r)), Image.LANCZOS)


def _add_logo(img: Image.Image, path, width_ratio: float, position: str) -> Image.Image:
    logo = Image.open(path).convert("RGBA")
    lw = int(img.width * width_ratio)
    lh = int(logo.height * lw / logo.width)
    logo = logo.resize((lw, lh), Image.LANCZOS)
    m = int(img.width * 0.035)
    x = img.width - lw - m if "right" in position else m
    y = img.height - lh - m if "bottom" in position else m
    base = img.convert("RGBA")
    base.alpha_composite(logo, (x, y))
    return base.convert("RGB")
