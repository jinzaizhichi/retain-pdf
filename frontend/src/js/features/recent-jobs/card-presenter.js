import { escapeAttribute, truncateRecentJobName } from "./formatting.js";

export function recentJobStatusLabel(status) {
  switch (`${status || ""}`.trim()) {
    case "queued":
      return "排队中";
    case "running":
      return "进行中";
    case "succeeded":
      return "已完成";
    case "failed":
      return "失败";
    case "canceled":
      return "已取消";
    default:
      return status || "-";
  }
}

export function recentJobStageLabel(item) {
  const stage = `${item?.stage || item?.stage_detail || ""}`.trim().toLowerCase();
  if (stage.includes("ocr")) {
    return "OCR 中";
  }
  if (stage.includes("translat") || stage.includes("翻译")) {
    return "翻译中";
  }
  if (stage.includes("render") || stage.includes("渲染")) {
    return "渲染中";
  }
  if (`${item?.status || ""}`.trim() === "queued") {
    return "排队中";
  }
  return "处理中";
}

export function recentJobProgressPercent(item) {
  const percent = Number(item?.progress?.percent);
  if (Number.isFinite(percent)) {
    return Math.max(0, Math.min(100, percent));
  }
  const current = Number(item?.progress?.current);
  const total = Number(item?.progress?.total);
  if (Number.isFinite(current) && Number.isFinite(total) && total > 0) {
    return Math.max(0, Math.min(100, (current / total) * 100));
  }
  return NaN;
}

export function isRecentJobActive(item) {
  const status = `${item?.status || ""}`.trim();
  if (status === "queued" || status === "running") {
    return true;
  }
  if (status === "succeeded" || status === "failed" || status === "canceled") {
    return false;
  }
  const percent = recentJobProgressPercent(item);
  return Number.isFinite(percent) && percent > 0 && percent < 100;
}

export function recentJobTitle(item) {
  return truncateRecentJobName(item.title || item.display_name || item.source_file_name || item.job_id || "-");
}

export function recentJobImageUrl(item) {
  const direct = `${item?.thumbnail_url || item?.cover_url || ""}`.trim();
  if (direct) {
    return escapeAttribute(direct);
  }
  const jobId = `${item?.job_id || ""}`.trim();
  return jobId ? `/api/v1/library/books/${encodeURIComponent(jobId)}/thumbnail` : "";
}

export function buildReaderUrl(item) {
  const jobId = `${item?.job_id || ""}`.trim();
  return jobId ? `./reader.html?job_id=${encodeURIComponent(jobId)}` : "#";
}
