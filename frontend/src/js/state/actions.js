import {
  resetDeepSeekBalanceState as resetDeepSeekBalanceStateSlice,
  resetOcrValidationCache as resetOcrValidationCacheSlice,
  resetOcrValidationState as resetOcrValidationStateSlice,
  setDeepSeekBalanceState as setDeepSeekBalanceStateSlice,
  setOcrValidationCache as setOcrValidationCacheSlice,
} from "./credential-state.js";
import {
  resetDeveloperConfig as resetDeveloperConfigSlice,
  setDeveloperConfig as setDeveloperConfigSlice,
} from "./developer-state.js";
import {
  setDesktopConfigured as setDesktopConfiguredSlice,
  setDesktopMode as setDesktopModeSlice,
} from "./desktop-state.js";
import {
  setHomeRecentJobsLoadingState as setHomeRecentJobsLoadingStateSlice,
  setHomeViewMode as setHomeViewModeSlice,
} from "./home-state.js";
import {
  resetJobSecondaryState as resetJobSecondaryStateSlice,
  resetJobState as resetJobStateSlice,
} from "./job-state.js";
import { resetRecentJobsListState as resetRecentJobsListStateSlice } from "./recent-jobs-state.js";
import {
  clearAppliedPageRange as clearAppliedPageRangeSlice,
  setAppliedPageRange as setAppliedPageRangeSlice,
  resetUploadState as resetUploadStateSlice,
  setUploadState as setUploadStateSlice,
} from "./upload-state.js";
import { state } from "./store.js";

export function resetJobState(target = state) {
  resetJobStateSlice(target);
}

export function resetJobSecondaryState(target = state) {
  resetJobSecondaryStateSlice(target);
}

export function resetUploadState(target = state, options = {}) {
  resetUploadStateSlice(target, options);
}

export function setUploadState(target = state, payload = {}) {
  setUploadStateSlice(target, payload);
}

export function setAppliedPageRange(target = state, value = "") {
  setAppliedPageRangeSlice(target, value);
}

export function clearAppliedPageRange(target = state) {
  clearAppliedPageRangeSlice(target);
}

export function resetRecentJobsListState(target = state) {
  resetRecentJobsListStateSlice(target);
}

export function resetOcrValidationState(target = state) {
  resetOcrValidationStateSlice(target);
}

export function resetOcrValidationCache(target = state) {
  resetOcrValidationCacheSlice(target);
}

export function setOcrValidationCache(target = state, payload = {}) {
  setOcrValidationCacheSlice(target, payload);
}

export function resetDeepSeekBalanceState(target = state) {
  resetDeepSeekBalanceStateSlice(target);
}

export function setDeepSeekBalanceState(target = state, balanceCny, checked = true) {
  setDeepSeekBalanceStateSlice(target, balanceCny, checked);
}

export function setDeveloperConfig(target = state, config = {}) {
  setDeveloperConfigSlice(target, config);
}

export function resetDeveloperConfig(target = state) {
  resetDeveloperConfigSlice(target);
}

export function setDesktopMode(target = state, value = true) {
  setDesktopModeSlice(target, value);
}

export function setDesktopConfigured(target = state, value = false) {
  setDesktopConfiguredSlice(target, value);
}

export function setHomeViewMode(target = state, mode) {
  setHomeViewModeSlice(target, mode);
}

export function setHomeRecentJobsLoadingState(target = state, loadingState, error = "") {
  setHomeRecentJobsLoadingStateSlice(target, loadingState, error);
}
