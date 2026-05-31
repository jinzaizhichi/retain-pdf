import { $ } from "../../dom.js";

export function applyHomeViewMode(mode) {
  $("app-shell")?.setAttribute("data-home-view-mode", mode || "library");
}

export function bindHomeStateView() {
  document.addEventListener("retainpdf:home-view-mode-changed", (event) => {
    applyHomeViewMode(event.detail?.mode);
  });
}
