from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from services.translation.llm.shared.control_context import TranslationControlContext
from services.translation.llm.shared.orchestration import translate_batch
from services.translation.payload import apply_translated_text_map
from services.translation.payload import pending_translation_items
from services.translation.payload.parts.common import GROUP_ITEM_PREFIX

from runtime.pipeline.book_translation_executor import _keep_origin_results_for_transport_batch
from runtime.pipeline.book_translation_executor import _submit_parallel_translation_batches as _submit_parallel_translation_batches_impl
from runtime.pipeline.book_translation_executor import _translate_batch_or_keep_origin as _translate_batch_or_keep_origin_impl
from runtime.pipeline.book_translation_flush import TranslationFlushState
from runtime.pipeline.book_translation_plan import _allocate_translation_queue_workers
from runtime.pipeline.book_translation_plan import _build_translation_batches
from runtime.pipeline.book_translation_plan import _classify_translation_batches
from runtime.pipeline.book_translation_plan import _dedupe_pending_items
from runtime.pipeline.book_translation_plan import _effective_translation_batch_size
from runtime.pipeline.book_translation_plan import _save_flush_interval
from runtime.pipeline.book_translation_plan import TranslationBatchRunStats


def _clone_result_for_item(payload: dict[str, str], *, item: dict) -> dict[str, str]:
    cloned = dict(payload)
    diagnostics = dict(cloned.get("translation_diagnostics") or {})
    if diagnostics:
        diagnostics["item_id"] = item.get("item_id", "")
        diagnostics["page_idx"] = item.get("page_idx")
        cloned["translation_diagnostics"] = diagnostics
    return cloned


def _expand_duplicate_results(
    translated: dict[str, dict[str, str]],
    *,
    duplicate_items_by_rep_id: dict[str, list[dict]],
) -> dict[str, dict[str, str]]:
    if not duplicate_items_by_rep_id:
        return translated
    expanded = dict(translated)
    for rep_id, duplicate_items in duplicate_items_by_rep_id.items():
        rep_payload = translated.get(rep_id)
        if not rep_payload:
            continue
        for duplicate_item in duplicate_items:
            expanded[str(duplicate_item.get("item_id", "") or "")] = _clone_result_for_item(
                rep_payload,
                item=duplicate_item,
            )
    return expanded


def _current_payload_page_indexes(flat_payload: list[dict], fallback_item_to_page: dict[str, int]) -> tuple[dict[str, int], dict[str, set[int]]]:
    item_to_page: dict[str, int] = dict(fallback_item_to_page)
    unit_to_pages: dict[str, set[int]] = {}
    for item in flat_payload:
        item_id = str(item.get("item_id", "") or "")
        page_idx = item.get("page_idx")
        if page_idx is None:
            page_idx = fallback_item_to_page.get(item_id)
        if page_idx is None:
            continue
        item_to_page[item_id] = int(page_idx)
        unit_id = str(item.get("translation_unit_id") or item_id or "")
        if unit_id:
            unit_to_pages.setdefault(unit_id, set()).add(int(page_idx))
    return item_to_page, unit_to_pages


def touched_pages_for_batch(
    translated: dict[str, str],
    flat_payload: list[dict],
    fallback_item_to_page: dict[str, int],
) -> set[int]:
    item_to_page, unit_to_pages = _current_payload_page_indexes(flat_payload, fallback_item_to_page)
    touched_pages: set[int] = set()
    for item_id in translated:
        if item_id.startswith(GROUP_ITEM_PREFIX):
            touched_pages.update(unit_to_pages.get(item_id, set()))
        elif item_id in item_to_page:
            touched_pages.add(item_to_page[item_id])
    return touched_pages


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
) -> dict[str, dict[str, str]]:
    return _translate_batch_or_keep_origin_impl(
        batch,
        api_key=api_key,
        model=model,
        base_url=base_url,
        request_label=request_label,
        domain_guidance=domain_guidance,
        mode=mode,
        context=context,
        translate_fn=translate_batch,
    )


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
) -> dict[object, tuple[str, list[dict]]]:
    return _submit_parallel_translation_batches_impl(
        batches,
        worker_count=worker_count,
        queue_name=queue_name,
        api_key=api_key,
        model=model,
        base_url=base_url,
        domain_guidance=domain_guidance,
        mode=mode,
        translation_context=translation_context,
        executors=executors,
        translate_fn=translate_batch,
    )


def translate_pending_units(
    *,
    page_payloads: dict[int, list[dict]],
    translation_paths: dict[int, Path],
    batch_size: int,
    workers: int,
    api_key: str,
    model: str,
    base_url: str,
    domain_guidance: str = "",
    mode: str = "fast",
    translation_context: TranslationControlContext | None = None,
    progress_callback: Callable[[int, int, set[int]], None] | None = None,
) -> dict[str, int]:
    flat_payload: list[dict] = []
    item_to_page: dict[str, int] = {}
    for page_idx in sorted(page_payloads):
        for item in page_payloads[page_idx]:
            flat_payload.append(item)
            item_to_page[item.get("item_id", "")] = page_idx

    pending = pending_translation_items(flat_payload)
    pending, duplicate_items_by_rep_id = _dedupe_pending_items(pending)
    effective_batch_size = _effective_translation_batch_size(
        batch_size=batch_size,
        model=model,
        base_url=base_url,
        translation_context=translation_context,
    )
    batches, immediate_results = _build_translation_batches(
        pending,
        effective_batch_size=effective_batch_size,
        translation_context=translation_context,
    )
    batched_fast_batches, single_fast_batches, single_slow_batches = _classify_translation_batches(batches)
    total_batches = len(batches)
    flush_interval = _save_flush_interval(workers=workers, total_batches=total_batches)
    queue_workers = _allocate_translation_queue_workers(
        workers,
        batched_fast_count=len(batched_fast_batches),
        single_fast_count=len(single_fast_batches),
        single_slow_count=len(single_slow_batches),
    )
    run_stats = TranslationBatchRunStats(
        pending_items=len(pending),
        total_batches=total_batches,
        effective_batch_size=effective_batch_size,
        flush_interval=flush_interval,
        effective_workers=max(1, workers),
        batched_fast_batches=len(batched_fast_batches),
        single_fast_batches=len(single_fast_batches),
        single_slow_batches=len(single_slow_batches),
    )
    print(
        f"book: pending items={len(pending)} batches={total_batches} workers={max(1, workers)} "
        f"mode={mode} effective_batch_size={effective_batch_size}",
        flush=True,
    )
    if immediate_results:
        print(f"book: fast-path keep_origin items={len(immediate_results)}", flush=True)
    duplicate_count = sum(len(items) for items in duplicate_items_by_rep_id.values())
    if duplicate_count:
        print(f"book: deduped duplicate items={duplicate_count}", flush=True)
    if total_batches:
        print(f"book: save flush interval={flush_interval} batches", flush=True)
        print(
            "book: queue split "
            f"batched_fast={len(batched_fast_batches)} "
            f"single_fast={len(single_fast_batches)} "
            f"single_slow={len(single_slow_batches)} "
            f"workers(batched_fast={queue_workers['batched_fast']}, "
            f"single_fast={queue_workers['single_fast']}, "
            f"single_slow={queue_workers['single_slow']})",
            flush=True,
        )
    flush_state = TranslationFlushState(
        page_payloads=page_payloads,
        translation_paths=translation_paths,
        flush_interval=flush_interval,
        total_batches=total_batches,
        progress_callback=progress_callback,
    )
    for immediate in immediate_results:
        immediate = _expand_duplicate_results(immediate, duplicate_items_by_rep_id=duplicate_items_by_rep_id)
        apply_translated_text_map(flat_payload, immediate)
        flush_state.mark_dirty(touched_pages_for_batch(immediate, flat_payload, item_to_page))
    if immediate_results and not batches:
        flush_state.flush(label="final flush for fast-path items")
    if workers <= 1:
        for index, batch in enumerate(batches, start=1):
            batch_label = f"book: batch {index}/{total_batches}"
            translated = _translate_batch_or_keep_origin(
                batch,
                api_key=api_key,
                model=model,
                base_url=base_url,
                request_label=batch_label,
                domain_guidance=domain_guidance,
                mode=mode,
                context=translation_context,
            )
            translated = _expand_duplicate_results(translated, duplicate_items_by_rep_id=duplicate_items_by_rep_id)
            apply_translated_text_map(flat_payload, translated)
            touched_pages = touched_pages_for_batch(translated, flat_payload, item_to_page)
            flush_state.mark_dirty(touched_pages)
            flush_state.record_progress(index, touched_pages)
            flush_state.flush_if_due(index, label=f"flushed after batch {index}/{total_batches}")
        flush_state.final_flush()
        return run_stats.as_dict()

    executors: list[ThreadPoolExecutor] = []
    futures: dict[object, tuple[str, list[dict]]] = {}
    futures.update(
        _submit_parallel_translation_batches(
            batched_fast_batches,
            worker_count=queue_workers["batched_fast"],
            queue_name="batched_fast",
            api_key=api_key,
            model=model,
            base_url=base_url,
            domain_guidance=domain_guidance,
            mode=mode,
            translation_context=translation_context,
            executors=executors,
        )
    )
    futures.update(
        _submit_parallel_translation_batches(
            single_fast_batches,
            worker_count=queue_workers["single_fast"],
            queue_name="single_fast",
            api_key=api_key,
            model=model,
            base_url=base_url,
            domain_guidance=domain_guidance,
            mode=mode,
            translation_context=translation_context,
            executors=executors,
        )
    )
    futures.update(
        _submit_parallel_translation_batches(
            single_slow_batches,
            worker_count=queue_workers["single_slow"],
            queue_name="single_slow",
            api_key=api_key,
            model=model,
            base_url=base_url,
            domain_guidance=domain_guidance,
            mode=mode,
            translation_context=translation_context,
            executors=executors,
        )
    )
    completed = 0
    try:
        for future in as_completed(futures):
            translated = future.result()
            translated = _expand_duplicate_results(translated, duplicate_items_by_rep_id=duplicate_items_by_rep_id)
            apply_translated_text_map(flat_payload, translated)
            completed += 1
            touched_pages = touched_pages_for_batch(translated, flat_payload, item_to_page)
            flush_state.mark_dirty(touched_pages)
            flush_state.record_progress(completed, touched_pages)
            flush_state.flush_if_due(completed, label=f"flushed after completed batch {completed}/{total_batches}")
            print(f"book: completed batch {completed}/{total_batches}", flush=True)
    finally:
        for executor in executors:
            executor.shutdown(wait=True, cancel_futures=False)
    flush_state.final_flush()
    return run_stats.as_dict()
