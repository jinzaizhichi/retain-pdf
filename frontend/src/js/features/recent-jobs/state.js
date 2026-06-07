import { resetRecentJobsListState } from "../../state/actions.js";
import { state } from "../../state/store.js";

export function getRecentJobsState() {
  return {
    offset: state.recentJobsOffset,
    hasMore: state.recentJobsHasMore,
    items: state.recentJobsItems,
  };
}

export function setRecentJobsOffset(value) {
  state.recentJobsOffset = Number(value) || 0;
}

export function setRecentJobsHasMore(value) {
  state.recentJobsHasMore = Boolean(value);
}

export function setRecentJobsItems(items) {
  state.recentJobsItems = Array.isArray(items) ? items : [];
}

export function resetRecentJobsPagination() {
  resetRecentJobsListState(state);
}
