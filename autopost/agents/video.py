"""7-agent: kartochka (yoki rasm) + ovozli maslahat + subtitrdan qisqa video.

Bepul: hech qanday pullik API yo‘q. Kadrlar Pillow bilan chiziladi, ffmpeg MP4 ga yig‘adi.
Kartochka sekin yaqinlashadi (Ken Burns), pastda ovozga mos subtitr chiqadi,
oxirida bir necha soniya telefon raqami ko‘rinib turadi.
"""
from __future__ import annotations

import io
import logging
import math
import re
import shutil
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from .card import EMOJI, GRAPHITE, SOFT, WHITE, YELLOW, _font, _wrap

log = logging.getLogger(__name__)

TRACK = (70, 75, 80)
LAYOUTS = {"4:5": (1080, 1350), "9:16": (1080, 1920)}


class VideoError(RuntimeError):
    pass


@dataclass
class Video:
    data: bytes
    width: int
    height: int
    duration: int          # butun video, soniya
    audio_seconds: float   # faqat ovoz qismi
    thumb: bytes


def settings(cfg: dict) -> dict:
    vc = {"enabled": True, "aspect_ratio": "4:5", "fps": 25, "subtitles": True, "end_seconds": 2,
          "zoom": 0.06, "crf": 23, "caption": "🎬 Video-maslahat"}
    vc.update(cfg.get("video") or {})
    return vc


def enabled(cfg: dict) -> bool:
    return bool(settings(cfg).get("enabled"))


def ffmpeg_exe() -> str | None:
    """Tizimdagi ffmpeg, bo‘lmasa imageio-ffmpeg paketidagi tayyor ffmpeg."""
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001 — paket o‘rnatilmagan bo‘lsa
        return None


# ---------------------------------------------------------------- subtitr
def clean_script(text: str) -> str:
    text = re.sub(r"\[[^\]]*\]", " ", text)          # ElevenLabs teglari: [calm], [pause] ...
    text = EMOJI.sub("", text)
    return " ".join(text.split())


def split_chunks(text: str, font, max_w: int, max_lines: int) -> list[str]:
    """Matnni ekranga sig‘adigan bo‘laklarga bo‘ladi: avval gaplar, keyin so‘zlar bo‘yicha."""
    d = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    sentences = [s for s in re.split(r"(?<=[.!?…])\s+", text) if s.strip()]
    chunks = []
    for sent in sentences:
        cur = ""
        for word in sent.split():
            test = f"{cur} {word}".strip()
            if len(_wrap(d, test, font, max_w)) <= max_lines:
                cur = test
            else:
                if cur:
                    chunks.append(cur)
                cur = word
        if cur:
            chunks.append(cur)
    # Juda qisqa qoldiqni (1–2 so‘z) oldingi bo‘lakka qo‘shishga urinamiz
    merged = []
    for c in chunks:
        if merged and len(c.split()) <= 2 and not re.search(r"[.!?…]$", merged[-1]):
            test = f"{merged[-1]} {c}"
            if len(_wrap(d, test, font, max_w)) <= max_lines:
                merged[-1] = test
                continue
        merged.append(c)
    return merged


def timings(chunks: list[str], total: float, lead: float = 0.15) -> list[tuple[float, float]]:
    """Har bo‘lakka ovoz uzunligini harflar soniga qarab taqsimlaydi (gap oxiridagi pauza hisobga olinadi)."""
    weights = [len(c) + (8 if re.search(r"[.!?…]$", c) else 3 if c.endswith(",") else 0) for c in chunks]
    span = max(total - lead, 0.5)
    out, t = [], lead
    for w in weights:
        dur = span * w / sum(weights)
        out.append((t, t + dur))
        t += dur
    return out


# ---------------------------------------------------------------- audio
def _decode_audio(ffmpeg: str, audio: bytes, workdir: Path) -> tuple[Path, float]:
    src, wav = workdir / "voice.bin", workdir / "voice.wav"
    src.write_bytes(audio)
    p = subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(src), "-ac", "1", "-ar", "44100", str(wav)],
                       capture_output=True)
    if p.returncode != 0 or not wav.exists():
        raise VideoError(f"Ovozni o‘qib bo‘lmadi: {p.stderr.decode(errors='ignore')[:200]}")
    with wave.open(str(wav)) as w:
        seconds = w.getnframes() / float(w.getframerate())
    if seconds < 1:
        raise VideoError("Ovoz juda qisqa")
    return wav, seconds


# ---------------------------------------------------------------- kadrlar
def _ease(x: float) -> float:
    return 0.5 - 0.5 * math.cos(math.pi * min(max(x, 0.0), 1.0))


def _text_block(size: tuple[int, int], lines: list[tuple[str, object, tuple]], gap: float = 1.22) -> Image.Image:
    """Markazlangan qatorlar (matn, shrift, rang) bilan shaffof qatlam."""
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    heights = [int(f.size * gap) for _, f, _ in lines]
    y = (size[1] - sum(heights)) // 2
    for (text, font, color), h in zip(lines, heights):
        x = (size[0] - d.textlength(text, font=font)) / 2
        d.text((x, y), text, font=font, fill=color)
        y += h
    return layer


def make_video(cfg: dict, image: bytes, audio: bytes, script: str) -> Video:
    vc, p = settings(cfg), cfg["post"]
    ffmpeg = ffmpeg_exe()
    if not ffmpeg:
        raise VideoError("ffmpeg topilmadi (requirements.txt ga imageio-ffmpeg qo‘shilganini tekshiring)")
    ratio = str(vc.get("aspect_ratio", "4:5"))
    if ratio not in LAYOUTS:
        log.warning("video.aspect_ratio=%s qo‘llanmaydi, 4:5 ishlatiladi", ratio)
        ratio = "4:5"
    W, H = LAYOUTS[ratio]
    fps = int(vc.get("fps", 25))

    card = Image.open(io.BytesIO(image)).convert("RGB")
    if card.size != (W, W):
        s = min(card.size)
        card = card.crop(((card.width - s) // 2, (card.height - s) // 2,
                          (card.width - s) // 2 + s, (card.height - s) // 2 + s)).resize((W, W), Image.LANCZOS)

    # Joylashuv: tepada kvadrat kartochka, pastda subtitr maydoni
    card_y = 0 if ratio == "4:5" else (H - W) // 3
    band_top = card_y + W
    band_h = H - band_top
    bar_h = 8
    margin = int(W * 0.065)
    sub_size = 46 if ratio == "4:5" else 58
    max_lines = 2 if ratio == "4:5" else 3
    sub_font = _font(sub_size, 700)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        wav, seconds = _decode_audio(ffmpeg, audio, tmp)
        end_s = float(vc.get("end_seconds", 2))
        total = seconds + end_s
        n_frames = int(math.ceil(total * fps))

        band_size = (W, band_h - bar_h)
        subs = []
        if vc.get("subtitles", True):
            chunks = split_chunks(clean_script(script), sub_font, W - 2 * margin, max_lines)
            d = ImageDraw.Draw(Image.new("RGB", (8, 8)))
            for c, (a, b) in zip(chunks, timings(chunks, seconds)):
                lines = [(ln, sub_font, WHITE) for ln in _wrap(d, c, sub_font, W - 2 * margin)]
                subs.append((a, b, _text_block(band_size, lines)))

        # Oxirgi kadr: chaqiriq va telefon
        end_lines = [("Bepul maslahat uchun qo‘ng‘iroq qiling", _font(int(sub_size * 0.72), 600), SOFT),
                     (p.get("phone", ""), _font(int(sub_size * 1.25), 800), YELLOW)]
        if p.get("site"):
            end_lines.append((p["site"], _font(int(sub_size * 0.62), 500), SOFT))
        end_layer = _text_block(band_size, end_lines, gap=1.3)

        base = Image.new("RGB", (W, H), GRAPHITE)

        zoom = float(vc.get("zoom", 0.06))
        cx, cy = W / 2, W * 0.47   # sarlavha markaziga sal yaqinroq
        fade_in = 0.4

        out = tmp / "video.mp4"
        log_path = tmp / "ffmpeg.log"
        cmd = [ffmpeg, "-y", "-loglevel", "error",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
               "-i", str(wav), "-af", "apad",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", str(vc.get("crf", 23)), "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", str(out)]
        thumb_frame = None
        with open(log_path, "wb") as logf:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=logf)
            try:
                for i in range(n_frames):
                    t = i / fps
                    z = 1 + zoom * _ease(t / total)
                    half = W / (2 * z)
                    x0 = min(max(cx - half, 0), W - 2 * half)
                    y0 = min(max(cy - half, 0), W - 2 * half)
                    frame = base.copy()
                    frame.paste(card.resize((W, W), Image.BICUBIC, box=(x0, y0, x0 + 2 * half, y0 + 2 * half)),
                                (0, card_y))

                    layer, alpha = None, 1.0
                    if t >= seconds:
                        layer, alpha = end_layer, min((t - seconds) / 0.25, 1.0)
                    else:
                        for a, b, lay in subs:
                            if a <= t < b:
                                layer, alpha = lay, min((t - a) / 0.12, 1.0)
                                break
                    if layer is not None:
                        if alpha < 1:
                            layer = layer.copy()
                            layer.putalpha(layer.getchannel("A").point(lambda v, k=alpha: int(v * k)))
                        frame.paste(layer, (0, band_top), layer)

                    dr = ImageDraw.Draw(frame)
                    dr.rectangle([0, H - bar_h, W, H], fill=TRACK)
                    dr.rectangle([0, H - bar_h, int(W * min(t / seconds, 1.0)), H], fill=YELLOW)

                    if t < fade_in:
                        frame = Image.blend(Image.new("RGB", (W, H), GRAPHITE), frame, t / fade_in)
                    if thumb_frame is None and t >= min(1.5, seconds / 2):
                        thumb_frame = frame.copy()
                    proc.stdin.write(frame.tobytes())
                proc.stdin.close()
                code = proc.wait(timeout=300)
            except BrokenPipeError:
                code = proc.wait(timeout=60)
            except Exception:
                proc.kill()
                raise
        if code != 0 or not out.exists():
            raise VideoError(f"ffmpeg videoni yig‘a olmadi: {log_path.read_text(errors='ignore')[-300:]}")
        data = out.read_bytes()

    if len(data) > 45 * 1024 * 1024:
        raise VideoError(f"Video juda katta ({len(data) // 1048576} MB), Telegram 50 MB dan kattasini qabul qilmaydi")

    thumb = (thumb_frame or card).copy()
    thumb.thumbnail((320, 320))
    tb = io.BytesIO()
    thumb.save(tb, "JPEG", quality=85)
    log.info("Video tayyor: %.1f s, %d KB", total, len(data) // 1024)
    return Video(data, W, H, int(round(total)), seconds, tb.getvalue())
