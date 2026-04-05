from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field

from services.translation.terms import AbbreviationEntry
from services.translation.terms import GlossaryEntry
from services.translation.terms import build_terms_guidance


@dataclass(frozen=True)
class PlaceholderPolicy:
    reject_unexpected_placeholders: bool = True
    reject_inventory_mismatch: bool = True
    allow_internal_keep_origin_degradation: bool = True


@dataclass(frozen=True)
class SegmentationPolicy:
    max_formula_segment_count: int = 16
    formula_segment_window_target_count: int = 8
    formula_segment_window_max_chars: int = 1200
    formula_segment_window_neighbor_context: int = 2


@dataclass(frozen=True)
class FallbackPolicy:
    plain_text_attempts: int = 4
    formula_segment_attempts: int = 4
    allow_tagged_placeholder_retry: bool = True
    allow_keep_origin_degradation: bool = True


@dataclass(frozen=True)
class TranslationControlContext:
    mode: str = "fast"
    domain_guidance: str = ""
    rule_guidance: str = ""
    request_label: str = ""
    placeholder_policy: PlaceholderPolicy = field(default_factory=PlaceholderPolicy)
    segmentation_policy: SegmentationPolicy = field(default_factory=SegmentationPolicy)
    fallback_policy: FallbackPolicy = field(default_factory=FallbackPolicy)
    glossary_entries: list[GlossaryEntry] = field(default_factory=list)
    abbreviation_entries: list[AbbreviationEntry] = field(default_factory=list)

    @property
    def terms_guidance(self) -> str:
        return build_terms_guidance(
            glossary_entries=self.glossary_entries,
            abbreviation_entries=self.abbreviation_entries,
        )

    @property
    def merged_guidance(self) -> str:
        parts = []
        for value in (self.domain_guidance, self.rule_guidance, self.terms_guidance):
            text = (value or "").strip()
            if text:
                parts.append(text)
        return "\n\n".join(parts).strip()


def build_translation_control_context(
    *,
    mode: str = "fast",
    domain_guidance: str = "",
    rule_guidance: str = "",
    request_label: str = "",
    glossary_entries: list[GlossaryEntry] | None = None,
    abbreviation_entries: list[AbbreviationEntry] | None = None,
) -> TranslationControlContext:
    return TranslationControlContext(
        mode=mode,
        domain_guidance=domain_guidance,
        rule_guidance=rule_guidance,
        request_label=request_label,
        glossary_entries=list(glossary_entries or []),
        abbreviation_entries=list(abbreviation_entries or []),
    )
