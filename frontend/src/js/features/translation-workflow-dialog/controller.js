import { $ } from "../../dom.js";
import {
  dispatchReturnHomeFromStatusArea,
  isStatusAreaVisible,
} from "../../status-area-view.js";
import {
  closeTranslationWorkflowDialogView,
  isTranslationWorkflowDialogOpen,
  openTranslationWorkflowDialogView,
  syncTranslationWorkflowDialogMode,
  translationWorkflowDialogElement,
} from "./view.js";

export function mountTranslationWorkflowDialogFeature() {
  function requestClose() {
    if (isStatusAreaVisible()) {
      dispatchReturnHomeFromStatusArea();
      return;
    }
    closeTranslationWorkflowDialogView();
  }

  function bindEvents() {
    document.addEventListener("click", (event) => {
      const trigger = event.target?.closest?.("#library-add-pdf-btn");
      if (!trigger) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      openTranslationWorkflowDialogView();
    });
    document.addEventListener("retainpdf:open-translation-workflow", openTranslationWorkflowDialogView);
    document.addEventListener("retainpdf:close-translation-workflow", closeTranslationWorkflowDialogView);
    document.addEventListener("retainpdf:translation-workflow-sync", syncTranslationWorkflowDialogMode);
    document.addEventListener("retainpdf:status-area-visibility-changed", syncTranslationWorkflowDialogMode);
    translationWorkflowDialogElement()?.addEventListener("click", (event) => {
      if (event.target === translationWorkflowDialogElement()) {
        requestClose();
      }
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && isTranslationWorkflowDialogOpen()) {
        requestClose();
      }
    });
    $("translation-workflow-close-btn")?.addEventListener("click", requestClose);
  }

  return {
    bindEvents,
    close: closeTranslationWorkflowDialogView,
    open: openTranslationWorkflowDialogView,
  };
}
