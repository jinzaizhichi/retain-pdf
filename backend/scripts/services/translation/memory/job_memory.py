from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MEMORY_VERSION = 1
MAX_SUMMARY_TERMS = 20
MAX_SUMMARY_PRESERVE_HINTS = 8
MAX_RETRIEVED_SUMMARY_TERMS = 8
MAX_RETRIEVED_PRESERVE_HINTS = 2
MAX_TERM_RECORDS = 160
MAX_PRESERVE_HINT_RECORDS = 80
MIN_TERM_HITS_FOR_PROMPT = 1
MAX_TRANSLATED_TERM_VALUE_CHARS = 12
MAX_TRANSLATED_TERM_VALUE_CJK = 8
MAX_TERM_KEY_WORDS_FOR_PROMPT = 4
NOUNISH_JIEBA_FLAGS = ("n", "nr", "ns", "nt", "nz", "vn", "l", "eng")
FUNCTION_JIEBA_FLAGS = ("uj", "ul", "p", "d", "u", "x")

TERM_PAIR_PATTERNS = (
    re.compile(r"(?P<zh>[\u4e00-\u9fff][\u4e00-\u9fffA-Za-z0-9·\-]{1,24})（(?:或称|又称|简称)?(?P<en>[A-Za-z][A-Za-z0-9 ._+/\-]{1,48})）"),
    re.compile(r"(?P<zh>[\u4e00-\u9fff][\u4e00-\u9fffA-Za-z0-9·\-]{1,24})\((?:or |also known as )?(?P<en>[A-Za-z][A-Za-z0-9 ._+/\-]{1,48})\)"),
    re.compile(r"(?P<zh>[\u4e00-\u9fff][\u4e00-\u9fffA-Za-z0-9·\-]{1,24})（(?P<en>[A-Za-z][A-Za-z0-9 ._+/\-]{1,48})）"),
)
TECH_TOKEN_RE = re.compile(r"\b[A-Z][A-Za-z0-9]*(?:[-_/][A-Za-z0-9]+)*(?:\s+[A-Z][A-Za-z0-9]*(?:[-_/][A-Za-z0-9]+)*){0,3}\b")


def _normalize_space(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _source_text_from_item(item: dict[str, Any]) -> str:
    return _normalize_space(
        item.get("translation_unit_protected_source_text")
        or item.get("protected_source_text")
        or item.get("source_text")
        or item.get("text")
        or ""
    )


def _source_text_for_batch(batch: list[dict]) -> str:
    return "\n".join(_source_text_from_item(item) for item in batch if _source_text_from_item(item)).strip()


def _term_key_matches_source(key: str, source_text: str) -> bool:
    cleaned_key = _clean_term_key(key)
    cleaned_source = _normalize_space(source_text)
    if not cleaned_key or not cleaned_source:
        return False
    if not re.search(r"[A-Za-z0-9]", cleaned_key):
        return cleaned_key.lower() in cleaned_source.lower()
    escaped_key = re.escape(cleaned_key).replace(r"\ ", r"\s+")
    pattern = re.compile(
        rf"(?<![A-Za-z0-9]){escaped_key}(?![A-Za-z0-9])",
        re.IGNORECASE,
    )
    return bool(pattern.search(cleaned_source))


def _preserve_hint_matches_source(hint: str, source_text: str) -> bool:
    cleaned_hint = _normalize_space(hint).lower()
    cleaned_source = _normalize_space(source_text).lower()
    if not cleaned_hint or not cleaned_source:
        return False
    if cleaned_hint in cleaned_source or cleaned_source in cleaned_hint:
        return True
    hint_lines = [line.strip().lower() for line in str(hint or "").splitlines() if len(line.strip()) >= 8]
    source_lines = {line.strip().lower() for line in str(source_text or "").splitlines() if len(line.strip()) >= 8}
    return any(line in source_lines for line in hint_lines)


def _clean_term_key(text: str) -> str:
    cleaned = _normalize_space(text)
    cleaned = cleaned.strip(" ,.;:()[]{}，。；：（）【】")
    return cleaned[:80]


def _clean_term_value(text: str) -> str:
    cleaned = _normalize_space(text)
    cleaned = cleaned.strip(" ,.;:()[]{}，。；：（）【】")
    return cleaned[:80]


def _looks_like_useful_term_key(key: str) -> bool:
    if len(key) < 2:
        return False
    if key.lower() in {"or", "and", "the", "from", "with", "for", "this", "that"}:
        return False
    return any(ch.isalpha() for ch in key)


def _looks_like_useful_term_value(value: str) -> bool:
    return bool(value and re.search(r"[\u4e00-\u9fff]", value))


def _cjk_count(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text or ""))


def _is_identity_term(key: str, value: str) -> bool:
    return _clean_term_key(key).lower() == _clean_term_value(value).lower()


def _jieba_posseg_cut(text: str) -> list[tuple[str, str]] | None:
    try:
        import jieba.posseg as pseg  # type: ignore[import-not-found]
    except Exception:
        return None
    try:
        return [(str(word), str(flag)) for word, flag in pseg.cut(text)]
    except Exception:
        return None


def _looks_like_noun_phrase(value: str) -> bool:
    cleaned = _clean_term_value(value)
    if not cleaned:
        return False
    tokens = _jieba_posseg_cut(cleaned)
    if tokens is None:
        return _fallback_looks_like_noun_phrase(cleaned)
    meaningful = [(word, flag) for word, flag in tokens if word.strip()]
    if not meaningful:
        return False
    if any(word in {"的", "已", "将", "被", "从", "在", "这", "其"} or flag.startswith(FUNCTION_JIEBA_FLAGS) for word, flag in meaningful):
        return False
    nounish_chars = sum(len(word) for word, flag in meaningful if flag.startswith(NOUNISH_JIEBA_FLAGS))
    total_chars = sum(len(word) for word, _flag in meaningful)
    if total_chars <= 0:
        return False
    return nounish_chars / total_chars >= 0.45


def _fallback_looks_like_noun_phrase(value: str) -> bool:
    cleaned = _clean_term_value(value)
    if not cleaned:
        return False
    if re.search(r"[，。；：、,.!?！？]", cleaned):
        return False
    return len(cleaned) <= MAX_TRANSLATED_TERM_VALUE_CHARS and _cjk_count(cleaned) <= MAX_TRANSLATED_TERM_VALUE_CJK


def _term_key_allowed_in_prompt(key: str) -> bool:
    cleaned = _clean_term_key(key)
    if not _looks_like_useful_term_key(cleaned):
        return False
    if len(cleaned.split()) > MAX_TERM_KEY_WORDS_FOR_PROMPT:
        return False
    return True


def _translated_value_allowed_in_prompt(value: str) -> bool:
    cleaned = _clean_term_value(value)
    if not _looks_like_useful_term_value(cleaned):
        return False
    if len(cleaned) > MAX_TRANSLATED_TERM_VALUE_CHARS:
        return False
    if _cjk_count(cleaned) > MAX_TRANSLATED_TERM_VALUE_CJK:
        return False
    return _looks_like_noun_phrase(cleaned)


def _term_record_allowed_in_prompt(record: dict[str, Any]) -> bool:
    key = _clean_term_key(str(record.get("key") or ""))
    value = _clean_term_value(str(record.get("value") or ""))
    if not _term_key_allowed_in_prompt(key) or not value:
        return False
    if _is_identity_term(key, value):
        return True
    return _translated_value_allowed_in_prompt(value)


def _is_preserve_candidate(source_text: str) -> bool:
    text = source_text.strip()
    if not text:
        return False
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) >= 2:
        symbolic_lines = sum(1 for line in lines if re.search(r"^(?:[$>#]|[-*]\s+|\|[-\w .]+|[A-Za-z_][\w.-]*\s*=)", line))
        if symbolic_lines >= max(1, len(lines) // 2):
            return True
    if re.search(r"^\s*(?:[$>#]\s*\w+|[A-Za-z_][\w.-]*\s*=\s*\S+)", text):
        return True
    if re.search(r"\b(?:Default|Type|Input|Output|Usage|Example)\s*:\s*\\?<?[A-Z0-9_./-]+>?$", text):
        return True
    return False


def _extract_term_candidates(source_text: str, translated_text: str) -> list[tuple[str, str]]:
    translated = _normalize_space(translated_text)
    candidates: list[tuple[str, str]] = []
    for pattern in TERM_PAIR_PATTERNS:
        for match in pattern.finditer(translated):
            key = _clean_term_key(match.group("en"))
            value = _clean_term_value(match.group("zh"))
            if _looks_like_useful_term_key(key) and _looks_like_useful_term_value(value):
                candidates.append((key, value))

    source_tokens = [_clean_term_key(match.group(0)) for match in TECH_TOKEN_RE.finditer(source_text or "")]
    translated_lower = translated.lower()
    for token in source_tokens[:24]:
        if not _looks_like_useful_term_key(token):
            continue
        if token.lower() in translated_lower:
            candidates.append((token, token))
    return candidates


@dataclass
class JobMemory:
    path: Path
    terms: dict[str, dict[str, Any]]
    preserve_hints: dict[str, dict[str, Any]]

    @classmethod
    def empty(cls, path: Path) -> "JobMemory":
        return cls(path=path, terms={}, preserve_hints={})

    @classmethod
    def from_dict(cls, path: Path, payload: dict[str, Any]) -> "JobMemory":
        return cls(
            path=path,
            terms={str(key): dict(value) for key, value in dict(payload.get("terms") or {}).items()},
            preserve_hints={
                str(key): dict(value)
                for key, value in dict(payload.get("preserve_hints") or {}).items()
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": MEMORY_VERSION,
            "terms": self.terms,
            "preserve_hints": self.preserve_hints,
        }

    def add_term(self, *, key: str, value: str, source: str) -> bool:
        normalized_key = _clean_term_key(key)
        normalized_value = _clean_term_value(value)
        if not _looks_like_useful_term_key(normalized_key) or not normalized_value:
            return False
        record = self.terms.setdefault(
            normalized_key,
            {
                "key": normalized_key,
                "value": normalized_value,
                "hits": 0,
                "sources": [],
            },
        )
        existing_value = _clean_term_value(str(record.get("value") or ""))
        if _looks_like_useful_term_value(normalized_value) or not _looks_like_useful_term_value(existing_value):
            record["value"] = normalized_value
        record["hits"] = int(record.get("hits") or 0) + 1
        sources = list(record.get("sources") or [])
        if source and source not in sources:
            sources.append(source)
        record["sources"] = sources[-8:]
        record["prompt_eligible"] = _term_record_allowed_in_prompt(record)
        return True

    def add_preserve_hint(self, *, key: str, source: str) -> bool:
        normalized_key = _normalize_space(key)[:120]
        if not normalized_key:
            return False
        record = self.preserve_hints.setdefault(
            normalized_key,
            {
                "key": normalized_key,
                "hits": 0,
                "sources": [],
            },
        )
        record["hits"] = int(record.get("hits") or 0) + 1
        sources = list(record.get("sources") or [])
        if source and source not in sources:
            sources.append(source)
        record["sources"] = sources[-8:]
        return True

    def trim(self) -> None:
        self.terms = dict(
            sorted(
                self.terms.items(),
                key=lambda item: (int(item[1].get("hits") or 0), item[0]),
                reverse=True,
            )[:MAX_TERM_RECORDS]
        )
        self.preserve_hints = dict(
            sorted(
                self.preserve_hints.items(),
                key=lambda item: (int(item[1].get("hits") or 0), item[0]),
                reverse=True,
            )[:MAX_PRESERVE_HINT_RECORDS]
        )

    def prompt_summary(self) -> str:
        lines: list[str] = []
        term_records = [
            record
            for record in self.terms.values()
            if int(record.get("hits") or 0) >= MIN_TERM_HITS_FOR_PROMPT
            and _term_record_allowed_in_prompt(record)
        ]
        term_records = sorted(term_records, key=lambda record: (-int(record.get("hits") or 0), str(record.get("key") or "")))
        if term_records:
            lines.append("当前文档记忆：术语保持一致。")
            for record in term_records[:MAX_SUMMARY_TERMS]:
                key = _clean_term_key(str(record.get("key") or ""))
                value = _clean_term_value(str(record.get("value") or ""))
                if key and value:
                    lines.append(f"- {key} => {value}")

        preserve_records = sorted(
            self.preserve_hints.values(),
            key=lambda record: (-int(record.get("hits") or 0), str(record.get("key") or "")),
        )
        if preserve_records:
            lines.append("当前文档记忆：以下类型更可能是技术原文/代码/参数块，应优先保留排版和符号。")
            for record in preserve_records[:MAX_SUMMARY_PRESERVE_HINTS]:
                lines.append(f"- {str(record.get('key') or '')}")
        return "\n".join(lines).strip()

    def prompt_summary_for_source(
        self,
        source_text: str,
        *,
        max_terms: int = MAX_RETRIEVED_SUMMARY_TERMS,
        max_preserve_hints: int = MAX_RETRIEVED_PRESERVE_HINTS,
    ) -> str:
        source = _normalize_space(source_text)
        if not source:
            return ""

        matched_terms = [
            record
            for record in self.terms.values()
            if int(record.get("hits") or 0) >= MIN_TERM_HITS_FOR_PROMPT
            and _term_record_allowed_in_prompt(record)
            and _term_key_matches_source(str(record.get("key") or ""), source)
        ]
        matched_terms = sorted(
            matched_terms,
            key=lambda record: (
                -int(record.get("hits") or 0),
                -len(_clean_term_key(str(record.get("key") or ""))),
                str(record.get("key") or ""),
            ),
        )

        lines: list[str] = []
        if matched_terms:
            lines.append("当前块相关文档记忆：术语保持一致。")
            for record in matched_terms[:max_terms]:
                key = _clean_term_key(str(record.get("key") or ""))
                value = _clean_term_value(str(record.get("value") or ""))
                if key and value:
                    lines.append(f"- {key} => {value}")

        matched_preserve_hints = [
            record
            for record in self.preserve_hints.values()
            if _preserve_hint_matches_source(str(record.get("key") or ""), source)
        ]
        matched_preserve_hints = sorted(
            matched_preserve_hints,
            key=lambda record: (-int(record.get("hits") or 0), str(record.get("key") or "")),
        )
        if matched_preserve_hints:
            lines.append("当前块相关文档记忆：以下内容此前更适合保留技术排版。")
            for record in matched_preserve_hints[:max_preserve_hints]:
                lines.append(f"- {str(record.get('key') or '')}")
        return "\n".join(lines).strip()


class JobMemoryStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def load(self) -> JobMemory:
        if not self.path.exists():
            return JobMemory.empty(self.path)
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return JobMemory.empty(self.path)
        if not isinstance(payload, dict):
            return JobMemory.empty(self.path)
        return JobMemory.from_dict(self.path, payload)

    def save(self, memory: JobMemory) -> None:
        memory.trim()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        tmp_path.write_text(
            json.dumps(memory.to_dict(), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp_path.replace(self.path)

    def summary(self) -> str:
        with self._lock:
            return self.load().prompt_summary()

    def summary_for_source(self, source_text: str) -> str:
        with self._lock:
            return self.load().prompt_summary_for_source(source_text)

    def summary_for_batch(self, batch: list[dict]) -> str:
        return self.summary_for_source(_source_text_for_batch(batch))

    def update_from_batch(self, batch: list[dict], translated: dict[str, dict[str, Any]]) -> int:
        with self._lock:
            memory = self.load()
            changed = update_job_memory_from_batch(memory, batch=batch, translated=translated)
            if changed:
                self.save(memory)
            return changed


def update_job_memory_from_batch(
    memory: JobMemory,
    *,
    batch: list[dict],
    translated: dict[str, dict[str, Any]],
) -> int:
    changed = 0
    for item in batch:
        item_id = str(item.get("item_id") or "")
        result = translated.get(item_id) or {}
        translated_text = _normalize_space(
            result.get("protected_translated_text")
            or result.get("translated_text")
            or item.get("protected_translated_text")
            or item.get("translated_text")
            or ""
        )
        source_text = _normalize_space(
            item.get("translation_unit_protected_source_text")
            or item.get("protected_source_text")
            or item.get("source_text")
            or ""
        )
        if not source_text or not translated_text:
            continue
        for key, value in _extract_term_candidates(source_text, translated_text):
            if memory.add_term(key=key, value=value, source=item_id):
                changed += 1
        if _is_preserve_candidate(source_text):
            hint = source_text if len(source_text) <= 80 else f"{source_text[:77]}..."
            if memory.add_preserve_hint(key=hint, source=item_id):
                changed += 1
    return changed
