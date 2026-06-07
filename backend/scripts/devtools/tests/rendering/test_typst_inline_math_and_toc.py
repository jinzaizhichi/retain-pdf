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
from services.rendering.workflow.cover_fallback import cover_fallback_page_indices
from services.rendering.workflow.context import RenderExecutionContext
from services.rendering.workflow.modes import _compress_final_pdf_if_needed
from services.rendering.document.pikepdf_overlay import overlay_pdf_pages_with_pikepdf
from services.rendering.document.pikepdf_overlay import overlay_page_pdfs_with_pikepdf
from services.rendering.document.pikepdf_pages import extract_pages_with_pikepdf
from services.rendering.layout.inline_content.core.markdown import build_direct_typst_passthrough_text
from devtools.tests.rendering_support.page_specs import sample_page_spec as _page_spec
from services.rendering.layout.model.models import RenderBlock
from services.rendering.layout.payload.formula_safety import formula_safety_insets_pt


def test_text_heavy_inline_math_demotes_latex_text_to_plain_text() -> None:
    blocks = build_render_blocks(
        [
            {
                "item_id": "p020-b015",
                "page_idx": 19,
                "block_type": "text",
                "block_kind": "text",
                "normalized_sub_type": "body",
                "bbox": [50.988, 307.815, 386.912, 332.3],
                "source_text": (
                    r"$ (\nabla_i \equiv \nabla_{r_i}, \text{with } \mathbf{r}_i "
                    r"\text{ denoting the position of electron } i), \text{ the interaction between electrons "
                    r"and nuclei (with charges } Z_\alpha e, e = |e|), $"
                ),
                "protected_translated_text": (
                    r"$ (\nabla_i \equiv \nabla_{r_i}, \text{其中 } \mathbf{r}_i "
                    r"\text{ 表示电子 } i \text{ 的位置}), \text{电子与原子核（带有电荷 } "
                    r"Z_\alpha e, e = |e|) \text{ 之间的相互作用}, $"
                ),
            }
        ],
        page_width=595.0,
        page_height=842.0,
    )

    markdown = blocks[0].markdown_text

    assert r"\text{其中" not in markdown
    assert "表示电子" in markdown


def test_direct_typst_adjacent_inline_math_boundaries_do_not_cross_text() -> None:
    from services.rendering.layout.inline_content.core.markdown import build_direct_typst_passthrough_text
    from services.rendering.layout.inline_content.core.inline_math import MATH_BLOCK_RE

    text = (
        r"根据Stewart的高斯展开，$^{70}$$ \phi_{\kappa} $指的是收缩型高斯原子轨道，"
        r"用于近似指数为$ \zeta_{\kappa} $的球面斯莱特型轨道。"
    )

    markdown = build_direct_typst_passthrough_text(text)

    assert "$^{70}$" in markdown
    assert r"$\phi_{\kappa}$" in markdown
    assert r"$\zeta_{\kappa}$" in markdown
    assert "指的是收缩型高斯原子轨道" in markdown
    assert r"\$phi" not in markdown
    assert not any("指的是收缩型高斯原子轨道" in match.group(0) for match in MATH_BLOCK_RE.finditer(markdown))


def test_formula_safety_insets_reserve_more_bottom_space_for_subscripts() -> None:
    insets = formula_safety_insets_pt(
        "文字 $x_i$",
        [],
        font_size_pt=10.0,
        box_height_pt=20.0,
    )

    assert insets.bottom_pt > insets.top_pt
    assert insets.bottom_pt >= 1.0


def test_typst_block_adds_formula_safety_padding_without_shrinking_outer_fill() -> None:
    block = RenderBlock(
        block_id="b1",
        bbox=[10.0, 20.0, 180.0, 42.0],
        cover_bbox=[10.0, 20.0, 180.0, 42.0],
        inner_bbox=[10.0, 20.0, 180.0, 42.0],
        markdown_text="这是一段文字 $x_i$",
        plain_text="这是一段文字 xi",
        render_kind="markdown",
        font_size_pt=10.0,
        leading_em=0.55,
        fit_to_box=True,
        fit_min_font_size_pt=8.0,
        fit_min_leading_em=0.45,
        fit_max_height_pt=22.0,
        math_map=[],
        use_cover_fill=True,
    )

    typst = build_typst_block("formula_safety", block, include_fill=True)

    assert "height: 22.0pt" in typst
    assert "fill:" in typst
    assert "pad(top:" in typst
    assert "bottom:" in typst
    assert "fit_height: 22.0pt" not in typst


def test_toc_entries_render_with_typst_style_rows() -> None:
    blocks = build_render_blocks(
        [
            {
                "item_id": "p010-b001",
                "page_idx": 9,
                "block_type": "text",
                "block_kind": "text",
                "layout_role": "toc",
                "semantic_role": "table_of_contents",
                "structure_role": "table_of_contents",
                "normalized_sub_type": "table_of_contents",
                "bbox": [100.0, 200.0, 780.0, 260.0],
                "text_flow": "preserve_lines",
                "source_text": "1 Introduction ..... 1\n2 Foundations of Density Functional Theory ..... 11",
                "protected_translated_text": "1 引言 ..... 1\n2 密度泛函理论基础 ..... 11",
                "source_line_texts": [
                    "1 Introduction ..... 1",
                    "2 Foundations of Density Functional Theory ..... 11",
                ],
                "lines": [
                    {"bbox": [100.0, 200.0, 780.0, 230.0], "spans": [{"content": "1 Introduction ..... 1"}]},
                    {"bbox": [100.0, 230.0, 780.0, 260.0], "spans": [{"content": "2 Foundations of Density Functional Theory ..... 11"}]},
                ],
                "toc_entries": [
                    {
                        "number": "1",
                        "title": "Introduction",
                        "page_label": "1",
                        "level": 1,
                        "line_index": 0,
                        "bbox": [200.0, 400.0, 1560.0, 460.0],
                    },
                    {
                        "number": "2",
                        "title": "Foundations of Density Functional Theory",
                        "page_label": "11",
                        "level": 1,
                        "line_index": 1,
                        "bbox": [200.0, 460.0, 1560.0, 520.0],
                    },
                ],
            }
        ],
        page_width=595.0,
        page_height=842.0,
    )

    typst = build_typst_block("rp9_item_p010_b001_0", blocks[0])

    assert "layout(size =>" in typst
    assert "measure(title-body)" in typst
    assert '"1 引言"' in typst
    assert '"2 密度泛函理论基础"' in typst
    assert "dash: (1pt, 2pt)" in typst
    assert '_toc_0_page = "1"' in typst
    assert '_toc_1_page = "11"' in typst
    assert "size.width - page-size.width" in typst
    assert "dy: 230.0pt" in typst
    assert "dx: 200.0pt" not in typst


def test_toc_line_fallback_uses_model_lines_without_content_rules() -> None:
    blocks = build_render_blocks(
        [
            {
                "item_id": "p005-b002",
                "page_idx": 4,
                "block_type": "text",
                "block_kind": "text",
                "layout_role": "toc",
                "semantic_role": "table_of_contents",
                "structure_role": "table_of_contents",
                "normalized_sub_type": "table_of_contents",
                "bbox": [75.5, 138.494, 384.0, 173.233],
                "text_flow": "preserve_lines",
                "source_text": "opaque source line A\nopaque source line B",
                "protected_translated_text": (
                    "图1.1 球极坐标下的类氢原子 22\n"
                    "表8.4 2-丁酮构象热力学性质 279"
                ),
                "source_line_texts": [
                    "opaque source line A",
                    "opaque source line B",
                ],
                "lines": [
                    {"bbox": [75.5, 138.494, 384.0, 155.864], "spans": [{"content": ""}]},
                    {"bbox": [75.5, 155.864, 384.0, 173.233], "spans": [{"content": ""}]},
                ],
                "toc_entries": [],
            }
        ],
        page_width=540.0,
        page_height=665.972,
    )

    block = blocks[0]
    typst = build_typst_block("rp4_item_p005_b002_0", block)

    assert block.toc_entries
    assert '_toc_0_page = "22"' in typst
    assert '_toc_1_page = "279"' in typst
    assert '"图1.1 球极坐标下的类氢原子"' in typst
    assert '"表8.4 2-丁酮构象热力学性质"' in typst
    assert "dash: (1pt, 2pt)" in typst
    assert "pdftr_fit_single_line_markdown" not in typst


def test_toc_entries_normalize_spaced_inline_math() -> None:
    blocks = build_render_blocks(
        [
            {
                "item_id": "p010-b001",
                "page_idx": 9,
                "block_type": "text",
                "block_kind": "text",
                "layout_role": "toc",
                "semantic_role": "table_of_contents",
                "structure_role": "table_of_contents",
                "normalized_sub_type": "table_of_contents",
                "bbox": [100.0, 200.0, 780.0, 230.0],
                "text_flow": "preserve_lines",
                "source_text": "4.2 Exact Representations of $ E_{xc}[n] $ ..... 115",
                "protected_translated_text": "4.2 $ E_{xc}[n] $ 的精确表示 ..... 115",
                "source_line_texts": ["4.2 Exact Representations of $ E_{xc}[n] $ ..... 115"],
                "lines": [
                    {
                        "bbox": [100.0, 200.0, 780.0, 230.0],
                        "spans": [{"content": "4.2 Exact Representations of $ E_{xc}[n] $ ..... 115"}],
                    },
                ],
                "toc_entries": [
                    {
                        "number": "4.2",
                        "title": "Exact Representations of $ E_{xc}[n] $",
                        "page_label": "115",
                        "level": 2,
                        "line_index": 0,
                        "bbox": [200.0, 400.0, 1560.0, 460.0],
                    },
                ],
            }
        ],
        page_width=595.0,
        page_height=842.0,
    )

    typst = build_typst_block("rp9_item_p010_b001_0", blocks[0])

    assert '"4.2 $E_{xc}[n]$ 的精确表示"' in typst
    assert '"4.2 $ E_{xc}[n] $ 的精确表示"' not in typst
