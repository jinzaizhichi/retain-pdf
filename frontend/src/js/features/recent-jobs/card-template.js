import { escapeAttribute, escapeHtml } from "./formatting.js";
import {
  isRecentJobActive,
  recentJobImageUrl,
  recentJobProgressPercent,
  recentJobStageLabel,
  recentJobStatusLabel,
  recentJobTitle,
} from "./card-presenter.js";

function activeOverlayMarkup(item) {
  if (!isRecentJobActive(item)) {
    return "";
  }
  const percent = recentJobProgressPercent(item);
  const percentText = Number.isFinite(percent) ? `${Math.round(percent)}%` : "";
  const width = Number.isFinite(percent) ? `${percent.toFixed(2)}%` : "0%";
  return `
    <div class="recent-job-active-overlay" aria-label="${escapeAttribute(recentJobStageLabel(item))}">
      <span class="recent-job-active-label">${recentJobStageLabel(item)}</span>
      ${percentText ? `<span class="recent-job-active-percent">${percentText}</span>` : ""}
      <span class="recent-job-active-track" aria-hidden="true">
        <span class="recent-job-active-bar" style="width:${width}"></span>
      </span>
    </div>
  `;
}

function hoverActionsMarkup(item) {
  return `
    <div class="recent-job-hover-actions" aria-hidden="true">
      <button type="button" class="recent-job-hover-btn recent-job-reader" title="对照阅读" aria-label="对照阅读">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M2.8 12s3.4-5.8 9.2-5.8S21.2 12 21.2 12s-3.4 5.8-9.2 5.8S2.8 12 2.8 12Z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/>
          <circle cx="12" cy="12" r="2.6" fill="none" stroke="currentColor" stroke-width="1.7"/>
        </svg>
      </button>
    </div>
  `;
}

function deleteControlsMarkup() {
  return `
    <button type="button" class="recent-job-delete" aria-label="删除任务" title="删除">
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M4 7h16M10 11v6M14 11v6M9 7l1-2h4l1 2M6 7l1 14h10l1-14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    </button>
    <div class="recent-job-delete-popover" role="group" aria-label="确认删除">
      <div>删除这本书？</div>
      <div class="recent-job-delete-actions">
        <button type="button" class="recent-job-delete-cancel">取消</button>
        <button type="button" class="recent-job-delete-confirm">删除</button>
      </div>
    </div>
  `;
}

export function recentJobCardMarkup(item) {
  const active = isRecentJobActive(item);
  const title = recentJobTitle(item);
  const pageCount = item.page_count || "-";
  const updatedAt = item.updated_at || "-";
  return `
    <article class="recent-job-item ${active ? "is-active-job" : ""}" role="button" tabindex="0" data-job-id="${escapeAttribute(item.job_id || "")}">
      <div class="recent-job-cover-wrap">
        <div class="recent-job-cover" data-image-url="${recentJobImageUrl(item)}">
          <span class="recent-job-cover-fallback">${escapeHtml(title.slice(0, 1))}</span>
          ${activeOverlayMarkup(item)}
          ${hoverActionsMarkup(item)}
        </div>
        <span class="recent-job-status">${escapeHtml(active ? recentJobStageLabel(item) : recentJobStatusLabel(item.status))}</span>
        ${deleteControlsMarkup()}
      </div>
      <div class="recent-job-title-wrap">
        <span class="recent-job-id" title="${escapeAttribute(item.title || item.display_name || item.job_id || "-")}">${escapeHtml(title)}</span>
        <span class="recent-job-real-id mono">${escapeHtml(pageCount)} 页 · ${escapeHtml(updatedAt)}</span>
      </div>
    </article>
  `;
}
