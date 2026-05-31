import { $ } from "../../dom.js";
import { initializeIdleAppView } from "./idle-reset.js";
import {
  bindDialogBackdropClose,
  bindInfoBubbles,
  bindUploadTilePicker,
  resetEventsList,
} from "./view.js";

export function mountAppShellFeature({
  isMockMode,
  prepareFilePicker,
  setText,
  setWorkflowSections,
  setLinearProgress,
  updateActionButtons,
  renderPageRangeSummary,
  resetUploadProgress,
  resetUploadedFile,
  applyWorkflowMode,
  updateJobWarning,
  activateDetailTab,
  translationWorkflowDialogFeature,
}) {
  function bindChrome() {
    [
      "query-dialog",
      "developer-auth-dialog",
      "developer-dialog",
      "glossary-manager-dialog",
      "browser-credentials-dialog",
      "page-range-dialog",
    "status-detail-dialog",
    "reader-dialog",
    ].forEach(bindDialogBackdropClose);
    bindInfoBubbles();
    bindUploadTilePicker(prepareFilePicker);
    translationWorkflowDialogFeature?.bindEvents();
  }

  function initializeIdleView() {
    initializeIdleAppView({
      isMockMode,
      setText,
      setWorkflowSections,
      setLinearProgress,
      updateActionButtons,
      renderPageRangeSummary,
      resetUploadProgress,
      resetUploadedFile,
      applyWorkflowMode,
      updateJobWarning,
      resetEventsList,
      activateDetailTab,
    });
  }

  return {
    bindChrome,
    initializeIdleView,
  };
}
