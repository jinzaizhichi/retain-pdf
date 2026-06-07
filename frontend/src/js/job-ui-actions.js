import { buildFrontendPageUrl } from "./config.js";
import {
  hasReadyManifestArtifact,
  resolveManifestArtifactUrl,
} from "./job-artifacts.js";
import {
  resolveJobActions,
  resolveJobSourcePdfAction,
} from "./job.js";
import {
  clearFileInputValueView,
  resetUploadedFileView,
  resetUploadProgressView,
  setActionLinkView,
  setLinearProgressView,
  setStatusCardCancelEnabled,
  setUploadProgressView,
} from "./job-ui-actions-view.js";
import { resetUploadState } from "./state/actions.js";
import { state } from "./state/store.js";
import { clearCurrentJobTiming } from "./features/job-runtime/runtime-state.js";

export function setActionLink(id, url, enabled) {
  setActionLinkView(id, url, enabled);
}

export function buildReaderPageUrl(jobId) {
  const normalizedJobId = `${jobId || ""}`.trim();
  if (!normalizedJobId) {
    return "";
  }
  return buildFrontendPageUrl("./reader.html", {
    job_id: normalizedJobId,
  });
}

export function isReaderActionEnabled(job, manifestPayload = null) {
  const actions = resolveJobActions(job);
  const sourcePdfAction = resolveJobSourcePdfAction(job, manifestPayload);
  return Boolean(
    job?.job_id
    && sourcePdfAction.ready
    && (hasReadyManifestArtifact(manifestPayload, "pdf")
      || hasReadyManifestArtifact(manifestPayload, "translated_pdf")
      || hasReadyManifestArtifact(manifestPayload, "result_pdf")
      || actions.pdfEnabled),
  );
}

export function updateActionButtons(job, manifestPayload = null) {
  const actions = resolveJobActions(job);
  setActionLink("download-btn", actions.bundle, actions.bundleEnabled && !!actions.bundle);
  const markdownBundleUrl = resolveManifestArtifactUrl(manifestPayload, "markdown_bundle_zip", {
    includeJobDir: true,
  });
  const sourcePdfAction = resolveJobSourcePdfAction(job, manifestPayload);
  setActionLink("markdown-bundle-btn", markdownBundleUrl, !!markdownBundleUrl);
  setActionLink("source-pdf-btn", sourcePdfAction.url, sourcePdfAction.ready && !!sourcePdfAction.url);
  setActionLink("pdf-btn", actions.pdf, actions.pdfEnabled && !!actions.pdf);
  setActionLink("markdown-btn", actions.markdownJson, actions.markdownJsonEnabled && !!actions.markdownJson);
  setActionLink("markdown-raw-btn", actions.markdownRaw, actions.markdownRawEnabled && !!actions.markdownRaw);
  const readerEnabled = isReaderActionEnabled(job, manifestPayload);
  setActionLink("reader-btn", buildReaderPageUrl(job?.job_id), readerEnabled);
  setActionLink("compare-reader-btn", buildReaderPageUrl(job?.job_id), readerEnabled);
  setStatusCardCancelEnabled(actions.cancelEnabled && !!actions.cancel);
}

export function setLinearProgress(barId, textId, current, total, fallbackText = "-", percentOverride = null) {
  setLinearProgressView(barId, textId, current, total, fallbackText, percentOverride);
}

export function setUploadProgress(loaded, total) {
  setUploadProgressView(loaded, total);
}

export function resetUploadProgress() {
  resetUploadProgressView();
}

export function clearFileInputValue() {
  clearFileInputValueView();
}

export function resetUploadedFile() {
  resetUploadState(state, { includePageRange: false });
  clearCurrentJobTiming(state);
  resetUploadedFileView();
}

export function prepareFilePicker() {
  clearFileInputValue();
}
