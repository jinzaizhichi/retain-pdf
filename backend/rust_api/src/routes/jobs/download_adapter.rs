use std::path::{Path, PathBuf};

use axum::http::HeaderMap;
use axum::response::Response;

use crate::error::AppError;
use crate::models::{JobSnapshot, MarkdownQuery};
use crate::routes::job_helpers::stream_file;

use super::common::JobsRouteDeps;

fn jobs_facade_ref<'a>(deps: &'a JobsRouteDeps<'a>) -> crate::services::jobs::JobsFacade<'a> {
    deps.jobs.clone()
}

async fn download_job_file(
    data_root: &Path,
    job: &JobSnapshot,
    job_id: &str,
    resolve_path: impl Fn(&JobSnapshot, &Path) -> Option<PathBuf>,
    not_ready_label: &str,
    content_type: &str,
) -> Result<Response, AppError> {
    let path = resolve_path(job, data_root)
        .ok_or_else(|| AppError::not_found(format!("{not_ready_label}: {job_id}")))?;
    stream_file(path, content_type, None).await
}

fn load_job_for_download(
    deps: &JobsRouteDeps<'_>,
    job_id: &str,
    ocr_only: bool,
) -> Result<JobSnapshot, AppError> {
    jobs_facade_ref(deps).load_supported_job_snapshot(job_id, ocr_only)
}

pub async fn download_document_response(
    deps: &JobsRouteDeps<'_>,
    job_id: &str,
    ocr_only: bool,
    resolve_path: impl Fn(&JobSnapshot, &Path) -> Option<PathBuf>,
    not_ready_label: &str,
    content_type: &str,
) -> Result<Response, AppError> {
    let job = load_job_for_download(deps, job_id, ocr_only)?;
    download_job_file(
        deps.data_root,
        &job,
        job_id,
        resolve_path,
        not_ready_label,
        content_type,
    )
    .await
}

pub async fn markdown_response(
    deps: &JobsRouteDeps<'_>,
    headers: &HeaderMap,
    job_id: String,
    query: &MarkdownQuery,
) -> Result<Response, AppError> {
    jobs_facade_ref(deps)
        .markdown_response(headers, job_id, query.raw)
        .await
}

pub async fn markdown_image_response(
    deps: &JobsRouteDeps<'_>,
    job_id: &str,
    path: &str,
) -> Result<Response, AppError> {
    jobs_facade_ref(deps)
        .markdown_image_response(job_id, path)
        .await
}

pub async fn bundle_response(deps: &JobsRouteDeps<'_>, job_id: &str) -> Result<Response, AppError> {
    jobs_facade_ref(deps).bundle_response(job_id).await
}

pub async fn registered_artifact_response(
    deps: &JobsRouteDeps<'_>,
    job_id: &str,
    artifact_key: &str,
    include_job_dir: bool,
    ocr_only: bool,
) -> Result<Response, AppError> {
    jobs_facade_ref(deps)
        .registered_artifact_response(job_id, artifact_key, include_job_dir, ocr_only)
        .await
}
