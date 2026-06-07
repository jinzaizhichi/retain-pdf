import {
  arrayOrEmpty,
  firstNonEmpty,
  isTerminalStatus,
  numberOrNull,
  objectOrNull,
  unwrapEnvelope,
} from "./job-core.js";

export function normalizeJobPayload(payload) {
  const unwrapped = unwrapEnvelope(payload) || {};
  const timestamps = unwrapped.timestamps || {};
  const progress = unwrapped.progress || {};
  const artifacts = unwrapped.artifacts || {};
  const runtime = unwrapped.runtime || {};
  const failure = unwrapped.failure || null;
  const invocation = unwrapped.invocation || {};
  const status = unwrapped.status || "idle";
  let progressCurrent = numberOrNull(progress.current ?? unwrapped.progress_current);
  let progressTotal = numberOrNull(progress.total ?? unwrapped.progress_total);
  let progressPercent = numberOrNull(progress.percent);

  if (isTerminalStatus(status)) {
    if (progressTotal !== null) {
      progressCurrent = progressTotal;
    }
    if (progressCurrent !== null && progressTotal === null) {
      progressTotal = progressCurrent;
    }
    if (status === "succeeded") {
      progressPercent = 100;
    }
  }

  return {
    raw_response: unwrapped,
    request_payload: unwrapped.request_payload || null,
    request_payload_page_ranges: firstNonEmpty(unwrapped.request_payload?.ocr?.page_ranges),
    request_payload_math_mode: firstNonEmpty(unwrapped.request_payload?.translation?.math_mode),
    job_id: unwrapped.job_id || "",
    workflow: unwrapped.workflow || unwrapped.job_type || "",
    job_type: unwrapped.job_type || unwrapped.workflow || "",
    status,
    display_stage: unwrapped.display_stage || "",
    stage: unwrapped.stage || "",
    stage_detail: unwrapped.stage_detail || "",
    progress_current: progressCurrent,
    progress_total: progressTotal,
    progress_percent: progressPercent,
    progress_unit: progress.unit || unwrapped.progress_unit || "",
    created_at: timestamps.created_at || unwrapped.created_at || "",
    updated_at: timestamps.updated_at || unwrapped.updated_at || "",
    started_at: timestamps.started_at || unwrapped.started_at || "",
    finished_at: timestamps.finished_at || unwrapped.finished_at || "",
    duration_seconds: numberOrNull(timestamps.duration_seconds ?? unwrapped.duration_seconds),
    links: unwrapped.links || {},
    actions: unwrapped.actions || {},
    artifacts,
    artifacts_display: arrayOrEmpty(unwrapped.artifacts_display),
    output_pdf_ready: Boolean(unwrapped.output_pdf_ready),
    source_pdf_ready: Boolean(unwrapped.source_pdf_ready),
    pdf_url: firstNonEmpty(unwrapped.pdf_url),
    pdf_path: firstNonEmpty(unwrapped.pdf_path),
    bundle_url: firstNonEmpty(unwrapped.bundle_url),
    bundle_path: firstNonEmpty(unwrapped.bundle_path),
    markdown_url: firstNonEmpty(unwrapped.markdown_url),
    markdown_path: firstNonEmpty(unwrapped.markdown_path),
    source_pdf_url: firstNonEmpty(unwrapped.source_pdf_url),
    source_pdf_path: firstNonEmpty(unwrapped.source_pdf_path),
    ocr_job: objectOrNull(unwrapped.ocr_job),
    runtime,
    invocation,
    failure,
    normalization_summary: objectOrNull(unwrapped.normalization_summary),
    glossary_summary: objectOrNull(unwrapped.glossary_summary),
    current_stage: firstNonEmpty(runtime.current_stage, unwrapped.stage),
    stage_started_at: firstNonEmpty(runtime.stage_started_at),
    last_stage_transition_at: firstNonEmpty(runtime.last_stage_transition_at),
    active_stage_elapsed_ms: numberOrNull(runtime.active_stage_elapsed_ms),
    total_elapsed_ms: numberOrNull(runtime.total_elapsed_ms),
    retry_count: numberOrNull(runtime.retry_count) ?? 0,
    last_retry_at: firstNonEmpty(runtime.last_retry_at),
    stage_history: arrayOrEmpty(runtime.stage_history),
    terminal_reason: firstNonEmpty(runtime.terminal_reason),
    final_failure_category: firstNonEmpty(runtime.final_failure_category),
    final_failure_summary: firstNonEmpty(runtime.final_failure_summary),
    failure_diagnostic: unwrapped.failure_diagnostic || null,
    log_tail: Array.isArray(unwrapped.log_tail) ? unwrapped.log_tail : [],
    error: unwrapped.error || "",
    pdf_ready: Boolean(unwrapped.output_pdf_ready ?? artifacts.pdf_ready ?? artifacts.pdf?.ready),
    markdown_ready: Boolean(unwrapped.markdown_ready ?? artifacts.markdown_ready ?? artifacts.markdown?.ready),
    bundle_ready: Boolean(unwrapped.bundle_ready ?? artifacts.bundle_ready ?? artifacts.bundle?.ready),
  };
}
