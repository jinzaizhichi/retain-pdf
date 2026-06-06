from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

from foundation.shared.job_dirs import JobDirs


@dataclass(frozen=True)
class OcrProviderResult:
    job_dirs: JobDirs
    source_pdf_path: Path
    provider_result_json_path: Path
    normalized_json_path: Path


OcrProviderDriver = Callable[[SimpleNamespace], OcrProviderResult]


__all__ = [
    "OcrProviderDriver",
    "OcrProviderResult",
]
