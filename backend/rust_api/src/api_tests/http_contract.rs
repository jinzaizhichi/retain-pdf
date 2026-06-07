use axum::body::Body;
use axum::http::{Request, StatusCode};
use serde_json::json;
use tower::util::ServiceExt;

use crate::api_tests::jobs_common::{read_json, test_state};
use crate::app::build_app;

#[tokio::test]
async fn json_success_routes_use_api_response_envelope() {
    let response = build_app(test_state("http-contract-success"))
        .oneshot(
            Request::builder()
                .uri("/api/v1/jobs")
                .header("X-API-Key", "test-key")
                .body(Body::empty())
                .expect("list jobs request"),
        )
        .await
        .expect("list jobs response");

    assert_eq!(response.status(), StatusCode::OK);
    let body = read_json(response).await;
    assert_eq!(body["code"], 0);
    assert_eq!(body["message"], "ok");
    assert!(body.get("data").is_some());
}

#[tokio::test]
async fn missing_api_key_uses_json_error_envelope() {
    let response = build_app(test_state("http-contract-unauthorized"))
        .oneshot(
            Request::builder()
                .uri("/api/v1/jobs")
                .body(Body::empty())
                .expect("list jobs request"),
        )
        .await
        .expect("list jobs response");

    assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
    let body = read_json(response).await;
    assert_eq!(body["code"], 40100);
    assert_eq!(body["message"], "missing or invalid X-API-Key");
    assert!(body.get("data").is_none());
}

#[tokio::test]
async fn missing_job_uses_json_not_found_envelope() {
    let response = build_app(test_state("http-contract-not-found"))
        .oneshot(
            Request::builder()
                .uri("/api/v1/jobs/missing-job")
                .header("X-API-Key", "test-key")
                .body(Body::empty())
                .expect("job detail request"),
        )
        .await
        .expect("job detail response");

    assert_eq!(response.status(), StatusCode::NOT_FOUND);
    let body = read_json(response).await;
    assert_eq!(body["code"], 40400);
    assert!(body["message"]
        .as_str()
        .expect("message")
        .contains("missing-job"));
    assert!(body.get("data").is_none());
}

#[tokio::test]
async fn invalid_job_payload_uses_json_bad_request_envelope() {
    let response = build_app(test_state("http-contract-bad-request"))
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/v1/jobs")
                .header("X-API-Key", "test-key")
                .header("content-type", "application/json")
                .body(Body::from(json!({"source": 3}).to_string()))
                .expect("create job request"),
        )
        .await
        .expect("create job response");

    assert_eq!(response.status(), StatusCode::BAD_REQUEST);
    let body = read_json(response).await;
    assert_eq!(body["code"], 40000);
    assert!(body["message"]
        .as_str()
        .expect("message")
        .contains("invalid job payload"));
    assert!(body.get("data").is_none());
}
