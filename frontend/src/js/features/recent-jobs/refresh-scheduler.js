const LIBRARY_SEARCH_DEBOUNCE_MS = 260;
const LIBRARY_REFRESH_MIN_INTERVAL_MS = 5000;

function isTranslationWorkflowOpen() {
  return document.getElementById("translation-workflow-dialog")?.dataset.open === "1";
}

export function createRecentJobsRefreshScheduler({
  loadRecentJobs,
  scheduleAutoLoadCheck,
  setDialogOpen,
}) {
  let refreshTimer = null;
  let searchTimer = null;
  let query = "";
  let suspended = false;
  let lastRefreshAt = 0;

  function isSuspended() {
    return suspended || isTranslationWorkflowOpen();
  }

  function getQuery() {
    return query;
  }

  function setSuspended(value) {
    suspended = Boolean(value);
  }

  function scheduleRefresh({ delay = 600, force = false } = {}) {
    if (!force && isSuspended()) {
      return;
    }
    const now = Date.now();
    if (!force && now - lastRefreshAt < LIBRARY_REFRESH_MIN_INTERVAL_MS) {
      return;
    }
    lastRefreshAt = now;
    window.clearTimeout(refreshTimer);
    refreshTimer = window.setTimeout(() => {
      void loadRecentJobs({ reset: true, silent: true });
    }, delay);
  }

  function updateSearch(nextQuery) {
    query = `${nextQuery || ""}`.trim();
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(() => {
      void loadRecentJobs({ reset: true, query });
    }, LIBRARY_SEARCH_DEBOUNCE_MS);
  }

  function openDialog() {
    setDialogOpen(true);
    loadRecentJobs({ reset: true });
  }

  function closeDialog() {
    setDialogOpen(false);
  }

  function initialize() {
    loadRecentJobs({ reset: true });
  }

  function scheduleAutoLoadIfNeeded() {
    scheduleAutoLoadCheck({ isSuspended });
  }

  return {
    closeDialog,
    getQuery,
    initialize,
    isSuspended,
    openDialog,
    scheduleAutoLoadIfNeeded,
    scheduleRefresh,
    setSuspended,
    updateSearch,
  };
}
