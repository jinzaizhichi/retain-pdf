import sys
from dataclasses import replace
from pathlib import Path
from unittest import mock


REPO_SCRIPTS_ROOT = Path("/home/wxyhgk/tmp/Code/backend/scripts")
sys.path.insert(0, str(REPO_SCRIPTS_ROOT))


from services.translation.llm import placeholder_guard
from services.translation.llm.shared import cache
from services.translation.llm.shared.orchestration import fallbacks
from services.translation.llm.shared.orchestration import segment_routing


def test_citation_rich_body_text_still_forces_translation() -> None:
    source_text = (
        "For infilling tasks, we attempt to query the LLaMA model with the prompt given the "
        "<prefix> and <suffix>, please answer the <middle> part, which includes both prefix and "
        "suffix information. However, this approach is no better than simply completing the prefix, "
        "likely because the LLaMA model needs tuning for filling in the middle (FIM; Bavarian et al. "
        "2022b). Additionally, Bavarian et al. (2022b) notes that using AR models for infilling "
        "presents challenges, such as prompting difficulties and repetition. In contrast, DLMs are "
        "naturally suited for this task, as they are trained to handle masked inputs, which is a key advantage."
    )
    item = {
        "item_id": "p024-b008",
        "block_type": "text",
        "metadata": {"structure_role": "body"},
        "translation_unit_protected_source_text": source_text,
        "protected_source_text": source_text,
    }

    assert placeholder_guard.should_force_translate_body_text(item)
    assert placeholder_guard.looks_like_untranslated_english_output(item, source_text)


def test_repeated_empty_translation_degrades_to_keep_origin() -> None:
    payload = fallbacks._keep_origin_payload_for_repeated_empty_translation(
        {
            "item_id": "p001-b017",
            "page_idx": 0,
            "block_type": "text",
        }
    )
    assert payload["p001-b017"]["decision"] == "keep_origin"
    assert payload["p001-b017"]["final_status"] == "kept_origin"
    assert (
        payload["p001-b017"]["translation_diagnostics"]["degradation_reason"]
        == "empty_translation_repeated"
    )


def test_translation_cache_prompt_hash_includes_plain_text_prompt_files() -> None:
    original_load_prompt = cache.load_prompt

    def fake_load_prompt(name: str) -> str:
        text = original_load_prompt(name)
        if name == "translation_task_plain_text.txt":
            return f"{text}\nCACHE TEST MUTATION"
        return text

    item = {
        "item_id": "p001-b001",
        "translation_unit_protected_source_text": "This is a source sentence.",
    }
    before = cache.cache_key_for_item(
        item,
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        mode="sci",
    )
    with mock.patch.object(cache, "load_prompt", side_effect=fake_load_prompt):
        cache._PROMPT_HASHES.clear()
        after = cache.cache_key_for_item(
            item,
            model="deepseek-chat",
            base_url="https://api.deepseek.com/v1",
            mode="sci",
        )
    cache._PROMPT_HASHES.clear()

    assert before != after


def test_formula_segment_route_prefers_plain_for_small_segment_count() -> None:
    item = {
        "item_id": "p001-b001",
        "protected_source_text": "After <f1-a7c/> hours, activity increased and <f2-b2d/> remained stable.",
    }
    policy = segment_routing.SegmentationPolicy(
        prefer_plain_when_segment_count_leq=6,
        small_formula_inline_enabled=False,
    )
    assert segment_routing.formula_segment_translation_route(item, policy=policy) == "none"


def test_direct_typst_skips_heavy_formula_split_entry() -> None:
    from services.translation.llm.shared import control_context

    item = {
        "item_id": "p001-b002",
        "page_idx": 0,
        "block_type": "text",
        "math_mode": "direct_typst",
        "metadata": {"structure_role": "body"},
        "protected_source_text": r"Observe $\mathrm{Ph(i-PrO)SiH_2}$ and more text.",
        "translation_unit_protected_source_text": r"Observe $\mathrm{Ph(i-PrO)SiH_2}$ and more text.",
    }
    context = control_context.build_translation_control_context(mode="sci")
    plain_payload = {
        "p001-b002": {
            "decision": "translate",
            "translated_text": r"观察到 $\mathrm{Ph(i-PrO)SiH_2}$ 以及更多文本。",
        }
    }

    with mock.patch.object(fallbacks, "_heavy_formula_split_reason", side_effect=AssertionError("should not be called")):
        with mock.patch.object(fallbacks, "translate_single_item_plain_text", return_value=plain_payload):
            result = fallbacks.translate_single_item_plain_text_with_retries(
                item,
                api_key="",
                model="deepseek-chat",
                base_url="https://api.deepseek.com/v1",
                request_label="test",
                context=context,
                diagnostics=None,
            )

    assert result["p001-b002"]["translated_text"] == plain_payload["p001-b002"]["translated_text"]


def test_english_residue_degrades_to_keep_origin_after_sentence_fallback_failure() -> None:
    from services.translation.llm.shared import control_context

    item = {
        "item_id": "p001-b002",
        "page_idx": 0,
        "block_type": "text",
        "metadata": {"structure_role": "body"},
        "protected_source_text": "This is the first sentence. This is the second sentence.",
        "translation_unit_protected_source_text": "This is the first sentence. This is the second sentence.",
    }
    context = control_context.build_translation_control_context(mode="sci")
    context = replace(
        context,
        fallback_policy=replace(
            context.fallback_policy,
            plain_text_attempts=1,
            allow_tagged_placeholder_retry=False,
        ),
    )
    english_residue = fallbacks.EnglishResidueError("p001-b002")

    with mock.patch.object(fallbacks, "translate_single_item_plain_text", side_effect=english_residue):
        with mock.patch.object(fallbacks, "translate_single_item_plain_text_unstructured", side_effect=english_residue):
            with mock.patch.object(
                fallbacks,
                "_sentence_level_fallback",
                side_effect=fallbacks.PlaceholderInventoryError("p001-b002", [], []),
            ):
                result = fallbacks.translate_single_item_plain_text_with_retries(
                    item,
                    api_key="",
                    model="deepseek-chat",
                    base_url="https://api.deepseek.com/v1",
                    request_label="test",
                    context=context,
                    diagnostics=None,
                )

    payload = result["p001-b002"]
    assert payload["decision"] == "keep_origin"
    assert payload["translation_diagnostics"]["degradation_reason"] == "english_residue_repeated"
    assert payload["translation_diagnostics"]["final_status"] == "kept_origin"
