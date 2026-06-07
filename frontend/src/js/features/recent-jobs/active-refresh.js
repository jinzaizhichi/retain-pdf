import { isRecentJobActive } from "./card-presenter.js";

export const LIBRARY_ACTIVE_REFRESH_MS = 2500;

export function hasActiveRecentJobs(items = []) {
  return (Array.isArray(items) ? items : []).some(isRecentJobActive);
}

export function createActiveLibraryRefreshLoop({
  getItems,
  fetchJobPayload,
  apiPrefix,
  updateFromRuntime,
  loadRecentJobs,
  isRecentJobsLoading,
}) {
  let activeLibraryRefreshTimer = null;

  function stop() {
    window.clearTimeout(activeLibraryRefreshTimer);
    activeLibraryRefreshTimer = null;
  }

  async function refreshActiveRecentJobDetails() {
    if (!fetchJobPayload) {
      return;
    }
    const activeItems = getItems().filter(isRecentJobActive).slice(0, 6);
    await Promise.allSettled(activeItems.map(async (item) => {
      const jobId = `${item?.job_id || ""}`.trim();
      if (!jobId) {
        return;
      }
      const payload = await fetchJobPayload(jobId, apiPrefix);
      updateFromRuntime(payload);
    }));
  }

  function schedule({ resetTimer = true } = {}) {
    if (resetTimer) {
      stop();
    }
    if (activeLibraryRefreshTimer) {
      return;
    }
    if (!hasActiveRecentJobs(getItems())) {
      return;
    }
    activeLibraryRefreshTimer = window.setTimeout(() => {
      activeLibraryRefreshTimer = null;
      if (isRecentJobsLoading()) {
        schedule();
        return;
      }
      void refreshActiveRecentJobDetails()
        .then(() => loadRecentJobs({ reset: true, silent: true }))
        .finally(() => {
          schedule();
        });
    }, LIBRARY_ACTIVE_REFRESH_MS);
  }

  return {
    schedule,
    stop,
  };
}
