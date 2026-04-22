from __future__ import annotations
import json
from pathlib import Path

from services.document_schema.defaults import normalize_block_continuation_hint
from services.document_schema.semantics import body_repair_applied
from services.document_schema.semantics import body_repair_peer_block_id
from services.document_schema.semantics import body_repair_role
from services.document_schema.semantics import is_algorithm_semantic
from services.translation.ocr.models import TextItem
from services.translation.item_reader import item_is_algorithm_like
from services.translation.item_reader import item_block_kind
from services.translation.item_reader import item_is_bodylike
from services.translation.item_reader import item_is_title_like
from services.translation.item_reader import item_policy_translate
from services.translation.payload.parts.translation_units import refresh_payload_translation_units

from .formula_protection import protect_inline_formulas_in_segments
from .formula_protection import protected_map_from_formula_map
from .formula_protection import re_protect_restored_formulas


TRANSLATED_TEXT_FIELDS = (
    "translation_unit_protected_translated_text",
    "translation_unit_translated_text",
    "protected_translated_text",
    "translated_text",
    "group_protected_translated_text",
    "group_translated_text",
)
REQUIRED_CONTRACT_FIELDS = (
    "block_kind",
    "layout_role",
    "semantic_role",
    "structure_role",
    "policy_translate",
    "asset_id",
    "reading_order",
    "raw_block_type",
    "normalized_sub_type",
)


def _unwrap_json_translated_text(text: str) -> tuple[str, str] | None:
    raw = str(text or "").strip()
    if not raw.startswith("{") or ("translated_text" not in raw and "translations" not in raw):
        return None
    try:
        payload = json.loads(raw)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if "translated_text" in payload:
        decision = str(payload.get("decision", "translate") or "translate").strip() or "translate"
        translated_text = str(payload.get("translated_text", "") or "").strip()
        return decision, translated_text
    translations = payload.get("translations", [])
    if not isinstance(translations, list) or len(translations) != 1 or not isinstance(translations[0], dict):
        return None
    decision = str(translations[0].get("decision", "translate") or "translate").strip() or "translate"
    translated_text = str(translations[0].get("translated_text", "") or "").strip()
    return decision, translated_text


def _sanitize_loaded_translation_record(record: dict) -> bool:
    changed = False
    for field in TRANSLATED_TEXT_FIELDS:
        current = str(record.get(field, "") or "").strip()
        unwrapped = _unwrap_json_translated_text(current)
        if unwrapped is None:
            continue
        decision, translated_text = unwrapped
        record[field] = "" if decision == "keep_origin" else translated_text
        changed = True
    return changed


def _item_policy_payload(block_type: str, metadata: dict | None = None, *, contract_fields: dict | None = None) -> dict:
    payload = {
        "block_type": block_type,
        "metadata": metadata or {},
    }
    if contract_fields:
        payload.update(contract_fields)
    return payload


def _is_algorithm_item(block_type: str, metadata: dict | None = None, *, contract_fields: dict | None = None) -> bool:
    payload = _item_policy_payload(block_type, metadata, contract_fields=contract_fields)
    if item_is_algorithm_like(payload):
        return True
    return is_algorithm_semantic(metadata or {})


def _is_default_translatable_text_block(
    block_type: str,
    metadata: dict | None = None,
    *,
    contract_fields: dict | None = None,
) -> bool:
    payload = _item_policy_payload(block_type, metadata, contract_fields=contract_fields)
    explicit_policy = item_policy_translate(payload)
    if explicit_policy is not None:
        return explicit_policy
    if item_block_kind(payload) != "text":
        return False
    return item_is_bodylike(payload)


def _default_translation_flags(
    block_type: str,
    metadata: dict | None = None,
    *,
    contract_fields: dict | None = None,
) -> tuple[str, bool, str]:
    payload = _item_policy_payload(block_type, metadata, contract_fields=contract_fields)
    normalized_block_type = item_block_kind(payload)
    if _is_algorithm_item(block_type, metadata, contract_fields=contract_fields):
        return "skip_algorithm", False, "skip_algorithm"
    semantic_role = str(payload.get("semantic_role", (metadata or {}).get("semantic_role", "")) or "").strip().lower()
    if semantic_role == "reference":
        return "skip_reference_zone", False, "skip_reference_zone"
    if normalized_block_type == "image":
        return "skip_image_body", False, "skip_image_body"
    if normalized_block_type == "table":
        return "skip_table_body", False, "skip_table_body"
    if normalized_block_type == "code":
        return "code", False, "code"
    if _is_default_translatable_text_block(normalized_block_type, metadata, contract_fields=contract_fields):
        return "", True, ""
    if item_is_title_like(payload):
        return "skip_title", False, "skip_title"
    if normalized_block_type:
        return f"skip_{normalized_block_type}", False, f"skip_{normalized_block_type}"
    return "skip_non_body_text", False, "skip_non_body_text"


def _ocr_continuation_fields(metadata: dict | None) -> dict:
    hint = normalize_block_continuation_hint((metadata or {}).get("continuation_hint"))
    return {
        "ocr_continuation_source": hint["source"],
        "ocr_continuation_group_id": hint["group_id"],
        "ocr_continuation_role": hint["role"],
        "ocr_continuation_scope": hint["scope"],
        "ocr_continuation_reading_order": hint["reading_order"],
        "ocr_continuation_confidence": hint["confidence"],
    }


def _provider_layout_warning_fields(metadata: dict | None) -> dict:
    metadata = metadata or {}
    return {
        "provider_cross_column_merge_suspected": bool(
            metadata.get("cross_column_merge_suspected", metadata.get("provider_cross_column_merge_suspected"))
        ),
        "provider_reading_order_unreliable": bool(
            metadata.get("reading_order_unreliable", metadata.get("provider_reading_order_unreliable"))
        ),
        "provider_structure_unreliable": bool(
            metadata.get("structure_unreliable", metadata.get("provider_structure_unreliable"))
        ),
        "provider_text_missing_but_bbox_present": bool(
            metadata.get("text_missing_but_bbox_present", metadata.get("provider_text_missing_but_bbox_present"))
        ),
        "provider_peer_block_absorbed_text": bool(
            metadata.get("peer_block_absorbed_text", metadata.get("provider_peer_block_absorbed_text"))
        ),
        "provider_body_repair_applied": body_repair_applied(metadata),
        "provider_body_repair_role": body_repair_role(metadata),
        "provider_body_repair_strategy": str(
            metadata.get("body_repair_strategy", metadata.get("provider_body_repair_strategy", "")) or ""
        ),
        "provider_suspected_peer_block_id": body_repair_peer_block_id(metadata),
        "provider_continuation_suppressed": bool(
            metadata.get("continuation_suppressed", metadata.get("provider_continuation_suppressed"))
        ),
        "provider_continuation_suppressed_reason": str(
            metadata.get("continuation_suppressed_reason", metadata.get("provider_continuation_suppressed_reason", "")) or ""
        ),
        "provider_column_layout_mode": str(
            metadata.get("column_layout_mode", metadata.get("provider_column_layout_mode", "")) or ""
        ),
        "provider_column_index_guess": str(
            metadata.get("column_index_guess", metadata.get("provider_column_index_guess", "")) or ""
        ),
    }


def _contract_fields_from_item(item: TextItem) -> dict:
    return {
        "block_kind": str(getattr(item, "block_kind", "") or item.block_type or "").strip().lower(),
        "layout_role": str(getattr(item, "layout_role", "") or "").strip().lower(),
        "semantic_role": str(getattr(item, "semantic_role", "") or "").strip().lower(),
        "structure_role": str(getattr(item, "structure_role", "") or "").strip().lower(),
        "policy_translate": getattr(item, "policy_translate", None),
        "asset_id": str(getattr(item, "asset_id", "") or "").strip(),
        "reading_order": int(getattr(item, "reading_order", item.block_idx) or 0),
        "raw_block_type": str(getattr(item, "raw_block_type", "") or item.block_type or "").strip().lower(),
        "normalized_sub_type": str(getattr(item, "normalized_sub_type", "") or "").strip().lower(),
    }


def _missing_contract_fields(record: dict) -> list[str]:
    missing: list[str] = []
    for key in REQUIRED_CONTRACT_FIELDS:
        if key not in record:
            missing.append(key)
    return missing


def _validate_translation_payload_contract(payload: list[dict], *, translation_path: Path) -> None:
    for index, record in enumerate(payload):
        if not isinstance(record, dict):
            raise RuntimeError(f"invalid translation payload at {translation_path}: record[{index}] is not an object")
        missing = _missing_contract_fields(record)
        if missing:
            item_id = str(record.get("item_id", "") or f"record[{index}]")
            missing_joined = ", ".join(missing)
            raise RuntimeError(
                f"invalid translation payload at {translation_path}: {item_id} missing strict contract fields: {missing_joined}"
            )


def _resolve_translation_item_payload(item: TextItem, *, math_mode: str) -> tuple[str, list[dict], list[dict]]:
    if math_mode == "direct_typst":
        return item.text, [], []
    return protect_inline_formulas_in_segments(item.segments)


def export_translation_template(
    items: list[TextItem],
    output_path: Path,
    page_idx: int,
    *,
    math_mode: str = "placeholder",
) -> None:
    payload = []
    for item in items:
        contract_fields = _contract_fields_from_item(item)
        protected_source_text, formula_map, protected_map = _resolve_translation_item_payload(item, math_mode=math_mode)
        classification_label, should_translate, skip_reason = _default_translation_flags(
            item.block_type,
            item.metadata,
            contract_fields=contract_fields,
        )
        ocr_continuation_fields = _ocr_continuation_fields(item.metadata)
        provider_layout_warning_fields = _provider_layout_warning_fields(item.metadata)
        payload.append(
            {
                "item_id": item.item_id,
                "page_idx": item.page_idx,
                "block_idx": item.block_idx,
                "block_type": item.block_type,
                **contract_fields,
                "bbox": item.bbox,
                "source_text": item.text,
                "lines": item.lines,
                "metadata": item.metadata,
                **ocr_continuation_fields,
                **provider_layout_warning_fields,
                "layout_mode": "",
                "layout_split_x": 0.0,
                "layout_zone": "",
                "layout_zone_rank": -1,
                "layout_zone_size": 0,
                "layout_boundary_role": "",
                "math_mode": math_mode,
                "protected_source_text": protected_source_text,
                "mixed_original_protected_source_text": protected_source_text,
                "formula_map": formula_map,
                "protected_map": protected_map,
                "classification_label": classification_label,
                "should_translate": should_translate,
                "skip_reason": skip_reason,
                "mixed_literal_action": "",
                "mixed_literal_prefix": "",
                "translation_unit_id": item.item_id,
                "translation_unit_kind": "single",
                "translation_unit_member_ids": [item.item_id],
                "translation_unit_protected_source_text": protected_source_text,
                "translation_unit_formula_map": formula_map,
                "translation_unit_protected_map": protected_map,
                "translation_unit_protected_translated_text": "",
                "translation_unit_translated_text": "",
                "protected_translated_text": "",
                "translated_text": "",
                "continuation_group": "",
                "continuation_prev_text": "",
                "continuation_next_text": "",
                "continuation_decision": "",
                "continuation_candidate_prev_id": "",
                "continuation_candidate_next_id": "",
                "group_protected_source_text": "",
                "group_formula_map": [],
                "group_protected_map": [],
                "group_protected_translated_text": "",
                "group_translated_text": "",
                "final_status": "",
                "translation_diagnostics": {},
            }
        )

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def load_translations(translation_path: Path, *, strict_contract: bool = True) -> list[dict]:
    with translation_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    changed = False
    for record in payload:
        if isinstance(record, dict):
            changed = _sanitize_loaded_translation_record(record) or changed
    if refresh_payload_translation_units(payload):
        changed = True
    if changed:
        save_translations(translation_path, payload)
    if strict_contract:
        _validate_translation_payload_contract(payload, translation_path=translation_path)
    return payload


def save_translations(translation_path: Path, payload: list[dict]) -> None:
    with translation_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def ensure_translation_template(
    items: list[TextItem],
    output_path: Path,
    page_idx: int,
    *,
    math_mode: str = "placeholder",
) -> Path:
    if not output_path.exists():
        output_path.parent.mkdir(parents=True, exist_ok=True)
        export_translation_template(items, output_path, page_idx=page_idx, math_mode=math_mode)
        return output_path

    try:
        payload = load_translations(output_path)
    except RuntimeError as exc:
        if "missing strict contract fields" not in str(exc):
            raise
        export_translation_template(items, output_path, page_idx=page_idx, math_mode=math_mode)
        return output_path
    item_map = {item.item_id: item for item in items}
    changed = False
    for record in payload:
        item = item_map.get(record.get("item_id"))
        if not item:
            continue
        contract_fields = _contract_fields_from_item(item)
        classification_label, should_translate, skip_reason = _default_translation_flags(
            item.block_type,
            item.metadata,
            contract_fields=contract_fields,
        )
        ocr_continuation_fields = _ocr_continuation_fields(item.metadata)
        provider_layout_warning_fields = _provider_layout_warning_fields(item.metadata)
        protected_source_text, formula_map, protected_map = _resolve_translation_item_payload(item, math_mode=math_mode)
        for key, value in contract_fields.items():
            if record.get(key) != value:
                record[key] = value
                changed = True
        if record.get("bbox") != item.bbox:
            record["bbox"] = item.bbox
            changed = True
        if record.get("source_text") != item.text:
            record["source_text"] = item.text
            changed = True
        if record.get("lines") != item.lines:
            record["lines"] = item.lines
            changed = True
        if record.get("metadata") != item.metadata:
            record["metadata"] = item.metadata
            changed = True
        if (
            "protected_source_text" not in record
            or "formula_map" not in record
            or "protected_translated_text" not in record
            or "lines" not in record
        ):
            record["source_text"] = item.text
            record["lines"] = item.lines
            record["metadata"] = item.metadata
            record.update(contract_fields)
            record.update(ocr_continuation_fields)
            record.update(provider_layout_warning_fields)
            record["math_mode"] = math_mode
            record["protected_source_text"] = protected_source_text
            record["formula_map"] = formula_map
            record["protected_map"] = protected_map
            record.setdefault("classification_label", classification_label)
            record.setdefault("should_translate", should_translate)
            record.setdefault("protected_translated_text", "")
            record.setdefault("continuation_group", "")
            record.setdefault("continuation_prev_text", "")
            record.setdefault("continuation_next_text", "")
            record.setdefault("group_protected_source_text", "")
            record.setdefault("group_formula_map", [])
            record.setdefault("group_protected_translated_text", "")
            record.setdefault("group_translated_text", "")
            changed = True
        if record.get("math_mode") != math_mode:
            record["math_mode"] = math_mode
            changed = True
        if math_mode == "direct_typst":
            if record.get("protected_source_text") != protected_source_text:
                record["protected_source_text"] = protected_source_text
                changed = True
            if record.get("mixed_original_protected_source_text") != protected_source_text:
                record["mixed_original_protected_source_text"] = protected_source_text
                changed = True
            if record.get("formula_map") != []:
                record["formula_map"] = []
                changed = True
            if record.get("protected_map") != []:
                record["protected_map"] = []
                changed = True
            if record.get("translation_unit_protected_source_text") != protected_source_text:
                record["translation_unit_protected_source_text"] = protected_source_text
                changed = True
            if record.get("translation_unit_formula_map") != []:
                record["translation_unit_formula_map"] = []
                changed = True
            if record.get("translation_unit_protected_map") != []:
                record["translation_unit_protected_map"] = []
                changed = True
        if "classification_label" not in record:
            record["classification_label"] = classification_label
            changed = True
        if "mixed_original_protected_source_text" not in record:
            record["mixed_original_protected_source_text"] = record.get("protected_source_text", "")
            changed = True
        if "mixed_literal_action" not in record:
            record["mixed_literal_action"] = ""
            changed = True
        if "mixed_literal_prefix" not in record:
            record["mixed_literal_prefix"] = ""
            changed = True
        if "layout_mode" not in record:
            record["layout_mode"] = ""
            changed = True
        if "layout_split_x" not in record:
            record["layout_split_x"] = 0.0
            changed = True
        if "layout_zone" not in record:
            record["layout_zone"] = ""
            changed = True
        if "layout_zone_rank" not in record:
            record["layout_zone_rank"] = -1
            changed = True
        if "layout_zone_size" not in record:
            record["layout_zone_size"] = 0
            changed = True
        if "layout_boundary_role" not in record:
            record["layout_boundary_role"] = ""
            changed = True
        if "metadata" not in record:
            record["metadata"] = item.metadata
            changed = True
        for key, value in ocr_continuation_fields.items():
            if record.get(key) != value:
                record[key] = value
                changed = True
        for key, value in provider_layout_warning_fields.items():
            if record.get(key) != value:
                record[key] = value
                changed = True
        if "should_translate" not in record:
            record["should_translate"] = should_translate
            changed = True
        if "skip_reason" not in record:
            record["skip_reason"] = skip_reason
            changed = True
        if not should_translate:
            if record.get("classification_label") != classification_label:
                record["classification_label"] = classification_label
                changed = True
            if record.get("should_translate") is not should_translate:
                record["should_translate"] = should_translate
                changed = True
            if record.get("skip_reason") != skip_reason:
                record["skip_reason"] = skip_reason
                changed = True
            if any(
                record.get(field)
                for field in (
                    "translation_unit_protected_translated_text",
                    "translation_unit_translated_text",
                    "protected_translated_text",
                    "translated_text",
                    "group_protected_translated_text",
                    "group_translated_text",
                )
            ):
                record["translation_unit_protected_translated_text"] = ""
                record["translation_unit_translated_text"] = ""
                record["protected_translated_text"] = ""
                record["translated_text"] = ""
                record["group_protected_translated_text"] = ""
                record["group_translated_text"] = ""
                changed = True
        if "translation_unit_id" not in record:
            record["translation_unit_id"] = record.get("item_id", item.item_id)
            changed = True
        if "translation_unit_kind" not in record:
            record["translation_unit_kind"] = "single"
            changed = True
        if "translation_unit_member_ids" not in record:
            record["translation_unit_member_ids"] = [record.get("item_id", item.item_id)]
            changed = True
        if "translation_unit_protected_source_text" not in record:
            record["translation_unit_protected_source_text"] = record.get("protected_source_text", "")
            changed = True
        if "translation_unit_formula_map" not in record:
            record["translation_unit_formula_map"] = record.get("formula_map", [])
            changed = True
        if "protected_map" not in record:
            record["protected_map"] = protected_map_from_formula_map(record.get("formula_map", []))
            changed = True
        if "translation_unit_protected_map" not in record:
            record["translation_unit_protected_map"] = record.get("protected_map", [])
            changed = True
        if "translation_unit_protected_translated_text" not in record:
            record["translation_unit_protected_translated_text"] = ""
            changed = True
        if "translation_unit_translated_text" not in record:
            record["translation_unit_translated_text"] = ""
            changed = True
        if "continuation_group" not in record:
            record["continuation_group"] = ""
            changed = True
        if "continuation_prev_text" not in record:
            record["continuation_prev_text"] = ""
            changed = True
        if "continuation_next_text" not in record:
            record["continuation_next_text"] = ""
            changed = True
        if "continuation_decision" not in record:
            record["continuation_decision"] = ""
            changed = True
        if "continuation_candidate_prev_id" not in record:
            record["continuation_candidate_prev_id"] = ""
            changed = True
        if "continuation_candidate_next_id" not in record:
            record["continuation_candidate_next_id"] = ""
            changed = True
        if "group_protected_source_text" not in record:
            record["group_protected_source_text"] = ""
            changed = True
        if "group_formula_map" not in record:
            record["group_formula_map"] = []
            changed = True
        if "group_protected_map" not in record:
            record["group_protected_map"] = []
            changed = True
        if "group_protected_translated_text" not in record:
            record["group_protected_translated_text"] = ""
            changed = True
        if "group_translated_text" not in record:
            record["group_translated_text"] = ""
            changed = True
        if "final_status" not in record:
            record["final_status"] = ""
            changed = True
        if "translation_diagnostics" not in record:
            record["translation_diagnostics"] = {}
            changed = True
        if not record.get("protected_translated_text") and record.get("translated_text"):
            record["protected_translated_text"] = re_protect_restored_formulas(
                record["translated_text"],
                record.get("formula_map", []),
            )
            changed = True
    if refresh_payload_translation_units(payload):
        changed = True
    if changed:
        save_translations(output_path, payload)
    return output_path
