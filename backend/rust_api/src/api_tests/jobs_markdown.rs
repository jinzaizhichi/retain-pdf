use std::fs;

use axum::body::Body;
use axum::http::{Request, StatusCode};
use tower::util::ServiceExt;

use super::jobs_common::{read_json, test_state};
use crate::app::build_app;
use crate::models::{CreateJobInput, JobArtifacts, JobSnapshot};

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
