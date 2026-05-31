from __future__ import annotations

from concurrent.futures import Future
import sys
from pathlib import Path
import threading
import time


REPO_SCRIPTS_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_SCRIPTS_ROOT))

from services.translation.services.results.applier import TranslationResultApplier
from services.translation.llm.shared.control_context import build_translation_control_context
from services.translation.llm.shared.tail_retry_queue import TranslationTailItem
from services.translation.workflow import batch_runner


class _FlushState:
    def __init__(self) -> None:
        self.dirty_pages: set[int] = set()
        self.progress: list[tuple[int, set[int], str]] = []
        self.flush_labels: list[str] = []
        self.final_flushed = False
        self.total_batches = 0

    def mark_dirty(self, pages: set[int]) -> None:
        self.dirty_pages.update(pages)

    def record_progress(self, completed: int, touched_pages: set[int], *, substage: str = "translation_batches") -> None:
        self.progress.append((completed, set(touched_pages), substage))

    def flush_if_due(self, _completed: int, *, label: str) -> None:
        self.flush_labels.append(label)

    def final_flush(self) -> None:
        self.final_flushed = True


def _done_future(result=None, exc: Exception | None = None) -> Future:
    future: Future = Future()
    if exc is not None:
        future.set_exception(exc)
    else:
        future.set_result(result)
    return future


def test_parallel_batch_runner_drains_successes_after_one_future_exception(monkeypatch) -> None:
    good_batch = [{"item_id": "a", "page_idx": 0, "source_text": "A"}]
    bad_batch = [{"item_id": "b", "page_idx": 1, "source_text": "B"}]

    def _translate(batch, **_kwargs):
        if batch[0]["item_id"] == "b":
            raise ValueError("broken result parser")
        return {"a": {"decision": "translate", "translated_text": "甲", "final_status": "translated"}}

    monkeypatch.setattr(batch_runner, "translate_batch", _translate)
    payload = [
        {"item_id": "a", "page_idx": 0, "source_text": "A", "translated_text": ""},
        {"item_id": "b", "page_idx": 1, "source_text": "B", "translated_text": ""},
    ]
    flush_state = _FlushState()
    applier = TranslationResultApplier(
        flat_payload=payload,
        item_to_page={"a": 0, "b": 1},
        duplicate_items_by_rep_id={},
        flush_state=flush_state,
        memory_store=None,
    )

    batch_runner.run_translation_batches_parallel(
        batched_fast_batches=[],
        single_fast_batches=[good_batch, bad_batch],
        single_slow_batches=[],
        queue_workers={"batched_fast": 1, "single_fast": 1, "single_slow": 1},
        api_key="sk-test",
        model="deepseek-chat",
        base_url="https://example.test",
        domain_guidance="",
        mode="plain",
        translation_context=None,
        memory_store=None,
        result_applier=applier,
        flush_state=flush_state,
    )

    assert payload[0]["translated_text"] == "甲"
    assert payload[0]["final_status"] == "translated"
    assert payload[1]["final_status"] == "failed"
    assert payload[1]["translation_diagnostics"]["degradation_reason"] == "batch_unhandled_exception"
    assert flush_state.final_flushed is True
    assert flush_state.progress[-1] == (2, {0, 1}, "translation_batches")


def test_parallel_batch_runner_drains_global_transport_tail_retry_queue(monkeypatch) -> None:
    context = build_translation_control_context()
    payload = [
        {"item_id": "a", "page_idx": 0, "source_text": "A", "translated_text": ""},
        {"item_id": "b", "page_idx": 1, "source_text": "B", "translated_text": ""},
    ]
    context.translation_tail_queue.push(
        TranslationTailItem(
            item=payload[1],
            api_key="sk-test",
            model="deepseek-chat",
            base_url="https://example.test",
            request_label="tail",
            context=context,
            diagnostics=None,
            single_item_translator=lambda item, **_kwargs: {
                item["item_id"]: {
                    "decision": "translate",
                    "translated_text": "乙",
                    "final_status": "translated",
                }
            },
            store_cached_batch_fn=lambda *_args, **_kwargs: None,
        )
    )
    monkeypatch.setattr(
        batch_runner,
        "translate_batch",
        lambda batch, **_kwargs: {
            batch[0]["item_id"]: {
                "decision": "translate",
                "translated_text": "甲",
                "final_status": "translated",
            }
        },
    )
    flush_state = _FlushState()
    flush_state.total_batches = 1
    applier = TranslationResultApplier(
        flat_payload=payload,
        item_to_page={"a": 0, "b": 1},
        duplicate_items_by_rep_id={},
        flush_state=flush_state,
        memory_store=None,
    )

    batch_runner.run_translation_batches_parallel(
        batched_fast_batches=[],
        single_fast_batches=[[payload[0]]],
        single_slow_batches=[],
        queue_workers={"batched_fast": 1, "single_fast": 1, "single_slow": 1},
        api_key="sk-test",
        model="deepseek-chat",
        base_url="https://example.test",
        domain_guidance="",
        mode="plain",
        translation_context=context,
        memory_store=None,
        result_applier=applier,
        flush_state=flush_state,
    )

    assert payload[0]["translated_text"] == "甲"
    assert payload[1]["translated_text"] == "乙"
    assert len(context.translation_tail_queue) == 0
    assert flush_state.total_batches == 2
    assert flush_state.progress[-1] == (2, {1}, "translation_tail_retry")


def test_parallel_batch_runner_defers_transport_tail_retry_until_main_batches_finish_by_default(monkeypatch) -> None:
    monkeypatch.setenv("RETAIN_TRANSLATION_EARLY_TAIL_RETRY", "0")
    context = build_translation_control_context()
    monkeypatch.setattr(batch_runner, "EARLY_TAIL_RETRY_DRAIN_INTERVAL", 1)
    batches = [[{"item_id": f"i{index}", "page_idx": index, "source_text": str(index)}] for index in range(3)]
    payload = [
        {"item_id": f"i{index}", "page_idx": index, "source_text": str(index), "translated_text": ""}
        for index in range(3)
    ]
    payload.append({"item_id": "tail", "page_idx": 9, "source_text": "tail", "translated_text": ""})
    context.translation_tail_queue.push(
        TranslationTailItem(
            item=payload[-1],
            api_key="sk-test",
            model="deepseek-chat",
            base_url="https://example.test",
            request_label="tail",
            context=context,
            diagnostics=None,
            single_item_translator=lambda item, **_kwargs: {
                item["item_id"]: {
                    "decision": "translate",
                    "translated_text": "尾部译文",
                    "final_status": "translated",
                }
            },
            store_cached_batch_fn=lambda *_args, **_kwargs: None,
        )
    )
    completed_main_when_tail_applied: list[int] = []

    def _translate(batch, **_kwargs):
        item_id = batch[0]["item_id"]
        time.sleep(0.01)
        return {item_id: {"decision": "translate", "translated_text": f"译{item_id}", "final_status": "translated"}}

    monkeypatch.setattr(batch_runner, "translate_batch", _translate)
    flush_state = _FlushState()
    flush_state.total_batches = len(batches)
    applier = TranslationResultApplier(
        flat_payload=payload,
        item_to_page={item["item_id"]: item["page_idx"] for item in payload},
        duplicate_items_by_rep_id={},
        flush_state=flush_state,
        memory_store=None,
    )
    original_apply_batch = applier.apply_batch

    def _record_tail_apply(batch, translated, **kwargs):
        if batch and batch[0].get("item_id") == "tail":
            completed_main_when_tail_applied.append(flush_state.progress[-1][0] if flush_state.progress else 0)
        return original_apply_batch(batch, translated, **kwargs)

    applier.apply_batch = _record_tail_apply

    batch_runner.run_translation_batches_parallel(
        batched_fast_batches=[],
        single_fast_batches=batches,
        single_slow_batches=[],
        queue_workers={"batched_fast": 0, "single_fast": 1, "single_slow": 0},
        api_key="sk-test",
        model="deepseek-chat",
        base_url="https://example.test",
        domain_guidance="",
        mode="plain",
        translation_context=context,
        memory_store=None,
        result_applier=applier,
        flush_state=flush_state,
    )

    assert payload[-1]["translated_text"] == "尾部译文"
    assert completed_main_when_tail_applied
    assert completed_main_when_tail_applied[0] == 3
    assert flush_state.progress[-1][0] == 4


def test_parallel_batch_runner_can_drain_transport_tail_retry_before_main_batches_finish(monkeypatch) -> None:
    monkeypatch.setenv("RETAIN_TRANSLATION_EARLY_TAIL_RETRY", "1")
    context = build_translation_control_context()
    monkeypatch.setattr(batch_runner, "EARLY_TAIL_RETRY_DRAIN_INTERVAL", 1)
    batches = [[{"item_id": f"i{index}", "page_idx": index, "source_text": str(index)}] for index in range(3)]
    payload = [
        {"item_id": f"i{index}", "page_idx": index, "source_text": str(index), "translated_text": ""}
        for index in range(3)
    ]
    payload.append({"item_id": "tail", "page_idx": 9, "source_text": "tail", "translated_text": ""})
    context.translation_tail_queue.push(
        TranslationTailItem(
            item=payload[-1],
            api_key="sk-test",
            model="deepseek-chat",
            base_url="https://example.test",
            request_label="tail",
            context=context,
            diagnostics=None,
            single_item_translator=lambda item, **_kwargs: {
                item["item_id"]: {
                    "decision": "translate",
                    "translated_text": "尾部译文",
                    "final_status": "translated",
                }
            },
            store_cached_batch_fn=lambda *_args, **_kwargs: None,
        )
    )
    completed_main_when_tail_applied: list[int] = []

    def _translate(batch, **_kwargs):
        item_id = batch[0]["item_id"]
        time.sleep(0.01)
        return {item_id: {"decision": "translate", "translated_text": f"译{item_id}", "final_status": "translated"}}

    monkeypatch.setattr(batch_runner, "translate_batch", _translate)
    flush_state = _FlushState()
    applier = TranslationResultApplier(
        flat_payload=payload,
        item_to_page={item["item_id"]: item["page_idx"] for item in payload},
        duplicate_items_by_rep_id={},
        flush_state=flush_state,
        memory_store=None,
    )
    original_apply_batch = applier.apply_batch

    def _record_tail_apply(batch, translated, **kwargs):
        if batch and batch[0].get("item_id") == "tail":
            completed_main_when_tail_applied.append(flush_state.progress[-1][0] if flush_state.progress else 0)
        return original_apply_batch(batch, translated, **kwargs)

    applier.apply_batch = _record_tail_apply

    batch_runner.run_translation_batches_parallel(
        batched_fast_batches=[],
        single_fast_batches=batches,
        single_slow_batches=[],
        queue_workers={"batched_fast": 0, "single_fast": 1, "single_slow": 0},
        api_key="sk-test",
        model="deepseek-chat",
        base_url="https://example.test",
        domain_guidance="",
        mode="plain",
        translation_context=context,
        memory_store=None,
        result_applier=applier,
        flush_state=flush_state,
    )

    assert payload[-1]["translated_text"] == "尾部译文"
    assert completed_main_when_tail_applied
    assert completed_main_when_tail_applied[0] < 3
    assert flush_state.progress[-1][0] == 3


def test_transport_tail_retry_workers_scale_with_main_worker_count() -> None:
    assert batch_runner._transport_tail_retry_workers({"batched_fast": 1, "single_fast": 0, "single_slow": 0}) == 1
    assert batch_runner._transport_tail_retry_workers({"batched_fast": 80, "single_fast": 20, "single_slow": 0}) == 50
    assert batch_runner._transport_tail_retry_workers({"batched_fast": 800, "single_fast": 200, "single_slow": 0}) == 128


def test_parallel_batch_runner_only_keeps_worker_count_futures_active(monkeypatch) -> None:
    batches = [[{"item_id": f"i{index}", "page_idx": index, "source_text": str(index)}] for index in range(6)]
    payload = [
        {"item_id": f"i{index}", "page_idx": index, "source_text": str(index), "translated_text": ""}
        for index in range(6)
    ]
    lock = threading.Lock()
    active = 0
    peak_active = 0

    def _translate(batch, **_kwargs):
        nonlocal active, peak_active
        with lock:
            active += 1
            peak_active = max(peak_active, active)
        time.sleep(0.01)
        with lock:
            active -= 1
        item_id = batch[0]["item_id"]
        return {item_id: {"decision": "translate", "translated_text": f"译{item_id}", "final_status": "translated"}}

    monkeypatch.setattr(batch_runner, "translate_batch", _translate)
    flush_state = _FlushState()
    applier = TranslationResultApplier(
        flat_payload=payload,
        item_to_page={item["item_id"]: item["page_idx"] for item in payload},
        duplicate_items_by_rep_id={},
        flush_state=flush_state,
        memory_store=None,
    )

    batch_runner.run_translation_batches_parallel(
        batched_fast_batches=[],
        single_fast_batches=batches,
        single_slow_batches=[],
        queue_workers={"batched_fast": 0, "single_fast": 2, "single_slow": 0},
        api_key="sk-test",
        model="deepseek-chat",
        base_url="https://example.test",
        domain_guidance="",
        mode="plain",
        translation_context=None,
        memory_store=None,
        result_applier=applier,
        flush_state=flush_state,
    )

    assert peak_active <= 2
    assert flush_state.progress[-1][0] == 6


def test_parallel_batch_runner_workers_keep_pulling_when_result_apply_is_slow(monkeypatch) -> None:
    batches = [[{"item_id": f"i{index}", "page_idx": index, "source_text": str(index)}] for index in range(20)]
    payload = [
        {"item_id": f"i{index}", "page_idx": index, "source_text": str(index), "translated_text": ""}
        for index in range(20)
    ]
    lock = threading.Lock()
    started = 0
    peak_started_before_apply = 0
    apply_count = 0

    def _translate(batch, **_kwargs):
        nonlocal started, peak_started_before_apply
        with lock:
            started += 1
            peak_started_before_apply = max(peak_started_before_apply, started - apply_count)
        time.sleep(0.002)
        item_id = batch[0]["item_id"]
        return {item_id: {"decision": "translate", "translated_text": f"译{item_id}", "final_status": "translated"}}

    monkeypatch.setattr(batch_runner, "translate_batch", _translate)
    flush_state = _FlushState()
    applier = TranslationResultApplier(
        flat_payload=payload,
        item_to_page={item["item_id"]: item["page_idx"] for item in payload},
        duplicate_items_by_rep_id={},
        flush_state=flush_state,
        memory_store=None,
    )
    original_apply_batches = applier.apply_batches

    def _slow_apply_batches(*args, **kwargs):
        nonlocal apply_count
        time.sleep(0.01)
        result = original_apply_batches(*args, **kwargs)
        with lock:
            apply_count += 1
        return result

    applier.apply_batches = _slow_apply_batches

    batch_runner.run_translation_batches_parallel(
        batched_fast_batches=[],
        single_fast_batches=batches,
        single_slow_batches=[],
        queue_workers={"batched_fast": 0, "single_fast": 4, "single_slow": 0},
        api_key="sk-test",
        model="deepseek-chat",
        base_url="https://example.test",
        domain_guidance="",
        mode="plain",
        translation_context=None,
        memory_store=None,
        result_applier=applier,
        flush_state=flush_state,
    )

    assert flush_state.progress[-1][0] == 20
    assert peak_started_before_apply > 4


def test_parallel_batch_runner_fast_workers_share_batched_and_single_tail(monkeypatch) -> None:
    batched = [[{"item_id": f"b{index}", "page_idx": index, "source_text": str(index)}] for index in range(2)]
    singles = [[{"item_id": f"s{index}", "page_idx": index + 10, "source_text": str(index)}] for index in range(12)]
    payload = [
        {"item_id": f"b{index}", "page_idx": index, "source_text": str(index), "translated_text": ""}
        for index in range(2)
    ]
    payload.extend(
        {"item_id": f"s{index}", "page_idx": index + 10, "source_text": str(index), "translated_text": ""}
        for index in range(12)
    )
    lock = threading.Lock()
    active = 0
    peak_active = 0

    def _translate(batch, **_kwargs):
        nonlocal active, peak_active
        with lock:
            active += 1
            peak_active = max(peak_active, active)
        time.sleep(0.01)
        with lock:
            active -= 1
        item_id = batch[0]["item_id"]
        return {item_id: {"decision": "translate", "translated_text": f"译{item_id}", "final_status": "translated"}}

    monkeypatch.setattr(batch_runner, "translate_batch", _translate)
    flush_state = _FlushState()
    applier = TranslationResultApplier(
        flat_payload=payload,
        item_to_page={item["item_id"]: item["page_idx"] for item in payload},
        duplicate_items_by_rep_id={},
        flush_state=flush_state,
        memory_store=None,
    )

    batch_runner.run_translation_batches_parallel(
        batched_fast_batches=batched,
        single_fast_batches=singles,
        single_slow_batches=[],
        queue_workers={"batched_fast": 10, "single_fast": 2, "single_slow": 0},
        api_key="sk-test",
        model="deepseek-chat",
        base_url="https://example.test",
        domain_guidance="",
        mode="plain",
        translation_context=None,
        memory_store=None,
        result_applier=applier,
        flush_state=flush_state,
    )

    assert flush_state.progress[-1][0] == 14
    assert peak_active > 2


def test_parallel_batch_runner_keeps_single_fast_workers_separate_from_batched_fast(monkeypatch) -> None:
    batched = [[{"item_id": f"b{index}", "page_idx": index, "source_text": str(index)}] for index in range(8)]
    singles = [[{"item_id": "s0", "page_idx": 20, "source_text": "single"}]]
    payload = [
        {"item_id": f"b{index}", "page_idx": index, "source_text": str(index), "translated_text": ""}
        for index in range(8)
    ]
    payload.append({"item_id": "s0", "page_idx": 20, "source_text": "single", "translated_text": ""})
    started: list[str] = []
    lock = threading.Lock()

    def _translate(batch, **_kwargs):
        item_id = batch[0]["item_id"]
        with lock:
            started.append(item_id)
        if item_id.startswith("b"):
            time.sleep(0.03)
        return {item_id: {"decision": "translate", "translated_text": f"译{item_id}", "final_status": "translated"}}

    monkeypatch.setattr(batch_runner, "translate_batch", _translate)
    flush_state = _FlushState()
    applier = TranslationResultApplier(
        flat_payload=payload,
        item_to_page={item["item_id"]: item["page_idx"] for item in payload},
        duplicate_items_by_rep_id={},
        flush_state=flush_state,
        memory_store=None,
    )

    batch_runner.run_translation_batches_parallel(
        batched_fast_batches=batched,
        single_fast_batches=singles,
        single_slow_batches=[],
        queue_workers={"batched_fast": 1, "single_fast": 1, "single_slow": 0},
        api_key="sk-test",
        model="deepseek-chat",
        base_url="https://example.test",
        domain_guidance="",
        mode="plain",
        translation_context=None,
        memory_store=None,
        result_applier=applier,
        flush_state=flush_state,
    )

    assert "s0" in started[:3]
    assert payload[-1]["translated_text"] == "译s0"
