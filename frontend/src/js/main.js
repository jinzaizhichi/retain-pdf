import { $ } from "./dom.js";
import {
  apiBase,
  applyKeyInputs,
  defaultMineruToken,
  defaultModelApiKey,
  defaultModelBaseUrl,
  defaultModelName,
  desktopInvoke,
  isDesktopMode,
  loadBrowserStoredConfig,
  saveBrowserStoredConfig,
} from "./config.js";
import {
  API_PREFIX,
  DEFAULT_BATCH_SIZE,
  DEFAULT_CLASSIFY_BATCH_SIZE,
  DEFAULT_COMPILE_WORKERS,
  DEFAULT_FILE_LABEL,
  DEFAULT_LANGUAGE,
  DEFAULT_MODE,
  DEFAULT_MODEL_VERSION,
  DEFAULT_RULE_PROFILE,
  DEFAULT_RENDER_MODE,
  DEFAULT_TIMEOUT_SECONDS,
  DEFAULT_WORKERS,
  FRONT_MAX_BYTES,
} from "./constants.js";
import {
  bootstrapDesktop,
  openSettingsDialog,
  openSetupDialog,
  saveDesktopConfig,
  setDesktopBusy,
} from "./desktop.js";
import {
  isTerminalStatus,
  normalizeJobPayload,
  summarizeStatus,
} from "./job.js";
import {
  fetchJobEvents,
  fetchJobArtifactsManifest,
  fetchJobPayload,
  fetchProtected,
  submitJson,
  submitUploadRequest,
} from "./network.js";
import { state } from "./state.js";
import {
  clearFileInputValue,
  prepareFilePicker,
  renderJob,
  resetUploadProgress,
  resetUploadedFile,
  setLinearProgress,
  setStatus,
  setWorkflowSections,
  setUploadProgress,
  updateActionButtons,
  updateJobWarning,
} from "./ui.js";

function setText(id, value) {
  const el = $(id);
  if (el) {
    el.textContent = value;
  }
}

function bindDialogBackdropClose(id) {
  const dialog = $(id);
  if (!dialog) {
    return;
  }
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) {
      dialog.close();
    }
  });
}

function stopPolling() {
  if (state.timer) {
    clearInterval(state.timer);
    state.timer = null;
  }
}

async function fetchJob(jobId) {
  const payload = await fetchJobPayload(jobId, API_PREFIX);
  let eventsPayload = { items: [], limit: 50, offset: 0 };
  let manifestPayload = { items: [] };
  try {
    eventsPayload = await fetchJobEvents(jobId, API_PREFIX, 50, 0);
  } catch (_err) {
    // Event stream is secondary; keep main status usable even if events fail.
  }
  try {
    manifestPayload = await fetchJobArtifactsManifest(jobId, API_PREFIX);
  } catch (_err) {
    // Artifacts manifest is secondary; keep main status usable even if manifest fails.
  }
  renderJob(payload, eventsPayload, manifestPayload);
  const job = normalizeJobPayload(payload);
  if (isTerminalStatus(job.status)) {
    stopPolling();
  }
}

function startPolling(jobId) {
  stopPolling();
  state.currentJobId = jobId;
  if (!state.currentJobStartedAt) {
    state.currentJobStartedAt = new Date().toISOString();
  }
  setWorkflowSections({ job_id: jobId, status: "queued" });
  fetchJob(jobId).catch((err) => {
    setText("error-box", err.message);
  });
  state.timer = setInterval(() => {
    fetchJob(jobId).catch((err) => {
      setText("error-box", err.message);
    });
  }, 3000);
}

function collectUploadFormData(file) {
  const form = new FormData();
  form.append("file", file);
  return form;
}

function normalizePageRangeValue(startValue = "", endValue = "") {
  const start = startValue.trim();
  const end = endValue.trim();
  if (!start && !end) {
    return "";
  }
  if (start && end) {
    return start === end ? start : `${start}-${end}`;
  }
  return start || end;
}

function currentPageRanges() {
  const applied = state.appliedPageRange || "";
  if (applied) {
    return applied;
  }
  const start = $("page-range-start")?.value || "";
  const end = $("page-range-end")?.value || "";
  return normalizePageRangeValue(start, end);
}

function collectRunPayload() {
  const pageRanges = currentPageRanges();
  return {
    workflow: "mineru",
    source: {
      upload_id: state.uploadId,
    },
    ocr: {
      provider: "mineru",
      mineru_token: $("mineru_token").value || defaultMineruToken(),
      model_version: DEFAULT_MODEL_VERSION,
      language: DEFAULT_LANGUAGE,
      page_ranges: pageRanges,
    },
    translation: {
      mode: DEFAULT_MODE,
      model: defaultModelName(),
      base_url: defaultModelBaseUrl(),
      api_key: $("api_key").value || defaultModelApiKey(),
      workers: DEFAULT_WORKERS,
      batch_size: DEFAULT_BATCH_SIZE,
      classify_batch_size: DEFAULT_CLASSIFY_BATCH_SIZE,
      rule_profile_name: DEFAULT_RULE_PROFILE,
      custom_rules_text: "",
      skip_title_translation: false,
    },
    render: {
      render_mode: DEFAULT_RENDER_MODE,
      compile_workers: DEFAULT_COMPILE_WORKERS,
    },
    runtime: {
      timeout_seconds: DEFAULT_TIMEOUT_SECONDS,
    },
  };
}

function fileNameFromDisposition(disposition, fallback) {
  if (!disposition || typeof disposition !== "string") {
    return fallback;
  }
  const utf8Match = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match && utf8Match[1]) {
    try {
      return decodeURIComponent(utf8Match[1]);
    } catch (_err) {
      return utf8Match[1];
    }
  }
  const plainMatch = disposition.match(/filename=\"?([^\";]+)\"?/i);
  return plainMatch && plainMatch[1] ? plainMatch[1] : fallback;
}

function downloadBlob(blob, filename) {
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
}

async function handleProtectedArtifactClick(event) {
  const link = event.currentTarget;
  const disabled = link.classList.contains("disabled") || link.getAttribute("aria-disabled") === "true";
  const url = link.dataset.url || "";
  if (disabled || !url) {
    event.preventDefault();
    return;
  }

  event.preventDefault();
  setText("error-box", "-");

  try {
    const resp = await fetchProtected(url);
    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(`下载失败: ${resp.status} ${text || "unknown error"}`);
    }

    const blob = await resp.blob();
    const disposition = resp.headers.get("content-disposition") || "";
    const jobId = $("job-id-input").value.trim() || state.currentJobId || "result";
    const fallbackName = link.id === "download-btn"
      ? `${jobId}.zip`
      : link.id === "markdown-bundle-btn"
        ? `${jobId}-markdown.zip`
      : link.id === "pdf-btn"
        ? `${jobId}.pdf`
        : link.id === "markdown-raw-btn"
          ? `${jobId}.md`
          : `${jobId}.json`;
    downloadBlob(blob, fileNameFromDisposition(disposition, fallbackName));
  } catch (err) {
    setText("error-box", err.message);
  }
}

async function handleFileSelected() {
  const file = $("file").files[0];
  resetUploadedFile();
  resetUploadProgress();
  setText("file-label", file ? file.name : DEFAULT_FILE_LABEL);
  if ($("file-label")) {
    $("file-label").title = file ? file.name : "";
  }
  if (!file) {
    return;
  }
  if (file.size > FRONT_MAX_BYTES) {
    setText("error-box", "当前前端限制为 200MB 以内 PDF");
    setText("upload-status", "文件超出大小限制");
    $("upload-status")?.classList.remove("hidden");
    return;
  }
  setText("error-box", "-");
  setText("upload-status", "正在上传…");
  $("upload-status")?.classList.remove("hidden");

  try {
    const payload = await submitUploadRequest(
      `${apiBase()}${API_PREFIX}/uploads`,
      collectUploadFormData(file),
      setUploadProgress,
    );
    state.uploadId = payload.upload_id || "";
    state.uploadedFileName = payload.filename || file.name;
    state.uploadedPageCount = Number(payload.page_count || 0);
    state.uploadedBytes = Number(payload.bytes || file.size || 0);
    $("submit-btn").disabled = !state.uploadId;
    $("upload-action-slot")?.classList.toggle("hidden", !state.uploadId);
    $("file")?.closest(".upload-tile")?.classList.toggle("is-ready", !!state.uploadId);
    $("file")?.closest(".upload-tile")?.classList.remove("is-uploading");
    setText("upload-status", `上传完成: ${state.uploadedFileName} | ${state.uploadedPageCount} 页 | ${(state.uploadedBytes / 1024 / 1024).toFixed(2)} MB`);
    $("upload-status")?.classList.remove("hidden");
    clearFileInputValue();
  } catch (err) {
    resetUploadedFile();
    clearFileInputValue();
    setText("error-box", err.message);
    setText("upload-status", "上传失败");
    $("upload-status")?.classList.remove("hidden");
  }
}

async function submitForm(event) {
  event.preventDefault();
  if (state.desktopMode && !state.desktopConfigured) {
    openSetupDialog();
    setText("error-box", "请先完成首次配置。");
    return;
  }
  if (!state.uploadId) {
    setText("error-box", "请先选择并上传 PDF 文件");
    return;
  }

  $("submit-btn").disabled = true;
  setText("error-box", "-");

  try {
    const runPayload = collectRunPayload();
    const payload = await submitJson(`${apiBase()}${API_PREFIX}/jobs`, runPayload);
    state.currentJobStartedAt = new Date().toISOString();
    state.currentJobFinishedAt = "";
    renderJob(payload);
    startPolling(payload.job_id);
  } catch (err) {
    setText("error-box", err.message);
  } finally {
    $("submit-btn").disabled = false;
  }
}

function watchExistingJob() {
  const jobId = $("job-id-input").value.trim();
  if (!jobId) {
    setText("error-box", "请输入 job_id");
    return;
  }
  $("query-dialog")?.close();
  startPolling(jobId);
}

function openQueryDialog() {
  $("query-dialog")?.showModal();
}

function renderPageRangeSummary() {
  const summary = $("page-range-summary");
  if (!summary) {
    return;
  }
  const value = currentPageRanges();
  if (!value) {
    summary.classList.add("hidden");
    summary.textContent = "已选择页码：-";
    return;
  }
  summary.classList.remove("hidden");
  summary.textContent = `已选择页码：${value}`;
}

function openPageRangeDialog() {
  const applied = state.appliedPageRange || "";
  const [start = "", end = ""] = applied.includes("-") ? applied.split("-", 2) : [applied, applied];
  if ($("page-range-start")) {
    $("page-range-start").value = start || "";
  }
  if ($("page-range-end")) {
    $("page-range-end").value = end || "";
  }
  $("page-range-dialog")?.showModal();
}

function applyPageRanges() {
  const startInput = $("page-range-start");
  const endInput = $("page-range-end");
  const start = startInput?.value?.trim() || "";
  const end = endInput?.value?.trim() || "";
  if ((start && Number(start) < 1) || (end && Number(end) < 1)) {
    setText("error-box", "页码必须从 1 开始");
    return;
  }
  if (start && end && Number(start) > Number(end)) {
    setText("error-box", "起始页不能大于结束页");
    return;
  }
  if (startInput) {
    startInput.value = start;
  }
  if (endInput) {
    endInput.value = end;
  }
  state.appliedPageRange = normalizePageRangeValue(start, end);
  setText("error-box", "-");
  renderPageRangeSummary();
  $("page-range-dialog")?.close();
}

function clearPageRanges() {
  if ($("page-range-start")) {
    $("page-range-start").value = "";
  }
  if ($("page-range-end")) {
    $("page-range-end").value = "";
  }
  state.appliedPageRange = "";
  renderPageRangeSummary();
}

function activateDetailTab(name = "overview") {
  const tabs = document.querySelectorAll(".detail-tab");
  const panels = document.querySelectorAll(".detail-tab-panel");
  tabs.forEach((tab) => {
    const active = tab.dataset.tab === name;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", active ? "true" : "false");
  });
  panels.forEach((panel) => {
    const active = panel.dataset.panel === name;
    panel.classList.toggle("is-active", active);
    panel.hidden = !active;
  });
}

function openStatusDetailDialog() {
  activateDetailTab("overview");
  $("status-detail-dialog")?.showModal();
}

async function copyCurrentJobId() {
  const jobId = $("job-id")?.textContent?.trim() || state.currentJobId || "";
  if (!jobId || jobId === "-") {
    setText("error-box", "当前没有可复制的任务编号");
    return;
  }
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(jobId);
    } else {
      const input = document.createElement("textarea");
      input.value = jobId;
      document.body.appendChild(input);
      input.select();
      document.execCommand("copy");
      input.remove();
    }
    setText("copy-job-btn", "已复制");
    window.setTimeout(() => {
      setText("copy-job-btn", "复制任务号");
    }, 1200);
  } catch (_err) {
    setText("error-box", "复制失败，请手动复制任务编号");
  }
}

function returnToHome() {
  stopPolling();
  $("status-detail-dialog")?.close();
  $("page-range-dialog")?.close();
  state.currentJobId = "";
  state.currentJobSnapshot = null;
  state.currentJobStartedAt = "";
  state.currentJobFinishedAt = "";
  state.appliedPageRange = "";
  setWorkflowSections(null);
  resetUploadProgress();
  resetUploadedFile();
  setText("job-summary", summarizeStatus("idle"));
  setText("job-stage-detail", "-");
  setText("job-id", "-");
  setText("query-job-duration", "-");
  setText("job-finished-at", "-");
  setText("query-job-finished-at", "-");
  if ($("job-id-input")) {
    $("job-id-input").value = "";
  }
  setText("copy-job-btn", "复制任务号");
  clearPageRanges();
  setText("runtime-current-stage", "-");
  setText("runtime-stage-elapsed", "-");
  setText("runtime-total-elapsed", "-");
  setText("runtime-retry-count", "0");
  setText("runtime-last-transition", "-");
  setText("runtime-terminal-reason", "-");
  setText("failure-summary", "-");
  setText("failure-category", "-");
  setText("failure-stage", "-");
  setText("failure-root-cause", "-");
  setText("failure-suggestion", "-");
  setText("failure-retryable", "-");
  setText("events-status", "最近 50 条");
  $("events-empty")?.classList.remove("hidden");
  $("events-list")?.classList.add("hidden");
  if ($("events-list")) {
    $("events-list").innerHTML = "";
  }
  activateDetailTab("overview");
}

async function cancelCurrentJob() {
  const jobId = $("job-id-input").value.trim() || state.currentJobId;
  if (!jobId) {
    setText("error-box", "当前没有可取消的任务");
    return;
  }
  $("cancel-btn").disabled = true;
  try {
    await submitJson(`${apiBase()}${API_PREFIX}/jobs/${jobId}/cancel`, {});
    await fetchJob(jobId);
  } catch (err) {
    setText("error-box", err.message);
  }
}

async function handleDesktopSetupSave() {
  const mineruToken = $("setup-mineru-token").value.trim();
  const modelApiKey = $("setup-model-api-key").value.trim();
  if (!mineruToken || !modelApiKey) {
    setDesktopBusy("请先填写 MinerU Token 和 Model API Key。");
    return;
  }
  setDesktopBusy("正在保存配置并启动服务…");
  try {
    await saveDesktopConfig(mineruToken, modelApiKey, checkApiConnectivity);
    setDesktopBusy("");
  } catch (err) {
    setDesktopBusy(err.message || String(err));
  }
}

async function handleDesktopSettingsSave() {
  const mineruToken = $("settings-mineru-token").value.trim();
  const modelApiKey = $("settings-model-api-key").value.trim();
  if (!mineruToken || !modelApiKey) {
    setDesktopBusy("请先填写完整的 Key。");
    return;
  }
  setDesktopBusy("正在保存设置…");
  try {
    await saveDesktopConfig(mineruToken, modelApiKey, checkApiConnectivity);
    setDesktopBusy("");
  } catch (err) {
    setDesktopBusy(err.message || String(err));
  }
}

async function handleOpenOutputDir() {
  try {
    await desktopInvoke("open_output_directory");
  } catch (err) {
    setText("error-box", err.message || String(err));
  }
}

function browserCredentialElements() {
  return {
    dialog: $("browser-credentials-dialog"),
    mineruInput: $("browser-mineru-token"),
    apiKeyInput: $("browser-api-key"),
    trigger: $("credentials-btn"),
  };
}

function syncBrowserDialogFromHiddenInputs() {
  const { mineruInput, apiKeyInput } = browserCredentialElements();
  if (mineruInput) {
    mineruInput.value = $("mineru_token").value || "";
  }
  if (apiKeyInput) {
    apiKeyInput.value = $("api_key").value || "";
  }
}

function persistBrowserCredentialsFromDialog() {
  const { mineruInput, apiKeyInput } = browserCredentialElements();
  applyKeyInputs(
    mineruInput?.value?.trim() || "",
    apiKeyInput?.value?.trim() || "",
  );
  saveBrowserStoredConfig();
}

function hasBrowserCredentials() {
  return Boolean(($("mineru_token").value || "").trim() && ($("api_key").value || "").trim());
}

function updateCredentialGate() {
  const trigger = $("credentials-btn");
  const gate = $("credential-gate");
  const tile = $("file")?.closest(".upload-tile");
  const fileInput = $("file");
  const uploadGlyph = $("upload-glyph");
  const fileLabel = $("file-label");
  const uploadHelp = $("upload-help");
  const uploadMeta = document.querySelector(".upload-meta");
  const uploadStatus = $("upload-status");

  if (!trigger || !gate || !tile || !fileInput || state.desktopMode) {
    return;
  }
  const show = !hasBrowserCredentials();
  gate.classList.toggle("hidden", !show);
  trigger.classList.toggle("is-nudged", show);
  tile.classList.toggle("is-locked", show);
  fileInput.disabled = show;
  uploadGlyph?.classList.toggle("hidden", show);
  fileLabel?.classList.toggle("hidden", show);
  uploadHelp?.classList.toggle("hidden", show);
  uploadMeta?.classList.toggle("hidden", show);
  if (show) {
    uploadStatus?.classList.add("hidden");
  }
  $("submit-btn").disabled = show || !state.uploadId;
  $("upload-action-slot")?.classList.toggle("hidden", show || !state.uploadId);
  tile.classList.toggle("is-ready", !show && !!state.uploadId);
}

function openBrowserCredentialsDialog() {
  const { dialog } = browserCredentialElements();
  if (!dialog) {
    return;
  }
  syncBrowserDialogFromHiddenInputs();
  dialog.showModal();
}

function handleBrowserCredentialSave() {
  persistBrowserCredentialsFromDialog();
  updateCredentialGate();
  $("browser-credentials-dialog")?.close();
}

async function checkApiConnectivity() {
  try {
    const resp = await fetch(`${apiBase()}/health`);
    if (!resp.ok) {
      throw new Error(`health ${resp.status}`);
    }
  } catch (_err) {
    setText("error-box", `当前前端无法连接后端。API Base: ${apiBase()}。请确认本地服务已经启动，然后重试。`);
  }
}

function initializePage() {
  const browserStored = loadBrowserStoredConfig();
  applyKeyInputs(
    browserStored.mineruToken || defaultMineruToken(),
    browserStored.modelApiKey || defaultModelApiKey(),
  );
  [
    "query-dialog",
    "browser-credentials-dialog",
    "desktop-setup-dialog",
    "desktop-settings-dialog",
    "page-range-dialog",
    "status-detail-dialog",
  ].forEach(bindDialogBackdropClose);
  document.querySelector(".upload-tile")?.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    if (target.closest("button") || target.closest("a") || target.closest("input")) {
      return;
    }
    const fileInput = $("file");
    if (!fileInput || fileInput.disabled) {
      return;
    }
    fileInput.click();
  });
  $("file").addEventListener("click", prepareFilePicker);
  $("file").addEventListener("change", handleFileSelected);
  $("mineru_token").addEventListener("input", saveBrowserStoredConfig);
  $("api_key").addEventListener("input", saveBrowserStoredConfig);
  $("job-form").addEventListener("submit", submitForm);
  $("watch-btn").addEventListener("click", watchExistingJob);
  $("open-query-btn").addEventListener("click", openQueryDialog);
  $("page-range-btn")?.addEventListener("click", openPageRangeDialog);
  $("page-range-apply-btn")?.addEventListener("click", applyPageRanges);
  $("page-range-clear-btn")?.addEventListener("click", clearPageRanges);
  $("cancel-btn").addEventListener("click", cancelCurrentJob);
  $("stop-btn").addEventListener("click", stopPolling);
  $("copy-job-btn").addEventListener("click", copyCurrentJobId);
  $("status-detail-btn").addEventListener("click", openStatusDetailDialog);
  $("back-home-btn").addEventListener("click", returnToHome);
  $("download-btn").addEventListener("click", handleProtectedArtifactClick);
  $("markdown-bundle-btn")?.addEventListener("click", handleProtectedArtifactClick);
  $("pdf-btn").addEventListener("click", handleProtectedArtifactClick);
  $("markdown-btn").addEventListener("click", handleProtectedArtifactClick);
  $("markdown-raw-btn").addEventListener("click", handleProtectedArtifactClick);
  $("desktop-settings-btn").addEventListener("click", openSettingsDialog);
  $("desktop-settings-save-btn").addEventListener("click", handleDesktopSettingsSave);
  $("desktop-setup-save-btn").addEventListener("click", handleDesktopSetupSave);
  $("open-output-btn").addEventListener("click", handleOpenOutputDir);
  $("credentials-btn")?.addEventListener("click", () => {
    if (state.desktopMode) {
      openSettingsDialog();
      return;
    }
    openBrowserCredentialsDialog();
  });
  $("browser-credentials-save-btn")?.addEventListener("click", handleBrowserCredentialSave);
  document.querySelectorAll(".detail-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      activateDetailTab(tab.dataset.tab || "overview");
    });
  });
  updateActionButtons(normalizeJobPayload({}));
  setWorkflowSections(null);
  setLinearProgress("job-progress-bar", "job-progress-text", NaN, NaN, "-");
  setText("job-summary", summarizeStatus("idle"));
  setText("job-stage-detail", "-");
  setText("query-job-finished-at", "-");
  setText("query-job-duration", "-");
  setText("diagnostic-box", "-");
  setText("runtime-current-stage", "-");
  setText("runtime-stage-elapsed", "-");
  setText("runtime-total-elapsed", "-");
  setText("runtime-retry-count", "0");
  setText("runtime-last-transition", "-");
  setText("runtime-terminal-reason", "-");
  setText("failure-summary", "-");
  setText("failure-category", "-");
  setText("failure-stage", "-");
  setText("failure-root-cause", "-");
  setText("failure-suggestion", "-");
  setText("failure-retryable", "-");
  setText("events-status", "最近 50 条");
  $("events-empty")?.classList.remove("hidden");
  $("events-list")?.classList.add("hidden");
  if ($("events-list")) {
    $("events-list").innerHTML = "";
  }
  activateDetailTab("overview");
  renderPageRangeSummary();
  resetUploadProgress();
  resetUploadedFile();
  updateJobWarning("idle");
  updateCredentialGate();
}

export function initializeApp() {
  initializePage();
  if (isDesktopMode()) {
    bootstrapDesktop().catch((err) => {
      setText("error-box", err.message || String(err));
    });
  } else {
    checkApiConnectivity().catch(() => {});
    updateCredentialGate();
  }
}
