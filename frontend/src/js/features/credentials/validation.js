import { API_PREFIX } from "../../constants.js";
import {
  getOcrProviderDefinition,
  TRANSLATION_PROVIDER_DEFINITION,
} from "../../provider-config.js";
import {
  resetOcrValidationCache as resetOcrValidationCacheState,
  setOcrValidationCache,
} from "../../state/actions.js";

export function resetOcrValidationCache(state) {
  resetOcrValidationCacheState(state);
}

export async function runOcrTokenValidation({
  state,
  providerId,
  token,
  validateOcrToken,
  setOcrValidationMessage,
  showResult = true,
}) {
  const definition = getOcrProviderDefinition(providerId);
  const normalizedToken = `${token || ""}`.trim();
  if (!normalizedToken) {
    resetOcrValidationCache(state);
    if (showResult) {
      setOcrValidationMessage(definition.validationMissingMessage, "error", definition.id);
    }
    return { ok: false, status: "unauthorized" };
  }
  if (!definition.supportsValidation) {
    setOcrValidationCache(state, {
      provider: definition.id,
      token: normalizedToken,
      status: "skipped",
    });
    if (showResult) {
      setOcrValidationMessage(definition.validationUnavailableMessage, "", definition.id);
    }
    return {
      ok: true,
      status: "skipped",
      summary: definition.validationUnavailableMessage,
    };
  }
  if (showResult) {
    setOcrValidationMessage(`正在检测 ${definition.label} Token…`, "", definition.id);
  }
  try {
    const result = await validateOcrToken(API_PREFIX, definition.id, normalizedToken);
    setOcrValidationCache(state, {
      provider: definition.id,
      token: normalizedToken,
      status: result.status || "",
    });
    if (showResult) {
      const hint = result.operator_hint ? ` ${result.operator_hint}` : "";
      const message = result.summary || `${definition.label} Token 检测结果：${result.status || "unknown"}`;
      setOcrValidationMessage(`${message}${hint}`.trim(), result.ok ? "valid" : "error", definition.id);
    }
    return result;
  } catch (_err) {
    resetOcrValidationCache(state);
    if (showResult) {
      setOcrValidationMessage(`${definition.label} Token 检测失败，请稍后重试。`, "error", definition.id);
    }
    return {
      ok: false,
      status: "network_error",
      summary: `${definition.label} Token 检测失败，请稍后重试。`,
    };
  }
}

export async function runDeepSeekConnectivityCheck({
  apiKey,
  baseUrl,
  validateDeepSeekToken,
  setDeepSeekValidationMessage,
  showResult = true,
}) {
  const modelApiKey = `${apiKey || ""}`.trim();
  const modelBaseUrl = `${baseUrl || ""}`.trim();
  if (!modelApiKey) {
    if (showResult) {
      setDeepSeekValidationMessage(TRANSLATION_PROVIDER_DEFINITION.validationMissingMessage, "error");
    }
    return { ok: false, status: 0 };
  }
  if (showResult) {
    setDeepSeekValidationMessage("正在检测 DeepSeek 接口…");
  }
  try {
    const result = await validateDeepSeekToken(API_PREFIX, {
      api_key: modelApiKey,
      base_url: modelBaseUrl,
    });
    if (showResult) {
      setDeepSeekValidationMessage(
        result.summary || (result.ok
          ? TRANSLATION_PROVIDER_DEFINITION.validationSuccessMessage
          : TRANSLATION_PROVIDER_DEFINITION.validationNetworkMessage),
        result.ok ? "valid" : "error",
      );
    }
    return result;
  } catch (_err) {
    if (showResult) {
      setDeepSeekValidationMessage(TRANSLATION_PROVIDER_DEFINITION.validationNetworkMessage, "error");
    }
    return { ok: false, status: 0 };
  }
}

export function summarizeDeepSeekBalance(result) {
  const infos = Array.isArray(result?.balance_infos) ? result.balance_infos : [];
  const parts = infos
    .filter((item) => item && item.currency && item.total_balance)
    .map((item) => `${item.currency} ${item.total_balance}`);
  if (parts.length > 0) {
    return `余额 ${parts.join("，")}`;
  }
  if (result?.is_available) {
    return "余额可用";
  }
  return "余额不足";
}

export async function runDeepSeekBalanceCheck({
  apiKey,
  baseUrl,
  queryDeepSeekBalance,
}) {
  const modelApiKey = `${apiKey || ""}`.trim();
  const modelBaseUrl = `${baseUrl || ""}`.trim();
  if (!modelApiKey) {
    return { ok: false, status: "missing_key" };
  }
  if (!queryDeepSeekBalance) {
    return { ok: false, status: "unsupported" };
  }
  try {
    return await queryDeepSeekBalance(API_PREFIX, {
      api_key: modelApiKey,
      base_url: modelBaseUrl,
    });
  } catch (_err) {
    return { ok: false, status: "network_error" };
  }
}
