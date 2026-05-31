use axum::extract::{Path as AxumPath, State};
use axum::Json;

use crate::error::AppError;
use crate::models::{ApiResponse, ReaderMetadataView, ReaderRegionsView};
use crate::AppState;

use super::super::common::build_jobs_route_deps;
use super::super::query_adapter::{reader_metadata_response, reader_regions_response};

pub async fn get_reader_regions(
    State(state): State<AppState>,
    AxumPath(job_id): AxumPath<String>,
) -> Result<Json<ApiResponse<ReaderRegionsView>>, AppError> {
    reader_regions_response(build_jobs_route_deps(&state), &job_id)
}

pub async fn get_reader_metadata(
    State(state): State<AppState>,
    AxumPath(job_id): AxumPath<String>,
) -> Result<Json<ApiResponse<ReaderMetadataView>>, AppError> {
    reader_metadata_response(build_jobs_route_deps(&state), &job_id)
}
