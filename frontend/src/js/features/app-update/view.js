import { APP_VERSION } from "../../generated/app-version.js";

function updateButton() {
  return document.getElementById("app-update-btn");
}

function updateDialog() {
  return document.getElementById("app-update-dialog");
}

function updateStatus() {
  return document.getElementById("app-update-status");
}

function setStatusText(text) {
  const status = updateStatus();
  if (!status) {
    return;
  }
  status.classList.toggle("hidden", !text);
  status.textContent = text;
}

function formatReleaseNotes(markdown = "") {
  return `${markdown || ""}`
    .replace(/\r\n/g, "\n")
    .split("\n")
    .map((line) => line
      .replace(/^#{1,6}\s+/, "")
      .replace(/^\s*[-*]\s+/, "• ")
      .replace(/\*\*([^*]+)\*\*/g, "$1")
      .replace(/`([^`]+)`/g, "$1")
      .trimEnd())
    .filter((line, index, lines) => line || (index > 0 && lines[index - 1]))
    .join("\n")
    .trim();
}

function setPanelContent({ title = "检查更新", body = "", latestVersion = "", currentVersion = APP_VERSION, htmlUrl = "" } = {}) {
  const dialog = updateDialog();
  if (!dialog) {
    return;
  }
  const note = `${body || ""}`.trim();
  dialog.querySelector("[data-update-title]").textContent = title;
  dialog.querySelector("[data-update-version]").textContent = latestVersion
    ? `当前 ${currentVersion} · 最新 ${latestVersion}`
    : `当前 ${currentVersion}`;
  dialog.querySelector("[data-update-notes]").textContent = formatReleaseNotes(note) || "暂无更新说明。";
  const link = dialog.querySelector("[data-update-link]");
  link.href = htmlUrl || "#";
  link.classList.toggle("hidden", !htmlUrl);
}

export function openUpdateDialog() {
  const dialog = updateDialog();
  if (!dialog) {
    return;
  }
  if (!dialog.open) {
    dialog.showModal();
  }
}

export function setUpdateChecking() {
  const button = updateButton();
  if (!button) {
    return;
  }
  button.dataset.updateState = "checking";
  button.setAttribute("title", "正在检查更新");
  setStatusText("正在检查 GitHub Releases...");
  setPanelContent({
    title: "正在检查更新",
    body: "正在连接 GitHub Releases...",
  });
}

export function setUpdateReady() {
  const button = updateButton();
  if (!button) {
    return;
  }
  button.dataset.updateState = "idle";
  button.classList.remove("has-update");
  button.setAttribute("title", "检查更新");
  setStatusText("");
  setPanelContent({
    title: "检查更新",
    body: "点击“重新检查”从 GitHub Releases 获取最新版本。",
  });
}

export function setUpdateAvailable(info) {
  const button = updateButton();
  if (!button) {
    return;
  }
  button.dataset.updateState = "available";
  button.classList.add("has-update");
  button.setAttribute("title", `发现新版本 ${info.latestVersion}`);
  setStatusText("发现新版本");
  setPanelContent({
    title: info.title || `RetainPDF ${info.latestVersion}`,
    body: info.body,
    latestVersion: info.latestVersion,
    currentVersion: info.currentVersion,
    htmlUrl: info.htmlUrl,
  });
}

export function setUpdateLatest(info) {
  const button = updateButton();
  if (!button) {
    return;
  }
  button.dataset.updateState = "latest";
  button.classList.remove("has-update");
  button.setAttribute("title", "已是最新版本");
  setStatusText("已是最新版本");
  setPanelContent({
    title: "已是最新版本",
    body: "当前版本已经是 GitHub Releases 上的最新版本。",
    latestVersion: info?.latestVersion || APP_VERSION,
    currentVersion: info?.currentVersion || APP_VERSION,
    htmlUrl: info?.htmlUrl || "",
  });
}

export function setUpdateError(error) {
  const button = updateButton();
  if (!button) {
    return;
  }
  button.dataset.updateState = "error";
  button.classList.remove("has-update");
  button.setAttribute("title", "检查更新失败");
  setStatusText("检查失败");
  setPanelContent({
    title: "检查更新失败",
    body: error?.message || "暂时无法连接 GitHub Releases。",
  });
}

export function bindUpdateButton({ onCheck } = {}) {
  updateButton()?.addEventListener("click", () => {
    openUpdateDialog();
  });
  document.getElementById("app-update-check-btn")?.addEventListener("click", () => {
    onCheck?.();
  });
}
