import { $ } from "../../dom.js";
import {
  getOcrProviderDefinition,
  normalizeOcrProvider,
  TRANSLATION_PROVIDER_DEFINITION,
} from "../../provider-config.js";
import { resetDeepSeekBalanceState } from "../../state/actions.js";
import { hasValidOcrValidationCache } from "../../state/credential-state.js";
import { isDesktopMode } from "../../state/desktop-state.js";
import { getUploadState } from "../../state/upload-state.js";
import {
  activateCredentialTabView,
  bindCredentialViewEvents,
  browserCredentialElements,
  closeCredentialDialog,
  credentialDialog,
  openCredentialDialog,
  setCredentialDialogModeView,
  setDeepSeekTopUpVisible,
  setDeepSeekValidationMessage,
  setDialogStatus,
  setOcrValidationMessage,
  syncOcrProviderControlsView,
  updateCredentialGateView,
} from "./view.js";
import {
  resetOcrValidationCache,
  runOcrTokenValidation,
} from "./validation.js";
import { handleBrowserDeepSeekValidate as runBrowserDeepSeekValidate } from "./deepseek-flow.js";
import {
  persistBrowserCredentialsFromDialog as persistBrowserCredentials,
  persistDesktopCredentialsFromDialog as persistDesktopCredentials,
} from "./persistence.js";

export function mountBrowserCredentialsFeature({
  state,
  applyKeyInputs,
  defaultMineruToken,
  defaultPaddleToken,
  defaultModelApiKey,
  defaultModelBaseUrl,
  getTaskOptions,
  saveTaskOptions,
  saveBrowserStoredConfig,
  saveDesktopConfig,
  checkApiConnectivity,
  validateOcrToken,
  validateDeepSeekToken,
  queryDeepSeekBalance,
  onCredentialStateChange,
}) {
  function setCredentialDialogMode(setupMode = false) {
    setCredentialDialogModeView({ setupMode, activateCredentialTab });
  }

  function activateCredentialTab(tabName = "api") {
    activateCredentialTabView(tabName);
  }

  function currentOcrProvider() {
    return normalizeOcrProvider($("ocr_provider")?.value);
  }

  function syncOcrProviderControls(providerId = currentOcrProvider()) {
    const activeProvider = normalizeOcrProvider(providerId);
    syncOcrProviderControlsView(activeProvider);
  }

  function syncBrowserDialogFromHiddenInputs() {
    const {
      mineruInput,
      paddleInput,
      apiKeyInput,
      modelBaseUrlInput,
      modelNameInput,
      mathModeSelect,
    } = browserCredentialElements();
    const taskOptions = getTaskOptions?.() || {};
    if (mineruInput) {
      mineruInput.value = $("mineru_token").value || "";
    }
    if (paddleInput) {
      paddleInput.value = $("paddle_token").value || "";
    }
    if (apiKeyInput) {
      apiKeyInput.value = $("api_key").value || "";
    }
    if (modelBaseUrlInput) {
      modelBaseUrlInput.value = taskOptions.baseUrl || defaultModelBaseUrl();
    }
    if (modelNameInput) {
      modelNameInput.value = taskOptions.model || "";
    }
    syncOcrProviderControls(currentOcrProvider());
    if (mathModeSelect) {
      mathModeSelect.value = taskOptions.mathMode === "placeholder" ? "placeholder" : "direct_typst";
    }
    setOcrValidationMessage("", "", "mineru");
    setOcrValidationMessage("", "", "paddle");
    setDeepSeekValidationMessage("", "");
    setDeepSeekTopUpVisible(false);
    resetDeepSeekBalanceState(state);
    setDialogStatus("", "");
  }

  function hasBrowserCredentials() {
    const definition = getOcrProviderDefinition(currentOcrProvider());
    return Boolean(($(`${definition.tokenField}`)?.value || "").trim() && ($("api_key").value || "").trim());
  }

  function openBrowserCredentialsDialog(options = {}) {
    const { dialog } = browserCredentialElements();
    if (!dialog) {
      return;
    }
    syncBrowserDialogFromHiddenInputs();
    setCredentialDialogMode(!!options.setupMode);
    activateCredentialTab("api");
    openCredentialDialog();
  }

  async function ensureOcrCredentialsReady({ onMissingToken, onInvalidToken } = {}) {
    const provider = currentOcrProvider();
    const definition = getOcrProviderDefinition(provider);
    const fallbackToken = definition.id === "paddle" ? defaultPaddleToken() : defaultMineruToken();
    const token = ($(`${definition.tokenField}`)?.value || fallbackToken).trim();
    if (!token) {
      onMissingToken?.();
      setOcrValidationMessage(definition.validationMissingMessage, "error", definition.id);
      return false;
    }
    if (hasValidOcrValidationCache(state, {
      provider: definition.id,
      token,
    })) {
      return true;
    }
    const result = await runOcrTokenValidation({
      state,
      providerId: definition.id,
      token,
      validateOcrToken,
      setOcrValidationMessage,
      showResult: !isDesktopMode(state),
    });
    if (result.ok) {
      return true;
    }
    onInvalidToken?.(result);
    return false;
  }

  function updateCredentialGate({
    workflowNeedsCredentials,
    workflowNeedsUpload,
    refreshSubmitControls,
  }) {
    const uploadEnabled = workflowNeedsUpload();
    const desktopMode = isDesktopMode(state);
    const uploadState = getUploadState(state);
    if (desktopMode) {
      if (!updateCredentialGateView({
        desktopMode: true,
        show: false,
        uploadEnabled,
        uploadReady: !!uploadState.uploadId,
      })) {
        return;
      }
      refreshSubmitControls();
      return;
    }
    const show = workflowNeedsCredentials() && !hasBrowserCredentials();
    if (!updateCredentialGateView({
      desktopMode: false,
      show,
      uploadEnabled,
      uploadReady: !!uploadState.uploadId,
    })) {
      return;
    }
    refreshSubmitControls();
  }

  function currentProviderInputValue() {
    const { mineruInput, paddleInput } = browserCredentialElements();
    return currentOcrProvider() === "paddle" ? paddleInput?.value || "" : mineruInput?.value || "";
  }

  async function handleBrowserOcrValidate() {
    await runOcrTokenValidation({
      state,
      providerId: currentOcrProvider(),
      token: currentProviderInputValue(),
      validateOcrToken,
      setOcrValidationMessage,
      showResult: true,
    });
  }

  async function handleBrowserDeepSeekValidate() {
    await runBrowserDeepSeekValidate({
      state,
      defaultModelApiKey,
      validateDeepSeekToken,
      queryDeepSeekBalance,
      onBalanceChange: onCredentialStateChange,
    });
  }

  async function refreshDeepSeekBalance({ silent = true } = {}) {
    return runBrowserDeepSeekValidate({
      state,
      defaultModelApiKey,
      validateDeepSeekToken,
      queryDeepSeekBalance,
      onBalanceChange: onCredentialStateChange,
      silent,
    });
  }

  async function handleBrowserCredentialSave() {
    const definition = getOcrProviderDefinition(currentOcrProvider());
    const { mineruInput, paddleInput, apiKeyInput } = browserCredentialElements();
    const ocrToken = (definition.id === "paddle" ? paddleInput?.value : mineruInput?.value)?.trim() || "";
    const modelApiKey = apiKeyInput?.value?.trim() || "";
    if (!ocrToken || !modelApiKey) {
      if (!ocrToken) {
        setOcrValidationMessage(definition.validationMissingMessage, "error", definition.id);
      }
      if (!modelApiKey) {
        setDeepSeekValidationMessage(TRANSLATION_PROVIDER_DEFINITION.validationMissingMessage, "error");
      }
      return;
    }
    const validation = await runOcrTokenValidation({
      state,
      providerId: definition.id,
      token: ocrToken,
      validateOcrToken,
      setOcrValidationMessage,
      showResult: true,
    });
    if (!validation.ok) {
      return;
    }
    try {
      if (isDesktopMode(state)) {
        await persistDesktopCredentials({
          currentOcrProvider,
          defaultModelApiKey,
          defaultModelBaseUrl,
          saveTaskOptions,
          saveDesktopConfig,
          checkApiConnectivity,
        });
      } else {
        persistBrowserCredentials({
          applyKeyInputs,
          currentOcrProvider,
          defaultModelApiKey,
          defaultModelBaseUrl,
          saveTaskOptions,
          saveBrowserStoredConfig,
        });
      }
    } catch (error) {
      setDialogStatus(error?.message || String(error), "error");
      setDeepSeekValidationMessage(error?.message || String(error), "error");
      return;
    }
    onCredentialStateChange?.();
    setDialogStatus("", "");
    closeCredentialDialog();
  }

  bindCredentialViewEvents({
    resetMineruValidation: () => {
      resetOcrValidationCache(state);
      setOcrValidationMessage("", "", "mineru");
    },
    resetPaddleValidation: () => {
      resetOcrValidationCache(state);
      setOcrValidationMessage("", "", "paddle");
    },
    resetDeepSeekValidation: () => {
      setDeepSeekValidationMessage("", "");
      setDeepSeekTopUpVisible(false);
      resetDeepSeekBalanceState(state);
      onCredentialStateChange?.();
    },
    validateOcr: handleBrowserOcrValidate,
    validateDeepSeek: handleBrowserDeepSeekValidate,
    save: handleBrowserCredentialSave,
    open: openBrowserCredentialsDialog,
    activateCredentialTab,
    changeProvider: (event) => {
      const provider = normalizeOcrProvider(event.currentTarget?.value);
      $("ocr_provider").value = provider;
      syncOcrProviderControls(provider);
    },
  });

  return {
    activateCredentialTab,
    ensureOcrCredentialsReady,
    hasBrowserCredentials,
    openBrowserCredentialsDialog,
    refreshDeepSeekBalance,
    setDialogStatus,
    updateCredentialGate,
  };
}
