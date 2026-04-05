use crate::error::AppError;
use crate::models::{ApiResponse, CreateJobInput, JobStatusKind, JobSubmissionView};
use crate::routes::job_helpers::{build_submission_view, request_base_url, stream_file};
use crate::routes::job_requests::{parse_ocr_job_request, parse_translate_bundle_request};
use crate::routes::uploads::store_upload;
use crate::services::artifacts::{attach_job_id_header, build_bundle_for_job};
use crate::services::jobs::{
    create_ocr_job as create_ocr_job_service, create_translation_job,
    validate_mineru_upload_limits, wait_for_terminal_job,
};
use crate::AppState;
use axum::extract::{Multipart, State};
use axum::http::HeaderMap;
use axum::response::Response;
use axum::Json;
use serde_json::Value;

pub async fn create_job(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(payload): Json<Value>,
) -> Result<Json<ApiResponse<JobSubmissionView>>, AppError> {
    let request = CreateJobInput::from_api_value(payload)
        .map_err(|e| AppError::bad_request(format!("invalid job payload: {e}")))?;
    let workflow = request.workflow.clone();
    let job = create_translation_job(&state, &request)?;
    let base_url = request_base_url(&headers, &state);
    Ok(Json(ApiResponse::ok(build_submission_view(
        &job,
        JobStatusKind::Queued,
        workflow,
        &base_url,
    ))))
}

pub async fn create_ocr_job(
    State(state): State<AppState>,
    headers: HeaderMap,
    mut multipart: Multipart,
) -> Result<Json<ApiResponse<JobSubmissionView>>, AppError> {
    let parsed = parse_ocr_job_request(&mut multipart).await?;
    let upload = match (parsed.filename, parsed.file_bytes) {
        (Some(filename), Some(bytes)) => {
            let upload = store_upload(&state, filename, bytes, parsed.developer_mode).await?;
            state.db.save_upload(&upload)?;
            Some(upload)
        }
        (None, None) => None,
        _ => return Err(AppError::bad_request("file upload is incomplete")),
    };

    let job = create_ocr_job_service(&state, &parsed.request, upload.as_ref())?;
    let base_url = request_base_url(&headers, &state);
    Ok(Json(ApiResponse::ok(build_submission_view(
        &job,
        JobStatusKind::Queued,
        crate::models::WorkflowKind::Ocr,
        &base_url,
    ))))
}

pub async fn translate_bundle(
    State(state): State<AppState>,
    mut multipart: Multipart,
) -> Result<Response, AppError> {
    let parsed = parse_translate_bundle_request(&mut multipart).await?;
    let upload = store_upload(
        &state,
        parsed.filename,
        parsed.file_bytes,
        parsed.developer_mode,
    )
    .await?;
    state.db.save_upload(&upload)?;

    let mut request = parsed.request;
    request.source.upload_id = upload.upload_id.clone();
    validate_mineru_upload_limits(&request, &upload)?;
    let job = create_translation_job(&state, &request)?;
    let finished_job = wait_for_terminal_job(&state, &job.job_id, request.ocr.poll_timeout).await?;

    let _guard = state.downloads_lock.lock().await;
    let zip_path = build_bundle_for_job(&state, &finished_job)?;
    let mut response = stream_file(
        zip_path,
        "application/zip",
        Some(format!("{}.zip", finished_job.job_id)),
    )
    .await?;
    attach_job_id_header(&mut response, &finished_job.job_id)?;
    Ok(response)
}
