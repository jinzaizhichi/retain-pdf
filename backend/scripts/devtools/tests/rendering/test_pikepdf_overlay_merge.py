import sys
import tempfile
from pathlib import Path
from unittest import mock
import re

import fitz
import pytest
from PIL import Image


REPO_SCRIPTS_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_SCRIPTS_ROOT))


from services.rendering.source.background.stage import build_clean_background_pdf
from foundation.config import fonts
from services.rendering.layout.payload.blocks import build_render_blocks
from services.rendering.layout.payload.body_pipeline import apply_body_payload_pipeline
from services.rendering.layout.payload.collision import mark_adjacent_collision_risk
from services.rendering.layout.payload.emit import payload_to_render_block
from services.rendering.layout.payload.first_line_indent import detect_first_line_indent_pt
from services.rendering.layout.payload.line_structure import maybe_preserve_structured_line_breaks
from services.rendering.layout.model.models import RenderLayoutBlock
from services.rendering.layout.model.models import RenderPageSpec
from services.rendering.layout.page_specs import build_render_page_specs
from services.rendering.layout.payload.continuation_split import split_protected_text_for_boxes
from services.rendering.layout.payload.prepare import prepare_render_payloads_by_page
from services.rendering.source.items import get_item_translated_text
from services.rendering.source.dev_overlay.text_draw import _build_direct_draw_tokens
from services.rendering.source.dev_overlay.text_draw import _fit_segment_layout
from services.rendering.layout.payload.suspicious_ocr import detect_and_drop_suspicious_ocr_glued_blocks
from services.rendering.output.typst.book_renderer import _compile_render_pages_pdf_resilient
from services.rendering.output.typst.block_renderer import build_typst_block
from services.rendering.output.typst.overlay_ops import overlay_translated_pages_on_doc
from services.rendering.output.typst.book_support import prepare_translated_pages_for_render
from services.rendering.output.typst.compiler import _resolved_font_paths
from services.rendering.output.typst.compiler import _resolved_common_root
from services.rendering.output.typst.compiler import TypstCompileError
from services.rendering.output.typst.compiler import compile_typst_book_background_pdf
from services.rendering.output.typst.compiler import compile_typst_overlay_pdf
from services.rendering.output.typst.compiler import compile_typst_render_pages_pdf
from services.rendering.output.typst.emitter import build_typst_source_from_page_specs
from services.rendering.output.typst.source_builder import build_typst_overlay_source
from services.rendering.policy import apply_render_page_policy_fields
from services.rendering.policy import build_render_page_policy
from services.rendering.policy import formula_neighbor_text_item_ids
from services.rendering.policy import item_render_policy
from services.rendering.policy import item_render_policy_reason
from services.rendering.policy import item_requires_visual_cover_only
from services.rendering.policy import item_uses_white_overlay_fill
from services.rendering.policy import protect_formula_regions_in_redaction_items
from services.rendering.output.typst.source_page_overlay import apply_source_page_overlay
from services.rendering.output.typst.overlay_diagnostics import apply_redaction_diagnostics
from services.rendering.output.typst.overlay_diagnostics import new_overlay_merge_diagnostics
from services.rendering.source.background.redaction_items import redaction_items_from_layout_blocks
from services.rendering.source.cleanup.item_rects import cover_rects_from_valid_items
from services.rendering.output.typst.source_page_overlay import overlay_pages_from_single_pdf
from services.rendering.output.typst.source_page_overlay import redaction_items_from_render_blocks
from services.rendering.output.typst.sanitize import sanitize_items_for_typst_compile
from services.rendering.output.typst.overlay_ops import _extract_failed_overlay_indices
from services.rendering.output.typst.overlay_ops import _can_use_pikepdf_book_overlay
from services.rendering.workflow.executor import _typst_cover_fallback_page_indices
from services.rendering.workflow.context import RenderExecutionContext
from services.rendering.workflow.modes import _compress_final_pdf_if_needed
from services.rendering.document.pikepdf_overlay import overlay_pdf_pages_with_pikepdf
from services.rendering.document.pikepdf_overlay import overlay_page_pdfs_with_pikepdf
from services.rendering.document.pikepdf_pages import extract_pages_with_pikepdf
from services.rendering.layout.inline_content.core.markdown import build_direct_typst_passthrough_text


def _page_spec(background_pdf_path: Path | None = None) -> RenderPageSpec:
    return RenderPageSpec(
        page_index=0,
        page_width_pt=200.0,
        page_height_pt=300.0,
        background_pdf_path=background_pdf_path,
        blocks=[
            RenderLayoutBlock(
                block_id="b1",
                page_index=0,
                background_rect=[10.0, 20.0, 80.0, 60.0],
                content_rect=[12.0, 22.0, 78.0, 58.0],
                content_kind="markdown",
                content_text="hello $x^2$",
                plain_text="hello x^2",
                math_map=[],
                font_size_pt=10.0,
                leading_em=0.6,
            )
        ],
    )

def test_pikepdf_overlay_merges_overlay_page_without_pymupdf_write() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source_pdf = root / "source.pdf"
        overlay_pdf = root / "overlay.pdf"
        output_pdf = root / "merged.pdf"

        doc = fitz.open()
        page = doc.new_page(width=200, height=120)
        page.insert_text((20, 40), "source text", fontsize=12)
        doc.save(source_pdf)
        doc.close()

        doc = fitz.open()
        page = doc.new_page(width=200, height=120)
        page.insert_text((20, 80), "overlay text", fontsize=12)
        doc.save(overlay_pdf)
        doc.close()

        result = overlay_pdf_pages_with_pikepdf(
            source_pdf_path=source_pdf,
            overlay_pdf_path=overlay_pdf,
            output_pdf_path=output_pdf,
        )

        assert result.pages_merged == 1
        merged = fitz.open(output_pdf)
        try:
            text = merged[0].get_text()
        finally:
            merged.close()
        assert "source text" in text
        assert "overlay text" in text


def test_pikepdf_overlay_merges_single_page_pdfs_by_source_page() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source_pdf = root / "source.pdf"
        page_two_overlay = root / "page-two-overlay.pdf"
        output_pdf = root / "merged.pdf"

        doc = fitz.open()
        for index in range(3):
            page = doc.new_page(width=200, height=120)
            page.insert_text((20, 40), f"source page {index + 1}", fontsize=12)
        doc.save(source_pdf)
        doc.close()

        doc = fitz.open()
        page = doc.new_page(width=200, height=120)
        page.insert_text((20, 80), "page two overlay", fontsize=12)
        doc.save(page_two_overlay)
        doc.close()

        result = overlay_page_pdfs_with_pikepdf(
            source_pdf_path=source_pdf,
            overlay_paths_by_page_index={1: page_two_overlay},
            output_pdf_path=output_pdf,
        )

        assert result.pages_merged == 1
        merged = fitz.open(output_pdf)
        try:
            assert "page two overlay" not in merged[0].get_text()
            assert "page two overlay" in merged[1].get_text()
            assert "page two overlay" not in merged[2].get_text()
        finally:
            merged.close()


def test_single_pdf_overlay_can_write_final_pdf_with_pikepdf() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source_pdf = root / "source.pdf"
        overlay_pdf = root / "overlay.pdf"
        output_pdf = root / "merged.pdf"

        doc = fitz.open()
        for index in range(2):
            page = doc.new_page(width=200, height=120)
            page.insert_text((20, 40), f"source page {index + 1}", fontsize=12)
        doc.save(source_pdf)
        doc.close()

        doc = fitz.open()
        for index in range(2):
            page = doc.new_page(width=200, height=120)
            page.insert_text((20, 80), f"overlay page {index + 1}", fontsize=12)
        doc.save(overlay_pdf)
        doc.close()

        source_doc = fitz.open(source_pdf)
        try:
            diagnostics = overlay_pages_from_single_pdf(
                source_doc,
                [0, 1],
                {
                    0: [{"item_id": "p001-b001", "bbox": [10.0, 10.0, 50.0, 30.0]}],
                    1: [{"item_id": "p002-b001", "bbox": [10.0, 10.0, 50.0, 30.0]}],
                },
                overlay_pdf,
                apply_source_overlay=False,
                skip_visual_cover=True,
                source_base_pdf_path=source_pdf,
                pikepdf_output_pdf_path=output_pdf,
            )
        finally:
            source_doc.close()

        assert diagnostics["mode"] == "single_pdf_overlay_pikepdf"
        assert diagnostics["pikepdf_overlay_pages"] == 2
        merged = fitz.open(output_pdf)
        try:
            assert "source page 1" in merged[0].get_text()
            assert "overlay page 1" in merged[0].get_text()
            assert "source page 2" in merged[1].get_text()
            assert "overlay page 2" in merged[1].get_text()
        finally:
            merged.close()


def test_pikepdf_extract_pages_copies_selected_page() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source_pdf = root / "source.pdf"
        output_pdf = root / "selected.pdf"
        doc = fitz.open()
        for index in range(3):
            page = doc.new_page(width=200, height=120)
            page.insert_text((20, 40), f"page {index + 1}", fontsize=12)
        doc.save(source_pdf)
        doc.close()

        extract_pages_with_pikepdf(
            source_pdf_path=source_pdf,
            output_pdf_path=output_pdf,
            start_page=1,
            end_page=1,
        )

        selected = fitz.open(output_pdf)
        try:
            assert selected.page_count == 1
            text = selected[0].get_text()
        finally:
            selected.close()
        assert "page 2" in text
        assert "page 1" not in text


