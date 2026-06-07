export function createCredentialState() {
  return {
    validatedOcrProvider: "",
    validatedOcrToken: "",
    ocrValidationStatus: "",
    deepseekBalanceCny: null,
    deepseekBalanceChecked: false,
  };
}

export function resetOcrValidationState(target) {
  Object.assign(target, createCredentialState());
}

export function resetDeepSeekBalanceState(target) {
  Object.assign(target, {
    deepseekBalanceCny: null,
    deepseekBalanceChecked: false,
  });
}

export function setDeepSeekBalanceState(target, balanceCny, checked = true) {
  Object.assign(target, {
    deepseekBalanceCny: Number.isFinite(Number(balanceCny)) ? Number(balanceCny) : null,
    deepseekBalanceChecked: Boolean(checked),
  });
}

export function resetOcrValidationCache(target) {
  Object.assign(target, {
    validatedOcrProvider: "",
    validatedOcrToken: "",
    ocrValidationStatus: "",
  });
}

export function setOcrValidationCache(target, {
  provider = "",
  token = "",
  status = "",
} = {}) {
  Object.assign(target, {
    validatedOcrProvider: `${provider || ""}`.trim(),
    validatedOcrToken: `${token || ""}`.trim(),
    ocrValidationStatus: `${status || ""}`.trim(),
  });
}

export function hasValidOcrValidationCache(target, {
  provider = "",
  token = "",
  statuses = ["valid", "skipped"],
} = {}) {
  return target.validatedOcrProvider === `${provider || ""}`.trim()
    && target.validatedOcrToken === `${token || ""}`.trim()
    && statuses.includes(target.ocrValidationStatus);
}

export function getDeepSeekBalanceState(target) {
  return {
    balanceCny: target.deepseekBalanceCny,
    balanceChecked: Boolean(target.deepseekBalanceChecked),
  };
}
