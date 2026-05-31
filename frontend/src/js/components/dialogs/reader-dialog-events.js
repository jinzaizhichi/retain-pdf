export function bindReaderDialogEvents(host, {
  onClose,
  onFrameLoad,
  onSourceDownload,
  onMergedDownload,
  onTranslatedDownload,
} = {}) {
  if (host.__retainPdfReaderDialogEventsBound) {
    host.__retainPdfReaderDialogHandlers = {
      onClose,
      onFrameLoad,
      onSourceDownload,
      onMergedDownload,
      onTranslatedDownload,
    };
    return;
  }
  host.__retainPdfReaderDialogEventsBound = true;
  host.__retainPdfReaderDialogHandlers = {
    onClose,
    onFrameLoad,
    onSourceDownload,
    onMergedDownload,
    onTranslatedDownload,
  };
  const handlers = () => host.__retainPdfReaderDialogHandlers || {};
  host.querySelector("#reader-source-download-btn")?.addEventListener("click", () => handlers().onSourceDownload?.());
  host.querySelector("#reader-merged-download-btn")?.addEventListener("click", () => handlers().onMergedDownload?.());
  host.querySelector("#reader-translated-download-btn")?.addEventListener("click", () => handlers().onTranslatedDownload?.());
  host.querySelector("#reader-dialog-close-btn")?.addEventListener("click", () => handlers().onClose?.());
  host.querySelector("#reader-dialog-frame")?.addEventListener("load", () => handlers().onFrameLoad?.());
}
