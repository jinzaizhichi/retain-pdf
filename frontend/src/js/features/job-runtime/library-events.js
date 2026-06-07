const LIBRARY_REFRESH_MIN_INTERVAL_MS = 4000;

export function requestLibraryRefresh(state, { terminal = false } = {}) {
  const now = Date.now();
  const minInterval = terminal ? 0 : LIBRARY_REFRESH_MIN_INTERVAL_MS;
  if (!terminal && state.lastLibraryRefreshRequestedAt && now - state.lastLibraryRefreshRequestedAt < minInterval) {
    return;
  }
  state.lastLibraryRefreshRequestedAt = now;
  document.dispatchEvent(new CustomEvent("retainpdf:library-refresh-requested", {
    detail: { delay: terminal ? 200 : 800 },
  }));
}

export function notifyLibraryJobUpdated(job) {
  document.dispatchEvent(new CustomEvent("retainpdf:library-job-updated", {
    detail: { job },
  }));
}
