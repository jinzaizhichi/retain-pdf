from __future__ import annotations

import re


FIELD_LABEL_RE = re.compile(r"(?:^|\s*[•\-]\s+)([A-Za-z][A-Za-z0-9 _./-]{1,40})\s*:")
SHORT_LITERAL_VALUE_RE = re.compile(
    r"^(?:"
    r"-?\d+(?:\.\d+)?(?:[Ee][+-]?\d+)?"
    r"|true|false|null|none|yes|no"
    r"|<[^<>\n]{1,80}>"
    r"|\"[^\"]{0,120}\""
    r"|'[^']{0,120}'"
    r"|\[[^\]\n]{1,160}\]"
    r")$",
    re.I,
)


def _normalized_text(item: dict) -> str:
    return " ".join(str(item.get("source_text", "") or "").split()).strip()


def _field_labels(text: str) -> list[str]:
    labels: list[str] = []
    for match in FIELD_LABEL_RE.finditer(text):
        label = " ".join(match.group(1).split()).strip()
        if label:
            labels.append(label)
    return labels


def looks_like_structured_technical_block(item: dict) -> bool:
    text = _normalized_text(item)
    if not text or len(text) > 1200:
        return False
    labels = _field_labels(text)
    if len(labels) >= 2:
        return True
    if len(labels) == 1:
        tail = text.split(":", 1)[1].strip() if ":" in text else ""
        # Single-field rows are only treated as structural when the value is
        # clearly a short literal, not prose. This avoids broad code/prose guesses.
        return bool(SHORT_LITERAL_VALUE_RE.fullmatch(tail))
    return False


def structured_technical_style_hint(item: dict) -> str:
    if not looks_like_structured_technical_block(item):
        return ""
    labels = _field_labels(_normalized_text(item))
    label_text = "、".join(labels[:6])
    return (
        "这是技术文档中的结构化条目"
        + (f"（字段包括：{label_text}）" if label_text else "")
        + "。请保持字段名、字段顺序、列表符号、分隔符和换行排版稳定；"
        "字段值、类型标记、枚举、路径、命令、变量名、文件名、代码片段和尖括号内容应原样保留；"
        "只翻译字段值中明显属于自然语言说明的部分。不要把结构化字段名随意改写成另一种语言。"
    )


def apply_structured_technical_context(payload: list[dict]) -> int:
    annotated = 0
    for item in payload:
        hint = structured_technical_style_hint(item)
        if not hint:
            continue
        existing = str(item.get("translation_style_hint", "") or "").strip()
        item["translation_style_hint"] = f"{existing}\n{hint}".strip() if existing else hint
        item["translation_structure_kind"] = "structured_technical_block"
        metadata = dict(item.get("metadata", {}) or {})
        metadata["translation_structure_kind"] = "structured_technical_block"
        metadata["translation_style_hint"] = item["translation_style_hint"]
        item["metadata"] = metadata
        annotated += 1
    return annotated


__all__ = [
    "apply_structured_technical_context",
    "looks_like_structured_technical_block",
    "structured_technical_style_hint",
]
