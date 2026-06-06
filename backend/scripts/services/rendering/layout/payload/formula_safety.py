from __future__ import annotations

import re
from dataclasses import dataclass


INLINE_MATH_RE = re.compile(r"\$(?!\s)(?:\\.|[^$\n]){1,240}?\$")
FORMULA_PLACEHOLDER_RE = re.compile(r"<[futnvc]\d+-[0-9a-z]{3}/>|\[\[FORMULA_\d+]]")
SCRIPT_OR_TALL_MATH_RE = re.compile(
    r"[_^]|\\(?:frac|dfrac|tfrac|sqrt|sum|prod|int|iint|iiint|lim|underset|overset|substack)\b"
)
MIN_SAFE_CONTENT_HEIGHT_PT = 8.0
MAX_FORMULA_INSET_HEIGHT_RATIO = 0.18


@dataclass(frozen=True)
class FormulaSafetyInsets:
    top_pt: float = 0.0
    bottom_pt: float = 0.0

    @property
    def total_pt(self) -> float:
        return self.top_pt + self.bottom_pt

    @property
    def active(self) -> bool:
        return self.total_pt > 0.01


def formula_safety_insets_pt(
    text: str,
    formula_map: list[dict] | None,
    *,
    font_size_pt: float,
    box_height_pt: float,
) -> FormulaSafetyInsets:
    if font_size_pt <= 0 or box_height_pt <= MIN_SAFE_CONTENT_HEIGHT_PT:
        return FormulaSafetyInsets()
    formula_texts = formula_texts_for_render(text, formula_map)
    if not formula_texts:
        return FormulaSafetyInsets()
    has_deep_formula = any(formula_needs_extra_descent(formula) for formula in formula_texts)
    top_ratio = 0.07 if has_deep_formula else 0.045
    bottom_ratio = 0.18 if has_deep_formula else 0.11
    top = min(max(font_size_pt * top_ratio, 0.25), 1.15)
    bottom = min(max(font_size_pt * bottom_ratio, 0.55), 2.6)
    return _fit_insets_to_box(top, bottom, box_height_pt)


def formula_texts_for_render(text: str, formula_map: list[dict] | None) -> list[str]:
    formulas = [
        str(entry.get("formula_text") or entry.get("latex") or "").strip()
        for entry in formula_map or []
        if isinstance(entry, dict)
    ]
    formulas.extend(match.group(0).strip("$") for match in INLINE_MATH_RE.finditer(str(text or "")))
    if formulas:
        return [formula for formula in formulas if formula]
    return [match.group(0) for match in FORMULA_PLACEHOLDER_RE.finditer(str(text or ""))]


def formula_needs_extra_descent(formula_text: str) -> bool:
    return bool(SCRIPT_OR_TALL_MATH_RE.search(str(formula_text or "")))


def formula_safe_inner_bbox(
    inner_bbox: list[float],
    text: str,
    formula_map: list[dict] | None,
    *,
    font_size_pt: float,
) -> tuple[list[float], FormulaSafetyInsets]:
    if len(inner_bbox) != 4:
        return inner_bbox, FormulaSafetyInsets()
    x0, y0, x1, y1 = [float(value) for value in inner_bbox]
    height = max(0.0, y1 - y0)
    insets = formula_safety_insets_pt(
        text,
        formula_map,
        font_size_pt=font_size_pt,
        box_height_pt=height,
    )
    if not insets.active:
        return [x0, y0, x1, y1], insets
    return [x0, y0 + insets.top_pt, x1, y1 - insets.bottom_pt], insets


def _fit_insets_to_box(top: float, bottom: float, box_height_pt: float) -> FormulaSafetyInsets:
    available = max(0.0, box_height_pt - MIN_SAFE_CONTENT_HEIGHT_PT)
    cap = min(box_height_pt * MAX_FORMULA_INSET_HEIGHT_RATIO, available)
    total = top + bottom
    if cap <= 0 or total <= 0:
        return FormulaSafetyInsets()
    if total > cap:
        scale = cap / total
        top *= scale
        bottom *= scale
    return FormulaSafetyInsets(top_pt=round(top, 2), bottom_pt=round(bottom, 2))
