from __future__ import annotations

from pathlib import Path

from services.rendering.source.prewarm import RenderPrewarmSpec
from services.rendering.source.prewarm import prewarm_manifest_path_from_artifacts_dir
from services.rendering.source.prewarm import start_render_source_prewarm
from services.translation.public import build_translation_record
from services.translation.public import extract_text_items
from services.translation.public import get_page_count
from services.translation.public import load_ocr_json


def build_source_render_preprocess_pages(
    *,
    source_json_path: Path,
    start_page: int,
    end_page: int,
    math_mode: str = "direct_typst",
) -> dict[int, list[dict]]:
    data = load_ocr_json(source_json_path)
    page_count = get_page_count(data)
    start = max(0, int(start_page))
    stop = page_count - 1 if int(end_page) < 0 else min(int(end_page), page_count - 1)
    pages: dict[int, list[dict]] = {}
    for page_idx in range(start, stop + 1):
        items = extract_text_items(data, page_idx=page_idx)
        pages[page_idx] = [
            build_translation_record(item, math_mode=math_mode)
            for item in items
        ]
    return pages


def run_ocr_render_preprocess(
    *,
    source_json_path: Path,
    source_pdf_path: Path,
    output_pdf_path: Path,
    artifacts_dir: Path,
    render_mode: str,
    start_page: int,
    end_page: int,
    pdf_compress_dpi: int,
    source_cleanup_strategy: str,
    math_mode: str = "direct_typst",
) -> Path | None:
    pages = build_source_render_preprocess_pages(
        source_json_path=source_json_path,
        start_page=start_page,
        end_page=end_page,
        math_mode=math_mode,
    )
    if not pages:
        return None
    handle = start_render_source_prewarm(
        RenderPrewarmSpec(
            source_pdf_path=source_pdf_path,
            output_pdf_path=output_pdf_path,
            artifacts_dir=artifacts_dir,
            translated_pages=pages,
            render_mode=render_mode,
            start_page=start_page,
            end_page=end_page,
            pdf_compress_dpi=pdf_compress_dpi,
            source_cleanup_strategy=source_cleanup_strategy,
        )
    )
    return handle.wait()


__all__ = [
    "build_source_render_preprocess_pages",
    "prewarm_manifest_path_from_artifacts_dir",
    "run_ocr_render_preprocess",
]
