import { normalizeJobPayload } from "./job.js";
import {
  currentJobId,
  syncCurrentJobSnapshot,
  syncSecondaryResource,
} from "./features/job-runtime/runtime-state.js";

function resolveElapsedStart(job) {
  return (job?.started_at || job?.created_at || "").trim();
}

function syncEventsPayload(state, jobId, eventsPayload) {
  return syncSecondaryResource(state, "events", jobId, eventsPayload);
}

function syncManifestPayload(state, jobId, manifestPayload) {
  return syncSecondaryResource(state, "manifest", jobId, manifestPayload);
}

function syncStageActionsPayload(state, jobId, stageActionsPayload) {
  return syncSecondaryResource(state, "stageActions", jobId, stageActionsPayload);
}

export function syncJobRenderCache({
  state,
  payload,
  eventsPayload = null,
  manifestPayload = null,
  stageActionsPayload = null,
}) {
  const job = normalizeJobPayload(payload);
  const jobId = job.job_id || currentJobId(state);
  syncCurrentJobSnapshot(state, job, jobId, {
    startedAt: resolveElapsedStart(job),
    finishedAt: job.finished_at || job.updated_at || "",
  });
  return {
    job,
    jobId,
    events: syncEventsPayload(state, jobId, eventsPayload),
    manifest: syncManifestPayload(state, jobId, manifestPayload),
    stageActions: syncStageActionsPayload(state, jobId, stageActionsPayload),
  };
}
