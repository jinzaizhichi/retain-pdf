export const HOME_VIEW_MODES = Object.freeze({
  LIBRARY: "library",
  WORKFLOW_UPLOAD: "workflow_upload",
  WORKFLOW_STATUS: "workflow_status",
});

export const HOME_LOADING_STATES = Object.freeze({
  IDLE: "idle",
  LOADING: "loading",
  READY: "ready",
  ERROR: "error",
});

export function createHomeState() {
  return {
    homeViewMode: HOME_VIEW_MODES.LIBRARY,
    homeRecentJobsLoadingState: HOME_LOADING_STATES.IDLE,
    homeRecentJobsError: "",
    lastLibraryRefreshRequestedAt: 0,
  };
}

export function setHomeViewMode(target, mode) {
  target.homeViewMode = Object.values(HOME_VIEW_MODES).includes(mode)
    ? mode
    : HOME_VIEW_MODES.LIBRARY;
}

export function setHomeRecentJobsLoadingState(target, loadingState, error = "") {
  target.homeRecentJobsLoadingState = Object.values(HOME_LOADING_STATES).includes(loadingState)
    ? loadingState
    : HOME_LOADING_STATES.IDLE;
  target.homeRecentJobsError = `${error || ""}`;
}
