use anyhow::Result;

use crate::models::{
    job_stage_detail, job_stage_str, now_iso, JobRuntimeState, JobStage, JobStatusKind,
};

use super::render_flow_artifacts::prepare_render_job_from_artifacts;
use super::{
    build_render_only_command, clear_job_failure, execute_process_job, sync_runtime_state,
    ProcessRuntimeDeps,
};

pub(super) async fn run_render_job_from_artifacts(
    deps: ProcessRuntimeDeps,
    job: JobRuntimeState,
) -> Result<JobRuntimeState> {
    let (mut job, render_inputs) = prepare_render_job_from_artifacts(&deps, job)?;
    let job_paths = crate::storage_paths::build_job_paths(&deps.persist.output_root, &job.job_id)?;

    job.command = build_render_only_command(
        &deps.worker_command_runtime(),
        &job.request_payload,
        &job_paths,
        &render_inputs.source_pdf_path,
        &render_inputs.translations_dir,
    );
    job.status = JobStatusKind::Running;
    job.started_at = Some(now_iso());
    job.updated_at = now_iso();
    job.stage = Some(job_stage_str(JobStage::Rendering).to_string());
    job.stage_detail = Some(job_stage_detail(JobStage::Rendering).to_string());
    clear_job_failure(&mut job);
    sync_runtime_state(&mut job);
    execute_process_job(deps, job, &[]).await
}
