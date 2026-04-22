use anyhow::Result;
use tracing::error;

use crate::job_events::{persist_job_with_resources, persist_runtime_job_with_resources};
use crate::models::{now_iso, JobStatusKind};

use super::{
    append_error_chain_log,
    cancel_registry::{clear_cancel_request_with_registry, is_cancel_requested_with_registry},
    execution_queue::wait_for_execution_slot,
    format_error_chain,
    ocr_flow::execute_ocr_job,
    render_flow::run_render_job_from_artifacts,
    translation_flow::run_translate_only_job_with_ocr,
    translation_flow::run_translation_job_with_ocr,
    ProcessRuntimeDeps,
};

pub(crate) fn spawn_job(deps: ProcessRuntimeDeps, job_id: String) {
    tokio::spawn(async move {
        if let Err(err) = run_job(deps.clone(), job_id.clone()).await {
            error!("job {} failed to run: {}", job_id, err);
            if let Ok(mut job) = deps.db.get_job(&job_id) {
                if matches!(job.status, JobStatusKind::Canceled) {
                    clear_cancel_request_with_registry(deps.canceled_jobs.as_ref(), &job_id).await;
                    return;
                }
                let detail = format_error_chain(&err);
                append_error_chain_log(&mut job, &err);
                job.status = JobStatusKind::Failed;
                job.stage = Some("failed".to_string());
                job.stage_detail = Some(detail.clone());
                job.error = Some(detail);
                job.updated_at = now_iso();
                job.finished_at = Some(now_iso());
                job.sync_runtime_state();
                job.replace_failure_info(crate::job_failure::classify_job_failure(&job));
                let _ = persist_job_with_resources(
                    deps.db.as_ref(),
                    &deps.config.data_root,
                    &deps.config.output_root,
                    &job,
                );
            }
            clear_cancel_request_with_registry(deps.canceled_jobs.as_ref(), &job_id).await;
        }
    });
}

async fn run_job(deps: ProcessRuntimeDeps, job_id: String) -> Result<()> {
    let mut job = deps.db.get_job(&job_id)?;
    if is_cancel_requested_with_registry(deps.canceled_jobs.as_ref(), &job_id).await
        || matches!(job.status, JobStatusKind::Canceled)
    {
        clear_cancel_request_with_registry(deps.canceled_jobs.as_ref(), &job_id).await;
        return Ok(());
    }
    job.status = JobStatusKind::Queued;
    job.stage = Some("queued".to_string());
    job.stage_detail = Some("任务排队中，等待可用执行槽位".to_string());
    job.updated_at = now_iso();
    job.sync_runtime_state();
    job.replace_failure_info(None);
    persist_job_with_resources(
        deps.db.as_ref(),
        &deps.config.data_root,
        &deps.config.output_root,
        &job,
    )?;

    let _permit = match wait_for_execution_slot(
        deps.db.as_ref(),
        deps.canceled_jobs.as_ref(),
        &deps.job_slots,
        &job_id,
    )
    .await?
    {
        Some(permit) => permit,
        None => return Ok(()),
    };

    let job = deps.db.get_job(&job_id)?;
    if is_cancel_requested_with_registry(deps.canceled_jobs.as_ref(), &job_id).await
        || matches!(job.status, JobStatusKind::Canceled)
    {
        clear_cancel_request_with_registry(deps.canceled_jobs.as_ref(), &job_id).await;
        return Ok(());
    }
    let finished_job = match job.workflow {
        crate::models::WorkflowKind::Ocr => {
            execute_ocr_job(deps.clone(), job.into_runtime(), None, None).await?
        }
        crate::models::WorkflowKind::Book => {
            run_translation_job_with_ocr(deps.clone(), job.into_runtime()).await?
        }
        crate::models::WorkflowKind::Translate => {
            run_translate_only_job_with_ocr(deps.clone(), job.into_runtime()).await?
        }
        crate::models::WorkflowKind::Render => {
            run_render_job_from_artifacts(deps.clone(), job.into_runtime()).await?
        }
    };
    persist_runtime_job_with_resources(
        deps.db.as_ref(),
        &deps.config.data_root,
        &deps.config.output_root,
        &finished_job,
    )?;
    clear_cancel_request_with_registry(deps.canceled_jobs.as_ref(), &job_id).await;
    Ok(())
}
