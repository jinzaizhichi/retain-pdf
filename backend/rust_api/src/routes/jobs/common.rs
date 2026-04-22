use std::path::Path;

use axum::Json;

use crate::models::ApiResponse;
use crate::services::jobs::build_jobs_facade;
use crate::services::jobs::JobsFacade;
use crate::AppState;

pub struct JobsRouteDeps<'a> {
    pub jobs: JobsFacade<'a>,
    pub data_root: &'a Path,
}

pub fn build_jobs_route_deps(state: &AppState) -> JobsRouteDeps<'_> {
    JobsRouteDeps {
        jobs: build_jobs_facade(state),
        data_root: &state.config.data_root,
    }
}

pub fn jobs_facade(deps: JobsRouteDeps<'_>) -> JobsFacade<'_> {
    deps.jobs
}

pub fn ok_json<T>(value: T) -> Json<ApiResponse<T>> {
    Json(ApiResponse::ok(value))
}
