import { getHomeState, setHomeViewMode } from "./state.js";
import { bindHomeStateView, applyHomeViewMode } from "./view.js";

export function mountHomeFeature() {
  function bindEvents() {
    bindHomeStateView();
    applyHomeViewMode(getHomeState().viewMode);
  }

  return {
    bindEvents,
    setViewMode: setHomeViewMode,
  };
}
