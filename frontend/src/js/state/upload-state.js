export function createUploadState() {
  return {
    uploadId: "",
    uploadedFileName: "",
    uploadedPageCount: 0,
    uploadedBytes: 0,
    appliedPageRange: "",
    submitBusy: false,
  };
}

export function resetUploadState(target, { includePageRange = true } = {}) {
  const next = createUploadState();
  if (!includePageRange) {
    delete next.appliedPageRange;
  }
  Object.assign(target, next);
}

export function setUploadState(target, {
  uploadId = "",
  uploadedFileName = "",
  uploadedPageCount = 0,
  uploadedBytes = 0,
} = {}) {
  Object.assign(target, {
    uploadId,
    uploadedFileName,
    uploadedPageCount,
    uploadedBytes,
  });
}

export function setAppliedPageRange(target, value = "") {
  target.appliedPageRange = `${value || ""}`.trim();
}

export function clearAppliedPageRange(target) {
  target.appliedPageRange = "";
}

export function getUploadState(target) {
  return {
    uploadId: target.uploadId,
    uploadedFileName: target.uploadedFileName,
    uploadedPageCount: target.uploadedPageCount,
    uploadedBytes: target.uploadedBytes,
    appliedPageRange: target.appliedPageRange,
    submitBusy: target.submitBusy,
  };
}
