from __future__ import annotations

import time
from pathlib import Path

import fitz

from services.pipeline_shared.events import emit_render_page_progress
from services.rendering.source.cleanup.ops import merge_rects
from services.rendering.source.cleanup.ops import remove_text_under_rects
from services.rendering.source.cleanup.vector_analysis import page_drawing_count
from services.rendering.source.cleanup.vector_analysis import page_is_vector_heavy_count
from services.rendering.source.background import page_has_large_background_image
from services.rendering.source.background.source_overlay import apply_source_page_overlay
from services.rendering.output.typst.overlay_diagnostics import apply_merge_elapsed
from services.rendering.output.typst.overlay_diagnostics import apply_redaction_diagnostics
from services.rendering.output.typst.overlay_diagnostics import new_overlay_merge_diagnostics


def mark_image_page_overlay_mode(page: fitz.Page, translated_items: list[dict]) -> list[dict]:
    if not translated_items:
        return translated_items
    if not page_has_large_background_image(page):
        return translated_items
    return translated_items


def overlay_pages_from_single_pdf(
    doc: fitz.Document,
    ordered_page_indices: list[int],
    translated_pages: dict[int, list[dict]],
    overlay_pdf_path: Path,
    *,
    cover_only: bool = False,
    apply_source_overlay: bool = True,
    remove_source_text_by_bbox: bool = False,
    redaction_strategy: str | None = None,
    redaction_pages: dict[int, list[dict]] | None = None,
) -> dict[str, object]:
    overlay_doc = fitz.open(overlay_pdf_path)
    diagnostics = new_overlay_merge_diagnostics()
    try:
        total_pages = len(ordered_page_indices)
        for overlay_page_idx, page_idx in enumerate(ordered_page_indices):
            print(
                f"overlay merge page {overlay_page_idx + 1}/{total_pages} -> source page {page_idx + 1}",
                flush=True,
            )
            emit_render_page_progress(
                current=overlay_page_idx + 1,
                total=total_pages,
                message=f"正在渲染第 {overlay_page_idx + 1}/{total_pages} 页",
                payload={"page_index": page_idx, "render_stage": "single_pdf_overlay"},
            )
            page = doc[page_idx]
            page_diag = {
                "page_index": page_idx,
                "source_overlay_elapsed_seconds": 0.0,
                "overlay_merge_elapsed_seconds": 0.0,
            }
            if apply_source_overlay:
                redaction = apply_source_page_overlay(
                    page,
                    translated_pages[page_idx],
                    cover_only=cover_only,
                    redaction_strategy=redaction_strategy,
                    redaction_items=(redaction_pages or {}).get(page_idx),
                )
                apply_redaction_diagnostics(diagnostics, page_diag, redaction)
            elif remove_source_text_by_bbox:
                cleanup_started = time.perf_counter()
                drawing_count = page_drawing_count(page)
                if page_is_vector_heavy_count(drawing_count):
                    cleanup_elapsed = time.perf_counter() - cleanup_started
                    page_diag.update(
                        {
                            "items": 0,
                            "raw_removable_rects": 0,
                            "merged_removable_rects": 0,
                            "cover_rects": 0,
                            "fast_page_cover_only": False,
                            "item_fast_cover_count": 0,
                            "route": "bbox_text_layer_cleanup_skipped_vector_heavy",
                            "strategy": "text_layer_only",
                            "elapsed_seconds": cleanup_elapsed,
                            "source_overlay_mode": "bbox_text_layer_cleanup_skipped_vector_heavy",
                            "page_drawing_count": drawing_count,
                        }
                    )
                    diagnostics["source_overlay_elapsed_seconds"] = float(
                        diagnostics.get("source_overlay_elapsed_seconds", 0.0) or 0.0
                    ) + cleanup_elapsed
                    diagnostics["bbox_text_cleanup_skipped_vector_heavy_pages"] = int(
                        diagnostics.get("bbox_text_cleanup_skipped_vector_heavy_pages", 0) or 0
                    ) + 1
                    diagnostics["bbox_text_cleanup_skipped_vector_heavy_drawings"] = int(
                        diagnostics.get("bbox_text_cleanup_skipped_vector_heavy_drawings", 0) or 0
                    ) + drawing_count
                    diagnostics["pages"].append(page_diag)
                    merge_started = time.perf_counter()
                    page.show_pdf_page(page.rect, overlay_doc, overlay_page_idx, overlay=True)
                    merge_elapsed = time.perf_counter() - merge_started
                    apply_merge_elapsed(diagnostics, page_diag, merge_elapsed)
                    continue

                cleanup_items = (redaction_pages or {}).get(page_idx) or translated_pages[page_idx]
                cleanup_rects = []
                for item in cleanup_items:
                    bbox = item.get("bbox", [])
                    if len(bbox) != 4:
                        continue
                    rect = fitz.Rect(bbox)
                    if not rect.is_empty:
                        cleanup_rects.append(rect)
                merged_rects = merge_rects(cleanup_rects)
                remove_text_under_rects(page, merged_rects)
                cleanup_elapsed = time.perf_counter() - cleanup_started
                page_diag.update(
                    {
                        "items": len(cleanup_rects),
                        "raw_removable_rects": len(cleanup_rects),
                        "merged_removable_rects": len(merged_rects),
                        "cover_rects": 0,
                        "fast_page_cover_only": False,
                        "item_fast_cover_count": 0,
                        "route": "bbox_text_layer_cleanup",
                        "strategy": "text_layer_only",
                        "elapsed_seconds": cleanup_elapsed,
                        "source_overlay_mode": "bbox_text_layer_cleanup",
                        "page_drawing_count": drawing_count,
                    }
                )
                diagnostics["source_overlay_elapsed_seconds"] = float(
                    diagnostics.get("source_overlay_elapsed_seconds", 0.0) or 0.0
                ) + cleanup_elapsed
                diagnostics["raw_removable_rects"] = int(diagnostics.get("raw_removable_rects", 0) or 0) + len(cleanup_rects)
                diagnostics["merged_removable_rects"] = int(
                    diagnostics.get("merged_removable_rects", 0) or 0
                ) + len(merged_rects)
                diagnostics["bbox_text_cleanup_pages"] = int(
                    diagnostics.get("bbox_text_cleanup_pages", 0) or 0
                ) + 1
            merge_started = time.perf_counter()
            page.show_pdf_page(page.rect, overlay_doc, overlay_page_idx, overlay=True)
            merge_elapsed = time.perf_counter() - merge_started
            apply_merge_elapsed(diagnostics, page_diag, merge_elapsed)
            diagnostics["pages"].append(page_diag)
    finally:
        overlay_doc.close()
    return diagnostics
