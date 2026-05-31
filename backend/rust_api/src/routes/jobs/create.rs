use crate::error::AppError;
use crate::models::{ApiResponse, CreateJobInput, JobSubmissionView};
use crate::routes::job_requests::{parse_ocr_job_request, parse_translate_bundle_request};
use crate::AppState;
use axum::extract::{Multipart, State};
use axum::http::HeaderMap;
use axum::Json;
use serde_json::Value;

use super::common::{build_jobs_route_deps, jobs_facade, ok_json, request_base_url};

pub async fn create_job(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(payload): Json<Value>,
) -> Result<Json<ApiResponse<JobSubmissionView>>, AppError> {
    let request = CreateJobInput::from_api_value(payload)
        .map_err(|e| AppError::bad_request(format!("invalid job payload: {e}")))?;
    let deps = build_jobs_route_deps(&state);
    let base_url = request_base_url(&headers, deps.default_port);
    Ok(ok_json(
        jobs_facade(deps).create_submission(&base_url, &request)?,
    ))
}

pub async fn create_ocr_job(
    State(state): State<AppState>,
    headers: HeaderMap,
    mut multipart: Multipart,
) -> Result<Json<ApiResponse<JobSubmissionView>>, AppError> {
    let parsed = parse_ocr_job_request(&mut multipart).await?;
    let upload = match (parsed.filename, parsed.file_bytes, parsed.developer_mode) {
        (Some(filename), Some(bytes), developer_mode) => Some((filename, bytes, developer_mode)),
        (None, None, _) => None,
        _ => return Err(AppError::bad_request("file upload is incomplete")),
    };
    let deps = build_jobs_route_deps(&state);
    let base_url = request_base_url(&headers, deps.default_port);
    let view = jobs_facade(deps)
        .create_ocr_submission(&base_url, &parsed.request, upload)
        .await?;
    Ok(ok_json(view))
}

pub async fn translate_bundle(
    State(state): State<AppState>,
    headers: HeaderMap,
    mut multipart: Multipart,
) -> Result<Json<ApiResponse<JobSubmissionView>>, AppError> {
    let parsed = parse_translate_bundle_request(&mut multipart).await?;
    let deps = build_jobs_route_deps(&state);
    let base_url = request_base_url(&headers, deps.default_port);
    let view = jobs_facade(deps)
        .create_translation_bundle_submission(
            &base_url,
            parsed.request,
            parsed.filename,
            parsed.file_bytes,
            parsed.developer_mode,
        )
        .await?;
    Ok(ok_json(view))
}
