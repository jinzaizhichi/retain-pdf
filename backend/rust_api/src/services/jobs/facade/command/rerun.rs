use axum::http::HeaderMap;

use crate::error::AppError;
use crate::models::{
    CreateJobInput, JobArtifacts, JobSnapshot, JobSourceInput, JobStatusKind, JobSubmissionView,
    WorkflowKind,
};

use super::super::super::creation::create_translation_job;
use super::super::super::query::load_job_or_404;
use super::super::JobsFacade;

impl<'a> JobsFacade<'a> {
    pub fn rerun_submission(
        &self,
        headers: &HeaderMap,
        source_job_id: &str,
    ) -> Result<JobSubmissionView, AppError> {
        let source_job = load_job_or_404(self.command.db, source_job_id)?;
        let request = build_rerun_request(&source_job)?;
        let workflow = request.workflow.clone();
        let job = create_translation_job(&self.command.submit, &request)?;
        Ok(self.build_submission_view(headers, &job, JobStatusKind::Queued, workflow))
    }
}

fn build_rerun_request(source_job: &JobSnapshot) -> Result<CreateJobInput, AppError> {
    let artifacts = source_job
        .artifacts
        .as_ref()
        .ok_or_else(|| AppError::bad_request("source job has no reusable artifacts"))?;
    let workflow = choose_rerun_workflow(artifacts)?;
    let mut request = CreateJobInput {
        workflow,
        source: JobSourceInput {
            upload_id: source_job.request_payload.source.upload_id.clone(),
            source_url: source_job.request_payload.source.source_url.clone(),
            artifact_job_id: source_job.request_payload.source.artifact_job_id.clone(),
        },
        ocr: source_job.request_payload.ocr.clone(),
        translation: source_job.request_payload.translation.clone(),
        render: source_job.request_payload.render.clone(),
        runtime: source_job.request_payload.runtime.clone(),
    };
    request.source.upload_id.clear();
    request.source.source_url.clear();
    request.source.artifact_job_id = source_job.job_id.clone();
    request.runtime.job_id.clear();
    Ok(request)
}

fn choose_rerun_workflow(artifacts: &JobArtifacts) -> Result<WorkflowKind, AppError> {
    if has_text(&artifacts.translations_dir) && has_text(&artifacts.source_pdf) {
        return Ok(WorkflowKind::Render);
    }
    if has_text(&artifacts.normalized_document_json) && has_text(&artifacts.source_pdf) {
        return Ok(WorkflowKind::Book);
    }
    Err(AppError::bad_request(
        "source job has no reusable checkpoint; need translations_dir+source_pdf or normalized_document_json+source_pdf",
    ))
}

fn has_text(value: &Option<String>) -> bool {
    value
        .as_deref()
        .map(str::trim)
        .is_some_and(|item| !item.is_empty())
}
