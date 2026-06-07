import { $ } from "../../dom.js";
import { withTimeout } from "../../async-timeout.js";
import { buildApiUrl } from "../../config.js";
import {
  clearAppliedPageRange,
  setAppliedPageRange,
  setUploadState,
} from "../../state/actions.js";
import { getUploadState } from "../../state/upload-state.js";
import {
  clearPageRangeInputs,
  closePageRangeDialog,
  markUploadReady,
  openPageRangeDialogView,
  readPageRangeInputs,
  selectedUploadFile,
  setFileLabel,
  setInlinePageRangeVisible,
  showUploadStatus,
  writePageRangeInputs,
} from "./view.js";

export function mountUploadFeature({
  state,
  apiBase,
  apiPrefix,
  frontMaxBytes,
  frontMaxPageCount,
  countPdfPages,
  defaultFileLabel,
  collectUploadFormData,
  submitUploadRequest,
  resetUploadedFile,
  resetUploadProgress,
  setUploadProgress,
  clearFileInputValue,
  setText,
  applyWorkflowMode,
  refreshSubmitControls,
  refreshDeepSeekBalance,
  workflowNeedsUpload,
}) {
  const BALANCE_CHECK_TIMEOUT_MS = 12000;

  function formatByteLimit(bytes) {
    const mb = Number(bytes) / (1024 * 1024);
    return Number.isFinite(mb) && mb > 0 ? `${Math.round(mb)}MB` : "当前";
  }

  function normalizePageRangeValue(startValue = "", endValue = "") {
    const start = startValue.trim();
    const end = endValue.trim();
    if (!start && !end) {
      return "";
    }
    if (start && end) {
      return start === end ? start : `${start}-${end}`;
    }
    return start || end;
  }

  function currentPageRanges() {
    const { start, end } = readPageRangeInputs();
    return normalizePageRangeValue(start, end);
  }

  function validatePageRanges() {
    const { start: rawStart, end: rawEnd } = readPageRangeInputs();
    const start = rawStart.trim();
    const end = rawEnd.trim();
    const uploadState = getUploadState(state);
    const maxPage = Number(uploadState.uploadedPageCount || 0) || frontMaxPageCount;
    if ((start && Number(start) < 1) || (end && Number(end) < 1)) {
      setText("error-box", "页码必须从 1 开始");
      return false;
    }
    if ((start && maxPage && Number(start) > maxPage) || (end && maxPage && Number(end) > maxPage)) {
      setText("error-box", `页码不能超过 ${maxPage}`);
      return false;
    }
    if (start && end && Number(start) > Number(end)) {
      setText("error-box", "起始页不能大于结束页");
      return false;
    }
    if (maxPage && start && end && Number(end) - Number(start) + 1 > maxPage) {
      setText("error-box", `页码区间不能超过 ${maxPage} 页`);
      return false;
    }
    setAppliedPageRange(state, normalizePageRangeValue(start, end));
    return true;
  }

  function renderPageRangeSummary() {
    const uploadState = getUploadState(state);
    setInlinePageRangeVisible(workflowNeedsUpload() && Boolean(uploadState.uploadId));
  }

  function openPageRangeDialog() {
    const uploadState = getUploadState(state);
    openPageRangeDialogView({
      applied: uploadState.appliedPageRange || "",
      maxPage: frontMaxPageCount || 0,
    });
  }

  function applyPageRanges() {
    closePageRangeDialog();
  }

  function clearPageRanges() {
    clearPageRangeInputs();
    clearAppliedPageRange(state);
    renderPageRangeSummary();
    refreshSubmitControls();
    closePageRangeDialog();
  }

  async function handleFileSelected() {
    const file = selectedUploadFile();
    resetUploadedFile();
    resetUploadProgress();
    clearAppliedPageRange(state);
    clearPageRangeInputs();
    renderPageRangeSummary();
    applyWorkflowMode();
    setFileLabel(file, defaultFileLabel);
    if (!file) {
      return;
    }
    if (file.size > frontMaxBytes) {
      setText("error-box", `当前前端限制为 ${formatByteLimit(frontMaxBytes)} 以内 PDF`);
      showUploadStatus("文件超出大小限制");
      return;
    }
    if (frontMaxPageCount && countPdfPages) {
      showUploadStatus("正在校验页数…");
      try {
        const localPageCount = await countPdfPages(file);
        if (!Number.isFinite(localPageCount) || localPageCount <= 0) {
          setText("error-box", "PDF 解析失败，请检查文件是否损坏或可访问性异常。");
          showUploadStatus("文件校验失败");
          clearFileInputValue();
          return;
        }
        if (localPageCount > frontMaxPageCount) {
          setText("error-box", `PDF 页数超过限制：最多 ${frontMaxPageCount} 页`);
          showUploadStatus("文件超出页数限制");
          clearFileInputValue();
          return;
        }
      } catch (err) {
        setText("error-box", err?.message || "PDF 解析失败，请稍后重试。");
        showUploadStatus("文件校验失败");
        clearFileInputValue();
        return;
      }
    }
    setText("error-box", "-");
    showUploadStatus("正在上传…");

    try {
      const uploadUrl = buildApiUrl(apiPrefix, "uploads");
      const payload = await submitUploadRequest(
        uploadUrl,
        collectUploadFormData(file),
        setUploadProgress,
      );
      const uploadedPageCount = Number(payload.page_count || 0);
      if (frontMaxPageCount > 0 && uploadedPageCount > frontMaxPageCount) {
        setText("error-box", `PDF 页数超过限制：最多 ${frontMaxPageCount} 页`);
        showUploadStatus("文件超出页数限制");
        clearFileInputValue();
        resetUploadedFile();
        return;
      }
      setUploadState(state, {
        uploadId: payload.upload_id || "",
        uploadedFileName: payload.filename || file.name,
        uploadedPageCount,
        uploadedBytes: Number(payload.bytes || file.size || 0),
      });
      writePageRangeInputs({
        start: uploadedPageCount > 0 ? "1" : "",
        end: uploadedPageCount > 0 ? `${uploadedPageCount}` : "",
      });
      setAppliedPageRange(state, currentPageRanges());
      markUploadReady(!!getUploadState(state).uploadId);
      showUploadStatus("上传完成，可以开始任务。");
      clearFileInputValue();
      renderPageRangeSummary();
      refreshSubmitControls();
      if (refreshDeepSeekBalance) {
        showUploadStatus("上传完成，正在检测余额…");
        void withTimeout(
          refreshDeepSeekBalance({ silent: true }),
          BALANCE_CHECK_TIMEOUT_MS,
          "DeepSeek 余额检测超时",
        )
          .then((result) => {
            const status = `${result?.status || ""}`;
            if (status === "network_error" || status === "missing_key") {
              showUploadStatus("上传完成，余额未确认，提交前会再次检测。");
              return;
            }
            showUploadStatus("上传完成，可以开始任务。");
          })
          .catch(() => {
            showUploadStatus("上传完成，余额未确认，提交前会再次检测。");
          })
          .finally(() => {
            refreshSubmitControls();
          });
      }
    } catch (err) {
      resetUploadedFile();
      clearFileInputValue();
      setText("error-box", err.message);
      showUploadStatus("上传失败");
      applyWorkflowMode();
    }
  }

  return {
    applyPageRanges,
    clearPageRanges,
    currentPageRanges,
    handleFileSelected,
    normalizePageRangeValue,
    openPageRangeDialog,
    renderPageRangeSummary,
    validatePageRanges,
  };
}
