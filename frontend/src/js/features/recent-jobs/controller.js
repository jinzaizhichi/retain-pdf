import { createRecentJobActions } from "./actions.js";
import {
  createActiveLibraryRefreshLoop,
} from "./active-refresh.js";
import { createRecentJobsLoader } from "./loader.js";
import { createRecentJobsRefreshScheduler } from "./refresh-scheduler.js";
import { createRecentJobsRuntimePatches } from "./runtime-patches.js";
import {
  getRecentJobsState,
} from "./state.js";
import {
  bindRecentJobsEvents,
  renderRecentJobsEmpty,
  renderRecentJobsError,
  renderRecentJobsList,
  replaceRecentJobCard,
  scheduleRecentJobsAutoLoadCheck,
  setRecentJobsDialogOpen,
} from "./view.js";

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
  let recentJobsLoader = null;
  let refreshScheduler = null;
  let activeRefreshLoop = null;
  const runtimePatches = createRecentJobsRuntimePatches({
    renderCurrentRecentJobs,
    replaceRecentJobCard,
    scheduleActiveRefresh: (options) => activeRefreshLoop?.schedule(options),
  });
  activeRefreshLoop = createActiveLibraryRefreshLoop({
    getItems: () => getRecentJobsState().items,
    fetchJobPayload,
    apiPrefix,
    updateFromRuntime: runtimePatches.update,
    loadRecentJobs,
    isRecentJobsLoading: () => recentJobsLoader?.isLoading?.() || false,
  });

  function renderCurrentRecentJobs({ reset = true, invocationSummary = null } = {}) {
    const { items, hasMore } = getRecentJobsState();
    renderRecentJobsList({
      items,
      allItems: items,
      invocationSummary,
      reset,
      hasMore,
      onSelect: recentJobActions.selectJob,
      onDelete: recentJobActions.deleteJob,
      onReader: recentJobActions.openJobReader,
    });
  }

  const recentJobActions = createRecentJobActions({
    apiPrefix,
    deleteLibraryBook,
    startPolling,
    openReader,
    currentJobId,
    closeRecentJobsDialog: () => refreshScheduler?.closeDialog?.(),
    renderCurrentRecentJobs,
    renderRecentJobsEmpty,
    renderRecentJobsError,
  });

  function loadRecentJobs(options) {
    return recentJobsLoader?.load(options);
  }

  recentJobsLoader = createRecentJobsLoader({
    fetchJobList,
    fetchLibraryBookList,
    apiPrefix,
    getQuery: () => refreshScheduler?.getQuery?.() || "",
    recentJobActions,
    runtimePatches,
    activeRefreshLoop: () => activeRefreshLoop,
    scheduleAutoLoadIfNeeded: () => refreshScheduler?.scheduleAutoLoadIfNeeded(),
  });

  refreshScheduler = createRecentJobsRefreshScheduler({
    loadRecentJobs,
    scheduleAutoLoadCheck: scheduleRecentJobsAutoLoadCheck,
    setDialogOpen: setRecentJobsDialogOpen,
  });

  bindRecentJobsEvents({
    onOpen: refreshScheduler.openDialog,
    onLoadMore: () => loadRecentJobs({ reset: false }),
    onSearch: refreshScheduler.updateSearch,
    isSuspended: refreshScheduler.isSuspended,
  });
  document.addEventListener("retainpdf:library-refresh-requested", (event) => {
    refreshScheduler.scheduleRefresh({ delay: Number(event.detail?.delay ?? 600) });
  });
  document.addEventListener("retainpdf:library-job-updated", (event) => {
    runtimePatches.update(event.detail?.job);
  });
  document.addEventListener("retainpdf:library-job-created", (event) => {
    runtimePatches.insert(event.detail?.job);
    refreshScheduler.scheduleRefresh({ delay: 1200, force: true });
  });
  document.addEventListener("retainpdf:status-area-visibility-changed", () => {
    refreshScheduler.setSuspended(refreshScheduler.isSuspended());
  });
  document.addEventListener("retainpdf:open-translation-workflow", () => {
    refreshScheduler.setSuspended(true);
  });
  document.addEventListener("retainpdf:close-translation-workflow", () => {
    refreshScheduler.setSuspended(false);
    refreshScheduler.scheduleRefresh({ delay: 300 });
  });
  refreshScheduler.initialize();

  return {
    openRecentJobsDialog: refreshScheduler.openDialog,
    closeRecentJobsDialog: refreshScheduler.closeDialog,
    loadRecentJobs,
    initializeLibraryView: refreshScheduler.initialize,
  };
}
