use std::path::Path;
use std::time::Instant;

use anyhow::{anyhow, Result};

use crate::job_events::record_custom_runtime_event;
use crate::job_runner::{job_artifacts_mut, ocr_provider_diagnostics_mut, register_job_retry};
use crate::models::JobRuntimeState;
use crate::ocr_provider::mineru::MineruClient;
use crate::AppState;

use super::markdown_bundle::export_markdown_bundle;
use super::save_ocr_job;

const MINERU_POLL_RETRY_LIMIT: usize = 5;
const MINERU_POLL_RETRY_BASE_DELAY_SECS: u64 = 2;

pub(super) async fn download_and_unpack_after_success(
    state: &AppState,
    job: &mut JobRuntimeState,
    client: &MineruClient,
    full_zip_url: &str,
    parent_job_id: Option<&str>,
) -> Result<()> {
    let artifacts = job_artifacts_mut(job);
    let provider_zip = artifacts
        .provider_zip
        .clone()
        .ok_or_else(|| anyhow!("provider_zip path missing"))?;
    let provider_raw_dir = artifacts
        .provider_raw_dir
        .clone()
        .ok_or_else(|| anyhow!("provider_raw_dir path missing"))?;
    ocr_provider_diagnostics_mut(job).artifacts.full_zip_url = Some(full_zip_url.to_string());
    job.stage = Some("translation_prepare".to_string());
    job.stage_detail = Some("MinerU 结果已就绪，正在下载原始 bundle".to_string());
    job.updated_at = crate::models::now_iso();
    save_ocr_job(state, job, parent_job_id).await?;
    download_mineru_bundle_with_retry(
        state,
        job,
        client,
        full_zip_url,
        Path::new(&provider_zip),
        std::cmp::max(job.request_payload.ocr.poll_timeout, 1) as u64,
        parent_job_id,
    )
    .await?;
    client.unpack_zip(Path::new(&provider_zip), Path::new(&provider_raw_dir))?;
    export_markdown_bundle(
        &provider_raw_dir,
        job_artifacts_mut(job).job_root.as_deref(),
    )?;
    Ok(())
}

async fn download_mineru_bundle_with_retry(
    state: &AppState,
    job: &mut JobRuntimeState,
    client: &MineruClient,
    full_zip_url: &str,
    dest_path: &Path,
    timeout_secs: u64,
    parent_job_id: Option<&str>,
) -> Result<()> {
    let started = Instant::now();
    let mut attempt = 0usize;
    loop {
        match client.download_bundle(full_zip_url, dest_path).await {
            Ok(()) => return Ok(()),
            Err(err) => {
                attempt += 1;
                if !super::mineru_retry::should_retry_mineru_poll_error(&err)
                    || started.elapsed().as_secs() >= timeout_secs
                    || attempt >= MINERU_POLL_RETRY_LIMIT
                {
                    return Err(err);
                }
                let delay_secs =
                    std::cmp::min(MINERU_POLL_RETRY_BASE_DELAY_SECS * attempt as u64, 10);
                job.append_log(&format!(
                    "MinerU download bundle retry {attempt}/{MINERU_POLL_RETRY_LIMIT}: {full_zip_url} after error: {}",
                    err
                ));
                job.stage = Some("translation_prepare".to_string());
                job.stage_detail = Some(format!(
                    "MinerU bundle 下载异常，{delay_secs}s 后重试（第 {attempt}/{MINERU_POLL_RETRY_LIMIT} 次）"
                ));
                job.updated_at = crate::models::now_iso();
                register_job_retry(job);
                record_custom_runtime_event(
                    state,
                    job,
                    "warn",
                    "retry_scheduled",
                    "MinerU bundle 下载进入重试",
                    Some(serde_json::json!({
                        "scope": "mineru_bundle_download",
                        "attempt": attempt,
                        "max_attempts": MINERU_POLL_RETRY_LIMIT,
                        "delay_seconds": delay_secs,
                        "reason": err.to_string(),
                        "url": full_zip_url,
                    })),
                );
                save_ocr_job(state, job, parent_job_id).await?;
                tokio::time::sleep(tokio::time::Duration::from_secs(delay_secs)).await;
            }
        }
    }
}
