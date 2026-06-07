import { bindMainEvents } from "../main-events.js";
import { setText } from "../main-helpers.js";
import { fetchProtected } from "../api/http.js";
import { state } from "../state/store.js";

export function bindFeatureEvents(features) {
  bindMainEvents({
    developerFeature: features.developerFeature,
    glossariesFeature: features.glossariesFeature,
    homeFeature: features.homeFeature,
    artifactDownloadsFeature: features.artifactDownloadsFeature,
    statusDetailFeature: features.statusDetailFeature,
    appShellFeature: features.appShellFeature,
    workflowFeature: features.workflowFeature,
    uploadFeature: features.uploadFeature,
    appActionsFeature: features.appActionsFeature,
    jobRuntimeFeature: features.jobRuntimeFeature,
    state,
    fetchProtected,
    setText,
  });
}
