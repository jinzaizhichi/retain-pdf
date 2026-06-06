from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
from typing import Iterable

import fitz


DrawingPredicate = Callable[[dict], bool]


@dataclass(frozen=True)
class DrawingClass:
    name: str
    blocks_text_strip: bool
    matches: DrawingPredicate


TEXT_STRIP_DRAWING_CLASSES: tuple[DrawingClass, ...] = (
    DrawingClass(
        name="stroked_path",
        blocks_text_strip=True,
        matches=lambda drawing: drawing_type(drawing) in {"s", "fs"},
    ),
    DrawingClass(
        name="stroke_only_path",
        blocks_text_strip=True,
        matches=lambda drawing: drawing.get("color") is not None and drawing.get("fill") is None,
    ),
)


def unsafe_text_strip_drawing_rects(page: fitz.Page) -> list[fitz.Rect]:
    return [
        rect
        for rect in (_drawing_rect(drawing) for drawing in iter_unsafe_text_strip_drawings(page))
        if rect is not None
    ]


def iter_unsafe_text_strip_drawings(page: fitz.Page) -> Iterable[dict]:
    return (
        drawing
        for drawing in page_drawings(page)
        if drawing_blocks_text_strip(drawing)
    )


def page_drawings(page: fitz.Page) -> list[dict]:
    try:
        return page.get_cdrawings() if hasattr(page, "get_cdrawings") else page.get_drawings()
    except Exception:
        return []


def drawing_blocks_text_strip(drawing: dict) -> bool:
    return any(drawing_class.blocks_text_strip for drawing_class in matching_drawing_classes(drawing))


def matching_drawing_classes(drawing: dict) -> tuple[DrawingClass, ...]:
    return tuple(drawing_class for drawing_class in TEXT_STRIP_DRAWING_CLASSES if drawing_class.matches(drawing))


def drawing_type(drawing: dict) -> str:
    return str(drawing.get("type") or "").strip().lower()


def _drawing_rect(drawing: dict) -> fitz.Rect | None:
    return _normalized_rect(drawing.get("rect"), drawing)


def _normalized_rect(value: object, drawing: dict) -> fitz.Rect | None:
    try:
        rect = fitz.Rect(value)
    except Exception:
        return None
    expanded = _expand_empty_rect(rect, drawing)
    return None if expanded.is_empty else expanded


def _expand_empty_rect(rect: fitz.Rect, drawing: dict) -> fitz.Rect:
    return _expand_thin_drawing_rect(rect, drawing) if rect.is_empty else rect


def _expand_thin_drawing_rect(rect: fitz.Rect, drawing: dict) -> fitz.Rect:
    stroke_width = _drawing_stroke_width(drawing)
    pad = max(stroke_width / 2.0, 0.5)
    expanded = fitz.Rect(rect)
    if expanded.x0 == expanded.x1:
        expanded.x0 -= pad
        expanded.x1 += pad
    if expanded.y0 == expanded.y1:
        expanded.y0 -= pad
        expanded.y1 += pad
    return expanded


def _drawing_stroke_width(drawing: dict) -> float:
    try:
        return float(drawing.get("width") or 1.0)
    except Exception:
        return 1.0
