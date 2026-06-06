use crate::error::AppError;
use crate::job_failure::classify_job_failure;
use crate::models::{JobDiagnosticsView, JobFailureInfo, JobResumePlanView, JobSnapshot};
use crate::services::jobs::stage_plan::resume_plan;

use super::super::super::presentation::load_supported_job;
use super::super::JobsFacade;

impl<'a> JobsFacade<'a> {
    pub fn job_diagnostics_view(&self, job_id: &str) -> Result<JobDiagnosticsView, AppError> {
        let job = load_supported_job(self.query.db, self.query.data_root, job_id)?;
        Ok(build_job_diagnostics_view(&job))
    }

    pub fn resume_plan_view(&self, job_id: &str) -> Result<JobResumePlanView, AppError> {
        let job = load_supported_job(self.query.db, self.query.data_root, job_id)?;
        Ok(build_resume_plan_view(&job))
    }
}

fn build_job_diagnostics_view(job: &JobSnapshot) -> JobDiagnosticsView {
    let failure = resolved_failure(job);
    let resume_plan = build_resume_plan_view(job);
    match failure {
        Some(failure) => JobDiagnosticsView {
            failed_stage: Some(failure.failed_stage_value().to_string()),
            failed_substage: failure.provider_stage.clone(),
            summary: failure.summary.clone(),
            detail: failure
                .root_cause
                .clone()
                .or_else(|| failure.raw_excerpt.clone())
                .or_else(|| failure.raw_error_excerpt.clone())
                .or_else(|| failure.last_log_line.clone()),
            suggestion: failure.suggestion.clone(),
            retryable: failure.retryable,
            resume_available: resume_plan.can_resume,
        },
        None => JobDiagnosticsView {
            failed_stage: job.stage.clone(),
            failed_substage: None,
            summary: if matches!(job.status, crate::models::JobStatusKind::Failed) {
                job.error
                    .clone()
                    .filter(|value| !value.trim().is_empty())
                    .unwrap_or_else(|| "任务失败，但暂未识别出明确原因".to_string())
            } else {
                "任务当前没有失败诊断".to_string()
            },
            detail: job.error.clone(),
            suggestion: None,
            retryable: false,
            resume_available: resume_plan.can_resume,
        },
    }
}

fn build_resume_plan_view(job: &JobSnapshot) -> JobResumePlanView {
    let plan = resume_plan(job);
    JobResumePlanView {
        can_resume: plan.can_resume,
        job_id: job.job_id.clone(),
        from_stage: plan.from_stage,
        resume_workflow: plan.resume_workflow,
        reuses_artifacts: plan.reuses_artifacts,
        reruns_stages: plan.reruns_stages,
        reason: plan.reason,
    }
}

fn resolved_failure(job: &JobSnapshot) -> Option<JobFailureInfo> {
    job.failure
        .clone()
        .map(JobFailureInfo::with_formal_fields)
        .or_else(|| classify_job_failure(job).map(JobFailureInfo::with_formal_fields))
}
