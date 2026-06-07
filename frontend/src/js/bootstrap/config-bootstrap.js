import {
  applyKeyInputs,
  defaultMineruToken,
  defaultModelApiKey,
  defaultOcrProvider,
  defaultPaddleToken,
} from "../config.js";
import { setDeveloperConfig } from "../state/actions.js";

export function applyPersistedConfig(state, persistedConfig) {
  const browserStored = persistedConfig.browserConfig || {};
  setDeveloperConfig(state, persistedConfig.developerConfig || {});
  applyKeyInputs(
    {
      ocrProvider: browserStored.ocrProvider || defaultOcrProvider(),
      mineruToken: browserStored.mineruToken || defaultMineruToken(),
      paddleToken: browserStored.paddleToken || defaultPaddleToken(),
      modelApiKey: browserStored.modelApiKey || defaultModelApiKey(),
    },
  );
}
