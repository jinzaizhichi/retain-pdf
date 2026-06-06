use anyhow::{anyhow, Result};

use crate::models::JobRuntimeState;
use crate::ocr_provider::mineru::MineruClient;
use crate::ocr_provider::paddle::PaddleClient;
use crate::ocr_provider::OcrProviderKind;

use super::transport::{prepare_local_upload_source, recover_remote_source_pdf};
use super::workspace::OcrWorkspace;
use super::{mineru, paddle};
use crate::job_runner::cancel_registry::is_cancel_requested_with_registry;
use crate::job_runner::ProcessRuntimeDeps;

pub(super) async fn execute_provider_transport(
    deps: &ProcessRuntimeDeps,
    job: &mut JobRuntimeState,
    provider_kind: &OcrProviderKind,
    workspace: &OcrWorkspace,
    parent_job_id: Option<&str>,
) -> Result<std::path::PathBuf> {
    if let Some(upload_path) =
        prepare_local_upload_source(deps.db.as_ref(), job, &workspace.source_dir)?
    {
        execute_local_provider_transport(
            deps,
            job,
            provider_kind,
            workspace,
            &upload_path,
            parent_job_id,
        )
        .await?;
        return Ok(upload_path);
    }

    execute_remote_provider_transport(deps, job, provider_kind, workspace, parent_job_id).await?;

    if is_cancel_requested_with_registry(deps.canceled_jobs.as_ref(), &job.job_id).await {
        return Ok(std::path::PathBuf::new());
    }

    recover_remote_source_pdf(
        provider_kind,
        job,
        &workspace.source_dir,
        &workspace.provider_raw_dir,
    )
    .await
}

async fn execute_local_provider_transport(
    deps: &ProcessRuntimeDeps,
    job: &mut JobRuntimeState,
    provider_kind: &OcrProviderKind,
    workspace: &OcrWorkspace,
    upload_path: &std::path::Path,
    parent_job_id: Option<&str>,
) -> Result<()> {
    match provider_kind {
        OcrProviderKind::Mineru => {
            let client = MineruClient::with_runtime(
                "",
                job.request_payload.ocr.mineru_token.clone(),
                deps.mineru_runtime().clone(),
            );
            mineru::run_local_ocr_transport_mineru(
                deps,
                job,
                &client,
                upload_path,
                &workspace.provider_result_json_path,
                parent_job_id,
            )
            .await
        }
        OcrProviderKind::Paddle => {
            let client = PaddleClient::with_runtime(
                job.request_payload.ocr.paddle_api_url.clone(),
                job.request_payload.ocr.paddle_token.clone(),
                deps.paddle_runtime().clone(),
            );
            paddle::run_local_ocr_transport_paddle(
                deps,
                job,
                &client,
                upload_path,
                &workspace.provider_result_json_path,
                &workspace.job_paths.root,
                parent_job_id,
            )
            .await
        }
        OcrProviderKind::Local => Err(anyhow!(
            "local OCR provider is only supported by provider stage script"
        )),
        OcrProviderKind::Unknown => Err(anyhow!("unsupported OCR provider")),
    }
}

async fn execute_remote_provider_transport(
    deps: &ProcessRuntimeDeps,
    job: &mut JobRuntimeState,
    provider_kind: &OcrProviderKind,
    workspace: &OcrWorkspace,
    parent_job_id: Option<&str>,
) -> Result<()> {
    match provider_kind {
        OcrProviderKind::Mineru => {
            let client = MineruClient::with_runtime(
                "",
                job.request_payload.ocr.mineru_token.clone(),
                deps.mineru_runtime().clone(),
            );
            mineru::run_remote_ocr_transport_mineru(
                deps,
                job,
                &client,
                &workspace.provider_result_json_path,
                parent_job_id,
            )
            .await
        }
        OcrProviderKind::Paddle => {
            let client = PaddleClient::with_runtime(
                job.request_payload.ocr.paddle_api_url.clone(),
                job.request_payload.ocr.paddle_token.clone(),
                deps.paddle_runtime().clone(),
            );
            paddle::run_remote_ocr_transport_paddle(
                deps,
                job,
                &client,
                &workspace.provider_result_json_path,
                &workspace.job_paths.root,
                parent_job_id,
            )
            .await
        }
        OcrProviderKind::Local => Err(anyhow!(
            "local OCR provider is only supported by provider stage script"
        )),
        OcrProviderKind::Unknown => Err(anyhow!("unsupported OCR provider")),
    }
}
