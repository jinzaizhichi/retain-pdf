import { $ } from "../../dom.js";
import { hydrateRecentJobImages } from "../../components/dialogs/recent-jobs-dialog-rendering.js";
import { bindRecentJobsListEvents } from "./list-events.js";
import { buildRecentJobsMarkup } from "./card-markup.js";
import { recentJobCardMarkup } from "./card-template.js";

function byId(root, id) {
  return root?.querySelector?.(`#${id}`);
}

function recentJobsRoot() {
  return document.querySelector("#library-view") || document;
}

function recentJobsDialogComponent() {
  if (isLibraryMainViewMounted()) {
    return null;
  }
  return document.querySelector("recent-jobs-dialog");
}

function isLibraryMainViewMounted() {
  return Boolean(document.querySelector("#library-view #recent-jobs-list"));
}

export function hasRecentJobsView() {
  if (isLibraryMainViewMounted()) {
    return true;
  }
  const component = recentJobsDialogComponent();
  if (component) {
    return true;
  }
  const root = recentJobsRoot();
  return Boolean(byId(root, "recent-jobs-list") && byId(root, "recent-jobs-empty") && byId(root, "load-more-jobs-btn"));
}

export function setRecentJobsDialogOpen(open) {
  const component = recentJobsDialogComponent();
  if (component?.setOpen) {
    component.setOpen(open);
  } else {
    const dialog = $("query-dialog");
    if (!dialog) {
      return;
    }
    if (open) {
      dialog.showModal();
    } else {
      dialog.close();
    }
  }
  $("open-query-btn")?.setAttribute("aria-expanded", open ? "true" : "false");
}

export function bindRecentJobsEvents({
  onOpen,
  onLoadMore,
  onSearch,
  isSuspended = () => false,
} = {}) {
  $("open-query-btn")?.addEventListener("click", () => onOpen?.());
  $("library-search-input")?.addEventListener("input", (event) => {
    onSearch?.(event.target?.value || "");
  });
  byId(recentJobsRoot(), "recent-jobs-scroll-body")?.addEventListener("scroll", () => {
    if (isSuspended?.()) {
      return;
    }
    scheduleRecentJobsAutoLoadCheck();
  }, { passive: true });

  const component = recentJobsDialogComponent();
  if (component?.bindEvents && !isLibraryMainViewMounted()) {
    component.bindEvents({ onLoadMore });
    return;
  }

  byId(recentJobsRoot(), "load-more-jobs-btn")?.addEventListener("click", () => onLoadMore?.());
}

export function scheduleRecentJobsAutoLoadCheck({ isSuspended = () => false } = {}) {
  const component = recentJobsDialogComponent();
  if (component?.scheduleAutoLoadCheck) {
    component.scheduleAutoLoadCheck();
    return;
  }
  window.requestAnimationFrame(() => {
    if (isSuspended?.()) {
      return;
    }
    const root = recentJobsRoot();
    const body = byId(root, "recent-jobs-scroll-body");
    const loadMoreButton = byId(root, "load-more-jobs-btn");
    if (!body || !loadMoreButton || loadMoreButton.classList.contains("hidden") || loadMoreButton.disabled) {
      return;
    }
    const remaining = body.scrollHeight - body.scrollTop - body.clientHeight;
    if (remaining < Math.max(260, body.clientHeight * 0.35)) {
      loadMoreButton.click();
    }
  });
}

function summarizeInvocationCounts(items) {
  let stageSpecCount = 0;
  let unknownCount = 0;
  for (const item of Array.isArray(items) ? items : []) {
    const protocol = `${item?.invocation?.input_protocol || ""}`.trim();
    if (protocol === "stage_spec") {
      stageSpecCount += 1;
    } else {
      unknownCount += 1;
    }
  }
  return { stageSpecCount, unknownCount };
}

export function renderRecentJobsSummary(invocationSummary, items) {
  const stageSpecCountValue = Number(invocationSummary?.stage_spec_count);
  const unknownCountValue = Number(invocationSummary?.unknown_count);
  const counts = Number.isFinite(stageSpecCountValue) && Number.isFinite(unknownCountValue)
    ? { stageSpecCount: stageSpecCountValue, unknownCount: unknownCountValue }
    : summarizeInvocationCounts(items);
  const text = `Stage Spec ${counts.stageSpecCount} · Unknown ${counts.unknownCount}`;
  const component = recentJobsDialogComponent();
  if (component?.renderSummary) {
    component.renderSummary(text);
    return;
  }
  const summaryEl = byId(recentJobsRoot(), "recent-jobs-summary");
  if (summaryEl) {
    summaryEl.textContent = text;
  }
}

export function renderRecentJobsLoading() {
  const component = recentJobsDialogComponent();
  if (component?.renderLoading) {
    component.renderLoading();
    return;
  }
  const root = recentJobsRoot();
  const list = byId(root, "recent-jobs-list");
  const empty = byId(root, "recent-jobs-empty");
  const loadMoreButton = byId(root, "load-more-jobs-btn");
  if (!list || !empty || !loadMoreButton) {
    return;
  }
  empty.classList.add("hidden");
  list.classList.remove("hidden");
  list.innerHTML = '<div class="events-empty">正在加载最近任务…</div>';
  loadMoreButton.classList.add("hidden");
}

export function renderRecentJobsEmpty(message, invocationSummary = null) {
  const component = recentJobsDialogComponent();
  const root = recentJobsRoot();
  const list = byId(root, "recent-jobs-list");
  const empty = byId(root, "recent-jobs-empty");
  const loadMoreButton = byId(root, "load-more-jobs-btn");
  if (!component?.renderEmpty && (!list || !empty || !loadMoreButton)) {
    return;
  }
  renderRecentJobsSummary(invocationSummary, []);
  if (component?.renderEmpty) {
    component.renderEmpty(message);
    return;
  }
  list.innerHTML = "";
  list.classList.add("hidden");
  empty.textContent = message || "暂无最近任务";
  empty.classList.remove("hidden");
  loadMoreButton.classList.add("hidden");
  loadMoreButton.disabled = false;
  loadMoreButton.textContent = "更多";
}

export function renderRecentJobsError(message, { reset = false } = {}) {
  const component = recentJobsDialogComponent();
  if (component?.renderError) {
    component.renderError(message, { reset });
    return;
  }
  const root = recentJobsRoot();
  const list = byId(root, "recent-jobs-list");
  const empty = byId(root, "recent-jobs-empty");
  const loadMoreButton = byId(root, "load-more-jobs-btn");
  if (!list || !empty || !loadMoreButton) {
    return;
  }
  if (reset) {
    list.innerHTML = "";
    list.classList.add("hidden");
    empty.textContent = message || "读取最近任务失败";
    empty.classList.remove("hidden");
  } else {
    loadMoreButton.classList.add("hidden");
  }
  loadMoreButton.disabled = false;
  loadMoreButton.textContent = "更多";
}

export function renderRecentJobsList({
  items,
  allItems,
  invocationSummary,
  reset = false,
  hasMore = false,
  onSelect,
  onDelete,
  onReader,
}) {
  const component = recentJobsDialogComponent();
  const root = recentJobsRoot();
  const list = byId(root, "recent-jobs-list");
  const empty = byId(root, "recent-jobs-empty");
  const loadMoreButton = byId(root, "load-more-jobs-btn");
  if (!component?.renderList && (!list || !empty || !loadMoreButton)) {
    return;
  }
  renderRecentJobsSummary(invocationSummary, allItems);
  const markup = buildRecentJobsMarkup(items);
  if (component?.renderList) {
    component.renderList(markup, { reset, hasMore, onSelect, onDelete, onReader });
    return;
  }
  list.classList.remove("hidden");
  empty.classList.add("hidden");
  list.__retainPdfRecentJobSelect = onSelect;
  list.__retainPdfRecentJobDelete = onDelete;
  list.__retainPdfRecentJobReader = onReader;
  bindRecentJobsListEvents(list);
  list.innerHTML = reset ? markup : `${list.innerHTML}${markup}`;
  hydrateRecentJobImages(list);
  loadMoreButton.classList.toggle("hidden", !hasMore);
  loadMoreButton.disabled = false;
  loadMoreButton.textContent = "更多";
}

export function replaceRecentJobCard(item) {
  const jobId = `${item?.job_id || ""}`.trim();
  if (!jobId) {
    return false;
  }
  const root = recentJobsRoot();
  const list = byId(root, "recent-jobs-list");
  const previous = Array.from(list?.querySelectorAll?.(".recent-job-item") || [])
    .find((node) => `${node.dataset?.jobId || ""}`.trim() === jobId);
  if (!list || !previous) {
    return false;
  }
  const template = document.createElement("template");
  template.innerHTML = recentJobCardMarkup(item).trim();
  const next = template.content.firstElementChild;
  if (!next) {
    return false;
  }
  previous.replaceWith(next);
  hydrateRecentJobImages(next);
  return true;
}

export function setRecentJobsLoadMoreLoading() {
  const component = recentJobsDialogComponent();
  if (component?.setLoadMoreLoading) {
    component.setLoadMoreLoading();
    return;
  }
  const loadMoreButton = byId(recentJobsRoot(), "load-more-jobs-btn");
  if (!loadMoreButton) {
    return;
  }
  loadMoreButton.disabled = true;
  loadMoreButton.textContent = "加载中…";
}
