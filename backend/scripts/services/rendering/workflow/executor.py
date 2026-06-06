from __future__ import annotations

from pathlib import Path
import time

from foundation.config import fonts
from foundation.config import layout
from foundation.config import runtime
from runtime.pipeline.render_plan import RenderPlan
from services.rendering.workflow.context import RenderExecutionContext
from services.rendering.workflow.cover_fallback import TypstCoverFallbackPlan
from services.rendering.workflow.modes import run_background_typst_render
from services.rendering.workflow.modes import run_dual_render
from services.rendering.workflow.modes import run_overlay_render
from services.rendering.workflow.modes import run_selected_pages_overlay_render
from services.rendering.source.render_source import build_render_source_pdf
from services.rendering.source.prewarm import try_load_prewarmed_render_source_pdf
from services.rendering.source.prewarm import try_load_render_payload_prewarm
from services.rendering.source.prewarm_fingerprint import build_render_prewarm_fingerprint
from services.rendering.source.prewarm_manifest import write_json_atomic
from services.rendering.source.prewarm_manifest_io import build_prewarm_manifest


def execute_render_plan(
    *,
    render_plan: RenderPlan,
    output_pdf_path: Path,
    start_page: int,
    end_page: int,
    compile_workers: int | None = None,
    extract_selected_pages: bool = False,
    api_key: str = "",
    model: str = "",
    base_url: str = "",
    typst_font_family: str = fonts.TYPST_DEFAULT_FONT_FAMILY,
    pdf_compress_dpi: int = runtime.DEFAULT_PDF_COMPRESS_DPI,
    source_cleanup_strategy: str | None = None,
    render_prewarm_manifest_path: Path | None = None,
) -> int:
    start = max(0, start_page)
    stop = max(render_plan.selected_pages) if end_page < 0 else end_page
    cleanup_strategy = layout.normalize_source_cleanup_strategy(source_cleanup_strategy)
    render_source_pdf = (
        try_load_prewarmed_render_source_pdf(
            manifest_path=render_prewarm_manifest_path,
            source_pdf_path=render_plan.render_inputs.source_pdf_path,
            translated_pages=render_plan.selected_pages,
            effective_render_mode=render_plan.effective_render_mode,
            start_page=start,
            end_page=stop,
            pdf_compress_dpi=pdf_compress_dpi,
            source_cleanup_strategy=cleanup_strategy,
        )
        if render_prewarm_manifest_path is not None
        else None
    )
    payload_prewarm = (
        try_load_render_payload_prewarm(
            manifest_path=render_prewarm_manifest_path,
            source_pdf_path=render_plan.render_inputs.source_pdf_path,
            translated_pages=render_plan.selected_pages,
            effective_render_mode=render_plan.effective_render_mode,
            start_page=start,
            end_page=stop,
            pdf_compress_dpi=pdf_compress_dpi,
            source_cleanup_strategy=cleanup_strategy,
        )
        if render_prewarm_manifest_path is not None
        else None
    )
    render_source_prewarm_hit = render_source_pdf is not None
    render_source_sync_cache_written = False
    if render_source_pdf is None:
        sync_prepare_started = time.perf_counter()
        render_source_pdf = build_render_source_pdf(
            source_pdf_path=render_plan.render_inputs.source_pdf_path,
            output_pdf_path=(
                render_prewarm_manifest_path.parent / output_pdf_path.name
                if render_prewarm_manifest_path is not None
                else output_pdf_path
            ),
            pdf_compress_dpi=pdf_compress_dpi,
            translated_pages=render_plan.selected_pages,
            strip_hidden_text=render_plan.effective_render_mode != "overlay",
            start_page=start,
            end_page=stop,
            artifact_mode=render_prewarm_manifest_path is not None,
            bbox_text_strip_candidates=(
                payload_prewarm.bbox_text_strip_candidates
                if payload_prewarm is not None
                else None
            ),
            source_cleanup_strategy=cleanup_strategy,
        )
        render_source_sync_cache_written = _persist_sync_render_source_prewarm(
            manifest_path=render_prewarm_manifest_path,
            prepared=render_source_pdf,
            source_pdf_path=render_plan.render_inputs.source_pdf_path,
            translated_pages=render_plan.selected_pages,
            effective_render_mode=render_plan.effective_render_mode,
            start_page=start,
            end_page=stop,
            pdf_compress_dpi=pdf_compress_dpi,
            source_cleanup_strategy=cleanup_strategy,
            elapsed=time.perf_counter() - sync_prepare_started,
        )

    cover_fallback_plan = TypstCoverFallbackPlan.build(
        source_pdf_path=render_plan.render_inputs.source_pdf_path,
        translated_pages=render_plan.selected_pages,
        cleanup_strategy=cleanup_strategy,
        precleaned_page_indices=render_source_pdf.source_text_precleaned_page_indices,
        skipped_page_indices=render_source_pdf.bbox_text_strip_skipped_page_indices,
    )
    context = RenderExecutionContext(
        output_pdf_path=output_pdf_path,
        start_page=start,
        end_page=stop,
        compile_workers=compile_workers,
        api_key=api_key,
        model=model,
        base_url=base_url,
        typst_font_family=typst_font_family,
        pdf_compress_dpi=pdf_compress_dpi,
        source_image_compressed=render_source_pdf.image_compressed,
        indent_detection_pdf_path=render_plan.render_inputs.source_pdf_path,
        first_line_indent_lookup=(
            payload_prewarm.first_line_indent_lookup
            if payload_prewarm is not None
            else None
        ),
        effective_inner_bbox_lookup=(
            payload_prewarm.effective_inner_bbox_lookup
            if payload_prewarm is not None
            else None
        ),
        bbox_text_stripped_page_indices=render_source_pdf.bbox_text_stripped_page_indices,
        bbox_text_strip_skipped_page_indices=render_source_pdf.bbox_text_strip_skipped_page_indices,
        source_text_precleaned_page_indices=render_source_pdf.source_text_precleaned_page_indices,
        source_cleanup_strategy=cleanup_strategy,
        background_render_page_specs=(
            cover_fallback_plan.apply_to_page_specs(payload_prewarm.background_render_page_specs)
            if payload_prewarm is not None
            else None
        ),
        render_colors_by_item_id=(
            payload_prewarm.render_colors_by_item_id
            if payload_prewarm is not None
            else None
        ),
    )
    render_diagnostics: dict[str, object] = {}
    try:
        pages_rendered, render_diagnostics = _dispatch_render_mode(
            mode=render_plan.effective_render_mode,
            source_pdf_path=render_source_pdf.path,
            translated_pages=cover_fallback_plan.apply_to_translated_pages(render_plan.selected_pages),
            context=context,
            extract_selected_pages=extract_selected_pages,
        )
        return pages_rendered
    finally:
        execute_render_plan.last_render_diagnostics = {
            **render_diagnostics,
            "render_source_prewarm_hit": render_source_prewarm_hit,
            "render_payload_prewarm_hit": payload_prewarm is not None,
            "render_source_prewarm_manifest": str(render_prewarm_manifest_path or ""),
            "render_source_sync_cache_written": render_source_sync_cache_written,
            "source_cleanup_strategy": cleanup_strategy,
            "source_text_precleaned_pages": len(render_source_pdf.source_text_precleaned_page_indices),
            "bbox_text_stripped_pages": len(render_source_pdf.bbox_text_stripped_page_indices),
            "bbox_text_strip_skipped_pages": len(render_source_pdf.bbox_text_strip_skipped_page_indices),
        }
        for temp_source_path in render_source_pdf.temp_paths:
            temp_source_path.unlink(missing_ok=True)


def _persist_sync_render_source_prewarm(
    *,
    manifest_path: Path | None,
    prepared,
    source_pdf_path: Path,
    translated_pages: dict[int, list[dict]],
    effective_render_mode: str,
    start_page: int,
    end_page: int,
    pdf_compress_dpi: int,
    source_cleanup_strategy: str,
    elapsed: float,
) -> bool:
    if manifest_path is None:
        return False
    try:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest = build_prewarm_manifest(
            manifest_path=manifest_path,
            prepared=prepared,
            fingerprint=build_render_prewarm_fingerprint(
                source_pdf_path=source_pdf_path,
                translated_pages=translated_pages,
                effective_render_mode=effective_render_mode,
                start_page=start_page,
                end_page=end_page,
                pdf_compress_dpi=pdf_compress_dpi,
                source_cleanup_strategy=source_cleanup_strategy,
            ),
            elapsed=elapsed,
        )
        write_json_atomic(manifest_path, manifest)
        print(f"render prewarm: cached synchronous source manifest={manifest_path}", flush=True)
        return True
    except Exception as exc:
        print(f"render prewarm: sync source cache write failed {type(exc).__name__}: {exc}", flush=True)
        return False


def _dispatch_render_mode(
    *,
    mode: str,
    source_pdf_path: Path,
    translated_pages: dict[int, list[dict]],
    context: RenderExecutionContext,
    extract_selected_pages: bool,
) -> tuple[int, dict[str, object]]:
    if mode == "dual":
        return run_dual_render(
            source_pdf_path=source_pdf_path,
            translated_pages=translated_pages,
            context=context,
        )

    if extract_selected_pages:
        return run_selected_pages_overlay_render(
            source_pdf_path=source_pdf_path,
            translated_pages=translated_pages,
            context=context,
        )

    if mode == "overlay":
        return run_overlay_render(
            source_pdf_path=source_pdf_path,
            translated_pages=translated_pages,
            context=context,
        )

    if mode in {"typst", "typst_visual"}:
        return run_background_typst_render(
            source_pdf_path=source_pdf_path,
            translated_pages=translated_pages,
            context=context,
            visual_only_background=mode == "typst_visual",
        )

    return run_overlay_render(
        source_pdf_path=source_pdf_path,
        translated_pages=translated_pages,
        context=context,
    )
