"""3-agent (bepul rejim): post uchun brend kartochka chizadi.

AI rasm o‘rniga: sariq-grafit fon (yoki assets/photos dagi obyekt rasmi), rubrika nomi,
post sarlavhasi, logo va aloqa ma’lumotlari. Hech qanday pullik API kerak emas.
"""
from __future__ import annotations

import io
import logging
import random
import re
import tempfile
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ..config import ROOT

log = logging.getLogger(__name__)

FONT_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/montserrat/Montserrat%5Bwght%5D.ttf"
FONT_CACHE = Path(tempfile.gettempdir()) / "techburin-montserrat.ttf"
FALLBACK_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]
EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\u2300-\u23FF\uFE0F\u200D]")

YELLOW = (242, 169, 0)
GRAPHITE = (43, 47, 51)
WHITE = (255, 255, 255)
SOFT = (205, 209, 213)


def _font_file() -> Path | None:
    local = sorted((ROOT / "assets" / "fonts").glob("*.ttf")) if (ROOT / "assets" / "fonts").exists() else []
    if local:
        return local[0]
    if not FONT_CACHE.exists():
        try:
            r = requests.get(FONT_URL, timeout=30)
            if r.status_code == 200 and len(r.content) > 100_000:
                FONT_CACHE.write_bytes(r.content)
        except requests.RequestException as e:
            log.warning("Shriftni yuklab bo‘lmadi: %s", e)
    if FONT_CACHE.exists():
        return FONT_CACHE
    for p in FALLBACK_FONTS:
        if Path(p).exists():
            return Path(p)
    return None


def _font(size: int, weight: int = 700) -> ImageFont.FreeTypeFont:
    path = _font_file()
    if path is None:
        return ImageFont.load_default(size)
    f = ImageFont.truetype(str(path), size)
    try:
        f.set_variation_by_axes([weight])
    except Exception:  # noqa: BLE001 — oddiy (o‘zgarmas) shriftlarda bu kerak emas
        pass
    return f


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        test = f"{cur} {word}".strip()
        if draw.textlength(test, font=font) <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _fit_title(draw, text: str, max_w: int, max_h: int):
    for size in range(84, 39, -4):
        font = _font(size, 800)
        lines = _wrap(draw, text, font, max_w)
        line_h = int(size * 1.18)
        if len(lines) * line_h <= max_h and all(draw.textlength(l, font=font) <= max_w for l in lines):
            return font, lines, line_h
    font = _font(40, 800)
    return font, _wrap(draw, text, font, max_w)[:6], int(40 * 1.18)


def _background(size: int, photos_dir: Path) -> Image.Image:
    photos = [p for p in photos_dir.glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")] \
        if photos_dir.exists() else []
    if photos:
        img = Image.open(random.choice(photos)).convert("RGB")
        w, h = img.size
        s = min(w, h)
        img = img.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s)).resize((size, size), Image.LANCZOS)
        img = img.filter(ImageFilter.GaussianBlur(1.2))
        shade = Image.new("RGB", (size, size), GRAPHITE)
        return Image.blend(img, shade, 0.62)
    # Fon: grafit, burchakda yengil sariq diagonal chiziqlar (qurilish ogohlantirish lentasi ruhida)
    img = Image.new("RGB", (size, size), GRAPHITE)
    d = ImageDraw.Draw(img)
    step = int(size * 0.055)
    for i in range(-size, size, step * 2):
        d.polygon([(size + i, 0), (size + i + step, 0), (i + step, size), (i, size)], fill=(50, 55, 60))
    return img


def make_card(cfg: dict, title: str) -> bytes:
    ic, p = cfg["image"], cfg["post"]
    size = int(ic.get("size_px", 1080))
    m = int(size * 0.075)
    img = _background(size, ROOT / ic.get("photos_dir", "assets/photos"))
    d = ImageDraw.Draw(img)

    # Yuqori: rubrika belgisi
    label = cfg["rubric"]["name"].upper()
    lf = _font(int(size * 0.03), 700)
    lw = d.textlength(label, font=lf)
    pad = int(size * 0.016)
    d.rectangle([m, m, m + lw + pad * 2, m + int(size * 0.03) + pad * 2], fill=YELLOW)
    d.text((m + pad, m + pad), label, font=lf, fill=GRAPHITE)

    # O‘rta: sarlavha
    clean = " ".join(EMOJI.sub("", title).split())
    top = m + int(size * 0.16)
    bottom_zone = int(size * 0.22)
    avail = size - top - bottom_zone - m
    font, lines, line_h = _fit_title(d, clean, size - 2 * m, avail)
    y = top + max(0, (avail - line_h * len(lines)) // 2)
    d.rectangle([m, y, m + int(size * 0.012), y + line_h * len(lines) - int(line_h * 0.18)], fill=YELLOW)
    for line in lines:
        d.text((m + int(size * 0.04), y), line, font=font, fill=WHITE)
        y += line_h

    # Pastki qism: chiziq, aloqa, logo
    base_y = size - m - int(size * 0.1)
    d.line([m, base_y, size - m, base_y], fill=YELLOW, width=max(3, size // 270))
    cf = _font(int(size * 0.03), 600)
    d.text((m, base_y + int(size * 0.03)), f"{p.get('phone', '')}", font=cf, fill=WHITE)
    d.text((m, base_y + int(size * 0.072)), p.get("site", ""), font=_font(int(size * 0.025), 500), fill=SOFT)

    logo_path = ROOT / ic.get("logo_path", "assets/logo.png")
    if logo_path.exists():
        logo = Image.open(logo_path).convert("RGBA")
        lh = int(size * 0.085)
        lw2 = int(logo.width * lh / logo.height)
        if lw2 > size * 0.35:
            lw2 = int(size * 0.35)
            lh = int(logo.height * lw2 / logo.width)
        logo = logo.resize((lw2, lh), Image.LANCZOS)
        base = img.convert("RGBA")
        base.alpha_composite(logo, (size - m - lw2, base_y + int(size * 0.025)))
        img = base.convert("RGB")
    else:
        name = cfg["company"]["name"].upper()
        nf = _font(int(size * 0.032), 800)
        d.text((size - m - d.textlength(name, font=nf), base_y + int(size * 0.035)), name, font=nf, fill=YELLOW)

    out = io.BytesIO()
    img.save(out, "JPEG", quality=92, optimize=True)
    return out.getvalue()
