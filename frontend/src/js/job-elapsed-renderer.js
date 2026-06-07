import { isTerminalStatus } from "./job.js";
import {
  currentJobSnapshot,
  startElapsedTimer,
  stopElapsedTimer,
} from "./features/job-runtime/runtime-state.js";
import { resolveLiveDurations } from "./status-detail-utils.js";
import {
  setStatusCardElapsed,
  setTextView,
  statusSectionStatus,
} from "./ui-presentation-view.js";

export function stopElapsedTicker(state) {
  stopElapsedTimer(state);
}

export function renderElapsed(state) {
  const snapshot = currentJobSnapshot(state);
  if (!snapshot) {
    setTextView("query-job-duration", "-");
    setStatusCardElapsed("-");
    return;
  }
  const durations = resolveLiveDurations(snapshot);
  setTextView("query-job-duration", durations.totalElapsedText);
  setStatusCardElapsed(durations.totalElapsedText);
  setTextView("runtime-stage-elapsed", durations.stageElapsedText);
  setTextView("runtime-total-elapsed", durations.totalElapsedText);
}

export function startElapsedTicker(state) {
  stopElapsedTicker(state);
  renderElapsed(state);
  const status = statusSectionStatus();
  if (isTerminalStatus(status)) {
    return;
  }
  startElapsedTimer(state, () => {
    renderElapsed(state);
  }, 1000);
}
