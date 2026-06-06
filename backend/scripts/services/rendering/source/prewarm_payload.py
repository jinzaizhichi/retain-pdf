from __future__ import annotations

from pathlib import Path
import time
from typing import Any

import fitz

from foundation.config import layout
from services.pipeline_shared.events import emit_stage_progress
from services.rendering.layout.payload.block_seed_metrics import collect_page_seed_metrics
from services.rendering.layout.payload.first_line_indent import detect_first_line_indent_pt_with_displaylist
from services.rendering.layout.payload.first_line_indent import is_first_line_indent_candidate
from services.rendering.layout.payload.render_item import get_render_first_line_indent_pt
from services.rendering.layout.payload.render_item import seed_render_fields
from services.rendering.source_cleanup.types import BBoxTextStripCandidates
from services.rendering.source_cleanup import plan_source_cleanup
from services.rendering.performance import should_use_fast_overlay_cover_path
from services.rendering.source.prewarm_color_profile import build_render_color_profile_manifest
from services.rendering.source.prewarm_contracts import FIRST_LINE_INDENT_ALGORITHM_VERSION
from services.rendering.source.prewarm_contracts import GEOMETRY_ADJUSTMENT_ALGORITHM_VERSION
from services.rendering.source.prewarm_contracts import PAYLOAD_RENDER_ALGORITHM_VERSION
from services.rendering.source.prewarm_manifest_io import bbox_candidates_to_manifest
from services.rendering.source.prewarm_page_specs import build_background_render_page_specs_manifest


def build_payload_prewarm(
    *,
    source_pdf_path: Path,
    translated_pages: dict[int, list[dict]],
    manifest_path: Path,
    effective_render_mode: str = "",
    source_cleanup_strategy: str = "pikepdf_text_strip",
    bbox_text_strip_candidates: BBoxTextStripCandidates | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    prepared_pages = seed_pages_for_payload_prewarm(translated_pages)
    first_line_indent_by_item_id: dict[str, float] = {}
    effective_inner_bbox_by_item_id: dict[str, list[float]] = {}
    page_widths = page_widths_by_index(source_pdf_path)
    with fitz.open(source_pdf_path) as source_doc:
        for page_idx, items in prepared_pages.items():
            page_width = page_widths.get(page_idx)
            try:
                metrics = collect_page_seed_metrics(items, page_width=page_width)
            except Exception as exc:
                print(f"render payload prewarm: geometry build failed page={page_idx + 1} {type(exc).__name__}: {exc}", flush=True)
                continue
            for index, bbox in metrics.effective_inner_bboxes.items():
                if index < 0 or index >= len(items):
                    continue
                item_id = str(items[index].get("item_id", "") or "")
                if item_id:
                    effective_inner_bbox_by_item_id[item_id] = [round(float(value), 3) for value in bbox]
            collect_first_line_indent_lookup(
                source_doc=source_doc,
                page_idx=page_idx,
                items=items,
                metrics=metrics,
                sink=first_line_indent_by_item_id,
            )
    mode = str(effective_render_mode or "").strip()
    skip_bbox_candidate_prewarm = should_use_fast_overlay_cover_path(
        translated_page_count=len([page_idx for page_idx, items in translated_pages.items() if items]),
        strip_hidden_text=mode != "overlay",
    )
    if layout.use_bbox_text_strip_cleanup(source_cleanup_strategy) and not skip_bbox_candidate_prewarm:
        try:
            bbox_candidates = (
                bbox_text_strip_candidates
                or plan_source_cleanup(
                    source_pdf_path=source_pdf_path,
                    translated_pages=translated_pages,
                    skip_formula_pages=False,
                )
            )
            bbox_payload = bbox_candidates_to_manifest(bbox_candidates)
        except Exception as exc:
            print(f"render payload prewarm: bbox candidate build failed {type(exc).__name__}: {exc}", flush=True)
            bbox_payload = {}
    else:
        bbox_payload = {}
    should_build_background_specs = mode in {"typst", "typst_visual"}
    render_color_profile = build_render_color_profile_manifest(
        source_pdf_path=source_pdf_path,
        translated_pages=translated_pages,
        first_line_indent_lookup=first_line_indent_by_item_id,
        effective_inner_bbox_lookup=effective_inner_bbox_by_item_id,
    )
    background_render_page_specs = (
        build_background_render_page_specs_manifest(
            source_pdf_path=source_pdf_path,
            translated_pages=translated_pages,
            first_line_indent_lookup=first_line_indent_by_item_id,
            effective_inner_bbox_lookup=effective_inner_bbox_by_item_id,
        )
        if should_build_background_specs
        else {}
    )
    elapsed_s = time.perf_counter() - started
    message = (
        f"render payload prewarm: ready mode={mode or 'unknown'} "
        f"indents={len(first_line_indent_by_item_id)} "
        f"geometry={len(effective_inner_bbox_by_item_id)} "
        f"background_specs={'yes' if should_build_background_specs else 'skipped'} "
        f"elapsed={elapsed_s:.2f}s"
    )
    emit_stage_progress(
        stage="render_preprocess",
        substage="render_prewarm",
        message=message,
        stage_detail="渲染 payload 预热完成",
        progress_current=2,
        progress_total=3,
        elapsed_ms=int(elapsed_s * 1000),
        payload={
            "user_stage": "render",
            "progress_unit": "step",
            "effective_render_mode": mode,
            "page_count": len(translated_pages),
            "indents": len(first_line_indent_by_item_id),
            "geometry": len(effective_inner_bbox_by_item_id),
            "background_specs": "built" if should_build_background_specs else "skipped",
        },
    )
    print(message, flush=True)
    return {
        "first_line_indent_algorithm": FIRST_LINE_INDENT_ALGORITHM_VERSION,
        "first_line_indent_by_item_id": first_line_indent_by_item_id,
        "geometry_adjustment_algorithm": GEOMETRY_ADJUSTMENT_ALGORITHM_VERSION,
        "payload_render_algorithm": PAYLOAD_RENDER_ALGORITHM_VERSION,
        "effective_render_mode": mode,
        "effective_inner_bbox_by_item_id": effective_inner_bbox_by_item_id,
        "bbox_text_strip_candidates": bbox_payload,
        "render_color_profile": render_color_profile,
        "background_render_page_specs": background_render_page_specs,
    }


def seed_pages_for_payload_prewarm(translated_pages: dict[int, list[dict]]) -> dict[int, list[dict]]:
    seeded: dict[int, list[dict]] = {}
    for page_idx, items in translated_pages.items():
        seeded_items: list[dict] = []
        for item in items:
            clone = dict(item)
            seed_render_fields(clone)
            seeded_items.append(clone)
        seeded[page_idx] = seeded_items
    return seeded


def collect_first_line_indent_lookup(
    *,
    source_doc: fitz.Document,
    page_idx: int,
    items: list[dict],
    metrics,
    sink: dict[str, float],
) -> None:
    if page_idx < 0 or page_idx >= len(source_doc):
        return
    candidates: list[tuple[dict, float]] = []
    for index, item in enumerate(items):
        item_id = str(item.get("item_id", "") or "")
        if not item_id:
            continue
        existing_indent = get_render_first_line_indent_pt(item)
        if existing_indent > 0:
            sink[item_id] = round(existing_indent, 2)
            continue
        base = metrics.base_metrics.get(index)
        if base is None:
            continue
        font_size_pt, _leading_em = base
        if not is_first_line_indent_candidate(item, page_text_width_med=metrics.page_text_width_med):
            continue
        candidates.append((item, font_size_pt))
    if not candidates:
        return
    displaylist = source_doc[page_idx].get_displaylist()
    for item, font_size_pt in candidates:
        item_id = str(item.get("item_id", "") or "")
        indent_pt = detect_first_line_indent_pt_with_displaylist(
            source_doc,
            displaylist,
            item,
            page_idx=page_idx,
            font_size_pt=font_size_pt,
            page_text_width_med=metrics.page_text_width_med,
        )
        if indent_pt > 0:
            sink[item_id] = round(indent_pt, 2)


def page_widths_by_index(source_pdf_path: Path) -> dict[int, float]:
    try:
        with fitz.open(source_pdf_path) as doc:
            return {index: float(page.rect.width) for index, page in enumerate(doc)}
    except Exception:
        return {}


__all__ = [
    "build_payload_prewarm",
    "collect_first_line_indent_lookup",
    "page_widths_by_index",
    "seed_pages_for_payload_prewarm",
]
