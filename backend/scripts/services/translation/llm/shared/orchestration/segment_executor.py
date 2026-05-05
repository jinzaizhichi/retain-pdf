from __future__ import annotations

import json
import time

from services.translation.diagnostics import TranslationDiagnosticsCollector
from services.translation.llm.result_canonicalizer import canonicalize_batch_result
from services.translation.llm.result_payload import result_entry
from services.translation.llm.result_validator import validate_batch_result
from services.translation.llm.shared.control_context import SegmentationPolicy
from services.translation.llm.shared.orchestration.segment_errors import SegmentTranslationFormatError
from services.translation.llm.shared.orchestration.segment_errors import SegmentTranslationSemanticError
from services.translation.llm.shared.orchestration.segment_parsing import parse_segment_translation_payload
from services.translation.llm.shared.orchestration.segment_plan import build_formula_segment_plan
from services.translation.llm.shared.orchestration.segment_plan import build_formula_segment_windows
from services.translation.llm.shared.orchestration.segment_plan import merge_segment_contexts
from services.translation.llm.shared.orchestration.segment_plan import rebuild_formula_segment_translation
from services.translation.llm.shared.orchestration.segment_prompts import build_formula_segment_messages
from services.translation.llm.shared.provider_runtime import DEFAULT_BASE_URL
from services.translation.llm.shared.provider_runtime import DEFAULT_MODEL
from services.translation.llm.shared.provider_runtime import request_chat_content
from services.translation.llm.shared.structured_models import FORMULA_SEGMENT_RESPONSE_SCHEMA
from services.translation.llm.validation.english_residue import unit_source_text


def request_formula_segment_translation(
    item: dict,
    skeleton: list[tuple[str, str]],
    segments: list[dict[str, str]],
    *,
    api_key: str,
    model: str,
    base_url: str,
    domain_guidance: str,
    timeout_s: int,
    request_label: str,
    context_before: str | None = None,
    context_after: str | None = None,
    request_chat_content_fn=request_chat_content,
) -> dict[str, str]:
    tagged_error: Exception | None = None
    tagged_request_label = f"{request_label} tagged" if request_label else ""
    try:
        content = request_chat_content_fn(
            build_formula_segment_messages(
                item,
                skeleton,
                segments,
                domain_guidance=domain_guidance,
                context_before=context_before,
                context_after=context_after,
                response_style="tagged",
            ),
            api_key=api_key,
            model=model,
            base_url=base_url,
            temperature=0.0,
            response_format=None,
            timeout=timeout_s,
            request_label=tagged_request_label,
        )
        return parse_segment_translation_payload(content, expected_segments=segments)
    except SegmentTranslationSemanticError:
        raise
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        tagged_error = exc

    content = request_chat_content_fn(
        build_formula_segment_messages(
            item,
            skeleton,
            segments,
            domain_guidance=domain_guidance,
            context_before=context_before,
            context_after=context_after,
            response_style="json",
        ),
        api_key=api_key,
        model=model,
        base_url=base_url,
        temperature=0.0,
        response_format=FORMULA_SEGMENT_RESPONSE_SCHEMA,
        timeout=timeout_s,
        request_label=f"{request_label} json" if request_label else "",
    )
    try:
        return parse_segment_translation_payload(content, expected_segments=segments)
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        if tagged_error is not None:
            raise SegmentTranslationFormatError(f"tagged_failed={tagged_error}; json_failed={exc}") from exc
        raise


def translate_single_item_formula_segment_text_with_retries(
    item: dict,
    *,
    api_key: str = "",
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    request_label: str = "",
    domain_guidance: str = "",
    policy: SegmentationPolicy | None = None,
    diagnostics: TranslationDiagnosticsCollector | None = None,
    attempt_limit: int = 4,
    timeout_s: int = 120,
    request_chat_content_fn=request_chat_content,
) -> dict[str, dict[str, str]]:
    if policy is None:
        policy = SegmentationPolicy()
    source_text = unit_source_text(item)
    skeleton, segments = build_formula_segment_plan(source_text)
    if not segments:
        raise SegmentTranslationFormatError(f"{item['item_id']}: no translatable formula segments")
    if len(segments) > policy.max_formula_segment_count:
        raise SegmentTranslationFormatError(
            f"{item['item_id']}: too many formula segments ({len(segments)} > {policy.max_formula_segment_count})"
        )

    last_error: Exception | None = None
    for attempt in range(1, max(1, attempt_limit) + 1):
        started = time.perf_counter()
        try:
            if request_label:
                print(f"{request_label}: segmented-formula attempt {attempt}/{max(1, attempt_limit)} segments={len(segments)}", flush=True)
            translated_segments = request_formula_segment_translation(
                item,
                skeleton,
                segments,
                api_key=api_key,
                model=model,
                base_url=base_url,
                domain_guidance=domain_guidance,
                timeout_s=timeout_s,
                request_label=f"{request_label} seg#{attempt}" if request_label else "",
                request_chat_content_fn=request_chat_content_fn,
            )
            rebuilt_text = rebuild_formula_segment_translation(skeleton, translated_segments)
            result = {item["item_id"]: result_entry("translate", rebuilt_text)}
            result = canonicalize_batch_result([item], result)
            validate_batch_result([item], result, diagnostics=diagnostics)
            if request_label:
                elapsed = time.perf_counter() - started
                print(f"{request_label}: segmented-formula ok in {elapsed:.2f}s", flush=True)
            return result
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            last_error = exc
            if request_label:
                elapsed = time.perf_counter() - started
                print(
                    f"{request_label}: segmented-formula failed attempt {attempt}/{max(1, attempt_limit)} after {elapsed:.2f}s: {type(exc).__name__}: {exc}",
                    flush=True,
                )
            if attempt >= max(1, attempt_limit):
                raise
            time.sleep(min(8, 2 * attempt))
    if last_error is not None:
        raise last_error
    raise RuntimeError("Segmented formula translation failed without an exception.")


def translate_formula_segment_window_with_retries(
    item: dict,
    window: dict[str, object],
    *,
    total_windows: int,
    api_key: str = "",
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    request_label: str = "",
    domain_guidance: str = "",
    attempt_limit: int = 4,
    timeout_s: int = 120,
    request_chat_content_fn=request_chat_content,
) -> dict[str, str]:
    window_index = int(window["window_index"])
    window_segments = list(window["segments"])
    window_range = str(window["segment_range"])
    context_before = str(window.get("context_before", "") or "")
    context_after = str(window.get("context_after", "") or "")
    if bool(window.get("is_first_window")):
        context_before = merge_segment_contexts(str(item.get("continuation_prev_text", "") or ""), context_before)
    if bool(window.get("is_last_window")):
        context_after = merge_segment_contexts(context_after, str(item.get("continuation_next_text", "") or ""))
    last_error: Exception | None = None
    for attempt in range(1, max(1, attempt_limit) + 1):
        started = time.perf_counter()
        try:
            if request_label:
                print(
                    f"{request_label}: formula-window {window_index}/{total_windows} attempt {attempt}/{max(1, attempt_limit)} segments={len(window_segments)} range={window_range}",
                    flush=True,
                )
            translated_segments = request_formula_segment_translation(
                item,
                list(window["skeleton"]),
                window_segments,
                api_key=api_key,
                model=model,
                base_url=base_url,
                domain_guidance=domain_guidance,
                timeout_s=timeout_s,
                request_label=f"{request_label} win{window_index}#{attempt}" if request_label else "",
                context_before=context_before,
                context_after=context_after,
                request_chat_content_fn=request_chat_content_fn,
            )
            if request_label:
                elapsed = time.perf_counter() - started
                print(f"{request_label}: formula-window {window_index}/{total_windows} ok in {elapsed:.2f}s", flush=True)
            return translated_segments
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            last_error = exc
            if request_label:
                elapsed = time.perf_counter() - started
                print(
                    f"{request_label}: formula-window {window_index}/{total_windows} failed attempt {attempt}/{max(1, attempt_limit)} after {elapsed:.2f}s: {type(exc).__name__}: {exc}",
                    flush=True,
                )
            if attempt >= max(1, attempt_limit):
                raise
            time.sleep(min(8, 2 * attempt))
    if last_error is not None:
        raise last_error
    raise RuntimeError("Formula window translation failed without an exception.")


def translate_single_item_formula_segment_windows_with_retries(
    item: dict,
    *,
    api_key: str = "",
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    request_label: str = "",
    domain_guidance: str = "",
    policy: SegmentationPolicy | None = None,
    diagnostics: TranslationDiagnosticsCollector | None = None,
    attempt_limit: int = 4,
    timeout_s: int = 120,
    request_chat_content_fn=request_chat_content,
) -> dict[str, dict[str, str]]:
    if policy is None:
        policy = SegmentationPolicy()
    source_text = unit_source_text(item)
    skeleton, segments = build_formula_segment_plan(source_text)
    if not segments:
        raise SegmentTranslationFormatError(f"{item['item_id']}: no translatable formula segments")
    windows = build_formula_segment_windows(skeleton, segments, policy=policy)
    if len(windows) <= 1:
        translated_segments = translate_formula_segment_window_with_retries(
            item,
            windows[0],
            total_windows=1,
            api_key=api_key,
            model=model,
            base_url=base_url,
            request_label=request_label,
            domain_guidance=domain_guidance,
            attempt_limit=attempt_limit,
            timeout_s=timeout_s,
            request_chat_content_fn=request_chat_content_fn,
        )
        rebuilt_text = rebuild_formula_segment_translation(skeleton, translated_segments)
        result = {item["item_id"]: result_entry("translate", rebuilt_text)}
        result = canonicalize_batch_result([item], result)
        validate_batch_result([item], result, diagnostics=diagnostics)
        if request_label:
            print(f"{request_label}: single-window-formula rebuilt ok translated_windows=1/1", flush=True)
        return result

    if request_label:
        print(f"{request_label}: route=windowed-formula windows={len(windows)} segments={len(segments)}", flush=True)
    translated_segments: dict[str, str] = {}
    successful_windows = 0
    for window in windows:
        try:
            translated_segments.update(
                translate_formula_segment_window_with_retries(
                    item,
                    window,
                    total_windows=len(windows),
                    api_key=api_key,
                    model=model,
                    base_url=base_url,
                    request_label=request_label,
                    domain_guidance=domain_guidance,
                    attempt_limit=attempt_limit,
                    timeout_s=timeout_s,
                    request_chat_content_fn=request_chat_content_fn,
                )
            )
            successful_windows += 1
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            window_index = int(window["window_index"])
            window_range = str(window["segment_range"])
            if diagnostics is not None:
                diagnostics.emit(
                    kind="formula_window_degraded",
                    item_id=str(item.get("item_id", "") or ""),
                    page_idx=item.get("page_idx"),
                    severity="warning",
                    message=f"Formula window degraded to source for range {window_range}",
                    retryable=True,
                    details={"window_index": window_index, "segment_range": window_range},
                )
            if request_label:
                print(
                    f"{request_label}: formula-window {window_index}/{len(windows)} degraded to local keep_origin range={window_range}: {type(exc).__name__}: {exc}",
                    flush=True,
                )
            for segment in list(window["segments"]):
                translated_segments[segment["segment_id"]] = segment["source_text"]

    if successful_windows == 0:
        raise SegmentTranslationFormatError(f"{item['item_id']}: all formula windows degraded to source")

    rebuilt_text = rebuild_formula_segment_translation(skeleton, translated_segments)
    result = {item["item_id"]: result_entry("translate", rebuilt_text)}
    result = canonicalize_batch_result([item], result)
    validate_batch_result([item], result, diagnostics=diagnostics)
    if request_label:
        print(
            f"{request_label}: windowed-formula rebuilt ok translated_windows={successful_windows}/{len(windows)}",
            flush=True,
        )
    return result
