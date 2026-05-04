from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from services.translation.llm.result_payload import result_entry
from services.translation.llm.shared.control_context import TranslationControlContext
from services.translation.llm.shared.orchestration import translate_batch as default_translate_batch
from services.translation.llm.shared.provider_runtime import is_transport_error

TranslateBatchFn = Callable[..., dict[str, dict[str, str]]]


def _keep_origin_results_for_transport_batch(
    batch: list[dict],
    *,
    degradation_reason: str = "batch_transport_timeout_budget_exceeded",
) -> dict[str, dict[str, str]]:
    degraded: dict[str, dict[str, str]] = {}
    for item in batch:
        payload = result_entry("keep_origin", "")
        payload["error_taxonomy"] = "transport"
        payload["translation_diagnostics"] = {
            "item_id": item.get("item_id", ""),
            "page_idx": item.get("page_idx"),
            "route_path": ["block_level", "batched_plain", "keep_origin"],
            "output_mode_path": [],
            "error_trace": [{"type": "transport", "code": "BATCH_TRANSPORT_ERROR"}],
            "fallback_to": "keep_origin",
            "degradation_reason": degradation_reason,
            "final_status": "kept_origin",
        }
        degraded[str(item.get("item_id", "") or "")] = payload
    return degraded


def _translate_batch_or_keep_origin(
    batch: list[dict],
    *,
    api_key: str,
    model: str,
    base_url: str,
    request_label: str,
    domain_guidance: str,
    mode: str,
    context: TranslationControlContext | None,
    translate_fn: TranslateBatchFn = default_translate_batch,
) -> dict[str, dict[str, str]]:
    try:
        return translate_fn(
            batch,
            api_key=api_key,
            model=model,
            base_url=base_url,
            request_label=request_label,
            domain_guidance=domain_guidance,
            mode=mode,
            context=context,
        )
    except Exception as exc:
        if not is_transport_error(exc):
            raise
        if request_label:
            print(
                f"{request_label}: transport failure, degrade batch to keep_origin: {type(exc).__name__}: {exc}",
                flush=True,
            )
        return _keep_origin_results_for_transport_batch(batch)


def _submit_parallel_translation_batches(
    batches: list[list[dict]],
    *,
    worker_count: int,
    queue_name: str,
    api_key: str,
    model: str,
    base_url: str,
    domain_guidance: str,
    mode: str,
    translation_context: TranslationControlContext | None,
    executors: list[ThreadPoolExecutor],
    translate_fn: TranslateBatchFn = default_translate_batch,
) -> dict[object, tuple[str, list[dict]]]:
    if not batches:
        return {}
    executor = ThreadPoolExecutor(max_workers=max(1, worker_count))
    executors.append(executor)
    return {
        executor.submit(
            _translate_batch_or_keep_origin,
            batch,
            api_key=api_key,
            model=model,
            base_url=base_url,
            request_label=f"book: {queue_name} batch {index}/{len(batches)}",
            domain_guidance=domain_guidance,
            mode=mode,
            context=translation_context,
            translate_fn=translate_fn,
        ): (queue_name, batch)
        for index, batch in enumerate(batches, start=1)
    }


__all__ = [
    "_keep_origin_results_for_transport_batch",
    "_submit_parallel_translation_batches",
    "_translate_batch_or_keep_origin",
]
