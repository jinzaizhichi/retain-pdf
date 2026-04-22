use std::path::Path;

use crate::db::Db;
use crate::error::AppError;
use crate::job_failure::classify_job_failure;
use crate::models::{
    build_artifact_links, build_artifact_manifest, build_job_actions,
    build_job_links_with_workflow, public_request_payload, ArtifactLinksView,
    JobArtifactManifestView, JobDetailView, JobProgressView, JobSnapshot, JobTimestampsView,
};
use crate::services::artifacts::list_registry_for_job;
use crate::services::jobs::readiness;
use crate::storage_paths::{resolve_markdown_path, resolve_output_pdf};

use super::helpers::{build_ocr_job_summary, job_failure_to_legacy_view};
use super::security::{redacted_error, redacted_log_tail};
use super::summary_loaders::{
    load_glossary_summary, load_invocation_summary, load_normalization_summary,
};

pub fn build_job_detail_view(data_root: &Path, job: &JobSnapshot, base_url: &str) -> JobDetailView {
    let (pdf_ready, markdown_ready, bundle_ready) =
        readiness(job, data_root, resolve_output_pdf, resolve_markdown_path);
    let duration_seconds = match (&job.started_at, &job.finished_at, &job.result) {
        (_, _, Some(result)) => Some(result.duration_seconds),
        _ => None,
    };
    let percent = match (job.progress_current, job.progress_total) {
        (Some(current), Some(total)) if total > 0 => Some((current as f64 / total as f64) * 100.0),
        _ => None,
    };
    let failure = job.failure.clone().or_else(|| classify_job_failure(job));
    JobDetailView {
        job_id: job.job_id.clone(),
        workflow: job.workflow.clone(),
        status: job.status.clone(),
        request_payload: public_request_payload(&job.request_payload),
        trace_id: job
            .artifacts
            .as_ref()
            .and_then(|item| item.trace_id.clone()),
        provider_trace_id: job
            .artifacts
            .as_ref()
            .and_then(|item| item.provider_trace_id.clone()),
        stage: job.stage.clone(),
        stage_detail: job.stage_detail.clone(),
        progress: JobProgressView {
            current: job.progress_current,
            total: job.progress_total,
            percent,
        },
        timestamps: JobTimestampsView {
            created_at: job.created_at.clone(),
            updated_at: job.updated_at.clone(),
            started_at: job.started_at.clone(),
            finished_at: job.finished_at.clone(),
            duration_seconds,
        },
        links: build_job_links_with_workflow(&job.job_id, &job.workflow, base_url),
        actions: build_job_actions(job, base_url, pdf_ready, markdown_ready, bundle_ready),
        artifacts: build_artifact_links(
            job,
            base_url,
            data_root,
            pdf_ready,
            markdown_ready,
            bundle_ready,
        ),
        ocr_job: build_ocr_job_summary(job, base_url),
        ocr_provider_diagnostics: job
            .artifacts
            .as_ref()
            .and_then(|artifacts| artifacts.ocr_provider_diagnostics.clone()),
        runtime: job.runtime.clone(),
        failure: failure.clone(),
        error: redacted_error(job),
        failure_diagnostic: failure.as_ref().map(job_failure_to_legacy_view),
        normalization_summary: load_normalization_summary(job, data_root),
        glossary_summary: load_glossary_summary(job, data_root),
        invocation: load_invocation_summary(job, data_root),
        log_tail: redacted_log_tail(job),
    }
}

pub fn build_job_artifact_links_view(
    data_root: &Path,
    job: &JobSnapshot,
    base_url: &str,
) -> ArtifactLinksView {
    let (pdf_ready, markdown_ready, bundle_ready) =
        readiness(job, data_root, resolve_output_pdf, resolve_markdown_path);
    build_artifact_links(
        job,
        base_url,
        data_root,
        pdf_ready,
        markdown_ready,
        bundle_ready,
    )
}

pub fn build_job_artifact_manifest_view(
    db: &Db,
    data_root: &Path,
    job: &JobSnapshot,
    base_url: &str,
) -> Result<JobArtifactManifestView, AppError> {
    let items = list_registry_for_job(db, data_root, job)?;
    Ok(build_artifact_manifest(job, base_url, &items))
}
