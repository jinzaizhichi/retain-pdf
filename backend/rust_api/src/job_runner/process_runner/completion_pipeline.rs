use anyhow::Result;

use crate::config::WorkerProcessRuntimeConfig;
use crate::job_runner::cancel_registry::is_cancel_requested_any;
use crate::job_runner::process_contract::validate_successful_worker_outputs;
use crate::job_runner::ProcessRuntimeDeps;
use crate::models::JobRuntimeState;

use super::completion::{
    apply_process_completion, classify_process_completion, should_treat_shutdown_noise_as_success,
    ProcessCompletionKind,
};
use super::execution::CompletedProcess;
use super::failure_ai_diagnosis::maybe_attach_ai_failure_diagnosis;
use super::result_support::attach_process_result;

pub(super) async fn finalize_completed_process(
    deps: &ProcessRuntimeDeps,
    worker_runtime: &WorkerProcessRuntimeConfig<'_>,
    completed: CompletedProcess,
    extra_cancel_job_ids: &[String],
) -> Result<JobRuntimeState> {
    let mut latest_job = completed.latest_job;
    attach_process_result(
        &mut latest_job,
        &completed.status,
        completed.started,
        completed.stdout_text,
        &completed.stderr_text,
        worker_runtime.project_root,
    );

    let mut completion = classify_process_completion(
        is_cancel_requested_any(
            &deps.canceled_jobs,
            &latest_job.job_id,
            extra_cancel_job_ids,
        )
        .await,
        completed.status.success(),
        should_treat_shutdown_noise_as_success(&latest_job, &completed.stderr_text),
    );
    if matches!(
        completion,
        ProcessCompletionKind::Succeeded | ProcessCompletionKind::SucceededWithShutdownNoise
    ) {
        ensure_successful_worker_contract(
            &mut latest_job,
            &deps.persist.data_root,
            &mut completion,
        );
    }
    apply_process_completion(&mut latest_job, completion, &completed.stderr_text);
    maybe_attach_ai_failure_diagnosis(
        deps.db.as_ref(),
        &deps.failure_ai_diagnosis_runtime(),
        &mut latest_job,
    )
    .await;
    Ok(latest_job)
}

fn ensure_successful_worker_contract(
    latest_job: &mut JobRuntimeState,
    data_root: &std::path::Path,
    completion: &mut ProcessCompletionKind,
) {
    if let Err(err) = validate_successful_worker_outputs(latest_job, data_root) {
        latest_job.append_log(&format!("ERROR: worker output contract failed: {err}"));
        latest_job.stage_detail = Some(format!("Python worker 成功退出，但必需产物缺失：{err}"));
        *completion = ProcessCompletionKind::Failed;
    }
}
