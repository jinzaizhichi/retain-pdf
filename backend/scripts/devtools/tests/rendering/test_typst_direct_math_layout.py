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

def test_direct_math_layout_shrinks_font_to_fit_rect() -> None:
    font = fitz.Font(fontfile=str(fonts.DEFAULT_FONT_PATH))
    rect = fitz.Rect(0, 0, 90, 30)
    markdown_text = "观察到 $\\mathrm{Ph(i-PrO)SiH_2}$ (6) 的消耗速率快于其他硅烷"

    tokens = _build_direct_draw_tokens(markdown_text, font)
    font_size, placements = _fit_segment_layout(rect, tokens, font)

    assert placements
    assert font_size < fonts.DEFAULT_FONT_SIZE
    assert font_size >= fonts.MIN_FONT_SIZE


def test_direct_math_layout_keeps_formula_token_atomic_on_wrap() -> None:
    font = fitz.Font(fontfile=str(fonts.DEFAULT_FONT_PATH))
    rect = fitz.Rect(0, 0, 80, 80)
    markdown_text = "前文 $\\mathrm{Ph(i-PrO)SiH_2}$ 后文"

    tokens = _build_direct_draw_tokens(markdown_text, font)
    _font_size, placements = _fit_segment_layout(rect, tokens, font)

    formula_placements = [placement for placement in placements if placement["token"]["kind"] == "formula"]
    assert len(formula_placements) == 1
    assert formula_placements[0]["token"]["text"] == r"\mathrm{Ph(i-PrO)SiH_2}"


def test_suspicious_ocr_skip_detector_does_not_drop_continuation_direct_typst_block() -> None:
    items = [
        {
            "item_id": "p003-b000",
            "block_type": "text",
            "bbox": [56, 66, 301, 144],
            "continuation_group": "cg-002-003",
            "translation_unit_kind": "group",
            "math_mode": "direct_typst",
            "render_protected_text": "阴离子交叉反应中，醇类并不仅仅是作为反应介质或质子源来周转催化剂。",
            "translation_unit_protected_source_text": "A" * 1200,
        },
        {
            "item_id": "p003-b001",
            "block_type": "text",
            "bbox": [56, 148, 301, 226],
            "render_protected_text": "下一段",
            "translation_unit_protected_source_text": "B" * 20,
        },
    ]

    summary = detect_and_drop_suspicious_ocr_glued_blocks(
        items,
        page_idx=2,
        page_font_size=11.4,
        page_line_pitch=14.0,
        page_line_height=14.0,
        density_baseline=1.0,
        page_text_width_med=245.0,
    )

    assert summary["count"] == 0
    assert items[0]["render_protected_text"]


def test_direct_typst_continuation_split_keeps_inline_math_atomic() -> None:
    text = "前文 观察到 $\\mathrm{Ph(i-PrO)SiH_2}$ (6) 的消耗速率快于其他硅烷，后文。"
    chunks = split_protected_text_for_boxes(
        text,
        [],
        [26.0, 48.0],
        direct_math_mode=True,
    )

    assert len(chunks) == 2
    assert all(chunk.count("$") % 2 == 0 for chunk in chunks)
    assert not any("$\\mathrm{Ph(" in chunk and "$\\mathrm{Ph(i-PrO)SiH_2}$" not in chunk for chunk in chunks)
    assert sum("$\\mathrm{Ph(i-PrO)SiH_2}$" in chunk for chunk in chunks) == 1


def test_prepare_render_payloads_preserves_direct_typst_formula_at_group_boundary() -> None:
    translated_pages = {
        1: [
            {
                "item_id": "p002-b024",
                "page_idx": 1,
                "bbox": [320, 504, 565, 606],
                "block_type": "text",
                "math_mode": "direct_typst",
                "translation_unit_id": "__cg__:cg-002-003",
                "translation_unit_kind": "group",
                "continuation_group": "cg-002-003",
                "protected_source_text": "A" * 300,
                "translation_unit_protected_source_text": "A" * 600,
                "translation_unit_protected_translated_text": (
                    "前文保持在较低丰度（图1）。观察到 $\\mathrm{Ph(i-PrO)SiH_2}$ (6) 的消耗速率快于其他硅烷，"
                    "这使我们推测其可能是一种更优的还原剂。"
                ),
                "translation_unit_formula_map": [],
            }
        ],
        2: [
            {
                "item_id": "p003-b000",
                "page_idx": 2,
                "bbox": [56, 66, 301, 144],
                "block_type": "text",
                "math_mode": "direct_typst",
                "translation_unit_id": "__cg__:cg-002-003",
                "translation_unit_kind": "group",
                "continuation_group": "cg-002-003",
                "protected_source_text": "B" * 300,
                "translation_unit_protected_source_text": "A" * 600,
                "translation_unit_protected_translated_text": (
                    "前文保持在较低丰度（图1）。观察到 $\\mathrm{Ph(i-PrO)SiH_2}$ (6) 的消耗速率快于其他硅烷，"
                    "这使我们推测其可能是一种更优的还原剂。"
                ),
                "translation_unit_formula_map": [],
            }
        ],
    }

    prepared = prepare_render_payloads_by_page(translated_pages)
    page2_item = prepared[1][0]
    page3_item = prepared[2][0]

    chunks = [page2_item["render_protected_text"], page3_item["render_protected_text"]]
    assert all(chunk.count("$") % 2 == 0 for chunk in chunks)
    assert not any("$\\mathrm{Ph(" in chunk and "$\\mathrm{Ph(i-PrO)SiH_2}$" not in chunk for chunk in chunks)
    assert sum("$\\mathrm{Ph(i-PrO)SiH_2}$" in chunk for chunk in chunks) == 1


def test_build_render_blocks_skips_display_formula_blocks() -> None:
    items = [
        {
            "item_id": "p005-b004",
            "page_idx": 4,
            "bbox": [44.938, 94.87, 352.34, 133.75],
            "block_type": "formula",
            "block_kind": "formula",
            "normalized_sub_type": "display_formula",
            "source_text": "$$ Y_{i}=Y_{i}(1)\\cdot D_{i}+Y_{i}(0)\\cdot(1-D_{i}). $$",
            "protected_source_text": "$$ Y_{i}=Y_{i}(1)\\cdot D_{i}+Y_{i}(0)\\cdot(1-D_{i}). $$",
            "translated_text": "",
            "protected_translated_text": "",
            "should_translate": False,
            "classification_label": "skip_model_keep_origin",
            "skip_reason": "skip_model_keep_origin",
            "math_mode": "direct_typst",
            "formula_map": [],
            "translation_unit_kind": "single",
            "translation_unit_protected_source_text": "$$ Y_{i}=Y_{i}(1)\\cdot D_{i}+Y_{i}(0)\\cdot(1-D_{i}). $$",
            "translation_unit_protected_translated_text": "",
            "translation_unit_formula_map": [],
        }
    ]

    blocks = build_render_blocks(items, page_width=362.8349914550781, page_height=272.1260070800781)

    assert blocks == []


def test_build_render_blocks_skips_keep_origin_display_math_text_blocks() -> None:
    items = [
        {
            "item_id": "p005-b004",
            "page_idx": 4,
            "bbox": [25.988, 94.87, 352.34, 133.75],
            "block_type": "text",
            "block_kind": "text",
            "normalized_sub_type": "body",
            "source_text": "$$ \\lim_{\\epsilon\\to0^+} f(x) $$ $$ \\lim_{\\epsilon\\to0^+} g(x) $$",
            "protected_source_text": "$$ \\lim_{\\epsilon\\to0^+} f(x) $$ $$ \\lim_{\\epsilon\\to0^+} g(x) $$",
            "translated_text": "",
            "protected_translated_text": "",
            "should_translate": False,
            "classification_label": "skip_model_keep_origin",
            "skip_reason": "skip_model_keep_origin",
            "math_mode": "direct_typst",
            "formula_map": [],
            "translation_unit_kind": "single",
            "translation_unit_protected_source_text": "$$ \\lim_{\\epsilon\\to0^+} f(x) $$ $$ \\lim_{\\epsilon\\to0^+} g(x) $$",
            "translation_unit_protected_translated_text": "",
            "translation_unit_formula_map": [],
        }
    ]

    blocks = build_render_blocks(items, page_width=362.8349914550781, page_height=272.1260070800781)

    assert blocks == []


def test_build_render_blocks_skips_model_keep_origin_shell_commands_with_dollars() -> None:
    items = [
        {
            "item_id": "p006-b004",
            "page_idx": 5,
            "bbox": [125.9785, 254.1719, 278.8715, 276.2591],
            "block_type": "text",
            "block_kind": "text",
            "normalized_sub_type": "body",
            "source_text": "$ uv venv deeph --python=3.13 $ source deeph/bin/activate",
            "protected_source_text": "$ uv venv deeph --python=3.13 $ source deeph/bin/activate",
            "translated_text": "",
            "protected_translated_text": "",
            "should_translate": False,
            "classification_label": "skip_model_keep_origin",
            "skip_reason": "skip_model_keep_origin",
            "math_mode": "direct_typst",
            "formula_map": [],
            "translation_unit_kind": "single",
            "translation_unit_protected_source_text": "$ uv venv deeph --python=3.13 $ source deeph/bin/activate",
            "translation_unit_protected_translated_text": "",
            "translation_unit_formula_map": [],
        }
    ]

    blocks = build_render_blocks(items, page_width=595.28, page_height=841.89)

    assert blocks == []


