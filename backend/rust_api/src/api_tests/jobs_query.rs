use std::collections::HashSet;
use std::fs;
use std::path::PathBuf;
use std::sync::Arc;

use axum::body::{to_bytes, Body};
use axum::http::{Request, StatusCode};
use serde_json::json;
use tower::util::ServiceExt;

use crate::app::{build_app, build_state};
use crate::config::AppConfig;
use crate::models::{CreateJobInput, JobArtifacts, JobFailureInfo, JobSnapshot, JobStatusKind};

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
        provider_limits: crate::config::ProviderLimitsConfig::default(),
        provider_runtime: crate::config::ProviderRuntimeConfig::default(),
        job_runner: crate::config::JobRunnerConfig::default(),
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

fn source_job_with_artifacts(job_id: &str, artifacts: JobArtifacts) -> JobSnapshot {
    let mut input = CreateJobInput::default();
    input.runtime.job_id = job_id.to_string();
    input.translation.api_key = "sk-rerun-test".to_string();
    input.translation.model = "deepseek-v4-flash".to_string();
    input.translation.base_url = "https://api.deepseek.com/v1".to_string();
    let mut job = JobSnapshot::new(job_id.to_string(), input, vec!["python".to_string()]);
    job.artifacts = Some(artifacts);
    job
}

fn seed_ocr_checkpoint_files(state: &crate::AppState, job: &JobSnapshot) {
    let artifacts = job.artifacts.as_ref().expect("job artifacts");
    if let Some(path) = artifacts.source_pdf.as_deref() {
        let path = state.config.data_root.join(path);
        fs::create_dir_all(path.parent().expect("source pdf parent")).expect("source pdf dir");
        fs::write(path, minimal_pdf_bytes(595, 842)).expect("source pdf file");
    }
    if let Some(path) = artifacts.normalized_document_json.as_deref() {
        let path = state.config.data_root.join(path);
        fs::create_dir_all(path.parent().expect("normalized parent")).expect("normalized dir");
        fs::write(path, br#"{"pages":[]}"#).expect("normalized file");
    }
}

#[tokio::test]
async fn rerun_route_prefers_render_when_translations_are_available() {
    let state = test_state("rerun-render");
    let mut source_job = source_job_with_artifacts(
        "job-rerun-render-source",
        JobArtifacts {
            source_pdf: Some("jobs/source/source/input.pdf".to_string()),
            normalized_document_json: Some("jobs/source/ocr/document.v1.json".to_string()),
            translations_dir: Some("jobs/source/translated".to_string()),
            ..JobArtifacts::default()
        },
    );
    source_job.status = JobStatusKind::Succeeded;
    seed_ocr_checkpoint_files(&state, &source_job);
    state.db.save_job(&source_job).expect("save source job");

    let response = build_app(state.clone())
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/v1/jobs/job-rerun-render-source/rerun")
                .header("X-API-Key", "test-key")
                .body(Body::empty())
                .expect("rerun request"),
        )
        .await
        .expect("rerun response");

    assert_eq!(response.status(), StatusCode::OK);
    let payload = read_json(response).await;
    assert_eq!(payload["data"]["workflow"], "render");
    let rerun_job_id = payload["data"]["job_id"].as_str().expect("job id");
    assert_eq!(rerun_job_id, "job-rerun-render-source");
    let rerun_job = state.db.get_job(rerun_job_id).expect("rerun job");
    assert_eq!(rerun_job.workflow, crate::models::WorkflowKind::Render);
    assert_eq!(rerun_job.status, JobStatusKind::Queued);
    assert_eq!(
        rerun_job.request_payload.source.artifact_job_id,
        "job-rerun-render-source"
    );
    assert_eq!(
        rerun_job.request_payload.runtime.job_id,
        "job-rerun-render-source"
    );
}

#[tokio::test]
async fn rerun_route_uses_book_when_only_ocr_checkpoint_is_available() {
    let state = test_state("rerun-book");
    let source_job = source_job_with_artifacts(
        "job-rerun-book-source",
        JobArtifacts {
            source_pdf: Some("jobs/source/source/input.pdf".to_string()),
            normalized_document_json: Some("jobs/source/ocr/document.v1.json".to_string()),
            ..JobArtifacts::default()
        },
    );
    seed_ocr_checkpoint_files(&state, &source_job);
    state.db.save_job(&source_job).expect("save source job");

    let response = build_app(state.clone())
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/v1/jobs/job-rerun-book-source/rerun")
                .header("X-API-Key", "test-key")
                .body(Body::empty())
                .expect("rerun request"),
        )
        .await
        .expect("rerun response");

    assert_eq!(response.status(), StatusCode::OK);
    let payload = read_json(response).await;
    assert_eq!(payload["data"]["workflow"], "book");
    let rerun_job_id = payload["data"]["job_id"].as_str().expect("job id");
    let rerun_job = state.db.get_job(rerun_job_id).expect("rerun job");
    assert_eq!(rerun_job.workflow, crate::models::WorkflowKind::Book);
    assert_eq!(
        rerun_job.request_payload.source.artifact_job_id,
        "job-rerun-book-source"
    );
}

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
async fn stage_actions_route_reports_retryable_stages() {
    let state = test_state("stage-actions");
    let mut source_job = source_job_with_artifacts(
        "job-stage-actions",
        JobArtifacts {
            source_pdf: Some("jobs/source/source/input.pdf".to_string()),
            normalized_document_json: Some("jobs/source/ocr/document.v1.json".to_string()),
            translations_dir: Some("jobs/source/translated".to_string()),
            ..JobArtifacts::default()
        },
    );
    source_job.status = JobStatusKind::Succeeded;
    seed_ocr_checkpoint_files(&state, &source_job);
    state.db.save_job(&source_job).expect("save source job");

    let response = build_app(state)
        .oneshot(
            Request::builder()
                .method("GET")
                .uri("/api/v1/jobs/job-stage-actions/stage-actions")
                .header("X-API-Key", "test-key")
                .body(Body::empty())
                .expect("stage actions request"),
        )
        .await
        .expect("stage actions response");

    assert_eq!(response.status(), StatusCode::OK);
    let payload = read_json(response).await;
    assert_eq!(payload["data"]["job_id"], "job-stage-actions");
    let stages = payload["data"]["stages"].as_array().expect("stages");
    let translation = stages
        .iter()
        .find(|item| item["stage"] == "translation")
        .expect("translation action");
    assert_eq!(translation["can_retry"], true);
    assert_eq!(translation["will_rerun"], json!(["translation", "render"]));
    assert_eq!(
        translation["action"]["url"],
        "http://127.0.0.1:41000/api/v1/jobs/job-stage-actions/retry-stage"
    );
    let render = stages
        .iter()
        .find(|item| item["stage"] == "render")
        .expect("render action");
    assert_eq!(render["can_retry"], true);
    assert_eq!(render["will_rerun"], json!(["render"]));
}

#[tokio::test]
async fn retry_stage_route_creates_translation_recovery_job_with_overrides() {
    let state = test_state("retry-stage-translation");
    let mut source_job = source_job_with_artifacts(
        "job-retry-stage-translation-source",
        JobArtifacts {
            source_pdf: Some("jobs/source/source/input.pdf".to_string()),
            normalized_document_json: Some("jobs/source/ocr/document.v1.json".to_string()),
            ..JobArtifacts::default()
        },
    );
    source_job.status = JobStatusKind::Succeeded;
    seed_ocr_checkpoint_files(&state, &source_job);
    state.db.save_job(&source_job).expect("save source job");

    let response = build_app(state.clone())
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/v1/jobs/job-retry-stage-translation-source/retry-stage")
                .header("X-API-Key", "test-key")
                .header("Content-Type", "application/json")
                .body(Body::from(
                    json!({
                        "stage": "translation",
                        "overrides": {
                            "translation": {
                                "model": "deepseek-v4-flash",
                                "workers": 50
                            },
                            "render": {
                                "compile_workers": 8
                            }
                        }
                    })
                    .to_string(),
                ))
                .expect("retry stage request"),
        )
        .await
        .expect("retry stage response");

    assert_eq!(response.status(), StatusCode::OK);
    let payload = read_json(response).await;
    assert_eq!(
        payload["data"]["source_job_id"],
        "job-retry-stage-translation-source"
    );
    assert_eq!(payload["data"]["workflow"], "book");
    assert_eq!(payload["data"]["rerun_from_stage"], "translation");
    assert_eq!(
        payload["data"]["reused_artifacts"],
        json!(["source_pdf", "ocr_result"])
    );
    let retry_job_id = payload["data"]["job_id"].as_str().expect("job id");
    let retry_job = state.db.get_job(retry_job_id).expect("retry job");
    assert_eq!(retry_job.workflow, crate::models::WorkflowKind::Book);
    assert_eq!(
        retry_job.request_payload.source.artifact_job_id,
        "job-retry-stage-translation-source"
    );
    assert_eq!(retry_job.request_payload.translation.workers, 50);
    assert_eq!(retry_job.request_payload.render.compile_workers, 8);
}

#[tokio::test]
async fn retry_stage_route_creates_render_job_by_default() {
    let state = test_state("retry-stage-render");
    let mut source_job = source_job_with_artifacts(
        "job-retry-stage-render-source",
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
                .uri("/api/v1/jobs/job-retry-stage-render-source/retry-stage")
                .header("X-API-Key", "test-key")
                .header("Content-Type", "application/json")
                .body(Body::from(json!({ "stage": "render" }).to_string()))
                .expect("retry render request"),
        )
        .await
        .expect("retry render response");

    assert_eq!(response.status(), StatusCode::OK);
    let payload = read_json(response).await;
    assert_eq!(payload["data"]["workflow"], "render");
    assert_eq!(payload["data"]["rerun_stages"], json!(["render"]));
    let retry_job_id = payload["data"]["job_id"].as_str().expect("job id");
    assert_ne!(retry_job_id, "job-retry-stage-render-source");
    let retry_job = state.db.get_job(retry_job_id).expect("retry job");
    assert_eq!(retry_job.workflow, crate::models::WorkflowKind::Render);
    assert_eq!(
        retry_job.request_payload.source.artifact_job_id,
        "job-retry-stage-render-source"
    );
}

#[tokio::test]
async fn retry_stage_route_allows_in_place_render_when_requested() {
    let state = test_state("retry-stage-render-in-place");
    let mut source_job = source_job_with_artifacts(
        "job-retry-stage-render-in-place",
        JobArtifacts {
            source_pdf: Some("jobs/source/source/input.pdf".to_string()),
            normalized_document_json: Some("jobs/source/ocr/document.v1.json".to_string()),
            translations_dir: Some("jobs/source/translated".to_string()),
            output_pdf: Some("jobs/source/output/old.pdf".to_string()),
            ..JobArtifacts::default()
        },
    );
    source_job.status = JobStatusKind::Succeeded;
    state.db.save_job(&source_job).expect("save source job");

    let response = build_app(state.clone())
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/v1/jobs/job-retry-stage-render-in-place/retry-stage")
                .header("X-API-Key", "test-key")
                .header("Content-Type", "application/json")
                .body(Body::from(
                    json!({
                        "stage": "render",
                        "create_new_job": false
                    })
                    .to_string(),
                ))
                .expect("retry render in place request"),
        )
        .await
        .expect("retry render in place response");

    assert_eq!(response.status(), StatusCode::OK);
    let payload = read_json(response).await;
    assert_eq!(payload["data"]["job_id"], "job-retry-stage-render-in-place");
    assert_eq!(payload["data"]["workflow"], "render");
    let retry_job = state
        .db
        .get_job("job-retry-stage-render-in-place")
        .expect("retry job");
    assert_eq!(retry_job.workflow, crate::models::WorkflowKind::Render);
    assert_eq!(retry_job.status, JobStatusKind::Queued);
    assert!(retry_job
        .artifacts
        .as_ref()
        .expect("artifacts")
        .output_pdf
        .is_none());
}

#[tokio::test]
async fn retry_stage_route_applies_overrides_for_in_place_render() {
    let state = test_state("retry-stage-render-in-place-overrides");
    let mut source_job = source_job_with_artifacts(
        "job-retry-stage-render-in-place-overrides",
        JobArtifacts {
            source_pdf: Some("jobs/source/source/input.pdf".to_string()),
            normalized_document_json: Some("jobs/source/ocr/document.v1.json".to_string()),
            translations_dir: Some("jobs/source/translated".to_string()),
            output_pdf: Some("jobs/source/output/old.pdf".to_string()),
            ..JobArtifacts::default()
        },
    );
    source_job.status = JobStatusKind::Succeeded;
    source_job.request_payload.render.compile_workers = 1;
    source_job.request_payload.render.render_mode = "overlay".to_string();
    source_job.request_payload.runtime.timeout_seconds = 10;
    state.db.save_job(&source_job).expect("save source job");

    let response = build_app(state.clone())
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/v1/jobs/job-retry-stage-render-in-place-overrides/retry-stage")
                .header("X-API-Key", "test-key")
                .header("Content-Type", "application/json")
                .body(Body::from(
                    json!({
                        "stage": "render",
                        "create_new_job": false,
                        "overrides": {
                            "render": {
                                "render_mode": "typst",
                                "compile_workers": 8
                            },
                            "runtime": {
                                "timeout_seconds": 120
                            }
                        }
                    })
                    .to_string(),
                ))
                .expect("retry render in place request"),
        )
        .await
        .expect("retry render in place response");

    assert_eq!(response.status(), StatusCode::OK);
    let payload = read_json(response).await;
    assert_eq!(
        payload["data"]["job_id"],
        "job-retry-stage-render-in-place-overrides"
    );
    let retry_job = state
        .db
        .get_job("job-retry-stage-render-in-place-overrides")
        .expect("retry job");
    assert_eq!(retry_job.request_payload.render.render_mode, "typst");
    assert_eq!(retry_job.request_payload.render.compile_workers, 8);
    assert_eq!(retry_job.request_payload.runtime.timeout_seconds, 120);
    assert_eq!(
        retry_job.request_payload.runtime.job_id,
        "job-retry-stage-render-in-place-overrides"
    );
}

#[tokio::test]
async fn diagnostics_route_exposes_stable_failure_summary() {
    let state = test_state("diagnostics-route");
    let mut job = JobSnapshot::new(
        "job-diagnostics-route".to_string(),
        CreateJobInput::default(),
        vec!["python".to_string()],
    );
    job.status = JobStatusKind::Failed;
    job.failure = Some(crate::models::JobFailureInfo {
        stage: "failed".to_string(),
        category: "legacy_provider_failed".to_string(),
        code: None,
        failed_stage: Some("translation".to_string()),
        failure_code: Some("upstream_timeout".to_string()),
        failure_category: Some("timeout".to_string()),
        provider_stage: Some("continuation_review".to_string()),
        provider_code: None,
        summary: "翻译阶段超时".to_string(),
        root_cause: Some("provider timed out".to_string()),
        retryable: true,
        upstream_host: None,
        provider: Some("translation".to_string()),
        suggestion: Some("从断点恢复任务".to_string()),
        last_log_line: None,
        raw_excerpt: None,
        raw_error_excerpt: None,
        raw_diagnostic: None,
        ai_diagnostic: None,
    });
    state.db.save_job(&job).expect("save job");

    let response = build_app(state)
        .oneshot(
            Request::builder()
                .method("GET")
                .uri("/api/v1/jobs/job-diagnostics-route/diagnostics")
                .header("X-API-Key", "test-key")
                .body(Body::empty())
                .expect("diagnostics request"),
        )
        .await
        .expect("diagnostics response");

    assert_eq!(response.status(), StatusCode::OK);
    let payload = read_json(response).await;
    assert_eq!(payload["data"]["failed_stage"], "translation");
    assert_eq!(payload["data"]["failed_substage"], "continuation_review");
    assert_eq!(payload["data"]["summary"], "翻译阶段超时");
    assert_eq!(payload["data"]["detail"], "provider timed out");
    assert_eq!(payload["data"]["retryable"], true);
    assert_eq!(payload["data"]["resume_available"], false);
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
            Some("failure classified".to_string()),
            Some("mineru".to_string()),
            Some("provider_failed".to_string()),
            "failure_classified",
            Some("failure_classified".to_string()),
            "message contains sk-route-secret",
            Some(1),
            Some(2),
            Some(json!({
                "api_key": "sk-route-secret",
                "note": "mineru-route-secret in payload"
            })),
            Some(0),
            Some(1234),
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
    assert_eq!(events_json["data"]["items"][0]["event_type"], "error");
    assert_eq!(
        events_json["data"]["items"][0]["raw_event_type"],
        "failure_classified"
    );
    assert_eq!(events_json["data"]["items"][0]["provider"], "mineru");
    assert_eq!(
        events_json["data"]["items"][0]["provider_stage"],
        "provider_failed"
    );
    assert_eq!(
        events_json["data"]["items"][0]["stage_detail"],
        "failure classified"
    );
    assert_eq!(events_json["data"]["items"][0]["payload"]["api_key"], "");
    assert_eq!(
        events_json["data"]["items"][0]["payload"]["note"],
        "[REDACTED] in payload"
    );
}

#[tokio::test]
async fn job_detail_route_prefers_formal_failure_fields() {
    let state = test_state("detail-formal-failure");
    let mut job = JobSnapshot::new(
        "job-route-formal-failure".to_string(),
        CreateJobInput::default(),
        vec!["python".to_string()],
    );
    job.status = JobStatusKind::Failed;
    job.failure = Some(crate::models::JobFailureInfo {
        stage: "failed".to_string(),
        category: "legacy_provider_failed".to_string(),
        code: Some("LEGACY-001".to_string()),
        failed_stage: Some("translation_prepare".to_string()),
        failure_code: Some("auth_failed".to_string()),
        failure_category: Some("auth".to_string()),
        provider_stage: Some("mineru_processing".to_string()),
        provider_code: Some("A0211".to_string()),
        summary: "鉴权失败".to_string(),
        root_cause: Some("token expired".to_string()),
        retryable: false,
        upstream_host: Some("mineru.example.test".to_string()),
        provider: Some("mineru".to_string()),
        suggestion: Some("检查 provider token".to_string()),
        last_log_line: Some("token expired during mineru_processing".to_string()),
        raw_excerpt: Some("token expired".to_string()),
        raw_error_excerpt: Some("legacy raw excerpt".to_string()),
        raw_diagnostic: None,
        ai_diagnostic: None,
    });
    state.db.save_job(&job).expect("save job");

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
        detail_json["data"]["failure"]["failed_stage"],
        "translation_prepare"
    );
    assert_eq!(
        detail_json["data"]["failure"]["failure_code"],
        "auth_failed"
    );
    assert_eq!(detail_json["data"]["failure"]["failure_category"], "auth");
    assert_eq!(
        detail_json["data"]["failure"]["provider_stage"],
        "mineru_processing"
    );
    assert_eq!(detail_json["data"]["failure"]["provider_code"], "A0211");
    assert_eq!(
        detail_json["data"]["failure"]["raw_excerpt"],
        "token expired"
    );
    assert_eq!(
        detail_json["data"]["failure_diagnostic"]["failed_stage"],
        "translation_prepare"
    );
    assert_eq!(
        detail_json["data"]["failure_diagnostic"]["error_kind"],
        "auth_failed"
    );
}

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
    assert_eq!(pipeline_item["stage"], "translation");
    assert_eq!(pipeline_item["substage"], "translation_batches");
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

#[tokio::test]
async fn job_events_route_keeps_rendering_page_progress_events() {
    let state = test_state("events-render-progress");
    let mut job = JobSnapshot::new(
        "job-route-render-progress".to_string(),
        CreateJobInput::default(),
        vec!["python".to_string()],
    );
    let job_root: PathBuf = state.config.data_root.join("jobs").join(&job.job_id);
    fs::create_dir_all(job_root.join("logs")).expect("create logs dir");
    job.artifacts
        .get_or_insert_with(crate::models::JobArtifacts::default)
        .job_root = Some(job_root.to_string_lossy().to_string());
    state.db.save_job(&job).expect("save job");
    fs::write(
        job_root.join("logs").join("pipeline_events.jsonl"),
        concat!(
            r#"{"job_id":"job-route-render-progress","seq":1,"ts":"2026-04-24T01:00:00Z","level":"info","stage":"rendering","stage_detail":"正在渲染第 1/3 页","provider":"","provider_stage":"","event_type":"stage_progress","message":"正在渲染第 1/3 页","progress_current":1,"progress_total":3,"retry_count":0,"elapsed_ms":1000,"payload":{"page_index":0,"render_stage":"book_overlay"}}"#,
            "\n",
            r#"{"job_id":"job-route-render-progress","seq":2,"ts":"2026-04-24T01:00:01Z","level":"error","stage":"failed","stage_detail":"渲染失败","provider":"","provider_stage":"","event_type":"job_terminal","message":"任务进入终态 failed","progress_current":null,"progress_total":null,"retry_count":0,"elapsed_ms":1100,"payload":{}}"#,
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
    assert_eq!(detail_json["data"]["stage"], "rendering");
    assert_eq!(detail_json["data"]["stage_detail"], "正在渲染第 1/3 页");
    assert_eq!(detail_json["data"]["progress"]["current"], 1);
    assert_eq!(detail_json["data"]["progress"]["total"], 3);
    assert_eq!(detail_json["data"]["progress"]["unit"], "page");

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
    let events = events_json["data"]["items"]
        .as_array()
        .expect("events items");
    let render_event = events
        .iter()
        .find(|item| item["raw_event_type"] == "stage_progress")
        .expect("render progress event");
    assert_eq!(render_event["stage"], "render");
    assert_eq!(render_event["lane"], "main");
    assert!(render_event.get("user_stage").is_none());
    assert_eq!(render_event["substage"], "render_pages");
    assert_eq!(render_event["event_type"], "progress");
    assert_eq!(render_event["progress"]["unit"], "page");
}

#[tokio::test]
async fn job_events_route_canonicalizes_render_prewarm_even_when_user_stage_is_stale() {
    let state = test_state("events-render-prewarm-canonical");
    let mut job = JobSnapshot::new(
        "job-route-render-prewarm-canonical".to_string(),
        CreateJobInput::default(),
        vec!["python".to_string()],
    );
    let job_root: PathBuf = state.config.data_root.join("jobs").join(&job.job_id);
    fs::create_dir_all(job_root.join("logs")).expect("create logs dir");
    job.artifacts
        .get_or_insert_with(crate::models::JobArtifacts::default)
        .job_root = Some(job_root.to_string_lossy().to_string());
    state.db.save_job(&job).expect("save job");
    fs::write(
        job_root.join("logs").join("pipeline_events.jsonl"),
        r#"{"job_id":"job-route-render-prewarm-canonical","seq":1,"ts":"2026-04-24T01:00:00Z","level":"info","user_stage":"translation","stage":"rendering","substage":"render_prewarm","stage_detail":"渲染预热完成","event_type":"stage_progress","message":"render payload prewarm: ready indents=333 geometry=836 elapsed=1.58s","progress_current":2,"progress_total":3,"progress_unit":"step","payload":{"render_stage":"payload_prewarm"}}"#,
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
    let item = events_json["data"]["items"]
        .as_array()
        .expect("events items")
        .first()
        .expect("event");
    assert_eq!(item["stage"], "render");
    assert_eq!(item["lane"], "background");
    assert!(item.get("user_stage").is_none());
    assert_eq!(item["substage"], "render_prewarm");
    assert_eq!(item["event_type"], "progress");
    assert_eq!(item["raw_event_type"], "stage_progress");
    assert_eq!(item["progress"]["unit"], "step");
    assert_eq!(item["payload"]["raw_user_stage"], "translation");
    assert_eq!(item["payload"]["raw_stage"], "rendering");
}

#[tokio::test]
async fn job_events_route_classifies_new_pipeline_substages() {
    let state = test_state("events-new-pipeline-substages");
    let mut job = JobSnapshot::new(
        "job-route-new-pipeline-substages".to_string(),
        CreateJobInput::default(),
        vec!["python".to_string()],
    );
    let job_root: PathBuf = state.config.data_root.join("jobs").join(&job.job_id);
    fs::create_dir_all(job_root.join("logs")).expect("create logs dir");
    job.artifacts
        .get_or_insert_with(crate::models::JobArtifacts::default)
        .job_root = Some(job_root.to_string_lossy().to_string());
    state.db.save_job(&job).expect("save job");
    fs::write(
        job_root.join("logs").join("pipeline_events.jsonl"),
        concat!(
            r#"{"job_id":"job-route-new-pipeline-substages","seq":1,"ts":"2026-04-24T01:00:00Z","level":"info","stage":"agent_repair","substage":"agent_repair","stage_detail":"翻译结果修复完成","event_type":"stage_progress","semantic_event_type":"progress","message":"翻译结果修复完成","progress_current":1,"progress_total":2,"payload":{}}"#,
            "\n",
            r#"{"job_id":"job-route-new-pipeline-substages","seq":2,"ts":"2026-04-24T01:00:01Z","level":"info","stage":"render_preprocess","substage":"render_prewarm","stage_detail":"渲染 payload 预热完成","event_type":"stage_progress","semantic_event_type":"progress","message":"render payload prewarm: ready","progress_current":2,"progress_total":3,"progress_unit":"step","payload":{}}"#,
            "\n"
        ),
    )
    .expect("write pipeline events");

    let response = build_app(state)
        .oneshot(
            Request::builder()
                .uri("/api/v1/jobs/job-route-new-pipeline-substages/events")
                .header("X-API-Key", "test-key")
                .body(Body::empty())
                .expect("events request"),
        )
        .await
        .expect("events response");
    assert_eq!(response.status(), StatusCode::OK);
    let events_json = read_json(response).await;
    let items = events_json["data"]["items"]
        .as_array()
        .expect("events items");
    assert_eq!(items[0]["stage"], "translation");
    assert_eq!(items[0]["substage"], "agent_repair");
    assert_eq!(items[0]["progress"]["unit"], "page");
    assert_eq!(items[1]["stage"], "render");
    assert_eq!(items[1]["lane"], "background");
    assert_eq!(items[1]["substage"], "render_prewarm");
    assert_eq!(items[1]["progress"]["unit"], "step");
}

#[tokio::test]
async fn main_job_events_include_ocr_child_page_progress() {
    let state = test_state("events-ocr-child-progress");
    let mut parent = JobSnapshot::new(
        "job-route-parent-progress".to_string(),
        CreateJobInput::default(),
        vec!["python".to_string()],
    );
    let parent_root: PathBuf = state.config.data_root.join("jobs").join(&parent.job_id);
    fs::create_dir_all(parent_root.join("logs")).expect("create parent logs dir");
    parent
        .artifacts
        .get_or_insert_with(crate::models::JobArtifacts::default)
        .job_root = Some(parent_root.to_string_lossy().to_string());
    parent.artifacts.as_mut().unwrap().ocr_job_id =
        Some("job-route-parent-progress-ocr".to_string());
    state.db.save_job(&parent).expect("save parent job");

    let mut child_input = CreateJobInput::default();
    child_input.workflow = crate::models::WorkflowKind::Ocr;
    let mut child = JobSnapshot::new(
        "job-route-parent-progress-ocr".to_string(),
        child_input,
        vec!["python".to_string()],
    );
    let child_root: PathBuf = state.config.data_root.join("jobs").join(&child.job_id);
    fs::create_dir_all(child_root.join("logs")).expect("create child logs dir");
    child
        .artifacts
        .get_or_insert_with(crate::models::JobArtifacts::default)
        .job_root = Some(child_root.to_string_lossy().to_string());
    state.db.save_job(&child).expect("save child job");
    fs::write(
        child_root.join("logs").join("pipeline_events.jsonl"),
        r#"{"job_id":"job-route-parent-progress-ocr","seq":1,"ts":"2026-04-24T01:00:00Z","level":"info","user_stage":"ocr","stage":"ocr_processing","substage":"provider_processing","stage_detail":"Paddle 正在解析文件，第 12/34 页","provider":"paddle","provider_stage":"provider_processing","event_type":"stage_progress","message":"Paddle 正在解析文件，第 12/34 页","progress_current":12,"progress_total":34,"progress_unit":"page","payload":{"provider_task_id":"task-1"}}"#,
    )
    .expect("write child pipeline events");

    let app = build_app(state.clone());
    let events_response = app
        .oneshot(
            Request::builder()
                .uri(format!("/api/v1/jobs/{}/events", parent.job_id))
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
    let ocr_progress = items
        .iter()
        .find(|item| item["stage"] == "ocr" && item["raw_event_type"] == "stage_progress")
        .expect("ocr child progress event");
    assert_eq!(ocr_progress["job_id"], parent.job_id);
    assert!(ocr_progress.get("user_stage").is_none());
    assert_eq!(ocr_progress["event_type"], "progress");
    assert_eq!(ocr_progress["substage"], "ocr_processing");
    assert!(ocr_progress.get("progress_unit").is_none());
    assert!(ocr_progress.get("progress_current").is_none());
    assert!(ocr_progress.get("progress_total").is_none());
    assert_eq!(ocr_progress["progress"]["unit"], "page");
    assert_eq!(
        ocr_progress["payload"]["source_job_id"],
        "job-route-parent-progress-ocr"
    );
}

#[tokio::test]
async fn reader_regions_route_maps_translated_items_to_source_blocks() {
    let state = test_state("reader-regions");
    let job_root = state.config.output_root.join("reader-region-job");
    let normalized_path = job_root.join("ocr/normalized/document.v1.json");
    let translated_dir = job_root.join("translated");
    fs::create_dir_all(normalized_path.parent().unwrap()).expect("normalized dir");
    fs::create_dir_all(&translated_dir).expect("translated dir");
    fs::write(
        &normalized_path,
        serde_json::to_vec(&json!({
            "pages": [{
                "page_index": 7,
                "blocks": [{
                    "block_id": "p008-b0009",
                    "bbox": [72.1, 132.4, 310.8, 186.2],
                    "source_text": "The source text",
                    "block_kind": "text"
                }]
            }]
        }))
        .expect("normalized json"),
    )
    .expect("write normalized");
    fs::write(
        translated_dir.join("page-008-deepseek.json"),
        serde_json::to_vec(&json!([
            {
                "item_id": "p008-b009",
                "page_idx": 7,
                "bbox": [74.0, 130.0, 330.0, 190.0],
                "translated_text": "译文",
                "render_markdown": "译文 markdown"
            }
        ]))
        .expect("page json"),
    )
    .expect("write translation page");
    fs::write(
        translated_dir.join("translation-manifest.json"),
        serde_json::to_vec(&json!({
            "pages": [{
                "page_index": 7,
                "path": "page-008-deepseek.json"
            }]
        }))
        .expect("manifest json"),
    )
    .expect("write manifest");

    let mut input = CreateJobInput::default();
    input.runtime.job_id = "reader-region-job".to_string();
    let mut job = JobSnapshot::new(
        "reader-region-job".to_string(),
        input,
        vec!["python".to_string()],
    );
    job.artifacts = Some(JobArtifacts {
        job_root: Some("jobs/reader-region-job".to_string()),
        normalized_document_json: Some(
            "jobs/reader-region-job/ocr/normalized/document.v1.json".to_string(),
        ),
        translations_dir: Some("jobs/reader-region-job/translated".to_string()),
        ..JobArtifacts::default()
    });
    state.db.save_job(&job).expect("save job");

    let response = build_app(state)
        .oneshot(
            Request::builder()
                .method("GET")
                .uri("/api/v1/jobs/reader-region-job/reader/regions")
                .header("X-API-Key", "test-key")
                .body(Body::empty())
                .expect("regions request"),
        )
        .await
        .expect("regions response");

    assert_eq!(response.status(), StatusCode::OK);
    let payload = read_json(response).await;
    assert_eq!(payload["data"]["items"][0]["item_id"], "p008-b009");
    assert_eq!(payload["data"]["items"][0]["source"]["page"], 8);
    assert_eq!(payload["data"]["items"][0]["translated"]["page"], 8);
    assert_eq!(
        payload["data"]["items"][0]["source"]["bbox"],
        json!([72.1, 132.4, 310.8, 186.2])
    );
    assert_eq!(
        payload["data"]["items"][0]["translated"]["bbox"],
        json!([74.0, 130.0, 330.0, 190.0])
    );
    assert_eq!(
        payload["data"]["items"][0]["source"]["text"],
        "The source text"
    );
    assert_eq!(payload["data"]["items"][0]["translated"]["text"], "译文");
    assert_eq!(payload["data"]["items"][0]["markdown"], "译文 markdown");
    assert_eq!(payload["data"]["items"][0]["region_type"], "text");
    assert_eq!(payload["data"]["items"][0]["status"], "translated");
}

#[tokio::test]
async fn reader_metadata_route_returns_pdf_page_dimensions_when_ready() {
    let state = test_state("reader-metadata");
    let job_root = state.config.output_root.join("reader-metadata-job");
    let source_dir = job_root.join("source");
    let rendered_dir = job_root.join("rendered");
    fs::create_dir_all(&source_dir).expect("source dir");
    fs::create_dir_all(&rendered_dir).expect("rendered dir");
    let source_pdf = source_dir.join("source.pdf");
    let translated_pdf = rendered_dir.join("translated.pdf");
    fs::write(&source_pdf, minimal_pdf_bytes(595, 842)).expect("source pdf");
    fs::write(&translated_pdf, minimal_pdf_bytes(612, 792)).expect("translated pdf");

    let mut input = CreateJobInput::default();
    input.runtime.job_id = "reader-metadata-job".to_string();
    let mut job = JobSnapshot::new(
        "reader-metadata-job".to_string(),
        input,
        vec!["python".to_string()],
    );
    job.artifacts = Some(JobArtifacts {
        job_root: Some("jobs/reader-metadata-job".to_string()),
        source_pdf: Some("jobs/reader-metadata-job/source/source.pdf".to_string()),
        output_pdf: Some("jobs/reader-metadata-job/rendered/translated.pdf".to_string()),
        ..JobArtifacts::default()
    });
    state.db.save_job(&job).expect("save job");

    let response = build_app(state)
        .oneshot(
            Request::builder()
                .method("GET")
                .uri("/api/v1/jobs/reader-metadata-job/reader/metadata")
                .header("X-API-Key", "test-key")
                .body(Body::empty())
                .expect("metadata request"),
        )
        .await
        .expect("metadata response");

    assert_eq!(response.status(), StatusCode::OK);
    let payload = read_json(response).await;
    assert_eq!(payload["data"]["source"]["page_count"], 1);
    assert_eq!(payload["data"]["source"]["pages"][0]["width"], 595.0);
    assert_eq!(payload["data"]["source"]["pages"][0]["height"], 842.0);
    assert_eq!(payload["data"]["translated"]["pages"][0]["width"], 612.0);
    assert_eq!(payload["data"]["translated"]["pages"][0]["height"], 792.0);
}

#[tokio::test]
async fn markdown_document_route_returns_content_and_direct_image_links() {
    let state = test_state("markdown-document");
    let job_root = state.config.output_root.join("markdown-document-job");
    let markdown_dir = job_root.join("md");
    let images_dir = markdown_dir.join("images/page-1/imgs");
    fs::create_dir_all(&images_dir).expect("create markdown images");
    fs::write(images_dir.join("chart a.png"), b"fake png").expect("write image");
    fs::write(
        markdown_dir.join("full.md"),
        "hello\n\n![Image](images/page-1/imgs/chart a.png)\n",
    )
    .expect("write markdown");

    let mut input = CreateJobInput::default();
    input.runtime.job_id = "markdown-document-job".to_string();
    let mut job = JobSnapshot::new(
        "markdown-document-job".to_string(),
        input,
        vec!["python".to_string()],
    );
    job.artifacts = Some(JobArtifacts {
        job_root: Some("jobs/markdown-document-job".to_string()),
        ..JobArtifacts::default()
    });
    state.db.save_job(&job).expect("save job");

    let response = build_app(state)
        .oneshot(
            Request::builder()
                .method("GET")
                .uri("/api/v1/jobs/markdown-document-job/markdown/document")
                .header("X-API-Key", "test-key")
                .body(Body::empty())
                .expect("markdown document request"),
        )
        .await
        .expect("markdown document response");

    assert_eq!(response.status(), StatusCode::OK);
    let payload = read_json(response).await;
    assert_eq!(payload["data"]["job_id"], "markdown-document-job");
    assert_eq!(payload["data"]["ready"], true);
    assert_eq!(
        payload["data"]["content"],
        "hello\n\n![Image](images/page-1/imgs/chart a.png)\n"
    );
    assert!(payload["data"]["content_with_absolute_image_urls"]
        .as_str()
        .expect("absolute markdown")
        .contains("http://127.0.0.1:41000/api/v1/jobs/markdown-document-job/markdown/images/page-1/imgs/chart%20a.png"));
    assert_eq!(
        payload["data"]["raw_path"],
        "/api/v1/jobs/markdown-document-job/markdown?raw=true"
    );
    assert_eq!(
        payload["data"]["images_base_path"],
        "/api/v1/jobs/markdown-document-job/markdown/images/"
    );
    let image = &payload["data"]["images"][0];
    assert_eq!(image["path"], "images/page-1/imgs/chart a.png");
    assert_eq!(image["content_type"], "image/png");
    assert_eq!(image["size_bytes"], 8);
    assert_eq!(
        image["url"],
        "http://127.0.0.1:41000/api/v1/jobs/markdown-document-job/markdown/images/page-1/imgs/chart%20a.png"
    );
}

fn minimal_pdf_bytes(width: i64, height: i64) -> Vec<u8> {
    let objects = [
        "<< /Type /Catalog /Pages 2 0 R >>".to_string(),
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>".to_string(),
        format!("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] >>"),
    ];
    let mut bytes = b"%PDF-1.4\n".to_vec();
    let mut offsets = vec![0usize];
    for (idx, object) in objects.iter().enumerate() {
        offsets.push(bytes.len());
        bytes.extend_from_slice(format!("{} 0 obj\n{}\nendobj\n", idx + 1, object).as_bytes());
    }
    let xref_offset = bytes.len();
    bytes.extend_from_slice(format!("xref\n0 {}\n", offsets.len()).as_bytes());
    bytes.extend_from_slice(b"0000000000 65535 f \n");
    for offset in offsets.iter().skip(1) {
        bytes.extend_from_slice(format!("{offset:010} 00000 n \n").as_bytes());
    }
    bytes.extend_from_slice(
        format!(
            "trailer\n<< /Size {} /Root 1 0 R >>\nstartxref\n{}\n%%EOF\n",
            offsets.len(),
            xref_offset
        )
        .as_bytes(),
    );
    bytes
}

#[tokio::test]
async fn job_events_route_prefers_formal_failure_fields() {
    let state = test_state("events-formal-failure");
    let mut job = JobSnapshot::new(
        "job-route-events-formal-failure".to_string(),
        CreateJobInput::default(),
        vec!["python".to_string()],
    );
    job.status = JobStatusKind::Failed;
    job.stage = Some("failed".to_string());
    job.replace_failure_info(Some(JobFailureInfo {
        stage: "translation".to_string(),
        category: "upstream_timeout".to_string(),
        code: Some("timeout_504".to_string()),
        failed_stage: Some("translation_prepare".to_string()),
        failure_code: Some("upstream_timeout".to_string()),
        failure_category: Some("timeout".to_string()),
        provider_stage: Some("llm_request".to_string()),
        provider_code: Some("timeout_504".to_string()),
        summary: "请求超时".to_string(),
        root_cause: Some("LLM upstream timed out".to_string()),
        retryable: true,
        upstream_host: Some("api.deepseek.com".to_string()),
        provider: Some("deepseek".to_string()),
        suggestion: Some("稍后重试".to_string()),
        last_log_line: Some("timeout".to_string()),
        raw_excerpt: Some("deadline exceeded".to_string()),
        raw_error_excerpt: Some("deadline exceeded".to_string()),
        raw_diagnostic: None,
        ai_diagnostic: None,
    }));
    state.db.save_job(&job).expect("save job");
    state
        .db
        .append_event(
            &job.job_id,
            "error",
            Some("failed".to_string()),
            None,
            None,
            None,
            "failure_classified",
            Some("failure_classified".to_string()),
            "",
            None,
            None,
            Some(json!({
                "stage": "translation",
                "category": "upstream_timeout",
                "code": "timeout_504",
                "summary": "请求超时"
            })),
            Some(0),
            Some(100),
        )
        .expect("append failure event");
    state
        .db
        .append_event(
            &job.job_id,
            "error",
            Some("failed".to_string()),
            None,
            None,
            None,
            "job_terminal",
            Some("job_terminal".to_string()),
            "",
            None,
            None,
            Some(json!({
                "status": "failed"
            })),
            Some(0),
            Some(120),
        )
        .expect("append terminal event");

    let app = build_app(state.clone());
    let response = app
        .oneshot(
            Request::builder()
                .uri(format!("/api/v1/jobs/{}/events", job.job_id))
                .header("X-API-Key", "test-key")
                .body(Body::empty())
                .expect("events request"),
        )
        .await
        .expect("events response");
    assert_eq!(response.status(), StatusCode::OK);
    let events_json = read_json(response).await;
    let items = events_json["data"]["items"]
        .as_array()
        .expect("items array");
    let failure_item = items
        .iter()
        .find(|item| item["event"] == "failure_classified")
        .expect("failure event");
    assert_eq!(failure_item["stage"], "done");
    assert_eq!(
        failure_item["payload"]["failure_stage"],
        "translation_prepare"
    );
    assert_eq!(failure_item["provider"], "deepseek");
    assert_eq!(failure_item["provider_stage"], "llm_request");
    assert_eq!(
        failure_item["payload"]["failed_stage"],
        "translation_prepare"
    );
    assert_eq!(failure_item["payload"]["failure_code"], "upstream_timeout");
    assert_eq!(failure_item["payload"]["failure_category"], "timeout");
    assert_eq!(failure_item["payload"]["provider_code"], "timeout_504");

    let terminal_item = items
        .iter()
        .find(|item| item["event"] == "job_terminal")
        .expect("terminal event");
    assert_eq!(terminal_item["stage"], "done");
    assert_eq!(
        terminal_item["payload"]["failure_stage"],
        "translation_prepare"
    );
    assert_eq!(terminal_item["provider"], "deepseek");
    assert_eq!(terminal_item["provider_stage"], "llm_request");
    assert_eq!(terminal_item["payload"]["status"], "failed");
    assert_eq!(
        terminal_item["payload"]["failed_stage"],
        "translation_prepare"
    );
    assert_eq!(terminal_item["payload"]["failure_code"], "upstream_timeout");
    assert_eq!(terminal_item["payload"]["failure_category"], "timeout");
}

#[tokio::test]
async fn failed_job_events_include_contract_readiness_payload() {
    let state = test_state("events-contracts");
    let job_id = "job-route-events-contracts";
    let job_root: PathBuf = state.config.data_root.join("jobs").join(job_id);
    let source_pdf = job_root.join("source/input.pdf");
    let translations_dir = job_root.join("translated");
    fs::create_dir_all(source_pdf.parent().expect("source parent")).expect("source dir");
    fs::create_dir_all(&translations_dir).expect("translations dir");
    fs::write(&source_pdf, b"%PDF").expect("source pdf");

    let mut job = JobSnapshot::new(
        job_id.to_string(),
        CreateJobInput::default(),
        vec!["python".to_string()],
    );
    job.status = JobStatusKind::Failed;
    job.stage = Some("failed".to_string());
    job.artifacts = Some(JobArtifacts {
        job_root: Some(job_root.to_string_lossy().to_string()),
        source_pdf: Some(source_pdf.to_string_lossy().to_string()),
        translations_dir: Some(translations_dir.to_string_lossy().to_string()),
        ..JobArtifacts::default()
    });
    state.db.save_job(&job).expect("save job");
    state
        .db
        .append_event(
            &job.job_id,
            "error",
            Some("failed".to_string()),
            None,
            None,
            None,
            "job_terminal",
            Some("job_terminal".to_string()),
            "任务进入终态 failed",
            None,
            None,
            Some(json!({"status": "failed"})),
            Some(0),
            Some(120),
        )
        .expect("append terminal event");

    let app = build_app(state.clone());
    let response = app
        .oneshot(
            Request::builder()
                .uri(format!("/api/v1/jobs/{job_id}/events"))
                .header("X-API-Key", "test-key")
                .body(Body::empty())
                .expect("events request"),
        )
        .await
        .expect("events response");
    assert_eq!(response.status(), StatusCode::OK);
    let events_json = read_json(response).await;
    let terminal_item = events_json["data"]["items"]
        .as_array()
        .expect("items")
        .iter()
        .find(|item| item["event"] == "job_terminal")
        .expect("terminal event");
    assert_eq!(
        terminal_item["payload"]["contracts"]["schema_version"],
        "job_stage_contracts.v1"
    );
    let stages = terminal_item["payload"]["contracts"]["stages"]
        .as_array()
        .expect("contract stages");
    let translation_stage = stages
        .iter()
        .find(|item| item["stage"] == "translation_ready_for_render")
        .expect("translation stage");
    assert_eq!(translation_stage["ready"], false);
    let manifest = translation_stage["artifacts"]
        .as_array()
        .expect("artifacts")
        .iter()
        .find(|item| item["artifact_key"] == "translation_manifest_json")
        .expect("manifest artifact");
    assert_eq!(manifest["ready"], false);
}

#[tokio::test]
async fn job_detail_route_prefers_live_pipeline_stage_snapshot() {
    let state = test_state("detail-live-stage");
    let mut job = JobSnapshot::new(
        "job-route-live-stage".to_string(),
        CreateJobInput::default(),
        vec!["python".to_string()],
    );
    job.stage = Some("queued".to_string());
    job.stage_detail = Some("old queued detail".to_string());
    let job_root: PathBuf = state.config.data_root.join("jobs").join(&job.job_id);
    fs::create_dir_all(job_root.join("logs")).expect("create logs dir");
    job.artifacts
        .get_or_insert_with(crate::models::JobArtifacts::default)
        .job_root = Some(job_root.to_string_lossy().to_string());
    state.db.save_job(&job).expect("save job");
    fs::write(
        job_root.join("logs").join("pipeline_events.jsonl"),
        concat!(
            r#"{"job_id":"job-route-live-stage","seq":1,"ts":"2026-04-24T01:00:00Z","level":"info","stage":"translating","stage_detail":"已完成第 2/5 批翻译","provider":"","provider_stage":"","event_type":"stage_progress","message":"已完成第 2/5 批翻译","progress_current":2,"progress_total":5,"retry_count":0,"elapsed_ms":1000,"payload":{}}"#,
            "\n",
            r#"{"job_id":"job-route-live-stage","seq":2,"ts":"2026-04-24T01:00:01Z","level":"info","stage":"saving","stage_detail":"最终 PDF 已发布","provider":"","provider_stage":"","event_type":"artifact_published","message":"最终 PDF 已发布","progress_current":null,"progress_total":null,"retry_count":0,"elapsed_ms":1100,"payload":{"artifact_key":"output_pdf"}}"#,
            "\n"
        ),
    )
    .expect("write pipeline events");

    let app = build_app(state.clone());
    let detail_response = app
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
    assert_eq!(detail_json["data"]["stage_detail"], "已完成第 2/5 批翻译");
    assert_eq!(detail_json["data"]["progress"]["current"], 2);
    assert_eq!(detail_json["data"]["progress"]["total"], 5);
}

#[tokio::test]
async fn job_detail_route_ignores_background_render_prewarm_for_main_stage() {
    let state = test_state("detail-ignores-background-prewarm");
    let mut job = JobSnapshot::new(
        "job-route-background-prewarm".to_string(),
        CreateJobInput::default(),
        vec!["python".to_string()],
    );
    job.stage = Some("queued".to_string());
    let job_root: PathBuf = state.config.data_root.join("jobs").join(&job.job_id);
    fs::create_dir_all(job_root.join("logs")).expect("create logs dir");
    job.artifacts
        .get_or_insert_with(crate::models::JobArtifacts::default)
        .job_root = Some(job_root.to_string_lossy().to_string());
    state.db.save_job(&job).expect("save job");
    fs::write(
        job_root.join("logs").join("pipeline_events.jsonl"),
        concat!(
            r#"{"job_id":"job-route-background-prewarm","seq":1,"ts":"2026-04-24T01:00:00Z","level":"info","stage":"translating","stage_detail":"已完成第 2/5 批翻译","event_type":"stage_progress","message":"已完成第 2/5 批翻译","progress_current":2,"progress_total":5,"payload":{}}"#,
            "\n",
            r#"{"job_id":"job-route-background-prewarm","seq":2,"ts":"2026-04-24T01:00:01Z","level":"info","stage":"rendering","substage":"render_prewarm","stage_detail":"渲染预热完成","event_type":"stage_progress","message":"render payload prewarm: ready","progress_current":3,"progress_total":3,"progress_unit":"step","payload":{"render_stage":"payload_prewarm"}}"#,
            "\n"
        ),
    )
    .expect("write pipeline events");

    let app = build_app(state.clone());
    let detail_response = app
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
    assert_eq!(detail_json["data"]["stage_detail"], "已完成第 2/5 批翻译");
    assert_eq!(detail_json["data"]["progress"]["current"], 2);
    assert_eq!(detail_json["data"]["progress"]["total"], 5);
    assert_eq!(detail_json["data"]["progress"]["unit"], "batch");
}

#[tokio::test]
async fn job_detail_route_keeps_render_page_progress_over_compile_steps() {
    let state = test_state("detail-render-page-over-compile");
    let mut job = JobSnapshot::new(
        "job-route-render-page-over-compile".to_string(),
        CreateJobInput::default(),
        vec!["python".to_string()],
    );
    job.stage = Some("rendering".to_string());
    let job_root: PathBuf = state.config.data_root.join("jobs").join(&job.job_id);
    fs::create_dir_all(job_root.join("logs")).expect("create logs dir");
    job.artifacts
        .get_or_insert_with(crate::models::JobArtifacts::default)
        .job_root = Some(job_root.to_string_lossy().to_string());
    state.db.save_job(&job).expect("save job");
    fs::write(
        job_root.join("logs").join("pipeline_events.jsonl"),
        concat!(
            r#"{"job_id":"job-route-render-page-over-compile","seq":1,"ts":"2026-04-24T01:00:00Z","level":"info","user_stage":"render","stage":"rendering","substage":"render_pages","stage_detail":"正在生成 Typst 页面，第 548/548 页","event_type":"stage_progress","message":"正在生成 Typst 页面，第 548/548 页","progress_current":548,"progress_total":548,"progress_unit":"page","payload":{"render_stage":"typst_source_build"}}"#,
            "\n",
            r#"{"job_id":"job-route-render-page-over-compile","seq":2,"ts":"2026-04-24T01:00:01Z","level":"info","user_stage":"render","stage":"rendering","substage":"render_compile","stage_detail":"整本 Typst 渲染编译完成，共 548 页","event_type":"stage_progress","message":"整本 Typst 渲染编译完成，共 548 页","progress_current":4,"progress_total":4,"progress_unit":"step","payload":{"render_stage":"background_typst_compile_done"}}"#,
            "\n"
        ),
    )
    .expect("write pipeline events");

    let app = build_app(state.clone());
    let detail_response = app
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
    assert_eq!(detail_json["data"]["stage"], "rendering");
    assert_eq!(
        detail_json["data"]["stage_detail"],
        "整本 Typst 渲染编译完成，共 548 页"
    );
    assert_eq!(detail_json["data"]["progress"]["current"], 548);
    assert_eq!(detail_json["data"]["progress"]["total"], 548);
    assert_eq!(detail_json["data"]["progress"]["unit"], "page");
}

#[tokio::test]
async fn job_detail_route_exposes_stage_contract_readiness() {
    let state = test_state("detail-stage-contracts");
    let job_id = "job-route-stage-contracts";
    let job_root: PathBuf = state.config.data_root.join("jobs").join(job_id);
    let source_pdf = job_root.join("source/input.pdf");
    let translations_dir = job_root.join("translated");
    fs::create_dir_all(source_pdf.parent().expect("source parent")).expect("source dir");
    fs::create_dir_all(&translations_dir).expect("translations dir");
    fs::write(&source_pdf, b"%PDF").expect("source pdf");

    let mut job = JobSnapshot::new(
        job_id.to_string(),
        CreateJobInput::default(),
        vec!["python".to_string()],
    );
    job.artifacts = Some(JobArtifacts {
        job_root: Some(job_root.to_string_lossy().to_string()),
        source_pdf: Some(source_pdf.to_string_lossy().to_string()),
        translations_dir: Some(translations_dir.to_string_lossy().to_string()),
        ..JobArtifacts::default()
    });
    state.db.save_job(&job).expect("save job");

    let app = build_app(state.clone());
    let detail_response = app
        .oneshot(
            Request::builder()
                .uri(format!("/api/v1/jobs/{job_id}"))
                .header("X-API-Key", "test-key")
                .body(Body::empty())
                .expect("detail request"),
        )
        .await
        .expect("detail response");
    assert_eq!(detail_response.status(), StatusCode::OK);
    let detail_json = read_json(detail_response).await;
    assert_eq!(
        detail_json["data"]["contracts"]["schema_version"],
        "job_stage_contracts.v1"
    );
    let stages = detail_json["data"]["contracts"]["stages"]
        .as_array()
        .expect("contract stages");
    let translation_stage = stages
        .iter()
        .find(|item| item["stage"] == "translation_ready_for_render")
        .expect("translation contract");
    assert_eq!(translation_stage["ready"], false);
    let manifest = translation_stage["artifacts"]
        .as_array()
        .expect("artifacts")
        .iter()
        .find(|item| item["artifact_key"] == "translation_manifest_json")
        .expect("manifest artifact");
    assert_eq!(manifest["required"], true);
    assert_eq!(manifest["ready"], false);
}

#[tokio::test]
async fn jobs_list_route_prefers_live_pipeline_stage_snapshot() {
    let state = test_state("list-live-stage");
    let mut job = JobSnapshot::new(
        "job-route-list-live-stage".to_string(),
        CreateJobInput::default(),
        vec!["python".to_string()],
    );
    job.stage = Some("queued".to_string());
    let job_root: PathBuf = state.config.data_root.join("jobs").join(&job.job_id);
    fs::create_dir_all(job_root.join("logs")).expect("create logs dir");
    job.artifacts
        .get_or_insert_with(crate::models::JobArtifacts::default)
        .job_root = Some(job_root.to_string_lossy().to_string());
    state.db.save_job(&job).expect("save job");
    fs::write(
        job_root.join("logs").join("pipeline_events.jsonl"),
        concat!(
            r#"{"job_id":"job-route-list-live-stage","seq":1,"ts":"2026-04-24T01:00:00Z","level":"info","stage":"translating","stage_detail":"已完成第 3/8 批翻译","provider":"","provider_stage":"","event_type":"stage_progress","message":"已完成第 3/8 批翻译","progress_current":3,"progress_total":8,"retry_count":0,"elapsed_ms":900,"payload":{}}"#,
            "\n",
            r#"{"job_id":"job-route-list-live-stage","seq":2,"ts":"2026-04-24T01:00:01Z","level":"info","stage":"saving","stage_detail":"最终 PDF 已发布","provider":"","provider_stage":"","event_type":"artifact_published","message":"最终 PDF 已发布","progress_current":null,"progress_total":null,"retry_count":0,"elapsed_ms":1000,"payload":{"artifact_key":"output_pdf"}}"#,
            "\n"
        ),
    )
    .expect("write pipeline events");

    let app = build_app(state.clone());
    let list_response = app
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
    let items = list_json["data"]["items"].as_array().expect("items array");
    let item = items
        .iter()
        .find(|item| item["job_id"] == "job-route-list-live-stage")
        .expect("job item");
    assert_eq!(item["stage"], "translating");
}

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
    assert_eq!(stage_progress["stage"], "translation");
    assert_eq!(artifact_published["event_type"], "artifact");
    assert_eq!(artifact_published["raw_event_type"], "artifact_published");
    assert_eq!(artifact_published["stage"], "render");
    assert_eq!(artifact_published["substage"], "render_pages");
}
