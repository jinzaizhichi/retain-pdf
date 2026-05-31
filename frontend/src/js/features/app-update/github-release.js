import { APP_VERSION, GITHUB_REPO } from "../../generated/app-version.js";

const GITHUB_LATEST_RELEASE_URL = `https://api.github.com/repos/${GITHUB_REPO}/releases/latest`;

function normalizeVersion(value = "") {
  return `${value || ""}`.trim().replace(/^v/i, "");
}

function versionParts(value = "") {
  const normalized = normalizeVersion(value).split(/[.+-]/)[0] || "";
  return normalized.split(".").map((part) => {
    const num = Number(part);
    return Number.isFinite(num) ? num : 0;
  });
}

export function isNewerVersion(latest = "", current = APP_VERSION) {
  const latestParts = versionParts(latest);
  const currentParts = versionParts(current);
  const length = Math.max(latestParts.length, currentParts.length);
  for (let index = 0; index < length; index += 1) {
    const latestPart = latestParts[index] || 0;
    const currentPart = currentParts[index] || 0;
    if (latestPart > currentPart) {
      return true;
    }
    if (latestPart < currentPart) {
      return false;
    }
  }
  return false;
}

export async function fetchLatestGithubRelease() {
  const resp = await fetch(GITHUB_LATEST_RELEASE_URL, {
    headers: {
      Accept: "application/vnd.github+json",
    },
  });
  if (!resp.ok) {
    throw new Error(`检查更新失败: GitHub ${resp.status}`);
  }
  return await resp.json();
}

export function normalizeReleaseInfo(release = {}) {
  const latestVersion = release.tag_name || release.name || "";
  return {
    currentVersion: APP_VERSION,
    latestVersion,
    hasUpdate: isNewerVersion(latestVersion, APP_VERSION),
    title: release.name || latestVersion || "RetainPDF 更新",
    body: release.body || "",
    htmlUrl: release.html_url || `https://github.com/${GITHUB_REPO}/releases`,
    publishedAt: release.published_at || "",
  };
}
