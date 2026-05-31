import { $ } from "../../dom.js";
import {
  HOME_VIEW_MODES,
  setHomeViewMode,
} from "../home/state.js";
import { isStatusAreaVisible } from "../../status-area-view.js";

export function translationWorkflowDialogElement() {
  return $("translation-workflow-dialog");
}

export function isTranslationWorkflowDialogOpen() {
  return translationWorkflowDialogElement()?.dataset.open === "1";
}

export function syncTranslationWorkflowDialogMode() {
  const dialog = translationWorkflowDialogElement();
  const title = $("translation-workflow-title");
  if (!dialog) {
    return;
  }
  const hasJob = isStatusAreaVisible();
  setHomeViewMode(hasJob ? HOME_VIEW_MODES.WORKFLOW_STATUS : HOME_VIEW_MODES.WORKFLOW_UPLOAD);
  dialog.classList.toggle("is-status-mode", hasJob);
  dialog.classList.toggle("is-upload-mode", !hasJob);
  if (title) {
    title.textContent = hasJob ? "任务进度" : "翻译 PDF";
  }
}

export function openTranslationWorkflowDialogView() {
  const dialog = translationWorkflowDialogElement();
  if (!dialog) {
    return;
  }
  syncTranslationWorkflowDialogMode();
  dialog.classList.remove("hidden");
  dialog.dataset.open = "1";
  document.documentElement.classList.add("translation-workflow-open");
}

export function closeTranslationWorkflowDialogView() {
  const dialog = translationWorkflowDialogElement();
  if (!dialog) {
    return;
  }
  dialog.classList.add("hidden");
  dialog.dataset.open = "0";
  document.documentElement.classList.remove("translation-workflow-open");
  setHomeViewMode(HOME_VIEW_MODES.LIBRARY);
}
