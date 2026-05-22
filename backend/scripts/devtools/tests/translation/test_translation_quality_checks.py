import sys
from pathlib import Path


REPO_SCRIPTS_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_SCRIPTS_ROOT))


from services.translation.quality import review_translation_batch
from services.translation.quality import review_translation_item
from services.translation.terms import GlossaryEntry


def _body_item(item_id: str, source_text: str, **overrides) -> dict:
    item = {
        "item_id": item_id,
        "block_type": "text",
        "metadata": {"structure_role": "body"},
        "translation_unit_protected_source_text": source_text,
    }
    item.update(overrides)
    return item


def test_quality_checks_collect_placeholder_and_english_issues() -> None:
    item = _body_item(
        "p001-b001",
        (
            "The self-consistent field procedure computes the molecular orbitals <f1-abc/> before "
            "the final energy is evaluated for the system."
        ),
    )

    report = review_translation_batch(
        [item],
        {
            "p001-b001": {
                "decision": "translate",
                "translated_text": (
                    "The self-consistent field procedure computes the molecular orbitals <f2-def/> before "
                    "the final energy is evaluated for the system."
                ),
            }
        },
    )

    kinds = {issue.kind for issue in report.issues}
    assert report.has_errors
    assert "english_residue" in kinds
    assert "unexpected_placeholder" in kinds
    assert "placeholder_inventory_mismatch" in kinds


def test_quality_checks_collect_glossary_issues() -> None:
    item = _body_item(
        "p002-b003",
        "The SCF cycle is initialized from Hartree-Fock orbitals and then iterated.",
    )

    report = review_translation_item(
        item,
        {
            "decision": "translate",
            "translated_text": "该循环由轨道初始化，然后迭代。",
        },
        glossary_entries=[
            GlossaryEntry(source="SCF", target="自洽场", level="preferred"),
            GlossaryEntry(source="Hartree-Fock", target="Hartree-Fock", level="preserve", match_mode="case_insensitive"),
        ],
    )

    glossary_issues = [issue for issue in report.issues if issue.kind == "glossary_term_missing"]
    assert [issue.details["source"] for issue in glossary_issues] == ["Hartree-Fock", "SCF"]
