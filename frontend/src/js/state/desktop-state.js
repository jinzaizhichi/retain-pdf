export function createDesktopState() {
  return {
    desktopMode: false,
    desktopConfigured: false,
  };
}

export function setDesktopMode(target, value = true) {
  target.desktopMode = Boolean(value);
}

export function setDesktopConfigured(target, value = false) {
  target.desktopConfigured = Boolean(value);
}

export function isDesktopMode(target) {
  return Boolean(target.desktopMode);
}

export function isDesktopConfigured(target) {
  return Boolean(target.desktopConfigured);
}
