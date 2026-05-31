import {
  summarizeStageKey,
  stageSubtypeOf,
} from "./job-status-summary.js";
import { eventLooksLikeRender } from "./job-stage-render-detection.js";
import { progressFromEvent } from "./job-stage-event-progress.js";
import { canonicalStageOf, normalizeUserStage, stageRank } from "./job-stage-presentation-utils.js";

function strongestStageKey(...payloads) {
  return payloads
    .map((payload) => summarizeStageKey(payload || {}))
    .filter(Boolean)
    .reduce((best, key) => stageRank(key) > stageRank(best) ? key : best, "");
}

export function keepForwardStageKey(job, eventPayload, eventsPayload) {
  const jobStageKey = strongestStageKey(job, eventsPayload?.live_stage);
  const eventStageKey = summarizeStageKey(eventPayload);
  return stageRank(eventStageKey) >= stageRank(jobStageKey) ? eventStageKey : jobStageKey;
}

export function latestStageEvent(job, eventsPayload) {
  const items = Array.isArray(eventsPayload?.items) ? eventsPayload.items : [];
  const currentStage = `${job?.current_stage || job?.stage || ""}`.trim();
  const currentStageKey = summarizeStageKey(job);
  const payloadForItem = (item = {}) => {
    const itemStage = `${item.stage || ""}`.trim();
    const providerStage = `${item.provider_stage || ""}`.trim();
    const canonicalStage = canonicalStageOf(item);
    const userStage = canonicalStage || normalizeUserStage(item.user_stage || item.payload?.user_stage || "");
    const itemStageForMatch = canonicalStage || (eventLooksLikeRender(item)
      ? "rendering"
      : itemStage || providerStage || userStage);
    if (!itemStageForMatch) {
      return null;
    }
    const progress = progressFromEvent(item);
    return {
      itemStageForMatch,
      progress,
      payload: {
        ...job,
        current_stage: itemStageForMatch,
        stage_detail: item.stage_detail || item.message || "",
        user_stage: userStage,
        substage: item.substage || item.payload?.substage || "",
        progress_current: progress.current,
        progress_total: progress.total,
      },
    };
  };
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const item = items[index] || {};
    const candidate = payloadForItem(item);
    if (!candidate) {
      continue;
    }
    const itemStageKey = summarizeStageKey(candidate.payload);
    if (stageRank(itemStageKey) <= stageRank(currentStageKey)) {
      continue;
    }
    if (!item.stage_detail && !item.message && candidate.progress.current === null) {
      continue;
    }
    return item;
  }
  const findMatchingEvent = (allowBroadStage, requireProgress = false) => {
    for (let index = items.length - 1; index >= 0; index -= 1) {
      const item = items[index] || {};
      const candidate = payloadForItem(item);
      if (!candidate) {
        continue;
      }
      const { itemStageForMatch, progress, payload: itemPayload } = candidate;
      if (requireProgress && (progress.current === null || progress.total === null)) {
        continue;
      }
      const itemStageKey = summarizeStageKey(itemPayload);
      if (currentStage) {
        const exactMatch = itemStageForMatch === currentStage;
        if (!exactMatch && (!allowBroadStage || itemStageKey !== currentStageKey)) {
          continue;
        }
      } else if (currentStageKey && itemStageKey !== currentStageKey) {
        continue;
      }
      if (!item.stage_detail && !item.message && progress.current === null) {
        continue;
      }
      return item;
    }
    return null;
  };
  const exactEvent = findMatchingEvent(false);
  if (currentStageKey === "ocr" || currentStageKey === "translate" || currentStageKey === "render") {
    const desiredSubstageKey = currentStageKey === "translate"
      ? stageSubtypeOf(eventsPayload?.live_stage || job)
      : "";
    if (desiredSubstageKey) {
      for (let index = items.length - 1; index >= 0; index -= 1) {
        const item = items[index] || {};
        const candidate = payloadForItem(item);
        if (!candidate) {
          continue;
        }
        const itemPayload = candidate.payload;
        if (summarizeStageKey(itemPayload) === currentStageKey && stageSubtypeOf(itemPayload) === desiredSubstageKey) {
          return item;
        }
      }
    }
    const broadEvent = findMatchingEvent(true, true) || findMatchingEvent(true);
    if (broadEvent) {
      return broadEvent;
    }
  }
  if (exactEvent) {
    return exactEvent;
  }
  return findMatchingEvent(true);
}
