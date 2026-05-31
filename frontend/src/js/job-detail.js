import { isMockMode } from "./config.js";
import { API_PREFIX } from "./constants.js";
import { $ } from "./dom.js";
import {
  fetchJobDiagnostics,
  fetchJobArtifactsManifest,
  fetchJobEvents,
  fetchJobMarkdown,
  fetchJobMarkdownDocument,
  fetchJobPayload,
  fetchResumePlan,
  rerunJob,
  resumeJob,
} from "./api/jobs.js";
import { fetchProtected } from "./api/http.js";
import {
  hasReadyManifestArtifact,
} from "./job-artifacts.js";
import {
  formatEventTimestamp,
  formatJobFinishedAt,
  normalizeJobPayload,
  resolveJobActions,
  summarizeInvocationProtocol,
  summarizeInvocationSchemaVersion,
  summarizePublicError,
  summarizeRuntimeField,
  summarizeStageDetail,
  summarizeStatus,
} from "./job.js";
import {
  renderArtifactsManifest,
  renderMarkdownContract as renderMarkdownContractView,
  renderMarkdownImagePreview as renderMarkdownImagePreviewView,
  resolveMarkdownImagesBaseUrl,
  isMarkdownReady,
  revokeMarkdownImageUrls as revokeMarkdownImageUrlsView,
} from "./job-detail-artifacts.js";
import {
  bindDetailModalDismiss,
  closeAllDetailModals,
  setDetailActionLink,
  setDetailEventsStatus,
  setDetailText,
} from "./job-detail-view.js";
import {
  bindEventsLauncher,
  bindStageHistoryLauncher,
} from "./job-detail-events.js";
import { bindProtectedDownloadLink } from "./job-detail-downloads.js";
import {
  applyDiagnostics,
  renderFailureDebugContext,
} from "./job-detail-failure.js";
import {
  buildReaderPageUrl,
  firstNonEmptyText,
  getJobIdFromQuery,
} from "./job-detail-routing.js";
import {
  bindRerunButton,
  summarizeResumePlan,
} from "./job-detail-resume.js";
import { resolveLiveDurations } from "./status-detail-utils.js";

const detailPageState = {
  job: null,
  manifestPayload: null,
  markdownPayload: null,
  markdownImageUrls: [],
  eventsPayload: null,
  eventsLoadingPromise: null,
  rerunActionUrl: "",
  resumePlan: null,
};

function setText(id, value) {
  setDetailText(id, value);
}

function setActionLink(id, url, enabled) {
  setDetailActionLink(id, url, enabled);
}

function summarizeMathMode(job) {
  const mathMode = `${job?.request_payload_math_mode || ""}`.trim();
  if (mathMode === "placeholder") {
    return "placeholder - 公式占位保护";
  }
  if (mathMode === "direct_typst") {
    return "direct_typst - 模型直出公式";
  }
  return mathMode || "-";
}

function revokeMarkdownImageUrls() {
  revokeMarkdownImageUrlsView(detailPageState.markdownImageUrls);
}

function renderMarkdownContract(job, markdownPayload = null) {
  renderMarkdownContractView({
    job,
    markdownPayload,
    markdownImageUrls: detailPageState.markdownImageUrls,
    setText,
    setActionLink,
  });
}

async function renderMarkdownImagePreview(markdownPayload, imagesBaseUrl) {
  await renderMarkdownImagePreviewView({
    markdownPayload,
    imagesBaseUrl,
    markdownImageUrls: detailPageState.markdownImageUrls,
    fetchProtected,
  });
}

function bindModalDismiss(modalId, closeButtonId) {
  bindDetailModalDismiss(modalId, closeButtonId);
}

function bindDetailModals() {
  window.addEventListener("beforeunload", revokeMarkdownImageUrls, { once: true });
  bindModalDismiss("detail-stage-history-modal", "detail-close-stage-history-btn");
  bindModalDismiss("detail-events-modal", "detail-close-events-btn");
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") {
      return;
    }
    closeAllDetailModals();
  });
}

function setEventsStatus(text) {
  setDetailEventsStatus(text);
}

async function initializePage() {
  bindDetailModals();
  bindStageHistoryLauncher({ detailPageState });
  bindEventsLauncher({ detailPageState, fetchJobEvents });
  bindRerunButton({
    detailPageState,
    getJobId: getJobIdFromQuery,
    rerunJob,
    resumeJob,
    apiPrefix: API_PREFIX,
    setText,
  });
  bindProtectedDownloadLink({
    id: "detail-pdf-btn",
    fallbackNameFactory: (jobId) => `${jobId}.pdf`,
    detailPageState,
    fetchProtected,
    setText,
  });
  bindProtectedDownloadLink({
    id: "detail-markdown-raw-btn",
    fallbackNameFactory: (jobId) => `${jobId}.md`,
    detailPageState,
    fetchProtected,
    setText,
  });
  bindProtectedDownloadLink({
    id: "detail-markdown-json-btn",
    fallbackNameFactory: (jobId) => `${jobId}-markdown.json`,
    detailPageState,
    fetchProtected,
    setText,
  });
  const jobId = getJobIdFromQuery();
  if (!jobId) {
    setText("detail-head-note", "缺少 job_id，请通过 detail.html?job_id=... 打开。");
    return;
  }
  setText("detail-job-id", jobId);
  setText("detail-head-note", isMockMode()
    ? "当前为 mock 明细页，可直接分享当前链接。"
    : "当前详情页可直接通过 URL 分享给其他人。");

  const [payloadRaw, manifestPayload, diagnosticsPayload, resumePlan] = await Promise.all([
    fetchJobPayload(jobId, API_PREFIX),
    fetchJobArtifactsManifest(jobId, API_PREFIX),
    fetchJobDiagnostics(jobId, API_PREFIX).catch(() => null),
    fetchResumePlan(jobId, API_PREFIX).catch(() => null),
  ]);
  const job = normalizeJobPayload(payloadRaw);
  detailPageState.job = job;
  detailPageState.manifestPayload = manifestPayload;
  detailPageState.resumePlan = resumePlan;
  const durations = resolveLiveDurations(job);
  const actions = resolveJobActions(job);
  detailPageState.rerunActionUrl = actions.rerun;
  renderArtifactsManifest(manifestPayload);
  renderMarkdownContract(job, null);

  setText("detail-status-summary", summarizeStatus(job.status || "idle"));
  setText("detail-stage-detail", summarizeStageDetail(job));
  setText("detail-finished-at", formatJobFinishedAt(job));
  setText("detail-runtime-current-stage", summarizeRuntimeField(job.current_stage || job.stage_detail));
  setText("detail-runtime-stage-elapsed", durations.stageElapsedText);
  setText("detail-runtime-total-elapsed", durations.totalElapsedText);
  setText("detail-runtime-retry-count", `${job.retry_count ?? 0}`);
  setText("detail-runtime-last-transition", job.last_stage_transition_at ? formatEventTimestamp(job.last_stage_transition_at) : "-");
  setText("detail-runtime-terminal-reason", summarizeRuntimeField(job.terminal_reason));
  setText("detail-runtime-input-protocol", summarizeInvocationProtocol(job));
  setText("detail-runtime-stage-spec-version", summarizeInvocationSchemaVersion(job));
  setText("detail-runtime-math-mode", summarizeMathMode(job));

  const failure = job.failure || {};
  const failureDiagnostic = job.failure_diagnostic || {};
  const retryable = failure.retryable ?? failureDiagnostic.retryable;
  const failureLastLogLine = firstNonEmptyText(
    failure.last_log_line,
    failureDiagnostic.last_log_line,
    Array.isArray(job.log_tail) && job.log_tail.length ? job.log_tail[job.log_tail.length - 1] : "",
  );
  setText("detail-failure-summary", summarizeRuntimeField(failure.summary || job.final_failure_summary || failureDiagnostic.summary || failure.raw_excerpt));
  setText("detail-failure-category", summarizeRuntimeField(
    failure.category
    || failure.failure_category
    || job.final_failure_category
    || failureDiagnostic.type
    || failureDiagnostic.error_kind,
  ));
  setText("detail-failure-stage", summarizeRuntimeField(
    failure.stage
    || failure.failed_stage
    || failure.provider_stage
    || failureDiagnostic.stage
    || failureDiagnostic.failed_stage,
  ));
  setText("detail-failure-root-cause", summarizeRuntimeField(failure.root_cause || failureDiagnostic.root_cause || failure.upstream_host));
  setText("detail-failure-suggestion", summarizeRuntimeField(failure.suggestion || failureDiagnostic.suggestion || failure.failure_code));
  setText("detail-failure-last-log-line", summarizeRuntimeField(failureLastLogLine));
  setText("detail-failure-retryable", typeof retryable === "boolean" ? (retryable ? "是" : "否") : "-");
  applyDiagnostics(diagnosticsPayload, job, setText);
  renderFailureDebugContext(job);
  const rerunEnabled = Boolean(resumePlan?.can_resume || (actions.rerunEnabled && actions.rerun));
  if ($("detail-rerun-btn")) {
    $("detail-rerun-btn").disabled = !rerunEnabled;
  }
  setText(
    "detail-rerun-status",
    summarizeResumePlan(resumePlan),
  );
  setText("detail-error-box", summarizePublicError(job));
  setEventsStatus("尚未加载");

  const readerEnabled = Boolean(
    job?.job_id
    && hasReadyManifestArtifact(manifestPayload, "source_pdf")
    && (hasReadyManifestArtifact(manifestPayload, "pdf")
      || hasReadyManifestArtifact(manifestPayload, "translated_pdf")
      || hasReadyManifestArtifact(manifestPayload, "result_pdf")
      || actions.pdfEnabled),
  );
  setActionLink("detail-reader-btn", buildReaderPageUrl(job.job_id), readerEnabled);
  setActionLink("detail-pdf-btn", actions.pdf, actions.pdfEnabled && !!actions.pdf);

  try {
    const markdownPayload = await fetchJobMarkdownDocument(jobId, API_PREFIX)
      || await fetchJobMarkdown(jobId, API_PREFIX);
    detailPageState.markdownPayload = markdownPayload;
    renderMarkdownContract(job, markdownPayload);
    if (markdownPayload) {
      await renderMarkdownImagePreview(
        markdownPayload,
        resolveMarkdownImagesBaseUrl(job, markdownPayload),
      );
    } else if (isMarkdownReady(job)) {
      setText("detail-markdown-status", "Markdown 已标记 ready，但 /markdown 暂未返回内容");
    }
  } catch (error) {
    renderMarkdownContract(job, null);
    setText("detail-markdown-status", error.message || "读取 Markdown 失败");
  }
}

initializePage().catch((err) => {
  setText("detail-head-note", err.message || String(err));
});
