from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


ItemPredicate = Callable[[dict], bool]


SAFE_VECTOR_OVERLAP_ROLES = frozenset(
    {
        "heading",
        "title",
        "toc",
        "table_of_contents",
        "page_number",
    }
)


@dataclass(frozen=True)
class CleanupItemClass:
    name: str
    allows_vector_overlap: bool
    matches: ItemPredicate


def page_all_strip_items_allow_vector_overlap(items: list[dict]) -> bool:
    strip_text_items = tuple(item for item in items if item_is_text(item))
    return bool(strip_text_items) and all(item_allows_vector_overlap(item) for item in strip_text_items)


def item_allows_vector_overlap(item: dict) -> bool:
    item_class = first_cleanup_item_class(item)
    return item_class.allows_vector_overlap if item_class is not None else False


def first_cleanup_item_class(item: dict) -> CleanupItemClass | None:
    return next((item_class for item_class in CLEANUP_ITEM_CLASSES if item_class.matches(item)), None)


def item_is_text(item: dict) -> bool:
    return item_block_kind(item) == "text"


def item_block_kind(item: dict) -> str:
    return str(item.get("block_kind") or item.get("block_type") or "").strip().lower()


def item_role_values(item: dict) -> frozenset[str]:
    return frozenset(
        str(item.get(key) or "").strip().lower()
        for key in (
            "layout_role",
            "semantic_role",
            "structure_role",
            "normalized_sub_type",
        )
    )


CLEANUP_ITEM_CLASSES: tuple[CleanupItemClass, ...] = (
    CleanupItemClass(
        name="safe_decorated_text",
        allows_vector_overlap=True,
        matches=lambda item: item_is_text(item) and bool(item_role_values(item) & SAFE_VECTOR_OVERLAP_ROLES),
    ),
    CleanupItemClass(
        name="ordinary_text",
        allows_vector_overlap=False,
        matches=item_is_text,
    ),
)
