import { isDesktopMode, loadPersistedConfig } from "../config.js";
import { bootstrapDesktop } from "../desktop.js";
import { fetchProtected } from "../api/http.js";
import {
  deleteLibraryBook,
  fetchJobList,
  fetchJobPayload,
  fetchLibraryBookList,
} from "../api/jobs.js";
import { setText } from "../main-helpers.js";
import {
  bootstrapStartupRoute,
  initializeIdleAndRecentJobs,
} from "../main-startup.js";
import { state } from "../state.js";
import { applyPersistedConfig } from "./config-bootstrap.js";
import { mountApplicationFeatures } from "./feature-registry.js";

async function initializePage() {
  const persistedConfig = await loadPersistedConfig();
  applyPersistedConfig(state, persistedConfig);
  const features = mountApplicationFeatures();

  initializeIdleAndRecentJobs({
    appShellFeature: features.appShellFeature,
    deleteLibraryBook,
    fetchJobList,
    fetchJobPayload,
    fetchLibraryBookList,
    jobRuntimeFeature: features.jobRuntimeFeature,
  });
  bootstrapStartupRoute({
    state,
    fetchProtected,
    jobRuntimeFeature: features.jobRuntimeFeature,
    setText,
  });

  return { persistedConfig, features };
}

export function initializeApp() {
  initializePage()
    .then(({ persistedConfig, features }) => {
      if (isDesktopMode()) {
        bootstrapDesktop(persistedConfig)
          .then(() => {
            features.workflowFeature?.applyWorkflowMode();
          })
          .catch((err) => {
            setText("error-box", err.message || String(err));
          });
        return;
      }
      features.checkApiConnectivity().catch(() => {});
      features.workflowFeature?.updateCredentialGate();
    })
    .catch((err) => {
      setText("error-box", err.message || String(err));
    });
}
