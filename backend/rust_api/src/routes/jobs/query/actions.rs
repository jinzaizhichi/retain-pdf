use axum::extract::{Path as AxumPath, State};
use axum::http::HeaderMap;
use axum::Json;

use crate::error::AppError;
use crate::models::{
    ApiResponse, JobSubmissionView, RetryStageRequest, RetryStageSubmissionView, StageActionsView,
};
use crate::AppState;

use super::super::json_response::{
    rerun_job_response, resume_job_response, retry_stage_response, stage_actions_response,
};
use crate::routes::common::build_jobs_route_deps;

pub async fn get_stage_actions(
    State(state): State<AppState>,
    AxumPath(job_id): AxumPath<String>,
    headers: HeaderMap,
) -> Result<Json<ApiResponse<StageActionsView>>, AppError> {
    stage_actions_response(build_jobs_route_deps(&state), &headers, &job_id)
}

pub async fn resume_job(
    State(state): State<AppState>,
    AxumPath(job_id): AxumPath<String>,
    headers: HeaderMap,
) -> Result<Json<ApiResponse<JobSubmissionView>>, AppError> {
    resume_job_response(build_jobs_route_deps(&state), &headers, &job_id)
}

pub async fn rerun_job(
    State(state): State<AppState>,
    AxumPath(job_id): AxumPath<String>,
    headers: HeaderMap,
) -> Result<Json<ApiResponse<JobSubmissionView>>, AppError> {
    rerun_job_response(build_jobs_route_deps(&state), &headers, &job_id)
}

pub async fn retry_stage(
    State(state): State<AppState>,
    AxumPath(job_id): AxumPath<String>,
    headers: HeaderMap,
    Json(request): Json<RetryStageRequest>,
) -> Result<Json<ApiResponse<RetryStageSubmissionView>>, AppError> {
    retry_stage_response(build_jobs_route_deps(&state), &headers, &job_id, request)
}
