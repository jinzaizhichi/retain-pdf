import { saveBrowserStoredConfig } from "./config.js";
import { $ } from "./dom.js";
import { bindDynamicPrimaryActions } from "./main-helpers.js";

export function bindMainEvents({
  developerFeature,
  glossariesFeature,
  homeFeature,
  artifactDownloadsFeature,
  statusDetailFeature,
  appShellFeature,
  workflowFeature,
  uploadFeature,
  appActionsFeature,
  jobRuntimeFeature,
  state,
  fetchProtected,
  setText,
}) {
  developerFeature?.bindEvents();
  glossariesFeature?.bindEvents();
  homeFeature?.bindEvents();
  artifactDownloadsFeature?.bindEvents();
  statusDetailFeature?.bindEvents();
  appShellFeature?.bindChrome();

  $("file")?.addEventListener("change", () => {
    void uploadFeature?.handleFileSelected();
  });
  $("credential-gate-action")?.addEventListener("click", (event) => {
    event.preventDefault();
    document.dispatchEvent(new CustomEvent("retainpdf:open-browser-credentials"));
  });
  $("ocr_provider")?.addEventListener("input", saveBrowserStoredConfig);
  $("mineru_token")?.addEventListener("input", saveBrowserStoredConfig);
  $("paddle_token")?.addEventListener("input", saveBrowserStoredConfig);
  $("api_key")?.addEventListener("input", saveBrowserStoredConfig);
  $("job-form")?.addEventListener("submit", (event) => {
    void appActionsFeature?.submitForm(event);
  });
  $("page-range-btn")?.addEventListener("click", () => uploadFeature?.openPageRangeDialog());
  $("page-range-apply-btn")?.addEventListener("click", () => uploadFeature?.applyPageRanges());
  $("page-range-clear-btn")?.addEventListener("click", () => uploadFeature?.clearPageRanges());
  $("page-range-start")?.addEventListener("input", () => workflowFeature?.refreshSubmitControls());
  $("page-range-end")?.addEventListener("input", () => workflowFeature?.refreshSubmitControls());
  $("cancel-btn")?.addEventListener("click", () => jobRuntimeFeature?.cancelCurrentJob());
  bindDynamicPrimaryActions({
    state,
    fetchProtected,
    setTextFn: setText,
    statusDetailFeature,
  });
  $("back-home-btn")?.addEventListener("click", () => jobRuntimeFeature?.returnToHome());
  document.addEventListener("retainpdf:return-home", () => jobRuntimeFeature?.returnToHome());
  document.addEventListener("retainpdf:retry-stage", (event) => {
    void jobRuntimeFeature?.retryStage(event.detail?.stage);
  });
  $("open-output-btn")?.addEventListener("click", () => {
    void appActionsFeature?.handleOpenOutputDir();
  });
}
