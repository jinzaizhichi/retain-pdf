import { state } from "./state/store.js";
import { currentJobFinishedAt } from "./features/job-runtime/runtime-state.js";
import {
  formatEventTimestamp,
  formatRuntimeDuration,
  isTerminalStatus,
} from "./job.js";

export function escapeHtml(value) {
  return `${value ?? ""}`
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function parseIsoTime(value) {
  const raw = `${value || ""}`.trim();
  if (!raw) {
    return null;
  }
  const parsed = new Date(raw);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function clampPositiveMs(value) {
  const num = Number(value);
  if (!Number.isFinite(num) || num < 0) {
    return null;
  }
  return num;
}

export function summarizeStageName(stage, detail) {
  const detailText = `${detail || ""}`.trim();
  if (detailText) {
    return detailText;
  }
  const normalizedStage = `${stage || ""}`.trim().toLowerCase();
  if (
    normalizedStage.includes("upload")
    || normalizedStage.includes("submit")
    || normalizedStage.includes("queued")
  ) {
    return "上传 PDF";
  }
  if (
    normalizedStage.includes("ocr_processing")
    || normalizedStage.includes("ocr")
    || normalizedStage.includes("mineru")
    || normalizedStage.includes("paddle")
    || normalizedStage.includes("parsing")
    || normalizedStage.includes("normalization")
    || normalizedStage.includes("normaliz")
  ) {
    return "云端 OCR / 标准化";
  }
  if (
    normalizedStage.includes("translation_prepare")
    || normalizedStage.includes("continuation_review")
    || normalizedStage.includes("page_policies")
    || normalizedStage.includes("garbled")
    || normalizedStage.includes("translat")
  ) {
    return "翻译准备 / 跨栏跨页判断";
  }
  if (
    normalizedStage.includes("render")
    || normalizedStage.includes("saving")
    || normalizedStage.includes("compile")
    || normalizedStage.includes("overlay")
  ) {
    return "渲染 PDF";
  }
  switch (normalizedStage) {
    case "queued":
      return "排队中";
    case "running":
      return "处理中";
    case "translating":
      return "翻译";
    case "parsing":
    case "ocr":
      return "解析 / OCR";
    case "translation_prepare":
      return "翻译准备";
    case "rendering":
      return "渲染";
    case "succeeded":
      return "已完成";
    case "failed":
      return "失败";
    default:
      return `${stage || "-"}`.trim() || "-";
  }
}

function latestStageHistoryEntry(job) {
  const history = Array.isArray(job?.stage_history) ? job.stage_history : [];
  if (history.length === 0) {
    return null;
  }
  return history[history.length - 1] || null;
}

export function resolveLiveDurations(job) {
  if (!job) {
    return {
      stageElapsedText: "-",
      totalElapsedText: "-",
    };
  }

  const status = job.status || "";
  const terminal = isTerminalStatus(status);
  const updatedAt = parseIsoTime(job.updated_at);
  const finishedAt = parseIsoTime(job.finished_at || currentJobFinishedAt(state));
  const now = terminal ? finishedAt || updatedAt || new Date() : new Date();
  const stageStartedAt = parseIsoTime(job.stage_started_at || job.last_stage_transition_at);
  const jobStartedAt = parseIsoTime(job.started_at || job.created_at);
  const latestStage = latestStageHistoryEntry(job);
  const snapshotDeltaMs = !terminal && updatedAt
    ? Math.max(0, now.getTime() - updatedAt.getTime())
    : 0;

  let stageElapsedMs = clampPositiveMs(job.active_stage_elapsed_ms);
  let totalElapsedMs = clampPositiveMs(job.total_elapsed_ms);

  if (terminal) {
    if (stageElapsedMs === null) {
      stageElapsedMs = clampPositiveMs(latestStage?.duration_ms);
    }
    if (totalElapsedMs === null && jobStartedAt) {
      totalElapsedMs = Math.max(0, now.getTime() - jobStartedAt.getTime());
    }
  } else {
    if (stageElapsedMs !== null) {
      stageElapsedMs += snapshotDeltaMs;
    } else if (stageStartedAt) {
      stageElapsedMs = Math.max(0, now.getTime() - stageStartedAt.getTime());
    } else if (clampPositiveMs(latestStage?.duration_ms) !== null) {
      stageElapsedMs = clampPositiveMs(latestStage?.duration_ms) + snapshotDeltaMs;
    }

    if (totalElapsedMs !== null) {
      totalElapsedMs += snapshotDeltaMs;
    } else if (jobStartedAt) {
      totalElapsedMs = Math.max(0, now.getTime() - jobStartedAt.getTime());
    }
  }

  return {
    stageElapsedText: formatRuntimeDuration(stageElapsedMs),
    totalElapsedText: formatRuntimeDuration(totalElapsedMs),
  };
}

export function resolveStageHistoryDuration(entry, job) {
  const explicitDuration = clampPositiveMs(entry?.duration_ms);
  if (explicitDuration !== null) {
    return explicitDuration;
  }
  const enterAt = parseIsoTime(entry?.enter_at);
  const exitAt = parseIsoTime(entry?.exit_at);
  if (enterAt && exitAt) {
    return Math.max(0, exitAt.getTime() - enterAt.getTime());
  }
  if (enterAt && !exitAt) {
    const status = job.status || "";
    const terminal = isTerminalStatus(status);
    const endAt = terminal
      ? parseIsoTime(job.finished_at || currentJobFinishedAt(state) || job.updated_at)
      : new Date();
    if (endAt) {
      return Math.max(0, endAt.getTime() - enterAt.getTime());
    }
  }
  return null;
}

export function resolveStageHistory(job) {
  const directHistory = Array.isArray(job?.stage_history) ? job.stage_history : [];
  return directHistory
    .map((entry, index) => ({ entry, index }))
    .sort((left, right) => {
      const leftEnterAt = parseIsoTime(left.entry?.enter_at)?.getTime() ?? Number.MAX_SAFE_INTEGER;
      const rightEnterAt = parseIsoTime(right.entry?.enter_at)?.getTime() ?? Number.MAX_SAFE_INTEGER;
      if (leftEnterAt !== rightEnterAt) {
        return leftEnterAt - rightEnterAt;
      }
      const leftExitAt = parseIsoTime(left.entry?.exit_at)?.getTime() ?? Number.MAX_SAFE_INTEGER;
      const rightExitAt = parseIsoTime(right.entry?.exit_at)?.getTime() ?? Number.MAX_SAFE_INTEGER;
      if (leftExitAt !== rightExitAt) {
        return leftExitAt - rightExitAt;
      }
      return left.index - right.index;
    })
    .map(({ entry }) => entry);
}

export { formatEventTimestamp, formatRuntimeDuration, isTerminalStatus };
