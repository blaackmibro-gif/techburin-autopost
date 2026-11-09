"""Buyruqlar:
    python -m autopost tick              — jadval bo‘yicha tekshiruv (har 30 daqiqada GitHub ishga tushiradi)
    python -m autopost yangi-post        — keyingi post uchun hozir qoralama tayyorlash
    python -m autopost tekshirish        — kalitlar, bot va kanal ulanishini tekshirish
    python -m autopost ovozlarni-sinash  — ElevenLabs ovozlaridan namunalar yuborish
"""
from __future__ import annotations

import html
import logging
import sys
import time
from urllib.parse import urlparse

from .config import load_config, secret
from .gemini import Gemini
from .agents import video as video_agent
from .agents.audio import ElevenLabs, speak
from .pipeline import Services, tick
from .state import load_state, save_state
from .telegram import Telegram

VOICE_SAMPLE = ("Assalomu alaykum! Techburin Construct’dan foydali maslahat. Poydevor ishlarini boshlashdan oldin "
                "albatta geologik tadqiqot o‘tkazing: grunt qanday ekanini bilmasdan qoziq turini tanlab bo‘lmaydi.")


def services(cfg: dict, need_ai: bool = True) -> Services:
    tg = Telegram(secret("TELEGRAM_BOT_TOKEN"))
    if not need_ai:
        return Services(tg, None, None)
    m = cfg["models"]
    gemini = Gemini(secret("GEMINI_API_KEY"), [m["text"], *m.get("text_fallbacks", [])],
                    [m["image"], *m.get("image_fallbacks", [])])
    return Services(tg, gemini, ElevenLabs(secret("ELEVENLABS_API_KEY")))


def cmd_tick(cfg, force: bool = False) -> None:
    state = load_state()
    if force:
        state["force_generate"] = True
    try:
        tick(services(cfg), cfg, state)
    finally:
        save_state(state)


def check_updates(tg: Telegram) -> list[str]:
    """Tugma bosilishlari botga yetib kelyaptimi: webhook va kutib turgan yangilanishlar."""
    lines = []
    try:
        wh = tg.get_webhook_info()
        if wh.get("url"):
            host = urlparse(wh["url"]).netloc or "noma’lum manzil"
            err = f" Oxirgi xato: {wh['last_error_message']}" if wh.get("last_error_message") else ""
            lines.append(f"⛔ Botga webhook ulangan ({host}). Tugma bosilishlari o‘sha yerga ketyapti, "
                         f"tizim ularni o‘chirib qo‘yadi.{err}")
        else:
            lines.append(f"✅ Webhook yo‘q (Telegram navbatida: {wh.get('pending_update_count', 0)} ta)")
        state = load_state()
        ups = tg.get_updates(state["last_update_id"] + 1)
        presses = sum(1 for u in ups if u.get("callback_query"))
        msgs = sum(1 for u in ups if u.get("message"))
        lines.append(f"ℹ️ Botga kelib turgan: {len(ups)} ta (tugma bosish: {presses}, xabar: {msgs}). "
                     f"Oxirgi o‘qilgan raqam: {state['last_update_id']}")
        if not ups and not wh.get("url"):
            lines.append(detect_other_reader(tg, state["last_update_id"] + 1))
    except Exception as e:  # noqa: BLE001
        lines.append(f"⛔ Telegram yangilanishlari: {str(e)[:300]}")
    return lines


def detect_other_reader(tg: Telegram, offset: int, seconds: int = 75) -> str:
    """Shu bot tokeni bilan boshqa dastur ham yangilanishlarni o‘qiyaptimi?

    Telegram bitta botga bir vaqtda faqat bitta o‘quvchiga ruxsat beradi: boshqa dastur o‘qisa,
    bizning kutib turgan so‘rovimiz «409 terminated by other getUpdates request» bilan uziladi.
    Yangilanishlar tasdiqlanmaydi (offset o‘zgarmaydi), shuning uchun hech narsa yo‘qolmaydi.
    """
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            ups = tg.call("getUpdates", {"offset": offset, "limit": 1, "timeout": 25,
                                         "allowed_updates": ["message", "callback_query"]})
        except Exception as e:  # noqa: BLE001
            if "409" in str(e) and "other getUpdates" in str(e):
                return ("⛔ Bot tokeni boshqa dasturda ham ishlatilyapti: tugma bosilishlari va xabarlaringizni "
                        "o‘sha dastur olib ketyapti, shuning uchun tasdiqlar yetib kelmaydi. Yechim: o‘sha dasturni "
                        "to‘xtating yoki @BotFather'da /revoke qilib yangi token oling va GitHub Secrets'dagi "
                        "TELEGRAM_BOT_TOKEN ni yangilang.")
            return f"⚠️ Ikkinchi o‘quvchini tekshirib bo‘lmadi: {str(e)[:200]}"
        if ups:
            return "✅ Tekshiruv paytida botga yangilanish keldi: tugma bosilishlari yetib kelyapti."
    return (f"✅ {seconds} soniya kuzatildi: boshqa dastur botni o‘qiyotgani sezilmadi. "
            f"Bu vaqtda bot chatiga /holat yozib ko‘rsangiz, tekshiruv aniqroq bo‘ladi.")


def cmd_check(cfg) -> int:
    lines, ok = [], True
    tg = Telegram(secret("TELEGRAM_BOT_TOKEN"))
    channel, admin = cfg["telegram"]["channel"], cfg["telegram"]["admin_chat_id"]
    try:
        me = tg.get_me()
        lines.append(f"✅ Bot: @{me['username']}")
        chat = tg.get_chat(channel)
        member = tg.call("getChatMember", {"chat_id": channel, "user_id": me["id"]})
        if member.get("status") == "administrator" and member.get("can_post_messages", False):
            lines.append(f"✅ Kanal: {chat.get('title')} — bot admin, post joylay oladi")
        else:
            ok = False
            lines.append(f"⛔ Kanal: {chat.get('title')} — bot admin emas yoki «Xabarlarni joylash» ruxsati yo‘q")
    except Exception as e:  # noqa: BLE001
        ok = False
        lines.append(f"⛔ Telegram: {e}")
    lines += check_updates(tg)
    if any(line.startswith("⛔") for line in lines):
        ok = False
    try:
        m = cfg["models"]
        g = Gemini(secret("GEMINI_API_KEY"), [m["text"], *m.get("text_fallbacks", [])], [])
        r = g.text("Reply with the single word OK.", temperature=0)
        lines.append(f"✅ Gemini: ishlayapti ({r.model})")
    except Exception as e:  # noqa: BLE001
        ok = False
        lines.append(f"⛔ Gemini: {str(e)[:300]}")
    try:
        el = ElevenLabs(secret("ELEVENLABS_API_KEY"))
        voice = speak(el, cfg, "Assalomu alaykum! Bu Techburin Construct ovozli xabarini sinash.")
        note = " (standart ovozlar ishlatiladi)" if el.used_defaults else ""
        lines.append(f"✅ ElevenLabs: o‘zbekcha ovoz yaratildi ({voice.model}){note}")
    except Exception as e:  # noqa: BLE001
        ok = False
        lines.append(f"⛔ ElevenLabs: {str(e)[:300]}")
    if video_agent.enabled(cfg):
        if video_agent.ffmpeg_exe():
            lines.append("✅ Video: ffmpeg tayyor")
        else:
            ok = False
            lines.append("⛔ Video: ffmpeg topilmadi (requirements.txt da imageio-ffmpeg borligini tekshiring)")

    report = "\n".join(lines)
    print(report)
    try:
        tg.send_message(admin, "<b>Ulanishlarni tekshirish</b>\n" + html.escape(report), parse_mode="HTML")
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"⛔ Adminga xabar yuborib bo‘lmadi ({e}). Telegram'da botingizni ochib, Start tugmasini bosing.")
    return 0 if ok else 1


def cmd_voices(cfg) -> None:
    tg = Telegram(secret("TELEGRAM_BOT_TOKEN"))
    el = ElevenLabs(secret("ELEVENLABS_API_KEY"))
    admin = cfg["telegram"]["admin_chat_id"]
    gender = cfg["audio"].get("voice_gender", "male")
    voices = el.voices()
    voices.sort(key=lambda v: (v.get("labels") or {}).get("gender", "") != gender)
    tg.send_message(admin, f"🎙 {min(len(voices), 6)} ta ovoz namunasi yuborilmoqda. Yoqqanining <code>voice_id</code> sini "
                           "config.yaml'dagi <code>audio.voice_id</code> ga yozing.")
    for v in voices[:6]:
        sample_cfg = {**cfg, "audio": {**cfg["audio"], "voice_id": v["voice_id"]}}
        try:
            voice = speak(el, sample_cfg, VOICE_SAMPLE)
            tg.send_voice(admin, voice.data, voice.filename, voice.mime, duration=voice.duration,
                          caption=f"{v.get('name')} — voice_id: {v['voice_id']}")
        except Exception as e:  # noqa: BLE001
            tg.send_message(admin, f"⛔ {html.escape(v.get('name', ''))}: {html.escape(str(e)[:200])}")


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    cmd = argv[1] if len(argv) > 1 else "tick"
    cfg = load_config()
    if cmd == "tick":
        cmd_tick(cfg)
    elif cmd == "yangi-post":
        cmd_tick(cfg, force=True)
    elif cmd == "tekshirish":
        return cmd_check(cfg)
    elif cmd == "ovozlarni-sinash":
        cmd_voices(cfg)
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
