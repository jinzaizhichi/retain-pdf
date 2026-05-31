import {
  browserCredentialElements,
  currentCredentialDialogSetupMode,
} from "./view.js";

export function persistBrowserCredentialsFromDialog({
  applyKeyInputs,
  currentOcrProvider,
  defaultModelApiKey,
  defaultModelBaseUrl,
  saveTaskOptions,
  saveBrowserStoredConfig,
}) {
  const {
    mineruInput,
    paddleInput,
    apiKeyInput,
    modelBaseUrlInput,
    modelNameInput,
    mathModeSelect,
  } = browserCredentialElements();
  applyKeyInputs({
    ocrProvider: currentOcrProvider(),
    mineruToken: mineruInput?.value?.trim() || "",
    paddleToken: paddleInput?.value?.trim() || "",
    modelApiKey: apiKeyInput?.value?.trim() || defaultModelApiKey?.() || "",
  });
  saveTaskOptions?.({
    model: modelNameInput?.value?.trim() || "",
    baseUrl: modelBaseUrlInput?.value?.trim() || defaultModelBaseUrl?.() || "",
    mathMode: mathModeSelect?.value || "direct_typst",
    translateTitles: true,
  });
  saveBrowserStoredConfig();
}

export async function persistDesktopCredentialsFromDialog({
  currentOcrProvider,
  defaultModelApiKey,
  defaultModelBaseUrl,
  saveTaskOptions,
  saveDesktopConfig,
  checkApiConnectivity,
}) {
  const {
    mineruInput,
    paddleInput,
    apiKeyInput,
    modelBaseUrlInput,
    modelNameInput,
    mathModeSelect,
  } = browserCredentialElements();
  const provider = currentOcrProvider();
  const mineruToken = mineruInput?.value?.trim() || "";
  const paddleToken = paddleInput?.value?.trim() || "";
  const modelApiKey = apiKeyInput?.value?.trim() || defaultModelApiKey?.() || "";
  await saveDesktopConfig?.(
    mineruToken,
    modelApiKey,
    async () => {
      await checkApiConnectivity?.();
    },
    {
      ocrProvider: provider,
      paddleToken,
      markConfigured: currentCredentialDialogSetupMode(),
    },
  );
  saveTaskOptions?.({
    model: modelNameInput?.value?.trim() || "",
    baseUrl: modelBaseUrlInput?.value?.trim() || defaultModelBaseUrl?.() || "",
    mathMode: mathModeSelect?.value || "direct_typst",
    translateTitles: true,
  });
}
