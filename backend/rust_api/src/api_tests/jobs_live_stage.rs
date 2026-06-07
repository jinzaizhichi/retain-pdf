use std::fs;
use std::path::PathBuf;

use axum::body::Body;
use axum::http::{Request, StatusCode};
use tower::util::ServiceExt;

use crate::app::build_app;
use crate::models::{CreateJobInput, JobSnapshot};

use super::jobs_common::{read_json, test_state};

#[tokio::test]
async fn job_detail_list_and_events_share_pipeline_event_priority() {
    let state = test_state("shared-live-stage-priority");
    let mut job = JobSnapshot::new(
        "job-route-shared-live-stage".to_string(),
        CreateJobInput::default(),
        vec!["python".to_string()],
    );
    job.stage = Some("queued".to_string());
    job.stage_detail = Some("stale queued detail".to_string());
    let job_root: PathBuf = state.config.data_root.join("jobs").join(&job.job_id);
    fs::create_dir_all(job_root.join("logs")).expect("create logs dir");
    job.artifacts
        .get_or_insert_with(crate::models::JobArtifacts::default)
        .job_root = Some(job_root.to_string_lossy().to_string());
    state.db.save_job(&job).expect("save job");
    fs::write(
        job_root.join("logs").join("pipeline_events.jsonl"),
        concat!(
            r#"{"job_id":"job-route-shared-live-stage","seq":1,"ts":"2026-04-24T01:00:00Z","level":"info","stage":"translating","stage_detail":"已完成第 4/9 批翻译","provider":"","provider_stage":"","event":"stage_progress","message":"已完成第 4/9 批翻译","progress_current":4,"progress_total":9,"retry_count":0,"elapsed_ms":900,"payload":{"origin":"python"}}"#,
            "\n",
            r#"{"job_id":"job-route-shared-live-stage","seq":2,"ts":"2026-04-24T01:00:01Z","level":"info","stage":"saving","stage_detail":"最终 PDF 已发布","provider":"","provider_stage":"","event":"artifact_published","message":"最终 PDF 已发布","progress_current":null,"progress_total":null,"retry_count":0,"elapsed_ms":1000,"payload":{"artifact_key":"output_pdf"}}"#,
            "\n"
        ),
    )
    .expect("write pipeline events");

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
    assert_eq!(detail_json["data"]["stage"], "translating");
    assert_eq!(detail_json["data"]["stage_detail"], "已完成第 4/9 批翻译");
    assert_eq!(detail_json["data"]["progress"]["current"], 4);
    assert_eq!(detail_json["data"]["progress"]["total"], 9);

    let list_response = app
        .clone()
        .oneshot(
            Request::builder()
                .uri("/api/v1/jobs")
                .header("X-API-Key", "test-key")
                .body(Body::empty())
                .expect("list request"),
        )
        .await
        .expect("list response");
    assert_eq!(list_response.status(), StatusCode::OK);
    let list_json = read_json(list_response).await;
    let list_item = list_json["data"]["items"]
        .as_array()
        .expect("list items")
        .iter()
        .find(|item| item["job_id"] == "job-route-shared-live-stage")
        .expect("job item");
    assert_eq!(list_item["stage"], "translating");

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
    let items = events_json["data"]["items"]
        .as_array()
        .expect("events items");
    let stage_progress = items
        .iter()
        .find(|item| item["event"] == "stage_progress")
        .expect("stage_progress event");
    let artifact_published = items
        .iter()
        .find(|item| item["event"] == "artifact_published")
        .expect("artifact_published event");
    assert_eq!(stage_progress["event_type"], "progress");
    assert_eq!(stage_progress["raw_event_type"], "stage_progress");
    assert_eq!(stage_progress["stage"], "translating");
    assert_eq!(stage_progress["display_stage"], "translation");
    assert_eq!(artifact_published["event_type"], "artifact");
    assert_eq!(artifact_published["raw_event_type"], "artifact_published");
    assert_eq!(artifact_published["stage"], "saving");
    assert_eq!(artifact_published["display_stage"], "render");
    assert_eq!(artifact_published["substage"], "render_pages");
}
