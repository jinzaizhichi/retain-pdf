from __future__ import annotations

import os
import time
from pathlib import Path

from services.translation.llm.shared.provider_runtime import DEFAULT_BASE_URL
from services.translation.llm.shared.provider_runtime import DEFAULT_MODEL
from services.translation.llm.shared.provider_runtime import get_api_key
from services.translation.llm.shared.provider_runtime import normalize_base_url
from services.translation.llm.shared.provider_runtime import request_chat_content
from services.translation.artifacts import blocking_untranslated_items
from services.translation.services.agents import AgentRunContext
from services.translation.services.agents import TranslationAgentCoordinator
from services.translation.services.agents import TranslationAgentRuntime
from services.translation.services.agents import run_agent_repair_pipeline
from services.translation.services.finalization import recover_blocking_untranslated_items
from services.translation.workflow.batching.pending_units import translate_pending_units
from services.translation.workflow.pages import save_pages
from services.translation.workflow.page_policies import apply_page_policies
from services.translation.workflow.page_policies import finalize_page_payloads
from services.translation.workflow.page_policies import review_and_apply_continuations
from services.pipeline_shared.events import emit_stage_progress
from services.pipeline_shared.events import emit_stage_transition
from services.translation.artifacts import TranslationRunDiagnostics
from services.translation.llm.shared.control_context import TranslationControlContext
from services.translation.services.policy import TranslationPolicyConfig
from services.translation.services.postprocess import GarbledReconstructionRuntime
from services.translation.services.postprocess import reconstruct_garbled_page_payloads


def format_translation_progress_message(current: int, total: int, touched_pages: set[int], *, substage: str = "translation_batches") -> str:
    if touched_pages:
        sorted_pages = sorted(page_idx + 1 for page_idx in touched_pages)
        if len(sorted_pages) == 1:
            page_suffix = f"（最近页: {sorted_pages[0]}）"
        else:
            preview = ",".join(str(page) for page in sorted_pages[:4])
            if len(sorted_pages) > 4:
                preview = f"{preview}..."
            page_suffix = f"（最近页: {preview}）"
    else:
        page_suffix = ""
    if substage == "translation_tail_retry":
        return f"正在处理翻译重试队列，第 {current}/{total} 项{page_suffix}"
    return f"已完成第 {current}/{total} 批翻译{page_suffix}"


def run_initial_continuation_pass(
    *,
    page_payloads: dict[int, list[dict]],
    translation_paths: dict[int, Path],
) -> None:
    stage_started = time.perf_counter()
    finalize_page_payloads(
        page_payloads=page_payloads,
        translation_paths=translation_paths,
    )
    emit_stage_progress(
        stage="continuation_review",
        substage="continuation_review",
        message="初始连续段整理完成",
        elapsed_ms=int((time.perf_counter() - stage_started) * 1000),
        payload={"page_count": len(page_payloads)},
    )
    print(f"book: initial continuation pass in {time.perf_counter() - stage_started:.2f}s", flush=True)


def run_continuation_review(
    *,
    page_payloads: dict[int, list[dict]],
    translation_paths: dict[int, Path],
    api_key: str,
    model: str,
    base_url: str,
    workers: int,
    run_diagnostics: TranslationRunDiagnostics | None,
) -> None:
    review_started = time.perf_counter()
    emit_stage_transition(
        stage="continuation_review",
        substage="continuation_review",
        message="开始复核跨栏/跨页连续段",
        progress_current=0,
        progress_total=len(page_payloads),
    )
    if run_diagnostics is not None:
        run_diagnostics.mark_phase_start("continuation_review")
    review_and_apply_continuations(
        page_payloads=page_payloads,
        translation_paths=translation_paths,
        api_key=api_key,
        model=model,
        base_url=base_url,
        workers=workers,
        request_chat_content_fn=request_chat_content,
        progress_callback=lambda current, total: emit_stage_progress(
            stage="continuation_review",
            substage="continuation_review",
            message=f"正在判断跨栏/跨页连续段，第 {current}/{total} 批",
            progress_current=current,
            progress_total=total,
            payload={"progress_unit": "page"},
        ),
    )
    if run_diagnostics is not None:
        run_diagnostics.mark_phase_end("continuation_review")
    emit_stage_progress(
        stage="continuation_review",
        substage="continuation_review",
        message="跨栏/跨页连续段复核完成",
        progress_current=len(page_payloads),
        progress_total=len(page_payloads),
        elapsed_ms=int((time.perf_counter() - review_started) * 1000),
    )
    print(f"book: continuation review in {time.perf_counter() - review_started:.2f}s", flush=True)


def run_page_policy_stage(
    *,
    page_payloads: dict[int, list[dict]],
    mode: str,
    classify_batch_size: int,
    workers: int,
    api_key: str,
    model: str,
    base_url: str,
    skip_title_translation: bool,
    sci_cutoff_page_idx: int | None,
    sci_cutoff_block_idx: int | None,
    policy_config: TranslationPolicyConfig | None,
    run_diagnostics: TranslationRunDiagnostics | None,
) -> int:
    policy_started = time.perf_counter()
    if run_diagnostics is not None:
        run_diagnostics.mark_phase_start("page_policies")
    emit_stage_transition(
        stage="page_policies",
        substage="page_policies",
        message="开始执行页面策略和块分类",
        progress_current=0,
        progress_total=len(page_payloads),
    )
    print("book: page policies start", flush=True)
    print(f"book: page policies mode={mode} total_pages={len(page_payloads)}", flush=True)
    classified_items = apply_page_policies(
        page_payloads=page_payloads,
        mode=mode,
        classify_batch_size=max(1, classify_batch_size),
        workers=max(1, workers),
        api_key=api_key,
        model=model,
        base_url=base_url,
        skip_title_translation=skip_title_translation,
        sci_cutoff_page_idx=sci_cutoff_page_idx,
        sci_cutoff_block_idx=sci_cutoff_block_idx,
        policy_config=policy_config,
        request_chat_content_fn=request_chat_content,
        progress_callback=lambda current, total, page_idx, page_classified: emit_stage_progress(
            stage="page_policies",
            substage="page_policies",
            message=f"正在执行页面策略，第 {current}/{total} 页",
            progress_current=current,
            progress_total=total,
            payload={
                "page_idx": page_idx,
                "page_number": page_idx + 1,
                "page_classified_items": page_classified,
            },
        ),
    )
    if classified_items:
        print(f"book: classified {classified_items} items", flush=True)
    if run_diagnostics is not None:
        run_diagnostics.mark_phase_end("page_policies")
    emit_stage_progress(
        stage="page_policies",
        substage="page_policies",
        message="页面策略和块分类完成",
        progress_current=len(page_payloads),
        progress_total=len(page_payloads),
        elapsed_ms=int((time.perf_counter() - policy_started) * 1000),
        payload={"classified_items": classified_items},
    )
    print(f"book: page policies in {time.perf_counter() - policy_started:.2f}s", flush=True)
    return int(classified_items)


def run_translation_batch_stage(
    *,
    page_payloads: dict[int, list[dict]],
    translation_paths: dict[int, Path],
    batch_size: int,
    workers: int,
    api_key: str,
    model: str,
    base_url: str,
    domain_guidance: str,
    mode: str,
    translation_context: TranslationControlContext | None,
    run_diagnostics: TranslationRunDiagnostics | None,
    flush_callback=None,
) -> dict:
    translate_started = time.perf_counter()
    if run_diagnostics is not None:
        run_diagnostics.mark_phase_start("translation_batches")
    emit_stage_transition(
        stage="translating",
        substage="translation_batches",
        message="开始批量翻译",
    )
    batch_summary = translate_pending_units(
        page_payloads=page_payloads,
        translation_paths=translation_paths,
        batch_size=batch_size,
        workers=max(1, workers),
        api_key=api_key,
        model=model,
        base_url=base_url,
        domain_guidance=domain_guidance,
        mode=mode,
        translation_context=translation_context,
        flush_callback=flush_callback,
        progress_callback=lambda current, total, touched_pages, substage: emit_stage_progress(
            stage="translating",
            substage=substage,
            message=format_translation_progress_message(current, total, touched_pages, substage=substage),
            progress_current=current,
            progress_total=total,
            payload={
                "substage": substage,
                "touched_page_indexes": sorted(touched_pages),
                "touched_page_numbers": [page_idx + 1 for page_idx in sorted(touched_pages)],
            },
        ),
    )
    if run_diagnostics is not None:
        run_diagnostics.mark_phase_end("translation_batches")
        run_diagnostics.set_effective_translation_batch_size(batch_summary["effective_batch_size"])
        run_diagnostics.set_workload(
            pending_items=batch_summary["pending_items"],
            total_batches=batch_summary["total_batches"],
        )
        run_diagnostics.set_translation_queue_workers(
            batched_fast_workers=batch_summary.get("batched_fast_workers", 0),
            single_fast_workers=batch_summary.get("single_fast_workers", 0),
            single_slow_workers=batch_summary.get("single_slow_workers", 0),
            slow_worker_limit=batch_summary.get("slow_worker_limit", 0),
        )
        run_diagnostics.set_translation_result_stats(
            applied_batches=batch_summary.get("total_batches", 0),
            apply_elapsed_ms=batch_summary.get("apply_elapsed_ms", 0),
            max_result_drain_batch=batch_summary.get("max_result_drain_batch", 0),
        )
    emit_stage_progress(
        stage="translating",
        substage="translation_batches",
        message="翻译批次完成",
        progress_current=batch_summary["total_batches"],
        progress_total=batch_summary["total_batches"],
        elapsed_ms=int((time.perf_counter() - translate_started) * 1000),
        payload={
            "substage": "translation_batches",
            "pending_items": batch_summary["pending_items"],
            "effective_batch_size": batch_summary["effective_batch_size"],
            "fast_queue_workers": batch_summary.get("fast_queue_workers", 0),
            "apply_elapsed_ms": batch_summary.get("apply_elapsed_ms", 0),
            "max_result_drain_batch": batch_summary.get("max_result_drain_batch", 0),
        },
    )
    print(f"book: translation batches in {time.perf_counter() - translate_started:.2f}s", flush=True)
    return batch_summary


def run_garbled_reconstruction_stage(
    *,
    page_payloads: dict[int, list[dict]],
    translation_paths: dict[int, Path],
    api_key: str,
    model: str,
    base_url: str,
    workers: int,
    run_diagnostics: TranslationRunDiagnostics | None,
) -> None:
    reconstruct_started = time.perf_counter()
    if run_diagnostics is not None:
        run_diagnostics.mark_phase_start("garbled_reconstruction")
    emit_stage_transition(
        stage="garbled_repair",
        substage="garbled_repair",
        message="开始修复乱码候选段",
        progress_current=0,
        progress_total=len(page_payloads),
    )
    summary = reconstruct_garbled_page_payloads(
        page_payloads,
        api_key=api_key,
        model=model,
        base_url=base_url,
        workers=workers,
        runtime=_garbled_reconstruction_runtime(
            api_key=api_key,
            model=model,
            base_url=base_url,
        ),
        progress_callback=lambda current, total, dirty_pages: emit_stage_progress(
            stage="garbled_repair",
            substage="garbled_repair",
            message=f"正在修复乱码候选段，第 {current}/{total} 项",
            progress_current=current,
            progress_total=total,
            payload={
                "progress_unit": "page",
                "dirty_pages": sorted(dirty_pages),
            },
        ),
    )
    if run_diagnostics is not None:
        run_diagnostics.mark_phase_end("garbled_reconstruction")
    reconstructed_items = int(summary["garbled_reconstructed"])
    garbled_candidates = int(summary["garbled_candidates"])
    dirty_pages = {int(page_idx) for page_idx in summary.get("dirty_pages", [])}
    if dirty_pages:
        save_pages(page_payloads, translation_paths, dirty_pages)
    emit_stage_progress(
        stage="garbled_repair",
        substage="garbled_repair",
        message="乱码候选段修复完成",
        progress_current=len(page_payloads),
        progress_total=len(page_payloads),
        elapsed_ms=int((time.perf_counter() - reconstruct_started) * 1000),
        payload={
            "progress_unit": "page",
            "garbled_candidates": garbled_candidates,
            "garbled_reconstructed": reconstructed_items,
            "dirty_pages": sorted(dirty_pages),
        },
    )
    print(
        f"book: garbled reconstruction candidates={garbled_candidates} reconstructed={reconstructed_items} "
        f"in {time.perf_counter() - reconstruct_started:.2f}s",
        flush=True,
    )


def _is_deepseek_provider(*, model: str, base_url: str) -> bool:
    normalized_base = normalize_base_url(base_url).lower()
    model_text = (model or "").strip().lower()
    return "deepseek" in model_text or "deepseek.com" in normalized_base


def _garbled_reconstruction_runtime(
    *,
    api_key: str,
    model: str,
    base_url: str,
) -> GarbledReconstructionRuntime:
    if _is_deepseek_provider(model=model, base_url=base_url):
        return GarbledReconstructionRuntime(
            api_key=api_key or get_api_key(required=False),
            model=model,
            base_url=base_url,
            provider_reason="job_provider",
            request_chat_content_fn=request_chat_content,
            normalize_base_url_fn=normalize_base_url,
        )

    deepseek_key = get_api_key(required=False)
    if deepseek_key:
        return GarbledReconstructionRuntime(
            api_key=deepseek_key,
            model=DEFAULT_MODEL,
            base_url=DEFAULT_BASE_URL,
            provider_reason="prefer_deepseek_api",
            request_chat_content_fn=request_chat_content,
            normalize_base_url_fn=normalize_base_url,
        )

    return GarbledReconstructionRuntime(
        api_key=api_key,
        model=model,
        base_url=base_url,
        provider_reason="job_provider_fallback",
        request_chat_content_fn=request_chat_content,
        normalize_base_url_fn=normalize_base_url,
    )


def run_agent_repair_stage(
    *,
    page_payloads: dict[int, list[dict]],
    translation_paths: dict[int, Path],
    api_key: str,
    model: str,
    base_url: str,
    translation_context: TranslationControlContext | None,
    run_diagnostics: TranslationRunDiagnostics | None,
) -> dict[str, int]:
    flat_payload: list[dict] = [item for page_idx in sorted(page_payloads) for item in page_payloads[page_idx]]
    blocking_untranslated = blocking_untranslated_items(page_payloads)
    repair_limit = _agent_repair_limit_from_env(
        payload_size=len(flat_payload),
        blocking_untranslated_count=len(blocking_untranslated),
    )
    if repair_limit <= 0:
        return {
            "reviewed_items": 0,
            "candidate_items": 0,
            "repaired_items": 0,
            "skipped_items": 0,
            "failed_items": 0,
        }
    repair_started = time.perf_counter()
    if run_diagnostics is not None:
        run_diagnostics.mark_phase_start("agent_repair")
    emit_stage_transition(
        stage="agent_repair",
        substage="agent_repair",
        message="开始执行翻译结果修复",
        progress_current=0,
        progress_total=repair_limit,
        payload={"blocking_untranslated": len(blocking_untranslated)},
    )
    glossary_entries = list(
        getattr(
            translation_context.scoped_to_source_texts([]) if translation_context is not None else None,
            "glossary_entries",
            [],
        )
        or []
    )
    coordinator = (
        TranslationAgentCoordinator.from_control_context(translation_context)
        if translation_context is not None
        else TranslationAgentCoordinator()
    )
    runtime = TranslationAgentRuntime(
        api_key=api_key,
        context=AgentRunContext(model=model, base_url=base_url),
        request_chat_content_fn=request_chat_content,
    )
    translated_results = {
        str(item.get("item_id", "") or ""): {
            "decision": "translate",
            "translated_text": str(
                item.get("protected_translated_text")
                or item.get("translation_unit_protected_translated_text")
                or item.get("translated_text")
                or ""
            ),
        }
        for item in flat_payload
        if str(item.get("item_id", "") or "")
    }
    summary = run_agent_repair_pipeline(
        payload=flat_payload,
        translated_results=translated_results,
        coordinator=coordinator,
        runtime=runtime,
        glossary_entries=glossary_entries,
        max_items=repair_limit,
        model=model,
        base_url=base_url,
    ).as_dict()
    if summary["repaired_items"] or summary["skipped_items"] or summary["failed_items"]:
        save_pages(page_payloads, translation_paths)
    if run_diagnostics is not None:
        run_diagnostics.mark_phase_end("agent_repair")
    emit_stage_progress(
        stage="agent_repair",
        substage="agent_repair",
        message="翻译结果修复完成",
        progress_current=summary["repaired_items"],
        progress_total=summary["candidate_items"],
        elapsed_ms=int((time.perf_counter() - repair_started) * 1000),
        payload=summary,
    )
    print(
        "book: agent repair "
        f"candidates={summary['candidate_items']} repaired={summary['repaired_items']} "
        f"skipped={summary['skipped_items']} failed={summary['failed_items']} "
        f"in {time.perf_counter() - repair_started:.2f}s",
        flush=True,
    )
    return summary


def run_final_untranslated_recovery_stage(
    *,
    page_payloads: dict[int, list[dict]],
    translation_paths: dict[int, Path],
    api_key: str,
    model: str,
    base_url: str,
    translation_context: TranslationControlContext | None,
    workers: int,
) -> dict[str, int]:
    target_language_name = str(
        getattr(translation_context, "target_language_name", "") if translation_context is not None else ""
    ) or "简体中文"
    blocking_before = len(blocking_untranslated_items(page_payloads))
    if blocking_before <= 0:
        return {
            "blocking_before": 0,
            "attempted_items": 0,
            "recovered_items": 0,
            "dead_letter_items": 0,
            "blocking_after": 0,
        }
    started = time.perf_counter()
    emit_stage_transition(
        stage="final_untranslated_recovery",
        substage="final_untranslated_recovery",
        message="开始最终未翻译收口",
        progress_current=0,
        progress_total=blocking_before,
        payload={"blocking_untranslated": blocking_before},
    )
    summary = recover_blocking_untranslated_items(
        page_payloads,
        api_key=api_key,
        model=model,
        base_url=base_url,
        target_language_name=target_language_name,
        workers=max(1, min(32, int(workers or 1))),
        request_chat_content_fn=request_chat_content,
    ).as_dict()
    save_pages(page_payloads, translation_paths)
    emit_stage_progress(
        stage="final_untranslated_recovery",
        substage="final_untranslated_recovery",
        message="最终未翻译收口完成",
        progress_current=summary["attempted_items"],
        progress_total=blocking_before,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        payload=summary,
    )
    print(
        "book: final untranslated recovery "
        f"before={summary['blocking_before']} attempted={summary['attempted_items']} "
        f"recovered={summary['recovered_items']} dead_letter={summary['dead_letter_items']} "
        f"after={summary['blocking_after']} in {time.perf_counter() - started:.2f}s",
        flush=True,
    )
    return summary


def _agent_repair_limit_from_env(
    *,
    payload_size: int = 0,
    blocking_untranslated_count: int = 0,
) -> int:
    raw = str(os.environ.get("RETAIN_TRANSLATION_AGENT_REPAIR_LIMIT", "") or "").strip()
    if not raw:
        return max(
            8,
            min(256, max(0, int(blocking_untranslated_count)) * 2),
            min(64, max(0, int(payload_size)) // 80),
        )
    try:
        return max(0, int(raw))
    except ValueError:
        return max(8, min(256, max(0, int(blocking_untranslated_count)) * 2))


__all__ = [
    "format_translation_progress_message",
    "run_agent_repair_stage",
    "run_continuation_review",
    "run_garbled_reconstruction_stage",
    "run_initial_continuation_pass",
    "run_final_untranslated_recovery_stage",
    "run_page_policy_stage",
    "run_translation_batch_stage",
]
