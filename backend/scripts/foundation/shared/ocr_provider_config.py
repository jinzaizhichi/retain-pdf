from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

OCR_PROVIDER_CONFIG_ENV = "RETAIN_OCR_PROVIDER_CONFIG"
PADDLE_DEFAULT_MODEL_ENV = "RETAIN_PADDLE_DEFAULT_MODEL"
PADDLE_DEFAULT_MODEL_FALLBACK = "PaddleOCR-VL-1.6"


def paddle_default_model() -> str:
    override = str(os.environ.get(PADDLE_DEFAULT_MODEL_ENV, "") or "").strip()
    if override:
        return override
    return str(_paddle_config().get("default_model") or PADDLE_DEFAULT_MODEL_FALLBACK).strip()


def normalize_paddle_model_name(model: str) -> str:
    trimmed = str(model or "").strip()
    if not trimmed:
        return paddle_default_model()
    aliases = _paddle_aliases()
    return aliases.get(trimmed.lower(), trimmed)


def _paddle_aliases() -> dict[str, str]:
    aliases = _paddle_config().get("model_aliases") or {}
    if not isinstance(aliases, dict):
        return {}
    return {
        str(key).strip().lower(): str(value).strip()
        for key, value in aliases.items()
        if str(key).strip() and str(value).strip()
    }


def _paddle_config() -> dict[str, Any]:
    payload = _ocr_provider_config()
    paddle = payload.get("paddle") if isinstance(payload, dict) else {}
    return dict(paddle or {}) if isinstance(paddle, dict) else {}


@lru_cache(maxsize=1)
def _ocr_provider_config() -> dict[str, Any]:
    path = _config_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload or {}) if isinstance(payload, dict) else {}


def _config_path() -> Path:
    override = str(os.environ.get(OCR_PROVIDER_CONFIG_ENV, "") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parents[3] / "config" / "ocr_providers.json"


__all__ = [
    "OCR_PROVIDER_CONFIG_ENV",
    "PADDLE_DEFAULT_MODEL_ENV",
    "PADDLE_DEFAULT_MODEL_FALLBACK",
    "normalize_paddle_model_name",
    "paddle_default_model",
]
