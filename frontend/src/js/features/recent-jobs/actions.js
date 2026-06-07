import { resolveRecoverableJobId } from "./active-job-recovery.js";
import {
  getRecentJobsState,
  setRecentJobsItems,
} from "./state.js";

export function createRecentJobActions({
  apiPrefix,
  deleteLibraryBook,
  startPolling,
  openReader,
  currentJobId = () => "",
  closeRecentJobsDialog,
  renderCurrentRecentJobs,
  renderRecentJobsEmpty,
  renderRecentJobsError,
}) {
  let activeJobRecoveryAttempted = false;

  function selectJob(jobId) {
    const normalizedJobId = `${jobId || ""}`.trim();
    if (!normalizedJobId) {
      renderRecentJobsError("该任务缺少 job_id，无法打开。", { reset: false });
      return;
    }
    closeRecentJobsDialog();
    document.dispatchEvent(new CustomEvent("retainpdf:open-translation-workflow"));
    startPolling(normalizedJobId);
  }

  async function deleteJob(jobId) {
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

  function openJobReader(jobId) {
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

  return {
    deleteJob,
    openJobReader,
    recoverActiveJob,
    selectJob,
  };
}
