from __future__ import annotations

import os


FAST_PATCH_PAGE_THRESHOLD = 120
BBOX_TEXT_STRIP_DEFAULT_MAX_SECONDS = 30.0


def source_cleanup_max_seconds() -> float:
    raw = str(os.environ.get("RETAIN_BBOX_TEXT_STRIP_MAX_SECONDS", "") or "").strip()
    if not raw:
        return BBOX_TEXT_STRIP_DEFAULT_MAX_SECONDS
    try:
        return max(0.0, float(raw))
    except ValueError:
        return BBOX_TEXT_STRIP_DEFAULT_MAX_SECONDS


def should_use_fast_overlay_cover_path(*, translated_page_count: int, strip_hidden_text: bool) -> bool:
    return not strip_hidden_text and translated_page_count >= FAST_PATCH_PAGE_THRESHOLD


__all__ = [
    "BBOX_TEXT_STRIP_DEFAULT_MAX_SECONDS",
    "FAST_PATCH_PAGE_THRESHOLD",
    "should_use_fast_overlay_cover_path",
    "source_cleanup_max_seconds",
]
