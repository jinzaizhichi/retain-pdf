import { $ } from "./dom.js";

export function statusAreaElement() {
  return $("status-section");
}

export function statusCardElement() {
  return $("job-status-card") || document.querySelector("job-status-card");
}

export function isStatusAreaVisible() {
  return !statusAreaElement()?.classList.contains("hidden");
}

export function setStatusAreaVisible(visible) {
  statusAreaElement()?.classList.toggle("hidden", !visible);
  statusCardElement()?.classList.toggle("hidden", !visible);
  document.dispatchEvent(new CustomEvent("retainpdf:status-area-visibility-changed"));
}

export function dispatchReturnHomeFromStatusArea() {
  const target = $("back-home-btn") || statusCardElement() || statusAreaElement();
  target?.dispatchEvent(new CustomEvent("retainpdf:return-home", { bubbles: true }));
}
