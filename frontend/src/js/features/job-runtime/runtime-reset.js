import { summarizeStatus } from "../../job.js";
import { resetJobState } from "../../state.js";
import { resetStatusDetailRuntimeView } from "../app-shell/idle-reset.js";
import { closeRuntimeDialogs, resetEventsList } from "../app-shell/view.js";
import { clearActiveJobId } from "./active-job-storage.js";
import { stopPolling } from "./runtime-state.js";

export function returnJobRuntimeToHome({
  state,
  onReaderDialogClose,
  setWorkflowSections,
  resetUploadProgress,
  resetUploadedFile,
  applyWorkflowMode,
  clearPageRanges,
  setText,
  updateJobWarning,
  activateDetailTab,
}) {
  clearActiveJobId(state.currentJobId);
  stopPolling(state);
  closeRuntimeDialogs();
  onReaderDialogClose?.();
  resetJobState(state);
  state.appliedPageRange = "";
  setWorkflowSections(null);
  resetUploadProgress();
  resetUploadedFile();
  applyWorkflowMode();
  setText("job-summary", summarizeStatus("idle"));
  setText("job-stage-detail", "-");
  setText("job-id", "-");
  setText("query-job-duration", "-");
  setText("job-finished-at", "-");
  clearPageRanges();
  resetStatusDetailRuntimeView({ setText, resetEventsList, activateDetailTab });
  updateJobWarning("idle");
}
