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

def test_body_font_unify_then_leading_refit_preserves_page_font_consistency() -> None:
    def make_payload(y0: float, y1: float, font_size: float, source_lines: int) -> dict:
        return {
            "inner_bbox": [10.0, y0, 260.0, y1],
            "translated_text": "这是一个用于测试页面级字体统一和行距二次拟合的正文段落。" * 2,
            "formula_map": [],
            "font_size_pt": font_size,
            "leading_em": 0.54,
            "dense_small_box": False,
            "heavy_dense_small_box": False,
            "is_body": True,
            "render_kind": "markdown",
            "prefer_typst_fit": False,
            "item": {
                "source_text": "body text with enough words for smoothing and refit",
                "bbox": [10.0, y0, 260.0, y1],
                "lines": [
                    {"bbox": [10.0, y0 + index * 12.0, 260.0, y0 + 10.0 + index * 12.0]}
                    for index in range(source_lines)
                ],
            },
        }

    compact = make_payload(10.0, 100.0, 10.0, 5)
    loose = make_payload(120.0, 300.0, 10.6, 12)

    apply_body_payload_pipeline([compact, loose], page_text_width_med=220.0)

    assert compact["font_size_pt"] == loose["font_size_pt"]
    assert loose["leading_em"] > compact["leading_em"] + 0.2
    assert loose["leading_em"] <= 1.02


def test_page_long_body_anchors_do_not_raise_single_line_body_font() -> None:
    def make_payload(y0: float, y1: float, font_size: float, text: str, source_lines: int) -> dict:
        return {
            "inner_bbox": [10.0, y0, 280.0, y1],
            "translated_text": text,
            "formula_map": [],
            "font_size_pt": font_size,
            "leading_em": 0.54,
            "dense_small_box": False,
            "heavy_dense_small_box": False,
            "is_body": True,
            "render_kind": "markdown",
            "prefer_typst_fit": False,
            "item": {
                "source_text": "body text with enough words for page anchor policy",
                "bbox": [10.0, y0, 280.0, y1],
                "lines": [
                    {"bbox": [10.0, y0 + index * 12.0, 280.0, y0 + 10.0 + index * 12.0]}
                    for index in range(source_lines)
                ],
            },
        }

    long_a = make_payload(10.0, 112.0, 10.8, "这是一个较长正文段落，用于稳定页面字体基准。" * 5, 8)
    long_b = make_payload(130.0, 232.0, 10.9, "这是另一个较长正文段落，用于稳定页面字体基准。" * 5, 8)
    short = make_payload(248.0, 262.0, 9.4, "短正文也应该继承页面字体。", 1)

    apply_body_payload_pipeline([long_a, long_b, short], page_text_width_med=240.0)

    assert short["font_size_pt"] == 9.4
    assert short.get("page_body_font_size_pt", 0.0) <= 9.7


def test_body_font_unify_shrinks_large_body_fonts_to_low_page_anchor() -> None:
    def make_payload(y0: float, y1: float, font_size: float, text: str, source_lines: int) -> dict:
        return {
            "inner_bbox": [45.0, y0, 385.0, y1],
            "translated_text": text,
            "formula_map": [],
            "font_size_pt": font_size,
            "leading_em": 0.56,
            "dense_small_box": False,
            "heavy_dense_small_box": False,
            "is_body": True,
            "render_kind": "markdown",
            "prefer_typst_fit": False,
            "item": {
                "source_text": "body text with enough words for page font unification",
                "bbox": [45.0, y0, 385.0, y1],
                "lines": [
                    {"bbox": [45.0, y0 + index * 12.0, 385.0, y0 + 10.0 + index * 12.0]}
                    for index in range(source_lines)
                ],
            },
        }

    long_a = make_payload(60.0, 116.0, 11.27, "这是稳定页面字号的长正文段落。" * 4, 5)
    long_b = make_payload(150.0, 212.0, 11.19, "这是另一个稳定页面字号的长正文段落。" * 5, 6)
    compact = make_payload(490.0, 525.0, 9.67, "这是较短但仍属于正文的段落，不能在同页显著小一圈。" * 3, 3)

    apply_body_payload_pipeline([long_a, long_b, compact], page_text_width_med=340.0)

    assert compact["font_size_pt"] <= 9.86
    assert max(payload["font_size_pt"] for payload in [long_a, long_b, compact]) / compact["font_size_pt"] < 1.08
    assert long_a["font_size_pt"] <= 10.5


def test_body_font_unify_locks_page_candidates_to_single_target() -> None:
    def make_payload(y0: float, y1: float, font_size: float, text: str, source_lines: int) -> dict:
        return {
            "inner_bbox": [45.0, y0, 385.0, y1],
            "translated_text": text,
            "formula_map": [],
            "font_size_pt": font_size,
            "leading_em": 0.56,
            "dense_small_box": False,
            "heavy_dense_small_box": False,
            "is_body": True,
            "render_kind": "markdown",
            "prefer_typst_fit": False,
            "item": {
                "source_text": "body text with enough words for page font unification",
                "bbox": [45.0, y0, 385.0, y1],
                "lines": [
                    {"bbox": [45.0, y0 + index * 12.0, 385.0, y0 + 10.0 + index * 12.0]}
                    for index in range(source_lines)
                ],
            },
        }

    top = make_payload(60.0, 86.0, 11.17, "这是顶部正文段落，用于模拟视觉字号偏大的短段。" * 2, 2)
    middle = make_payload(110.0, 160.0, 11.19, "这是中部正文段落，用于模拟视觉字号偏大的多行段。" * 3, 4)
    low = make_payload(190.0, 226.0, 9.57, "这是同栏正文段落，应该作为低字号统一目标。" * 2, 3)

    apply_body_payload_pipeline([top, middle, low], page_text_width_med=340.0)

    fonts = {payload["font_size_pt"] for payload in (top, middle, low)}
    assert len(fonts) == 1
    assert fonts == {9.57}


def test_collision_keeps_unified_body_font_and_only_compresses_leading() -> None:
    current = {
        "inner_bbox": [45.0, 490.0, 384.0, 525.0],
        "translated_text": "这里乘积函数是一个新的高斯函数，中心位于某处，并包含多个较长说明。" * 3,
        "formula_map": [],
        "font_size_pt": 11.17,
        "page_body_font_size_pt": 11.17,
        "leading_em": 0.72,
        "dense_small_box": False,
        "heavy_dense_small_box": False,
        "is_body": True,
        "render_kind": "markdown",
        "prefer_typst_fit": False,
        "adjacent_collision_risk": False,
        "item": {
            "source_text": "body text with nearby next block",
            "bbox": [45.0, 490.0, 384.0, 525.0],
            "lines": [{"bbox": [45.0, 490.0, 384.0, 502.0]}],
        },
    }
    nxt = {
        "inner_bbox": [45.0, 526.0, 384.0, 610.0],
        "translated_text": "下一段正文。",
        "formula_map": [],
        "font_size_pt": 11.17,
        "page_body_font_size_pt": 11.17,
        "leading_em": 0.72,
        "dense_small_box": False,
        "heavy_dense_small_box": False,
        "is_body": True,
        "render_kind": "markdown",
        "prefer_typst_fit": False,
        "adjacent_collision_risk": False,
        "item": {"source_text": "next body", "bbox": [45.0, 526.0, 384.0, 610.0], "lines": []},
    }

    mark_adjacent_collision_risk([current, nxt])

    assert current["font_size_pt"] == 11.17
    assert current["leading_em"] == 0.56
    assert current["prefer_typst_fit"] is False
    assert current["adjacent_collision_risk"] is False
    assert current["_body_collision_leading_only"] is True


def test_body_font_unify_includes_short_dense_body_without_typst_fit() -> None:
    def make_payload(
        y0: float,
        y1: float,
        font_size: float,
        text: str,
        *,
        dense: bool = False,
        heavy: bool = False,
        prefer_fit: bool = False,
    ) -> dict:
        return {
            "inner_bbox": [45.0, y0, 385.0, y1],
            "translated_text": text,
            "formula_map": [],
            "font_size_pt": font_size,
            "leading_em": 0.56,
            "dense_small_box": dense,
            "heavy_dense_small_box": heavy,
            "is_body": True,
            "render_kind": "markdown",
            "prefer_typst_fit": prefer_fit,
            "item": {
                "source_text": "body text",
                "bbox": [45.0, y0, 385.0, y1],
                "lines": [{"bbox": [45.0, y0, 385.0, y0 + 10.0]}],
            },
        }

    anchor_a = make_payload(60.0, 112.0, 11.17, "这是稳定页面字号的长正文段落。" * 4)
    anchor_b = make_payload(132.0, 190.0, 11.17, "这是另一个稳定页面字号的长正文段落。" * 4)
    short_dense = make_payload(
        210.0,
        223.0,
        10.2,
        "这里，变量 r 是从高斯球原点起测量的。",
        dense=True,
        heavy=True,
        prefer_fit=True,
    )

    apply_body_payload_pipeline([anchor_a, anchor_b, short_dense], page_text_width_med=340.0)

    assert short_dense["font_size_pt"] == anchor_a["font_size_pt"] == anchor_b["font_size_pt"]
    assert short_dense["prefer_typst_fit"] is False
    assert short_dense["_body_font_unified"] is True


def test_unified_body_font_still_uses_typst_fit_when_estimated_overflow() -> None:
    payload = {
        "index": "p024-b007",
        "item": {
            "item_id": "p024-b007",
            "bbox": [33.482, 541.747, 398.284, 613.214],
            "lines": [{"bbox": [33.482, 541.747, 398.284, 553.0]}],
            "protected_translated_text": "我们找到的波函数尚未归一化。归一化常数由式(3.93)给出。"
            "我们有积分近似、求和近似以及多个单元格公式，文本足够长以模拟统一字号后溢出。"
            * 6,
        },
        "bbox": [33.482, 541.747, 398.284, 613.214],
        "cover_bbox": [33.482, 541.747, 398.284, 613.214],
        "inner_bbox": [33.482, 542.819, 398.284, 612.142],
        "translated_text": "我们找到的波函数尚未归一化。归一化常数由式(3.93)给出。"
        "我们有积分近似、求和近似以及多个单元格公式，文本足够长以模拟统一字号后溢出。"
        * 6,
        "formula_map": [],
        "render_kind": "markdown",
        "font_size_pt": 10.35,
        "leading_em": 0.56,
        "first_line_indent_pt": 18.0,
        "font_weight": "regular",
        "page_body_font_size_pt": 10.35,
        "is_body": True,
        "dense_small_box": False,
        "heavy_dense_small_box": False,
        "prefer_typst_fit": False,
        "title_fit": None,
        "adjacent_collision_risk": False,
        "adjacent_available_height_pt": None,
        "_body_font_unified": True,
    }

    block = payload_to_render_block(payload)

    assert block.fit_to_box is True
    assert block.fit_max_height_pt <= 70.0
    assert block.fit_min_font_size_pt < block.font_size_pt


def test_caption_and_footnote_fonts_use_low_role_anchor() -> None:
    from services.rendering.layout.payload.annotation_font_policy import unify_annotation_fonts

    caption_a = {
        "item": {"layout_role": "caption", "semantic_role": "caption"},
        "render_kind": "markdown",
        "font_size_pt": 9.7,
    }
    caption_b = {
        "item": {"layout_role": "caption", "semantic_role": "caption"},
        "render_kind": "markdown",
        "font_size_pt": 8.9,
    }
    footnote_a = {
        "item": {"layout_role": "footnote", "semantic_role": "footnote"},
        "render_kind": "markdown",
        "font_size_pt": 8.7,
    }
    footnote_b = {
        "item": {"layout_role": "footnote", "semantic_role": "footnote"},
        "render_kind": "markdown",
        "font_size_pt": 7.8,
    }

    unify_annotation_fonts([caption_a, caption_b, footnote_a, footnote_b])

    assert caption_a["font_size_pt"] == 8.9
    assert caption_b["font_size_pt"] == 8.9
    assert footnote_a["font_size_pt"] == 7.84
    assert footnote_b["font_size_pt"] == 7.8
    assert footnote_a["font_size_pt"] < caption_a["font_size_pt"]


def test_role_font_unify_ignores_extreme_small_font_outlier() -> None:
    from services.rendering.layout.payload.annotation_font_policy import unify_annotation_fonts

    tiny = {
        "item": {"layout_role": "caption", "semantic_role": "caption"},
        "render_kind": "markdown",
        "font_size_pt": 5.2,
    }
    normal_a = {
        "item": {"layout_role": "caption", "semantic_role": "caption"},
        "render_kind": "markdown",
        "font_size_pt": 9.1,
    }
    normal_b = {
        "item": {"layout_role": "caption", "semantic_role": "caption"},
        "render_kind": "markdown",
        "font_size_pt": 9.4,
    }

    unify_annotation_fonts([tiny, normal_a, normal_b])

    assert normal_a["font_size_pt"] >= 9.1
    assert normal_b["font_size_pt"] >= 9.1


def test_caption_and_footnote_density_recovery_uses_same_floor_rule() -> None:
    from services.rendering.layout.payload.annotation_font_policy import recover_underfilled_annotation_density
    from services.rendering.layout.payload.body_common import payload_density

    def make_payload(role: str, height: float) -> dict:
        return {
            "item": {"layout_role": role, "semantic_role": role},
            "inner_bbox": [10.0, 0.0, 220.0, height],
            "translated_text": "注释文字用于测试密度恢复。" * 2,
            "formula_map": [],
            "render_kind": "markdown",
            "font_size_pt": 8.4 if role == "caption" else 7.4,
            "leading_em": 0.46,
        }

    caption_ok = make_payload("caption", 20.0)
    caption_low = make_payload("caption", 48.0)
    footnote_low = make_payload("footnote", 46.0)

    before_caption_ok = (caption_ok["font_size_pt"], caption_ok["leading_em"], payload_density(caption_ok))
    before_caption_low = payload_density(caption_low)
    before_footnote_low = payload_density(footnote_low)

    recover_underfilled_annotation_density([caption_ok, caption_low, footnote_low])

    assert before_caption_ok[2] >= 0.60
    assert (caption_ok["font_size_pt"], caption_ok["leading_em"]) == before_caption_ok[:2]
    assert before_caption_low < 0.60
    assert before_caption_low < payload_density(caption_low) < 1.0
    assert before_footnote_low < 0.60
    assert before_footnote_low < payload_density(footnote_low) < 1.0
    assert caption_low["font_size_pt"] > 8.4
    assert footnote_low["font_size_pt"] > 7.4
    assert footnote_low["font_size_pt"] <= caption_low["font_size_pt"]


def test_caption_and_footnote_recovery_do_not_exceed_body_font_reference() -> None:
    from services.rendering.layout.payload.annotation_font_policy import recover_underfilled_annotation_density

    body = {
        "item": {"layout_role": "paragraph", "semantic_role": "body"},
        "inner_bbox": [10.0, 0.0, 220.0, 30.0],
        "translated_text": "正文。",
        "formula_map": [],
        "render_kind": "markdown",
        "font_size_pt": 9.0,
        "leading_em": 0.56,
        "dense_small_box": False,
        "heavy_dense_small_box": False,
        "is_body": True,
    }
    caption = {
        "item": {"layout_role": "caption", "semantic_role": "caption"},
        "inner_bbox": [10.0, 40.0, 220.0, 100.0],
        "translated_text": "图题文字用于测试字号不能超过正文。" * 2,
        "formula_map": [],
        "render_kind": "markdown",
        "font_size_pt": 8.8,
        "leading_em": 0.46,
    }
    footnote = {
        "item": {"layout_role": "footnote", "semantic_role": "footnote"},
        "inner_bbox": [10.0, 110.0, 220.0, 170.0],
        "translated_text": "脚注文字用于测试字号低于正文。" * 2,
        "formula_map": [],
        "render_kind": "markdown",
        "font_size_pt": 8.2,
        "leading_em": 0.44,
    }

    recover_underfilled_annotation_density([body, caption, footnote])

    assert caption["font_size_pt"] <= round(body["font_size_pt"] * 0.88, 2)
    assert footnote["font_size_pt"] <= round(body["font_size_pt"] * 0.82, 2)


def test_caption_seed_font_is_restrained_below_body_scale() -> None:
    from services.rendering.layout.font_size_fit import local_font_size_pt

    item = {
        "layout_role": "caption",
        "semantic_role": "caption",
        "block_kind": "text",
        "source_text": "Figure 1. Caption text",
        "bbox": [10.0, 10.0, 210.0, 24.0],
        "lines": [{"bbox": [10.0, 10.0, 210.0, 24.0], "text": "Figure 1. Caption text"}],
    }

    assert local_font_size_pt(item) <= 10.0


def test_page_leading_baseline_only_weakly_dampens_normal_body_leading_jumps() -> None:
    def make_payload(height: float, source_lines: int) -> dict:
        return {
            "inner_bbox": [10.0, 0.0, 260.0, height],
            "translated_text": "普通正文段落用于测试页面行距基准。" * 2,
            "formula_map": [],
            "font_size_pt": 10.2,
            "leading_em": 0.54,
            "dense_small_box": False,
            "heavy_dense_small_box": False,
            "is_body": True,
            "render_kind": "markdown",
            "prefer_typst_fit": False,
            "item": {
                "source_text": "normal body words enough",
                "lines": [
                    {"bbox": [10.0, index * 10.0, 260.0, index * 10.0 + 8.0]}
                    for index in range(source_lines)
                ],
            },
        }

    compact = make_payload(90.0, 4)
    loose = make_payload(180.0, 7)

    apply_body_payload_pipeline([compact, loose], page_text_width_med=220.0)

    assert loose["leading_em"] >= compact["leading_em"]
    assert loose["leading_em"] - compact["leading_em"] <= 0.32


def test_loose_source_pitch_can_override_page_leading_baseline() -> None:
    def make_payload(height: float, source_lines: int, pitch: float) -> dict:
        return {
            "inner_bbox": [10.0, 0.0, 260.0, height],
            "translated_text": "普通正文段落用于测试很宽松英文原文对应的动态行距。" * 2,
            "formula_map": [],
            "font_size_pt": 10.2,
            "leading_em": 0.54,
            "dense_small_box": False,
            "heavy_dense_small_box": False,
            "is_body": True,
            "render_kind": "markdown",
            "prefer_typst_fit": False,
            "item": {
                "source_text": "normal body words enough",
                "lines": [
                    {"bbox": [10.0, index * pitch, 260.0, index * pitch + 8.0]}
                    for index in range(source_lines)
                ],
            },
        }

    compact = make_payload(90.0, 4, 10.0)
    loose = make_payload(210.0, 11, 18.0)

    apply_body_payload_pipeline([compact, loose], page_text_width_med=220.0)

    assert loose["leading_em"] >= compact["leading_em"] + 0.20
    assert loose["leading_em"] <= 1.02
