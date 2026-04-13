import re

from services.document_schema.semantics import is_metadata_semantic


EDITORIAL_PREFIX_RE = re.compile(
    r"^(received|revised|accepted|published|available online|online publication date|supporting information|editor|editors)\b",
    re.I,
)
EDITORIAL_TOKEN_RE = re.compile(
    r"^(crossmark|open access|graphical abstract|highlights|supplementary data|supplemental data|corrigendum|erratum)$",
    re.I,
)
COPYRIGHT_RE = re.compile(r"\b(copyright|all rights reserved|periodicals)\b", re.I)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
AUTHOR_MARKER_RE = re.compile(r"[†‡§]|corresponding author", re.I)
URL_LIKE_RE = re.compile(
    r"^(?:(?:https?://|ftp://|www\.)\S+|(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?:/[A-Za-z0-9._~:/?#\[\]@!$&()*+,;=%-]*)?)$",
    re.I,
)
WORD_TOKEN_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9]+(?:[.'`´/-][A-Za-zÀ-ÖØ-öø-ÿ0-9]+)*")
MAX_METADATA_FRAGMENT_WORDS = 9


def _normalized_text(item: dict) -> str:
    return " ".join((item.get("source_text") or "").split())


def _line_count(item: dict) -> int:
    return len(item.get("lines", []))


def _word_count(text: str) -> int:
    return len(WORD_TOKEN_RE.findall(text))


def _looks_like_editorial_metadata(text: str) -> bool:
    stripped = text.strip()
    return bool(EDITORIAL_PREFIX_RE.match(stripped) or EDITORIAL_TOKEN_RE.fullmatch(stripped))


def looks_like_url_fragment(text: str) -> bool:
    stripped = text.strip().strip("()[]<>\"'“”‘’,;")
    if not stripped or any(ch.isspace() for ch in stripped):
        return False
    return bool(URL_LIKE_RE.fullmatch(stripped))


def _looks_like_supporting_information(text: str, item: dict) -> bool:
    return _line_count(item) <= 2 and len(text) <= 64 and text.strip().lower() == "supporting information"


def looks_like_safe_nontranslatable_metadata(item: dict) -> bool:
    if item.get("block_type") not in {"text", "title", "list"}:
        return False

    metadata = item.get("metadata") or {}
    if is_metadata_semantic(metadata):
        return True

    text = _normalized_text(item)
    if not text:
        return False

    return (
        _looks_like_editorial_metadata(text)
        or _looks_like_supporting_information(text, item)
        or looks_like_url_fragment(text)
        or bool(COPYRIGHT_RE.search(text))
        or bool(EMAIL_RE.search(text))
        or bool(AUTHOR_MARKER_RE.search(text))
    )


def looks_like_nontranslatable_metadata(item: dict) -> bool:
    return looks_like_safe_nontranslatable_metadata(item)


def should_skip_metadata_fragment(item: dict) -> bool:
    if item.get("block_type") not in {"text", "title", "list"}:
        return False
    if not item.get("should_translate", True):
        return False

    text = _normalized_text(item)
    if not text:
        return False
    if _word_count(text) > MAX_METADATA_FRAGMENT_WORDS and not looks_like_safe_nontranslatable_metadata(item):
        return False
    return looks_like_safe_nontranslatable_metadata(item)


def find_metadata_fragment_item_ids(payload: list[dict]) -> set[str]:
    skipped: set[str] = set()
    for item in payload:
        if should_skip_metadata_fragment(item):
            skipped.add(item.get("item_id", ""))
    return skipped


__all__ = [
    "find_metadata_fragment_item_ids",
    "looks_like_url_fragment",
    "looks_like_safe_nontranslatable_metadata",
    "looks_like_nontranslatable_metadata",
    "should_skip_metadata_fragment",
]
