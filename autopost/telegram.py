"""Telegram Bot API uchun yupqa qobiq."""
from __future__ import annotations

import json
import logging
import time

import requests

log = logging.getLogger(__name__)


class TelegramError(RuntimeError):
    pass


class Telegram:
    def __init__(self, token: str, timeout: int = 60):
        self.base = f"https://api.telegram.org/bot{token}/"
        self.timeout = timeout

    def call(self, method: str, data: dict | None = None, files: dict | None = None):
        payload = {}
        for k, v in (data or {}).items():
            if v is None:
                continue
            payload[k] = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
        for attempt in range(3):
            try:
                r = requests.post(self.base + method, data=payload, files=files, timeout=self.timeout)
            except requests.RequestException as e:
                if attempt == 2:
                    raise TelegramError(f"{method}: tarmoq xatosi: {e}") from e
                time.sleep(3)
                continue
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            if body.get("ok"):
                return body["result"]
            retry = (body.get("parameters") or {}).get("retry_after")
            if r.status_code == 429 and retry and attempt < 2:
                time.sleep(min(int(retry), 30))
                continue
            # Tokenni hech qachon logga chiqarmaymiz
            raise TelegramError(f"{method}: {r.status_code} {body.get('description', r.text[:200])}")
        raise TelegramError(f"{method}: muvaffaqiyatsiz")

    # --- yuborish ---
    def send_message(self, chat_id, text: str, buttons: list[list[dict]] | None = None,
                     parse_mode: str | None = "HTML", disable_preview: bool = True):
        return self.call("sendMessage", {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "link_preview_options": {"is_disabled": disable_preview},
            "reply_markup": {"inline_keyboard": buttons} if buttons else None,
        })

    def send_photo(self, chat_id, photo: bytes, caption: str, parse_mode: str = "HTML"):
        return self.call("sendPhoto", {"chat_id": chat_id, "caption": caption, "parse_mode": parse_mode},
                         files={"photo": ("post.jpg", photo, "image/jpeg")})

    def send_voice(self, chat_id, audio: bytes, filename: str, mime: str,
                   caption: str | None = None, duration: int | None = None):
        return self.call("sendVoice", {"chat_id": chat_id, "caption": caption, "duration": duration},
                         files={"voice": (filename, audio, mime)})

    def send_video(self, chat_id, video: bytes, caption: str | None = None, width: int | None = None,
                   height: int | None = None, duration: int | None = None, thumbnail: bytes | None = None):
        data = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML" if caption else None,
                "width": width, "height": height, "duration": duration, "supports_streaming": "true"}
        files = {"video": ("maslahat.mp4", video, "video/mp4")}
        if thumbnail:
            data["thumbnail"] = "attach://thumb"
            files["thumb"] = ("thumb.jpg", thumbnail, "image/jpeg")
        old, self.timeout = self.timeout, max(self.timeout, 180)  # katta fayl yuklanishi uchun
        try:
            return self.call("sendVideo", data, files=files)
        finally:
            self.timeout = old

    def copy_message(self, to_chat, from_chat, message_id: int):
        return self.call("copyMessage", {"chat_id": to_chat, "from_chat_id": from_chat, "message_id": message_id})

    def edit_text(self, chat_id, message_id: int, text: str, buttons: list[list[dict]] | None = None):
        try:
            return self.call("editMessageText", {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "parse_mode": "HTML",
                "link_preview_options": {"is_disabled": True},
                "reply_markup": {"inline_keyboard": buttons or []},
            })
        except TelegramError as e:
            if "message is not modified" in str(e):
                return None
            log.warning("Xabarni tahrirlab bo‘lmadi: %s", e)
            return None

    def answer_callback(self, callback_id: str, text: str = ""):
        try:
            self.call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})
        except TelegramError:
            pass  # eski tugma bosilishlariga javob berib bo‘lmaydi, bu normal

    # --- qabul qilish ---
    def get_updates(self, offset: int, _retried: bool = False):
        try:
            updates = self.call("getUpdates", {
                "offset": offset,
                "timeout": 0,
                "allowed_updates": ["message", "callback_query"],
            })
        except TelegramError as e:
            if "409" in str(e) and not _retried:  # webhook o‘rnatilgan bo‘lsa
                log.warning("Telegram: botga webhook ulangan ekan, o‘chirib qayta o‘qiyman (%s)", str(e)[:200])
                self.call("deleteWebhook", {"drop_pending_updates": False})
                return self.get_updates(offset, _retried=True)
            raise
        kinds = {}
        for u in updates:
            kind = next((k for k in u if k != "update_id"), "?")
            kinds[kind] = kinds.get(kind, 0) + 1
        log.info("Telegram'dan %d ta yangilanish olindi (offset=%s) %s", len(updates), offset, kinds or "")
        return updates

    def get_webhook_info(self) -> dict:
        return self.call("getWebhookInfo")

    def get_chat(self, chat_id):
        return self.call("getChat", {"chat_id": chat_id})

    def get_me(self):
        return self.call("getMe")
