#[cfg(unix)]
use std::io;
use std::path::Path;
use std::process::Stdio;
use std::time::Instant;

#[cfg(windows)]
use anyhow::anyhow;
use anyhow::{Context, Result};
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::Command;
use tokio::time::{sleep, timeout, Duration};
use tracing::info;

use crate::job_events::{persist_job, persist_runtime_job};
#[cfg(test)]
use crate::models::JobArtifacts;
use crate::models::{now_iso, JobRuntimeState, JobStatusKind, ProcessResult};
use crate::AppState;

use super::lifecycle::is_cancel_requested_any;
use super::runtime_state::apply_job_stdout_line;
use super::{
    attach_job_provider_failure, clear_canceled_runtime_artifacts, clear_job_failure,
    refresh_job_failure, sync_runtime_state,
};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum ProcessCompletionKind {
    Canceled,
    Succeeded,
    SucceededWithShutdownNoise,
    Failed,
}

pub(crate) async fn execute_process_job(
    state: AppState,
    mut job: JobRuntimeState,
    extra_cancel_job_ids: &[String],
) -> Result<JobRuntimeState> {
    job.status = JobStatusKind::Running;
    if job.started_at.is_none() {
        job.started_at = Some(now_iso());
    }
    if job.stage.is_none() || matches!(job.stage.as_deref(), Some("queued")) {
        job.stage = Some("running".to_string());
        job.stage_detail = Some("正在启动 Python worker".to_string());
    }
    job.updated_at = now_iso();
    sync_runtime_state(&mut job);

    let mut command = Command::new(&job.command[0]);
    command
        .args(&job.command[1..])
        .env("RUST_API_DATA_ROOT", &state.config.data_root)
        .env("RUST_API_OUTPUT_ROOT", &state.config.output_root)
        .env("OUTPUT_ROOT", &state.config.output_root)
        .env("PYTHONUNBUFFERED", "1")
        .current_dir(&state.config.project_root)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    configure_child_process(&mut command);

    let program = job.command.first().cloned().unwrap_or_default();
    let mut child = command
        .spawn()
        .with_context(|| format!("failed to spawn python worker: {program}"))?;
    job.pid = child.id();
    persist_runtime_job(&state, &job)?;
    info!("started job {} pid={:?}", job.job_id, job.pid);

    if is_cancel_requested_any(&state, &job.job_id, extra_cancel_job_ids).await {
        if let Some(pid) = job.pid {
            terminate_job_process_tree(pid).await?;
        }
    }

    let stdout = child.stdout.take().context("missing stdout pipe")?;
    let stderr = child.stderr.take().context("missing stderr pipe")?;
    let child_pid = job.pid;
    let timeout_secs = job.request_payload.runtime.timeout_seconds;
    let stdout_handle = tokio::spawn(read_stdout(
        state.clone(),
        job,
        stdout,
        extra_cancel_job_ids.to_vec(),
    ));
    let stderr_handle = tokio::spawn(read_stream(stderr));
    let started = Instant::now();

    let status = if timeout_secs > 0 {
        match timeout(Duration::from_secs(timeout_secs as u64), child.wait()).await {
            Ok(result) => result?,
            Err(_) => {
                if let Some(pid) = child_pid {
                    let _ = terminate_job_process_tree(pid).await;
                }
                let mut timed_out_job = state.db.get_job(&stdout_handle.await??.1.job_id)?;
                apply_timeout_failure(&mut timed_out_job, now_iso());
                persist_job(&state, &timed_out_job)?;
                return Ok(timed_out_job.into_runtime());
            }
        }
    } else {
        child.wait().await?
    };
    let stdout_job = stdout_handle.await??;
    let stderr_text = stderr_handle.await??;
    let stdout_text = stdout_job.0;
    let mut latest_job = stdout_job.1;
    latest_job.updated_at = now_iso();
    latest_job.finished_at = Some(now_iso());
    latest_job.pid = None;
    latest_job.result = Some(ProcessResult {
        success: status.success(),
        return_code: status.code().unwrap_or(-1),
        duration_seconds: started.elapsed().as_secs_f64(),
        command: latest_job.command.clone(),
        cwd: state.config.project_root.to_string_lossy().to_string(),
        stdout: stdout_text,
        stderr: stderr_text.clone(),
    });

    let completion = classify_process_completion(
        is_cancel_requested_any(&state, &latest_job.job_id, extra_cancel_job_ids).await,
        status.success(),
        should_treat_shutdown_noise_as_success(&latest_job, &stderr_text),
    );
    apply_process_completion(&mut latest_job, completion, &stderr_text);
    Ok(latest_job)
}

fn timeout_detail_for_stage(stage: Option<&str>) -> &'static str {
    match stage {
        Some("normalizing") => "normalization timeout",
        _ => "provider timeout",
    }
}

fn apply_timeout_failure(job: &mut crate::models::JobSnapshot, timestamp: String) {
    let timeout_detail = timeout_detail_for_stage(job.stage.as_deref()).to_string();
    job.pid = None;
    job.updated_at = timestamp.clone();
    job.finished_at = Some(timestamp);
    job.status = JobStatusKind::Failed;
    job.stage = Some("failed".to_string());
    job.stage_detail = Some(timeout_detail.clone());
    job.error = Some(timeout_detail);
    job.sync_runtime_state();
    job.replace_failure_info(crate::job_failure::classify_job_failure(job));
}

fn classify_process_completion(
    canceled: bool,
    process_success: bool,
    shutdown_noise_success: bool,
) -> ProcessCompletionKind {
    if canceled {
        ProcessCompletionKind::Canceled
    } else if process_success {
        ProcessCompletionKind::Succeeded
    } else if shutdown_noise_success {
        ProcessCompletionKind::SucceededWithShutdownNoise
    } else {
        ProcessCompletionKind::Failed
    }
}

fn apply_process_completion(
    job: &mut JobRuntimeState,
    completion: ProcessCompletionKind,
    stderr_text: &str,
) {
    match completion {
        ProcessCompletionKind::Canceled => {
            job.status = JobStatusKind::Canceled;
            job.stage = Some("canceled".to_string());
            job.stage_detail = Some("任务已取消".to_string());
            clear_canceled_runtime_artifacts(job);
            clear_job_failure(job);
        }
        ProcessCompletionKind::Succeeded => {
            job.status = JobStatusKind::Succeeded;
            job.stage = Some("finished".to_string());
            job.stage_detail = Some("任务完成".to_string());
            clear_job_failure(job);
        }
        ProcessCompletionKind::SucceededWithShutdownNoise => {
            job.status = JobStatusKind::Succeeded;
            job.stage = Some("finished".to_string());
            job.stage_detail = Some("任务完成（已忽略 Python 退出阶段的收尾噪音）".to_string());
            job.error = None;
            clear_job_failure(job);
            job.append_log(
                "INFO: ignored Python shutdown noise after artifacts were already written successfully",
            );
        }
        ProcessCompletionKind::Failed => {
            attach_job_provider_failure(job, stderr_text);
            job.status = JobStatusKind::Failed;
            job.stage = Some("failed".to_string());
            if job
                .stage_detail
                .as_deref()
                .map(str::trim)
                .filter(|value| !value.is_empty())
                .is_none()
            {
                job.stage_detail = Some("Python worker 执行失败".to_string());
            }
            job.error = Some(stderr_text.to_string());
            refresh_job_failure(job);
        }
    }
    sync_runtime_state(job);
}

fn should_treat_shutdown_noise_as_success(job: &JobRuntimeState, stderr_text: &str) -> bool {
    let stderr = stderr_text.trim();
    if stderr.is_empty() {
        return false;
    }
    let is_shutdown_noise = is_shutdown_noise(stderr);
    if !is_shutdown_noise {
        return false;
    }
    let Some(artifacts) = job.artifacts.as_ref() else {
        return false;
    };
    let output_pdf_ready = artifacts
        .output_pdf
        .as_deref()
        .map(Path::new)
        .is_some_and(Path::exists);
    let summary_ready = artifacts
        .summary
        .as_deref()
        .map(Path::new)
        .is_some_and(Path::exists);
    output_pdf_ready && summary_ready
}

async fn read_stream<R>(reader: R) -> Result<String>
where
    R: tokio::io::AsyncRead + Unpin,
{
    let mut lines = BufReader::new(reader).lines();
    let mut out = String::new();
    while let Some(line) = lines.next_line().await? {
        out.push_str(&line);
        out.push('\n');
    }
    Ok(out)
}

async fn read_stdout(
    state: AppState,
    mut job: JobRuntimeState,
    stdout: tokio::process::ChildStdout,
    extra_cancel_job_ids: Vec<String>,
) -> Result<(String, JobRuntimeState)> {
    let mut out = String::new();
    let mut lines = BufReader::new(stdout).lines();
    while let Some(line) = lines.next_line().await? {
        if is_cancel_requested_any(&state, &job.job_id, &extra_cancel_job_ids).await
            && !should_continue_after_cancel(&job)
        {
            break;
        }
        out.push_str(&line);
        out.push('\n');
        apply_job_stdout_line(&mut job, &line);
        if is_cancel_requested_any(&state, &job.job_id, &extra_cancel_job_ids).await
            && !should_continue_after_cancel(&job)
        {
            break;
        }
        job.updated_at = now_iso();
        persist_runtime_job(&state, &job)?;
    }
    Ok((out, job))
}

fn should_continue_after_cancel(job: &JobRuntimeState) -> bool {
    matches!(job.stage.as_deref(), Some("normalizing"))
}

fn is_shutdown_noise(stderr: &str) -> bool {
    stderr.contains("Exception ignored in")
        || stderr.contains("sys.unraisablehook")
        || stderr.contains("Exception ignored in sys.unraisablehook")
}

#[cfg(unix)]
fn configure_child_process(command: &mut Command) {
    unsafe {
        command.pre_exec(|| {
            if libc::setpgid(0, 0) != 0 {
                return Err(io::Error::last_os_error());
            }
            Ok(())
        });
    }
}

#[cfg(windows)]
fn configure_child_process(_command: &mut Command) {}

pub async fn terminate_job_process_tree(pid: u32) -> Result<()> {
    #[cfg(windows)]
    {
        let status = Command::new("taskkill")
            .args(["/PID", &pid.to_string(), "/T", "/F"])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .await
            .context("failed to invoke taskkill")?;
        if status.success() {
            return Ok(());
        }
        return Err(anyhow!("taskkill failed for pid {pid}"));
    }

    #[cfg(unix)]
    {
        let pgid = pid as i32;
        signal_process_group(pgid, libc::SIGTERM)?;
        for _ in 0..15 {
            if !process_group_exists(pgid) {
                return Ok(());
            }
            sleep(Duration::from_millis(200)).await;
        }
        signal_process_group(pgid, libc::SIGKILL)?;
        for _ in 0..10 {
            if !process_group_exists(pgid) {
                return Ok(());
            }
            sleep(Duration::from_millis(100)).await;
        }
        Ok(())
    }
}

#[cfg(unix)]
fn signal_process_group(pgid: i32, signal: i32) -> Result<()> {
    let rc = unsafe { libc::kill(-pgid, signal) };
    if rc == 0 {
        return Ok(());
    }
    let err = io::Error::last_os_error();
    if matches!(err.raw_os_error(), Some(libc::ESRCH)) {
        return Ok(());
    }
    Err(err.into())
}

#[cfg(unix)]
fn process_group_exists(pgid: i32) -> bool {
    let rc = unsafe { libc::kill(-pgid, 0) };
    if rc == 0 {
        return true;
    }
    !matches!(io::Error::last_os_error().raw_os_error(), Some(libc::ESRCH))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::models::CreateJobInput;

    fn build_job() -> JobRuntimeState {
        crate::models::JobSnapshot::new(
            "job-test".to_string(),
            CreateJobInput::default(),
            vec!["python".to_string()],
        )
        .into_runtime()
    }

    #[test]
    fn should_continue_after_cancel_only_for_normalizing_stage() {
        let mut job = build_job();
        job.stage = Some("normalizing".to_string());
        assert!(should_continue_after_cancel(&job));

        job.stage = Some("translating".to_string());
        assert!(!should_continue_after_cancel(&job));
    }

    #[test]
    fn shutdown_noise_requires_known_patterns() {
        assert!(is_shutdown_noise("Exception ignored in sys.unraisablehook"));
        assert!(is_shutdown_noise("Exception ignored in"));
        assert!(!is_shutdown_noise("normal stderr"));
    }

    #[test]
    fn shutdown_noise_success_requires_written_artifacts() {
        let mut job = build_job();
        job.artifacts = Some(JobArtifacts {
            output_pdf: Some("/definitely/missing.pdf".to_string()),
            summary: Some("/definitely/missing.json".to_string()),
            ..JobArtifacts::default()
        });
        assert!(!should_treat_shutdown_noise_as_success(
            &job,
            "Exception ignored in sys.unraisablehook"
        ));
    }

    #[test]
    fn timeout_detail_distinguishes_normalizing_stage() {
        assert_eq!(
            timeout_detail_for_stage(Some("normalizing")),
            "normalization timeout"
        );
        assert_eq!(
            timeout_detail_for_stage(Some("translating")),
            "provider timeout"
        );
        assert_eq!(timeout_detail_for_stage(None), "provider timeout");
    }

    #[test]
    fn classify_process_completion_prefers_cancel_then_success_then_noise() {
        assert_eq!(
            classify_process_completion(true, true, true),
            ProcessCompletionKind::Canceled
        );
        assert_eq!(
            classify_process_completion(false, true, true),
            ProcessCompletionKind::Succeeded
        );
        assert_eq!(
            classify_process_completion(false, false, true),
            ProcessCompletionKind::SucceededWithShutdownNoise
        );
        assert_eq!(
            classify_process_completion(false, false, false),
            ProcessCompletionKind::Failed
        );
    }

    #[test]
    fn apply_timeout_failure_marks_job_failed() {
        let mut job = crate::models::JobSnapshot::new(
            "job-test".to_string(),
            CreateJobInput::default(),
            vec!["python".to_string()],
        );
        job.stage = Some("normalizing".to_string());
        apply_timeout_failure(&mut job, "2026-04-04T00:00:00Z".to_string());
        assert_eq!(job.status, JobStatusKind::Failed);
        assert_eq!(job.stage.as_deref(), Some("failed"));
        assert_eq!(job.stage_detail.as_deref(), Some("normalization timeout"));
        assert_eq!(job.error.as_deref(), Some("normalization timeout"));
    }

    #[test]
    fn apply_process_completion_marks_cancel_and_clears_runtime_artifacts() {
        let mut job = build_job();
        job.artifacts = Some(JobArtifacts {
            normalized_document_json: Some("/tmp/doc.json".to_string()),
            normalization_report_json: Some("/tmp/doc.report.json".to_string()),
            schema_version: Some("document.v1".to_string()),
            ..JobArtifacts::default()
        });
        apply_process_completion(&mut job, ProcessCompletionKind::Canceled, "");
        assert_eq!(job.status, JobStatusKind::Canceled);
        assert_eq!(job.stage.as_deref(), Some("canceled"));
        let artifacts = job.artifacts.as_ref().unwrap();
        assert!(artifacts.normalized_document_json.is_none());
        assert!(artifacts.normalization_report_json.is_none());
        assert!(artifacts.schema_version.is_none());
    }
}
