from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import requests


REPO_SCRIPTS_ROOT = Path("/home/wxyhgk/tmp/Code/backend/scripts")
sys.path.insert(0, str(REPO_SCRIPTS_ROOT))


from services.translation.workflow.batching.pending_units import _translate_batch_or_keep_origin
from services.translation.llm.shared.orchestration.batched_plain import translate_items_plain_text
from services.translation.llm.shared.control_context import build_translation_control_context
from services.translation.llm.shared.control_context import FallbackPolicy
from services.translation.llm.shared.control_context import EngineProfile
from services.translation.llm.shared.orchestration.transport import DeferredTransportRetry
from services.translation.llm.shared.orchestration.transport import DeferredValidationRetry
from services.translation.services.terms import GlossaryEntry


def _item(item_id: str, text: str, **overrides):
    item = {
        "item_id": item_id,
        "block_type": "text",
        "source_text": text,
        "protected_source_text": text,
        "should_translate": True,
    }
    item.update(overrides)
    return item


def test_translate_batch_wrapper_marks_transport_failure_failed() -> None:
    context = build_translation_control_context()
    batch = [
        _item("a", "This sentence describes antibacterial activity and provides enough body text for translation."),
        _item("b", "This paragraph keeps enough content for translation even when the network request times out."),
    ]
    with mock.patch(
        "services.translation.workflow.batching.pending_units.translate_batch",
        side_effect=requests.ConnectionError("Read timed out"),
    ):
        result = _translate_batch_or_keep_origin(
            batch,
            api_key="sk-test",
            model="deepseek-chat",
            base_url="https://api.deepseek.com/v1",
            request_label="book: batch 1/1",
            domain_guidance="",
            mode="fast",
            context=context,
        )

    assert result["a"]["decision"] == "translate"
    assert result["b"]["decision"] == "translate"
    assert result["a"]["translated_text"] == ""
    assert result["b"]["translated_text"] == ""
    assert result["a"]["final_status"] == "failed"
    assert result["b"]["final_status"] == "failed"
    assert result["a"]["translation_diagnostics"]["degradation_reason"] == "batch_transport_timeout_budget_exceeded"
    assert result["a"]["translation_diagnostics"]["fallback_to"] == "retry_required"
    assert result["a"]["translation_diagnostics"]["route_path"] == ["block_level", "batched_plain", "failed"]


def test_translate_batch_wrapper_appends_relevant_job_memory_to_domain_guidance() -> None:
    captured: dict[str, object] = {}

    class _MemoryStore:
        def summary(self) -> str:
            return "当前文档记忆：术语保持一致。\n- SCF => 自洽场\n- DFTB => 密度泛函紧束缚"

        def summary_for_batch(self, batch) -> str:
            source = "\n".join(str(item.get("source_text") or "") for item in batch)
            if "SCF" in source:
                return "当前块相关文档记忆：术语保持一致。\n- SCF => 自洽场"
            return ""

    def _fake_translate_fn(*_args, **kwargs):
        captured["domain_guidance"] = kwargs["domain_guidance"]
        captured["context"] = kwargs["context"]
        return {"a": {"decision": "translate", "translated_text": "自洽场"}}

    result = _translate_batch_or_keep_origin(
        [_item("a", "SCF")],
        api_key="sk-test",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        request_label="book: batch 1/1",
        domain_guidance="文档领域：量子化学。",
        mode="fast",
        context=build_translation_control_context(),
        memory_store=_MemoryStore(),
        translate_fn=_fake_translate_fn,
    )

    assert result["a"]["translated_text"] == "自洽场"
    assert "文档领域：量子化学。" in captured["domain_guidance"]
    assert "SCF => 自洽场" in captured["domain_guidance"]
    assert "DFTB =>" not in captured["domain_guidance"]
    assert "SCF => 自洽场" in captured["context"].merged_guidance
    assert "DFTB =>" not in captured["context"].merged_guidance


def test_translate_items_plain_text_sends_only_matched_glossary_entries_to_prompt() -> None:
    captured: dict[str, str] = {}
    batch = [
        _item(
            "a",
            "The SCF cycle is converged before evaluating the total energy.",
            _batched_plain_candidate=True,
        ),
        _item(
            "b",
            "Hartree-Fock orbitals provide the initial guess.",
            _batched_plain_candidate=True,
        ),
    ]
    context = build_translation_control_context(
        glossary_entries=[
            GlossaryEntry(source="SCF", target="自洽场", level="preferred"),
            GlossaryEntry(source="DFTB", target="密度泛函紧束缚", level="preferred"),
            GlossaryEntry(source="Hartree-Fock", target="Hartree-Fock", level="preserve", match_mode="case_insensitive"),
        ]
    )

    def _translate_batch_once(batch_arg, **kwargs):
        captured["domain_guidance"] = kwargs["domain_guidance"]
        return {
            item["item_id"]: {
                "decision": "translate",
                "translated_text": "已翻译",
                "final_status": "translated",
            }
            for item in batch_arg
        }

    result = translate_items_plain_text(
        batch,
        api_key="sk-test",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        request_label="test glossary scope",
        context=context,
        diagnostics=None,
        single_item_translator=lambda *_args, **_kwargs: {},
        split_cached_batch_fn=lambda batch_arg, **_kwargs: ({}, batch_arg),
        store_cached_batch_fn=lambda *_args, **_kwargs: None,
        translate_batch_once_fn=_translate_batch_once,
    )

    assert result["a"]["translated_text"] == "已翻译"
    assert '"source": "SCF"' in captured["domain_guidance"]
    assert '"target": "自洽场"' in captured["domain_guidance"]
    assert "DFTB" not in captured["domain_guidance"]
    assert '"source": "Hartree-Fock"' not in captured["domain_guidance"]
    assert result["a"]["translation_diagnostics"]["term_scope"]["glossary_sources"] == ["SCF"]
    assert result["b"]["translation_diagnostics"]["term_scope"]["glossary_sources"] == ["Hartree-Fock"]


def test_batched_plain_main_request_uses_fast_fail_http_attempt_budget() -> None:
    captured: dict[str, int] = {}
    batch = [
        _item(
            "a",
            "This body paragraph is long enough for the batched plain translation path.",
            _batched_plain_candidate=True,
        ),
        _item(
            "b",
            "A second body paragraph keeps this test on the direct batched request path.",
            _batched_plain_candidate=True,
        ),
    ]
    context = build_translation_control_context(
        engine_profile=EngineProfile(
            fallback_policy=FallbackPolicy(main_http_retry_attempts=1, tail_http_retry_attempts=3),
        )
    )

    def _translate_batch_once(batch_arg, **kwargs):
        captured["http_retry_attempts"] = kwargs["http_retry_attempts"]
        return {
            item["item_id"]: {
                "decision": "translate",
                "translated_text": "已翻译",
                "final_status": "translated",
            }
            for item in batch_arg
        }

    result = translate_items_plain_text(
        batch,
        api_key="sk-test",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        request_label="test fast fail",
        context=context,
        diagnostics=None,
        single_item_translator=lambda *_args, **_kwargs: {},
        split_cached_batch_fn=lambda batch_arg, **_kwargs: ({}, batch_arg),
        store_cached_batch_fn=lambda *_args, **_kwargs: None,
        translate_batch_once_fn=_translate_batch_once,
    )

    assert result["a"]["translated_text"] == "已翻译"
    assert result["b"]["translated_text"] == "已翻译"
    assert captured["http_retry_attempts"] == 1


def test_single_batched_plain_candidate_uses_single_item_path_instead_of_tail_queue() -> None:
    batch = [
        _item(
            "a",
            "This body paragraph is long enough for normal single-item translation.",
            _batched_plain_candidate=True,
        )
    ]
    context = build_translation_control_context()
    calls: list[str] = []

    def _single_item_translator(item, **_kwargs):
        calls.append(item["item_id"])
        return {
            item["item_id"]: {
                "decision": "translate",
                "translated_text": "正文已翻译",
                "final_status": "translated",
            }
        }

    result = translate_items_plain_text(
        batch,
        api_key="sk-test",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        request_label="test single batched candidate",
        context=context,
        diagnostics=None,
        single_item_translator=_single_item_translator,
        split_cached_batch_fn=lambda batch_arg, **_kwargs: ({}, batch_arg),
        store_cached_batch_fn=lambda *_args, **_kwargs: None,
        translate_batch_once_fn=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("must not batch")),
    )

    assert result["a"]["translated_text"] == "正文已翻译"
    assert calls == ["a"]
    assert len(context.translation_tail_queue) == 0


def test_failed_batched_plain_request_is_queued_instead_of_retried_inline() -> None:
    batch = [
        _item(
            "a",
            "This body paragraph is long enough for the single-item translation path.",
            _batched_plain_candidate=False,
        ),
        _item(
            "b",
            "A second body paragraph should still finish before tail retry starts.",
            _batched_plain_candidate=False,
        ),
    ]
    context = build_translation_control_context()
    calls: list[str] = []

    def _single_item_translator(item, **kwargs):
        calls.append(f"{item['item_id']}:{kwargs['allow_transport_tail_defer']}")
        if item["item_id"] == "a":
            raise DeferredTransportRetry(item=item, route_path=["block_level"], cause=TimeoutError("timeout"))
        return {
            "b": {
                "decision": "translate",
                "translated_text": "第二段已翻译",
                "final_status": "translated",
            }
        }

    result = translate_items_plain_text(
        batch,
        api_key="sk-test",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        request_label="test tail queue",
        context=context,
        diagnostics=None,
        single_item_translator=_single_item_translator,
        split_cached_batch_fn=lambda batch_arg, **_kwargs: ({}, batch_arg),
        store_cached_batch_fn=lambda *_args, **_kwargs: None,
        translate_batch_once_fn=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("skip batched path")),
    )

    assert result == {}
    assert calls == []
    assert len(context.translation_tail_queue) == 2


def test_validation_failure_from_single_fallback_is_queued_instead_of_retried_inline(monkeypatch) -> None:
    monkeypatch.setenv("RETAIN_TRANSLATION_INLINE_BATCH_FALLBACK", "1")
    batch = [
        _item(
            "a",
            "This body paragraph is long enough for the single-item translation path.",
            _batched_plain_candidate=False,
        ),
        _item(
            "b",
            "A second body paragraph should still finish before validation tail retry starts.",
            _batched_plain_candidate=False,
        ),
    ]
    context = build_translation_control_context()
    calls: list[str] = []

    def _single_item_translator(item, **kwargs):
        calls.append(f"{item['item_id']}:{kwargs['allow_transport_tail_defer']}")
        if item["item_id"] == "a":
            raise DeferredValidationRetry(item=item, route_path=["block_level", "validation"], cause=ValueError("bad output"))
        return {
            "b": {
                "decision": "translate",
                "translated_text": "第二段已翻译",
                "final_status": "translated",
            }
        }

    result = translate_items_plain_text(
        batch,
        api_key="sk-test",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        request_label="test validation tail queue",
        context=context,
        diagnostics=None,
        single_item_translator=_single_item_translator,
        split_cached_batch_fn=lambda batch_arg, **_kwargs: ({}, batch_arg),
        store_cached_batch_fn=lambda *_args, **_kwargs: None,
        translate_batch_once_fn=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("skip batched path")),
    )

    assert result == {
        "b": {
            "decision": "translate",
            "translated_text": "第二段已翻译",
            "final_status": "translated",
        }
    }
    assert calls == ["a:True", "b:True"]
    drained = context.translation_tail_queue.drain()
    assert [item.item["item_id"] for item in drained] == ["a"]
    assert [item.reason for item in drained] == ["validation"]


def test_batched_plain_fallback_queues_uncached_items_for_tail_retry_by_default() -> None:
    batch = [
        _item(
            f"item-{index}",
            "This body paragraph is long enough for the batched plain translation path.",
            _batched_plain_candidate=True,
        )
        for index in range(4)
    ]
    context = build_translation_control_context()
    calls: list[str] = []

    def _single_item_translator(item, **_kwargs):
        calls.append(item["item_id"])
        return {
            item["item_id"]: {
                "decision": "translate",
                "translated_text": f"已翻译 {item['item_id']}",
                "final_status": "translated",
            }
        }

    result = translate_items_plain_text(
        batch,
        api_key="sk-test",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        request_label="test batched fallback",
        context=context,
        diagnostics=None,
        single_item_translator=_single_item_translator,
        split_cached_batch_fn=lambda batch_arg, **_kwargs: ({}, batch_arg),
        store_cached_batch_fn=lambda *_args, **_kwargs: None,
        translate_batch_once_fn=lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad batch")),
    )

    assert result == {}
    assert calls == []
    assert len(context.translation_tail_queue) == len(batch)


def test_batched_plain_fallback_can_retry_uncached_items_inline_for_compatibility(monkeypatch) -> None:
    monkeypatch.setenv("RETAIN_TRANSLATION_INLINE_BATCH_FALLBACK", "1")
    batch = [
        _item(
            f"item-{index}",
            "This body paragraph is long enough for the batched plain translation path.",
            _batched_plain_candidate=True,
        )
        for index in range(4)
    ]
    context = build_translation_control_context()
    calls: list[str] = []

    def _single_item_translator(item, **_kwargs):
        calls.append(item["item_id"])
        return {
            item["item_id"]: {
                "decision": "translate",
                "translated_text": f"已翻译 {item['item_id']}",
                "final_status": "translated",
            }
        }

    result = translate_items_plain_text(
        batch,
        api_key="sk-test",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        request_label="test batched fallback",
        context=context,
        diagnostics=None,
        single_item_translator=_single_item_translator,
        split_cached_batch_fn=lambda batch_arg, **_kwargs: ({}, batch_arg),
        store_cached_batch_fn=lambda *_args, **_kwargs: None,
        translate_batch_once_fn=lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad batch")),
    )

    assert sorted(result) == [item["item_id"] for item in batch]
    assert sorted(calls) == [item["item_id"] for item in batch]
