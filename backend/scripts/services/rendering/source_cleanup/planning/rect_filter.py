from __future__ import annotations

import fitz

from services.rendering.source.rects import rect_area
from services.rendering.source_cleanup.planning.drawing_classifier import unsafe_text_strip_drawing_rects


MIN_UNSAFE_VECTOR_OVERLAP_AREA_PT2 = 0.5


def keep_rects_without_unsafe_vector_overlap(page: fitz.Page, rects: list[fitz.Rect]) -> list[fitz.Rect]:
    unsafe_rects = unsafe_text_strip_drawing_rects(page)
    if not unsafe_rects:
        return rects
    return [rect for rect in rects if not rect_overlaps_any_unsafe_vector(rect, unsafe_rects)]


def has_unsafe_vector_overlap(page: fitz.Page, view_rect: fitz.Rect) -> bool:
    return rect_overlaps_any_unsafe_vector(view_rect, unsafe_text_strip_drawing_rects(page))


def rect_overlaps_any_unsafe_vector(rect: fitz.Rect, unsafe_rects: list[fitz.Rect]) -> bool:
    return any(rect_overlap_area(rect, unsafe_rect) > MIN_UNSAFE_VECTOR_OVERLAP_AREA_PT2 for unsafe_rect in unsafe_rects)


def rect_overlap_area(left: fitz.Rect, right: fitz.Rect) -> float:
    return rect_area(left & right)
