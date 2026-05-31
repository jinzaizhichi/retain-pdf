from __future__ import annotations

import re

TOC_LINE_RE = re.compile(
    r"^\s*(?:(?P<number>(?:[A-Z]|\d+)(?:\.\d+)*\.?)\s+)?"
    r"(?P<title>.+?)"
    r"(?:\s*(?P<leader>\.{2,}|…+)\s*|\s{2,})"
    r"(?P<page>[ivxlcdmIVXLCDM]+|\d+[A-Za-z]?)\s*$"
)
def parse_toc_line(text: str) -> dict | None:
    raw = " ".join(str(text or "").split()).strip()
    if not raw:
        return None
    match = TOC_LINE_RE.match(raw)
    if match is None:
        return None
    title = str(match.group("title") or "").strip(" .\t")
    page_label = str(match.group("page") or "").strip()
    if not title or not page_label:
        return None
    number = str(match.group("number") or "").strip()
    level = 1
    if number:
        level = max(1, min(6, number.rstrip(".").count(".") + 1))
    return {
        "number": number,
        "title": title,
        "page_label": page_label,
        "level": level,
    }


def build_toc_entries(*, lines: list[dict], line_texts: list[str]) -> list[dict]:
    entries: list[dict] = []
    for index, text in enumerate(line_texts):
        parsed = parse_toc_line(text)
        if parsed is None:
            continue
        line = lines[index] if index < len(lines) and isinstance(lines[index], dict) else {}
        bbox = line.get("bbox")
        parsed["line_index"] = index
        if isinstance(bbox, list) and len(bbox) == 4:
            try:
                parsed["bbox"] = [float(value) for value in bbox]
            except (TypeError, ValueError):
                pass
        entries.append(parsed)
    return entries


__all__ = ["build_toc_entries", "parse_toc_line"]
