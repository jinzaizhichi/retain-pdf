from __future__ import annotations

import json
from typing import Any

from foundation.shared.prompt_loader import load_prompt
from services.translation.context import TranslationItemContext


JSON_ONLY_INSTRUCTION = 'Return only valid JSON with the schema {"translations":[{"item_id":"...","translated_text":"..."}]}.'
LEGACY_JSON_ONLY_INSTRUCTION_ZH = (
    "返回结果时只输出符合以下结构的合法 JSON：\n"
    '{"translations":[{"item_id":"...","translated_text":"..."}]}'
)


def direct_math_guidance() -> str:
    return (
        "当前启用 direct_typst 公式直出模式。\n"
        "请先理解整句语义，再直接输出中文译文。\n"
        "凡是语义上属于公式、变量、上下标、数学表达式、化学式、物理量符号、带上标或下标的单位与记号，请主动用 `$...$` 包裹。\n"
        "不要把裸露的 LaTeX 风格数学片段直接留在正文里。\n"
        "普通正文不要随意放进 `$...$`。\n"
        "如果 OCR 造成公式存在明显且局部的错误，例如空格错乱、括号缺失、花括号缺失、上下标脱落或命令被截断，你可以按语义做最小修复后再输出，使其可以正常渲染。\n"
        "不要补写缺失的正文内容，不要扩写原文，不要编造新的科学信息。\n"
        "不要输出占位符、结构化数据、标签、代码块或解释，只输出最终译文。"
    )


def build_translation_system_prompt(
    *,
    domain_guidance: str = "",
    mode: str = "fast",
    response_style: str = "tagged",
    include_sci_decision: bool = False,
) -> str:
    system_prompt = load_prompt(
        "translation_system_plain_text.txt"
        if response_style == "plain_text"
        else "translation_system.txt"
    )
    if response_style != "json":
        system_prompt = system_prompt.replace(JSON_ONLY_INSTRUCTION, "")
        system_prompt = system_prompt.replace(LEGACY_JSON_ONLY_INSTRUCTION_ZH, "").strip()
    if domain_guidance.strip():
        system_prompt = f"{system_prompt}\n\nDocument-specific translation guidance:\n{domain_guidance.strip()}"
    if mode == "sci" and include_sci_decision:
        system_prompt = f"{system_prompt}\n\n{load_prompt('translation_sci_decision.txt')}"
    return system_prompt


def direct_typst_batch_user_prompt(
    batch: list[TranslationItemContext],
    *,
    mode: str,
) -> str:
    lines: list[str] = [
        load_prompt("translation_task_plain_text.txt"),
        "",
        "下面是若干段待翻译正文。",
        "请为每段输出一个 tagged block，除此之外不要输出结构化数据、代码块、解释或额外文字。",
        "严格格式：",
        "<<<ITEM item_id=对应的原文 ID>>>",
        "译文",
        "<<<END>>>",
    ]
    for item in batch:
        lines.append("")
        lines.append(f"原文 {item.item_id}:")
        lines.append(item.source_for_prompt())
        if item.style_hint:
            lines.append(f"风格提示：{item.style_hint}")
        if item.continuation_group:
            lines.append("这是跨栏或跨页续接正文的一部分，请结合上下文理解后直接输出这一整段的译文。")
        context_before = item.context_before_for_prompt()
        if context_before:
            lines.append(f"前文上下文：{context_before}")
        context_after = item.context_after_for_prompt()
        if context_after:
            lines.append(f"后文上下文：{context_after}")
    return "\n".join(lines).strip()


def direct_typst_single_user_prompt(
    item: TranslationItemContext,
    *,
    mode: str,
) -> str:
    lines: list[str] = [
        load_prompt("translation_task_plain_text.txt"),
        "",
        "下面是一段待翻译正文。",
        "你只输出最终中文译文正文，不要输出编号、决策字段、结构化数据、标签、代码块或解释。",
        "",
        "原文：",
        item.source_for_prompt(),
    ]
    if item.style_hint:
        lines.append(f"风格提示：{item.style_hint}")
    if item.continuation_group:
        lines.append("这是跨栏或跨页续接正文的一部分，请结合上下文理解后直接输出这一整段的译文。")
    context_before = item.context_before_for_prompt()
    if context_before:
        lines.append(f"前文上下文：{context_before}")
    context_after = item.context_after_for_prompt()
    if context_after:
        lines.append(f"后文上下文：{context_after}")
    return "\n".join(lines).strip()


def plain_text_single_user_prompt(
    item: TranslationItemContext,
    *,
    mode: str,
) -> str:
    lines: list[str] = [
        load_prompt("translation_task_plain_text.txt"),
        "",
        "下面是一段待翻译正文。",
        "只输出这一段的最终中文译文正文，不要输出编号、决策字段、结构化数据、标签、代码块或解释。",
        "",
        "原文：",
        item.source_for_prompt(),
    ]
    if item.style_hint:
        lines.append(f"风格提示：{item.style_hint}")
    if item.continuation_group:
        lines.append("这是跨栏或跨页续接正文的一部分，请结合上下文理解后直接输出这一整段的译文。")
    context_before = item.context_before_for_prompt()
    if context_before:
        lines.append(f"前文上下文：{context_before}")
    context_after = item.context_after_for_prompt()
    if context_after:
        lines.append(f"后文上下文：{context_after}")
    return "\n".join(lines).strip()


def batch_json_user_prompt(batch: list[TranslationItemContext]) -> str:
    groups: dict[str, dict[str, Any]] = {}
    items_payload = []
    for item in batch:
        group_id = item.continuation_group
        item_payload = item.as_batch_payload()
        if group_id:
            group = groups.setdefault(group_id, {"group_id": group_id, "item_ids": [], "combined_source_text": []})
            group["item_ids"].append(item.item_id)
            group["combined_source_text"].append(item.source_for_context())
        items_payload.append(item_payload)
    user_payload = {
        "task": load_prompt("translation_task.txt"),
        "items": items_payload,
    }
    if groups:
        user_payload["continuation_groups"] = [
            {
                "group_id": group["group_id"],
                "item_ids": group["item_ids"],
                "combined_source_text": " ".join(group["combined_source_text"]),
            }
            for group in groups.values()
        ]
    return json.dumps(user_payload, ensure_ascii=False)


__all__ = [
    "batch_json_user_prompt",
    "build_translation_system_prompt",
    "direct_math_guidance",
    "direct_typst_batch_user_prompt",
    "direct_typst_single_user_prompt",
    "plain_text_single_user_prompt",
]
