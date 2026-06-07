use std::fs;
use std::path::PathBuf;

use axum::body::Body;
use axum::http::{Request, StatusCode};
use serde_json::json;
use tower::util::ServiceExt;

use crate::app::build_app;
use crate::models::{CreateJobInput, JobSnapshot};

use crate::api_tests::jobs_common::{read_json, test_state};

#[tokio::test]
async fn job_events_route_merges_pipeline_jsonl_events() {
    let state = test_state("events-jsonl-merge");
    let mut job = JobSnapshot::new(
        "job-route-events-jsonl".to_string(),
        CreateJobInput::default(),
        vec!["python".to_string()],
    );
    let job_root: PathBuf = state.config.data_root.join("jobs").join(&job.job_id);
    fs::create_dir_all(job_root.join("logs")).expect("create logs dir");
    job.artifacts
        .get_or_insert_with(crate::models::JobArtifacts::default)
        .job_root = Some(job_root.to_string_lossy().to_string());
    state.db.save_job(&job).expect("save job");
    state
        .db
        .append_event(
            &job.job_id,
            "info",
            Some("queued".to_string()),
            Some("db created".to_string()),
            None,
            None,
            "job_created",
            Some("job_created".to_string()),
            "db created",
            Some(0),
            None,
            Some(json!({"origin": "db"})),
            Some(0),
            Some(5),
        )
        .expect("append db event");
    fs::write(
        job_root.join("logs").join("pipeline_events.jsonl"),
        r#"{"job_id":"job-route-events-jsonl","seq":1,"ts":"2026-04-24T01:00:00Z","level":"info","stage":"translating","stage_detail":"batch done","provider":"paddle","provider_stage":"","event_type":"stage_progress","message":"batch done","progress_current":2,"progress_total":5,"retry_count":0,"elapsed_ms":1000,"payload":{"origin":"python"}}"#,
    )
    .expect("write pipeline events");

    let app = build_app(state.clone());
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
        .expect("events items array");
    assert_eq!(items.len(), 2);
    assert!(items.iter().any(|item| item["event"] == "job_created"));
    let pipeline_item = items
        .iter()
        .find(|item| item["raw_event_type"] == "stage_progress")
        .expect("pipeline event item");
    assert_eq!(pipeline_item["provider"], "paddle");
    assert_eq!(pipeline_item["event_type"], "progress");
    assert_eq!(pipeline_item["stage"], "translating");
    assert_eq!(pipeline_item["display_stage"], "translation");
    assert_eq!(pipeline_item["substage"], "translation_batches");
    assert_eq!(pipeline_item["raw"]["source_kind"], "pipeline_jsonl");
    assert_eq!(pipeline_item["raw"]["source_seq"], 1);
    assert!(pipeline_item.get("user_stage").is_none());
    assert_eq!(pipeline_item["created_at"], "2026-04-24T01:00:00Z");
    assert!(pipeline_item.get("progress_unit").is_none());
    assert!(pipeline_item.get("progress_current").is_none());
    assert_eq!(pipeline_item["progress"]["unit"], "batch");
    assert_eq!(pipeline_item["progress"]["current"], 2);
    assert_eq!(pipeline_item["progress"]["total"], 5);
    assert_eq!(pipeline_item["payload"]["origin"], "python");
    let db_item = items
        .iter()
        .find(|item| item["event"] == "job_created")
        .expect("db event item");
    assert!(db_item
        .as_object()
        .expect("db event object")
        .get("user_stage")
        .is_none());
    assert!(db_item
        .as_object()
        .expect("db event object")
        .get("progress_unit")
        .is_none());
    assert!(db_item
        .as_object()
        .expect("db event object")
        .get("progress_total")
        .is_none());
}
