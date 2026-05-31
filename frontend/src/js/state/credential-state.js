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
