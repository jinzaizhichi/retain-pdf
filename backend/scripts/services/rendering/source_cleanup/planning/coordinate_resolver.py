from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import fitz

from services.rendering.source.rects import rect_area


BBoxTransform = Callable[[fitz.Page, fitz.Rect], fitz.Rect]


@dataclass(frozen=True)
class BBoxCoordinateCandidate:
    name: str
    transform: BBoxTransform


@dataclass(frozen=True)
class BBoxCoordinateScore:
    candidate: BBoxCoordinateCandidate
    rect: fitz.Rect
    text_overlap_count: int
    text_overlap_area: float


BBOX_COORDINATE_CANDIDATES: tuple[BBoxCoordinateCandidate, ...] = (
    BBoxCoordinateCandidate(
        name="pdf_matrix",
        transform=lambda page, rect: rect * ~page.transformation_matrix,
    ),
    BBoxCoordinateCandidate(
        name="raw_top_left",
        transform=lambda _page, rect: fitz.Rect(rect),
    ),
)


def resolve_bbox_rect(page: fitz.Page, bbox: object) -> fitz.Rect | None:
    raw_rect = raw_bbox_rect(bbox)
    if raw_rect is None:
        return None
    scores = tuple(score_bbox_candidate(page, candidate, raw_rect) for candidate in BBOX_COORDINATE_CANDIDATES)
    best = max(scores, key=lambda score: (score.text_overlap_count, score.text_overlap_area))
    return None if best.rect.is_empty else best.rect


def raw_bbox_rect(bbox: object) -> fitz.Rect | None:
    if not isinstance(bbox, list) or len(bbox) != 4:
        return None
    rect = fitz.Rect(*(to_float(value) for value in bbox))
    return None if rect.is_empty else rect


def score_bbox_candidate(
    page: fitz.Page,
    candidate: BBoxCoordinateCandidate,
    raw_rect: fitz.Rect,
) -> BBoxCoordinateScore:
    rect = candidate.transform(page, raw_rect)
    count, area = text_overlap_score(page, rect)
    return BBoxCoordinateScore(
        candidate=candidate,
        rect=rect,
        text_overlap_count=count,
        text_overlap_area=area,
    )


def text_overlap_score(page: fitz.Page, target_rect: fitz.Rect) -> tuple[int, float]:
    if target_rect.is_empty:
        return 0, 0.0
    count = 0
    area = 0.0
    for text_rect in page_text_rects(page):
        overlap = rect_area(text_rect & target_rect)
        if overlap <= 0.0:
            continue
        count += 1
        area += overlap
    return count, area


def page_text_rects(page: fitz.Page) -> tuple[fitz.Rect, ...]:
    try:
        bboxlog = page.get_bboxlog()
    except Exception:
        return ()
    rects: list[fitz.Rect] = []
    for entry in bboxlog:
        text_rect = bboxlog_text_rect(entry)
        if text_rect is not None:
            rects.append(text_rect)
    return tuple(rects)


def bboxlog_text_rect(entry: object) -> fitz.Rect | None:
    try:
        kind = str(entry[0])
        value = entry[1]
    except Exception:
        return None
    if "text" not in kind:
        return None
    try:
        rect = fitz.Rect(value)
    except Exception:
        return None
    return None if rect.is_empty else rect


def to_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default
