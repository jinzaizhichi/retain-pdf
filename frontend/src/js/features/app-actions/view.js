import { $ } from "../../dom.js";
import { resetUploadState } from "../../state/actions.js";

export function setSubmitBusy(busy) {
  document.dispatchEvent(new CustomEvent("retainpdf:submit-busy-changed", {
    detail: { busy: !!busy },
  }));
  const button = $("submit-btn");
  if (button) {
    button.disabled = !!busy;
    button.dataset.busy = busy ? "1" : "0";
  }
}

export function resetMissingUploadState({ state, resetUploadedFile, setText }) {
  resetUploadState(state, { includePageRange: false });
  resetUploadedFile?.();
  setText("error-box", "当前上传文件已失效，请重新上传 PDF 后再提交。");
}
