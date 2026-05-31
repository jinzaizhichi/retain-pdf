import {
  setHomeRecentJobsLoadingState as setGlobalHomeRecentJobsLoadingState,
  setHomeViewMode as setGlobalHomeViewMode,
  state,
} from "../../state.js";
import {
  HOME_LOADING_STATES,
  HOME_VIEW_MODES,
} from "../../state/home-state.js";

export { HOME_LOADING_STATES, HOME_VIEW_MODES };

export function setHomeViewMode(mode) {
  setGlobalHomeViewMode(state, mode);
  document.dispatchEvent(new CustomEvent("retainpdf:home-view-mode-changed", {
    detail: { mode: state.homeViewMode },
  }));
}

export function setHomeRecentJobsLoadingState(loadingState, error = "") {
  setGlobalHomeRecentJobsLoadingState(state, loadingState, error);
  document.dispatchEvent(new CustomEvent("retainpdf:home-recent-jobs-state-changed", {
    detail: {
      loadingState: state.homeRecentJobsLoadingState,
      error: state.homeRecentJobsError,
    },
  }));
}

export function getHomeState() {
  return {
    viewMode: state.homeViewMode,
    recentJobsLoadingState: state.homeRecentJobsLoadingState,
    recentJobsError: state.homeRecentJobsError,
  };
}
