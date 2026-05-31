import { API_PREFIX } from "./constants.js";
import { mountRecentJobsFeature } from "./features/recent-jobs/controller.js";
import {
  ensureReaderDialogFeature,
  getRequestedJobIdFromLocation,
  getRequestedReaderJobIdFromLocation,
  setText,
} from "./main-helpers.js";

function openReaderWhenStatusActionReady({ attempts = 10, delay = 350 } = {}) {
  const readerButton = document.getElementById("reader-btn");
  if (readerButton && !readerButton.classList.contains("disabled")) {
    readerButton.click();
    return;
  }
  if (attempts <= 0) {
    setText("error-box", "对照阅读暂不可用，请等待任务产物刷新后再试。");
    return;
  }
  window.setTimeout(() => {
    openReaderWhenStatusActionReady({ attempts: attempts - 1, delay });
  }, delay);
}

export function initializeIdleAndRecentJobs({
  appShellFeature,
  fetchJobList,
  fetchJobPayload,
  fetchLibraryBookList,
  deleteLibraryBook,
  jobRuntimeFeature,
}) {
  appShellFeature?.initializeIdleView();
  mountRecentJobsFeature({
    fetchJobList,
    fetchJobPayload,
    fetchLibraryBookList,
    deleteLibraryBook,
    apiPrefix: API_PREFIX,
    startPolling: (jobId) => jobRuntimeFeature?.startPolling(jobId),
    currentJobId: () => jobRuntimeFeature?.currentJobId?.() || "",
    openReader: (jobId) => {
      jobRuntimeFeature?.startPolling(jobId);
      openReaderWhenStatusActionReady();
    },
  });
}

export function bootstrapStartupRoute({
  state,
  fetchProtected,
  jobRuntimeFeature,
  setText,
}) {
  const startupReaderJobId = getRequestedReaderJobIdFromLocation();
  const startupJobId = startupReaderJobId || getRequestedJobIdFromLocation();
  if (startupJobId) {
    jobRuntimeFeature?.startPolling(startupJobId);
  }
  if (!startupReaderJobId) {
    return;
  }
  window.setTimeout(async () => {
    try {
      const feature = await ensureReaderDialogFeature({
        state,
        fetchProtected,
        setText,
      });
      feature.open({ jobId: startupReaderJobId });
    } catch (error) {
      setText("error-box", error.message || String(error));
    }
  }, 0);
}
