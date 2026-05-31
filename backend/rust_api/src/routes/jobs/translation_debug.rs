use axum::extract::{Path as AxumPath, Query, State};
use axum::http::HeaderMap;
use axum::Json;

use crate::error::AppError;
use crate::models::{
    ApiResponse, ListTranslationItemsQuery, TranslationDebugItemView, TranslationDebugListView,
    TranslationDiagnosticsView, TranslationReplayView,
};
use crate::AppState;

use super::common::build_jobs_route_deps;
use super::query_adapter::{
    replay_translation_item_response, translation_diagnostics_response, translation_item_response,
    translation_items_response,
};

pub async fn get_translation_diagnostics(
    State(state): State<AppState>,
    AxumPath(job_id): AxumPath<String>,
    _headers: HeaderMap,
) -> Result<Json<ApiResponse<TranslationDiagnosticsView>>, AppError> {
    translation_diagnostics_response(build_jobs_route_deps(&state), &job_id)
}

pub async fn list_translation_items(
    State(state): State<AppState>,
    AxumPath(job_id): AxumPath<String>,
    Query(query): Query<ListTranslationItemsQuery>,
) -> Result<Json<ApiResponse<TranslationDebugListView>>, AppError> {
    translation_items_response(build_jobs_route_deps(&state), &job_id, &query)
}

pub async fn get_translation_item(
    State(state): State<AppState>,
    AxumPath((job_id, item_id)): AxumPath<(String, String)>,
) -> Result<Json<ApiResponse<TranslationDebugItemView>>, AppError> {
    translation_item_response(build_jobs_route_deps(&state), &job_id, &item_id)
}

pub async fn replay_translation_item_route(
    State(state): State<AppState>,
    AxumPath((job_id, item_id)): AxumPath<(String, String)>,
) -> Result<Json<ApiResponse<TranslationReplayView>>, AppError> {
    replay_translation_item_response(build_jobs_route_deps(&state), &job_id, &item_id).await
}
