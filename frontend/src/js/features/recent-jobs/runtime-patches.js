import { isRecentJobActive } from "./card-presenter.js";
import {
  createLibraryJobItemFromRuntime,
  mergeLibraryJobItem,
  mergeRuntimePatches,
} from "./runtime-item.js";
import {
  dedupeRecentJobs,
} from "./pagination.js";
import {
  getRecentJobsState,
  setRecentJobsHasMore,
  setRecentJobsItems,
} from "./state.js";

export function createRecentJobsRuntimePatches({
  renderCurrentRecentJobs,
  replaceRecentJobCard,
  scheduleActiveRefresh,
}) {
  const runtimeJobPatches = new Map();

  function apply(items) {
    return mergeRuntimePatches(items, runtimeJobPatches);
  }

  function update(job) {
    const jobId = `${job?.job_id || ""}`.trim();
    if (!jobId) {
      return;
    }
    runtimeJobPatches.set(jobId, job);
    const state = getRecentJobsState();
    const index = state.items.findIndex((item) => `${item?.job_id || ""}`.trim() === jobId);
    if (index < 0) {
      if (isRecentJobActive(job)) {
        insert(job);
      }
      return;
    }
    const nextItems = [...state.items];
    const nextItem = mergeLibraryJobItem(nextItems[index], job);
    nextItems[index] = nextItem;
    setRecentJobsItems(nextItems);
    replaceRecentJobCard(nextItem);
    scheduleActiveRefresh?.({ resetTimer: false });
  }

  function insert(job) {
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
    scheduleActiveRefresh?.({ resetTimer: false });
  }

  return {
    apply,
    insert,
    update,
  };
}
