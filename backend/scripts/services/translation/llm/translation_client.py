from __future__ import annotations

import json
import re

from services.translation.diagnostics import TranslationDiagnosticsCollector
from services.translation.llm.deepseek_client import build_messages
from services.translation.llm.deepseek_client import build_single_item_fallback_messages
from services.translation.llm.deepseek_client import extract_json_text
from services.translation.llm.deepseek_client import extract_single_item_translation_text
from services.translation.llm.deepseek_client import request_chat_content
from services.translation.llm.placeholder_guard import canonicalize_batch_result
from services.translation.llm.placeholder_guard import result_entry
from services.translation.llm.placeholder_guard import validate_batch_result


TAGGED_ITEM_RE = re.compile(
    r"<<<ITEM\s+item_id=(?P<item_id>[^\s>]+)(?:\s+decision=(?P<decision>[A-Za-z_-]+))?\s*>>>\s*"
    r"(?P<content>.*?)"
    r"\s*<<<END>>>",
    re.DOTALL,
)


def parse_translation_payload(content: str) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for match in TAGGED_ITEM_RE.finditer(content or ""):
        item_id = (match.group("item_id") or "").strip()
        decision = match.group("decision") or "translate"
        translated_text = (match.group("content") or "").strip()
        if item_id:
            result[item_id] = result_entry(decision, translated_text)
    if result:
        return result

    payload = json.loads(extract_json_text(content))
    translations = payload.get("translations", [])
    for item in translations:
        item_id = item.get("item_id")
        translated_text = item.get("translated_text", "")
        decision = item.get("decision", "translate")
        if item_id:
            result[item_id] = result_entry(decision, translated_text)
    return result


def translate_single_item_plain_text(
    item: dict,
    *,
    api_key: str = "",
    model: str = "deepseek-chat",
    base_url: str = "https://api.deepseek.com/v1",
    request_label: str = "",
    domain_guidance: str = "",
    mode: str = "fast",
    diagnostics: TranslationDiagnosticsCollector | None = None,
) -> dict[str, dict[str, str]]:
    content = request_chat_content(
        build_single_item_fallback_messages(
            item,
            domain_guidance=domain_guidance,
            mode=mode,
            structured_decision=False,
        ),
        api_key=api_key,
        model=model,
        base_url=base_url,
        temperature=0.0,
        response_format=None,
        timeout=120,
        request_label=request_label,
    )
    translated_text = extract_single_item_translation_text(content, item["item_id"])
    result = {item["item_id"]: result_entry("translate", translated_text)}
    result = canonicalize_batch_result([item], result)
    validate_batch_result([item], result, diagnostics=diagnostics)
    return result


def translate_single_item_tagged_text(
    item: dict,
    *,
    api_key: str = "",
    model: str = "deepseek-chat",
    base_url: str = "https://api.deepseek.com/v1",
    request_label: str = "",
    domain_guidance: str = "",
    diagnostics: TranslationDiagnosticsCollector | None = None,
) -> dict[str, dict[str, str]]:
    content = request_chat_content(
        build_messages([item], domain_guidance=domain_guidance, mode="fast"),
        api_key=api_key,
        model=model,
        base_url=base_url,
        temperature=0.0,
        response_format=None,
        timeout=120,
        request_label=request_label,
    )
    result = parse_translation_payload(content)
    result = canonicalize_batch_result([item], result)
    validate_batch_result([item], result, diagnostics=diagnostics)
    return result


def translate_single_item_with_decision(
    item: dict,
    *,
    api_key: str = "",
    model: str = "deepseek-chat",
    base_url: str = "https://api.deepseek.com/v1",
    request_label: str = "",
    domain_guidance: str = "",
    mode: str = "fast",
    diagnostics: TranslationDiagnosticsCollector | None = None,
) -> dict[str, dict[str, str]]:
    content = request_chat_content(
        build_single_item_fallback_messages(
            item,
            domain_guidance=domain_guidance,
            mode=mode,
            structured_decision=True,
        ),
        api_key=api_key,
        model=model,
        base_url=base_url,
        temperature=0.0,
        response_format=None,
        timeout=120,
        request_label=request_label,
    )
    result = parse_translation_payload(content)
    result = canonicalize_batch_result([item], result)
    validate_batch_result([item], result, diagnostics=diagnostics)
    return result


def translate_batch_once(
    batch: list[dict],
    *,
    api_key: str = "",
    model: str = "deepseek-chat",
    base_url: str = "https://api.deepseek.com/v1",
    request_label: str = "",
    domain_guidance: str = "",
    mode: str = "fast",
    diagnostics: TranslationDiagnosticsCollector | None = None,
) -> dict[str, dict[str, str]]:
    content = request_chat_content(
        build_messages(batch, domain_guidance=domain_guidance, mode=mode),
        api_key=api_key,
        model=model,
        base_url=base_url,
        temperature=0.2,
        response_format=None,
        timeout=120,
        request_label=request_label,
    )
    result = parse_translation_payload(content)
    result = canonicalize_batch_result(batch, result)
    validate_batch_result(batch, result, diagnostics=diagnostics)
    return result
