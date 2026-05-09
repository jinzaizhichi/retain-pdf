use anyhow::{anyhow, Result};

use crate::job_events::persist_runtime_job_with_resources;
use crate::models::{now_iso, JobArtifacts, JobRuntimeState, JobStatusKind};
use crate::storage_paths::{build_job_paths, resolve_data_path};

#[path = "translation_flow_child.rs"]
mod translation_flow_child;
#[path = "translation_flow_stage.rs"]
mod translation_flow_stage;
#[path = "translation_flow_support.rs"]
mod translation_flow_support;

use self::translation_flow_child::{
    create_ocr_child_job, load_translation_upload_source, mark_parent_ocr_submitting,
};
use self::translation_flow_stage::{
    record_ocr_child_finished, run_render_stage_after_translation, run_translation_stage,
};
use self::translation_flow_support::{finalize_parent_after_ocr, OcrContinuation};
use super::ocr_flow::{execute_ocr_job, sync_parent_with_ocr_child};
use super::{attach_job_paths, ProcessRuntimeDeps};

pub(super) async fn run_translation_job_with_ocr(
    deps: ProcessRuntimeDeps,
    parent_job: JobRuntimeState,
) -> Result<JobRuntimeState> {
    if !parent_job
        .request_payload
        .source
        .artifact_job_id
        .trim()
        .is_empty()
    {
        return run_book_job_from_artifacts(deps, parent_job).await;
    }
    run_job_with_ocr(deps, parent_job, OcrContinuation::FullPipeline).await
}

pub(super) async fn run_translate_only_job_with_ocr(
    deps: ProcessRuntimeDeps,
    parent_job: JobRuntimeState,
) -> Result<JobRuntimeState> {
    if !parent_job
        .request_payload
        .source
        .artifact_job_id
        .trim()
        .is_empty()
    {
        return run_translate_only_job_from_artifacts(deps, parent_job).await;
    }
    run_job_with_ocr(deps, parent_job, OcrContinuation::TranslateOnly).await
}

async fn run_translate_only_job_from_artifacts(
    deps: ProcessRuntimeDeps,
    job: JobRuntimeState,
) -> Result<JobRuntimeState> {
    let source_job_id = job
        .request_payload
        .source
        .artifact_job_id
        .trim()
        .to_string();
    let (job, _source_pdf_path) =
        prepare_job_from_ocr_artifacts(&deps, job, &source_job_id, "继续翻译").await?;
    let job_paths = build_job_paths(&deps.config.output_root, &job.job_id)?;
    run_translation_stage(&deps, job, &job_paths)
        .await
        .map(|result| result.job)
}

async fn run_book_job_from_artifacts(
    deps: ProcessRuntimeDeps,
    job: JobRuntimeState,
) -> Result<JobRuntimeState> {
    let source_job_id = job
        .request_payload
        .source
        .artifact_job_id
        .trim()
        .to_string();
    let (job, _source_pdf_path) =
        prepare_job_from_ocr_artifacts(&deps, job, &source_job_id, "继续翻译并渲染").await?;
    let job_paths = build_job_paths(&deps.config.output_root, &job.job_id)?;
    let translation_stage = run_translation_stage(&deps, job, &job_paths).await?;
    let translated_job = translation_stage.job;
    let source_pdf_path = translation_stage.source_pdf_path;
    if !matches!(translated_job.status, JobStatusKind::Succeeded) {
        return Ok(translated_job);
    }
    run_render_stage_after_translation(deps, translated_job, &job_paths, &source_pdf_path).await
}

async fn prepare_job_from_ocr_artifacts(
    deps: &ProcessRuntimeDeps,
    mut job: JobRuntimeState,
    source_job_id: &str,
    action_label: &str,
) -> Result<(JobRuntimeState, std::path::PathBuf)> {
    let source_job = deps.db.get_job(&source_job_id)?;
    let source_artifacts = source_job
        .artifacts
        .as_ref()
        .ok_or_else(|| anyhow!("artifact source job has no artifacts: {source_job_id}"))?;
    let source_pdf_path = source_artifacts
        .source_pdf
        .as_deref()
        .ok_or_else(|| anyhow!("artifact source job is missing source_pdf: {source_job_id}"))
        .and_then(|raw| resolve_data_path(&deps.config.data_root, raw))?;
    let normalized_path = source_artifacts
        .normalized_document_json
        .as_deref()
        .ok_or_else(|| {
            anyhow!("artifact source job is missing normalized_document_json: {source_job_id}")
        })
        .and_then(|raw| resolve_data_path(&deps.config.data_root, raw))?;
    let layout_json_path = source_artifacts
        .layout_json
        .as_deref()
        .map(|raw| resolve_data_path(&deps.config.data_root, raw))
        .transpose()?;
    if !source_pdf_path.exists() {
        return Err(anyhow!(
            "source_pdf not found for artifact job {source_job_id}: {}",
            source_pdf_path.display()
        ));
    }
    if !normalized_path.exists() {
        return Err(anyhow!(
            "normalized_document_json not found for artifact job {source_job_id}: {}",
            normalized_path.display()
        ));
    }

    let job_paths = build_job_paths(&deps.config.output_root, &job.job_id)?;
    attach_job_paths(&mut job, &job_paths);
    copy_ocr_checkpoint_artifacts(&mut job, &source_job_id, source_artifacts);
    if let Some(artifacts) = job.artifacts.as_mut() {
        artifacts.source_pdf = Some(source_pdf_path.to_string_lossy().to_string());
        artifacts.normalized_document_json = Some(normalized_path.to_string_lossy().to_string());
        artifacts.layout_json = layout_json_path
            .as_ref()
            .map(|path| path.to_string_lossy().to_string());
    }
    job.stage_detail = Some(format!(
        "正在基于任务 {source_job_id} 的 OCR 产物{action_label}"
    ));
    persist_runtime_job_with_resources(
        deps.db.as_ref(),
        &deps.config.data_root,
        &deps.config.output_root,
        &job,
    )?;
    Ok((job, source_pdf_path))
}

fn copy_ocr_checkpoint_artifacts(
    job: &mut JobRuntimeState,
    source_job_id: &str,
    source_artifacts: &JobArtifacts,
) {
    let artifacts = job.artifacts.get_or_insert_with(JobArtifacts::default);
    artifacts.ocr_job_id = source_artifacts
        .ocr_job_id
        .clone()
        .or_else(|| Some(source_job_id.to_string()));
    artifacts.ocr_status = source_artifacts.ocr_status.clone();
    artifacts.ocr_trace_id = source_artifacts.ocr_trace_id.clone();
    artifacts.ocr_provider_trace_id = source_artifacts.ocr_provider_trace_id.clone();
    artifacts.source_pdf = source_artifacts.source_pdf.clone();
    artifacts.layout_json = source_artifacts.layout_json.clone();
    artifacts.normalized_document_json = source_artifacts.normalized_document_json.clone();
    artifacts.normalization_report_json = source_artifacts.normalization_report_json.clone();
    artifacts.provider_raw_dir = source_artifacts.provider_raw_dir.clone();
    artifacts.provider_zip = source_artifacts.provider_zip.clone();
    artifacts.provider_summary_json = source_artifacts.provider_summary_json.clone();
    artifacts.schema_version = source_artifacts.schema_version.clone();
    artifacts.trace_id = artifacts
        .trace_id
        .clone()
        .or(source_artifacts.trace_id.clone());
    artifacts.provider_trace_id = source_artifacts.provider_trace_id.clone();
    artifacts.ocr_provider_diagnostics = source_artifacts.ocr_provider_diagnostics.clone();
}

async fn run_job_with_ocr(
    deps: ProcessRuntimeDeps,
    mut parent_job: JobRuntimeState,
    continuation: OcrContinuation,
) -> Result<JobRuntimeState> {
    let parent_job_paths = build_job_paths(&deps.config.output_root, &parent_job.job_id)?;
    attach_job_paths(&mut parent_job, &parent_job_paths);
    let source = load_translation_upload_source(deps.db.as_ref(), &parent_job)?;
    mark_parent_ocr_submitting(&deps, &mut parent_job)?;
    let ocr_child = create_ocr_child_job(&deps, &mut parent_job, &parent_job_paths, &source)?;

    let ocr_finished = execute_ocr_job(
        deps.clone(),
        ocr_child,
        Some(parent_job.job_id.clone()),
        Some(parent_job.job_id.clone()),
    )
    .await?;
    persist_runtime_job_with_resources(
        deps.db.as_ref(),
        &deps.config.data_root,
        &deps.config.output_root,
        &ocr_finished,
    )?;
    sync_parent_with_ocr_child(&mut parent_job, &ocr_finished);
    record_ocr_child_finished(&deps, &parent_job, &ocr_finished);

    if finalize_parent_after_ocr(&mut parent_job, &ocr_finished, now_iso())? {
        return Ok(parent_job);
    }

    let translation_stage = run_translation_stage(&deps, parent_job, &parent_job_paths).await?;
    let translated_job = translation_stage.job;
    let source_pdf_path = translation_stage.source_pdf_path;

    if !matches!(translated_job.status, JobStatusKind::Succeeded) {
        return Ok(translated_job);
    }
    match continuation {
        OcrContinuation::TranslateOnly => Ok(translated_job),
        OcrContinuation::FullPipeline => {
            run_render_stage_after_translation(
                deps,
                translated_job,
                &parent_job_paths,
                &source_pdf_path,
            )
            .await
        }
    }
}
