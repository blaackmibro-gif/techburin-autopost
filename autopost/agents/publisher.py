"""6-agent: qoralamani adminga yuboradi, tasdiqni qabul qiladi va kanalga chiqaradi."""
from __future__ import annotations

import html
import logging
from datetime import datetime

from ..state import parse_slot
from ..telegram import Telegram

log = logging.getLogger(__name__)

WEEKDAYS = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]
MONTHS = ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr"]


def pretty_slot(dt: datetime) -> str:
    return f"{WEEKDAYS[dt.weekday()]}, {dt.day}-{MONTHS[dt.month - 1]}, {dt:%H:%M}"


def buttons(draft: dict) -> list[list[dict]]:
    sid, st = draft["slot"], draft["status"]
    if st in ("pending", "auto"):
        return [
            [{"text": "✅ Vaqtida chiqarish", "callback_data": f"approve:{sid}"},
             {"text": "🚀 Hozir chiqarish", "callback_data": f"now:{sid}"}],
            [{"text": "🔁 Qayta yozish", "callback_data": f"regen:{sid}"},
             {"text": "❌ Bekor qilish", "callback_data": f"reject:{sid}"}],
        ]
    if st == "approved":
        return [[{"text": "🚀 Hozir chiqarish", "callback_data": f"now:{sid}"},
                 {"text": "❌ Bekor qilish", "callback_data": f"reject:{sid}"}]]
    return []


def control_text(cfg: dict, draft: dict) -> str:
    slot = pretty_slot(parse_slot(cfg, draft["slot"]))
    qa = draft.get("qa", {})
    if qa.get("passed"):
        qa_line = f"✅ o‘tdi ({qa.get('score', '?')}/10). {html.escape(qa.get('summary_uz', ''))}"
    else:
        issues = "; ".join(qa.get("issues_uz") or qa.get("issues") or [])[:600]
        qa_line = f"⚠️ <b>o‘tmadi</b>. {html.escape(qa.get('summary_uz', ''))} {html.escape(issues)}"
    if qa.get("warnings"):
        qa_line += "\nEslatma: " + html.escape("; ".join(qa["warnings"]))
    src = draft.get("sources", [])[:5]
    src_lines = "\n".join(
        f"• <a href=\"{html.escape(s['url'], quote=True)}\">{html.escape(s.get('title') or 'manba')}</a>" for s in src
    ) or ("• internet qidiruvisiz (bepul rejim), umumiy amaliyot asosida yozildi"
          if not cfg.get("features", {}).get("web_search", True) else "• (manba ko‘rsatilmagan)")
    voice = draft.get("voice", {})
    voice_line = f"{voice.get('duration') or '?'} soniya · {html.escape(voice.get('model', ''))}" if voice else "yo‘q"
    video = draft.get("video")
    video_line = f"{video['duration']} soniya · {video['size_kb'] / 1024:.1f} MB" if video else "yo‘q"

    status = {
        "pending": f"⏳ Tasdiqlashingizni kutmoqda. Tasdiqlansa, <b>{slot}</b> da chiqadi.",
        "auto": f"🤖 Avtomatik rejim: <b>{slot}</b> da o‘zi chiqadi. To‘xtatish uchun «Bekor qilish»ni bosing.",
        "approved": f"✅ Tasdiqlandi. <b>{slot}</b> da chiqadi.",
        "publish_now": "🚀 Hozir chiqariladi…",
        "regen_requested": "🔁 Qayta yozilmoqda. Yangi qoralama keyingi tekshiruvda keladi.",
        "rejected": "❌ Bekor qilindi. Bu vaqtga post chiqmaydi.",
        "expired": "⌛ Vaqtida tasdiqlanmadi, post chiqmadi.",
        "published": f"📢 Kanalga chiqdi{': ' + draft['post_link'] if draft.get('post_link') else ''}",
        "failed": f"⛔ Chiqarishda xato: {html.escape(draft.get('error', ''))}",
        "replaced": "🔁 Bu qoralama yangisi bilan almashtirildi (pastda).",
    }.get(draft["status"], draft["status"])

    return (
        f"📝 <b>Yangi qoralama</b> · {slot}\n"
        f"<b>Mavzu:</b> {html.escape(draft.get('title', ''))}\n"
        f"<b>Nazorat:</b> {qa_line}\n"
        f"<b>Audio:</b> {voice_line}\n"
        f"<b>Video:</b> {video_line}\n"
        f"<b>Manbalar:</b>\n{src_lines}\n\n"
        f"{status}\n\n"
        f"<i>Tugma bosilgani tizimga yetib borgach, alohida «Qabul qilindi» xabari keladi. "
        f"U kelmasa, bosilish yetib bormagan.</i>"
    )


# ---------------------------------------------------------------- adminga alohida xabarlar
def notify(tg: Telegram, cfg: dict, text: str, buttons_: list[list[dict]] | None = None) -> None:
    """Adminga yangi xabar (tahrir emas, shuning uchun telefonga bildirishnoma keladi)."""
    try:
        tg.send_message(cfg["telegram"]["admin_chat_id"], text, buttons_)
    except Exception as e:  # noqa: BLE001 — xabar ketmasa ham post jarayoni to‘xtamasin
        log.warning("Adminga xabar yuborib bo‘lmadi: %s", e)


def ack_text(cfg: dict, draft: dict, action: str, title: str, now: datetime) -> str | None:
    """Tugma bosilishi qabul qilingani haqida xabar. Chiqdi/xato/muddat xabarlari alohida yuboriladi."""
    t = html.escape(title)
    got = f"\n<i>Tizim tugmani {now:%H:%M} da qabul qildi.</i>"
    st = draft["status"]
    if st in ("published", "failed", "expired"):
        return None  # publish_due o‘z xabarini yuborgan
    if action == "approve" and st == "approved":
        slot = pretty_slot(parse_slot(cfg, draft["slot"]))
        return f"✅ <b>Tasdiq qabul qilindi</b>\n«{t}»\n<b>{slot}</b> da kanalga chiqadi.{got}"
    if action == "reject":
        return f"❌ <b>Bekor qilish qabul qilindi</b>\n«{t}» kanalga chiqmaydi.{got}"
    if action == "regen":
        return (f"🔁 <b>Qayta yozish qabul qilindi</b>\n«{t}» o‘rniga yangi qoralama tayyorlanadi "
                f"va alohida keladi.{got}")
    return None


def published_text(draft: dict) -> str:
    link = f"\n{draft['post_link']}" if draft.get("post_link") else ""
    return f"📢 <b>Kanalga chiqdi</b>\n«{html.escape(draft.get('title', ''))}»{link}"


def failed_text(draft: dict) -> str:
    return (f"⛔ <b>Kanalga chiqmadi</b>\n«{html.escape(draft.get('title', ''))}»\n"
            f"Xato: {html.escape(draft.get('error', ''))}")


def expired_text(draft: dict) -> str:
    return (f"⌛ <b>Post chiqmadi</b>\n«{html.escape(draft.get('title', ''))}» vaqtida tasdiqlanmadi.\n"
            f"Bugun post kerak bo‘lsa, botga /yangi yozing va qoralama kelgach «🚀 Hozir chiqarish»ni bosing.")


def reminder(cfg: dict, draft: dict, now: datetime, deadline: datetime) -> tuple[str, list[list[dict]]]:
    slot = parse_slot(cfg, draft["slot"])
    t = html.escape(draft.get("title", ""))
    sid = draft["slot"]
    tail = ("\n\nTugmani bosgan bo‘lsangiz-u, baribir shu xabar kelgan bo‘lsa, bosilish botga yetib bormagan. "
            "Shu yerdagi tugmani qayta bosing.")
    if now < slot:
        text = (f"⏰ <b>Qoralama hali tasdiqlanmagan</b>\n«{t}»\n"
                f"{pretty_slot(slot)} da chiqishi uchun tugmani bosing.{tail}")
        kb = [[{"text": "✅ Vaqtida chiqarish", "callback_data": f"approve:{sid}"},
               {"text": "🚀 Hozir chiqarish", "callback_data": f"now:{sid}"}]]
    else:
        text = (f"⏰ <b>Post vaqti o‘tdi, lekin tasdiq kelmadi</b>\n«{t}»\n"
                f"Bugun chiqishi uchun «🚀 Hozir chiqarish»ni bosing (oxirgi muddat {deadline:%H:%M}).{tail}")
        kb = [[{"text": "🚀 Hozir chiqarish", "callback_data": f"now:{sid}"}]]
    return text, kb


def video_caption(cfg: dict, draft: dict) -> str:
    note = (cfg.get("video") or {}).get("caption", "🎬 Video-maslahat")
    return f"<b>{html.escape(draft.get('title', ''))}</b>\n{html.escape(note)}" if note else ""


def send_to_admin(tg: Telegram, cfg: dict, draft: dict, image: bytes, voice, video=None) -> None:
    admin = cfg["telegram"]["admin_chat_id"]
    photo = tg.send_photo(admin, image, draft["caption"])
    vmsg = tg.send_voice(admin, voice.data, voice.filename, voice.mime, duration=voice.duration)
    draft["admin_msgs"] = {"photo": photo["message_id"], "voice": vmsg["message_id"]}
    if video is not None:
        try:
            m = tg.send_video(admin, video.data, video_caption(cfg, draft), video.width, video.height,
                              video.duration, video.thumb)
            draft["admin_msgs"]["video"] = m["message_id"]
        except Exception as e:  # noqa: BLE001 — video yuborilmasa ham post to‘xtamaydi
            log.warning("Videoni yuborib bo‘lmadi: %s", e)
            draft["video"] = None
            draft.setdefault("qa", {}).setdefault("warnings", []).append(f"Video yuborilmadi: {str(e)[:150]}")
    ctrl = tg.send_message(admin, control_text(cfg, draft), buttons(draft))
    draft["admin_msgs"]["control"] = ctrl["message_id"]


def refresh_control(tg: Telegram, cfg: dict, draft: dict) -> None:
    mid = (draft.get("admin_msgs") or {}).get("control")
    if mid:
        tg.edit_text(cfg["telegram"]["admin_chat_id"], mid, control_text(cfg, draft), buttons(draft))


def publish(tg: Telegram, cfg: dict, draft: dict) -> None:
    admin, channel = cfg["telegram"]["admin_chat_id"], cfg["telegram"]["channel"]
    msgs = draft["admin_msgs"]
    photo = tg.copy_message(channel, admin, msgs["photo"])
    voice = tg.copy_message(channel, admin, msgs["voice"])
    draft["published_msgs"] = {"photo": photo["message_id"], "voice": voice["message_id"]}
    if msgs.get("video"):
        try:
            vid = tg.copy_message(channel, admin, msgs["video"])
            draft["published_msgs"]["video"] = vid["message_id"]
        except Exception as e:  # noqa: BLE001 — rasm va ovoz chiqqan, video xatosi postni buzmasin
            log.warning("Videoni kanalga chiqarib bo‘lmadi: %s", e)
    if str(channel).startswith("@"):
        draft["post_link"] = f"https://t.me/{channel[1:]}/{photo['message_id']}"
