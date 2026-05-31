import { normalizeUserStage } from "./job-stage-presentation-utils.js";
import { eventLooksLikeRender } from "./job-stage-render-detection.js";

export function compositeRenderProgressFromEvents(
  job,
  eventsPayload,
  {
    fallbackProgress = null,
    normalizeProgressRecord,
    shouldReplaceCurrentStageProgress,
  } = {},
) {
  const items = Array.isArray(eventsPayload?.items) ? eventsPayload.items : [];
  let latestPrepareProgress = null;
  let latestPrewarmProgress = null;
  let latestPageProgress = null;
  let latestCompileProgress = null;
  for (const item of items) {
    const itemStage = eventLooksLikeRender(item)
      ? "rendering"
      : `${item?.stage || item?.provider_stage || normalizeUserStage(item?.user_stage || item?.payload?.user_stage) || ""}`.trim();
    if (!itemStage) {
      continue;
    }
    const next = normalizeProgressRecord?.(job, item, itemStage);
    if (!next || next.stageKey !== "render") {
      continue;
    }
    if (next.substageKey === "render_prepare" && next.progressUnit === "step" && shouldReplaceCurrentStageProgress(latestPrepareProgress, next)) {
      latestPrepareProgress = next;
    }
    if (next.substageKey === "render_prewarm" && next.progressUnit === "step" && shouldReplaceCurrentStageProgress(latestPrewarmProgress, next)) {
      latestPrewarmProgress = next;
    }
    if (next.progressUnit === "page" && shouldReplaceCurrentStageProgress(latestPageProgress, next)) {
      latestPageProgress = next;
    }
    if (next.substageKey === "render_compile" && next.progressUnit === "step" && shouldReplaceCurrentStageProgress(latestCompileProgress, next)) {
      latestCompileProgress = next;
    }
  }
  const latest = latestCompileProgress || latestPageProgress || latestPrewarmProgress || latestPrepareProgress || fallbackProgress;
  if (!latest) {
    return null;
  }
  if (
    latestCompileProgress
    && latestCompileProgress.current !== null
    && latestCompileProgress.total !== null
    && latestCompileProgress.total > 0
  ) {
    const compileRatio = Math.max(0, Math.min(1, latestCompileProgress.current / latestCompileProgress.total));
    const compileText = `编译 ${latestCompileProgress.current}/${latestCompileProgress.total}`;
    return {
      ...latestCompileProgress,
      current: 80 + Math.round(compileRatio * 20),
      total: 100,
      progressUnit: "percent",
      progressText: compileText,
      payload: {
        ...latestCompileProgress.payload,
        stage_detail: compileText,
        progress_unit: "percent",
      },
      indeterminate: false,
    };
  }
  if (
    latestPageProgress
    && latestPageProgress.current !== null
    && latestPageProgress.total !== null
    && latestPageProgress.total > 0
  ) {
    const pageRatio = Math.max(0, Math.min(1, latestPageProgress.current / latestPageProgress.total));
    return {
      ...latestPageProgress,
      current: 10 + Math.round(pageRatio * 70),
      total: 100,
      progressUnit: "percent",
      progressText: latestPageProgress.progressText,
      payload: {
        ...latestPageProgress.payload,
        progress_unit: "percent",
      },
      indeterminate: latestPageProgress.current <= 0,
    };
  }
  if (
    latestPrewarmProgress
    && latestPrewarmProgress.current !== null
    && latestPrewarmProgress.total !== null
    && latestPrewarmProgress.total > 0
  ) {
    const prewarmRatio = Math.max(0, Math.min(1, latestPrewarmProgress.current / latestPrewarmProgress.total));
    const prewarmText = `预热 ${latestPrewarmProgress.current}/${latestPrewarmProgress.total}`;
    return {
      ...latestPrewarmProgress,
      current: Math.round(prewarmRatio * 10),
      total: 100,
      progressUnit: "percent",
      progressText: prewarmText,
      payload: {
        ...latestPrewarmProgress.payload,
        stage_detail: prewarmText,
        progress_unit: "percent",
      },
      indeterminate: latestPrewarmProgress.current <= 0,
    };
  }
  if (
    latestPrepareProgress
    && latestPrepareProgress.current !== null
    && latestPrepareProgress.total !== null
    && latestPrepareProgress.total > 0
  ) {
    const prepareRatio = Math.max(0, Math.min(1, latestPrepareProgress.current / latestPrepareProgress.total));
    return {
      ...latestPrepareProgress,
      current: Math.round(prepareRatio * 10),
      total: 100,
      progressUnit: "percent",
      progressText: latestPrepareProgress.payload?.stage_detail || latestPrepareProgress.progressText || `准备 ${latestPrepareProgress.current}/${latestPrepareProgress.total}`,
      payload: {
        ...latestPrepareProgress.payload,
        progress_unit: "percent",
      },
      indeterminate: latestPrepareProgress.current <= 0,
    };
  }
  return latest;
}
