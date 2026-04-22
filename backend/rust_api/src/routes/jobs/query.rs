use crate::error::AppError;
use crate::models::{
    ApiResponse, ArtifactLinksView, JobArtifactManifestView, JobDetailView, JobEventListView,
    JobListView, ListJobEventsQuery, ListJobsQuery,
};
use crate::AppState;
use axum::extract::{Path as AxumPath, Query, State};
use axum::http::HeaderMap;
use axum::Json;

use super::common::build_jobs_route_deps;
use super::query_adapter::{
    job_artifact_manifest_response, job_artifacts_response, job_detail_response,
    job_events_response, list_jobs_response,
};

pub async fn list_jobs(
    State(state): State<AppState>,
    headers: HeaderMap,
    Query(query): Query<ListJobsQuery>,
) -> Result<Json<ApiResponse<JobListView>>, AppError> {
    list_jobs_response(build_jobs_route_deps(&state), &headers, &query)
}

pub async fn list_ocr_jobs(
    State(state): State<AppState>,
    headers: HeaderMap,
    Query(mut query): Query<ListJobsQuery>,
) -> Result<Json<ApiResponse<JobListView>>, AppError> {
    query.workflow = Some(crate::models::WorkflowKind::Ocr);
    list_jobs(State(state), headers, Query(query)).await
}

pub async fn get_ocr_job(
    State(state): State<AppState>,
    AxumPath(job_id): AxumPath<String>,
    headers: HeaderMap,
) -> Result<Json<ApiResponse<JobDetailView>>, AppError> {
    job_detail_response(build_jobs_route_deps(&state), &headers, &job_id, true)
}

pub async fn get_ocr_job_events(
    State(state): State<AppState>,
    AxumPath(job_id): AxumPath<String>,
    Query(query): Query<ListJobEventsQuery>,
) -> Result<Json<ApiResponse<JobEventListView>>, AppError> {
    job_events_response(build_jobs_route_deps(&state), &job_id, &query, true)
}

pub async fn get_ocr_job_artifacts(
    State(state): State<AppState>,
    AxumPath(job_id): AxumPath<String>,
    headers: HeaderMap,
) -> Result<Json<ApiResponse<ArtifactLinksView>>, AppError> {
    job_artifacts_response(build_jobs_route_deps(&state), &headers, &job_id, true)
}

pub async fn get_ocr_job_artifacts_manifest(
    State(state): State<AppState>,
    AxumPath(job_id): AxumPath<String>,
    headers: HeaderMap,
) -> Result<Json<ApiResponse<JobArtifactManifestView>>, AppError> {
    job_artifact_manifest_response(build_jobs_route_deps(&state), &headers, &job_id, true)
}

pub async fn get_job(
    State(state): State<AppState>,
    AxumPath(job_id): AxumPath<String>,
    headers: HeaderMap,
) -> Result<Json<ApiResponse<JobDetailView>>, AppError> {
    job_detail_response(build_jobs_route_deps(&state), &headers, &job_id, false)
}

pub async fn get_job_events(
    State(state): State<AppState>,
    AxumPath(job_id): AxumPath<String>,
    Query(query): Query<ListJobEventsQuery>,
) -> Result<Json<ApiResponse<JobEventListView>>, AppError> {
    job_events_response(build_jobs_route_deps(&state), &job_id, &query, false)
}

pub async fn get_job_artifacts(
    State(state): State<AppState>,
    AxumPath(job_id): AxumPath<String>,
    headers: HeaderMap,
) -> Result<Json<ApiResponse<ArtifactLinksView>>, AppError> {
    job_artifacts_response(build_jobs_route_deps(&state), &headers, &job_id, false)
}

pub async fn get_job_artifacts_manifest(
    State(state): State<AppState>,
    AxumPath(job_id): AxumPath<String>,
    headers: HeaderMap,
) -> Result<Json<ApiResponse<JobArtifactManifestView>>, AppError> {
    job_artifact_manifest_response(build_jobs_route_deps(&state), &headers, &job_id, false)
}

#[cfg(test)]
mod tests {
    use std::collections::HashSet;
    use std::fs;
    use std::sync::Arc;

    use axum::body::{to_bytes, Body};
    use axum::http::{Request, StatusCode};
    use serde_json::json;
    use tower::util::ServiceExt;

    use crate::app::{build_app, build_state};
    use crate::config::AppConfig;
    use crate::models::{CreateJobInput, JobSnapshot, JobStatusKind};

    fn test_state(test_name: &str) -> crate::AppState {
        let root = std::env::temp_dir().join(format!(
            "rust-api-query-routes-{test_name}-{}",
            fastrand::u64(..)
        ));
        let data_root = root.join("data");
        let output_root = data_root.join("jobs");
        let downloads_dir = data_root.join("downloads");
        let uploads_dir = data_root.join("uploads");
        let rust_api_root = root.join("rust_api");
        let scripts_dir = root.join("scripts");
        fs::create_dir_all(&output_root).expect("create output root");
        fs::create_dir_all(&downloads_dir).expect("create downloads dir");
        fs::create_dir_all(&uploads_dir).expect("create uploads dir");
        fs::create_dir_all(&rust_api_root).expect("create rust_api root");
        fs::create_dir_all(&scripts_dir).expect("create scripts dir");

        build_state(Arc::new(AppConfig {
            project_root: root.clone(),
            rust_api_root,
            data_root: data_root.clone(),
            scripts_dir: scripts_dir.clone(),
            run_provider_case_script: scripts_dir.join("run_provider_case.py"),
            run_provider_ocr_script: scripts_dir.join("run_provider_ocr.py"),
            run_normalize_ocr_script: scripts_dir.join("run_normalize_ocr.py"),
            run_translate_from_ocr_script: scripts_dir.join("run_translate_from_ocr.py"),
            run_translate_only_script: scripts_dir.join("run_translate_only.py"),
            run_render_only_script: scripts_dir.join("run_render_only.py"),
            run_failure_ai_diagnosis_script: scripts_dir.join("diagnose_failure_with_ai.py"),
            uploads_dir,
            downloads_dir,
            jobs_db_path: data_root.join("db").join("jobs.db"),
            output_root,
            python_bin: "python3".to_string(),
            bind_host: "127.0.0.1".to_string(),
            port: 41000,
            simple_port: 42000,
            upload_max_bytes: 0,
            upload_max_pages: 0,
            api_keys: HashSet::from(["test-key".to_string()]),
            max_running_jobs: 1,
        }))
        .expect("build state")
    }

    async fn read_json(response: axum::response::Response) -> serde_json::Value {
        serde_json::from_slice(
            &to_bytes(response.into_body(), usize::MAX)
                .await
                .expect("read body"),
        )
        .expect("parse json")
    }

    #[tokio::test]
    async fn job_detail_and_events_routes_redact_secrets() {
        let state = test_state("detail-events-redaction");
        let mut input = CreateJobInput::default();
        input.translation.api_key = "sk-route-secret".to_string();
        input.ocr.mineru_token = "mineru-route-secret".to_string();
        let mut job = JobSnapshot::new(
            "job-route-redaction".to_string(),
            input,
            vec!["python".to_string()],
        );
        job.status = JobStatusKind::Failed;
        job.error = Some("upstream said sk-route-secret".to_string());
        job.log_tail = vec!["mineru-route-secret appeared in log".to_string()];
        state.db.save_job(&job).expect("save job");
        state
            .db
            .append_event(
                &job.job_id,
                "error",
                Some("failed".to_string()),
                "failure_classified",
                "message contains sk-route-secret",
                Some(json!({
                    "api_key": "sk-route-secret",
                    "note": "mineru-route-secret in payload"
                })),
            )
            .expect("append event");

        let app = build_app(state.clone());

        let detail_response = app
            .clone()
            .oneshot(
                Request::builder()
                    .uri(format!("/api/v1/jobs/{}", job.job_id))
                    .header("X-API-Key", "test-key")
                    .body(Body::empty())
                    .expect("detail request"),
            )
            .await
            .expect("detail response");
        assert_eq!(detail_response.status(), StatusCode::OK);
        let detail_json = read_json(detail_response).await;
        assert_eq!(
            detail_json["data"]["request_payload"]["translation"]["api_key"],
            ""
        );
        assert_eq!(
            detail_json["data"]["request_payload"]["ocr"]["mineru_token"],
            ""
        );
        assert_eq!(detail_json["data"]["error"], "upstream said [REDACTED]");
        assert_eq!(
            detail_json["data"]["log_tail"][0],
            "[REDACTED] appeared in log"
        );

        let events_response = app
            .oneshot(
                Request::builder()
                    .uri(format!("/api/v1/jobs/{}/events", job.job_id))
                    .header("X-API-Key", "test-key")
                    .body(Body::empty())
                    .expect("events request"),
            )
            .await
            .expect("events response");
        assert_eq!(events_response.status(), StatusCode::OK);
        let events_json = read_json(events_response).await;
        assert_eq!(
            events_json["data"]["items"][0]["message"],
            "message contains [REDACTED]"
        );
        assert_eq!(events_json["data"]["items"][0]["payload"]["api_key"], "");
        assert_eq!(
            events_json["data"]["items"][0]["payload"]["note"],
            "[REDACTED] in payload"
        );
    }
}
