from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from services.translation.artifacts import blocking_untranslated_items
from services.translation.core.payload.parts.apply import apply_single_translated_entry
from services.translation.core.payload.parts.policy_state import mark_keep_origin
from services.translation.llm.shared.provider_runtime import request_chat_content
from services.translation.llm.result_payload import result_entry
from services.translation.llm.validation.quality import review_translation_item
from services.translation.services.policy import should_skip_model_by_policy


DEFAULT_MAX_WORKERS = 32
DEFAULT_MAX_ITEMS = 256


@dataclass(frozen=True)
class FinalUntranslatedRecoverySummary:
    blocking_before: int = 0
    attempted_items: int = 0
    recovered_items: int = 0
    dead_letter_items: int = 0
    blocking_after: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "blocking_before": self.blocking_before,
            "attempted_items": self.attempted_items,
            "recovered_items": self.recovered_items,
            "dead_letter_items": self.dead_letter_items,
            "blocking_after": self.blocking_after,
        }


def recover_blocking_untranslated_items(
    page_payloads: dict[int, list[dict]],
    *,
    api_key: str,
    model: str,
    base_url: str,
    target_language_name: str = "简体中文",
    max_items: int = DEFAULT_MAX_ITEMS,
    workers: int = DEFAULT_MAX_WORKERS,
    request_chat_content_fn=request_chat_content,
) -> FinalUntranslatedRecoverySummary:
    blocking = blocking_untranslated_items(page_payloads)
    if not blocking:
        return FinalUntranslatedRecoverySummary()
    item_by_id = _item_index(page_payloads)
    blocking_before = len(blocking)
    for item in (
        item_by_id[item["item_id"]]
        for item in blocking
        if item.get("item_id") in item_by_id and should_skip_model_by_policy(item_by_id[item["item_id"]])
    ):
        _mark_final_policy_keep_origin(item)
    blocking = blocking_untranslated_items(page_payloads)
    if not blocking:
        return FinalUntranslatedRecoverySummary(
            blocking_before=blocking_before,
            blocking_after=0,
        )
    candidates = [
        item_by_id[item["item_id"]]
        for item in blocking[: max(0, max_items)]
        if item.get("item_id") in item_by_id and _can_final_recover(item_by_id[item["item_id"]])
    ]
    if not candidates:
        return FinalUntranslatedRecoverySummary(
            blocking_before=blocking_before,
            blocking_after=len(blocking),
        )

    recovered = 0
    dead_letter = 0
    max_workers = max(1, min(int(workers or 1), len(candidates)))
    if max_workers <= 1:
        results = [
            _recover_one(
                item,
                api_key=api_key,
                model=model,
                base_url=base_url,
                target_language_name=target_language_name,
                request_chat_content_fn=request_chat_content_fn,
            )
            for item in candidates
        ]
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(
                    _recover_one,
                    item,
                    api_key=api_key,
                    model=model,
                    base_url=base_url,
                    target_language_name=target_language_name,
                    request_chat_content_fn=request_chat_content_fn,
                )
                for item in candidates
            ]
            results = [future.result() for future in as_completed(futures)]

    for item, payload, exc in results:
        if payload is not None:
            apply_single_translated_entry(item, payload)
            recovered += 1
            continue
        _mark_final_dead_letter(item, exc)
        dead_letter += 1

    after = blocking_untranslated_items(page_payloads)
    return FinalUntranslatedRecoverySummary(
        blocking_before=blocking_before,
        attempted_items=len(candidates),
        recovered_items=recovered,
        dead_letter_items=dead_letter,
        blocking_after=len(after),
    )


def _item_index(page_payloads: dict[int, list[dict]]) -> dict[str, dict]:
    return {
        str(item.get("item_id", "") or ""): item
        for page_idx in sorted(page_payloads)
        for item in page_payloads[page_idx]
        if str(item.get("item_id", "") or "")
    }


def _can_final_recover(item: dict) -> bool:
    if should_skip_model_by_policy(item):
        return False
    source_text = _source_text(item)
    return bool(source_text and any(ch.isalpha() for ch in source_text))


def _recover_one(
    item: dict,
    *,
    api_key: str,
    model: str,
    base_url: str,
    target_language_name: str,
    request_chat_content_fn,
):
    try:
        translated = _request_final_translation(
            item,
            api_key=api_key,
            model=model,
            base_url=base_url,
            target_language_name=target_language_name,
            request_chat_content_fn=request_chat_content_fn,
        )
        payload = result_entry("translate", translated)
        payload["translation_diagnostics"] = {
            "item_id": item.get("item_id", ""),
            "page_idx": item.get("page_idx"),
            "route_path": ["block_level", "final_untranslated_recovery"],
            "fallback_to": "final_untranslated_recovery",
            "degradation_reason": "blocking_untranslated_recovered",
            "final_status": "translated",
        }
        issues = [
            issue
            for issue in review_translation_item(item, payload).issues
            if issue.severity == "error"
        ]
        if issues:
            raise ValueError("final recovery output failed validation: " + ", ".join(issue.kind for issue in issues[:3]))
        return item, payload, None
    except Exception as exc:
        return item, None, exc


def _request_final_translation(
    item: dict,
    *,
    api_key: str,
    model: str,
    base_url: str,
    target_language_name: str,
    request_chat_content_fn,
) -> str:
    source_text = _source_text(item)
    content = request_chat_content_fn(
        [
            {
                "role": "system",
                "content": (
                    f"Translate the current scientific PDF block into {target_language_name}.\n"
                    "Preserve every inline LaTeX math expression and placeholder exactly.\n"
                    "Return only the translated block text. Do not return JSON."
                ),
            },
            {"role": "user", "content": source_text},
        ],
        api_key=api_key,
        model=model,
        base_url=base_url,
        temperature=0.0,
        response_format=None,
        timeout=45,
        request_label=f"final-untranslated-recovery {item.get('item_id', '')}",
        max_attempts=2,
    )
    translated = str(content or "").strip()
    if not translated:
        raise ValueError("final recovery returned empty translation")
    return translated


def _source_text(item: dict) -> str:
    return str(
        item.get("translation_unit_protected_source_text")
        or item.get("protected_source_text")
        or item.get("source_text")
        or ""
    ).strip()


def _mark_final_dead_letter(item: dict, exc: Exception | None) -> None:
    diagnostics = dict(item.get("translation_diagnostics") or {})
    diagnostics.update(
        {
            "item_id": item.get("item_id", ""),
            "page_idx": item.get("page_idx"),
            "route_path": ["block_level", "final_untranslated_recovery", "dead_letter"],
            "fallback_to": "dead_letter_queue",
            "degradation_reason": "final_untranslated_recovery_failed",
            "final_status": "kept_origin",
            "dead_letter": True,
            "final_recovery_error_type": type(exc).__name__ if exc is not None else "UnknownError",
            "final_recovery_error": str(exc or ""),
        }
    )
    item["translation_diagnostics"] = diagnostics
    mark_keep_origin(item)
    item["translation_diagnostics"] = diagnostics


def _mark_final_policy_keep_origin(item: dict) -> None:
    diagnostics = dict(item.get("translation_diagnostics") or {})
    diagnostics.update(
        {
            "item_id": item.get("item_id", ""),
            "page_idx": item.get("page_idx"),
            "route_path": ["block_level", "final_untranslated_recovery", "policy_keep_origin"],
            "fallback_to": "policy_keep_origin",
            "degradation_reason": "policy_keep_origin",
            "final_status": "kept_origin",
        }
    )
    mark_keep_origin(item)
    item["translation_diagnostics"] = diagnostics


__all__ = [
    "FinalUntranslatedRecoverySummary",
    "recover_blocking_untranslated_items",
]
