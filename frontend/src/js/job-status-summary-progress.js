import {
  firstNonEmpty,
  looksLikeProviderPercentProgress,
  numberOrNull,
  progressFromText,
} from "./job-status-summary-helpers.js";
import { progressUnitOf } from "./job-stage-presentation-utils.js";
import { stageKeyOf, stageSubtypeOf, userStageFor } from "./job-status-summary-stage.js";

export function summarizeStageProgressText(payload) {
  const rawCurrent = numberOrNull(payload.progress_current ?? payload.progress?.current);
  const rawTotal = numberOrNull(payload.progress_total ?? payload.progress?.total);
  const textProgress = progressFromText(payload);
  const current = (rawCurrent === null || (rawCurrent === 0 && Number.isFinite(textProgress.current) && textProgress.current > 0))
    ? textProgress.current
    : rawCurrent;
  const total = rawTotal === null ? textProgress.total : rawTotal;
  if (current === null || total === null || total <= 0) {
    return "";
  }
  const stageKey = stageKeyOf(payload);
  const subtype = stageSubtypeOf(payload);
  const stage = userStageFor(payload);
  const progressUnit = progressUnitOf(payload) || firstNonEmpty(payload.progress_unit, payload.payload?.progress_unit).toLowerCase();
  if (stage.key === "render" && subtype === "render_compile") {
    return `编译 ${current}/${total}`;
  }
  if (stage.key === "render" && subtype === "render_prewarm") {
    return `预热 ${current}/${total}`;
  }
  if (stage.key === "render" && subtype === "render_prepare") {
    return `准备 ${current}/${total}`;
  }
  if (progressUnit === "page") {
    if (stage.key === "ocr" && current <= 0) {
      return `OCR 处理中，共 ${total} 页`;
    }
    if (stage.key === "render" && current <= 0) {
      return `正在渲染，共 ${total} 页`;
    }
    if (stage.key === "render" && current >= total) {
      return `渲染完成，共 ${total} 页`;
    }
    return `第 ${current}/${total} 页`;
  }
  if (progressUnit === "batch") {
    return `第 ${current}/${total} 批`;
  }
  if (progressUnit === "step") {
    if (stage.key === "render") {
      return `准备 ${current}/${total}`;
    }
    return `进度 ${current}/${total}`;
  }
  if (progressUnit === "percent") {
    return current > 0 ? `进度 ${current}%` : "处理中";
  }
  if (subtype === "continuation_review" || subtype === "page_policies") {
    return `第 ${current}/${total} 页`;
  }
  if (subtype === "domain_inference" || subtype === "translation_prepare") {
    return `进度 ${current}/${total}`;
  }
  if (stage.key === "translate") {
    return `第 ${current}/${total} 批`;
  }
  if (stage.key === "ocr") {
    if (looksLikeProviderPercentProgress(current, total)) {
      return current > 0 ? `OCR ${current}%` : "OCR 处理中";
    }
    return `第 ${current}/${total} 页`;
  }
  if (stage.key === "render") {
    return `第 ${current}/${total} 页`;
  }
  return `进度 ${current}/${total}`;
}
