import {
  HOME_LOADING_STATES,
  setHomeRecentJobsLoadingState,
} from "../home/state.js";
import { resolveRecoverableJobId } from "./active-job-recovery.js";
import {
  createLibraryJobItemFromRuntime,
  mergeLibraryJobItem,
  mergeRuntimePatches,
} from "./runtime-item.js";
import { isRecentJobActive } from "./card-presenter.js";
import {
  getRecentJobsState,
  resetRecentJobsPagination,
  setRecentJobsHasMore,
  setRecentJobsItems,
  setRecentJobsOffset,
} from "./state.js";
import {
  bindRecentJobsEvents,
  hasRecentJobsView,
  renderRecentJobsEmpty,
  renderRecentJobsError,
  renderRecentJobsList,
  replaceRecentJobCard,
  renderRecentJobsLoading,
  scheduleRecentJobsAutoLoadCheck,
  setRecentJobsDialogOpen,
  setRecentJobsLoadMoreLoading,
} from "./view.js";

const RECENT_JOBS_PAGE_SIZE = 24;
const LIBRARY_SEARCH_DEBOUNCE_MS = 260;
const LIBRARY_REFRESH_MIN_INTERVAL_MS = 5000;
const LIBRARY_ACTIVE_REFRESH_MS = 2500;

function dedupeRecentJobs(items) {
  const seen = new Set();
  const result = [];
  for (const item of Array.isArray(items) ? items : []) {
    const jobId = `${item?.job_id || ""}`.trim();
    if (!jobId || seen.has(jobId)) {
      continue;
    }
    seen.add(jobId);
    result.push(item);
  }
  return result;
}

function isPrimaryRecentJob(item) {
  const workflow = `${item?.workflow || item?.job_type || ""}`.trim();
  const jobId = `${item?.job_id || ""}`.trim();
  if (workflow === "ocr") {
    return false;
  }
  if (jobId.endsWith("-ocr")) {
    return false;
  }
  return true;
}


async function collectRecentJobsPage(
  fetchJobList,
  fetchLibraryBookList,
  apiPrefix,
  startOffset,
  pageSize,
  existingJobIds = new Set(),
  query = "",
) {
  const fetchLimit = Math.max(pageSize, 20);
  const collected = [];
  const seenJobIds = new Set(existingJobIds);
  let latestInvocationSummary = null;
  let nextOffset = startOffset;
  let hasMore = true;

  while (collected.length < pageSize) {
    const payload = fetchLibraryBookList
      ? await fetchLibraryBookList(apiPrefix, { limit: fetchLimit, offset: nextOffset, q: query })
      : await fetchJobList(apiPrefix, { limit: fetchLimit, offset: nextOffset, q: query });
    latestInvocationSummary = payload?.invocation_summary || latestInvocationSummary;
    const items = Array.isArray(payload?.items) ? payload.items : [];
    if (items.length === 0) {
      hasMore = false;
      break;
    }

    for (const item of items) {
      if (!isPrimaryRecentJob(item)) {
        continue;
      }
      const jobId = `${item?.job_id || ""}`.trim();
      if (!jobId || seenJobIds.has(jobId)) {
        continue;
      }
      seenJobIds.add(jobId);
      collected.push(item);
      if (collected.length >= pageSize) {
        break;
      }
    }

    nextOffset += fetchLimit;

    if (!hasMore || collected.length >= pageSize) {
      break;
    }
    if (items.length === 0) {
      hasMore = false;
      break;
    }
  }

  return {
    collected,
    hasMore,
    latestInvocationSummary,
    nextOffset,
  };
}

export function mountRecentJobsFeature({
  fetchJobList,
  fetchJobPayload,
  fetchLibraryBookList,
  deleteLibraryBook,
  apiPrefix,
  startPolling,
  openReader,
  currentJobId = () => "",
}) {
  let recentJobsLoading = false;
  let recentJobsRefreshTimer = null;
  let recentJobsSearchTimer = null;
  let recentJobsQuery = "";
  let activeJobRecoveryAttempted = false;
  let librarySuspended = false;
  let lastLibraryRefreshAt = 0;
  let pendingRecentJobsLoad = null;
  let activeLibraryRefreshTimer = null;
  const runtimeJobPatches = new Map();

  function isTranslationWorkflowOpen() {
    return document.getElementById("translation-workflow-dialog")?.dataset.open === "1";
  }

  function isLibrarySuspended() {
    return librarySuspended || isTranslationWorkflowOpen();
  }

  function renderCurrentRecentJobs({ reset = true, invocationSummary = null } = {}) {
    const { items, hasMore } = getRecentJobsState();
    renderRecentJobsList({
      items,
      allItems: items,
      invocationSummary,
      reset,
      hasMore,
      onSelect: handleSelectRecentJob,
      onDelete: handleDeleteRecentJob,
      onReader: handleOpenRecentJobReader,
    });
  }

  function hasActiveRecentJobs(items = getRecentJobsState().items) {
    return (Array.isArray(items) ? items : []).some(isRecentJobActive);
  }

  function stopActiveLibraryRefresh() {
    window.clearTimeout(activeLibraryRefreshTimer);
    activeLibraryRefreshTimer = null;
  }

  async function refreshActiveRecentJobDetails() {
    if (!fetchJobPayload) {
      return;
    }
    const activeItems = getRecentJobsState().items.filter(isRecentJobActive).slice(0, 6);
    await Promise.allSettled(activeItems.map(async (item) => {
      const jobId = `${item?.job_id || ""}`.trim();
      if (!jobId) {
        return;
      }
      const payload = await fetchJobPayload(jobId, apiPrefix);
      updateRecentJobCardFromRuntime(payload);
    }));
  }

  function scheduleActiveLibraryRefresh({ resetTimer = true } = {}) {
    if (resetTimer) {
      stopActiveLibraryRefresh();
    }
    if (activeLibraryRefreshTimer) {
      return;
    }
    if (!hasActiveRecentJobs()) {
      return;
    }
    activeLibraryRefreshTimer = window.setTimeout(() => {
      activeLibraryRefreshTimer = null;
      if (recentJobsLoading) {
        scheduleActiveLibraryRefresh();
        return;
      }
      void refreshActiveRecentJobDetails()
        .then(() => loadRecentJobs({ reset: true, silent: true }))
        .finally(() => {
          scheduleActiveLibraryRefresh();
        });
    }, LIBRARY_ACTIVE_REFRESH_MS);
  }

  function handleSelectRecentJob(jobId) {
    const normalizedJobId = `${jobId || ""}`.trim();
    if (!normalizedJobId) {
      renderRecentJobsError("该任务缺少 job_id，无法打开。", { reset: false });
      return;
    }
    closeRecentJobsDialog();
    document.dispatchEvent(new CustomEvent("retainpdf:open-translation-workflow"));
    startPolling(normalizedJobId);
  }

  async function handleDeleteRecentJob(jobId) {
    const normalizedJobId = `${jobId || ""}`.trim();
    if (!normalizedJobId || !deleteLibraryBook) {
      return;
    }
    try {
      await deleteLibraryBook(apiPrefix, normalizedJobId);
    } catch (error) {
      const message = error?.message || String(error);
      if (message.includes("(409)")) {
        await deleteLibraryBook(apiPrefix, normalizedJobId, { force: true });
      } else {
        renderRecentJobsError(message || "删除失败", { reset: false });
        return;
      }
    }
    const rootJobId = normalizedJobId.replace(/-ocr$/, "");
    const nextItems = getRecentJobsState().items.filter((item) => {
      const itemJobId = `${item?.job_id || ""}`.trim();
      return itemJobId !== rootJobId && itemJobId !== `${rootJobId}-ocr`;
    });
    setRecentJobsItems(nextItems);
    if (nextItems.length === 0) {
      renderRecentJobsEmpty("暂无最近任务");
      return;
    }
    renderCurrentRecentJobs({ reset: true });
  }

  function handleOpenRecentJobReader(jobId) {
    const normalizedJobId = `${jobId || ""}`.trim();
    if (!normalizedJobId) {
      renderRecentJobsError("该任务缺少 job_id，无法打开对照阅读。", { reset: false });
      return;
    }
    closeRecentJobsDialog();
    openReader?.(normalizedJobId);
  }

  function recoverActiveJob(items = []) {
    if (activeJobRecoveryAttempted) {
      return;
    }
    if (`${currentJobId?.() || ""}`.trim()) {
      activeJobRecoveryAttempted = true;
      return;
    }
    activeJobRecoveryAttempted = true;
    const jobId = resolveRecoverableJobId(items);
    if (!jobId) {
      return;
    }
    startPolling(jobId);
  }

  function updateRecentJobCardFromRuntime(job) {
    const jobId = `${job?.job_id || ""}`.trim();
    if (!jobId) {
      return;
    }
    runtimeJobPatches.set(jobId, job);
    const state = getRecentJobsState();
    const index = state.items.findIndex((item) => `${item?.job_id || ""}`.trim() === jobId);
    if (index < 0) {
      if (isRecentJobActive(job)) {
        insertRecentJobCardFromRuntime(job);
      }
      return;
    }
    const nextItems = [...state.items];
    const nextItem = mergeLibraryJobItem(nextItems[index], job);
    nextItems[index] = nextItem;
    setRecentJobsItems(nextItems);
    replaceRecentJobCard(nextItem);
    scheduleActiveLibraryRefresh({ resetTimer: false });
  }

  function insertRecentJobCardFromRuntime(job) {
    const nextItem = createLibraryJobItemFromRuntime(job);
    if (!nextItem) {
      return;
    }
    runtimeJobPatches.set(nextItem.job_id, job);
    const state = getRecentJobsState();
    const nextItems = dedupeRecentJobs([nextItem, ...state.items]);
    setRecentJobsItems(nextItems);
    setRecentJobsHasMore(state.hasMore);
    renderCurrentRecentJobs({ reset: true });
    scheduleActiveLibraryRefresh({ resetTimer: false });
  }

  async function loadRecentJobs({ reset = false, silent = false, query = recentJobsQuery } = {}) {
    if (recentJobsLoading) {
      pendingRecentJobsLoad = {
        reset: reset || Boolean(pendingRecentJobsLoad?.reset),
        silent: silent && pendingRecentJobsLoad?.silent !== false,
        query,
      };
      return;
    }
    if (!hasRecentJobsView()) {
      return;
    }
    recentJobsLoading = true;
    if (!silent) {
      setHomeRecentJobsLoadingState(HOME_LOADING_STATES.LOADING);
    }
    if (reset) {
      resetRecentJobsPagination();
      if (!silent) {
        renderRecentJobsLoading();
      }
    } else {
      setRecentJobsLoadMoreLoading();
    }

    try {
      const { offset, items: previousItems } = getRecentJobsState();
      const existingJobIds = new Set(
        (reset ? [] : previousItems)
          .map((item) => `${item?.job_id || ""}`.trim())
          .filter(Boolean),
      );
      const {
        collected,
        hasMore,
        latestInvocationSummary,
        nextOffset,
      } = await collectRecentJobsPage(
        fetchJobList,
        fetchLibraryBookList,
        apiPrefix,
        reset ? 0 : offset,
        RECENT_JOBS_PAGE_SIZE,
        existingJobIds,
        query,
      );

      if (reset && collected.length === 0) {
        setRecentJobsItems([]);
        setRecentJobsHasMore(false);
        setHomeRecentJobsLoadingState(HOME_LOADING_STATES.READY);
        renderRecentJobsEmpty(`${query || ""}`.trim() ? "没有匹配的书籍" : "暂无最近任务", latestInvocationSummary);
        return;
      }
      if (!reset && collected.length === 0) {
        setRecentJobsHasMore(false);
        setHomeRecentJobsLoadingState(HOME_LOADING_STATES.READY);
        renderRecentJobsError("", { reset: false });
        return;
      }

      const nextItems = mergeRuntimePatches(
        dedupeRecentJobs(reset ? collected : [...previousItems, ...collected]),
        runtimeJobPatches,
      );
      const renderItems = reset
        ? nextItems
        : mergeRuntimePatches(collected, runtimeJobPatches);
      setRecentJobsOffset(nextOffset);
      setRecentJobsHasMore(hasMore);
      setRecentJobsItems(nextItems);
      if (hasActiveRecentJobs(nextItems)) {
        scheduleActiveLibraryRefresh();
      } else {
        stopActiveLibraryRefresh();
      }
      if (reset) {
        recoverActiveJob(nextItems);
      }
      renderRecentJobsList({
        items: renderItems,
        allItems: nextItems,
        invocationSummary: latestInvocationSummary,
        reset,
        hasMore,
        onSelect: handleSelectRecentJob,
        onDelete: handleDeleteRecentJob,
        onReader: handleOpenRecentJobReader,
      });
      if (hasMore && !`${query || ""}`.trim()) {
        window.setTimeout(() => scheduleRecentJobsAutoLoadCheck({ isSuspended: isLibrarySuspended }), 0);
      }
      setHomeRecentJobsLoadingState(HOME_LOADING_STATES.READY);
    } catch (err) {
      if (!reset) {
        setRecentJobsHasMore(false);
      }
      setHomeRecentJobsLoadingState(HOME_LOADING_STATES.ERROR, err.message || "读取最近任务失败");
      renderRecentJobsError(err.message || "读取最近任务失败", { reset });
    } finally {
      recentJobsLoading = false;
      if (pendingRecentJobsLoad) {
        const nextLoad = pendingRecentJobsLoad;
        pendingRecentJobsLoad = null;
        window.setTimeout(() => {
          void loadRecentJobs(nextLoad);
        }, 0);
      }
    }
  }

  function scheduleLibraryRefresh({ delay = 600, force = false } = {}) {
    if (!force && isLibrarySuspended()) {
      return;
    }
    const now = Date.now();
    if (!force && now - lastLibraryRefreshAt < LIBRARY_REFRESH_MIN_INTERVAL_MS) {
      return;
    }
    lastLibraryRefreshAt = now;
    window.clearTimeout(recentJobsRefreshTimer);
    recentJobsRefreshTimer = window.setTimeout(() => {
      void loadRecentJobs({ reset: true, silent: true });
    }, delay);
  }

  function updateLibrarySearch(query) {
    recentJobsQuery = `${query || ""}`.trim();
    window.clearTimeout(recentJobsSearchTimer);
    recentJobsSearchTimer = window.setTimeout(() => {
      void loadRecentJobs({ reset: true, query: recentJobsQuery });
    }, LIBRARY_SEARCH_DEBOUNCE_MS);
  }

  function openRecentJobsDialog() {
    setRecentJobsDialogOpen(true);
    loadRecentJobs({ reset: true });
  }

  function initializeLibraryView() {
    loadRecentJobs({ reset: true });
  }

  function closeRecentJobsDialog() {
    setRecentJobsDialogOpen(false);
  }

  bindRecentJobsEvents({
    onOpen: openRecentJobsDialog,
    onLoadMore: () => loadRecentJobs({ reset: false }),
    onSearch: updateLibrarySearch,
    isSuspended: isLibrarySuspended,
  });
  document.addEventListener("retainpdf:library-refresh-requested", (event) => {
    scheduleLibraryRefresh({ delay: Number(event.detail?.delay ?? 600) });
  });
  document.addEventListener("retainpdf:library-job-updated", (event) => {
    updateRecentJobCardFromRuntime(event.detail?.job);
  });
  document.addEventListener("retainpdf:library-job-created", (event) => {
    insertRecentJobCardFromRuntime(event.detail?.job);
    scheduleLibraryRefresh({ delay: 1200, force: true });
  });
  document.addEventListener("retainpdf:status-area-visibility-changed", () => {
    librarySuspended = isTranslationWorkflowOpen();
  });
  document.addEventListener("retainpdf:open-translation-workflow", () => {
    librarySuspended = true;
  });
  document.addEventListener("retainpdf:close-translation-workflow", () => {
    librarySuspended = false;
    scheduleLibraryRefresh({ delay: 300 });
  });
  initializeLibraryView();

  return {
    openRecentJobsDialog,
    closeRecentJobsDialog,
    loadRecentJobs,
    initializeLibraryView,
  };
}
