from __future__ import annotations

import fitz
import pikepdf

from services.rendering.source_cleanup.pdf.hit_test import RectIndex
from services.rendering.source_cleanup.pdf.pdf_math import IDENTITY_MATRIX
from services.rendering.source_cleanup.pdf.pdf_math import PdfMatrix
from services.rendering.source_cleanup.pdf.text_ops import TEXT_SHOW_OPERATORS
from services.rendering.source_cleanup.pdf.stream_state import ContentStreamState
from services.rendering.source_cleanup.pdf.text_removal import decide_text_show_rewrite
from services.rendering.source_cleanup.pdf.xobject_ops import rewrite_xobject_do
from services.rendering.source_cleanup.pdf.xobject_ops import xobject_dict


def strip_bbox_text_from_page(
    page: pikepdf.Page,
    rects: list[fitz.Rect],
    *,
    pdf: pikepdf.Pdf | None = None,
    protected_rects: list[fitz.Rect] | None = None,
    recurse_forms: bool = True,
) -> tuple[bytes | None, int, int]:
    return strip_bbox_text_from_stream(
        page,
        rects,
        pdf=pdf,
        protected_rects=protected_rects,
        recurse_forms=recurse_forms,
    )


def strip_bbox_text_from_stream(
    stream_obj: pikepdf.Page | pikepdf.Object,
    rects: list[fitz.Rect],
    *,
    pdf: pikepdf.Pdf | None = None,
    protected_rects: list[fitz.Rect] | None = None,
    recurse_forms: bool = True,
    initial_ctm: PdfMatrix = IDENTITY_MATRIX,
    visited_forms: set[tuple[int, int]] | None = None,
) -> tuple[bytes | None, int, int]:
    instructions = list(pikepdf.parse_content_stream(stream_obj))
    if not instructions or not rects:
        return None, 0, 0

    output: list[tuple] = []
    protected_rects = protected_rects or []
    strip_index = RectIndex.build(rects)
    protected_index = RectIndex.build(protected_rects)
    removed = 0
    forms_changed = 0
    state = ContentStreamState(ctm=initial_ctm)

    xobjects = xobject_dict(stream_obj)

    for operands, operator in instructions:
        op = str(operator)
        if state.apply_state_operator(op, operands):
            output.append((operands, operator))
            continue
        if op == "Do" and operands:
            xobject_result = rewrite_xobject_do(
                operands=operands,
                xobjects=xobjects,
                rects=rects,
                pdf=pdf,
                protected_rects=protected_rects,
                recurse_forms=recurse_forms,
                ctm=state.ctm,
                visited_forms=visited_forms,
                rewrite_stream=_rewrite_stream_for_form,
            )
            operands = xobject_result.operands
            removed += xobject_result.removed
            forms_changed += xobject_result.forms_changed
            output.append((operands, operator))
            continue
        if op in {"'", '"'}:
            state.prepare_quote_text_show(op, operands)

        if op in TEXT_SHOW_OPERATORS:
            text_decision = decide_text_show_rewrite(
                operands=operands,
                ctm=state.ctm,
                text_matrix=state.text_matrix,
                text_state=state.text_state,
                strip_index=strip_index,
                protected_index=protected_index,
            )
            state.advance_text(operands, text_metrics=text_decision.text_metrics)
            if text_decision.remove:
                removed += 1
                continue

        output.append((operands, operator))

    if removed <= 0:
        return None, 0, forms_changed
    return pikepdf.unparse_content_stream(output), removed, forms_changed


def _rewrite_stream_for_form(
    stream_obj: pikepdf.Object,
    rects: list[fitz.Rect],
    pdf: pikepdf.Pdf,
    protected_rects: list[fitz.Rect],
    recurse_forms: bool,
    initial_ctm: PdfMatrix,
    visited_forms: set[tuple[int, int]],
) -> tuple[bytes | None, int, int]:
    return strip_bbox_text_from_stream(
        stream_obj,
        rects,
        pdf=pdf,
        protected_rects=protected_rects,
        recurse_forms=recurse_forms,
        initial_ctm=initial_ctm,
        visited_forms=visited_forms,
    )
