import { normalizeJobPayload, isTerminalStatus } from "../../job.js";
import { resetJobSecondaryState } from "../../state.js";
import { isReaderDialogOpen, setCancelButtonDisabled } from "../app-shell/view.js";
import {
  clearActiveJobId,
  writeActiveJobId,
} from "./active-job-storage.js";
import {
  cachedEventsFor,
  cachedManifestFor,
  fetchAllJobEvents,
  fetchRecentJobEvents,
  cachedStageActionsFor,
  JOB_EVENTS_REFRESH_MS,
  JOB_MANIFEST_REFRESH_MS,
  JOB_POLL_INTERVAL_MS,
  JOB_STAGE_ACTIONS_REFRESH_MS,
  shouldRefreshSecondary,
  stopPolling,
} from "./runtime-state.js";
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
  function requestLibraryRefresh({ terminal = false } = {}) {
    const now = Date.now();
    const minInterval = terminal ? 0 : 4000;
    if (!terminal && state.lastLibraryRefreshRequestedAt && now - state.lastLibraryRefreshRequestedAt < minInterval) {
      return;
    }
    state.lastLibraryRefreshRequestedAt = now;
    document.dispatchEvent(new CustomEvent("retainpdf:library-refresh-requested", {
      detail: { delay: terminal ? 200 : 800 },
    }));
  }

  function notifyLibraryJobUpdated(job) {
    document.dispatchEvent(new CustomEvent("retainpdf:library-job-updated", {
      detail: { job },
    }));
  }

  function latestJobPayloadFor(jobId, fallbackPayload) {
    const snapshot = state.currentJobId === jobId ? state.currentJobSnapshot : null;
    return snapshot || fallbackPayload;
  }

  function renderLatestJob(jobId, fallbackPayload, eventsPayload, manifestPayload, stageActionsPayload) {
    renderJob(
      latestJobPayloadFor(jobId, fallbackPayload),
      eventsPayload,
      manifestPayload,
      stageActionsPayload,
    );
  }

  async function fetchJob(jobId) {
    if (state.currentJobPollInFlight) {
      return;
    }
    state.currentJobPollInFlight = true;
    const generation = Number(state.currentJobPollGeneration || 0);
    let payload;
    try {
      payload = await fetchJobPayload(jobId, apiPrefix);
    } finally {
      state.currentJobPollInFlight = false;
    }
    if (state.currentJobId !== jobId || generation !== Number(state.currentJobPollGeneration || 0)) {
      return;
    }
    const cachedEvents = cachedEventsFor(state, jobId);
    const cachedManifest = cachedManifestFor(state, jobId);
    const cachedStageActions = cachedStageActionsFor(state, jobId);
    renderJob(payload, cachedEvents, cachedManifest, cachedStageActions);
    notifyLibraryJobUpdated(state.currentJobSnapshot || normalizeJobPayload(payload));
    if (isReaderDialogOpen()) {
      onReaderDialogSync?.();
    }
    const job = normalizeJobPayload(payload);
    const terminal = isTerminalStatus(job.status);
    requestLibraryRefresh({ terminal });
    if (isTerminalStatus(job.status)) {
      clearActiveJobId(jobId);
      stopPolling(state);
    }
    if (!state.currentJobEventsFetchInFlight && shouldRefreshSecondary(state.currentJobEventsFetchedAt, JOB_EVENTS_REFRESH_MS, terminal || !cachedEvents)) {
      state.currentJobEventsFetchInFlight = true;
      const eventsGeneration = generation;
      const fetchEvents = terminal ? fetchAllJobEvents : fetchRecentJobEvents;
      void fetchEvents({ fetchJobEvents, apiPrefix, jobId })
        .then((eventsPayload) => {
          if (state.currentJobId !== jobId || eventsGeneration !== Number(state.currentJobPollGeneration || 0)) {
            return;
          }
          state.currentJobEvents = eventsPayload;
          state.currentJobEventsJobId = jobId;
          state.currentJobEventsFetchedAt = Date.now();
          renderLatestJob(jobId, payload, eventsPayload, cachedManifestFor(state, jobId), cachedStageActionsFor(state, jobId));
          notifyLibraryJobUpdated(state.currentJobSnapshot || normalizeJobPayload(payload));
        })
        .catch(() => {
          // Event stream is secondary; keep main status usable even if events fail.
        })
        .finally(() => {
          if (state.currentJobId === jobId) {
            state.currentJobEventsFetchInFlight = false;
          }
        });
    }
    if (!state.currentJobManifestFetchInFlight && shouldRefreshSecondary(state.currentJobManifestFetchedAt, JOB_MANIFEST_REFRESH_MS, terminal || !cachedManifest)) {
      state.currentJobManifestFetchInFlight = true;
      const manifestGeneration = generation;
      void fetchJobArtifactsManifest(jobId, apiPrefix)
        .then((manifestPayload) => {
          if (state.currentJobId !== jobId || manifestGeneration !== Number(state.currentJobPollGeneration || 0)) {
            return;
          }
          state.currentJobManifest = manifestPayload;
          state.currentJobManifestJobId = jobId;
          state.currentJobManifestFetchedAt = Date.now();
          renderLatestJob(jobId, payload, cachedEventsFor(state, jobId), manifestPayload, cachedStageActionsFor(state, jobId));
        })
        .catch(() => {
          // Artifacts manifest is secondary; keep main status usable even if manifest fails.
        })
        .finally(() => {
          if (state.currentJobId === jobId) {
            state.currentJobManifestFetchInFlight = false;
          }
        });
    }
    if (fetchJobStageActions && !state.currentJobStageActionsFetchInFlight && shouldRefreshSecondary(state.currentJobStageActionsFetchedAt, JOB_STAGE_ACTIONS_REFRESH_MS, terminal || !cachedStageActions)) {
      state.currentJobStageActionsFetchInFlight = true;
      const stageActionsGeneration = generation;
      void fetchJobStageActions(jobId, apiPrefix)
        .then((stageActionsPayload) => {
          if (state.currentJobId !== jobId || stageActionsGeneration !== Number(state.currentJobPollGeneration || 0)) {
            return;
          }
          state.currentJobStageActions = stageActionsPayload;
          state.currentJobStageActionsJobId = jobId;
          state.currentJobStageActionsFetchedAt = Date.now();
          renderLatestJob(jobId, payload, cachedEventsFor(state, jobId), cachedManifestFor(state, jobId), stageActionsPayload);
        })
        .catch(() => {
          // Stage actions are secondary; keep main status usable even if action discovery fails.
        })
        .finally(() => {
          if (state.currentJobId === jobId) {
            state.currentJobStageActionsFetchInFlight = false;
          }
        });
    }
  }

  function startPolling(jobId) {
    stopPolling(state);
    state.currentJobId = jobId;
    writeActiveJobId(jobId);
    resetJobSecondaryState(state);
    state.currentJobPollGeneration = Number(state.currentJobPollGeneration || 0) + 1;
    if (!state.currentJobStartedAt) {
      state.currentJobStartedAt = new Date().toISOString();
    }
    const placeholderJob = {
      job_id: jobId,
      status: "queued",
      stage: "queued",
      current_stage: "queued",
      stage_detail: "正在读取任务状态...",
      created_at: state.currentJobStartedAt,
      started_at: state.currentJobStartedAt,
    };
    setWorkflowSections(placeholderJob);
    renderJob(placeholderJob);
    requestLibraryRefresh();
    fetchJob(jobId).catch((err) => {
      setText("error-box", err.message);
    });
    state.timer = setInterval(() => {
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
    const jobId = state.currentJobId;
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
    const jobId = state.currentJobId;
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
    currentJobId: () => `${state.currentJobId || ""}`.trim(),
    fetchJob,
    retryStage,
    returnToHome,
    startPolling,
    stopPolling,
  };
}
