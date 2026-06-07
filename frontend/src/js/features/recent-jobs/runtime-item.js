import { firstNonEmpty, isTerminalStatus, numberOrNull } from "../../job-core.js";
import {
  summarizeStageDetail,
  summarizeStageKey,
} from "../../job-status-summary.js";

function progressFromJob(job = {}) {
  const progress = job?.progress && typeof job.progress === "object" ? job.progress : {};
  const current = numberOrNull(progress.current ?? job.progress_current);
  const total = numberOrNull(progress.total ?? job.progress_total);
  let percent = numberOrNull(progress.percent ?? job.progress_percent);
  if (percent === null && current !== null && total !== null && total > 0) {
    percent = Math.max(0, Math.min(100, (current / total) * 100));
  }
  return {
    current,
    total,
    percent,
    unit: firstNonEmpty(progress.unit, job.progress_unit),
  };
}

function isMeaningfulStageKey(value = "") {
  return !["", "idle", "running", "queued"].includes(`${value || ""}`.trim());
}

function valueOrPrevious(value, previousValue) {
  return value === undefined || value === null || value === "" ? previousValue : value;
}

export function mergeLibraryJobItem(previousItem = {}, job = {}) {
  const jobId = firstNonEmpty(job.job_id, previousItem.job_id);
  const stageKey = summarizeStageKey(job);
  const stage = isMeaningfulStageKey(stageKey)
    ? stageKey
    : firstNonEmpty(job.stage, job.current_stage, previousItem.stage);
  const summarizedDetail = summarizeStageDetail(job);
  const stageDetail = summarizedDetail && summarizedDetail !== "等待任务开始"
    ? summarizedDetail
    : firstNonEmpty(job.stage_detail, previousItem.stage_detail);
  const jobProgress = progressFromJob(job);
  const previousProgress = previousItem.progress && typeof previousItem.progress === "object"
    ? previousItem.progress
    : {};
  const progress = {
    ...previousProgress,
    current: valueOrPrevious(jobProgress.current, previousProgress.current),
    total: valueOrPrevious(jobProgress.total, previousProgress.total),
    percent: valueOrPrevious(jobProgress.percent, previousProgress.percent),
    unit: valueOrPrevious(jobProgress.unit, previousProgress.unit),
  };
  if (isTerminalStatus(job.status) && job.status === "succeeded") {
    progress.percent = 100;
    if (progress.total !== undefined && progress.total !== null) {
      progress.current = progress.total;
    }
  } else if (isTerminalStatus(job.status)) {
    progress.percent = valueOrPrevious(jobProgress.percent, previousProgress.percent);
  }
  return {
    ...previousItem,
    job_id: jobId,
    id: previousItem.id || jobId,
    status: firstNonEmpty(job.status, previousItem.status),
    stage,
    stage_detail: stageDetail,
    workflow: firstNonEmpty(job.workflow, job.job_type, previousItem.workflow),
    job_type: firstNonEmpty(job.job_type, job.workflow, previousItem.job_type),
    title: firstNonEmpty(job.title, job.display_name, previousItem.title),
    display_name: firstNonEmpty(job.display_name, job.title, previousItem.display_name),
    source_file_name: firstNonEmpty(job.source_file_name, job.book_summary?.source_file_name, previousItem.source_file_name),
    page_count: valueOrPrevious(numberOrNull(job.page_count ?? job.book_summary?.page_count), previousItem.page_count),
    cover_url: firstNonEmpty(job.cover_url, previousItem.cover_url),
    thumbnail_url: firstNonEmpty(job.thumbnail_url, previousItem.thumbnail_url),
    updated_at: firstNonEmpty(job.updated_at, previousItem.updated_at),
    progress,
  };
}

export function createLibraryJobItemFromRuntime(job = {}) {
  const jobId = firstNonEmpty(job.job_id);
  if (!jobId) {
    return null;
  }
  return mergeLibraryJobItem({
    id: jobId,
    job_id: jobId,
    title: jobId,
    display_name: jobId,
    source_file_name: "",
    page_count: null,
    status: "queued",
    stage: "queued",
    stage_detail: "任务已提交",
    progress: {},
    created_at: job.created_at || new Date().toISOString(),
    updated_at: job.updated_at || new Date().toISOString(),
  }, job);
}

export function mergeRuntimePatches(items, patches) {
  return (Array.isArray(items) ? items : []).map((item) => {
    const jobId = firstNonEmpty(item?.job_id);
    const patch = jobId ? patches.get(jobId) : null;
    return patch ? mergeLibraryJobItem(item, patch) : item;
  });
}
