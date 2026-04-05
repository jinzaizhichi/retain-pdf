use crate::error::AppError;
use crate::models::{JobSnapshot, ListJobsQuery};
use crate::storage_paths::{
    job_uses_legacy_output_layout, job_uses_legacy_path_storage, LEGACY_JOB_UNSUPPORTED_MESSAGE,
};
use crate::AppState;

pub fn load_job_or_404(state: &AppState, job_id: &str) -> Result<JobSnapshot, AppError> {
    state
        .db
        .get_job(job_id)
        .map_err(|_| AppError::not_found(format!("job not found: {job_id}")))
}

pub fn ensure_supported_job_layout(state: &AppState, job: &JobSnapshot) -> Result<(), AppError> {
    if job_uses_legacy_output_layout(job, &state.config.data_root)
        || job_uses_legacy_path_storage(job)
    {
        return Err(AppError::conflict(LEGACY_JOB_UNSUPPORTED_MESSAGE));
    }
    Ok(())
}

pub fn list_jobs_filtered(
    state: &AppState,
    query: &ListJobsQuery,
) -> Result<Vec<JobSnapshot>, AppError> {
    let jobs = state.db.list_jobs(
        query.limit,
        query.offset,
        query.status.as_ref(),
        query.workflow.as_ref(),
    )?;
    Ok(jobs
        .into_iter()
        .filter(|job| {
            query
                .provider
                .as_deref()
                .map(|provider| {
                    job.artifacts
                        .as_ref()
                        .and_then(|artifacts| artifacts.ocr_provider_diagnostics.as_ref())
                        .map(|diag| {
                            format!("{:?}", diag.provider).to_ascii_lowercase()
                                == provider.to_ascii_lowercase()
                        })
                        .unwrap_or(false)
                })
                .unwrap_or(true)
        })
        .collect())
}
