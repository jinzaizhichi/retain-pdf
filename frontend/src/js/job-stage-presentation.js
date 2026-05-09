import {
  summarizeStageDetail,
  summarizeStageKey,
  summarizeStageLabel,
  summarizeStageProgressText,
} from "./job.js";

function stageRank(stageKey) {
  return {
    queued: 0,
    ocr: 1,
    translate: 2,
    render: 3,
    done: 4,
  }[stageKey] ?? 0;
}

function keepForwardStageKey(job, eventPayload) {
  const jobStageKey = summarizeStageKey(job);
  const eventStageKey = summarizeStageKey(eventPayload);
  return stageRank(eventStageKey) >= stageRank(jobStageKey) ? eventStageKey : jobStageKey;
}

function latestStageEvent(job, eventsPayload) {
  const items = Array.isArray(eventsPayload?.items) ? eventsPayload.items : [];
  const currentStage = `${job?.current_stage || job?.stage || ""}`.trim();
  const currentStageKey = summarizeStageKey(job);
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const item = items[index] || {};
    const itemStage = `${item.stage || ""}`.trim();
    if (!itemStage) {
      continue;
    }
    const itemPayload = {
      ...job,
      current_stage: itemStage,
      stage_detail: item.stage_detail || item.message || "",
    };
    if (currentStage && itemStage !== currentStage && summarizeStageKey(itemPayload) !== currentStageKey) {
      continue;
    }
    if (!item.stage_detail && !item.message && !Number.isFinite(Number(item.progress_current))) {
      continue;
    }
    return item;
  }
  return null;
}

export function resolveDisplayedStagePresentation(job, eventsPayload) {
  const fallback = {
    stageKey: summarizeStageKey(job),
    label: summarizeStageLabel(job),
    detail: summarizeStageDetail(job),
    progressText: summarizeStageProgressText(job),
    progressCurrent: job?.progress_current,
    progressTotal: job?.progress_total,
  };
  const event = latestStageEvent(job, eventsPayload);
  if (!event) {
    return fallback;
  }
  const eventPayload = {
    ...job,
    status: job.status,
    current_stage: event.stage || job.current_stage || job.stage || "",
    stage_detail: event.stage_detail || event.message || job.stage_detail || "",
    progress_current: Number.isFinite(Number(event.progress_current)) ? Number(event.progress_current) : job.progress_current,
    progress_total: Number.isFinite(Number(event.progress_total)) ? Number(event.progress_total) : job.progress_total,
  };
  const stageKey = keepForwardStageKey(job, eventPayload);
  return {
    stageKey,
    label: stageKey === summarizeStageKey(eventPayload) ? summarizeStageLabel(eventPayload) : summarizeStageLabel(job),
    detail: summarizeStageDetail(eventPayload),
    progressText: summarizeStageProgressText(eventPayload),
    progressCurrent: eventPayload.progress_current,
    progressTotal: eventPayload.progress_total,
  };
}
