import { $ } from "../../dom.js";
import { DEFAULT_FILE_LABEL } from "../../constants.js";
import {
  applyMockUploadView,
  applyWorkflowUploadView,
  closeDeveloperDialog,
  readDeveloperDialogValues,
  readDeveloperWorkflowValue,
  readModelApiKey,
  readOcrProviderValue,
  readOcrTokenValue,
  renderTranslationBudgetNote,
  setDeveloperDialogValues,
  setDeveloperGlossaryOptions,
  setDeveloperWorkflowFormState,
  setSubmitControls,
} from "./view.js";
import {
  buildDeveloperConfigWithDefaults,
  workflowHeadline as resolveWorkflowHeadline,
  workflowNeedsCredentials as resolveWorkflowNeedsCredentials,
  workflowNeedsUpload as resolveWorkflowNeedsUpload,
  workflowSubmitLabel as resolveWorkflowSubmitLabel,
  workflowUsesRenderStage as resolveWorkflowUsesRenderStage,
} from "./rules.js";
import {
  buildOcrPayload as buildOcrPayloadRequest,
  buildRenderPayload as buildRenderPayloadRequest,
  buildSourcePayload as buildSourcePayloadRequest,
  buildTranslationPayload as buildTranslationPayloadRequest,
} from "./payload.js";
import { createGlossaryOptionsLoader } from "./glossary-options.js";
import {
  buildDeveloperConfigFromDialog,
  defaultDeveloperDialogReadOptions,
} from "./developer-dialog.js";
import {
  resetDeveloperConfig,
  setDeveloperConfig,
} from "../../state/actions.js";
import { getDeepSeekBalanceState } from "../../state/credential-state.js";
import { getDeveloperConfig } from "../../state/developer-state.js";
import { isDesktopMode } from "../../state/desktop-state.js";
import { getUploadState } from "../../state/upload-state.js";
import { resolveSubmitControlState } from "./submit-controls.js";
import { resolveTranslationBudgetState } from "./budget.js";

export function mountWorkflowFeature({
  state,
  isMockMode,
  saveDeveloperStoredConfig,
  defaultModelName,
  defaultModelBaseUrl,
  defaultMineruToken,
  defaultPaddleApiUrl,
  defaultPaddleToken,
  defaultOcrProvider,
  defaultModelApiKey,
  normalizeWorkflow,
  normalizeMathMode,
  constants,
  currentPageRanges,
  renderPageRangeSummary,
  getBrowserCredentialsFeature,
  fetchGlossaries,
  apiPrefix,
  setText,
}) {
  const {
    DEFAULT_WORKERS,
    DEFAULT_BATCH_SIZE,
    DEFAULT_CLASSIFY_BATCH_SIZE,
    DEFAULT_COMPILE_WORKERS,
    DEFAULT_TIMEOUT_SECONDS,
    WORKFLOW_BOOK,
    WORKFLOW_TRANSLATE,
    WORKFLOW_RENDER,
  } = constants;

  let refreshSubmitControlsRef = null;
  let applyWorkflowModeRef = null;
  const glossaryOptionsLoader = createGlossaryOptionsLoader({
    fetchGlossaries,
    apiPrefix,
    setDeveloperGlossaryOptions,
    setText,
    getDefaultSelectedId: () => developerConfigWithDefaults().glossaryId,
  });

  function developerConfigWithDefaults() {
    return buildDeveloperConfigWithDefaults({
      saved: getDeveloperConfig(state),
      normalizeWorkflow,
      normalizeMathMode,
      defaults: {
        workers: DEFAULT_WORKERS,
        batchSize: DEFAULT_BATCH_SIZE,
        classifyBatchSize: DEFAULT_CLASSIFY_BATCH_SIZE,
        compileWorkers: DEFAULT_COMPILE_WORKERS,
        timeoutSeconds: DEFAULT_TIMEOUT_SECONDS,
      },
      defaultModelName,
      defaultModelBaseUrl,
    });
  }

  function syncDeveloperDialogFromState() {
    const config = developerConfigWithDefaults();
    glossaryOptionsLoader.applyOptions(config.glossaryId);
    setDeveloperDialogValues(config);
    updateDeveloperWorkflowFormState();
    void loadGlossaryOptions();
  }

  function currentWorkflow() {
    return developerConfigWithDefaults().workflow;
  }

  function currentRenderSourceJobId() {
    return developerConfigWithDefaults().renderSourceJobId;
  }

  function workflowNeedsUpload(workflow = currentWorkflow()) {
    return resolveWorkflowNeedsUpload(workflow, constants);
  }

  function workflowNeedsCredentials(workflow = currentWorkflow()) {
    return resolveWorkflowNeedsCredentials(workflow, constants);
  }

  function workflowUsesRenderStage(workflow = currentWorkflow()) {
    return resolveWorkflowUsesRenderStage(workflow, constants);
  }

  function workflowSubmitLabel(workflow = currentWorkflow()) {
    return resolveWorkflowSubmitLabel(workflow, constants);
  }

  function workflowUsesTranslation(workflow = currentWorkflow()) {
    return workflow === WORKFLOW_BOOK || workflow === WORKFLOW_TRANSLATE;
  }

  function workflowHeadline(workflow = currentWorkflow()) {
    return resolveWorkflowHeadline(workflow, constants);
  }

  function updateDeveloperWorkflowFormState() {
    const workflow = normalizeWorkflow(readDeveloperWorkflowValue());
    setDeveloperWorkflowFormState({
      workflow,
      workflowRender: WORKFLOW_RENDER,
      workflowTranslate: WORKFLOW_TRANSLATE,
    });
  }

  function refreshSubmitControls() {
    const workflow = currentWorkflow();
    const uploadState = getUploadState(state);
    const submitState = resolveSubmitControlState({
      workflow,
      isMock: isMockMode(),
      desktopMode: isDesktopMode(state),
      uploadId: uploadState.uploadId,
      renderSourceJobId: currentRenderSourceJobId(),
      hasBrowserCredentials: Boolean(getBrowserCredentialsFeature()?.hasBrowserCredentials()),
      workflowNeedsUpload,
      workflowNeedsCredentials,
      workflowSubmitLabel,
    });
    const budget = currentBudgetState(workflow);
    renderTranslationBudgetNote(budget);
    setSubmitControls({
      ...submitState,
      disabled: submitState.disabled || budget.blocking,
    });
  }

  function currentBudgetState(workflow = currentWorkflow()) {
    const uploadState = getUploadState(state);
    const balanceState = getDeepSeekBalanceState(state);
    return resolveTranslationBudgetState({
      pageRanges: currentPageRanges(),
      uploadedPageCount: uploadState.uploadedPageCount,
      balanceCny: balanceState.balanceCny,
      balanceChecked: balanceState.balanceChecked,
      needsTranslation: workflowNeedsUpload(workflow) && workflowUsesTranslation(workflow) && Boolean(uploadState.uploadId),
    });
  }

  function updateCredentialGate() {
    if (isMockMode()) {
      return;
    }
    getBrowserCredentialsFeature()?.updateCredentialGate({
      workflowNeedsCredentials: () => workflowNeedsCredentials(currentWorkflow()),
      workflowNeedsUpload: () => workflowNeedsUpload(currentWorkflow()),
      refreshSubmitControls,
    });
  }

  function applyWorkflowMode() {
    const workflow = currentWorkflow();
    const needsUpload = workflowNeedsUpload(workflow);
    const showPageRangeButton = workflowNeedsUpload(workflow);
    if (isMockMode()) {
      applyMockUploadView({
        mockScenario: new URLSearchParams(window.location.search).get("mock") || "running",
        submitLabel: workflowSubmitLabel(workflow),
        showPageRangeButton,
      });
      renderPageRangeSummary();
      updateCredentialGate();
      return;
    }
    const uploadState = getUploadState(state);
    applyWorkflowUploadView({
      needsUpload,
      uploadReady: Boolean(uploadState.uploadId),
      defaultFileLabel: DEFAULT_FILE_LABEL,
      headline: workflowHeadline(workflow),
      renderSourceJobId: currentRenderSourceJobId(),
    });
    renderPageRangeSummary();
    refreshSubmitControls();
    updateCredentialGate();
    void loadGlossaryOptions();
  }

  function saveDeveloperDialog() {
    const currentConfig = developerConfigWithDefaults();
    const values = readDeveloperDialogValues(defaultDeveloperDialogReadOptions({
      defaultModelName,
      defaultModelBaseUrl,
      defaults: {
        workers: DEFAULT_WORKERS,
        batchSize: DEFAULT_BATCH_SIZE,
        classifyBatchSize: DEFAULT_CLASSIFY_BATCH_SIZE,
        compileWorkers: DEFAULT_COMPILE_WORKERS,
        timeoutSeconds: DEFAULT_TIMEOUT_SECONDS,
      },
    }));
    setDeveloperConfig(state, buildDeveloperConfigFromDialog({
      currentConfig,
      values,
      normalizeWorkflow,
    }));
    setDeveloperDialogValues(developerConfigWithDefaults());
    void saveDeveloperStoredConfig(getDeveloperConfig(state));
    applyWorkflowMode();
    closeDeveloperDialog();
  }

  function resetDeveloperDialog() {
    resetDeveloperConfig(state);
    void saveDeveloperStoredConfig({});
    syncDeveloperDialogFromState();
    applyWorkflowMode();
  }

  function buildOcrPayload(pageRanges) {
    return buildOcrPayloadRequest({
      pageRanges,
      readOcrProviderValue,
      readOcrTokenValue,
      defaultOcrProvider,
      defaultPaddleToken,
      defaultMineruToken,
      defaultPaddleApiUrl,
      constants,
    });
  }

  function buildTranslationPayload(developerConfig) {
    return buildTranslationPayloadRequest({
      developerConfig,
      readModelApiKey,
      defaultModelApiKey,
      constants,
    });
  }

  async function loadGlossaryOptions({ force = false, selectedId = "" } = {}) {
    return glossaryOptionsLoader.loadGlossaryOptions({ force, selectedId });
  }

  function buildRenderPayload(developerConfig) {
    return buildRenderPayloadRequest({
      developerConfig,
      constants,
    });
  }

  function collectRunPayload() {
    const pageRanges = currentPageRanges();
    const developerConfig = developerConfigWithDefaults();
    const workflow = developerConfig.workflow;
    const uploadState = getUploadState(state);
    const payload = {
      workflow,
      source: buildSourcePayloadRequest({
        workflow,
        developerConfig,
        uploadId: uploadState.uploadId,
        workflowNeedsUpload,
      }),
      runtime: {
        job_id: "",
        timeout_seconds: developerConfig.timeoutSeconds,
      },
    };
    if (workflow === WORKFLOW_BOOK || workflow === WORKFLOW_TRANSLATE) {
      payload.ocr = buildOcrPayload(pageRanges);
      payload.translation = buildTranslationPayload(developerConfig);
    }
    if (workflowUsesRenderStage(workflow)) {
      payload.render = buildRenderPayload(developerConfig);
    }
    return payload;
  }

  return {
    applyWorkflowMode,
    collectRunPayload,
    currentRenderSourceJobId,
    currentWorkflow,
    currentBudgetState,
    developerConfigWithDefaults,
    loadGlossaryOptions,
    refreshSubmitControls,
    resetDeveloperDialog,
    saveDeveloperDialog,
    syncDeveloperDialogFromState,
    updateCredentialGate,
    updateDeveloperWorkflowFormState,
    workflowNeedsCredentials,
    workflowNeedsUpload,
  };
}
