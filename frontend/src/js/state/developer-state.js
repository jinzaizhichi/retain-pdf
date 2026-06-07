export function createDeveloperState() {
  return {
    developerConfig: {},
  };
}

export function setDeveloperConfig(target, config = {}) {
  target.developerConfig = config && typeof config === "object" ? { ...config } : {};
}

export function resetDeveloperConfig(target) {
  target.developerConfig = {};
}

export function getDeveloperConfig(target) {
  return target.developerConfig && typeof target.developerConfig === "object"
    ? target.developerConfig
    : {};
}
