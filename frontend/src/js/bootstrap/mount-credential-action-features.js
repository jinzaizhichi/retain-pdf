import {
  apiBase,
  applyKeyInputs,
  defaultMineruToken,
  defaultModelApiKey,
  defaultModelBaseUrl,
  defaultPaddleToken,
  isMockMode,
  openDesktopOutputDirectory,
  saveBrowserStoredConfig,
  savePersistedDeveloperStoredConfig,
} from "../config.js";
import { API_PREFIX, DEFAULT_MODEL_VERSION } from "../constants.js";
import {
  openSetupDialog,
  saveDesktopConfig,
  setDesktopBusy,
} from "../desktop.js";
import { mountAppActionsFeature } from "../features/app-actions/controller.js";
import { mountArtifactDownloadsFeature } from "../features/artifact-downloads/controller.js";
import { mountBrowserCredentialsFeature } from "../features/credentials/browser.js";
import { normalizeMathMode, setText } from "../main-helpers.js";
import {
  buildApiEndpoint,
  fetchProtected,
  submitJson,
} from "../api/http.js";
import {
  queryDeepSeekBalance,
  validateDeepSeekToken,
  validateMineruToken,
  validatePaddleToken,
} from "../api/providers.js";
import { submitJobRequest } from "../api/jobs.js";
import { state } from "../state/store.js";
import { setDeveloperConfig } from "../state/actions.js";
import { getDeveloperConfig } from "../state/developer-state.js";
import {
  renderJob,
  resetUploadedFile,
} from "../ui.js";
import { WORKFLOW_BOOK, WORKFLOW_RENDER } from "./workflow-constants.js";

export function mountCredentialAndActionFeatures(features) {
  features.browserCredentialsFeature = mountBrowserCredentialsFeature({
    state,
    applyKeyInputs,
    defaultMineruToken,
    defaultPaddleToken,
    defaultModelApiKey,
    defaultModelBaseUrl,
    getTaskOptions: () => features.workflowFeature?.developerConfigWithDefaults() || {},
    saveTaskOptions: ({ model, baseUrl, mathMode, translateTitles }) => {
      const currentDeveloperConfig = getDeveloperConfig(state);
      setDeveloperConfig(state, {
        ...currentDeveloperConfig,
        model: `${model || ""}`.trim() || currentDeveloperConfig.model,
        baseUrl: `${baseUrl || ""}`.trim() || currentDeveloperConfig.baseUrl,
        mathMode: normalizeMathMode(mathMode),
        translateTitles: translateTitles !== false,
      });
      void savePersistedDeveloperStoredConfig(getDeveloperConfig(state));
    },
    saveBrowserStoredConfig,
    saveDesktopConfig,
    checkApiConnectivity: () => features.appActionsFeature?.checkApiConnectivity(),
    validateOcrToken: (apiPrefix, providerId, token) => {
      if (providerId === "paddle") {
        return validatePaddleToken(apiPrefix, {
          paddle_token: token,
          base_url: "https://paddleocr.aistudio-app.com",
        });
      }
      return validateMineruToken(apiPrefix, {
        mineru_token: token,
        base_url: "https://mineru.net",
        model_version: DEFAULT_MODEL_VERSION,
      });
    },
    validateDeepSeekToken,
    queryDeepSeekBalance,
    onCredentialStateChange: () => features.workflowFeature?.applyWorkflowMode(),
  });
  features.artifactDownloadsFeature = mountArtifactDownloadsFeature({
    state,
    fetchProtected,
    setText,
  });
  features.appActionsFeature = mountAppActionsFeature({
    state,
    apiBase,
    apiPrefix: API_PREFIX,
    buildApiEndpoint,
    isMockMode,
    openSetupDialog,
    renderJob,
    setText,
    submitJson,
    submitJobRequest,
    saveDesktopConfig,
    setDesktopBusy,
    openDesktopOutputDirectory,
    resetUploadedFile,
    currentWorkflow: () => features.workflowFeature?.currentWorkflow() || WORKFLOW_BOOK,
    workflowNeedsCredentials: (workflow) => features.workflowFeature?.workflowNeedsCredentials(workflow) ?? (workflow !== WORKFLOW_RENDER),
    workflowNeedsUpload: (workflow) => features.workflowFeature?.workflowNeedsUpload(workflow) ?? (workflow !== WORKFLOW_RENDER),
    currentRenderSourceJobId: () => features.workflowFeature?.currentRenderSourceJobId() || "",
    currentBudgetState: () => features.workflowFeature?.currentBudgetState?.(),
    collectRunPayload: () => features.workflowFeature?.collectRunPayload() || {},
    validateBeforeSubmit: () => features.uploadFeature?.validatePageRanges?.() ?? true,
    getBrowserCredentialsFeature: () => features.browserCredentialsFeature,
    getJobRuntimeFeature: () => features.jobRuntimeFeature,
    onDesktopConfigSaved: () => features.workflowFeature?.applyWorkflowMode(),
  });
}
