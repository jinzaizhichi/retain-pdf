from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import fitz

from services.rendering.source.cleanup.analysis import page_drawing_count
from services.rendering.source.cleanup.analysis import page_has_large_background_image
from services.rendering.source.cleanup.analysis import page_is_vector_heavy_count
from services.rendering.source.cleanup.analysis import page_should_use_cover_only_count
from services.rendering.source.cleanup.plan import RedactionPlan
from services.rendering.source.cleanup.strategy import RedactionRoute
from services.rendering.source.cleanup.strategy import resolve_redaction_route


ResolvedRedactionExecution = Literal[
    "auto",
    "visual_cover",
    "visual_cover_and_remove_text",
    "image_page_redaction",
    "cover_only_count",
    "vector_heavy_redaction",
    "standard_redaction",
]


@dataclass(frozen=True)
class RedactionRouteDecision:
    execution: ResolvedRedactionExecution
    route: RedactionRoute
    image_page: bool
    drawing_count: int


def select_redaction_route(
    page: fitz.Page,
    *,
    fill_background: bool | None,
    cover_only: bool,
    strategy: str | None,
    plan: RedactionPlan | None,
) -> RedactionRouteDecision:
    route = resolve_redaction_route(strategy, cover_only=cover_only)

    if route == "auto":
        return RedactionRouteDecision(
            execution="auto",
            route=route,
            image_page=False,
            drawing_count=0,
        )
    elif route == "visual_cover":
        return RedactionRouteDecision(
            execution="visual_cover",
            route=route,
            image_page=False,
            drawing_count=0,
        )
    elif route == "visual_cover_and_remove_text":
        return RedactionRouteDecision(
            execution="visual_cover_and_remove_text",
            route=route,
            image_page=False,
            drawing_count=0,
        )

    image_page = plan.image_page if plan is not None else page_has_large_background_image(page)
    drawing_count = plan.drawing_count if plan is not None else page_drawing_count(page)

    if image_page:
        execution = "image_page_redaction"
    elif fill_background is None and page_should_use_cover_only_count(drawing_count):
        execution = "cover_only_count"
    elif fill_background is None and page_is_vector_heavy_count(drawing_count):
        execution = "vector_heavy_redaction"
    else:
        execution = "standard_redaction"

    return RedactionRouteDecision(
        execution=execution,
        route=route,
        image_page=image_page,
        drawing_count=drawing_count,
    )


__all__ = [
    "RedactionRouteDecision",
    "ResolvedRedactionExecution",
    "select_redaction_route",
]
