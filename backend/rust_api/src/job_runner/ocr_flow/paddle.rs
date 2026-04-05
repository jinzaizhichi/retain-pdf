use anyhow::{anyhow, Result};
use serde_json::json;
use std::path::Path;

use crate::models::{now_iso, JobRuntimeState};
use crate::ocr_provider::paddle::{map_task_status as map_paddle_task_status, PaddleClient};
use crate::ocr_provider::OcrTaskHandle;
use crate::AppState;

use super::artifacts::persist_provider_result;
use super::polling::{should_stop_polling, wait_next_poll_or_timeout};
use super::status::{record_provider_trace, update_ocr_job_from_status};
use crate::job_runner::ocr_provider_diagnostics_mut;

use super::save_ocr_job;

pub(super) async fn run_local_ocr_transport_paddle(
    state: &AppState,
    job: &mut JobRuntimeState,
    client: &PaddleClient,
    upload_path: &Path,
    provider_result_json_path: &Path,
    parent_job_id: Option<&str>,
) -> Result<()> {
    let created = client
        .submit_local_file(
            upload_path,
            &job.request_payload.ocr.paddle_model,
            &build_paddle_optional_payload(&job.request_payload.ocr.paddle_model),
        )
        .await?;
    run_paddle_poll_loop(
        state,
        job,
        client,
        created.data,
        created.trace_id,
        provider_result_json_path,
        parent_job_id,
    )
    .await
}

pub(super) async fn run_remote_ocr_transport_paddle(
    state: &AppState,
    job: &mut JobRuntimeState,
    client: &PaddleClient,
    provider_result_json_path: &Path,
    parent_job_id: Option<&str>,
) -> Result<()> {
    let created = client
        .submit_remote_url(
            &job.request_payload.source.source_url,
            &job.request_payload.ocr.paddle_model,
            &build_paddle_optional_payload(&job.request_payload.ocr.paddle_model),
        )
        .await?;
    run_paddle_poll_loop(
        state,
        job,
        client,
        created.data,
        created.trace_id,
        provider_result_json_path,
        parent_job_id,
    )
    .await
}

async fn run_paddle_poll_loop(
    state: &AppState,
    job: &mut JobRuntimeState,
    client: &PaddleClient,
    job_id: String,
    trace_id: Option<String>,
    provider_result_json_path: &Path,
    parent_job_id: Option<&str>,
) -> Result<()> {
    record_provider_trace(job, trace_id);
    ocr_provider_diagnostics_mut(job).handle.task_id = Some(job_id.clone());
    job.append_log(&format!("task_id: {}", job_id));
    job.stage = Some("ocr_processing".to_string());
    job.stage_detail = Some("Paddle 任务已提交，等待解析".to_string());
    job.updated_at = now_iso();
    save_ocr_job(state, job, parent_job_id).await?;

    let poll_interval = std::cmp::max(job.request_payload.ocr.poll_interval, 1) as u64;
    let timeout_secs = std::cmp::max(job.request_payload.ocr.poll_timeout, 1) as u64;

    let started = std::time::Instant::now();
    loop {
        if should_stop_polling(state, &job.job_id).await {
            return Ok(());
        }
        let task = client.query_job(&job_id).await?;
        record_provider_trace(job, task.trace_id.clone());
        let item = task.data;
        job.append_log(&format!("paddle task {}: state={}", job_id, item.state));
        update_ocr_job_from_status(
            state,
            job,
            map_paddle_task_status(
                &item.state,
                OcrTaskHandle {
                    batch_id: None,
                    task_id: Some(job_id.clone()),
                    file_name: None,
                },
                Some(item.error_msg.clone()),
                task.trace_id.clone(),
            ),
            item.extract_progress
                .as_ref()
                .and_then(|progress| progress.extracted_pages),
            item.extract_progress
                .as_ref()
                .and_then(|progress| progress.total_pages),
            parent_job_id,
        )
        .await?;

        if item.state == "done" {
            let jsonl_url = item
                .result_url
                .as_ref()
                .map(|v| v.json_url.trim().to_string())
                .filter(|v| !v.is_empty())
                .ok_or_else(|| anyhow!("Paddle task finished but resultUrl.jsonUrl is missing"))?;
            let result = client.download_jsonl_result(&jsonl_url).await?;
            ocr_provider_diagnostics_mut(job).artifacts.full_zip_url = Some(jsonl_url.clone());
            let mut payload = result.payload;
            if let Some(meta) = payload.get_mut("_meta").and_then(|v| v.as_object_mut()) {
                meta.insert("provider".to_string(), json!("paddle"));
                meta.insert("taskId".to_string(), json!(job_id));
                meta.insert("jsonlUrl".to_string(), json!(jsonl_url));
                meta.insert(
                    "traceId".to_string(),
                    json!(task.trace_id.clone().unwrap_or_default()),
                );
            }
            persist_provider_result(job, provider_result_json_path, &payload).await?;
            return Ok(());
        }
        if item.state == "failed" {
            return Err(anyhow!(
                "Paddle task failed: {}",
                item.error_msg.trim().to_string()
            ));
        }
        wait_next_poll_or_timeout(started, timeout_secs, poll_interval, || {
            format!("Timed out waiting for Paddle task {}", job_id)
        })
        .await?;
    }
}

fn build_paddle_optional_payload(model: &str) -> serde_json::Value {
    let normalized = model.trim().to_ascii_lowercase();
    if normalized.contains("pp-structurev3") {
        return json!({
            "markdownIgnoreLabels": [
                "header",
                "header_image",
                "footer",
                "footer_image",
                "number",
                "footnote",
                "aside_text"
            ],
            "useChartRecognition": false,
            "useRegionDetection": true,
            "useDocOrientationClassify": false,
            "useDocUnwarping": false,
            "useTextlineOrientation": false,
            "useSealRecognition": true,
            "useFormulaRecognition": true,
            "useTableRecognition": true,
            "layoutThreshold": 0.5,
            "layoutNms": true,
            "layoutUnclipRatio": 1,
            "textDetLimitType": "min",
            "textDetLimitSideLen": 64,
            "textDetThresh": 0.3,
            "textDetBoxThresh": 0.6,
            "textDetUnclipRatio": 1.5,
            "textRecScoreThresh": 0,
            "sealDetLimitType": "min",
            "sealDetLimitSideLen": 736,
            "sealDetThresh": 0.2,
            "sealDetBoxThresh": 0.6,
            "sealDetUnclipRatio": 0.5,
            "sealRecScoreThresh": 0,
            "useTableOrientationClassify": true,
            "useOcrResultsWithTableCells": true,
            "useE2eWiredTableRecModel": false,
            "useE2eWirelessTableRecModel": false,
            "useWiredTableCellsTransToHtml": false,
            "useWirelessTableCellsTransToHtml": false,
            "parseLanguage": "default",
            "visualize": false
        });
    }

    json!({
        "mergeLayoutBlocks": false,
        "markdownIgnoreLabels": [
            "header",
            "header_image",
            "footer",
            "footer_image",
            "number",
            "footnote",
            "aside_text"
        ],
        "useDocOrientationClassify": false,
        "useDocUnwarping": false,
        "useLayoutDetection": true,
        "useChartRecognition": false,
        "useSealRecognition": true,
        "useOcrForImageBlock": false,
        "mergeTables": true,
        "relevelTitles": true,
        "layoutShapeMode": "auto",
        "promptLabel": "ocr",
        "repetitionPenalty": 1,
        "temperature": 0,
        "topP": 1,
        "minPixels": 147384,
        "maxPixels": 2822400,
        "layoutNms": true,
        "restructurePages": true,
        "visualize": false
    })
}
