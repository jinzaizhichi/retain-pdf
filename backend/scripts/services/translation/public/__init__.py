"""Stable translation integration surface for other backend subsystems.

Runtime pipeline, OCR provider, and rendering code should import translation
contracts from this package instead of reaching into translation internals.
Exports are lazy to avoid import cycles between translation and rendering.
"""

from __future__ import annotations

from importlib import import_module


_EXPORTS = {
    "write_translation_debug_index": ("services.translation.artifacts", "write_translation_debug_index"),
    "write_translation_diagnostics": ("services.translation.artifacts", "write_translation_diagnostics"),
    "item_asset_id": ("services.translation.core.item_reader", "item_asset_id"),
    "item_bbox": ("services.translation.core.item_reader", "item_bbox"),
    "item_block_kind": ("services.translation.core.item_reader", "item_block_kind"),
    "item_effective_role": ("services.translation.core.item_reader", "item_effective_role"),
    "item_is_algorithm_like": ("services.translation.core.item_reader", "item_is_algorithm_like"),
    "item_is_bodylike": ("services.translation.core.item_reader", "item_is_bodylike"),
    "item_is_caption_like": ("services.translation.core.item_reader", "item_is_caption_like"),
    "item_is_footnote_like": ("services.translation.core.item_reader", "item_is_footnote_like"),
    "item_is_plain_text_block": ("services.translation.core.item_reader", "item_is_plain_text_block"),
    "item_is_reference_heading_like": ("services.translation.core.item_reader", "item_is_reference_heading_like"),
    "item_is_reference_like": ("services.translation.core.item_reader", "item_is_reference_like"),
    "item_is_textual": ("services.translation.core.item_reader", "item_is_textual"),
    "item_is_title_like": ("services.translation.core.item_reader", "item_is_title_like"),
    "item_layout_role": ("services.translation.core.item_reader", "item_layout_role"),
    "item_normalized_sub_type": ("services.translation.core.item_reader", "item_normalized_sub_type"),
    "item_policy_translate": ("services.translation.core.item_reader", "item_policy_translate"),
    "item_raw_block_type": ("services.translation.core.item_reader", "item_raw_block_type"),
    "item_reading_order": ("services.translation.core.item_reader", "item_reading_order"),
    "item_semantic_role": ("services.translation.core.item_reader", "item_semantic_role"),
    "item_source_text": ("services.translation.core.item_reader", "item_source_text"),
    "item_structure_role": ("services.translation.core.item_reader", "item_structure_role"),
    "item_tags": ("services.translation.core.item_reader", "item_tags"),
    "load_translation_manifest": ("services.translation.core.payload", "load_translation_manifest"),
    "load_translation_manifest_file": ("services.translation.core.payload", "load_translation_manifest_file"),
    "load_translations": ("services.translation.core.payload", "load_translations"),
    "PROTECTED_TOKEN_RE": ("services.translation.core.payload", "PROTECTED_TOKEN_RE"),
    "re_protect_restored_formulas": ("services.translation.core.payload", "re_protect_restored_formulas"),
    "restore_protected_tokens": ("services.translation.core.payload", "restore_protected_tokens"),
    "TRANSLATION_MANIFEST_FILE_NAME": ("services.translation.core.payload", "TRANSLATION_MANIFEST_FILE_NAME"),
    "translation_manifest_path": ("services.translation.core.payload", "translation_manifest_path"),
    "protected_map_from_formula_map": (
        "services.translation.core.payload.formula_protection",
        "protected_map_from_formula_map",
    ),
    "GlossaryEntry": ("services.translation.core.terms", "GlossaryEntry"),
    "parse_glossary_json": ("services.translation.core.terms", "parse_glossary_json"),
    "DEFAULT_BASE_URL": ("services.translation.llm.shared.provider_runtime", "DEFAULT_BASE_URL"),
    "DEFAULT_MODEL": ("services.translation.llm.shared.provider_runtime", "DEFAULT_MODEL"),
    "get_api_key": ("services.translation.llm.shared.provider_runtime", "get_api_key"),
    "normalize_base_url": ("services.translation.llm.shared.provider_runtime", "normalize_base_url"),
    "request_chat_content": ("services.translation.llm.shared.provider_runtime", "request_chat_content"),
    "TranslationExecutionRequest": ("services.translation.workflow", "TranslationExecutionRequest"),
    "execute_translation_request": ("services.translation.workflow", "execute_translation_request"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
