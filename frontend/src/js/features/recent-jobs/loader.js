import {
  HOME_LOADING_STATES,
  setHomeRecentJobsLoadingState,
} from "../home/state.js";
import {
  hasActiveRecentJobs,
} from "./active-refresh.js";
import {
  collectRecentJobsPage,
  dedupeRecentJobs,
  RECENT_JOBS_PAGE_SIZE,
} from "./pagination.js";
import {
  getRecentJobsState,
  resetRecentJobsPagination,
  setRecentJobsHasMore,
  setRecentJobsItems,
  setRecentJobsOffset,
} from "./state.js";
import {
  hasRecentJobsView,
  renderRecentJobsEmpty,
  renderRecentJobsError,
  renderRecentJobsList,
  renderRecentJobsLoading,
  setRecentJobsLoadMoreLoading,
} from "./view.js";

export function createRecentJobsLoader({
  fetchJobList,
  fetchLibraryBookList,
  apiPrefix,
  getQuery,
  recentJobActions,
  runtimePatches,
  activeRefreshLoop,
  scheduleAutoLoadIfNeeded,
}) {
  let loading = false;
  let pendingLoad = null;

  function isLoading() {
    return loading;
  }

  async function load({ reset = false, silent = false, query = getQuery?.() || "" } = {}) {
    if (loading) {
      pendingLoad = {
        reset: reset || Boolean(pendingLoad?.reset),
        silent: silent && pendingLoad?.silent !== false,
        query,
      };
      return;
    }
    if (!hasRecentJobsView()) {
      return;
    }
    loading = true;
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
      } = await collectRecentJobsPage({
        fetchJobList,
        fetchLibraryBookList,
        apiPrefix,
        startOffset: reset ? 0 : offset,
        pageSize: RECENT_JOBS_PAGE_SIZE,
        existingJobIds,
        query,
      });

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

      const nextItems = runtimePatches.apply(dedupeRecentJobs(reset ? collected : [...previousItems, ...collected]));
      const renderItems = reset
        ? nextItems
        : runtimePatches.apply(collected);
      setRecentJobsOffset(nextOffset);
      setRecentJobsHasMore(hasMore);
      setRecentJobsItems(nextItems);
      if (hasActiveRecentJobs(nextItems)) {
        activeRefreshLoop()?.schedule();
      } else {
        activeRefreshLoop()?.stop();
      }
      if (reset) {
        recentJobActions.recoverActiveJob(nextItems);
      }
      renderRecentJobsList({
        items: renderItems,
        allItems: nextItems,
        invocationSummary: latestInvocationSummary,
        reset,
        hasMore,
        onSelect: recentJobActions.selectJob,
        onDelete: recentJobActions.deleteJob,
        onReader: recentJobActions.openJobReader,
      });
      if (hasMore && !`${query || ""}`.trim()) {
        window.setTimeout(() => scheduleAutoLoadIfNeeded?.(), 0);
      }
      setHomeRecentJobsLoadingState(HOME_LOADING_STATES.READY);
    } catch (err) {
      if (!reset) {
        setRecentJobsHasMore(false);
      }
      setHomeRecentJobsLoadingState(HOME_LOADING_STATES.ERROR, err.message || "读取最近任务失败");
      renderRecentJobsError(err.message || "读取最近任务失败", { reset });
    } finally {
      loading = false;
      if (pendingLoad) {
        const nextLoad = pendingLoad;
        pendingLoad = null;
        window.setTimeout(() => {
          void load(nextLoad);
        }, 0);
      }
    }
  }

  return {
    isLoading,
    load,
  };
}
