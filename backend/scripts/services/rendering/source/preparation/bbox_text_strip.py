from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import time

import fitz
import pikepdf
from pikepdf import Name

from services.rendering.source.cleanup.ops import merge_rects
from services.translation.item_reader import item_block_kind


TEXT_SHOW_OPERATORS = {"Tj", "TJ", "'", '"'}
DEFAULT_TEXT_ADVANCE_PT = 18.0
MIN_TEXT_BOX_HEIGHT_PT = 2.0
BBOX_TEXT_STRIP_CONTENT_STREAM_SIZE_THRESHOLD = 1_000_000


@dataclass(frozen=True)
class BBoxTextStripResult:
    changed: bool
    output_pdf_path: Path | None = None
    pages_changed: int = 0
    text_show_ops_removed: int = 0
    pages_skipped_complex: int = 0
    pages_skipped_no_text_overlap: int = 0
    forms_changed: int = 0


def _mul(left: tuple[float, float, float, float, float, float], right: tuple[float, float, float, float, float, float]) -> tuple[float, float, float, float, float, float]:
    a, b, c, d, e, f = left
    g, h, i, j, k, l = right
    return (
        a * g + c * h,
        b * g + d * h,
        a * i + c * j,
        b * i + d * j,
        a * k + c * l + e,
        b * k + d * l + f,
    )


def _point(matrix: tuple[float, float, float, float, float, float]) -> tuple[float, float]:
    return matrix[4], matrix[5]


def _inside_any_rect(x: float, y: float, rects: list[fitz.Rect]) -> bool:
    probe = fitz.Point(x, y)
    return any(rect.contains(probe) for rect in rects)


def _intersects_any_rect(rect: fitz.Rect, rects: list[fitz.Rect]) -> bool:
    return any(not (rect & target).is_empty for target in rects)


def _to_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _matrix_from_operands(operands: object) -> tuple[float, float, float, float, float, float] | None:
    if len(operands) < 6:
        return None
    return tuple(_to_float(operands[index]) for index in range(6))  # type: ignore[return-value]


def _matrix_from_object(value: object) -> tuple[float, float, float, float, float, float]:
    try:
        if len(value) >= 6:
            return tuple(_to_float(value[index]) for index in range(6))  # type: ignore[return-value]
    except Exception:
        pass
    return (1, 0, 0, 1, 0, 0)


def _text_operand_length(operands: object) -> int:
    if not operands:
        return 0
    value = operands[-1] if len(operands) > 1 else operands[0]
    if isinstance(value, (str, bytes, pikepdf.String)):
        return len(str(value))
    if isinstance(value, pikepdf.Array):
        return sum(len(str(item)) for item in value if isinstance(item, (str, bytes, pikepdf.String)))
    return 1


def _estimated_text_rect(
    matrix: tuple[float, float, float, float, float, float],
    *,
    text_length: int,
) -> fitz.Rect:
    x, y = _point(matrix)
    font_height = max(abs(matrix[3]), abs(matrix[1]), MIN_TEXT_BOX_HEIGHT_PT)
    char_width = max(abs(matrix[0]) * 0.5, 1.0)
    width = max(char_width, min(DEFAULT_TEXT_ADVANCE_PT, char_width * max(text_length, 1)))
    return fitz.Rect(x, y - font_height * 0.35, x + width, y + font_height * 1.05)


def _page_text_rects(
    *,
    page_height: float,
    translated_items: list[dict],
) -> list[fitz.Rect]:
    rects: list[fitz.Rect] = []
    for item in translated_items:
        if not _should_strip_item_text(item):
            continue
        bbox = item.get("bbox", [])
        if len(bbox) != 4:
            continue
        x0, y0, x1, y1 = (_to_float(value) for value in bbox)
        rect = fitz.Rect(x0, page_height - y1, x1, page_height - y0)
        if rect.is_empty:
            continue
        rects.append(rect + (-1.0, -1.0, 1.0, 1.0))
    return merge_rects(rects)


def _page_item_rects(translated_items: list[dict]) -> list[fitz.Rect]:
    rects: list[fitz.Rect] = []
    for item in translated_items:
        if not _should_strip_item_text(item):
            continue
        bbox = item.get("bbox", [])
        if len(bbox) != 4:
            continue
        rect = fitz.Rect(_to_float(bbox[0]), _to_float(bbox[1]), _to_float(bbox[2]), _to_float(bbox[3]))
        if not rect.is_empty:
            rects.append(rect)
    return merge_rects(rects)


def _item_render_text(item: dict) -> str:
    return str(
        item.get("protected_translated_text")
        or item.get("translated_text")
        or item.get("render_text")
        or ""
    ).strip()


def _should_strip_item_text(item: dict) -> bool:
    return item_block_kind(item) == "text" and bool(_item_render_text(item))


def _page_bboxlog_stats(
    page: fitz.Page,
    target_rects: list[fitz.Rect],
) -> tuple[int, int]:
    try:
        bboxlog = page.get_bboxlog()
    except Exception:
        return 0, 0
    nontext_count = 0
    text_overlap_count = 0
    for entry in bboxlog:
        kind = str(entry[0])
        if "text" not in kind:
            nontext_count += 1
            continue
        if len(entry) < 2:
            continue
        try:
            text_rect = fitz.Rect(entry[1])
        except Exception:
            continue
        if any(not (text_rect & target_rect).is_empty for target_rect in target_rects):
            text_overlap_count += 1
    return nontext_count, text_overlap_count


def _page_content_stream_size(doc: fitz.Document, page: fitz.Page) -> int:
    try:
        content_xrefs = page.get_contents() or []
    except Exception:
        return 0
    total = 0
    for xref in content_xrefs:
        try:
            total += len(doc.xref_stream(xref) or b"")
        except Exception:
            continue
        if total >= BBOX_TEXT_STRIP_CONTENT_STREAM_SIZE_THRESHOLD:
            return total
    return total


def _xobject_dict(container: pikepdf.Page | pikepdf.Object) -> object | None:
    try:
        resources = container.obj.get(Name("/Resources")) if isinstance(container, pikepdf.Page) else container.get(Name("/Resources"))
        if resources is None:
            return None
        return resources.get(Name("/XObject"))
    except Exception:
        return None


def _strip_bbox_text_from_stream(
    stream_obj: pikepdf.Page | pikepdf.Object,
    rects: list[fitz.Rect],
    *,
    initial_ctm: tuple[float, float, float, float, float, float] = (1, 0, 0, 1, 0, 0),
    visited_forms: set[tuple[int, int]] | None = None,
) -> tuple[bytes | None, int, int]:
    instructions = list(pikepdf.parse_content_stream(stream_obj))
    if not instructions or not rects:
        return None, 0, 0

    output: list[tuple] = []
    removed = 0
    forms_changed = 0
    ctm: tuple[float, float, float, float, float, float] = initial_ctm
    ctm_stack: list[tuple[float, float, float, float, float, float]] = []
    text_matrix: tuple[float, float, float, float, float, float] = (1, 0, 0, 1, 0, 0)
    line_matrix: tuple[float, float, float, float, float, float] = (1, 0, 0, 1, 0, 0)
    leading = 0.0

    xobjects = _xobject_dict(stream_obj)

    def move_text(tx: float, ty: float) -> None:
        nonlocal text_matrix, line_matrix
        move = (1, 0, 0, 1, tx, ty)
        line_matrix = _mul(line_matrix, move)
        text_matrix = line_matrix

    def advance_text(operands: object) -> None:
        nonlocal text_matrix
        text_length = _text_operand_length(operands)
        font_size = max(abs(text_matrix[0]), 1.0)
        tx = min(DEFAULT_TEXT_ADVANCE_PT, max(1.0, text_length * font_size * 0.5))
        text_matrix = _mul(text_matrix, (1, 0, 0, 1, tx / font_size, 0))

    for operands, operator in instructions:
        op = str(operator)
        if op == "q":
            ctm_stack.append(ctm)
            output.append((operands, operator))
            continue
        if op == "Q":
            ctm = ctm_stack.pop() if ctm_stack else (1, 0, 0, 1, 0, 0)
            output.append((operands, operator))
            continue
        if op == "cm":
            matrix = _matrix_from_operands(operands)
            if matrix is not None:
                ctm = _mul(ctm, matrix)
            output.append((operands, operator))
            continue
        if op == "Do" and operands:
            xobject_name = operands[0]
            xobject = None
            if xobjects is not None:
                try:
                    xobject = xobjects.get(xobject_name)
                except Exception:
                    xobject = None
            if xobject is not None and str(xobject.get(Name("/Subtype"))) == "/Form":
                objgen = getattr(xobject, "objgen", None)
                form_key = tuple(objgen) if objgen is not None else (id(xobject), 0)
                if visited_forms is None:
                    visited_forms = set()
                if form_key not in visited_forms:
                    visited_forms.add(form_key)
                    form_matrix = _matrix_from_object(xobject.get(Name("/Matrix"), []))
                    form_content, form_removed, nested_forms_changed = _strip_bbox_text_from_stream(
                        xobject,
                        rects,
                        initial_ctm=_mul(ctm, form_matrix),
                        visited_forms=visited_forms,
                    )
                    if form_content and form_removed > 0:
                        xobject.write(form_content)
                        forms_changed += 1
                        removed += form_removed
                    forms_changed += nested_forms_changed
                    visited_forms.remove(form_key)
            output.append((operands, operator))
            continue
        if op == "BT":
            text_matrix = (1, 0, 0, 1, 0, 0)
            line_matrix = text_matrix
            output.append((operands, operator))
            continue
        if op == "Tm":
            matrix = _matrix_from_operands(operands)
            if matrix is not None:
                text_matrix = matrix
                line_matrix = matrix
            output.append((operands, operator))
            continue
        if op in {"Td", "TD"} and len(operands) >= 2:
            tx = _to_float(operands[0])
            ty = _to_float(operands[1])
            if op == "TD":
                leading = -ty
            move_text(tx, ty)
            output.append((operands, operator))
            continue
        if op == "TL" and operands:
            leading = _to_float(operands[0])
            output.append((operands, operator))
            continue
        if op == "T*":
            move_text(0, -leading)
            output.append((operands, operator))
            continue
        if op in {"'", '"'}:
            move_text(0, -leading)

        if op in TEXT_SHOW_OPERATORS:
            user_matrix = _mul(ctm, text_matrix)
            user_point = _point(user_matrix)
            text_rect = _estimated_text_rect(user_matrix, text_length=_text_operand_length(operands))
            should_remove = _inside_any_rect(user_point[0], user_point[1], rects) or _intersects_any_rect(text_rect, rects)
            advance_text(operands)
            if should_remove:
                removed += 1
                continue

        output.append((operands, operator))

    if removed <= 0:
        return None, 0, forms_changed
    return pikepdf.unparse_content_stream(output), removed, forms_changed


def _strip_bbox_text_from_page(page: pikepdf.Page, rects: list[fitz.Rect]) -> tuple[bytes | None, int, int]:
    return _strip_bbox_text_from_stream(page, rects)


def build_bbox_text_stripped_pdf_copy(
    *,
    source_pdf_path: Path,
    output_pdf_path: Path,
    translated_pages: dict[int, list[dict]],
) -> BBoxTextStripResult:
    if not translated_pages:
        return BBoxTextStripResult(changed=False)

    candidate_started = time.perf_counter()
    page_rects: dict[int, list[fitz.Rect]] = {}
    skipped_complex = 0
    skipped_no_text_overlap = 0
    doc = fitz.open(source_pdf_path)
    try:
        for page_idx, items in translated_pages.items():
            if page_idx < 0 or page_idx >= len(doc):
                continue
            page = doc[page_idx]
            item_rects = _page_item_rects(items)
            if not item_rects:
                continue
            if _page_content_stream_size(doc, page) >= BBOX_TEXT_STRIP_CONTENT_STREAM_SIZE_THRESHOLD:
                skipped_complex += 1
                continue
            _drawing_count, text_overlap_count = _page_bboxlog_stats(page, item_rects)
            if text_overlap_count <= 0:
                skipped_no_text_overlap += 1
                continue
            rects = _page_text_rects(page_height=page.rect.height, translated_items=items)
            if rects:
                page_rects[page_idx] = rects
    finally:
        doc.close()
    candidate_elapsed = time.perf_counter() - candidate_started

    if not page_rects:
        return BBoxTextStripResult(
            changed=False,
            pages_skipped_complex=skipped_complex,
            pages_skipped_no_text_overlap=skipped_no_text_overlap,
        )

    output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    copy_started = time.perf_counter()
    shutil.copy2(source_pdf_path, output_pdf_path)
    copy_elapsed = time.perf_counter() - copy_started

    pages_changed = 0
    removed_total = 0
    forms_changed_total = 0
    parse_elapsed = 0.0
    save_elapsed = 0.0
    with pikepdf.Pdf.open(output_pdf_path, allow_overwriting_input=True) as pdf:
        for page_idx, rects in page_rects.items():
            parse_started = time.perf_counter()
            content_stream, removed, forms_changed = _strip_bbox_text_from_page(pdf.pages[page_idx], rects)
            parse_elapsed += time.perf_counter() - parse_started
            forms_changed_total += forms_changed
            if not content_stream or removed <= 0:
                if forms_changed > 0:
                    pages_changed += 1
                    removed_total += removed
                continue
            pdf.pages[page_idx].obj[Name("/Contents")] = pdf.make_stream(content_stream)
            pages_changed += 1
            removed_total += removed

        if pages_changed <= 0:
            output_pdf_path.unlink(missing_ok=True)
            return BBoxTextStripResult(
                changed=False,
                pages_skipped_complex=skipped_complex,
                pages_skipped_no_text_overlap=skipped_no_text_overlap,
            )

        save_started = time.perf_counter()
        pdf.save(
            output_pdf_path,
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
            compress_streams=True,
            recompress_flate=False,
        )
        save_elapsed = time.perf_counter() - save_started

    print(
        f"bbox text strip: pages={pages_changed} text_show_ops={removed_total} "
        f"forms={forms_changed_total} skipped_complex_pages={skipped_complex} "
        f"skipped_no_text_overlap_pages={skipped_no_text_overlap} "
        f"copy={copy_elapsed:.2f}s candidates={candidate_elapsed:.2f}s parse={parse_elapsed:.2f}s save={save_elapsed:.2f}s "
        f"output={output_pdf_path}",
        flush=True,
    )
    return BBoxTextStripResult(
        changed=True,
        output_pdf_path=output_pdf_path,
        pages_changed=pages_changed,
        text_show_ops_removed=removed_total,
        pages_skipped_complex=skipped_complex,
        pages_skipped_no_text_overlap=skipped_no_text_overlap,
        forms_changed=forms_changed_total,
    )
