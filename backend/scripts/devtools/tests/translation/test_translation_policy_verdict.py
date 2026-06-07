from __future__ import annotations

import sys
from pathlib import Path


REPO_SCRIPTS_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_SCRIPTS_ROOT))


from services.translation.services.policy import translation_policy_verdict


def _item(item_id: str, source_text: str, **overrides) -> dict:
    item = {
        "item_id": item_id,
        "block_type": "text",
        "block_kind": "text",
        "source_text": source_text,
        "protected_source_text": source_text,
        "should_translate": True,
    }
    item.update(overrides)
    return item


def test_policy_verdict_translatable_body_calls_model_and_blocks_empty_export() -> None:
    verdict = translation_policy_verdict(
        _item("body", "The density functional is evaluated on the numerical grid.")
    )

    assert verdict.action == "translate"
    assert verdict.should_call_model is True
    assert verdict.allow_keep_origin is False
    assert verdict.blocks_export is True
    assert verdict.fast_path_keep_origin is False


def test_policy_verdict_policy_skip_keeps_origin_without_model_or_export_block() -> None:
    verdict = translation_policy_verdict(
        _item("formula", "$$ E = mc^2 $$", raw_block_type="display_formula", should_translate=False)
    )

    assert verdict.action == "keep_origin"
    assert verdict.reason == "policy_skip"
    assert verdict.should_call_model is False
    assert verdict.allow_keep_origin is True
    assert verdict.blocks_export is False
    assert verdict.fast_path_keep_origin is True


def test_policy_verdict_protocol_hex_dump_keeps_origin_without_model_or_export_block() -> None:
    source = "Answer(slave-Base module):\n" + " ".join(["01", "03", "40", "FF", "00"] * 80)
    verdict = translation_policy_verdict(_item("p182-b016", source))

    assert verdict.action == "keep_origin"
    assert verdict.reason == "protocol_hex_dump"
    assert verdict.should_call_model is False
    assert verdict.allow_keep_origin is True
    assert verdict.blocks_export is False
    assert verdict.fast_path_keep_origin is True
