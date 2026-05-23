import json
import sys
import tempfile
from pathlib import Path


REPO_SCRIPTS_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_SCRIPTS_ROOT))


from services.translation.artifacts.review import write_translation_review
from services.translation.services.agents.review_artifact import build_translation_review
from services.translation.llm.shared.control_context import GlossaryEntry
from services.translation.llm.shared.control_context import build_translation_control_context


def _item(item_id: str, source_text: str, translated_text: str) -> dict:
    return {
        "item_id": item_id,
        "page_idx": 0,
        "block_idx": 1,
        "block_type": "text",
        "metadata": {"structure_role": "body"},
        "translation_unit_protected_source_text": source_text,
        "source_text": source_text,
        "translated_text": translated_text,
        "final_status": "translated",
    }


def test_build_translation_review_collects_issue_summary() -> None:
    context = build_translation_control_context(
        glossary_entries=[GlossaryEntry(source="SCF", target="自洽场", level="preferred")]
    )
    payload = {
        0: [
            _item(
                "p001-b001",
                "The SCF cycle is converged before the energy is evaluated.",
                "该循环在计算能量前收敛。",
            )
        ]
    }

    review = build_translation_review(translated_pages_map=payload, translation_context=context)

    assert review["schema"] == "translation_review_v1"
    assert review["reviewed_item_count"] == 1
    assert review["issue_count"] == 1
    assert review["issue_summary"]["glossary_term_missing"] == 1
    assert review["issues"][0]["page_number"] == 1
    assert review["issues"][0]["block_idx"] == 1


def test_write_translation_review_round_trips_json() -> None:
    payload = {
        0: [
            _item(
                "p001-b002",
                "The final energy <f1-abc/> is reported for the system.",
                "最终能量 <f2-def/> 被报告。",
            )
        ]
    }
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "translation_review.json"

        review = write_translation_review(path, build_translation_review(translated_pages_map=payload))
        loaded = json.loads(path.read_text(encoding="utf-8"))

    assert loaded == review
    assert loaded["issue_summary"]["unexpected_placeholder"] == 1
    assert loaded["issue_summary"]["placeholder_inventory_mismatch"] == 1
