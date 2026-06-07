import { API_PREFIX } from "../constants.js";
import { mountJobRuntimeFeature } from "../features/job-runtime/controller.js";
import { mountStatusDetailFeature } from "../features/status-detail/controller.js";
import {
  buildJobDetailEndpoint,
  submitJson,
} from "../api/http.js";
import {
  fetchJobArtifactsManifest,
  fetchJobDiagnostics,
  fetchJobEvents,
  fetchJobPayload,
  fetchJobStageActions,
  fetchResumePlan,
  rerunJob,
  retryJobStage,
} from "../api/jobs.js";
import {
  fetchTranslationDiagnostics,
  fetchTranslationItem,
  fetchTranslationItems,
  replayTranslationItem,
} from "../api/translation-debug.js";
import { state } from "../state/store.js";
import {
  renderJob,
  resetUploadProgress,
  resetUploadedFile,
  setWorkflowSections,
  updateJobWarning,
} from "../ui.js";
import { setText } from "../main-helpers.js";

export function mountJobFeatures(features) {
  features.statusDetailFeature = mountStatusDetailFeature({
    state,
    apiPrefix: API_PREFIX,
    fetchJobPayload,
    fetchJobEvents,
    fetchJobDiagnostics,
    fetchResumePlan,
    fetchTranslationDiagnostics,
    fetchTranslationItems,
    fetchTranslationItem,
    replayTranslationItem,
    rerunJob,
    renderJob,
    startPolling: (jobId) => features.jobRuntimeFeature?.startPolling(jobId),
    setText,
  });
  features.jobRuntimeFeature = mountJobRuntimeFeature({
    state,
    apiPrefix: API_PREFIX,
    buildJobDetailEndpoint,
    fetchJobPayload,
    fetchJobEvents,
    fetchJobArtifactsManifest,
    fetchJobStageActions,
    retryJobStage,
    submitJson,
    renderJob,
    setText,
    setWorkflowSections,
    resetUploadProgress,
    resetUploadedFile,
    applyWorkflowMode: () => features.workflowFeature?.applyWorkflowMode(),
    clearPageRanges: () => features.uploadFeature?.clearPageRanges(),
    updateJobWarning,
    activateDetailTab: (name) => features.statusDetailFeature?.activateDetailTab(name),
    onReaderDialogSync: () => features.readerDialogFeature?.syncToolbarActions(),
    onReaderDialogClose: () => features.readerDialogFeature?.close(),
  });
}
