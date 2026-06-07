from __future__ import annotations

from pathlib import Path
from typing import Any

import fitz

from services.rendering.output.typst.book_support import prepare_translated_pages_for_render
from services.rendering.output.typst.color_adapt import apply_adaptive_overlay_colors
from services.rendering.source.prewarm_manifest import color_tuple


RENDER_COLOR_PROFILE_ALGORITHM_VERSION = "render_color_profile_v2_tuple_color"


def build_render_color_profile_manifest(
    *,
    source_pdf_path: Path,
    translated_pages: dict[int, list[dict]],
    first_line_indent_lookup: dict[str, float],
    effective_inner_bbox_lookup: dict[str, list[float]],
    prepared_translated_pages: dict[int, list[dict]] | None = None,
    color_adapted_pages: dict[int, list[dict]] | None = None,
) -> dict[str, Any]:
    try:
        prepared = prepared_translated_pages or prepare_translated_pages_for_render(
            source_pdf_path,
            translated_pages,
            first_line_indent_lookup=first_line_indent_lookup,
            effective_inner_bbox_lookup=effective_inner_bbox_lookup,
        )
        adapted = color_adapted_pages or apply_page_color_adapt_for_prewarm(source_pdf_path, prepared)
        colors: dict[str, dict[str, list[float]]] = {}
        for items in adapted.values():
            for item in items:
                item_id = str(item.get("item_id") or "")
                if not item_id:
                    continue
                colors[item_id] = {
                    "cover_fill": round_color(item.get("_render_cover_fill", (1, 1, 1))),
                    "text_color": round_color(item.get("_render_text_color", (0, 0, 0))),
                }
        return {
            "algorithm": RENDER_COLOR_PROFILE_ALGORITHM_VERSION,
            "colors_by_item_id": colors,
        }
    except Exception as exc:
        print(f"render payload prewarm: color profile failed {type(exc).__name__}: {exc}", flush=True)
        return {}


def apply_page_color_adapt_for_prewarm(
    source_pdf_path: Path,
    translated_pages: dict[int, list[dict]],
) -> dict[int, list[dict]]:
    sample_doc = fitz.open(source_pdf_path)
    try:
        return {
            page_idx: apply_adaptive_overlay_colors(sample_doc[page_idx], items)
            if 0 <= page_idx < len(sample_doc)
            else list(items)
            for page_idx, items in translated_pages.items()
        }
    finally:
        sample_doc.close()


def render_colors_from_manifest(value: object) -> dict[str, dict[str, tuple[float, float, float]]]:
    payload = dict(value or {})
    if payload.get("algorithm") != RENDER_COLOR_PROFILE_ALGORITHM_VERSION:
        return {}
    result: dict[str, dict[str, tuple[float, float, float]]] = {}
    for item_id, raw in dict(payload.get("colors_by_item_id") or {}).items():
        if not isinstance(raw, dict):
            continue
        result[str(item_id)] = {
            "cover_fill": color_tuple(raw.get("cover_fill"), default=(1.0, 1.0, 1.0)),
            "text_color": color_tuple(raw.get("text_color"), default=(0.0, 0.0, 0.0)),
        }
    return result


def round_color(value: object) -> list[float]:
    color = color_tuple(value, default=(0.0, 0.0, 0.0))
    return [round(float(component), 5) for component in color]


__all__ = [
    "RENDER_COLOR_PROFILE_ALGORITHM_VERSION",
    "apply_page_color_adapt_for_prewarm",
    "build_render_color_profile_manifest",
    "render_colors_from_manifest",
]
