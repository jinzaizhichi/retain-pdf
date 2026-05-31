import { isMockMode } from "../config.js";
import { mountAppUpdateFeature } from "../features/app-update/controller.js";
import { mountAppShellFeature } from "../features/app-shell/controller.js";
import { mountHomeFeature } from "../features/home/controller.js";
import { mountTranslationWorkflowDialogFeature } from "../features/translation-workflow-dialog/controller.js";
import { setText } from "../main-helpers.js";
import {
  prepareFilePicker,
  renderJob,
  resetUploadProgress,
  resetUploadedFile,
  setLinearProgress,
  setWorkflowSections,
  updateActionButtons,
  updateJobWarning,
} from "../ui.js";

export function mountCoreFeatures(features) {
  features.homeFeature = mountHomeFeature();
  features.appUpdateFeature = mountAppUpdateFeature();
  features.translationWorkflowDialogFeature = mountTranslationWorkflowDialogFeature();
  features.appShellFeature = mountAppShellFeature({
    isMockMode,
    prepareFilePicker,
    setText,
    setWorkflowSections,
    setLinearProgress,
    updateActionButtons,
    renderPageRangeSummary: () => features.uploadFeature?.renderPageRangeSummary(),
    resetUploadProgress,
    resetUploadedFile,
    applyWorkflowMode: () => features.workflowFeature?.applyWorkflowMode(),
    updateJobWarning,
    activateDetailTab: (name) => features.statusDetailFeature?.activateDetailTab(name),
    translationWorkflowDialogFeature: features.translationWorkflowDialogFeature,
  });
}

export const coreUiDependencies = {
  renderJob,
  resetUploadProgress,
  resetUploadedFile,
  setText,
  setWorkflowSections,
  updateJobWarning,
};
