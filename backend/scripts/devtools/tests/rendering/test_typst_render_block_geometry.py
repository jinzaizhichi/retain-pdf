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

def test_build_render_blocks_uses_vertical_fit_for_tight_stacked_overlay_blocks() -> None:
    items = [
        {
            "item_id": "p001-b001",
            "page_idx": 0,
            "block_type": "text",
            "bbox": [20.0, 40.0, 210.0, 110.0],
            "lines": [{"text": "raw"}],
            "source_text": "upper",
            "protected_source_text": "upper",
            "protected_translated_text": (
                "这是一段会在渲染时变得明显更长的中文正文，用来模拟上方块在原始 OCR 框已经"
                "贴到下方块时，仍然需要继续压缩高度避免覆盖下一块。"
            ),
        },
        {
            "item_id": "p001-b002",
            "page_idx": 0,
            "block_type": "text",
            "bbox": [20.0, 109.7, 210.0, 152.0],
            "lines": [{"text": "raw"}],
            "source_text": "lower",
            "protected_source_text": "lower",
            "protected_translated_text": "下方块",
        },
    ]

    blocks = build_render_blocks(items, page_width=240.0, page_height=320.0)

    upper, lower = blocks
    expected_limit = lower.inner_bbox[1] - upper.inner_bbox[1] - 0.9
    assert upper.fit_to_box is True
    assert upper.fit_max_height_pt <= expected_limit
    assert upper.fit_min_font_size_pt <= upper.font_size_pt
    assert upper.fit_min_leading_em <= upper.leading_em


def test_build_render_blocks_binary_fits_long_translated_title_to_box() -> None:
    items = [
        {
            "item_id": "p001-title",
            "page_idx": 0,
            "block_type": "text",
            "block_kind": "text",
            "layout_role": "title",
            "structure_role": "title",
            "bbox": [20.0, 22.0, 180.0, 50.0],
            "lines": [{"text": "A Long Title"}],
            "source_text": "A Long Title",
            "protected_source_text": "A Long Title",
            "protected_translated_text": "这是一个非常长的中文标题需要在很窄的标题框里面自动缩小并且完整显示",
        }
    ]

    blocks = build_render_blocks(items, page_width=200.0, page_height=300.0)

    title = blocks[0]
    assert title.font_weight == "bold"
    assert title.fit_to_box is True
    assert title.fit_single_line is False
    assert title.font_size_pt < 12.0
    assert title.leading_em >= 0.34
    assert title.fit_min_font_size_pt < title.font_size_pt
    assert title.fit_target_width_pt == 160.0
    assert title.fit_target_height_pt == 28.0


def test_build_render_blocks_insets_tight_body_vertical_gap() -> None:
    items = [
        {
            "item_id": "p001-b001",
            "page_idx": 0,
            "block_type": "text",
            "block_kind": "text",
            "layout_role": "paragraph",
            "semantic_role": "body",
            "bbox": [20.0, 40.0, 220.0, 92.0],
            "lines": [{"text": "raw"}],
            "source_text": "This body paragraph has enough source text to be treated as body text.",
            "protected_source_text": "This body paragraph has enough source text to be treated as body text.",
            "protected_translated_text": "这是一段正文内容，用于确认 OCR 框上下贴得很近时可以获得一点有效高度余量。",
        },
        {
            "item_id": "p001-b002",
            "page_idx": 0,
            "block_type": "text",
            "block_kind": "text",
            "layout_role": "paragraph",
            "semantic_role": "body",
            "bbox": [20.0, 92.8, 220.0, 145.0],
            "lines": [{"text": "raw"}],
            "source_text": "This second body paragraph is in the same column and follows very closely.",
            "protected_source_text": "This second body paragraph is in the same column and follows very closely.",
            "protected_translated_text": "这是同一栏的下一段正文，用来给上一段提供安全边界。",
        },
    ]

    blocks = build_render_blocks(items, page_width=260.0, page_height=320.0)

    upper, lower = blocks
    assert upper.inner_bbox[1] > 40.0
    assert upper.inner_bbox[3] < 92.0
    assert (92.0 - 40.0) - (upper.inner_bbox[3] - upper.inner_bbox[1]) <= (92.0 - 40.0) * 0.03
    assert upper.cover_bbox[0] < 20.0
    assert upper.cover_bbox[1] < 40.0
    assert upper.cover_bbox[2] > 220.0
    assert upper.cover_bbox[3] > 92.0


def test_build_render_blocks_expands_short_body_region_up_and_right_only() -> None:
    items = [
        {
            "item_id": "p001-b001",
            "page_idx": 0,
            "block_type": "text",
            "block_kind": "text",
            "layout_role": "paragraph",
            "semantic_role": "body",
            "bbox": [30.0, 40.0, 230.0, 92.0],
            "lines": [{"text": "raw"}],
            "source_text": "This body paragraph has enough source text to be treated as body text.",
            "protected_source_text": "This body paragraph has enough source text to be treated as body text.",
            "protected_translated_text": "这是第一段正文，用于建立同一区域的宽正文参照。",
        },
        {
            "item_id": "p001-b002",
            "page_idx": 0,
            "block_type": "text",
            "block_kind": "text",
            "layout_role": "paragraph",
            "semantic_role": "body",
            "bbox": [31.0, 106.0, 231.0, 158.0],
            "lines": [{"text": "raw"}],
            "source_text": "This second body paragraph has enough source text to be treated as body text.",
            "protected_source_text": "This second body paragraph has enough source text to be treated as body text.",
            "protected_translated_text": "这是第二段正文，用于确认同列正文区域的宽度和位置。",
        },
        {
            "item_id": "p001-b003",
            "page_idx": 0,
            "block_type": "text",
            "block_kind": "text",
            "layout_role": "paragraph",
            "semantic_role": "body",
            "bbox": [34.0, 172.0, 144.0, 192.0],
            "lines": [{"text": "raw"}],
            "source_text": "Short but body-like text that belongs to the same paragraph region.",
            "protected_source_text": "Short but body-like text that belongs to the same paragraph region.",
            "protected_translated_text": "这是较短的第三段正文，翻译后需要更多宽度避免异常换行。",
        },
    ]

    blocks = build_render_blocks(items, page_width=260.0, page_height=320.0)

    short = blocks[2]
    assert short.inner_bbox[1] < 172.0
    assert short.inner_bbox[3] <= 192.0
    assert short.inner_bbox[2] > 144.0
    assert short.inner_bbox[2] <= 177.0


def test_build_render_blocks_expands_title_width_toward_body_column() -> None:
    items = [
        {
            "item_id": "p001-title",
            "page_idx": 0,
            "block_type": "text",
            "block_kind": "text",
            "layout_role": "heading",
            "structure_role": "heading",
            "bbox": [24.0, 24.0, 150.0, 48.0],
            "lines": [{"text": "Related work"}],
            "source_text": "Related work",
            "protected_source_text": "Related work",
            "protected_translated_text": "相关工作和方法",
        },
        {
            "item_id": "p001-b001",
            "page_idx": 0,
            "block_type": "text",
            "block_kind": "text",
            "layout_role": "paragraph",
            "semantic_role": "body",
            "bbox": [22.0, 60.0, 224.0, 128.0],
            "lines": [{"text": "raw"}],
            "source_text": "This body paragraph has enough source text to be treated as body text.",
            "protected_source_text": "This body paragraph has enough source text to be treated as body text.",
            "protected_translated_text": "这是标题下方的正文段落，用于给标题提供同栏宽度参考。",
        },
    ]

    blocks = build_render_blocks(items, page_width=260.0, page_height=320.0)

    title = blocks[0]
    assert title.inner_bbox[2] > 150.0
    assert title.fit_target_width_pt == title.inner_bbox[2] - title.inner_bbox[0]
    assert title.cover_bbox == [23.0, 23.0, 151.0, 49.0]


def test_build_render_blocks_expands_body_cover_bbox_slightly() -> None:
    items = [
        {
            "item_id": "p001-b001",
            "page_idx": 0,
            "block_type": "text",
            "block_kind": "text",
            "layout_role": "paragraph",
            "semantic_role": "body",
            "bbox": [20.0, 40.0, 220.0, 140.0],
            "lines": [{"text": "raw"}],
            "source_text": "This body paragraph has enough source text to be treated as body text.",
            "protected_source_text": "This body paragraph has enough source text to be treated as body text.",
            "protected_translated_text": "这是一段正文内容，用于确认背景遮盖区域会轻微扩张以防止原文边缘漏出。",
        },
    ]

    blocks = build_render_blocks(items, page_width=260.0, page_height=320.0)

    cover = blocks[0].cover_bbox
    assert cover[0] < 20.0
    assert cover[1] < 40.0
    assert cover[2] > 220.0
    assert cover[3] > 140.0
    assert cover[0] >= 17.0
    assert cover[3] <= 143.0


def test_build_render_blocks_uses_conservative_cover_y_near_inline_formula() -> None:
    items = [
        {
            "item_id": "p001-b001",
            "page_idx": 0,
            "block_type": "text",
            "block_kind": "text",
            "layout_role": "paragraph",
            "semantic_role": "body",
            "bbox": [20.0, 40.0, 220.0, 140.0],
            "lines": [{"text": "raw"}],
            "source_text": r"This paragraph contains $\frac{a}{b}$ inline math.",
            "protected_source_text": r"This paragraph contains $\frac{a}{b}$ inline math.",
            "protected_translated_text": r"这段正文包含 $\\frac{a}{b}$ 行内公式。",
        },
    ]

    blocks = build_render_blocks(items, page_width=260.0, page_height=320.0)

    cover = blocks[0].cover_bbox
    assert 39.5 < cover[1] < 40.0
    assert 140.0 < cover[3] < 140.5
    assert cover[0] < 20.0
    assert cover[2] > 220.0


def test_typst_overlay_source_uses_title_single_line_fit_when_title_fits_one_line() -> None:
    source = build_typst_overlay_source(
        200.0,
        300.0,
        [
            {
                "item_id": "p001-title",
                "page_idx": 0,
                "block_type": "text",
                "block_kind": "text",
                "layout_role": "title",
                "structure_role": "title",
                "bbox": [20.0, 22.0, 180.0, 58.0],
                "lines": [{"text": "Intro"}],
                "source_text": "Intro",
                "protected_source_text": "Intro",
                "protected_translated_text": "引言",
            }
        ],
    )

    assert "pdftr_fit_single_line_markdown" in source
    assert 'weight: "bold"' in source
    assert "fit_width: 160.0pt" in source
    assert "fit_height: 36.0pt" in source


