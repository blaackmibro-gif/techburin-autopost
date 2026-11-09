"""Agentlarni bir zanjirga bog‘lash va jadval bo‘yicha boshqarish."""
from __future__ import annotations

import html
import logging
from datetime import datetime, timedelta

from .agents import audio as audio_agent
from .agents import card as card_agent
from .agents import image as image_agent
from .agents import video as video_agent
from .agents import publisher, quality, topic, writer
from .state import next_slot, now_local, parse_slot, slot_id, utc_now_iso

log = logging.getLogger(__name__)

PUBLISH_EARLY_MIN = 10       # post vaqtidan necha daqiqa oldin chiqarishga ruxsat
MAX_GEN_ERRORS = 3
MAX_REGENS = 3
REMIND_BEFORE = timedelta(hours=3)   # tasdiq kelmasa, post vaqtidan qancha oldin eslatish
DONE = ("published", "rejected", "expired")


class Services:
    """Tashqi API mijozlari (testda soxtalari bilan almashtiriladi)."""

    def __init__(self, tg, gemini, eleven):
        self.tg, self.gemini, self.eleven = tg, gemini, eleven


# ---------------------------------------------------------------- generation
def previous_titles(state: dict) -> list[str]:
    titles = [h["title"] for h in state["history"]]
    titles += [d["title"] for d in state["drafts"].values() if d.get("title")]
    titles += [d.get("topic", {}).get("title_uz", "") for d in state["drafts"].values()]
    return [t for t in titles if t]


def generate_draft(svc: Services, cfg: dict, state: dict, sid: str) -> dict:
    """1–5-agentlar: mavzu → maslahat va post → nazorat → rasm → audio. 6-agent adminga yuboradi."""
    g = svc.gemini
    prev = previous_titles(state)

    # 1-agent: mavzu
    tp = topic.find_topic(g, cfg, prev)

    # 2-agent: izlanish va yozish
    rs = writer.research(g, tp, cfg)
    post = writer.write(g, cfg, tp, rs["notes"])

    # 5-agent: matn nazorati (kerak bo‘lsa, qayta yozdiriladi)
    qa = {}
    for attempt in range(cfg["quality"]["max_rewrites"] + 1):
        hard, soft = quality.rule_check(cfg, post, prev)
        review = quality.llm_check(g, cfg, post, rs["notes"])
        issues = hard + ([] if review.get("pass") else review.get("issues", []))
        qa = {"passed": not issues, "score": review.get("score"), "summary_uz": review.get("summary_uz", ""),
              "issues": issues, "warnings": soft, "rewrites": attempt}
        if not issues or attempt == cfg["quality"]["max_rewrites"]:
            break
        log.info("Nazoratdan o‘tmadi (%d-urinish): %s", attempt + 1, issues)
        post = writer.rewrite(g, cfg, post, rs["notes"], issues)

    if not qa["passed"] and cfg["quality"].get("on_fail") == "skip":
        raise RuntimeError("Post nazoratdan o‘tmadi va sozlamaga ko‘ra tashlab yuborildi: " + "; ".join(qa["issues"])[:500])

    # 3-agent: rasm — bepul rejimda brend kartochka, aks holda AI rasm
    if cfg["image"].get("mode", "card") != "ai":
        img = card_agent.make_card(cfg, post["title"])
    else:
        img = _ai_image(g, cfg, post, qa)

    # 4-agent: audio
    voice = audio_agent.speak(svc.eleven, cfg, post["audio_script"])

    # 7-agent: video (kartochka + ovoz + subtitr). Xato bo‘lsa, post videosiz davom etadi.
    video = _make_video(cfg, img, voice, post, qa)
    return _finish_draft(svc, cfg, state, sid, tp, post, rs, qa, img, voice, video)


def _make_video(cfg: dict, img: bytes, voice, post: dict, qa: dict):
    if not video_agent.enabled(cfg):
        return None
    try:
        return video_agent.make_video(cfg, img, voice.data, post["audio_script"])
    except Exception as e:  # noqa: BLE001
        log.exception("Video tayyorlanmadi")
        qa.setdefault("warnings", []).append(f"Video tayyorlanmadi: {str(e)[:150]}")
        return None


def _ai_image(g, cfg: dict, post: dict, qa: dict) -> bytes:
    """Nano Banana rasmi + 5-agent rasm nazorati (bitta qayta urinish)."""
    img = image_agent.generate(g, cfg, post["image_prompt"])
    try:
        ic = quality.image_check(g, img, post["title"])
        if not ic.get("pass"):
            log.info("Rasm nazoratdan o‘tmadi: %s", ic.get("issues"))
            img = image_agent.generate(g, cfg, post["image_prompt"], extra="Avoid: " + "; ".join(ic.get("issues", [])))
            ic = quality.image_check(g, img, post["title"])
            if not ic.get("pass"):
                qa["warnings"].append("Rasm: " + "; ".join(ic.get("issues", [])))
    except Exception as e:  # noqa: BLE001 — rasm tekshiruvi ishlamasa, post to‘xtamaydi
        log.warning("Rasm tekshiruvi bajarilmadi: %s", e)
        qa["warnings"].append("Rasm avtomatik tekshirilmadi")
    return img


def _finish_draft(svc: Services, cfg: dict, state: dict, sid: str, tp: dict, post: dict, rs: dict,
                  qa: dict, img: bytes, voice, video=None) -> dict:
    old = state["drafts"].get(sid, {})
    if video is not None and not voice.duration:
        voice.duration = int(round(video.audio_seconds))  # ovozli xabar uzunligini ham ko‘rsatish uchun
    draft = {
        "slot": sid,
        "created": utc_now_iso(),
        "status": "pending",
        "topic": {k: tp.get(k) for k in ("title_uz", "angle")},
        "title": post["title"],
        "caption": post["caption"],
        "audio_script": post["audio_script"],
        "sources": rs["sources"],
        "qa": qa,
        "voice": {"duration": voice.duration, "model": voice.model, "voice_id": voice.voice_id},
        "video": {"duration": video.duration, "size_kb": len(video.data) // 1024} if video is not None else None,
        "regen_count": old.get("regen_count", 0),
    }
    if cfg.get("mode") == "auto" and qa["passed"]:
        draft["status"] = "auto"

    # 6-agent: adminga yuborish
    publisher.send_to_admin(svc.tg, cfg, draft, img, voice, video)
    state["drafts"][sid] = draft
    return draft


# ---------------------------------------------------------------- admin updates
HELP = ("Men Techburin Construct kanali uchun postlar tayyorlayman.\n\n"
        "/yangi — keyingi post uchun hozir qoralama tayyorlash\n"
        "/holat — navbatdagi postlar holati\n\n"
        "Qoralama tagidagi tugmalar: ✅ vaqtida chiqarish, 🚀 hozir chiqarish, 🔁 qayta yozish, ❌ bekor qilish.\n"
        "Tugma bosilgani qabul qilinganda alohida «Qabul qilindi» xabari keladi.")


def status_text(cfg: dict, state: dict) -> str:
    now = now_local(cfg)
    lines = [f"<b>Keyingi post vaqti:</b> {publisher.pretty_slot(next_slot(cfg, now))}"]
    active = [d for d in state["drafts"].values() if d["status"] not in DONE]
    for d in sorted(active, key=lambda x: x["slot"]):
        lines.append(f"• {publisher.pretty_slot(parse_slot(cfg, d['slot']))}: {html.escape(d.get('title', ''))} — {d['status']}")
    if not active:
        lines.append("Faol qoralama yo‘q.")
    last = [h for h in state["history"]][-3:]
    if last:
        lines.append("\n<b>Oxirgi chiqqanlar:</b>")
        lines += [f"• {h['date']}: {html.escape(h['title'])}" for h in last]
    return "\n".join(lines)


def process_updates(svc: Services, cfg: dict, state: dict, now=None) -> list[tuple[str, str, str]]:
    """Tugma va buyruqlarni o‘qiydi. Qabul qilingan tugmalar ro‘yxatini qaytaradi: (slot, action, sarlavha)."""
    tg, admin = svc.tg, int(cfg["telegram"]["admin_chat_id"])
    now = now or now_local(cfg)
    late = timedelta(hours=cfg["schedule"].get("late_publish_hours", 6))
    acks = []
    updates = tg.get_updates(state["last_update_id"] + 1)
    for u in updates:
        state["last_update_id"] = max(state["last_update_id"], u["update_id"])
        cq = u.get("callback_query")
        if cq:
            if cq["from"]["id"] != admin:
                tg.answer_callback(cq["id"], "Ruxsat yo‘q")
                continue
            action, _, sid = (cq.get("data") or "").partition(":")
            d = state["drafts"].get(sid)
            if not d:
                tg.answer_callback(cq["id"], "Qoralama topilmadi")
                continue
            if d["status"] in DONE:
                tg.answer_callback(cq["id"], "Bu qoralama allaqachon yakunlangan")
                continue
            if action == "approve":
                # Tizim tugmani kech o‘qigan bo‘lsa (post vaqti o‘tib ketgan), tasdiqni yo‘qotmasdan darhol chiqaramiz
                d["status"] = "publish_now" if now > parse_slot(cfg, sid) + late else "approved"
            elif action == "now":
                d["status"] = "publish_now"
            elif action == "regen":
                d["status"] = "regen_requested"
            elif action == "reject":
                d["status"] = "rejected"
            else:
                continue
            tg.answer_callback(cq["id"], "Qabul qilindi")
            publisher.refresh_control(tg, cfg, d)
            acks.append((sid, action, d.get("title", "")))
            continue

        msg = u.get("message")
        if not msg or msg.get("chat", {}).get("id") != admin:
            continue
        text = (msg.get("text") or "").strip().split("@")[0].lower()
        if text in ("/yangi", "yangi"):
            state["force_generate"] = True
            tg.send_message(admin, "🛠 Yangi qoralama tayyorlanmoqda, bir necha daqiqada keladi.")
        elif text in ("/holat", "holat"):
            tg.send_message(admin, status_text(cfg, state))
        elif text.startswith("/"):
            tg.send_message(admin, HELP, parse_mode=None)
    return acks


def send_acks(svc: Services, cfg: dict, state: dict, acks, now) -> None:
    for sid, action, title in acks:
        d = state["drafts"].get(sid)
        text = publisher.ack_text(cfg, d, action, title, now) if d else None
        if text:
            publisher.notify(svc.tg, cfg, text)


def remind_pending(svc: Services, cfg: dict, state: dict, now) -> None:
    """Tasdiq kelmagan qoralama haqida bir marta eslatadi (tugmalari bilan)."""
    late = timedelta(hours=cfg["schedule"].get("late_publish_hours", 6))
    for d in state["drafts"].values():
        if d["status"] != "pending" or d.get("reminded"):
            continue
        slot = parse_slot(cfg, d["slot"])
        created = datetime.fromisoformat(d["created"]) if d.get("created") else None
        if created and now - created < timedelta(hours=1):
            continue  # qoralama endigina keldi
        if slot - REMIND_BEFORE <= now <= slot + late:
            text, kb = publisher.reminder(cfg, d, now, slot + late)
            publisher.notify(svc.tg, cfg, text, kb)
            d["reminded"] = True


# ---------------------------------------------------------------- publishing
def publish_due(svc: Services, cfg: dict, state: dict, now) -> None:
    late = timedelta(hours=cfg["schedule"].get("late_publish_hours", 6))
    for d in state["drafts"].values():
        if d["status"] in DONE or d["status"] == "failed":
            continue
        slot = parse_slot(cfg, d["slot"])
        ready = d["status"] == "publish_now" or (
            d["status"] in ("approved", "auto") and now >= slot - timedelta(minutes=PUBLISH_EARLY_MIN))
        if d["status"] == "publish_now" or (ready and now <= slot + late):
            try:
                publisher.publish(svc.tg, cfg, d)
                d["status"] = "published"
                state["history"].append({"date": now.strftime("%Y-%m-%d"), "title": d["title"], "slot": d["slot"]})
                log.info("Chiqarildi: %s", d["title"])
                publisher.notify(svc.tg, cfg, publisher.published_text(d))
            except Exception as e:  # noqa: BLE001
                d["status"], d["error"] = "failed", str(e)[:300]
                log.error("Chiqarishda xato: %s", e)
                publisher.notify(svc.tg, cfg, publisher.failed_text(d))
            publisher.refresh_control(svc.tg, cfg, d)
        elif now > slot + late and d["status"] in ("pending", "approved", "auto", "regen_requested"):
            d["status"] = "expired"
            publisher.refresh_control(svc.tg, cfg, d)
            publisher.notify(svc.tg, cfg, publisher.expired_text(d))


def maybe_generate(svc: Services, cfg: dict, state: dict, now) -> None:
    window = timedelta(hours=cfg["schedule"].get("generate_hours_before", 14))
    late = timedelta(hours=cfg["schedule"].get("late_publish_hours", 6))
    admin = cfg["telegram"]["admin_chat_id"]

    targets = [sid for sid, d in state["drafts"].items()
               if d["status"] == "regen_requested" and now <= parse_slot(cfg, sid) + late]

    slot = next_slot(cfg, now)
    while state["drafts"].get(slot_id(slot), {}).get("status") in DONE + ("failed",):
        slot = next_slot(cfg, slot + timedelta(minutes=1))
    sid = slot_id(slot)
    existing = state["drafts"].get(sid)
    if state.get("force_generate"):
        state["gen_errors"].pop(sid, None)  # qo‘lda so‘ralganda xatolar hisobini nolga qaytaramiz
        targets.append(sid)
    elif existing is None and slot - now <= window:
        targets.append(sid)
    state["force_generate"] = False

    for sid in dict.fromkeys(targets):
        old = state["drafts"].get(sid)
        if old and old["status"] == "regen_requested" and old.get("regen_count", 0) >= MAX_REGENS:
            old["status"] = "pending"
            svc.tg.send_message(admin, "🔁 Qayta yozish chegarasiga yetildi. Oxirgi qoralamani tasdiqlang yoki bekor qiling.")
            publisher.refresh_control(svc.tg, cfg, old)
            continue
        errors = state["gen_errors"].get(sid, 0)
        if errors >= MAX_GEN_ERRORS:
            continue
        try:
            new = generate_draft(svc, cfg, state, sid)
            state["gen_errors"].pop(sid, None)
            if old:
                new["regen_count"] = old.get("regen_count", 0) + (1 if old["status"] == "regen_requested" else 0)
                publisher.refresh_control(svc.tg, cfg, {**old, "status": "replaced"})
            log.info("Qoralama tayyor: %s — %s", sid, new["title"])
        except Exception as e:  # noqa: BLE001
            state["gen_errors"][sid] = errors + 1
            log.exception("Qoralama tayyorlanmadi")
            note = " Keyingi tekshiruvda yana urinib ko‘raman." if errors + 1 < MAX_GEN_ERRORS else \
                   " 3 marta urinildi, bu vaqt uchun to‘xtatildi. /yangi bilan qayta boshlashingiz mumkin."
            svc.tg.send_message(admin, f"⛔ Qoralama tayyorlanmadi: {html.escape(str(e)[:400])}.{note}")


def tick(svc: Services, cfg: dict, state: dict, now=None) -> None:
    now = now or now_local(cfg)
    acks = process_updates(svc, cfg, state, now)
    publish_due(svc, cfg, state, now)
    maybe_generate(svc, cfg, state, now)
    publish_due(svc, cfg, state, now)  # avtomatik rejimda yangi tayyorlangan post vaqti kelgan bo‘lsa
    send_acks(svc, cfg, state, acks, now)
    remind_pending(svc, cfg, state, now)
