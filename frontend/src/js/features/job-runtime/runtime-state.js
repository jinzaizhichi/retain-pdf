export const JOB_EVENTS_PAGE_SIZE = 200;
export const JOB_EVENTS_PREVIEW_PAGE_SIZE = 500;
export const JOB_POLL_INTERVAL_MS = 1000;
export const JOB_EVENTS_REFRESH_MS = 2500;
export const JOB_MANIFEST_REFRESH_MS = 5000;
export const JOB_STAGE_ACTIONS_REFRESH_MS = 5000;

export function stopPolling(state) {
  if (state.timer) {
    clearInterval(state.timer);
    state.timer = null;
  }
  state.currentJobPollInFlight = false;
  state.currentJobEventsFetchInFlight = false;
  state.currentJobManifestFetchInFlight = false;
  state.currentJobStageActionsFetchInFlight = false;
}

export function beginJobPoll(state) {
  if (state.currentJobPollInFlight) {
    return null;
  }
  state.currentJobPollInFlight = true;
  return Number(state.currentJobPollGeneration || 0);
}

export function finishJobPoll(state) {
  state.currentJobPollInFlight = false;
}

export function isCurrentJobGeneration(state, jobId, generation) {
  return state.currentJobId === jobId
    && Number(generation) === Number(state.currentJobPollGeneration || 0);
}

export function startRuntimeJob(state, jobId) {
  state.currentJobId = jobId;
  state.currentJobPollGeneration = Number(state.currentJobPollGeneration || 0) + 1;
  if (!state.currentJobStartedAt) {
    state.currentJobStartedAt = new Date().toISOString();
  }
  return {
    generation: Number(state.currentJobPollGeneration || 0),
    startedAt: state.currentJobStartedAt,
  };
}

export function startPollingTimer(state, callback, intervalMs = JOB_POLL_INTERVAL_MS) {
  if (state.timer) {
    clearInterval(state.timer);
  }
  state.timer = setInterval(callback, intervalMs);
}

export function stopElapsedTimer(state) {
  if (state.elapsedTimer) {
    clearInterval(state.elapsedTimer);
    state.elapsedTimer = null;
  }
}

export function startElapsedTimer(state, callback, intervalMs = 1000) {
  stopElapsedTimer(state);
  state.elapsedTimer = setInterval(callback, intervalMs);
}

export function currentJobId(state) {
  return `${state.currentJobId || ""}`.trim();
}

export function currentJobSnapshot(state) {
  return state.currentJobSnapshot || null;
}

export function currentJobFinishedAt(state) {
  return `${state.currentJobFinishedAt || ""}`.trim();
}

export function currentJobSnapshotFor(state, jobId) {
  return state.currentJobId === jobId ? state.currentJobSnapshot : null;
}

export function currentJobManifest(state) {
  return state.currentJobManifest || null;
}

export function currentJobStageActions(state) {
  return state.currentJobStageActions || null;
}

export function currentJobEventsFor(state, jobId) {
  return state.currentJobEventsJobId === jobId ? state.currentJobEvents : null;
}

export function currentDisplayedStagePin(state) {
  return {
    jobId: `${state.currentJobDisplayedStageJobId || ""}`.trim(),
    stageKey: `${state.currentJobDisplayedStageKey || ""}`.trim(),
  };
}

export function resetDisplayedStagePin(state, jobId) {
  state.currentJobDisplayedStageKey = "";
  state.currentJobDisplayedStageJobId = `${jobId || ""}`.trim();
}

export function setDisplayedStagePin(state, stageKey) {
  state.currentJobDisplayedStageKey = `${stageKey || ""}`.trim();
}

const SECONDARY_RESOURCE_FIELDS = Object.freeze({
  events: {
    payload: "currentJobEvents",
    jobId: "currentJobEventsJobId",
    fetchedAt: "currentJobEventsFetchedAt",
    inFlight: "currentJobEventsFetchInFlight",
  },
  manifest: {
    payload: "currentJobManifest",
    jobId: "currentJobManifestJobId",
    fetchedAt: "currentJobManifestFetchedAt",
    inFlight: "currentJobManifestFetchInFlight",
  },
  stageActions: {
    payload: "currentJobStageActions",
    jobId: "currentJobStageActionsJobId",
    fetchedAt: "currentJobStageActionsFetchedAt",
    inFlight: "currentJobStageActionsFetchInFlight",
  },
});

function secondaryResourceFields(type) {
  return SECONDARY_RESOURCE_FIELDS[type] || null;
}

export function isSecondaryFetchInFlight(state, type) {
  const fields = secondaryResourceFields(type);
  return fields ? Boolean(state[fields.inFlight]) : false;
}

export function secondaryResourceFetchedAt(state, type) {
  const fields = secondaryResourceFields(type);
  return fields ? Number(state[fields.fetchedAt] || 0) : 0;
}

export function setSecondaryFetchInFlight(state, type, value) {
  const fields = secondaryResourceFields(type);
  if (fields) {
    state[fields.inFlight] = Boolean(value);
  }
}

export function clearSecondaryFetchInFlightForCurrentJob(state, type, jobId) {
  if (state.currentJobId === jobId) {
    setSecondaryFetchInFlight(state, type, false);
  }
}

export function cacheSecondaryResource(state, type, jobId, payload) {
  const fields = secondaryResourceFields(type);
  if (!fields) {
    return;
  }
  state[fields.payload] = payload;
  state[fields.jobId] = jobId;
  state[fields.fetchedAt] = Date.now();
}

export function clearSecondaryResourceForOtherJob(state, type, jobId) {
  const fields = secondaryResourceFields(type);
  if (!fields || !state[fields.jobId] || state[fields.jobId] === jobId) {
    return;
  }
  state[fields.payload] = null;
  state[fields.jobId] = "";
  state[fields.fetchedAt] = 0;
}

export function cachedSecondaryResourceFor(state, type, jobId) {
  const fields = secondaryResourceFields(type);
  return fields && state[fields.jobId] === jobId ? state[fields.payload] : null;
}

export function syncSecondaryResource(state, type, jobId, payload) {
  if (payload === null) {
    clearSecondaryResourceForOtherJob(state, type, jobId);
    return cachedSecondaryResourceFor(state, type, jobId);
  }
  cacheSecondaryResource(state, type, jobId, payload);
  return cachedSecondaryResourceFor(state, type, jobId);
}

export function syncCurrentJobSnapshot(state, job, jobId, {
  startedAt = "",
  finishedAt = "",
} = {}) {
  state.currentJobSnapshot = job;
  state.currentJobId = jobId;
  state.currentJobStartedAt = `${startedAt || ""}`.trim();
  state.currentJobFinishedAt = `${finishedAt || ""}`.trim();
}

export function clearCurrentJobTiming(state) {
  state.currentJobStartedAt = "";
  state.currentJobFinishedAt = "";
}

export function cacheJobDiagnostics(state, jobId, payload) {
  state.currentJobDiagnostics = payload;
  state.currentJobDiagnosticsJobId = `${jobId || ""}`.trim();
}

export function cacheJobResumePlan(state, jobId, payload) {
  state.currentJobResumePlan = payload;
  state.currentJobResumePlanJobId = `${jobId || ""}`.trim();
}

export async function fetchAllJobEvents({ fetchJobEvents, apiPrefix, jobId }) {
  const items = [];
  let offset = 0;
  while (true) {
    const payload = await fetchJobEvents(jobId, apiPrefix, JOB_EVENTS_PAGE_SIZE, offset);
    const batch = Array.isArray(payload?.items) ? payload.items : [];
    items.push(...batch);
    if (batch.length < JOB_EVENTS_PAGE_SIZE) {
      return {
        ...payload,
        items,
        offset: 0,
        limit: items.length,
      };
    }
    offset += batch.length;
  }
}

export async function fetchRecentJobEvents({ fetchJobEvents, apiPrefix, jobId }) {
  return await fetchJobEvents(jobId, apiPrefix, JOB_EVENTS_PREVIEW_PAGE_SIZE, 0);
}

export function cachedEventsFor(state, jobId) {
  return state.currentJobEventsJobId === jobId ? state.currentJobEvents : null;
}

export function cachedManifestFor(state, jobId) {
  return state.currentJobManifestJobId === jobId ? state.currentJobManifest : null;
}

export function cachedStageActionsFor(state, jobId) {
  return state.currentJobStageActionsJobId === jobId ? state.currentJobStageActions : null;
}

export function shouldRefreshSecondary(lastFetchedAt, refreshMs, force) {
  if (force) {
    return true;
  }
  if (!Number.isFinite(lastFetchedAt) || lastFetchedAt <= 0) {
    return true;
  }
  return (Date.now() - lastFetchedAt) >= refreshMs;
}
