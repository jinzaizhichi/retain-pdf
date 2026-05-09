from __future__ import annotations

import fitz


def _normalize_toc_levels(toc: list[list]) -> list[list]:
    normalized: list[list] = []
    previous_level = 0
    for entry in toc:
        if len(entry) < 3:
            continue
        level = int(entry[0] or 1)
        if not normalized:
            level = 1
        else:
            level = max(1, min(level, previous_level + 1))
        normalized.append([level, entry[1], entry[2]])
        previous_level = level
    return normalized


def copy_toc(
    source_doc: fitz.Document,
    target_doc: fitz.Document,
    *,
    start_page: int = 0,
    end_page: int | None = None,
) -> int:
    try:
        source_toc = source_doc.get_toc()
    except Exception:
        return 0
    if not source_toc:
        return 0

    last_source_page = len(source_doc) - 1
    first = max(0, start_page)
    last = last_source_page if end_page is None or end_page < 0 else min(end_page, last_source_page)
    if first > last:
        return 0

    remapped: list[list] = []
    target_page_count = len(target_doc)
    for level, title, page, *_rest in source_toc:
        source_page = int(page or 0) - 1
        if not (first <= source_page <= last):
            continue
        target_page = source_page - first + 1
        if not (1 <= target_page <= target_page_count):
            continue
        remapped.append([level, title, target_page])

    remapped = _normalize_toc_levels(remapped)
    if not remapped:
        return 0
    try:
        target_doc.set_toc(remapped)
    except Exception:
        return 0
    return len(remapped)
