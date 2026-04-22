from __future__ import annotations

import argparse
import base64
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import requests

sys.path.append(str(Path(__file__).resolve().parents[2]))

from foundation.config import layout
from foundation.shared.job_dirs import job_dirs_from_explicit_args
from foundation.shared.stage_specs import ProviderStageSpec
from foundation.shared.stage_specs import build_stage_invocation_metadata
from foundation.shared.stage_specs import resolve_credential_ref
from foundation.shared.tee_output import enable_job_log_capture
from runtime.pipeline.book_pipeline import run_book_pipeline
from services.document_schema import DOCUMENT_SCHEMA_REPORT_FILE_NAME
from services.document_schema import adapt_path_to_document_v1_with_report
from services.document_schema import validate_saved_document_path
from services.document_schema.provider_adapters.paddle.content_extract import build_lines as build_paddle_lines
from services.document_schema.provider_adapters.paddle.content_extract import tighten_text_bbox as tighten_paddle_text_bbox
from services.document_schema.reporting import build_normalization_summary
from services.document_schema.providers import PROVIDER_PADDLE
from services.mineru.artifacts import save_json
from services.mineru.contracts import PIPELINE_SUMMARY_FILE_NAME
from services.mineru.job_flow import run_mineru_to_job_dir
from services.mineru.summary import print_pipeline_summary
from services.mineru.summary import write_pipeline_summary
from services.ocr_provider.paddle_api import PADDLE_BASE_URL
from services.ocr_provider.paddle_api import build_optional_payload as build_paddle_optional_payload
from services.ocr_provider.paddle_api import download_jsonl_result
from services.ocr_provider.paddle_api import get_paddle_token
from services.ocr_provider.paddle_api import normalize_model_name as normalize_paddle_model_name
from services.ocr_provider.paddle_api import poll_until_done as poll_paddle_until_done
from services.ocr_provider.paddle_api import submit_local_file as submit_local_paddle_file
from services.ocr_provider.paddle_api import submit_remote_url as submit_remote_paddle_url
from services.translation.llm import DEFAULT_BASE_URL
from services.translation.llm import get_api_key
from services.translation.llm import normalize_base_url
from services.translation.terms import parse_glossary_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="End-to-end provider-backed pipeline: OCR provider -> normalize -> translate -> render.",
    )
    parser.add_argument("--spec", type=str, required=True, help="Path to provider stage spec JSON.")
    return parser.parse_args()


def _serialize_glossary_entries(entries: list[dict]) -> str:
    return json.dumps(entries, ensure_ascii=False)


def _args_from_spec(spec: ProviderStageSpec) -> SimpleNamespace:
    job_dirs = spec.job_dirs
    provider = str(spec.ocr.provider or "mineru").strip().lower()
    provider_token = resolve_credential_ref(spec.ocr.credential_ref)
    return SimpleNamespace(
        provider=provider,
        file_url=spec.source.file_url,
        file_path=str(spec.source.file_path or ""),
        mineru_token=provider_token if provider == "mineru" else "",
        paddle_token=provider_token if provider == "paddle" else "",
        model_version=spec.ocr.model_version,
        paddle_api_url=spec.ocr.paddle_api_url,
        paddle_model=spec.ocr.paddle_model,
        is_ocr=spec.ocr.is_ocr,
        disable_formula=spec.ocr.disable_formula,
        disable_table=spec.ocr.disable_table,
        language=spec.ocr.language,
        page_ranges=spec.ocr.page_ranges,
        data_id=spec.ocr.data_id,
        no_cache=spec.ocr.no_cache,
        cache_tolerance=spec.ocr.cache_tolerance,
        extra_formats=spec.ocr.extra_formats,
        poll_interval=spec.ocr.poll_interval,
        poll_timeout=spec.ocr.poll_timeout,
        job_root=str(job_dirs.root),
        source_dir=str(job_dirs.source_dir),
        ocr_dir=str(job_dirs.ocr_dir),
        translated_dir=str(job_dirs.translated_dir),
        rendered_dir=str(job_dirs.rendered_dir),
        artifacts_dir=str(job_dirs.artifacts_dir),
        logs_dir=str(job_dirs.logs_dir),
        start_page=spec.translation.start_page,
        end_page=spec.translation.end_page,
        batch_size=spec.translation.batch_size,
        workers=spec.translation.workers,
        mode=spec.translation.mode,
        math_mode=spec.translation.math_mode,
        skip_title_translation=spec.translation.skip_title_translation,
        classify_batch_size=spec.translation.classify_batch_size,
        rule_profile_name=spec.translation.rule_profile_name,
        custom_rules_text=spec.translation.custom_rules_text,
        glossary_id=spec.translation.glossary_id,
        glossary_name=spec.translation.glossary_name,
        glossary_resource_entry_count=spec.translation.glossary_resource_entry_count,
        glossary_inline_entry_count=spec.translation.glossary_inline_entry_count,
        glossary_overridden_entry_count=spec.translation.glossary_overridden_entry_count,
        glossary_json=_serialize_glossary_entries(spec.translation.glossary_entries),
        api_key=resolve_credential_ref(spec.translation.credential_ref),
        model=spec.translation.model,
        base_url=spec.translation.base_url,
        render_mode=spec.render.render_mode,
        compile_workers=spec.render.compile_workers,
        typst_font_family=spec.render.typst_font_family,
        pdf_compress_dpi=spec.render.pdf_compress_dpi,
        translated_pdf_name=spec.render.translated_pdf_name,
        body_font_size_factor=spec.render.body_font_size_factor,
        body_leading_factor=spec.render.body_leading_factor,
        inner_bbox_shrink_x=spec.render.inner_bbox_shrink_x,
        inner_bbox_shrink_y=spec.render.inner_bbox_shrink_y,
        inner_bbox_dense_shrink_x=spec.render.inner_bbox_dense_shrink_x,
        inner_bbox_dense_shrink_y=spec.render.inner_bbox_dense_shrink_y,
    )


def _materialize_local_source(args: SimpleNamespace) -> None:
    raw_path = str(args.file_path or "").strip()
    if not raw_path:
        return
    source_path = Path(raw_path).resolve()
    if not source_path.exists():
        raise RuntimeError(f"file not found: {source_path}")
    source_dir = Path(args.source_dir).resolve()
    source_dir.mkdir(parents=True, exist_ok=True)
    target_path = source_dir / source_path.name
    if source_path != target_path:
        shutil.copy2(source_path, target_path)
        source_path = target_path
    args.file_path = str(source_path)


def _download_source_pdf(source_url: str, source_dir: Path) -> Path:
    source_dir.mkdir(parents=True, exist_ok=True)
    response = requests.get(source_url, timeout=300)
    response.raise_for_status()
    file_name = Path(source_url.split("?", 1)[0]).name or "source.pdf"
    if not file_name.lower().endswith(".pdf"):
        file_name = f"{file_name}.pdf"
    target_path = source_dir / file_name
    target_path.write_bytes(response.content)
    return target_path


def _job_markdown_dir(job_root: Path) -> Path:
    return job_root / "md"


def _job_markdown_images_dir(job_root: Path) -> Path:
    return _job_markdown_dir(job_root) / "images"


def _decode_paddle_markdown_image(payload: str) -> bytes:
    value = str(payload or "").strip()
    if not value:
        raise RuntimeError("empty markdown image payload")
    if value.startswith(("http://", "https://")):
        response = requests.get(value, timeout=300)
        response.raise_for_status()
        return response.content
    if value.startswith("data:") and "," in value:
        _, encoded = value.split(",", 1)
        return base64.b64decode(encoded)
    return base64.b64decode(value)


def materialize_paddle_markdown_artifacts(*, payload: dict, job_root: Path) -> Path | None:
    layout_results = payload.get("layoutParsingResults") or []
    if not isinstance(layout_results, list) or not layout_results:
        return None

    markdown_dir = _job_markdown_dir(job_root)
    images_root = _job_markdown_images_dir(job_root)
    page_texts: list[str] = []
    wrote_anything = False

    for page_index, page_payload in enumerate(layout_results, start=1):
        if not isinstance(page_payload, dict):
            continue
        markdown = page_payload.get("markdown") or {}
        if not isinstance(markdown, dict):
            continue
        text = str(markdown.get("text") or "")
        images = markdown.get("images") or {}
        if not text.strip() and not images:
            continue

        remapped_text = text
        if isinstance(images, dict) and images:
            for raw_rel_path, raw_image_payload in images.items():
                rel_path = str(raw_rel_path or "").strip().lstrip("/")
                if not rel_path:
                    continue
                # Keep the provider-returned relative path shape intact. The only rewrite we do
                # is adding a `page-N/` prefix so identical per-page image names do not collide.
                target_rel_path = Path(f"page-{page_index}") / rel_path
                target_path = images_root / target_rel_path
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(_decode_paddle_markdown_image(str(raw_image_payload or "")))
                normalized_source = rel_path.replace("\\", "/")
                normalized_target = target_rel_path.as_posix()
                remapped_text = remapped_text.replace(normalized_source, normalized_target)
                wrote_anything = True

        if remapped_text.strip():
            page_texts.append(remapped_text.strip())
            wrote_anything = True

    if not wrote_anything:
        return None

    markdown_dir.mkdir(parents=True, exist_ok=True)
    full_md_path = markdown_dir / "full.md"
    full_md_path.write_text("\n\n".join(page_texts).strip() + "\n", encoding="utf-8")
    return full_md_path


def _save_normalized_document_for_paddle(
    *,
    provider_result_json_path: Path,
    source_pdf_path: Path,
    normalized_json_path: Path,
    normalized_report_json_path: Path,
    document_id: str,
    provider_version: str,
) -> None:
    normalized_document, normalization_report = adapt_path_to_document_v1_with_report(
        source_json_path=provider_result_json_path,
        document_id=document_id,
        provider=PROVIDER_PADDLE,
        provider_version=provider_version,
    )
    normalized_document = _rescale_document_geometry_to_pdf(normalized_document, source_pdf_path)
    normalized_document = _post_rescale_rebuild_paddle_text_geometry(normalized_document)
    save_json(normalized_json_path, normalized_document)
    save_json(normalized_report_json_path, normalization_report)
    report = validate_saved_document_path(normalized_json_path)
    normalization_summary = build_normalization_summary(normalization_report)
    print(
        "normalized document validated: "
        f"schema={report['schema']} "
        f"version={report['schema_version']} "
        f"pages={report['page_count']} "
        f"blocks={report['block_count']} "
        f"path={normalized_json_path}",
        flush=True,
    )
    print(
        "normalized document report: "
        f"provider={normalization_summary['provider']} "
        f"detected={normalization_summary['detected_provider']} "
        f"pages_observed={normalization_summary['pages_observed']} "
        f"blocks_observed={normalization_summary['blocks_observed']} "
        f"defaulted_document_fields={normalization_summary['defaulted_document_fields']} "
        f"defaulted_page_fields={normalization_summary['defaulted_page_fields']} "
        f"defaulted_block_fields={normalization_summary['defaulted_block_fields']} "
        f"path={normalized_report_json_path}",
        flush=True,
    )


def _rescale_document_geometry_to_pdf(document: dict, source_pdf_path: Path) -> dict:
    import fitz

    pdf = fitz.open(source_pdf_path)
    try:
        pages = document.get("pages", []) or []
        for page_index, page in enumerate(pages):
            if page_index >= len(pdf):
                break
            pdf_page = pdf[page_index]
            pdf_w = float(pdf_page.rect.width)
            pdf_h = float(pdf_page.rect.height)
            raw_w = float(page.get("width", 0) or 0)
            raw_h = float(page.get("height", 0) or 0)
            if raw_w <= 0 or raw_h <= 0:
                page["width"] = pdf_w
                page["height"] = pdf_h
                continue
            scale_x = pdf_w / raw_w
            scale_y = pdf_h / raw_h
            page["width"] = pdf_w
            page["height"] = pdf_h
            for block in page.get("blocks", []) or []:
                block["bbox"] = _scale_bbox(block.get("bbox", []), scale_x, scale_y)
                for line in block.get("lines", []) or []:
                    line["bbox"] = _scale_bbox(line.get("bbox", []), scale_x, scale_y)
                    for span in line.get("spans", []) or []:
                        span["bbox"] = _scale_bbox(span.get("bbox", []), scale_x, scale_y)
                for segment in block.get("segments", []) or []:
                    if isinstance(segment, dict):
                        segment["bbox"] = _scale_bbox(segment.get("bbox", []), scale_x, scale_y)
                source = block.get("source") or {}
                if source:
                    source["raw_bbox"] = _scale_bbox(source.get("raw_bbox", []), scale_x, scale_y)
                metadata = block.get("metadata") or {}
                if metadata:
                    metadata["raw_polygon"] = _scale_point_list(metadata.get("raw_polygon", []), scale_x, scale_y)
                    metadata["layout_det_polygon"] = _scale_point_list(metadata.get("layout_det_polygon", []), scale_x, scale_y)
    finally:
        pdf.close()
    return document


def _scale_bbox(value: list[float], scale_x: float, scale_y: float) -> list[float]:
    if not isinstance(value, list) or len(value) != 4:
        return value
    return [
        round(float(value[0]) * scale_x, 3),
        round(float(value[1]) * scale_y, 3),
        round(float(value[2]) * scale_x, 3),
        round(float(value[3]) * scale_y, 3),
    ]


def _scale_point_list(value: list, scale_x: float, scale_y: float) -> list:
    if not isinstance(value, list):
        return value
    scaled = []
    for item in value:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            scaled.append([round(float(item[0]) * scale_x, 3), round(float(item[1]) * scale_y, 3)])
        else:
            scaled.append(item)
    return scaled


def _post_rescale_rebuild_paddle_text_geometry(document: dict) -> dict:
    for page in document.get("pages", []) or []:
        for block in page.get("blocks", []) or []:
            block_type = str(block.get("type", "") or "")
            sub_type = str(block.get("sub_type", "") or "")
            text = str(block.get("text", "") or "")
            raw_label = str((block.get("source") or {}).get("raw_type", "") or "")
            original_bbox = list(block.get("bbox", []) or [])
            tightened_bbox = tighten_paddle_text_bbox(
                bbox=original_bbox,
                text=text,
                block_type=block_type,
                sub_type=sub_type,
            )
            if tightened_bbox != original_bbox:
                block["bbox"] = tightened_bbox
                source_payload = block.get("source") or {}
                if source_payload:
                    source_payload["raw_bbox"] = tightened_bbox
                metadata = block.get("metadata") or {}
                metadata["provider_bbox_tightened"] = True
                metadata["provider_bbox_original"] = original_bbox
                block["metadata"] = metadata
            rebuilt_lines = build_paddle_lines(
                bbox=block.get("bbox", []),
                segments=block.get("segments", []) or [],
                text=text,
                raw_label=raw_label,
                block_type=block_type,
                sub_type=sub_type,
            )
            if rebuilt_lines:
                block["lines"] = rebuilt_lines
    return document


def run_paddle_to_job_dir(args: SimpleNamespace) -> tuple[Path, Path, Path, Path]:
    paddle_token = get_paddle_token(explicit_value=args.paddle_token)
    if not paddle_token:
        raise RuntimeError("Missing Paddle token. Set RETAIN_PADDLE_API_TOKEN or backend/scripts/.env/paddle.env.")
    job_dirs = job_dirs_from_explicit_args(args)
    provider_result_json_path = job_dirs.ocr_dir / "result.json"
    normalized_json_path = job_dirs.ocr_dir / "normalized" / "document.v1.json"
    normalized_report_json_path = job_dirs.ocr_dir / "normalized" / DOCUMENT_SCHEMA_REPORT_FILE_NAME
    source_dir = job_dirs.source_dir
    if str(args.file_url or "").strip():
        source_pdf_path = _download_source_pdf(str(args.file_url).strip(), source_dir)
        task_id, trace_id = submit_remote_paddle_url(
            token=paddle_token,
            source_url=str(args.file_url).strip(),
            model=normalize_paddle_model_name(args.paddle_model),
            optional_payload=build_paddle_optional_payload(args.paddle_model),
            base_url=args.paddle_api_url or PADDLE_BASE_URL,
        )
    else:
        source_pdf_path = Path(args.file_path).resolve()
        task_id, trace_id = submit_local_paddle_file(
            token=paddle_token,
            file_path=source_pdf_path,
            model=normalize_paddle_model_name(args.paddle_model),
            optional_payload=build_paddle_optional_payload(args.paddle_model),
            base_url=args.paddle_api_url or PADDLE_BASE_URL,
        )
    print(f"job dir: {job_dirs.root}", flush=True)
    print(f"task_id: {task_id}", flush=True)
    if trace_id:
        print(f"trace_id: {trace_id}", flush=True)
    _, jsonl_url = poll_paddle_until_done(
        token=paddle_token,
        job_id=task_id,
        poll_interval=args.poll_interval,
        poll_timeout=args.poll_timeout,
        base_url=args.paddle_api_url or PADDLE_BASE_URL,
    )
    payload = download_jsonl_result(jsonl_url=jsonl_url)
    meta = dict(payload.get("_meta") or {})
    meta["provider"] = "paddle"
    meta["taskId"] = task_id
    meta["jsonlUrl"] = jsonl_url
    if trace_id:
        meta["traceId"] = trace_id
    payload["_meta"] = meta
    save_json(provider_result_json_path, payload)
    markdown_path = materialize_paddle_markdown_artifacts(payload=payload, job_root=job_dirs.root)
    if markdown_path is not None:
        print(f"published markdown: {markdown_path}", flush=True)
    _save_normalized_document_for_paddle(
        provider_result_json_path=provider_result_json_path,
        source_pdf_path=source_pdf_path,
        normalized_json_path=normalized_json_path,
        normalized_report_json_path=normalized_report_json_path,
        document_id=job_dirs.root.name,
        provider_version=normalize_paddle_model_name(args.paddle_model),
    )
    print(f"source: {job_dirs.source_dir}", flush=True)
    print(f"ocr: {job_dirs.ocr_dir}", flush=True)
    print(f"translated: {job_dirs.translated_dir}", flush=True)
    print(f"rendered: {job_dirs.rendered_dir}", flush=True)
    print(f"artifacts: {job_dirs.artifacts_dir}", flush=True)
    print(f"logs: {job_dirs.logs_dir}", flush=True)
    return job_dirs.root, source_pdf_path, provider_result_json_path, normalized_json_path


def main() -> None:
    parsed = parse_args()
    spec = ProviderStageSpec.load(Path(parsed.spec))
    stage_spec_schema_version = spec.schema_version
    args = _args_from_spec(spec)
    _materialize_local_source(args)
    job_dirs = job_dirs_from_explicit_args(args)
    enable_job_log_capture(job_dirs.logs_dir, prefix="provider-pipeline")
    layout.apply_layout_tuning(
        body_font_size_factor=args.body_font_size_factor,
        body_leading_factor=args.body_leading_factor,
        inner_bbox_shrink_x=args.inner_bbox_shrink_x,
        inner_bbox_shrink_y=args.inner_bbox_shrink_y,
        inner_bbox_dense_shrink_x=args.inner_bbox_dense_shrink_x,
        inner_bbox_dense_shrink_y=args.inner_bbox_dense_shrink_y,
    )
    provider = str(args.provider or "mineru").strip().lower()
    if provider == "mineru":
        job_dirs, source_pdf_path, layout_json_path, normalized_json_path = run_mineru_to_job_dir(args)
    elif provider == "paddle":
        _, source_pdf_path, layout_json_path, normalized_json_path = run_paddle_to_job_dir(args)
        job_dirs = job_dirs_from_explicit_args(args)
    else:
        raise RuntimeError(f"unsupported provider-backed workflow provider: {provider}")

    normalization_report_path = normalized_json_path.with_name(DOCUMENT_SCHEMA_REPORT_FILE_NAME)
    translation_source_json_path = normalized_json_path
    translations_dir = job_dirs.translated_dir
    translated_pdf_name = args.translated_pdf_name.strip() or f"{source_pdf_path.stem}-translated.pdf"
    output_pdf_path = job_dirs.rendered_dir / translated_pdf_name
    api_key = get_api_key(
        args.api_key,
        required=normalize_base_url(args.base_url) == normalize_base_url(DEFAULT_BASE_URL),
    )
    result = run_book_pipeline(
        source_json_path=translation_source_json_path,
        source_pdf_path=source_pdf_path,
        output_dir=translations_dir,
        output_pdf_path=output_pdf_path,
        api_key=api_key,
        start_page=args.start_page,
        end_page=args.end_page,
        batch_size=args.batch_size,
        workers=args.workers,
        model=args.model,
        base_url=args.base_url,
        mode=args.mode,
        math_mode=args.math_mode,
        classify_batch_size=args.classify_batch_size,
        skip_title_translation=args.skip_title_translation,
        render_mode=args.render_mode,
        rule_profile_name=args.rule_profile_name,
        custom_rules_text=args.custom_rules_text,
        glossary_id=args.glossary_id,
        glossary_name=args.glossary_name,
        glossary_resource_entry_count=args.glossary_resource_entry_count,
        glossary_inline_entry_count=args.glossary_inline_entry_count,
        glossary_overridden_entry_count=args.glossary_overridden_entry_count,
        glossary_entries=parse_glossary_json(args.glossary_json),
        compile_workers=args.compile_workers or None,
        typst_font_family=args.typst_font_family,
        pdf_compress_dpi=args.pdf_compress_dpi,
        invocation=build_stage_invocation_metadata(
            stage="provider",
            stage_spec_schema_version=stage_spec_schema_version,
        ),
    )
    summary_path = job_dirs.artifacts_dir / PIPELINE_SUMMARY_FILE_NAME
    write_pipeline_summary(
        summary_path=summary_path,
        job_root=job_dirs.root,
        source_pdf_path=source_pdf_path,
        layout_json_path=layout_json_path,
        normalized_json_path=normalized_json_path,
        normalization_report_path=normalization_report_path,
        source_json_path=translation_source_json_path,
        result=result,
        mode=args.mode,
        model=args.model,
        base_url=args.base_url,
        render_mode=args.render_mode,
        pdf_compress_dpi=args.pdf_compress_dpi,
        invocation=build_stage_invocation_metadata(
            stage="provider",
            stage_spec_schema_version=stage_spec_schema_version,
        ),
    )
    print_pipeline_summary(
        job_root=job_dirs.root,
        source_pdf_path=source_pdf_path,
        layout_json_path=layout_json_path,
        normalized_json_path=normalized_json_path,
        normalization_report_path=normalization_report_path,
        source_json_path=translation_source_json_path,
        summary_path=summary_path,
        result=result,
    )


if __name__ == "__main__":
    main()
