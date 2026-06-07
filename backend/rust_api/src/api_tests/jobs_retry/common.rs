use std::fs;

use crate::api_tests::jobs_common::minimal_pdf_bytes;
use crate::models::{CreateJobInput, JobArtifacts, JobSnapshot};

pub(super) fn source_job_with_artifacts(job_id: &str, artifacts: JobArtifacts) -> JobSnapshot {
    let mut input = CreateJobInput::default();
    input.runtime.job_id = job_id.to_string();
    input.translation.api_key = "sk-rerun-test".to_string();
    input.translation.model = "deepseek-v4-flash".to_string();
    input.translation.base_url = "https://api.deepseek.com/v1".to_string();
    let mut job = JobSnapshot::new(job_id.to_string(), input, vec!["python".to_string()]);
    job.artifacts = Some(artifacts);
    job
}

pub(super) fn seed_ocr_checkpoint_files(state: &crate::AppState, job: &JobSnapshot) {
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
