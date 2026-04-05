from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GlossaryEntry:
    source: str
    target: str
    note: str = ""


def build_glossary_guidance(entries: list[GlossaryEntry]) -> str:
    if not entries:
        return ""
    lines = ["Glossary preferences:"]
    for entry in entries:
        text = f"- {entry.source} -> {entry.target}"
        if entry.note.strip():
            text = f"{text} ({entry.note.strip()})"
        lines.append(text)
    return "\n".join(lines)
