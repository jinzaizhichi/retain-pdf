from __future__ import annotations

from typing import Iterable

import fitz

from services.rendering.source.rects import rect_area
from services.rendering.source.rects import rects_should_merge


ACTIVE_VERTICAL_MARGIN_PT = 8.0


def merge_rects(rects: Iterable[fitz.Rect]) -> list[fitz.Rect]:
    rect_list = list(rects)
    if len(rect_list) <= 1:
        return [fitz.Rect(rect) for rect in rect_list]

    active: list[fitz.Rect] = []
    merged: list[fitz.Rect] = []
    for rect in sorted(rect_list, key=lambda value: (round(value.y0, 2), round(value.x0, 2), round(value.y1, 2))):
        current_y0 = float(rect.y0)
        still_active: list[fitz.Rect] = []
        for existing in active:
            if existing.y1 < current_y0 - ACTIVE_VERTICAL_MARGIN_PT:
                merged.append(existing)
            else:
                still_active.append(existing)
        active = _merge_into_active(fitz.Rect(rect), still_active)

    merged.extend(active)
    return sorted(merged, key=lambda value: (round(value.y0, 2), round(value.x0, 2), round(value.y1, 2)))


def _merge_into_active(current: fitz.Rect, active: list[fitz.Rect]) -> list[fitz.Rect]:
    changed = True
    while changed:
        changed = False
        kept: list[fitz.Rect] = []
        for existing in active:
            if rects_should_merge(existing, current):
                current |= existing
                changed = True
            else:
                kept.append(existing)
        active = kept
    active.append(current)
    return active
