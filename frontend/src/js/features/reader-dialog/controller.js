import { isTrustedWindowMessage } from "../../config.js";
import { downloadBlob } from "../../downloads.js";
import {
  completeDownloadToast,
  failDownloadToast,
} from "../../download-feedback.js";
import {
  resolveSourcePdfDownloadName,
  resolveTranslatedPdfDownloadName,
} from "../../job-artifacts.js";
import {
  bindReaderDialogEvents,
  closeReaderDialog,
  getReaderFrameWindow,
  getReaderLinkOpenState,
  getReaderToolbarButtonUrl,
  hasLoadedReaderFrame,
  openReaderDialog,
  restoreReaderButton,
  setReaderButtonBusy,
  setReaderFrameSource,
  setReaderLoadingProgress,
  setReaderLoadingVisible,
  setReaderToolbarButtonState,
} from "./view.js";
import {
  buildMergedComparePdf,
  downloadProtectedResource,
  fetchProtectedBytes,
  summarizeDownloadProgress,
} from "./downloads.js";
import {
  buildReaderPageUrl,
  buildReaderRouteUrl,
  currentReaderArtifactUrls,
  jobIdFromReaderUrl,
  requestedReaderJobIdFromLocation,
} from "./routing.js";
import { currentJobId } from "../job-runtime/runtime-state.js";

export function mountReaderDialogFeature({
  state,
  fetchProtected,
  setText,
}) {
  const progressState = {
    value: 0,
    target: 0,
    rafId: 0,
  };

  function syncReaderRoute(jobId = "") {
    window.history.replaceState(window.history.state, "", buildReaderRouteUrl(jobId));
  }

  function setLoading(loading) {
    setReaderLoadingVisible(loading);
  }

  function setLoadingProgress(percent = 0, text = "正在准备对照阅读…") {
    setReaderLoadingProgress(progressState, percent, text);
  }

  function syncToolbarActions() {
    const { sourcePdf, translatedPdf } = currentReaderArtifactUrls(state);
    setReaderToolbarButtonState("reader-source-download-btn", !!sourcePdf, sourcePdf);
    setReaderToolbarButtonState("reader-translated-download-btn", !!translatedPdf, translatedPdf);
    setReaderToolbarButtonState("reader-merged-download-btn", !!sourcePdf && !!translatedPdf);
  }

  async function handleSourceDownload() {
    const url = getReaderToolbarButtonUrl("reader-source-download-btn");
    if (!url) {
      return;
    }
    try {
      const jobId = currentJobId(state) || "result";
      const preferredName = resolveSourcePdfDownloadName(state, `${jobId}-source.pdf`);
      await downloadProtectedResource(
        fetchProtected,
        url,
        `${jobId}-source.pdf`,
        preferredName,
        ({ filename, receivedBytes, totalBytes, percent, done }) => {
          setText("error-box", done ? `已开始保存 ${filename}` : summarizeDownloadProgress(receivedBytes, totalBytes, percent));
        },
        (busy, label) => setReaderButtonBusy("reader-source-download-btn", busy, label),
      );
    } catch (err) {
      setText("error-box", err.message);
      failDownloadToast(err.message || "下载失败");
    } finally {
      syncToolbarActions();
    }
  }

  async function handleTranslatedDownload() {
    const url = getReaderToolbarButtonUrl("reader-translated-download-btn");
    if (!url) {
      return;
    }
    try {
      const jobId = currentJobId(state) || "result";
      const preferredName = resolveTranslatedPdfDownloadName(state, "");
      await downloadProtectedResource(
        fetchProtected,
        url,
        `${jobId}-translated.pdf`,
        preferredName,
        ({ filename, receivedBytes, totalBytes, percent, done }) => {
          setText("error-box", done ? `已开始保存 ${filename}` : summarizeDownloadProgress(receivedBytes, totalBytes, percent));
        },
        (busy, label) => setReaderButtonBusy("reader-translated-download-btn", busy, label),
      );
    } catch (err) {
      setText("error-box", err.message);
      failDownloadToast(err.message || "下载失败");
    } finally {
      syncToolbarActions();
    }
  }

  async function handleMergedDownload() {
    const { sourcePdf, translatedPdf } = currentReaderArtifactUrls(state);
    if (!sourcePdf || !translatedPdf) {
      return;
    }
    const previousMarkup = setReaderButtonBusy("reader-merged-download-btn", true, "生成中…");
    try {
      const [sourceBytes, translatedBytes] = await Promise.all([
        fetchProtectedBytes(fetchProtected, sourcePdf, "原始 PDF"),
        fetchProtectedBytes(fetchProtected, translatedPdf, "译文 PDF"),
      ]);
      const mergedBytes = await buildMergedComparePdf(sourceBytes, translatedBytes);
      const filename = `${currentJobId(state) || "result"}-compare.pdf`;
      downloadBlob(new Blob([mergedBytes], { type: "application/pdf" }), filename);
      completeDownloadToast(filename);
    } catch (err) {
      setText("error-box", err.message);
      failDownloadToast(err.message || "下载失败");
    } finally {
      restoreReaderButton("reader-merged-download-btn", previousMarkup);
      syncToolbarActions();
    }
  }

  function resolveOpenArgs(input) {
    if (typeof input === "string") {
      return {
        url: buildReaderPageUrl(input),
        jobId: `${input || ""}`.trim(),
        disabled: false,
      };
    }
    if (input?.jobId || input?.url || typeof input?.disabled === "boolean") {
      const jobId = `${input?.jobId || ""}`.trim() || jobIdFromReaderUrl(input?.url);
      return {
        url: `${input?.url || buildReaderPageUrl(jobId)}`.trim(),
        jobId,
        disabled: !!input?.disabled,
      };
    }
    const { url, disabled } = getReaderLinkOpenState(input);
    let jobId = currentJobId(state);
    if (!jobId && url) {
      try {
        jobId = new URL(url, window.location.href).searchParams.get("job_id")?.trim() || "";
      } catch (_err) {
        jobId = "";
      }
    }
    return {
      url,
      jobId,
      disabled,
    };
  }

  function open(input) {
    const { url, jobId, disabled } = resolveOpenArgs(input);
    if (input?.preventDefault) {
      input.preventDefault();
    }
    if (disabled || !url || !jobId) {
      return;
    }
    syncReaderRoute(jobId);
    setLoading(true);
    setLoadingProgress(8, "正在准备对照阅读…");
    setReaderFrameSource(url);
    syncToolbarActions();
    openReaderDialog();
  }

  function close() {
    closeReaderDialog();
    setLoading(false);
    setLoadingProgress(0, "正在准备对照阅读…");
    setReaderToolbarButtonState("reader-source-download-btn", false);
    setReaderToolbarButtonState("reader-translated-download-btn", false);
    setReaderToolbarButtonState("reader-merged-download-btn", false);
    syncReaderRoute("");
    setReaderFrameSource("about:blank");
  }

  function bindEvents() {
    bindReaderDialogEvents({
      onClose: close,
      onSourceDownload: handleSourceDownload,
      onMergedDownload: handleMergedDownload,
      onTranslatedDownload: handleTranslatedDownload,
      onFrameLoad() {
        window.setTimeout(() => {
          if (hasLoadedReaderFrame()) {
            setLoading(false);
          }
        }, 1200);
      },
    });
    window.addEventListener("message", (event) => {
      if (!isTrustedWindowMessage(event, getReaderFrameWindow())) {
        return;
      }
      const data = event.data;
      if (!data || data.type !== "retainpdf-reader-progress") {
        return;
      }
      setLoading(true);
      setLoadingProgress(data.percent, data.text);
      if (Number(data.percent) >= 100 && data.stage === "ready") {
        window.setTimeout(() => {
          setLoading(false);
        }, 180);
      }
    });
  }

  return {
    bindEvents,
    close,
    getRequestedJobIdFromLocation: requestedReaderJobIdFromLocation,
    open,
    syncToolbarActions,
  };
}
