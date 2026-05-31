import {
  fileNameFromDisposition,
  formatTransferSize,
  prepareDownloadTarget,
  saveResponseDownload,
} from "../../downloads.js";
import {
  completeDownloadToast,
  showDownloadPreparing,
  updateDownloadProgress,
} from "../../download-feedback.js";

let pdfDocumentModulePromise = null;

async function loadPdfDocument() {
  if (!pdfDocumentModulePromise) {
    const pdfLibUrl = new URL("./vendor/pdf-lib/dist/pdf-lib.esm.js", window.location.href).toString();
    pdfDocumentModulePromise = import(pdfLibUrl)
      .then((module) => module.PDFDocument);
  }
  return pdfDocumentModulePromise;
}

export function summarizeDownloadProgress(receivedBytes, totalBytes, percent) {
  const receivedText = formatTransferSize(receivedBytes);
  if (Number.isFinite(totalBytes) && totalBytes > 0) {
    const totalText = formatTransferSize(totalBytes);
    const safePercent = Math.max(0, Math.min(100, Number(percent) || 0));
    return `正在下载 ${receivedText} / ${totalText} (${safePercent.toFixed(0)}%)`;
  }
  return receivedText ? `正在下载 ${receivedText}` : "正在下载...";
}

export async function downloadProtectedResource(
  fetchProtected,
  url,
  fallbackName,
  preferredName = "",
  onStatus = null,
  onBusy = null,
) {
  const suggestedName = `${preferredName || ""}`.trim() || fallbackName;
  const downloadTarget = await prepareDownloadTarget(suggestedName);
  if (downloadTarget.kind === "aborted") {
    return;
  }
  if (typeof onBusy === "function") {
    onBusy(true, "下载中...");
  }
  try {
    showDownloadPreparing(suggestedName);
    const resp = await fetchProtected(url);
    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(`下载失败: ${resp.status} ${text || "unknown error"}`);
    }
    const disposition = resp.headers.get("content-disposition") || "";
    const finalName = `${preferredName || ""}`.trim() || fileNameFromDisposition(disposition, fallbackName);
    await saveResponseDownload(resp, {
      target: downloadTarget,
      filename: finalName,
      onProgress: ({ receivedBytes, totalBytes, percent, done }) => {
        if (typeof onStatus === "function") {
          onStatus({ filename: finalName, receivedBytes, totalBytes, percent, done });
        }
        if (typeof onBusy === "function") {
          onBusy(
            true,
            done
              ? "已完成"
              : Number.isFinite(percent)
                ? `${Math.max(0, Math.min(100, Number(percent) || 0)).toFixed(0)}%`
                : "下载中...",
          );
        }
        if (done) {
          completeDownloadToast(finalName);
          return;
        }
        updateDownloadProgress({ filename: finalName, receivedBytes, totalBytes, percent });
      },
    });
  } finally {
    if (typeof onBusy === "function") {
      window.setTimeout(() => onBusy(false), 240);
    }
  }
}

export async function fetchProtectedBytes(fetchProtected, url, label) {
  const resp = await fetchProtected(url);
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`读取${label}失败: ${resp.status} ${text || "unknown error"}`);
  }
  return resp.arrayBuffer();
}

export async function buildMergedComparePdf(sourceBytes, translatedBytes) {
  const PDFDocument = await loadPdfDocument();
  const mergedDoc = await PDFDocument.create();
  const sourceDoc = await PDFDocument.load(sourceBytes);
  const translatedDoc = await PDFDocument.load(translatedBytes);
  const totalPages = Math.max(sourceDoc.getPageCount(), translatedDoc.getPageCount());

  for (let index = 0; index < totalPages; index += 1) {
    const sourceEmbedded = index < sourceDoc.getPageCount()
      ? (await mergedDoc.embedPdf(sourceBytes, [index]))[0]
      : null;
    const translatedEmbedded = index < translatedDoc.getPageCount()
      ? (await mergedDoc.embedPdf(translatedBytes, [index]))[0]
      : null;

    const sourceWidth = sourceEmbedded?.width || 0;
    const sourceHeight = sourceEmbedded?.height || 0;
    const translatedWidth = translatedEmbedded?.width || 0;
    const translatedHeight = translatedEmbedded?.height || 0;
    const pageWidth = Math.max(1, sourceWidth + translatedWidth);
    const pageHeight = Math.max(sourceHeight, translatedHeight, 1);
    const page = mergedDoc.addPage([pageWidth, pageHeight]);

    if (sourceEmbedded) {
      page.drawPage(sourceEmbedded, {
        x: 0,
        y: pageHeight - sourceHeight,
        width: sourceWidth,
        height: sourceHeight,
      });
    }
    if (translatedEmbedded) {
      page.drawPage(translatedEmbedded, {
        x: sourceWidth,
        y: pageHeight - translatedHeight,
        width: translatedWidth,
        height: translatedHeight,
      });
    }
  }

  return mergedDoc.save();
}
