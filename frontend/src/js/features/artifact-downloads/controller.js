import {
  bindProtectedArtifactLinks,
  isActionLinkDisabled,
} from "./view.js";
import {
  fileNameFromDisposition,
  formatTransferSize,
  prepareDownloadTarget,
  saveResponseDownload,
} from "../../downloads.js";
import {
  completeDownloadToast,
  failDownloadToast,
  showDownloadPreparing,
  updateDownloadProgress,
} from "../../download-feedback.js";
import {
  resolveSourcePdfDownloadName,
  resolveTranslatedPdfDownloadName,
} from "../../job-artifacts.js";
import { currentJobId } from "../job-runtime/runtime-state.js";

export function mountArtifactDownloadsFeature({
  state,
  fetchProtected,
  setText,
}) {
  function setLinkBusy(link, busy, text = "") {
    if (!link) {
      return;
    }
    const label = link.querySelector("span");
    const labelTarget = label || link;
    if (!link.dataset.defaultLabel) {
      link.dataset.defaultLabel = labelTarget.textContent?.trim() || "下载";
    }
    link.classList.toggle("disabled", busy);
    link.setAttribute("aria-disabled", busy ? "true" : "false");
    labelTarget.textContent = busy ? text || "下载中..." : link.dataset.defaultLabel;
  }

  function summarizeDownloadProgress(receivedBytes, totalBytes, percent) {
    const receivedText = formatTransferSize(receivedBytes);
    if (Number.isFinite(totalBytes) && totalBytes > 0) {
      const totalText = formatTransferSize(totalBytes);
      const safePercent = Math.max(0, Math.min(100, Number(percent) || 0));
      return `正在下载 ${receivedText} / ${totalText} (${safePercent.toFixed(0)}%)`;
    }
    return receivedText ? `正在下载 ${receivedText}` : "正在下载...";
  }

  async function handleProtectedArtifactClick(event) {
    const link = event.currentTarget;
    const disabled = isActionLinkDisabled(link);
    const url = link.dataset.url || "";
    if (disabled || !url) {
      event.preventDefault();
      return;
    }

    event.preventDefault();
    setText("error-box", "-");
    const jobId = currentJobId(state) || "result";
    const fallbackName = link.id === "download-btn"
      ? `${jobId}.zip`
      : link.id === "markdown-bundle-btn"
        ? `${jobId}-markdown.zip`
        : link.id === "source-pdf-btn"
          ? `${jobId}-source.pdf`
          : link.id === "pdf-btn"
            ? `${jobId}.pdf`
            : link.id === "markdown-raw-btn"
              ? `${jobId}.md`
              : `${jobId}.json`;
    const preferredName = link.id === "pdf-btn"
      ? resolveTranslatedPdfDownloadName(state, fallbackName)
      : link.id === "source-pdf-btn"
        ? resolveSourcePdfDownloadName(state, fallbackName)
        : fallbackName;
    const downloadTarget = await prepareDownloadTarget(preferredName);
    if (downloadTarget.kind === "aborted") {
      return;
    }

    try {
      setLinkBusy(link, true, "下载中...");
      showDownloadPreparing(preferredName);
      const resp = await fetchProtected(url);
      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(`下载失败: ${resp.status} ${text || "unknown error"}`);
      }

      const disposition = resp.headers.get("content-disposition") || "";
      const filename = link.id === "pdf-btn" || link.id === "source-pdf-btn"
        ? preferredName
        : fileNameFromDisposition(disposition, fallbackName);
      await saveResponseDownload(resp, {
        target: downloadTarget,
        filename,
        onProgress: ({ receivedBytes, totalBytes, percent, done }) => {
          if (done) {
            setText("error-box", `已开始保存 ${filename}`);
            setLinkBusy(link, true, "已完成");
            completeDownloadToast(filename);
            return;
          }
          setText("error-box", summarizeDownloadProgress(receivedBytes, totalBytes, percent));
          setLinkBusy(
            link,
            true,
            Number.isFinite(percent) ? `${Math.max(0, Math.min(100, Number(percent) || 0)).toFixed(0)}%` : "下载中...",
          );
          updateDownloadProgress({
            filename,
            receivedBytes,
            totalBytes,
            percent,
          });
        },
      });
    } catch (err) {
      setText("error-box", err.message);
      failDownloadToast(err.message || "下载失败");
    } finally {
      setLinkBusy(link, false);
    }
  }

  function bindEvents() {
    bindProtectedArtifactLinks(handleProtectedArtifactClick);
  }

  return {
    bindEvents,
    handleProtectedArtifactClick,
  };
}
