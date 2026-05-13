from __future__ import annotations

from services.rendering.layout.payload.metrics import estimated_render_height_pt
from services.rendering.layout.payload.metrics import VERTICAL_COLLISION_GAP_PT
from services.rendering.layout.payload.fit_vertical import fit_block_to_vertical_limit


VERTICAL_COLLISION_MIN_WIDTH_OVERLAP_RATIO = 0.6
VERTICAL_COLLISION_SOURCE_GAP_TRIGGER_PT = 3.0
VERTICAL_COLLISION_TRIGGER_RATIO = 0.9
VERTICAL_COLLISION_SAFETY_PAD_PT = 2.2
VERTICAL_COLLISION_TIGHT_SOURCE_GAP_PT = 0.8
VERTICAL_COLLISION_FORMULA_SAFETY_PAD_PT = 6.8


def _collision_safety_pad_pt(payload: dict, source_gap: float) -> float:
    safety_pad = VERTICAL_COLLISION_SAFETY_PAD_PT
    if source_gap <= VERTICAL_COLLISION_TIGHT_SOURCE_GAP_PT:
        safety_pad = max(safety_pad, 3.4)
    if payload.get("formula_map") or "$" in str(payload.get("translated_text", "") or ""):
        safety_pad = max(safety_pad, VERTICAL_COLLISION_FORMULA_SAFETY_PAD_PT)
    return safety_pad


def mark_adjacent_collision_risk(ordered_payloads: list[dict]) -> None:
    for current, nxt in zip(ordered_payloads, ordered_payloads[1:]):
        current_left, current_top, current_right, current_bottom = current["inner_bbox"]
        next_left, next_top, next_right, _ = nxt["inner_bbox"]
        overlap_width = max(0.0, min(current_right, next_right) - max(current_left, next_left))
        min_width = max(1.0, min(current_right - current_left, next_right - next_left))
        if overlap_width / min_width < VERTICAL_COLLISION_MIN_WIDTH_OVERLAP_RATIO:
            continue

        source_gap = next_top - current_bottom
        if source_gap > VERTICAL_COLLISION_SOURCE_GAP_TRIGGER_PT:
            continue

        max_height_pt = next_top - current_top - VERTICAL_COLLISION_GAP_PT - _collision_safety_pad_pt(current, source_gap)
        if max_height_pt <= 0:
            continue

        estimated_height = estimated_render_height_pt(
            current["inner_bbox"],
            current["translated_text"],
            current["formula_map"],
            current["font_size_pt"],
            current["leading_em"],
        )
        if estimated_height <= max_height_pt * VERTICAL_COLLISION_TRIGGER_RATIO:
            continue

        current["adjacent_collision_risk"] = True
        fitted_font_size, fitted_leading = fit_block_to_vertical_limit(
            {
                **current["item"],
                "_render_inner_bbox": current["inner_bbox"],
                "_is_body_text_candidate": current["is_body"],
                "_dense_small_box": current["dense_small_box"],
                "_heavy_dense_small_box": current["heavy_dense_small_box"],
            },
            current["translated_text"],
            current["formula_map"],
            current["font_size_pt"],
            current["leading_em"],
            max_height_pt,
            page_body_font_size_pt=current["page_body_font_size_pt"],
        )
        current["font_size_pt"] = fitted_font_size
        current["leading_em"] = fitted_leading
        current["prefer_typst_fit"] = True
        previous_limit = current.get("adjacent_available_height_pt")
        if previous_limit is None or max_height_pt < previous_limit:
            current["adjacent_available_height_pt"] = max(6.0, max_height_pt)
