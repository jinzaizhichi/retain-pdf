import { $ } from "./dom.js";
import {
  applyKeyInputs,
  loadPersistedConfig,
  savePersistedDesktopConfig,
  savePersistedBrowserStoredConfig,
} from "./config.js";
import { state } from "./state/store.js";
import {
  setDesktopConfigured,
  setDesktopMode,
  setDeveloperConfig,
} from "./state/actions.js";
import { getDeveloperConfig } from "./state/developer-state.js";
import { isDesktopConfigured } from "./state/desktop-state.js";

export function showDesktopUi() {
  $("open-output-btn").classList.remove("hidden");
}

export function setDesktopBusy(message = "") {
  const targetIds = ["browser-credentials-status"];
  for (const id of targetIds) {
    const el = $(id);
    if (!el) {
      continue;
    }
    if (message) {
      el.textContent = message;
      el.classList.remove("hidden");
    } else {
      el.textContent = "";
      el.classList.add("hidden");
    }
  }
}

export function openSetupDialog() {
  document.dispatchEvent(new CustomEvent("retainpdf:open-browser-credentials", {
    detail: { setupMode: true },
  }));
}

export function closeSetupDialog() {
  const dialog = $("browser-credentials-dialog");
  if (dialog?.open && dialog.dataset.setupMode === "1") {
    dialog.close();
  }
}

export async function bootstrapDesktop(initialConfig = null) {
  setDesktopMode(state, true);
  showDesktopUi();
  const payload = initialConfig || await loadPersistedConfig();
  setDeveloperConfig(state, payload.developerConfig || {});
  applyKeyInputs(payload.browserConfig || {});
  setDesktopConfigured(state, payload.firstRunCompleted);
  if (!isDesktopConfigured(state)) {
    openSetupDialog();
  } else {
    closeSetupDialog();
  }
}

export async function saveDesktopConfig(mineruToken, modelApiKey, afterSave, extraBrowserConfig = {}) {
  let markConfigured = false;
  let nextBrowserConfig = {
    ...extraBrowserConfig,
    mineruToken,
    modelApiKey,
  };
  let callback = afterSave;
  if (typeof mineruToken === "object" && mineruToken !== null) {
    nextBrowserConfig = { ...(mineruToken.browserConfig || mineruToken) };
    markConfigured = !!mineruToken.markConfigured;
    callback = typeof modelApiKey === "function" ? modelApiKey : afterSave;
  } else {
    markConfigured = !!extraBrowserConfig?.markConfigured;
  }
  let persisted = await savePersistedBrowserStoredConfig({
    ...nextBrowserConfig,
  });
  setDeveloperConfig(state, persisted.developerConfig || getDeveloperConfig(state));
  applyKeyInputs(persisted.browserConfig || {});
  if (markConfigured && !persisted.firstRunCompleted) {
    persisted = await savePersistedDesktopConfig({ firstRunCompleted: true });
    setDeveloperConfig(state, persisted.developerConfig || getDeveloperConfig(state));
    applyKeyInputs(persisted.browserConfig || {});
  }
  setDesktopConfigured(state, persisted.firstRunCompleted);
  if (isDesktopConfigured(state)) {
    closeSetupDialog();
    const errorBox = $("error-box") || $("error-box-inline");
    if (errorBox) {
      errorBox.textContent = "-";
      errorBox.classList?.add("hidden");
    }
  }
  if (callback) {
    try {
      await callback();
    } catch (error) {
      if (isDesktopConfigured(state)) {
        const message = error?.message || String(error);
        throw new Error(`首次配置已保存，但当前无法连接本地后端。${message}`);
      }
      throw error;
    }
  }
  setDeveloperConfig(state, persisted.developerConfig || getDeveloperConfig(state));
  applyKeyInputs(persisted.browserConfig || {});
  return persisted;
}
