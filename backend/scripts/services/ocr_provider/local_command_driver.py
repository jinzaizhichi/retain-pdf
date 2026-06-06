from __future__ import annotations

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

from foundation.shared.job_dirs import job_dirs_from_explicit_args
from services.document_schema import DOCUMENT_SCHEMA_REPORT_FILE_NAME
from services.document_schema import validate_saved_document_path
from services.ocr_provider.types import OcrProviderResult
from services.pipeline_shared.events import emit_stage_progress
from services.pipeline_shared.io import save_json

LOCAL_OCR_COMMAND_ENV = "RETAIN_LOCAL_OCR_COMMAND"


def run_local_command_ocr_to_job_dir(args: SimpleNamespace) -> OcrProviderResult:
    command = str(os.environ.get(LOCAL_OCR_COMMAND_ENV, "") or "").strip()
    if not command:
        raise RuntimeError(f"local OCR provider requires {LOCAL_OCR_COMMAND_ENV}")

    source_pdf_path = Path(str(args.file_path or "")).resolve()
    if not source_pdf_path.exists():
        raise RuntimeError(
            f"local OCR provider requires an existing local file_path: {source_pdf_path}"
        )

    job_dirs = job_dirs_from_explicit_args(args)
    provider_result_json_path = job_dirs.ocr_dir / "result.json"
    normalized_json_path = job_dirs.ocr_dir / "normalized" / "document.v1.json"
    normalized_report_json_path = job_dirs.ocr_dir / "normalized" / DOCUMENT_SCHEMA_REPORT_FILE_NAME
    normalized_json_path.parent.mkdir(parents=True, exist_ok=True)
    provider_result_json_path.parent.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.update(
        {
            "RETAIN_OCR_PROVIDER": "local",
            "RETAIN_OCR_SOURCE_PDF": str(source_pdf_path),
            "RETAIN_OCR_JOB_ROOT": str(job_dirs.root),
            "RETAIN_OCR_SOURCE_DIR": str(job_dirs.source_dir),
            "RETAIN_OCR_DIR": str(job_dirs.ocr_dir),
            "RETAIN_OCR_PROVIDER_RESULT_JSON": str(provider_result_json_path),
            "RETAIN_OCR_NORMALIZED_DOCUMENT_JSON": str(normalized_json_path),
            "RETAIN_OCR_NORMALIZATION_REPORT_JSON": str(normalized_report_json_path),
        }
    )

    emit_stage_progress(
        stage="ocr_processing",
        substage="local_provider",
        message="正在执行本地 OCR provider",
        stage_detail="正在执行本地 OCR provider",
        provider="local",
    )
    completed = subprocess.run(
        command,
        shell=True,
        cwd=str(job_dirs.root),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.stdout:
        print(
            completed.stdout,
            end="" if completed.stdout.endswith("\n") else "\n",
            flush=True,
        )
    if completed.stderr:
        print(
            completed.stderr,
            end="" if completed.stderr.endswith("\n") else "\n",
            flush=True,
        )
    if completed.returncode != 0:
        raise RuntimeError(f"local OCR provider command failed with exit code {completed.returncode}")
    if not normalized_json_path.exists():
        raise RuntimeError(
            "local OCR provider did not write normalized document: "
            f"{normalized_json_path}"
        )

    validation = validate_saved_document_path(normalized_json_path)
    if not normalized_report_json_path.exists():
        save_json(
            normalized_report_json_path,
            {
                "provider": "local",
                "detected_provider": "local",
                "provider_was_explicit": True,
                "validation": validation,
            },
        )
    if not provider_result_json_path.exists():
        save_json(
            provider_result_json_path,
            {
                "provider": "local",
                "source_pdf": str(source_pdf_path),
                "normalized_document_json": str(normalized_json_path),
            },
        )

    emit_stage_progress(
        stage="ocr_processing",
        substage="local_provider",
        message="本地 OCR provider 已完成",
        stage_detail="本地 OCR provider 已完成",
        provider="local",
        progress_current=validation.get("page_count"),
        progress_total=validation.get("page_count"),
        payload={"progress_unit": "page"},
    )
    return OcrProviderResult(
        job_dirs=job_dirs,
        source_pdf_path=source_pdf_path,
        provider_result_json_path=provider_result_json_path,
        normalized_json_path=normalized_json_path,
    )


__all__ = [
    "LOCAL_OCR_COMMAND_ENV",
    "run_local_command_ocr_to_job_dir",
]
