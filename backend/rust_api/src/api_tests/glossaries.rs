use std::collections::HashSet;
use std::sync::Arc;

use axum::body::to_bytes;
use axum::body::Body;
use axum::http::{header, Request, StatusCode};
use tower::util::ServiceExt;

use crate::app::build_app;
use crate::config::AppConfig;
use crate::db::Db;
use crate::models::GlossaryUpsertInput;
use crate::AppState;

fn test_state() -> AppState {
    let root = std::env::temp_dir().join(format!("rust-api-glossary-route-{}", fastrand::u64(..)));
    let data_root = root.join("data");
    let output_root = data_root.join("jobs");
    let downloads_dir = data_root.join("downloads");
    let uploads_dir = data_root.join("uploads");
    let rust_api_root = root.join("rust_api");
    let scripts_dir = root.join("scripts");
    std::fs::create_dir_all(&output_root).expect("create output root");
    std::fs::create_dir_all(&downloads_dir).expect("create downloads dir");
    std::fs::create_dir_all(&uploads_dir).expect("create uploads dir");
    std::fs::create_dir_all(&rust_api_root).expect("create rust_api root");
    std::fs::create_dir_all(&scripts_dir).expect("create scripts dir");

    let config = Arc::new(AppConfig {
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
    });

    AppState {
        config: config.clone(),
        db: Arc::new(Db::new(
            config.jobs_db_path.clone(),
            config.data_root.clone(),
        )),
        downloads_lock: Arc::new(tokio::sync::Mutex::new(())),
        canceled_jobs: Arc::new(tokio::sync::RwLock::new(HashSet::new())),
        job_slots: Arc::new(tokio::sync::Semaphore::new(1)),
    }
}

#[tokio::test]
async fn export_glossary_csv_route_returns_csv() {
    let state = test_state();
    let app = build_app(state.clone());
    let create = crate::services::glossaries::create_glossary(
        state.db.as_ref(),
        &GlossaryUpsertInput {
            glossary_id: String::new(),
            name: "physics".to_string(),
            description: "physics glossary".to_string(),
            source_lang: "en".to_string(),
            target_lang: "zh-CN".to_string(),
            enabled: true,
            entries: vec![crate::models::GlossaryEntryInput {
                source: "band gap".to_string(),
                target: "带隙".to_string(),
                note: String::new(),
                level: String::new(),
                match_mode: String::new(),
                context: String::new(),
            }],
        },
    )
    .expect("create glossary");

    let request = Request::builder()
        .uri(format!(
            "/api/v1/glossaries/{}/export.csv",
            create.glossary_id
        ))
        .header("X-API-Key", "test-key")
        .body(Body::empty())
        .expect("request");

    let response = app.oneshot(request).await.expect("response");
    assert_eq!(response.status(), StatusCode::OK);
    assert_eq!(
        response
            .headers()
            .get(header::CONTENT_TYPE)
            .and_then(|v| v.to_str().ok()),
        Some("text/csv; charset=utf-8")
    );
    let body = to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("body");
    let text = std::str::from_utf8(&body).expect("csv text");
    assert!(text.contains("band gap"));
}

#[tokio::test]
async fn import_glossary_route_creates_glossary() {
    let state = test_state();
    let app = build_app(state.clone());
    let request = Request::builder()
        .method("POST")
        .uri("/api/v1/glossaries/import")
        .header("X-API-Key", "test-key")
        .header(header::CONTENT_TYPE, "application/json")
        .body(Body::from(
            r#"{
                "name": "imported",
                "description": "imported glossary",
                "source_lang": "en",
                "target_lang": "zh-CN",
                "enabled": true,
                "entries": [
                    {"source": "SCF", "target": "自洽场", "level": "preferred"}
                ]
            }"#,
        ))
        .expect("request");

    let response = app.oneshot(request).await.expect("response");
    assert_eq!(response.status(), StatusCode::OK);
    let body = to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("body");
    let payload: serde_json::Value = serde_json::from_slice(&body).expect("json");
    assert_eq!(payload["data"]["name"], "imported");
    assert_eq!(payload["data"]["entry_count"], 1);
    assert!(!payload["data"]["glossary_id"]
        .as_str()
        .unwrap_or("")
        .is_empty());
}
