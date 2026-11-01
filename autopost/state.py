"""Holat fayli (state/state.json) va jadval hisoblari.

Holat GitHub repo ichida saqlanadi: har ishga tushishdan keyin workflow uni commit qiladi.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import ROOT

STATE_PATH = ROOT / "state" / "state.json"
DAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
HISTORY_KEEP = 300


def empty_state() -> dict:
    return {"last_update_id": 0, "drafts": {}, "history": [], "force_generate": False, "gen_errors": {}}


def load_state(path: Path = STATE_PATH) -> dict:
    if not path.exists():
        return empty_state()
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    base = empty_state()
    base.update(data)
    return base


def save_state(state: dict, path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Eski qoralamalarni tozalash: 30 kundan eskilari o‘chadi
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(timespec="seconds")
    state["drafts"] = {k: v for k, v in state["drafts"].items() if v.get("created", "") >= cutoff}
    state["history"] = state["history"][-HISTORY_KEEP:]
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def tz(cfg: dict) -> ZoneInfo:
    return ZoneInfo(cfg.get("timezone", "Asia/Tashkent"))


def now_local(cfg: dict) -> datetime:
    return datetime.now(tz(cfg))


def slot_id(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M")


def parse_slot(cfg: dict, sid: str) -> datetime:
    return datetime.strptime(sid, "%Y-%m-%dT%H:%M").replace(tzinfo=tz(cfg))


def next_slot(cfg: dict, after: datetime) -> datetime:
    """`after` vaqtidan keyingi (yoki unga teng) birinchi post vaqti."""
    days = sorted(DAYS[d.strip().lower()[:3]] for d in cfg["schedule"]["days"])
    hh, mm = (int(x) for x in str(cfg["schedule"]["time"]).split(":"))
    for i in range(0, 15):
        day = (after + timedelta(days=i)).date()
        if day.weekday() not in days:
            continue
        cand = datetime(day.year, day.month, day.day, hh, mm, tzinfo=after.tzinfo)
        if cand >= after:
            return cand
    raise ValueError("schedule.days bo‘sh yoki noto‘g‘ri")
