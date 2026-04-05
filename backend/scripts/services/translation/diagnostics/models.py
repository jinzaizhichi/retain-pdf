from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field


@dataclass(frozen=True)
class TranslationDiagnostic:
    kind: str
    item_id: str = ""
    page_idx: int | None = None
    stage: str = "translation"
    severity: str = "warning"
    message: str = ""
    retryable: bool = True
    details: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class TranslationDiagnosticsCollector:
    diagnostics: list[TranslationDiagnostic] = field(default_factory=list)

    def add(self, diagnostic: TranslationDiagnostic) -> TranslationDiagnostic:
        self.diagnostics.append(diagnostic)
        return diagnostic

    def emit(
        self,
        *,
        kind: str,
        item_id: str = "",
        page_idx: int | None = None,
        stage: str = "translation",
        severity: str = "warning",
        message: str = "",
        retryable: bool = True,
        details: dict[str, object] | None = None,
    ) -> TranslationDiagnostic:
        return self.add(
            TranslationDiagnostic(
                kind=kind,
                item_id=item_id,
                page_idx=page_idx,
                stage=stage,
                severity=severity,
                message=message,
                retryable=retryable,
                details=details or {},
            )
        )

    def extend(self, diagnostics: list[TranslationDiagnostic]) -> None:
        self.diagnostics.extend(diagnostics)

    def as_dicts(self) -> list[dict[str, object]]:
        return [item.to_dict() for item in self.diagnostics]
