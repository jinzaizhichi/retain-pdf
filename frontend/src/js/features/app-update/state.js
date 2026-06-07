import { APP_VERSION } from "../../generated/app-version.js";

const CACHE_KEY = "retainpdf:update-check:v1";
const CACHE_TTL_MS = 24 * 60 * 60 * 1000;

function isObject(value) {
  return value && typeof value === "object" && !Array.isArray(value);
}

function normalizeCachedInfo(value) {
  if (!isObject(value)) {
    return null;
  }
  const checkedAt = Number(value.checkedAt);
  const latestVersion = `${value.latestVersion || ""}`.trim();
  if (!Number.isFinite(checkedAt) || !latestVersion) {
    return null;
  }
  return {
    checkedAt,
    currentVersion: value.currentVersion || APP_VERSION,
    latestVersion,
    hasUpdate: Boolean(value.hasUpdate),
    title: value.title || latestVersion,
    body: value.body || "",
    htmlUrl: value.htmlUrl || "",
    publishedAt: value.publishedAt || "",
  };
}

export function readUpdateCache(now = Date.now()) {
  try {
    const cached = normalizeCachedInfo(JSON.parse(window.localStorage.getItem(CACHE_KEY) || "null"));
    if (!cached) {
      return { info: null, fresh: false };
    }
    return {
      info: cached,
      fresh: now - cached.checkedAt < CACHE_TTL_MS,
    };
  } catch {
    return { info: null, fresh: false };
  }
}

export function writeUpdateCache(info, now = Date.now()) {
  if (!info) {
    return;
  }
  try {
    const cached = {
      checkedAt: now,
      currentVersion: info.currentVersion || APP_VERSION,
      latestVersion: info.latestVersion || "",
      hasUpdate: Boolean(info.hasUpdate),
      title: info.title || "",
      body: info.body || "",
      htmlUrl: info.htmlUrl || "",
      publishedAt: info.publishedAt || "",
    };
    window.localStorage.setItem(CACHE_KEY, JSON.stringify(cached));
  } catch {
    // Cache failures should never affect update checks.
  }
}
