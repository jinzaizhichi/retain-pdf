import { normalizeJobPayload } from "../../job.js";
import {
  cacheSecondaryResource,
  cachedEventsFor,
  cachedManifestFor,
  fetchAllJobEvents,
  fetchRecentJobEvents,
  cachedStageActionsFor,
  clearSecondaryFetchInFlightForCurrentJob,
  currentJobSnapshotFor,
  isCurrentJobGeneration,
  isSecondaryFetchInFlight,
  JOB_EVENTS_REFRESH_MS,
  JOB_MANIFEST_REFRESH_MS,
  JOB_STAGE_ACTIONS_REFRESH_MS,
  secondaryResourceFetchedAt,
  setSecondaryFetchInFlight,
  shouldRefreshSecondary,
} from "./runtime-state.js";

function latestJobPayloadFor(state, jobId, fallbackPayload) {
  const snapshot = currentJobSnapshotFor(state, jobId);
  return snapshot || fallbackPayload;
}

function renderLatestJob({
  state,
  jobId,
  fallbackPayload,
  eventsPayload,
  manifestPayload,
  stageActionsPayload,
  renderJob,
}) {
  renderJob(
    latestJobPayloadFor(state, jobId, fallbackPayload),
    eventsPayload,
    manifestPayload,
    stageActionsPayload,
  );
}

export function scheduleSecondaryResourceFetches({
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
}) {
  const cachedEvents = cachedEventsFor(state, jobId);
  const cachedManifest = cachedManifestFor(state, jobId);
  const cachedStageActions = cachedStageActionsFor(state, jobId);

  if (!isSecondaryFetchInFlight(state, "events") && shouldRefreshSecondary(secondaryResourceFetchedAt(state, "events"), JOB_EVENTS_REFRESH_MS, terminal || !cachedEvents)) {
    setSecondaryFetchInFlight(state, "events", true);
    const eventsGeneration = generation;
    const fetchEvents = terminal ? fetchAllJobEvents : fetchRecentJobEvents;
    void fetchEvents({ fetchJobEvents, apiPrefix, jobId })
      .then((eventsPayload) => {
        if (!isCurrentJobGeneration(state, jobId, eventsGeneration)) {
          return;
        }
        cacheSecondaryResource(state, "events", jobId, eventsPayload);
        renderLatestJob({
          state,
          jobId,
          fallbackPayload: payload,
          eventsPayload,
          manifestPayload: cachedManifestFor(state, jobId),
          stageActionsPayload: cachedStageActionsFor(state, jobId),
          renderJob,
        });
        notifyLibraryJobUpdated(currentJobSnapshotFor(state, jobId) || normalizeJobPayload(payload));
      })
      .catch(() => {
        // Event stream is secondary; keep main status usable even if events fail.
      })
      .finally(() => {
        clearSecondaryFetchInFlightForCurrentJob(state, "events", jobId);
      });
  }

  if (!isSecondaryFetchInFlight(state, "manifest") && shouldRefreshSecondary(secondaryResourceFetchedAt(state, "manifest"), JOB_MANIFEST_REFRESH_MS, terminal || !cachedManifest)) {
    setSecondaryFetchInFlight(state, "manifest", true);
    const manifestGeneration = generation;
    void fetchJobArtifactsManifest(jobId, apiPrefix)
      .then((manifestPayload) => {
        if (!isCurrentJobGeneration(state, jobId, manifestGeneration)) {
          return;
        }
        cacheSecondaryResource(state, "manifest", jobId, manifestPayload);
        renderLatestJob({
          state,
          jobId,
          fallbackPayload: payload,
          eventsPayload: cachedEventsFor(state, jobId),
          manifestPayload,
          stageActionsPayload: cachedStageActionsFor(state, jobId),
          renderJob,
        });
      })
      .catch(() => {
        // Artifacts manifest is secondary; keep main status usable even if manifest fails.
      })
      .finally(() => {
        clearSecondaryFetchInFlightForCurrentJob(state, "manifest", jobId);
      });
  }

  if (fetchJobStageActions && !isSecondaryFetchInFlight(state, "stageActions") && shouldRefreshSecondary(secondaryResourceFetchedAt(state, "stageActions"), JOB_STAGE_ACTIONS_REFRESH_MS, terminal || !cachedStageActions)) {
    setSecondaryFetchInFlight(state, "stageActions", true);
    const stageActionsGeneration = generation;
    void fetchJobStageActions(jobId, apiPrefix)
      .then((stageActionsPayload) => {
        if (!isCurrentJobGeneration(state, jobId, stageActionsGeneration)) {
          return;
        }
        cacheSecondaryResource(state, "stageActions", jobId, stageActionsPayload);
        renderLatestJob({
          state,
          jobId,
          fallbackPayload: payload,
          eventsPayload: cachedEventsFor(state, jobId),
          manifestPayload: cachedManifestFor(state, jobId),
          stageActionsPayload,
          renderJob,
        });
      })
      .catch(() => {
        // Stage actions are secondary; keep main status usable even if action discovery fails.
      })
      .finally(() => {
        clearSecondaryFetchInFlightForCurrentJob(state, "stageActions", jobId);
      });
  }
}
