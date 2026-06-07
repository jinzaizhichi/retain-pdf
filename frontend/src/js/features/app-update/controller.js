import {
  fetchLatestGithubRelease,
  normalizeReleaseInfo,
} from "./github-release.js";
import {
  readUpdateCache,
  writeUpdateCache,
} from "./state.js";
import {
  bindUpdateButton,
  setUpdateAvailable,
  setUpdateChecking,
  setUpdateError,
  setUpdateLatest,
  setUpdateReady,
} from "./view.js";

export function mountAppUpdateFeature() {
  function applyUpdateInfo(info) {
    if (!info) {
      setUpdateReady();
      return;
    }
    if (info.hasUpdate) {
      setUpdateAvailable(info);
    } else {
      setUpdateLatest(info);
    }
  }

  async function checkForUpdates({ manual = false } = {}) {
    if (manual) {
      setUpdateChecking();
    }
    try {
      const release = await fetchLatestGithubRelease();
      const info = normalizeReleaseInfo(release);
      writeUpdateCache(info);
      applyUpdateInfo(info);
    } catch (error) {
      if (manual) {
        setUpdateError(error);
      }
    }
  }

  bindUpdateButton({
    onCheck: () => {
      void checkForUpdates({ manual: true });
    },
  });

  const cached = readUpdateCache();
  applyUpdateInfo(cached.info);
  if (cached.fresh) {
    return {
      checkForUpdates,
    };
  }

  window.setTimeout(() => {
    void checkForUpdates({ manual: false });
  }, 1200);

  return {
    checkForUpdates,
  };
}
