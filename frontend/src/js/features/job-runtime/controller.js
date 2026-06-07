import { normalizeJobPayload, isTerminalStatus } from "../../job.js";
import { resetJobSecondaryState } from "../../state/actions.js";
import { isReaderDialogOpen, setCancelButtonDisabled } from "../app-shell/view.js";
import {
  clearActiveJobId,
  writeActiveJobId,
} from "./active-job-storage.js";
import {
  beginJobPoll,
  cachedEventsFor,
  cachedManifestFor,
  cachedStageActionsFor,
  currentJobSnapshot,
  currentJobId,
  finishJobPoll,
  isCurrentJobGeneration,
  JOB_POLL_INTERVAL_MS,
  startPollingTimer,
  startRuntimeJob,
  stopPolling,
} from "./runtime-state.js";
import {
  notifyLibraryJobUpdated,
  requestLibraryRefresh,
} from "./library-events.js";
import { scheduleSecondaryResourceFetches } from "./secondary-resources.js";
import { returnJobRuntimeToHome } from "./runtime-reset.js";

export function mountJobRuntimeFeature({
  state,
  apiPrefix,
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
  applyWorkflowMode,
  clearPageRanges,
  updateJobWarning,
  activateDetailTab,
  onReaderDialogSync,
  onReaderDialogClose,
}) {
  async function fetchJob(jobId) {
    const generation = beginJobPoll(state);
    if (generation === null) {
      return;
    }
    let payload;
    try {
      payload = await fetchJobPayload(jobId, apiPrefix);
    } finally {
      finishJobPoll(state);
    }
    if (!isCurrentJobGeneration(state, jobId, generation)) {
      return;
    }
    const cachedEvents = cachedEventsFor(state, jobId);
    const cachedManifest = cachedManifestFor(state, jobId);
    const cachedStageActions = cachedStageActionsFor(state, jobId);
    renderJob(payload, cachedEvents, cachedManifest, cachedStageActions);
    notifyLibraryJobUpdated(currentJobSnapshot(state) || normalizeJobPayload(payload));
    if (isReaderDialogOpen()) {
      onReaderDialogSync?.();
    }
    const job = normalizeJobPayload(payload);
    const terminal = isTerminalStatus(job.status);
    requestLibraryRefresh(state, { terminal });
    if (isTerminalStatus(job.status)) {
      clearActiveJobId(jobId);
      stopPolling(state);
    }
    scheduleSecondaryResourceFetches({
      state,
      apiPrefix,
      jobId,
      payload,
      generation,
      terminal,
      fetchJobEvents,
      fetchJobArtifactsManifest,
      fetchJobStageActions,
      renderJob,
      notifyLibraryJobUpdated,
    });
  }

  function startPolling(jobId) {
    stopPolling(state);
    writeActiveJobId(jobId);
    resetJobSecondaryState(state);
    const { startedAt } = startRuntimeJob(state, jobId);
    const placeholderJob = {
      job_id: jobId,
      status: "queued",
      stage: "queued",
      current_stage: "queued",
      stage_detail: "正在读取任务状态...",
      created_at: startedAt,
      started_at: startedAt,
    };
    setWorkflowSections(placeholderJob);
    renderJob(placeholderJob);
    requestLibraryRefresh(state);
    fetchJob(jobId).catch((err) => {
      setText("error-box", err.message);
    });
    startPollingTimer(state, () => {
      fetchJob(jobId).catch((err) => {
        setText("error-box", err.message);
      });
    }, JOB_POLL_INTERVAL_MS);
  }

  function returnToHome() {
    returnJobRuntimeToHome({
      state,
      onReaderDialogClose,
      setWorkflowSections,
      resetUploadProgress,
      resetUploadedFile,
      applyWorkflowMode,
      clearPageRanges,
      setText,
      updateJobWarning,
      activateDetailTab,
    });
  }

  async function cancelCurrentJob() {
    const jobId = currentJobId(state);
    if (!jobId) {
      setText("error-box", "当前没有可取消的任务");
      return;
    }
    setCancelButtonDisabled(true);
    try {
      await submitJson(`${buildJobDetailEndpoint(jobId, apiPrefix)}/cancel`, {});
      await fetchJob(jobId);
    } catch (err) {
      setText("error-box", err.message);
    }
  }

  async function retryStage(stage) {
    const jobId = currentJobId(state);
    const normalizedStage = `${stage || ""}`.trim();
    if (!jobId || !normalizedStage) {
      setText("error-box", "当前没有可重新执行的阶段");
      return;
    }
    try {
      setText("error-box", "-");
      const result = await retryJobStage(jobId, apiPrefix, normalizedStage);
      const nextJobId = `${result?.job_id || jobId}`.trim();
      if (nextJobId) {
        startPolling(nextJobId);
      } else {
        await fetchJob(jobId);
      }
    } catch (err) {
      setText("error-box", err.message || String(err));
    }
  }

  return {
    cancelCurrentJob,
    currentJobId: () => currentJobId(state),
    fetchJob,
    retryStage,
    returnToHome,
    startPolling,
    stopPolling,
  };
}
