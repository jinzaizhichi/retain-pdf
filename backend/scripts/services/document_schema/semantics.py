from __future__ import annotations


CAPTION_TAGS = {"caption", "image_caption", "table_caption", "table_footnote", "image_footnote"}
REFERENCE_HEADING_TAGS = {"reference_heading"}
REFERENCE_ENTRY_TAGS = {"reference_entry", "reference_zone"}
ALGORITHM_TAGS = {"algorithm"}
CAPTION_BLOCK_TYPES = {"image_caption", "table_caption", "table_footnote"}


def normalize_tags(tags: list[str] | set[str] | tuple[str, ...] | None) -> set[str]:
    return {str(tag or "").strip().lower() for tag in (tags or []) if str(tag or "").strip()}


def derived_role(payload: dict | None) -> str:
    source = payload or {}
    derived = source.get("derived", {}) or {}
    return str(derived.get("role", "") or "").strip().lower()


def normalized_sub_type(payload: dict | None) -> str:
    source = payload or {}
    if "normalized_sub_type" in source:
        return str(source.get("normalized_sub_type", "") or "").strip().lower()
    return str(source.get("sub_type", "") or "").strip().lower()


def layout_role(payload: dict | None) -> str:
    source = payload or {}
    return str(source.get("layout_role", "") or "").strip().lower()


def semantic_role(payload: dict | None) -> str:
    source = payload or {}
    return str(source.get("semantic_role", "") or "").strip().lower()


def policy_translate(payload: dict | None) -> bool | None:
    source = payload or {}
    policy = source.get("policy", {}) or {}
    value = policy.get("translate")
    if isinstance(value, bool):
        return value
    return None


def has_any_tag(payload: dict | None, tags: set[str]) -> bool:
    source = payload or {}
    return bool(normalize_tags(source.get("tags", [])) & tags)


def is_caption_semantic(payload: dict | None) -> bool:
    source = payload or {}
    return derived_role(source) == "caption" or has_any_tag(source, CAPTION_TAGS)


def is_caption_like_block(payload: dict | None) -> bool:
    source = payload or {}
    if is_caption_semantic(source):
        return True
    block_type = str(source.get("block_type", source.get("type", "")) or "").strip().lower()
    return block_type in CAPTION_BLOCK_TYPES


def is_reference_heading_semantic(payload: dict | None) -> bool:
    source = payload or {}
    return derived_role(source) == "reference_heading" or has_any_tag(source, REFERENCE_HEADING_TAGS)


def is_reference_entry_semantic(payload: dict | None) -> bool:
    source = payload or {}
    return derived_role(source) == "reference_entry" or has_any_tag(source, REFERENCE_ENTRY_TAGS)


def is_algorithm_semantic(payload: dict | None) -> bool:
    source = payload or {}
    return normalized_sub_type(source) == "algorithm" or derived_role(source) == "algorithm" or has_any_tag(source, ALGORITHM_TAGS)


def is_metadata_semantic(payload: dict | None) -> bool:
    return normalized_sub_type(payload) == "metadata"


def structure_role(payload: dict | None) -> str:
    source = payload or {}
    return str(source.get("structure_role", "") or "").strip().lower()


def is_body_structure_role(payload: dict | None) -> bool:
    role = structure_role(payload)
    return role in {"", "body"}


def is_body_like_structure_role(payload: dict | None) -> bool:
    role = structure_role(payload)
    return role in {"", "body", "example_line"}


def body_repair_applied(payload: dict | None) -> bool:
    source = payload or {}
    return bool(source.get("body_repair_applied") or source.get("provider_body_repair_applied"))


def body_repair_role(payload: dict | None) -> str:
    source = payload or {}
    return str(source.get("body_repair_role", source.get("provider_body_repair_role", "")) or "").strip().lower()


def body_repair_peer_block_id(payload: dict | None) -> str:
    source = payload or {}
    return str(source.get("body_repair_peer_block_id", source.get("provider_suspected_peer_block_id", "")) or "").strip()
