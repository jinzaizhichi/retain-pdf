from __future__ import annotations

from pathlib import Path

from services.pipeline_shared.io import save_json
from services.translation.agents import TranslationAgentCoordinator
from services.translation.llm.shared.control_context import TranslationControlContext


TRANSLATION_REVIEW_FILE_NAME = "translation_review.json"
TRANSLATION_REVIEW_SCHEMA = "translation_review_v1"
TRANSLATION_REVIEW_SCHEMA_VERSION = 1


def build_translation_review(
    *,
    translated_pages_map: dict[int, list[dict]],
    translation_context: TranslationControlContext | None = None,
) -> dict[str, object]:
    coordinator = (
        TranslationAgentCoordinator.from_control_context(translation_context)
        if translation_context is not None
        else TranslationAgentCoordinator()
    )
    issues: list[dict] = []
    reviewed_item_count = 0
    for page_idx, items in sorted(translated_pages_map.items()):
        for item in items:
            item_id = str(item.get("item_id", "") or "")
            if not item_id:
                continue
            result = {
                item_id: {
                    "decision": str(item.get("decision", "") or "translate"),
                    "translated_text": str(
                        item.get("translated_text")
                        or item.get("protected_translated_text")
                        or item.get("translation_unit_translated_text")
                        or item.get("translation_unit_protected_translated_text")
                        or ""
                    ),
                    "final_status": str(item.get("final_status", "") or ""),
                    "translation_diagnostics": item.get("translation_diagnostics") or {},
                }
            }
            review = coordinator.review_batch([item], result)
            reviewed_item_count += review.reviewed_item_count
            for issue in review.issues:
                payload = issue.as_dict()
                payload.setdefault("page_idx", int(item.get("page_idx", page_idx) or page_idx))
                payload.setdefault("page_number", int(item.get("page_idx", page_idx) or page_idx) + 1)
                payload.setdefault("block_idx", int(item.get("block_idx", -1) or -1))
                issues.append(payload)

    issue_summary: dict[str, int] = {}
    severity_summary: dict[str, int] = {}
    for issue in issues:
        kind = str(issue.get("kind", "") or "")
        severity = str(issue.get("severity", "") or "")
        if kind:
            issue_summary[kind] = issue_summary.get(kind, 0) + 1
        if severity:
            severity_summary[severity] = severity_summary.get(severity, 0) + 1
    return {
        "schema": TRANSLATION_REVIEW_SCHEMA,
        "schema_version": TRANSLATION_REVIEW_SCHEMA_VERSION,
        "reviewed_item_count": reviewed_item_count,
        "issue_count": len(issues),
        "has_errors": severity_summary.get("error", 0) > 0,
        "issue_summary": issue_summary,
        "severity_summary": severity_summary,
        "issues": issues,
    }


def write_translation_review(
    path: Path,
    *,
    translated_pages_map: dict[int, list[dict]],
    translation_context: TranslationControlContext | None = None,
) -> dict[str, object]:
    payload = build_translation_review(
        translated_pages_map=translated_pages_map,
        translation_context=translation_context,
    )
    save_json(path, payload)
    return payload


__all__ = [
    "TRANSLATION_REVIEW_FILE_NAME",
    "TRANSLATION_REVIEW_SCHEMA",
    "TRANSLATION_REVIEW_SCHEMA_VERSION",
    "build_translation_review",
    "write_translation_review",
]
