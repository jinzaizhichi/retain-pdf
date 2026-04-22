from __future__ import annotations

from .common import GROUP_ITEM_PREFIX


def _single_unit_id(item: dict) -> str:
    return str(item.get("item_id", "") or "")


def _group_unit_id(group_id: str) -> str:
    return f"{GROUP_ITEM_PREFIX}{group_id}"


def _existing_group_unit_id(item: dict) -> str:
    unit_id = str(item.get("translation_unit_id", "") or "").strip()
    if unit_id.startswith(GROUP_ITEM_PREFIX):
        return unit_id
    return ""


def _group_key(item: dict) -> str:
    group_id = str(item.get("continuation_group", "") or "").strip()
    if group_id:
        return f"continuation:{group_id}"
    unit_id = _existing_group_unit_id(item)
    if unit_id:
        return f"unit:{unit_id}"
    return ""


def _effective_group_unit_id(members: list[dict]) -> str:
    existing_ids = []
    seen: set[str] = set()
    for member in members:
        unit_id = _existing_group_unit_id(member)
        if unit_id and unit_id not in seen:
            existing_ids.append(unit_id)
            seen.add(unit_id)
    if len(existing_ids) == 1:
        return existing_ids[0]
    for member in members:
        group_id = str(member.get("continuation_group", "") or "").strip()
        if group_id:
            return _group_unit_id(group_id)
    return existing_ids[0] if existing_ids else ""


def refresh_payload_translation_units(payload: list[dict]) -> bool:
    changed = False
    grouped_members: dict[str, list[dict]] = {}
    for item in payload:
        key = _group_key(item)
        if not key:
            continue
        grouped_members.setdefault(key, []).append(item)

    preserved_singleton_groups = {
        key: members
        for key, members in grouped_members.items()
        if len(members) == 1 and _existing_group_unit_id(members[0])
    }
    effective_groups = {
        key: members
        for key, members in grouped_members.items()
        if len(members) >= 2
    }
    effective_groups.update(preserved_singleton_groups)
    effective_member_ids = {
        key: [str(member.get("item_id", "") or "") for member in members]
        for key, members in effective_groups.items()
    }
    effective_unit_ids = {
        key: _effective_group_unit_id(members)
        for key, members in effective_groups.items()
    }

    for item in payload:
        item_id = _single_unit_id(item)
        key = _group_key(item)
        if key and key in effective_groups:
            member_ids = effective_member_ids[key]
            unit_id = effective_unit_ids[key] or _existing_group_unit_id(item) or item_id
            if item.get("translation_unit_id") != unit_id:
                item["translation_unit_id"] = unit_id
                changed = True
            if item.get("translation_unit_kind") != "group":
                item["translation_unit_kind"] = "group"
                changed = True
            if item.get("translation_unit_member_ids") != member_ids:
                item["translation_unit_member_ids"] = list(member_ids)
                changed = True
            continue

        if item.get("translation_unit_id") != item_id:
            item["translation_unit_id"] = item_id
            changed = True
        if item.get("translation_unit_kind") != "single":
            item["translation_unit_kind"] = "single"
            changed = True
        if item.get("translation_unit_member_ids") != [item_id]:
            item["translation_unit_member_ids"] = [item_id]
            changed = True

        protected_source = item.get("protected_source_text", "")
        formula_map = item.get("formula_map", [])
        protected_map = item.get("protected_map", formula_map)
        if item.get("translation_unit_protected_source_text") != protected_source:
            item["translation_unit_protected_source_text"] = protected_source
            changed = True
        if item.get("translation_unit_formula_map") != formula_map:
            item["translation_unit_formula_map"] = formula_map
            changed = True
        if item.get("translation_unit_protected_map") != protected_map:
            item["translation_unit_protected_map"] = protected_map
            changed = True
        if item.get("group_protected_source_text"):
            item["group_protected_source_text"] = ""
            changed = True
        if item.get("group_formula_map"):
            item["group_formula_map"] = []
            changed = True
        if item.get("group_protected_map"):
            item["group_protected_map"] = []
            changed = True
        if item.get("group_protected_translated_text"):
            item["group_protected_translated_text"] = ""
            changed = True
        if item.get("group_translated_text"):
            item["group_translated_text"] = ""
            changed = True

    return changed


__all__ = ["refresh_payload_translation_units"]
