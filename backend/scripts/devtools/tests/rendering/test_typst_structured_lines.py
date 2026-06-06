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

def test_regular_structured_lines_preserve_source_line_structure() -> None:
    item = {
        "item_id": "p014-b001",
        "block_type": "text",
        "block_kind": "text",
        "normalized_sub_type": "body",
        "bbox": [48.989, 221.367, 351.92, 594.643],
        "source_text": (
            "ALDA adiabatic local density approximation AF antiferromagnetic ASA atomic sphere approximation "
            "B86 Becke 86 GGA for exchange energy B88 Becke 88 GGA for exchange energy B3LYP hybrid "
            "constructed on basis of Becke-Lee-Yang-Parr GGA BLYP Becke-Lee-Yang-Parr GGA bcc "
            "body-centered cubic BO Born-Oppenheimer C Coulomb CDFT current density functional theory "
            "CS Colle-Salvetti CSDFT current spin density functional theory DC Dirac-Coulomb DCB "
            "Dirac-Coulomb-Breit DFT density functional theory DIR direct matrix element EA electron "
            "affinity ext external EXX exact exchange fcc face-centered cubic FP full potential GE "
            "gradient expansion GGA generalized gradient approximation GKS generalized Kohn-Sham GK "
            "Gross-Kohn H Hartree HDL high-density limit HEG homogeneous electron gas HF Hartree-Fock "
            "HK Hohenberg-Kohn"
        ),
        "lines": [
            {"bbox": [48.989, 221.367, 351.92, 240.031], "spans": [{"content": "ALDA adiabatic local density approximation"}]},
            {"bbox": [48.989, 240.031, 351.92, 258.695], "spans": [{"content": "AF antiferromagnetic ASA atomic sphere"}]},
            {"bbox": [48.989, 258.695, 351.92, 277.358], "spans": [{"content": "approximation B86 Becke 86 GGA for"}]},
            {"bbox": [48.989, 277.358, 351.92, 296.022], "spans": [{"content": "exchange energy B88 Becke 88 GGA for"}]},
            {"bbox": [48.989, 296.022, 351.92, 314.686], "spans": [{"content": "exchange energy B3LYP hybrid constructed"}]},
            {"bbox": [48.989, 314.686, 351.92, 333.35], "spans": [{"content": "on basis of Becke-Lee-Yang-Parr GGA"}]},
            {"bbox": [48.989, 333.35, 351.92, 352.014], "spans": [{"content": "BLYP Becke-Lee-Yang-Parr GGA bcc body-centered"}]},
            {"bbox": [48.989, 352.014, 351.92, 370.677], "spans": [{"content": "cubic BO Born-Oppenheimer C Coulomb"}]},
        ],
    }
    translated = (
        "ALDA 绝热局域密度近似 AF 反铁磁 ASA 原子球近似 B86 Becke 86 交换能GGA "
        "B88 Becke 88 交换能GGA B3LYP 基于Becke-Lee-Yang-Parr GGA的混合泛函 "
        "BLYP Becke-Lee-Yang-Parr GGA bcc 体心立方 BO Born-Oppenheimer C 库仑 "
        "CDFT 流密度泛函理论 CS Colle-Salvetti CSDFT 流自旋密度泛函理论"
    )

    structured = maybe_preserve_structured_line_breaks(item, translated)

    assert item["_render_preserve_line_breaks"] is True
    assert item["_render_line_structure"] == "structured_lines"
    assert structured.count("\n") == len(item["lines"]) - 1
    assert "ALDA 绝热局域密度近似" in structured.splitlines()[0]
    assert "CSDFT" in structured.splitlines()[-1]


def test_structured_line_render_block_keeps_hard_line_breaks() -> None:
    blocks = build_render_blocks(
        [
            {
                "item_id": "p014-b001",
                "page_idx": 13,
                "block_type": "text",
                "block_kind": "text",
                "normalized_sub_type": "body",
                "bbox": [48.989, 221.367, 351.92, 594.643],
                "source_text": (
                    "ALDA adiabatic local density approximation AF antiferromagnetic ASA atomic sphere approximation "
                    "B86 Becke 86 GGA for exchange energy B88 Becke 88 GGA for exchange energy B3LYP hybrid "
                    "constructed on basis of Becke-Lee-Yang-Parr GGA BLYP Becke-Lee-Yang-Parr GGA bcc "
                    "body-centered cubic BO Born-Oppenheimer C Coulomb CDFT current density functional theory "
                    "CS Colle-Salvetti CSDFT current spin density functional theory"
                ),
                "protected_source_text": (
                    "ALDA adiabatic local density approximation AF antiferromagnetic ASA atomic sphere approximation "
                    "B86 Becke 86 GGA for exchange energy B88 Becke 88 GGA for exchange energy B3LYP hybrid "
                    "constructed on basis of Becke-Lee-Yang-Parr GGA BLYP Becke-Lee-Yang-Parr GGA bcc "
                    "body-centered cubic BO Born-Oppenheimer C Coulomb CDFT current density functional theory "
                    "CS Colle-Salvetti CSDFT current spin density functional theory"
                ),
                "protected_translated_text": (
                    "ALDA 绝热局域密度近似 AF 反铁磁 ASA 原子球近似 B86 Becke 86 交换能GGA "
                    "B88 Becke 88 交换能GGA B3LYP 基于Becke-Lee-Yang-Parr GGA的混合泛函 "
                    "BLYP Becke-Lee-Yang-Parr GGA bcc 体心立方 BO Born-Oppenheimer C 库仑 "
                    "CDFT 流密度泛函理论 CS Colle-Salvetti CSDFT 流自旋密度泛函理论"
                ),
                "lines": [
                    {"bbox": [48.989, 221.367, 351.92, 240.031], "spans": [{"content": "ALDA adiabatic local density approximation"}]},
                    {"bbox": [48.989, 240.031, 351.92, 258.695], "spans": [{"content": "AF antiferromagnetic ASA atomic sphere"}]},
                    {"bbox": [48.989, 258.695, 351.92, 277.358], "spans": [{"content": "approximation B86 Becke 86 GGA for"}]},
                    {"bbox": [48.989, 277.358, 351.92, 296.022], "spans": [{"content": "exchange energy B88 Becke 88 GGA for"}]},
                    {"bbox": [48.989, 296.022, 351.92, 314.686], "spans": [{"content": "exchange energy B3LYP hybrid constructed"}]},
                    {"bbox": [48.989, 314.686, 351.92, 333.35], "spans": [{"content": "on basis of Becke-Lee-Yang-Parr GGA"}]},
                ],
            }
        ],
        page_width=595.0,
        page_height=842.0,
    )

    assert len(blocks) == 1
    assert "\n" in blocks[0].markdown_text
    assert blocks[0].fit_to_box is False
    assert blocks[0].preserved_line_boxes


def test_structured_line_typst_uses_source_line_boxes() -> None:
    blocks = build_render_blocks(
        [
            {
                "item_id": "p014-b001",
                "page_idx": 13,
                "block_type": "text",
                "block_kind": "text",
                "normalized_sub_type": "body",
                "bbox": [48.989, 221.367, 351.92, 594.643],
                "text_flow": "preserve_lines",
                "source_text": "ALDA adiabatic local density approximation\nAF antiferromagnetic\nASA atomic sphere approximation",
                "protected_source_text": "ALDA adiabatic local density approximation\nAF antiferromagnetic\nASA atomic sphere approximation",
                "protected_translated_text": "ALDA 绝热局域密度近似\nAF 反铁磁性\nASA 原子球近似",
                "lines": [
                    {"bbox": [48.989, 221.367, 351.92, 233.408], "spans": [{"content": "ALDA adiabatic local density approximation"}]},
                    {"bbox": [48.989, 233.408, 351.92, 245.449], "spans": [{"content": "AF antiferromagnetic"}]},
                    {"bbox": [48.989, 245.449, 351.92, 257.49], "spans": [{"content": "ASA atomic sphere approximation"}]},
                ],
            }
        ],
        page_width=595.0,
        page_height=842.0,
    )

    typst = build_typst_block("rp13_item_p014_b001_1", blocks[0])

    assert "stack(dir: ttb" not in typst
    assert "rp13_item_p014_b001_1_line_0_md" in typst
    assert "dy: 221.367pt" in typst
    assert "dy: 233.408pt" in typst
    assert "dy: 245.449pt" in typst


