import { TRANSLATION_PROVIDER_DEFINITION } from "../../provider-config.js";
import { $ } from "../../dom.js";
import {
  resetDeepSeekBalanceState,
  setDeepSeekBalanceState,
} from "../../state/actions.js";
import {
  browserCredentialElements,
  setDeepSeekTopUpVisible,
  setDeepSeekValidationMessage,
} from "./view.js";
import {
  runDeepSeekBalanceCheck,
  runDeepSeekConnectivityCheck,
  summarizeDeepSeekBalance,
} from "./validation.js";

const DEEPSEEK_LOW_BALANCE_THRESHOLD = 2;

function deepSeekBalanceAmount(result) {
  const infos = Array.isArray(result?.balance_infos) ? result.balance_infos : [];
  return infos.reduce((sum, item) => {
    const raw = `${item?.total_balance ?? ""}`.replace(/[^\d.-]/g, "");
    const value = Number.parseFloat(raw);
    return Number.isFinite(value) ? sum + value : sum;
  }, 0);
}

export async function handleBrowserDeepSeekValidate({
  state,
  defaultModelApiKey,
  validateDeepSeekToken,
  queryDeepSeekBalance,
  onBalanceChange,
  silent = false,
}) {
  const {
    apiKeyInput,
    modelBaseUrlInput,
  } = browserCredentialElements();
  const modelApiKey = apiKeyInput?.value?.trim() || $("api_key")?.value?.trim() || defaultModelApiKey?.() || "";
  if (apiKeyInput && !apiKeyInput.value && modelApiKey) {
    apiKeyInput.value = modelApiKey;
  }
  const baseUrl = modelBaseUrlInput?.value?.trim() || "";
  if (state) {
    resetDeepSeekBalanceState(state);
  }
  onBalanceChange?.();
  if (!modelApiKey) {
    return { ok: false, status: "missing_key" };
  }
  setDeepSeekTopUpVisible(false);
  if (!silent) {
    setDeepSeekValidationMessage("正在检测 DeepSeek 和余额…");
  }
  const result = await runDeepSeekConnectivityCheck({
    apiKey: modelApiKey,
    baseUrl,
    validateDeepSeekToken,
    setDeepSeekValidationMessage,
    showResult: false,
  });
  if (result.ok) {
    const balance = await runDeepSeekBalanceCheck({
      apiKey: modelApiKey,
      baseUrl,
      queryDeepSeekBalance,
    });
    if (balance.status === "unsupported_provider") {
      if (!silent) {
        setDeepSeekValidationMessage("DeepSeek 可用", "valid");
      }
      return balance;
    }
    if (balance.status === "network_error") {
      if (!silent) {
        setDeepSeekValidationMessage("DeepSeek 可用，余额查询失败", "valid");
      }
      return balance;
    }
    const balanceSummary = summarizeDeepSeekBalance(balance);
    const balanceAmount = deepSeekBalanceAmount(balance);
    if (state) {
      setDeepSeekBalanceState(state, balanceAmount, true);
    }
    onBalanceChange?.();
    const shouldTopUp = balanceAmount < DEEPSEEK_LOW_BALANCE_THRESHOLD;
    setDeepSeekTopUpVisible(shouldTopUp);
    setDeepSeekValidationMessage(
      `DeepSeek 可用，${balanceSummary}${shouldTopUp ? "，余额低于 2 元" : ""}`,
      balance.is_available ? "valid" : "error",
    );
    return balance;
  }
  setDeepSeekTopUpVisible(false);
  if (!silent) {
    setDeepSeekValidationMessage(
      result.summary || TRANSLATION_PROVIDER_DEFINITION.validationNetworkMessage,
      "error",
    );
  }
  return result;
}
