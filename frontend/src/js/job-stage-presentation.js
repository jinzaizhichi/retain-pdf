import {
  summarizeStageDetail,
  summarizeStageKey,
  summarizeStageLabel,
  summarizeStageProgressText,
  stageSubtypeOf,
} from "./job-status-summary.js";
import {
  rawStageOfPayload,
  visualStageKeyForRawStage,
} from "./job-stage-contract.js";
import {
  normalizeUserStage,
  progressUnitOf,
} from "./job-stage-presentation-utils.js";
import {
  progressFromEvent,
} from "./job-stage-event-progress.js";
import {
  keepForwardStageKey,
  latestStageEvent,
} from "./job-stage-event-selection.js";
import {
  collectLatestCurrentStageProgress,
  collectStageProgressByKey,
  visualStageKeyForEventPayload,
} from "./job-stage-progress-records.js";
import {
  jobProgress,
  jobProgressRecord,
  shouldPreferJobProgress,
  stageFallbackProgress,
} from "./job-stage-job-progress.js";

function translationSubstageKeyFromTextPayload(payload = {}) {
  if (stageKeyOfPayload(payload) !== "translate") {
    return "";
  }
  return stageSubtypeOf(payload);
}

function stageKeyOfPayload(payload = {}) {
  return summarizeStageKey(payload);
}

export { collectStageProgressByKey };

function stageProgressMatches(stageKey, eventPayload) {
  return Boolean(stageKey) && summarizeStageKey(eventPayload) === stageKey;
}

function visualStageKeyFor(job = {}, stageKey = "") {
  const substage = `${job?.substage || job?.payload?.substage || ""}`.trim().toLowerCase();
  if (stageKey === "ocr" && substage) {
    return visualStageKeyForEventPayload(job, stageKey);
  }
  return visualStageKeyForRawStage(rawStageOfPayload(job), stageKey);
}

export function resolveDisplayedStagePresentation(job, eventsPayload) {
  const fallbackProgress = jobProgress(job);
  const fallbackStageKey = summarizeStageKey(job);
  const stageFallback = stageFallbackProgress(fallbackStageKey, job);
  const fallback = {
    stageKey: fallbackStageKey,
    visualStageKey: visualStageKeyFor(job, fallbackStageKey),
    label: summarizeStageLabel(job),
    detail: summarizeStageDetail(job),
    progressText: summarizeStageProgressText(job) || stageFallback?.text || "",
    progressCurrent: fallbackProgress.current ?? stageFallback?.current ?? null,
    progressTotal: fallbackProgress.total ?? stageFallback?.total ?? null,
    substageKey: stageSubtypeOf(job),
    progressIndeterminate: fallbackProgress.current === null && fallbackProgress.total === null && Boolean(stageFallback),
  };
  const event = latestStageEvent(job, eventsPayload);
  if (!event) {
    return fallback;
  }
  const eventProgress = progressFromEvent(event);
  const rawEventPayload = {
    ...job,
    status: job.status,
    user_stage: normalizeUserStage(event.user_stage || event.payload?.user_stage || ""),
    current_stage: event.stage || event.provider_stage || normalizeUserStage(event.user_stage || event.payload?.user_stage) || job.current_stage || job.stage || "",
    substage: event.substage || event.payload?.substage || "",
    stage_detail: event.stage_detail || event.message || event.payload?.stage_detail || job.stage_detail || "",
    progress_unit: progressUnitOf(event),
    progress_current: eventProgress.current,
    progress_total: eventProgress.total,
  };
  const eventMatchesCurrentStage = stageProgressMatches(fallback.stageKey, rawEventPayload);
  const progress = {
    current: eventProgress.current ?? (eventMatchesCurrentStage ? fallbackProgress.current : null),
    total: eventProgress.total ?? (eventMatchesCurrentStage ? fallbackProgress.total : null),
  };
  const eventPayload = {
    ...rawEventPayload,
    progress_current: progress.current ?? stageFallback?.current ?? null,
    progress_total: progress.total ?? stageFallback?.total ?? null,
  };
  const eventProgressText = summarizeStageProgressText(eventPayload);
  const stageKey = keepForwardStageKey(job, eventPayload, eventsPayload);
  const eventSubstageKey = translationSubstageKeyFromTextPayload(eventPayload) || stageSubtypeOf(eventPayload);
  let latestCurrentProgress = collectLatestCurrentStageProgress(job, eventsPayload, stageKey, eventSubstageKey);
  if (shouldPreferJobProgress(job, stageKey, latestCurrentProgress)) {
    latestCurrentProgress = jobProgressRecord(job, stageKey);
  }
  const latestProgressPayload = latestCurrentProgress
    ? {
        ...latestCurrentProgress.payload,
        progress_unit: latestCurrentProgress.progressUnit || latestCurrentProgress.payload?.progress_unit || "",
        progress_current: latestCurrentProgress.current,
        progress_total: latestCurrentProgress.total,
      }
    : null;
  const currentProgressText = latestCurrentProgress?.progressText
    || (latestProgressPayload ? summarizeStageProgressText(latestProgressPayload) : eventProgressText);
  const currentVisualPayload = latestProgressPayload || eventPayload;
  const currentSubstagePayload = latestProgressPayload || eventPayload;
  const currentProgressIndeterminate = latestCurrentProgress
    ? (
        latestCurrentProgress.total !== null
        && (
          (stageKey === "ocr" && latestCurrentProgress.current === null)
          || (stageKey === "render" && latestCurrentProgress.current === 0)
        )
      )
    : eventProgress.current === null && eventProgress.total === null && Boolean(stageFallback);
  return {
    stageKey,
    visualStageKey: visualStageKeyFor(currentVisualPayload, stageKey),
    label: stageKey === summarizeStageKey(eventPayload) ? summarizeStageLabel(eventPayload) : summarizeStageLabel(job),
    detail: summarizeStageDetail(eventPayload),
    progressText: currentProgressText || stageFallback?.text || "",
    progressCurrent: latestCurrentProgress?.current ?? eventPayload.progress_current,
    progressTotal: latestCurrentProgress?.total ?? eventPayload.progress_total,
    progressPercent: latestCurrentProgress?.progressPercent ?? null,
    progressUnit: latestCurrentProgress?.progressUnit || eventPayload.progress_unit || "",
    substageKey: stageSubtypeOf(currentSubstagePayload),
    progressIndeterminate: currentProgressIndeterminate,
  };
}
