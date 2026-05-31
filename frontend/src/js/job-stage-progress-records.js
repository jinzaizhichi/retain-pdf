import {
  summarizeStageKey,
  summarizeStageProgressText,
  stageSubtypeOf,
} from "./job-status-summary.js";
import {
  rawStageOfPayload,
  visualStageKeyForRawStage,
} from "./job-stage-contract.js";
import {
  compareProgressEventOrder,
  canonicalStageOf,
  eventIdentity,
  normalizeUserStage,
  progressUnitOf,
  progressUnitPriority,
} from "./job-stage-presentation-utils.js";
import {
  progressFromEvent,
  progressPercentFromEvent,
} from "./job-stage-event-progress.js";
import { compositeRenderProgressFromEvents } from "./job-stage-render-progress.js";
import { eventLooksLikeRender } from "./job-stage-render-detection.js";

export function stagePayloadFromEvent(job, item, progress) {
  const canonicalStage = canonicalStageOf(item);
  const userStage = canonicalStage || normalizeUserStage(item?.user_stage || item?.payload?.user_stage || "");
  const rawStage = item?.stage || item?.provider_stage || userStage;
  return {
    ...job,
    status: item?.status || "running",
    user_stage: userStage,
    current_stage: rawStage,
    stage: item?.stage || "",
    substage: item?.substage || item?.payload?.substage || "",
    stage_detail: item?.stage_detail || item?.message || item?.payload?.stage_detail || "",
    progress_unit: progressUnitOf(item),
    progress_current: progress.current,
    progress_total: progress.total,
  };
}

export function visualStageKeyForEventPayload(payload = {}, stageKey = "") {
  const substage = `${payload?.substage || payload?.payload?.substage || ""}`.trim().toLowerCase();
  if (stageKey === "ocr" && substage) {
    if (substage.includes("upload") || substage.includes("submitting") || substage.includes("submit")) {
      return "ocr_upload";
    }
    if (substage.includes("processing") || substage.includes("recogn") || substage.includes("running")) {
      return "ocr_processing";
    }
    if (substage.includes("result")) {
      return "ocr_result_ready";
    }
    if (substage.includes("normaliz") || substage.includes("standard")) {
      return "ocr_normalizing";
    }
  }
  return visualStageKeyForRawStage(rawStageOfPayload(payload), stageKey);
}

export function shouldReplaceStageProgress(previous, next) {
  if (!previous) {
    return true;
  }
  if (
    next.current > 0
    && next.total > 0
    && next.current >= next.total
    && (next.progressUnit === "page" || next.progressUnit === "none" || next.visualStageKey === "ocr_result_ready")
  ) {
    return true;
  }
  const previousPriority = progressUnitPriority(previous.progressUnit);
  const nextPriority = progressUnitPriority(next.progressUnit);
  if (nextPriority !== previousPriority) {
    return nextPriority > previousPriority;
  }
  return true;
}

export function shouldReplaceCurrentStageProgress(previous, next) {
  if (!previous) {
    return true;
  }
  const previousSeq = Number(previous.seq);
  const nextSeq = Number(next.seq);
  if (Number.isFinite(previousSeq) && Number.isFinite(nextSeq) && nextSeq !== previousSeq) {
    return nextSeq > previousSeq;
  }
  const previousTs = Date.parse(previous.ts || "");
  const nextTs = Date.parse(next.ts || "");
  if (Number.isFinite(previousTs) && Number.isFinite(nextTs) && nextTs !== previousTs) {
    return nextTs > previousTs;
  }
  return true;
}

export function normalizeProgressRecord(job, item, itemStage) {
  const progress = progressFromEvent(item);
  const progressPercent = progressPercentFromEvent(item);
  if (
    (progress.current === null || progress.total === null || progress.total <= 0)
    && progressPercent === null
  ) {
    return null;
  }
  const stageForPayload = eventLooksLikeRender(item) ? "rendering" : itemStage;
  const payload = stagePayloadFromEvent(job, { ...item, stage: stageForPayload }, progress);
  const stageKey = summarizeStageKey(payload);
  if (!["ocr", "translate", "render"].includes(stageKey)) {
    return null;
  }
  const displayPayload = { ...payload };
  const visualStageKey = visualStageKeyForEventPayload(displayPayload, stageKey);
  const substageKey = stageSubtypeOf(displayPayload);
  const identity = eventIdentity(item);
  return {
    item,
    payload: displayPayload,
    stageKey,
    current: progress.current,
    total: progress.total,
    progressPercent,
    progressUnit: displayPayload.progress_unit,
    progressText: summarizeStageProgressText(displayPayload),
    visualStageKey,
    substageKey,
    indeterminate: stageKey === "ocr" && progress.current <= 0 && progress.total > 0,
    seq: identity.seq,
    ts: item?.ts || item?.created_at,
  };
}

function itemStageForProgress(item) {
  return `${item?.stage || item?.provider_stage || normalizeUserStage(item?.user_stage || item?.payload?.user_stage) || ""}`.trim();
}

export function collectLatestCurrentStageProgress(job, eventsPayload, stageKey = "", substageKey = "") {
  if (stageKey === "render") {
    return compositeRenderProgressFromEvents(job, eventsPayload, {
      normalizeProgressRecord,
      shouldReplaceCurrentStageProgress,
    });
  }
  const items = Array.isArray(eventsPayload?.items) ? eventsPayload.items : [];
  let latest = null;
  let latestSameSubstage = null;
  for (const item of items) {
    const itemStage = itemStageForProgress(item);
    if (!itemStage) {
      continue;
    }
    const next = normalizeProgressRecord(job, item, itemStage);
    if (!next || next.stageKey !== stageKey) {
      continue;
    }
    if (shouldReplaceCurrentStageProgress(latest, next)) {
      latest = next;
    }
    if (substageKey && next.substageKey === substageKey && shouldReplaceCurrentStageProgress(latestSameSubstage, next)) {
      latestSameSubstage = next;
    }
  }
  return latestSameSubstage || latest;
}

export function collectStageProgressByKey(job, eventsPayload) {
  const items = Array.isArray(eventsPayload?.items) ? eventsPayload.items : [];
  const progressByKey = {};
  const progressBySubstage = {};
  for (const item of items) {
    const itemStage = itemStageForProgress(item);
    if (!itemStage) {
      continue;
    }
    const nextProgress = normalizeProgressRecord(job, item, itemStage);
    if (!nextProgress) {
      continue;
    }
    const { stageKey, substageKey } = nextProgress;
    if (shouldReplaceStageProgress(progressByKey[stageKey], nextProgress)) {
      progressByKey[stageKey] = nextProgress;
    }
    if (stageKey === "translate" && substageKey) {
      const bySubstage = progressBySubstage[stageKey] || {};
      if (compareProgressEventOrder(bySubstage[substageKey], nextProgress) >= 0) {
        bySubstage[substageKey] = nextProgress;
      }
      progressBySubstage[stageKey] = bySubstage;
    }
  }
  Object.entries(progressBySubstage).forEach(([stageKey, bySubstage]) => {
    progressByKey[stageKey] = {
      ...progressByKey[stageKey],
      bySubstage,
    };
  });
  const renderCompositeProgress = compositeRenderProgressFromEvents(job, eventsPayload, {
    fallbackProgress: progressByKey.render,
    normalizeProgressRecord,
    shouldReplaceCurrentStageProgress,
  });
  if (renderCompositeProgress) {
    progressByKey.render = renderCompositeProgress;
  }
  return progressByKey;
}
