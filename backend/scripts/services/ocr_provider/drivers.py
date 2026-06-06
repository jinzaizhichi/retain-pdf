from __future__ import annotations

from types import SimpleNamespace

from services.mineru.job_flow import run_mineru_to_job_dir
from services.ocr_provider.local_command_driver import run_local_command_ocr_to_job_dir
from services.ocr_provider.types import OcrProviderDriver
from services.ocr_provider.types import OcrProviderResult
from services.pipeline_shared.events import emit_stage_transition


def normalize_provider_name(provider: str) -> str:
    return str(provider or "mineru").strip().lower()


def run_registered_ocr_provider(
    provider: str,
    args: SimpleNamespace,
    *,
    paddle_driver: OcrProviderDriver,
) -> OcrProviderResult:
    provider_name = normalize_provider_name(provider)
    driver = _provider_driver(provider_name, paddle_driver=paddle_driver)
    emit_stage_transition(
        stage="ocr_processing",
        substage="ocr_processing",
        message=f"开始执行 {provider_name} OCR provider 流程",
        provider=provider_name,
    )
    return driver(args)


def _provider_driver(
    provider: str,
    *,
    paddle_driver: OcrProviderDriver,
) -> OcrProviderDriver:
    if provider == "mineru":
        return _run_mineru_provider
    if provider == "paddle":
        return paddle_driver
    if provider == "local":
        return run_local_command_ocr_to_job_dir
    raise RuntimeError(f"unsupported provider-backed workflow provider: {provider}")


def _run_mineru_provider(args: SimpleNamespace) -> OcrProviderResult:
    job_dirs, source_pdf_path, provider_result_json_path, normalized_json_path = run_mineru_to_job_dir(
        args
    )
    return OcrProviderResult(
        job_dirs=job_dirs,
        source_pdf_path=source_pdf_path,
        provider_result_json_path=provider_result_json_path,
        normalized_json_path=normalized_json_path,
    )


__all__ = [
    "normalize_provider_name",
    "run_registered_ocr_provider",
]
