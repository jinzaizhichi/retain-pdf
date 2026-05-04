from __future__ import annotations

import json

from dataclasses import dataclass
from typing import Callable

from services.translation.item_reader import item_block_kind
from services.translation.item_reader import item_is_bodylike
from services.translation.item_reader import item_is_caption_like
from services.translation.item_reader import item_layout_role
from services.translation.item_reader import item_policy_translate
from services.translation.item_reader import item_semantic_role
from services.translation.llm.result_payload import result_entry
from services.translation.llm.validation.english_residue import should_force_translate_body_text
from services.translation.llm.validation.placeholder_tokens import placeholder_sequence
from services.translation.llm.validation.placeholder_tokens import strip_placeholders
from services.translation.llm.shared.control_context import TranslationControlContext
from services.translation.payload.parts.common import GROUP_ITEM_PREFIX
from services.translation.policy.metadata_filter import looks_like_hard_nontranslatable_metadata


@dataclass(frozen=True)
class _PlanItemView:
    item: dict
    source: str
    compact: str
    policy_translate: bool | None
    layout_zone: str


@dataclass(frozen=True)
class _KeepOriginRule:
    reason: str
    predicate: Callable[["_PlanItemView"], bool]


@dataclass(frozen=True)
class _BatchabilityRule:
    predicate: Callable[["_PlanItemView", TranslationControlContext], bool]


@dataclass(frozen=True)
class TranslationBatchRunStats:
    pending_items: int
    total_batches: int
    effective_batch_size: int
    flush_interval: int
    effective_workers: int
    batched_fast_batches: int
    single_fast_batches: int
    single_slow_batches: int

    def as_dict(self) -> dict[str, int]:
        return {
            "pending_items": self.pending_items,
            "total_batches": self.total_batches,
            "effective_batch_size": self.effective_batch_size,
            "flush_interval": self.flush_interval,
            "effective_workers": self.effective_workers,
            "fast_queue_batches": self.batched_fast_batches + self.single_fast_batches,
            "slow_queue_batches": self.single_slow_batches,
            "batched_fast_batches": self.batched_fast_batches,
            "single_fast_batches": self.single_fast_batches,
            "single_slow_batches": self.single_slow_batches,
        }


def chunked(seq: list[dict], size: int) -> list[list[dict]]:
    return [seq[i : i + size] for i in range(0, len(seq), size)]


def _save_flush_interval(*, workers: int, total_batches: int) -> int:
    if total_batches <= 1:
        return 1
    return max(2, min(12, max(1, workers) * 2))


def _effective_translation_batch_size(
    *,
    batch_size: int,
    model: str,
    base_url: str,
    translation_context: TranslationControlContext | None,
) -> int:
    del model, base_url
    configured = max(1, batch_size)
    if translation_context is None:
        return configured
    return max(configured, max(1, translation_context.batch_policy.plain_batch_size))


def _source_text(item: dict) -> str:
    return str(
        item.get("translation_unit_protected_source_text")
        or item.get("group_protected_source_text")
        or item.get("protected_source_text")
        or item.get("source_text")
        or ""
    )


def _normalized_text_without_placeholders(item: dict) -> str:
    return " ".join(strip_placeholders(_source_text(item)).split())


def _plan_item_view(item: dict) -> _PlanItemView:
    return _PlanItemView(
        item=item,
        source=_source_text(item),
        compact=_normalized_text_without_placeholders(item),
        policy_translate=item_policy_translate(item),
        layout_zone=str(item.get("layout_zone", "") or "").strip().lower(),
    )


def _dedupe_signature(item: dict) -> str | None:
    item_id = str(item.get("item_id", "") or "")
    if item_id.startswith(GROUP_ITEM_PREFIX):
        return None
    if item.get("continuation_group"):
        return None
    if item.get("formula_map") or item.get("translation_unit_formula_map"):
        return None
    if item.get("protected_map") or item.get("translation_unit_protected_map"):
        return None
    source = _source_text(item).strip()
    if not source:
        return None
    payload = {
        "block_kind": item_block_kind(item),
        "layout_role": item_layout_role(item),
        "semantic_role": item_semantic_role(item),
        "source": source,
        "mixed_literal_action": str(item.get("mixed_literal_action", "") or ""),
        "mixed_literal_prefix": str(item.get("mixed_literal_prefix", "") or ""),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _dedupe_pending_items(pending: list[dict]) -> tuple[list[dict], dict[str, list[dict]]]:
    unique: list[dict] = []
    duplicates_by_rep_id: dict[str, list[dict]] = {}
    representative_by_signature: dict[str, dict] = {}
    for item in pending:
        signature = _dedupe_signature(item)
        if signature is None:
            unique.append(item)
            continue
        representative = representative_by_signature.get(signature)
        if representative is None:
            representative_by_signature[signature] = item
            unique.append(item)
            continue
        rep_id = str(representative.get("item_id", "") or "")
        duplicates_by_rep_id.setdefault(rep_id, []).append(item)
    return unique, duplicates_by_rep_id


def _fast_path_keep_origin_result(item: dict, reason: str) -> dict[str, dict[str, str]]:
    payload = result_entry("keep_origin", "")
    payload["translation_diagnostics"] = {
        "item_id": item.get("item_id", ""),
        "page_idx": item.get("page_idx"),
        "route_path": ["block_level", "fast_path_keep_origin"],
        "output_mode_path": [],
        "fallback_to": "keep_origin",
        "degradation_reason": reason,
        "final_status": "kept_origin",
    }
    return {str(item.get("item_id", "") or ""): payload}


def _is_short_alnum_label(view: _PlanItemView) -> bool:
    return len(view.compact) <= 4 and view.compact.replace(" ", "").isalnum()


_FAST_PATH_KEEP_ORIGIN_RULES: tuple[_KeepOriginRule, ...] = (
    _KeepOriginRule("empty_source_text", lambda view: not view.source.strip()),
    _KeepOriginRule("placeholder_only", lambda view: not view.compact),
    _KeepOriginRule("policy_skip", lambda view: view.policy_translate is False),
    _KeepOriginRule("hard_metadata_fragment", lambda view: looks_like_hard_nontranslatable_metadata(view.item)),
    _KeepOriginRule(
        "short_non_body_label",
        lambda view: _is_short_alnum_label(view) and item_is_caption_like(view.item),
    ),
    _KeepOriginRule(
        "short_non_body_label",
        lambda view: _is_short_alnum_label(view) and not view.policy_translate and view.layout_zone == "non_flow",
    ),
)


def _is_fast_path_keep_origin_item(item: dict) -> tuple[bool, str]:
    view = _plan_item_view(item)
    matched_rule = next((rule for rule in _FAST_PATH_KEEP_ORIGIN_RULES if rule.predicate(view)), None)
    return (True, matched_rule.reason) if matched_rule is not None else (False, "")


def _math_mode(item: dict) -> str:
    return str(item.get("math_mode", "placeholder") or "placeholder").strip()


def _is_within_batch_text_size(view: _PlanItemView, context: TranslationControlContext) -> bool:
    return (
        context.batch_policy.batch_low_risk_min_chars
        <= len(view.compact)
        <= context.batch_policy.batch_low_risk_max_chars
    )


def _has_acceptable_placeholder_count(view: _PlanItemView, context: TranslationControlContext) -> bool:
    return len(placeholder_sequence(view.source)) <= context.batch_policy.batch_low_risk_max_placeholders


_LOW_RISK_BATCHABILITY_RULES: tuple[_BatchabilityRule, ...] = (
    _BatchabilityRule(lambda view, _context: _math_mode(view.item) != "direct_typst"),
    _BatchabilityRule(lambda view, _context: not str(view.item.get("continuation_group", "") or "").strip()),
    _BatchabilityRule(lambda view, _context: not str(view.item.get("translation_unit_id", "") or "").startswith(GROUP_ITEM_PREFIX)),
    _BatchabilityRule(lambda view, _context: item_block_kind(view.item) == "text"),
    _BatchabilityRule(lambda view, _context: item_is_bodylike(view.item)),
    _BatchabilityRule(lambda view, _context: should_force_translate_body_text(view.item)),
    _BatchabilityRule(lambda view, _context: bool(view.source.strip())),
    _BatchabilityRule(_is_within_batch_text_size),
    _BatchabilityRule(_has_acceptable_placeholder_count),
)


def _is_low_risk_batchable_item(item: dict, *, translation_context: TranslationControlContext | None) -> bool:
    if translation_context is None:
        return False
    view = _plan_item_view(item)
    return all(rule.predicate(view, translation_context) for rule in _LOW_RISK_BATCHABILITY_RULES)


def _build_translation_batches(
    pending: list[dict],
    *,
    effective_batch_size: int,
    translation_context: TranslationControlContext | None,
) -> tuple[list[list[dict]], list[dict[str, dict[str, str]]]]:
    immediate_results: list[dict[str, dict[str, str]]] = []
    batchable: list[dict] = []
    singles: list[dict] = []
    for item in pending:
        should_skip, reason = _is_fast_path_keep_origin_item(item)
        if should_skip:
            immediate_results.append(_fast_path_keep_origin_result(item, reason))
            continue
        if _is_low_risk_batchable_item(item, translation_context=translation_context):
            tagged_item = dict(item)
            tagged_item["_batched_plain_candidate"] = True
            batchable.append(tagged_item)
        else:
            singles.append(item)

    batches: list[list[dict]] = []
    if batchable:
        batches.extend(chunked(batchable, effective_batch_size))
    for item in singles:
        batches.append([item])
    return batches, immediate_results


def _is_batched_fast_batch(batch: list[dict]) -> bool:
    return bool(batch) and (
        len(batch) > 1 or any(item.get("_batched_plain_candidate") for item in batch)
    )


def _is_single_slow_batch(batch: list[dict]) -> bool:
    if len(batch) != 1:
        return False
    item = batch[0]
    return bool(item.get("_heavy_formula_split_applied"))


def _classify_translation_batches(
    batches: list[list[dict]],
) -> tuple[list[list[dict]], list[list[dict]], list[list[dict]]]:
    batched_fast_batches: list[list[dict]] = []
    single_fast_batches: list[list[dict]] = []
    single_slow_batches: list[list[dict]] = []
    for batch in batches:
        if _is_batched_fast_batch(batch):
            batched_fast_batches.append(batch)
        elif _is_single_slow_batch(batch):
            single_slow_batches.append(batch)
        else:
            single_fast_batches.append(batch)
    return batched_fast_batches, single_fast_batches, single_slow_batches


def _empty_worker_allocation() -> dict[str, int]:
    return {
        "batched_fast": 0,
        "single_fast": 0,
        "single_slow": 0,
    }


def _single_worker_allocation(*, batched_fast_count: int, single_fast_count: int, single_slow_count: int) -> dict[str, int]:
    allocation = _empty_worker_allocation()
    first_queue = next(
        (
            name
            for name, count in (
                ("batched_fast", batched_fast_count),
                ("single_fast", single_fast_count),
                ("single_slow", single_slow_count),
            )
            if count > 0
        ),
        "",
    )
    if first_queue:
        allocation[first_queue] = 1
    return allocation


def _slow_worker_cap(workers: int) -> int:
    if workers <= 8:
        return 1
    if workers <= 24:
        return 2
    return min(4, max(2, workers // 8))


def _fast_queue_targets(*, batched_fast_count: int, single_fast_count: int) -> list[tuple[str, int]]:
    return [
        (name, count)
        for name, count in (
            ("batched_fast", batched_fast_count),
            ("single_fast", single_fast_count),
        )
        if count > 0
    ]


def _distribute_extra_workers(remaining_after_floor: int, fast_targets: list[tuple[str, int]]) -> dict[str, int]:
    total_fast_batches = sum(count for _, count in fast_targets)
    if remaining_after_floor <= 0 or total_fast_batches <= 0:
        return {name: 0 for name, _count in fast_targets}
    extras: dict[str, int] = {}
    assigned = 0
    for index, (name, count) in enumerate(fast_targets):
        extra = (
            remaining_after_floor - assigned
            if index == len(fast_targets) - 1
            else (remaining_after_floor * count) // total_fast_batches
        )
        assigned += extra
        extras[name] = extra
    return extras


def _allocate_translation_queue_workers(
    total_workers: int,
    *,
    batched_fast_count: int,
    single_fast_count: int,
    single_slow_count: int,
) -> dict[str, int]:
    workers = max(1, total_workers)
    allocation = _empty_worker_allocation()
    if workers == 1:
        return _single_worker_allocation(
            batched_fast_count=batched_fast_count,
            single_fast_count=single_fast_count,
            single_slow_count=single_slow_count,
        )

    if single_slow_count > 0:
        allocation["single_slow"] = min(single_slow_count, _slow_worker_cap(workers), max(1, workers - 1))

    remaining = workers - allocation["single_slow"]
    fast_targets = _fast_queue_targets(
        batched_fast_count=batched_fast_count,
        single_fast_count=single_fast_count,
    )

    if not fast_targets:
        allocation["single_slow"] = workers
        return allocation
    if len(fast_targets) == 1:
        allocation[fast_targets[0][0]] = remaining
        return allocation

    remaining_after_floor = remaining - len(fast_targets)
    for name, _count in fast_targets:
        allocation[name] = 1
    for name, extra in _distribute_extra_workers(remaining_after_floor, fast_targets).items():
        allocation[name] += extra
    return allocation


__all__ = [
    "chunked",
    "TranslationBatchRunStats",
    "_allocate_translation_queue_workers",
    "_build_translation_batches",
    "_classify_translation_batches",
    "_dedupe_pending_items",
    "_effective_translation_batch_size",
    "_save_flush_interval",
]
