"""4-agent: ElevenLabs orqali maslahatni ovozli xabarga aylantiradi."""
from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import requests

log = logging.getLogger(__name__)
API = "https://api.elevenlabs.io"


class AudioError(RuntimeError):
    pass


@dataclass
class Voice:
    data: bytes
    filename: str
    mime: str
    duration: int | None
    voice_id: str
    model: str


class ElevenLabs:
    def __init__(self, api_key: str):
        self.headers = {"xi-api-key": api_key}

    def voices(self) -> list[dict]:
        r = requests.get(f"{API}/v1/voices", headers=self.headers, timeout=60)
        if r.status_code != 200:
            raise AudioError(f"Ovozlar ro‘yxatini olib bo‘lmadi: {r.status_code} {r.text[:200]}. "
                             "API kalitida «Voices → Read» ruxsati yoqilganini tekshiring yoki config.yaml'da audio.voice_id ni yozing.")
        return r.json().get("voices", [])

    def pick_voice(self, gender: str = "male") -> str:
        voices = self.voices()
        if not voices:
            raise AudioError("Akkauntda ovoz topilmadi")
        for v in voices:
            if (v.get("labels") or {}).get("gender", "").lower() == gender.lower():
                return v["voice_id"]
        return voices[0]["voice_id"]

    def tts(self, text: str, voice_id: str, model: str, language_code: str | None) -> bytes:
        body = {"text": text, "model_id": model}
        if language_code:
            body["language_code"] = language_code
        r = requests.post(f"{API}/v1/text-to-speech/{voice_id}", params={"output_format": "mp3_44100_128"},
                          headers={**self.headers, "accept": "audio/mpeg"}, json=body, timeout=180)
        if r.status_code == 400 and language_code and "language" in r.text.lower():
            body.pop("language_code")  # model tilni majburlashni qo‘llamasa
            r = requests.post(f"{API}/v1/text-to-speech/{voice_id}", params={"output_format": "mp3_44100_128"},
                              headers={**self.headers, "accept": "audio/mpeg"}, json=body, timeout=180)
        if r.status_code != 200:
            raise AudioError(f"{model}: {r.status_code} {r.text[:300]}")
        return r.content


def speak(el: ElevenLabs, cfg: dict, text: str) -> Voice:
    ac = cfg["audio"]
    voice_id = ac.get("voice_id") or el.pick_voice(ac.get("voice_gender", "male"))
    errors = []
    for model in [ac.get("model"), ac.get("fallback_model")]:
        if not model:
            continue
        try:
            mp3 = el.tts(text, voice_id, model, ac.get("language_code"))
            return _to_voice(mp3, voice_id, model)
        except AudioError as e:
            errors.append(str(e))
            log.warning("TTS xatosi: %s", e)
    raise AudioError(" | ".join(errors))


def _to_voice(mp3: bytes, voice_id: str, model: str) -> Voice:
    """Telegram ovozli xabari uchun OGG/Opus ga o‘tkazish. ffmpeg bo‘lmasa, MP3 yuboriladi."""
    if not shutil.which("ffmpeg"):
        return Voice(mp3, "maslahat.mp3", "audio/mpeg", None, voice_id, model)
    with tempfile.TemporaryDirectory() as d:
        src, dst = Path(d) / "in.mp3", Path(d) / "out.ogg"
        src.write_bytes(mp3)
        proc = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-ac", "1",
                               "-c:a", "libopus", "-b:a", "64k", str(dst)], capture_output=True)
        if proc.returncode != 0 or not dst.exists():
            log.warning("ffmpeg o‘tkaza olmadi, MP3 yuboriladi: %s", proc.stderr[:200])
            return Voice(mp3, "maslahat.mp3", "audio/mpeg", None, voice_id, model)
        return Voice(dst.read_bytes(), "maslahat.ogg", "audio/ogg", _duration(dst), voice_id, model)


def _duration(path: Path) -> int | None:
    if not shutil.which("ffprobe"):
        return None
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                        "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    try:
        return round(float(p.stdout.strip()))
    except ValueError:
        return None
