import {
  fetchLatestGithubRelease,
  normalizeReleaseInfo,
} from "./github-release.js";
import {
  bindUpdateButton,
  setUpdateAvailable,
  setUpdateChecking,
  setUpdateError,
  setUpdateLatest,
} from "./view.js";

export function mountAppUpdateFeature() {
  async function checkForUpdates() {
    setUpdateChecking();
    try {
      const release = await fetchLatestGithubRelease();
      const info = normalizeReleaseInfo(release);
      if (info.hasUpdate) {
        setUpdateAvailable(info);
      } else {
        setUpdateLatest(info);
      }
    } catch (error) {
      setUpdateError(error);
    }
  }

  bindUpdateButton({
    onCheck: () => {
      void checkForUpdates();
    },
  });
  window.setTimeout(() => {
    void checkForUpdates();
  }, 1200);

  return {
    checkForUpdates,
  };
}
