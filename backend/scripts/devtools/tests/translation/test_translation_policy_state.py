from __future__ import annotations

import sys
from pathlib import Path


REPO_SCRIPTS_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_SCRIPTS_ROOT))


from services.translation.core.payload.parts.policy_state import mark_policy_skip
from services.translation.core.payload.parts.policy_state import mark_translation_required


def test_mark_policy_skip_clears_translation_and_sets_keep_origin_state() -> None:
    item = {
        "source_text": "References",
        "protected_source_text": "References",
        "translated_text": "参考文献",
        "protected_translated_text": "参考文献",
        "translation_unit_translated_text": "参考文献",
        "translation_unit_protected_translated_text": "参考文献",
    }

    mark_policy_skip(item, "skip_reference_zone")

    assert item["classification_label"] == "skip_reference_zone"
    assert item["should_translate"] is False
    assert item["skip_reason"] == "skip_reference_zone"
    assert item["final_status"] == "kept_origin"
    assert item["translated_text"] == ""
    assert item["protected_translated_text"] == ""
    assert item["translation_unit_translated_text"] == ""
    assert item["translation_unit_protected_translated_text"] == ""


def test_mark_translation_required_clears_skip_state_without_touching_translation() -> None:
    item = {
        "classification_label": "skip_reference_zone",
        "should_translate": False,
        "skip_reason": "skip_reference_zone",
        "translated_text": "existing text",
    }

    mark_translation_required(item, label="translate_literal")

    assert item["classification_label"] == "translate_literal"
    assert item["should_translate"] is True
    assert item["skip_reason"] == ""
    assert item["translated_text"] == "existing text"
