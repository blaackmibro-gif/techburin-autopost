"""Sozlamalar va maxfiy kalitlarni yuklash."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"


class ConfigError(RuntimeError):
    pass


def load_config(path: Path = CONFIG_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    _validate(cfg)
    return cfg


def _validate(cfg: dict) -> None:
    for key in ("telegram", "schedule", "post", "quality", "image", "audio", "models", "rubric"):
        if key not in cfg:
            raise ConfigError(f"config.yaml ichida '{key}' bo‘limi yo‘q")
    if not cfg["telegram"].get("channel"):
        raise ConfigError("config.yaml: telegram.channel bo‘sh")
    if not cfg["telegram"].get("admin_chat_id"):
        raise ConfigError("config.yaml: telegram.admin_chat_id bo‘sh")


def secret(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(
            f"{name} topilmadi. GitHub → Settings → Secrets and variables → Actions bo‘limiga qo‘shing."
        )
    return value
