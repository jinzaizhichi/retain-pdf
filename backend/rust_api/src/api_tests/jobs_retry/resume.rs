use axum::body::Body;
use axum::http::{Request, StatusCode};
use serde_json::json;
use tower::util::ServiceExt;

use crate::api_tests::jobs_common::{read_json, test_state};
use crate::app::build_app;
use crate::models::{JobArtifacts, JobStatusKind};

use super::common::source_job_with_artifacts;

#[tokio::test]
async fn resume_plan_route_reports_render_checkpoint() {
    let state = test_state("resume-plan-render");
    let source_job = source_job_with_artifacts(
        "job-resume-plan-render",
        JobArtifacts {
            source_pdf: Some("jobs/source/source/input.pdf".to_string()),
            normalized_document_json: Some("jobs/source/ocr/document.v1.json".to_string()),
            translations_dir: Some("jobs/source/translated".to_string()),
            ..JobArtifacts::default()
        },
    );
    state.db.save_job(&source_job).expect("save source job");

    let response = build_app(state)
        .oneshot(
            Request::builder()
                .method("GET")
                .uri("/api/v1/jobs/job-resume-plan-render/resume-plan")
                .header("X-API-Key", "test-key")
                .body(Body::empty())
                .expect("resume plan request"),
        )
        .await
        .expect("resume plan response");

    assert_eq!(response.status(), StatusCode::OK);
    let payload = read_json(response).await;
    assert_eq!(payload["data"]["can_resume"], true);
    assert_eq!(payload["data"]["from_stage"], "render");
    assert_eq!(payload["data"]["resume_workflow"], "render");
    assert_eq!(payload["data"]["reruns_stages"], json!(["rendering"]));
}

#[tokio::test]
async fn resume_route_reuses_rerun_submission_contract() {
    let state = test_state("resume-render");
    let mut source_job = source_job_with_artifacts(
        "job-resume-render-source",
        JobArtifacts {
            source_pdf: Some("jobs/source/source/input.pdf".to_string()),
            normalized_document_json: Some("jobs/source/ocr/document.v1.json".to_string()),
            translations_dir: Some("jobs/source/translated".to_string()),
            ..JobArtifacts::default()
        },
    );
    source_job.status = JobStatusKind::Succeeded;
    state.db.save_job(&source_job).expect("save source job");

    let response = build_app(state.clone())
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/v1/jobs/job-resume-render-source/resume")
                .header("X-API-Key", "test-key")
                .body(Body::empty())
                .expect("resume request"),
        )
        .await
        .expect("resume response");

    assert_eq!(response.status(), StatusCode::OK);
    let payload = read_json(response).await;
    assert_eq!(payload["data"]["job_id"], "job-resume-render-source");
    assert_eq!(payload["data"]["workflow"], "render");
    let resumed_job = state.db.get_job("job-resume-render-source").expect("job");
    assert_eq!(resumed_job.workflow, crate::models::WorkflowKind::Render);
    assert_eq!(resumed_job.status, JobStatusKind::Queued);
}
