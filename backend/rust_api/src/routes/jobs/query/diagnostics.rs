use axum::extract::{Path as AxumPath, State};
use axum::Json;

use crate::error::AppError;
use crate::models::{ApiResponse, JobDiagnosticsView, JobResumePlanView};
use crate::AppState;

use super::super::json_response::{job_diagnostics_response, resume_plan_response};
use crate::routes::common::build_jobs_route_deps;

pub async fn get_job_diagnostics(
    State(state): State<AppState>,
    AxumPath(job_id): AxumPath<String>,
) -> Result<Json<ApiResponse<JobDiagnosticsView>>, AppError> {
    job_diagnostics_response(build_jobs_route_deps(&state), &job_id)
}

pub async fn get_resume_plan(
    State(state): State<AppState>,
    AxumPath(job_id): AxumPath<String>,
) -> Result<Json<ApiResponse<JobResumePlanView>>, AppError> {
    resume_plan_response(build_jobs_route_deps(&state), &job_id)
}
