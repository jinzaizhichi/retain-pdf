import {
  prepareFilePicker,
  resetUploadedFile as resetUploadedFilePresentation,
  setLinearProgress,
  updateActionButtons,
} from "./job-ui-actions.js";
import { resolveRenderStagePresentation } from "./job-render-stage-presentation.js";
import { renderJobStatusCard } from "./job-status-card-renderer.js";
import { renderStatusDetails } from "./status-detail-renderer.js";
import {
  startElapsedTicker,
  stopElapsedTicker,
} from "./job-elapsed-renderer.js";
import { renderJobStatusSummary } from "./job-status-summary-renderer.js";
import {
  setStatusView,
} from "./ui-presentation-view.js";
import { syncJobRenderCache } from "./job-render-cache.js";
import {
  setWorkflowSections as setWorkflowSectionsVisibility,
  updateJobWarning,
} from "./job-workflow-visibility.js";
import { state } from "./state/store.js";
import {
  isTerminalStatus,
} from "./job.js";

export function setStatus(status) {
  setStatusView(status);
  startElapsedTicker(state);
}

export function setWorkflowSections(job = null) {
  setWorkflowSectionsVisibility(job, {
    onClear: () => stopElapsedTicker(state),
  });
}

export {
  clearFileInputValue,
  prepareFilePicker,
  resetUploadProgress,
  setLinearProgress,
  setUploadProgress,
  updateActionButtons,
} from "./job-ui-actions.js";

export function resetUploadedFile() {
  stopElapsedTicker(state);
  resetUploadedFilePresentation();
}

export { updateJobWarning };

export function renderJob(payload, eventsPayload = null, manifestPayload = null, stageActionsPayload = null) {
  const { job, jobId, events, manifest, stageActions } = syncJobRenderCache({
    state,
    payload,
    eventsPayload,
    manifestPayload,
    stageActionsPayload,
  });
  const stagePresentation = resolveRenderStagePresentation({
    state,
    job,
    jobId,
    events,
  });
  setWorkflowSections(job);
  setStatus(job.status || "idle");
  const { publicErrorText } = renderJobStatusSummary(job, stagePresentation);
  updateActionButtons(job, manifest);
  renderJobStatusCard({
    job,
    jobId,
    stagePresentation,
    events,
    manifest,
    stageActions,
    publicErrorText,
  });
  renderStatusDetails(job, events);
  startElapsedTicker(state);
  updateJobWarning(job.status || "idle");
}
