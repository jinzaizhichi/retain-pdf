from __future__ import annotations

import time

from services.translation.diagnostics import TranslationDiagnosticsCollector
from services.translation.llm.result_validator import validate_batch_result
from services.translation.llm.placeholder_diagnostics import log_placeholder_failure
from services.translation.llm.placeholder_transform import item_with_runtime_hard_glossary
from services.translation.llm.result_canonicalizer import canonicalize_batch_result
from services.translation.llm.validation.errors import EmptyTranslationError
from services.translation.llm.validation.errors import EnglishResidueError
from services.translation.llm.validation.errors import MathDelimiterError
from services.translation.llm.validation.errors import PlaceholderInventoryError
from services.translation.llm.validation.errors import TranslationProtocolError
from services.translation.llm.validation.errors import UnexpectedPlaceholderError
from services.translation.llm.shared.cache import split_cached_batch
from services.translation.llm.shared.cache import store_cached_batch
from services.translation.llm.shared.orchestration.batched_plain import translate_items_plain_text as _translate_items_plain_text
from services.translation.llm.shared.control_context import TranslationControlContext
from services.translation.llm.shared.orchestration.common import should_keep_origin_on_empty_translation
from services.translation.llm.shared.orchestration.common import single_item_http_retry_attempts
from services.translation.llm.shared.orchestration.direct_typst import translate_direct_typst_plain_text_with_retries
from services.translation.llm.shared.orchestration.formula_segment_path import try_formula_segment_path
from services.translation.llm.shared.orchestration.heavy_formula import heavy_formula_split_reason
from services.translation.llm.shared.orchestration.heavy_formula import translate_heavy_formula_block
from services.translation.llm.shared.orchestration.keep_origin import keep_origin_payload_for_empty_translation
from services.translation.llm.shared.orchestration.keep_origin import keep_origin_payload_for_repeated_empty_translation
from services.translation.llm.shared.orchestration.keep_origin import keep_origin_payload_for_transport_error
from services.translation.llm.shared.orchestration.metadata import attach_result_metadata
from services.translation.llm.shared.orchestration.metadata import formula_route_diagnostics
from services.translation.llm.shared.orchestration.metadata import restore_runtime_term_tokens
from services.translation.llm.shared.orchestration.metadata import should_store_translation_result
from services.translation.llm.shared.orchestration.plain_text_retry import PlainTextRetryRuntime
from services.translation.llm.shared.orchestration.plain_text_retry import run_plain_text_attempts
from services.translation.llm.shared.orchestration.route_selection import select_single_item_route
from services.translation.llm.shared.orchestration.segment_routing import translate_single_item_formula_segment_text_with_retries
from services.translation.llm.shared.orchestration.sentence_level import sentence_level_fallback
from services.translation.llm.shared.orchestration.tagged_placeholder import translate_stable_placeholder_text
from services.translation.llm.shared.orchestration.tagged_placeholder import try_tagged_placeholder_path
from services.translation.llm.shared.orchestration.transport import DeferredTransportRetry
from services.translation.llm.shared.orchestration.transport import defer_transport_retry
from services.translation.llm.shared.orchestration.transport import plain_text_timeout_seconds
from services.translation.llm.shared.provider_runtime import DEFAULT_BASE_URL
from services.translation.llm.shared.provider_runtime import DEFAULT_MODEL
from services.translation.llm.shared.provider_runtime import is_transport_error
from services.translation.llm.shared.provider_runtime import translate_batch_once
from services.translation.llm.shared.provider_runtime import translate_single_item_plain_text
from services.translation.llm.shared.provider_runtime import translate_single_item_plain_text_unstructured
from services.translation.llm.shared.provider_runtime import unwrap_translation_shell

_sentence_level_fallback = sentence_level_fallback
_keep_origin_payload_for_empty_translation = keep_origin_payload_for_empty_translation
_keep_origin_payload_for_repeated_empty_translation = keep_origin_payload_for_repeated_empty_translation
_keep_origin_payload_for_transport_error = keep_origin_payload_for_transport_error
_should_keep_origin_on_empty_translation = should_keep_origin_on_empty_translation
_heavy_formula_split_reason = heavy_formula_split_reason
_should_store_translation_result = should_store_translation_result

def _translate_heavy_formula_block(
    item: dict,
    *,
    api_key: str,
    model: str,
    base_url: str,
    request_label: str,
    context: TranslationControlContext,
    diagnostics: TranslationDiagnosticsCollector | None,
    split_reason: str,
) -> dict[str, dict[str, str]] | None:
    return translate_heavy_formula_block(
        item,
        api_key=api_key,
        model=model,
        base_url=base_url,
        request_label=request_label,
        context=context,
        diagnostics=diagnostics,
        split_reason=split_reason,
        translate_single_item_fn=translate_single_item_plain_text_with_retries,
        deferred_transport_retry_type=DeferredTransportRetry,
    )


def _sentence_level_fallback(
    item: dict,
    *,
    api_key: str,
    model: str,
    base_url: str,
    request_label: str,
    context: TranslationControlContext,
    diagnostics: TranslationDiagnosticsCollector | None,
    translate_plain_fn=None,
    translate_unstructured_fn=None,
) -> dict[str, dict[str, str]]:
    try:
        return sentence_level_fallback(
            item,
            api_key=api_key,
            model=model,
            base_url=base_url,
            request_label=request_label,
            context=context,
            diagnostics=diagnostics,
            translate_plain_fn=translate_plain_fn or translate_single_item_plain_text,
            translate_unstructured_fn=translate_unstructured_fn or translate_single_item_plain_text_unstructured,
        )
    except Exception as exc:
        if exc.__class__.__name__ == "EnglishResidueError" and not isinstance(exc, EnglishResidueError):
            raise EnglishResidueError(
                str(item.get("item_id", "") or ""),
                source_text=str(item.get("translation_unit_protected_source_text") or item.get("protected_source_text") or ""),
                translated_text=str(getattr(exc, "translated_text", "") or ""),
            ) from exc
        raise


def translate_single_item_stable_placeholder_text(
    item: dict,
    *,
    api_key: str = "",
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    request_label: str = "",
    context: TranslationControlContext,
    diagnostics: TranslationDiagnosticsCollector | None = None,
) -> dict[str, dict[str, str]]:
    return translate_stable_placeholder_text(
        item,
        api_key=api_key,
        model=model,
        base_url=base_url,
        request_label=request_label,
        context=context,
        diagnostics=diagnostics,
    )


def _try_tagged_placeholder_path(
    item: dict,
    *,
    api_key: str,
    model: str,
    base_url: str,
    request_label: str,
    context: TranslationControlContext,
    diagnostics: TranslationDiagnosticsCollector | None,
    route_path: list[str],
    allow_transport_tail_defer: bool,
    label_suffix: str = "tagged",
    attach_metadata: bool = True,
    handle_transport_error: bool = True,
) -> dict[str, dict[str, str]]:
    return try_tagged_placeholder_path(
        item,
        api_key=api_key,
        model=model,
        base_url=base_url,
        request_label=request_label,
        context=context,
        diagnostics=diagnostics,
        route_path=route_path,
        allow_transport_tail_defer=allow_transport_tail_defer,
        label_suffix=label_suffix,
        attach_metadata=attach_metadata,
        handle_transport_error=handle_transport_error,
        stable_placeholder_text_fn=translate_single_item_stable_placeholder_text,
        is_transport_error_fn=is_transport_error,
    )


def translate_single_item_plain_text_with_retries(
    item: dict,
    *,
    api_key: str = "",
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    request_label: str = "",
    context: TranslationControlContext,
    diagnostics: TranslationDiagnosticsCollector | None = None,
    allow_transport_tail_defer: bool = False,
) -> dict[str, dict[str, str]]:
    item = item_with_runtime_hard_glossary(item, context.glossary_entries)
    route = select_single_item_route(item, context=context)
    if route.direct_typst:
        return _translate_direct_typst_plain_text_with_retries(
            item,
            api_key=api_key,
            model=model,
            base_url=base_url,
            request_label=request_label,
            context=context,
            diagnostics=diagnostics,
            allow_transport_tail_defer=allow_transport_tail_defer,
        )

    split_reason = route.heavy_formula_split_reason
    if split_reason:
        if request_label:
            print(f"{request_label}: split heavy formula block before formula routing reason={split_reason}", flush=True)
        split_result = translate_heavy_formula_block(
            item,
            api_key=api_key,
            model=model,
            base_url=base_url,
            request_label=request_label,
            context=context,
            diagnostics=diagnostics,
            split_reason=split_reason,
            translate_single_item_fn=translate_single_item_plain_text_with_retries,
            deferred_transport_retry_type=DeferredTransportRetry,
        )
        if split_result is not None:
            return attach_result_metadata(
                restore_runtime_term_tokens(split_result, item=item),
                item=item,
                context=context,
                route_path=["block_level", "heavy_formula_split"],
                output_mode_path=["plain_text"],
                degradation_reason=split_reason,
            )

    plain_timeout_s = plain_text_timeout_seconds(
        item,
        context=context,
        transport_tail_retry=not allow_transport_tail_defer,
    )
    route_prefix = ["block_level"]

    if route.formula_segment_route == "single":
        formula_result = try_formula_segment_path(
            item,
            api_key=api_key,
            model=model,
            base_url=base_url,
            request_label=request_label,
            context=context,
            diagnostics=diagnostics,
            allow_transport_tail_defer=allow_transport_tail_defer,
            is_transport_error_fn=is_transport_error,
            formula_segment_translator_fn=translate_single_item_formula_segment_text_with_retries,
        )
        if formula_result is not None:
            return formula_result

    if route.prefer_tagged_placeholder_first:
        tagged_started = time.perf_counter()
        try:
            return _try_tagged_placeholder_path(
                item,
                api_key=api_key,
                model=model,
                base_url=base_url,
                request_label=request_label,
                context=context,
                diagnostics=diagnostics,
                route_path=route_prefix + ["tagged_placeholder_first"],
                allow_transport_tail_defer=allow_transport_tail_defer,
                label_suffix="tagged-first",
            )
        except Exception as exc:
            if request_label:
                print(
                    f"{request_label}: tagged-first path failed after {time.perf_counter() - tagged_started:.2f}s, fallback to plain-text path: {type(exc).__name__}: {exc}",
                    flush=True,
                )

    runtime = PlainTextRetryRuntime(
        translate_plain_fn=translate_single_item_plain_text,
        translate_unstructured_fn=translate_single_item_plain_text_unstructured,
        tagged_placeholder_path_fn=_try_tagged_placeholder_path,
        sentence_level_fallback_fn=_sentence_level_fallback,
        canonicalize_batch_result_fn=canonicalize_batch_result,
        validate_batch_result_fn=validate_batch_result,
        unwrap_translation_shell_fn=unwrap_translation_shell,
        log_placeholder_failure_fn=log_placeholder_failure,
        is_transport_error_fn=is_transport_error,
    )
    return run_plain_text_attempts(
        item,
        api_key=api_key,
        model=model,
        base_url=base_url,
        request_label=request_label,
        context=context,
        diagnostics=diagnostics,
        allow_transport_tail_defer=allow_transport_tail_defer,
        plain_timeout_s=plain_timeout_s,
        route_prefix=route_prefix,
        runtime=runtime,
    )


def translate_items_plain_text(
    batch: list[dict],
    *,
    api_key: str = "",
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    request_label: str = "",
    context: TranslationControlContext,
    diagnostics: TranslationDiagnosticsCollector | None = None,
) -> dict[str, dict[str, str]]:
    return _translate_items_plain_text(
        batch,
        api_key=api_key,
        model=model,
        base_url=base_url,
        request_label=request_label,
        context=context,
        diagnostics=diagnostics,
        single_item_translator=translate_single_item_plain_text_with_retries,
        split_cached_batch_fn=split_cached_batch,
        store_cached_batch_fn=store_cached_batch,
        translate_batch_once_fn=translate_batch_once,
    )


def _translate_direct_typst_plain_text_with_retries(
    item: dict,
    *,
    api_key: str,
    model: str,
    base_url: str,
    request_label: str,
    context: TranslationControlContext,
    diagnostics: TranslationDiagnosticsCollector | None,
    allow_transport_tail_defer: bool = False,
) -> dict[str, dict[str, str]]:
    return translate_direct_typst_plain_text_with_retries(
        item,
        api_key=api_key,
        model=model,
        base_url=base_url,
        request_label=request_label,
        context=context,
        diagnostics=diagnostics,
        allow_transport_tail_defer=allow_transport_tail_defer,
        translator=translate_single_item_plain_text_with_retries,
        translate_plain_fn=translate_single_item_plain_text,
        translate_unstructured_fn=translate_single_item_plain_text_unstructured,
        sentence_level_fallback_fn=_sentence_level_fallback,
        validate_batch_result_fn=validate_batch_result,
    )
