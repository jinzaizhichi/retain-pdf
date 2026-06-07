import { apiBase } from "./config.js";
import {
  currentJobManifest,
  currentJobSnapshot,
} from "./features/job-runtime/runtime-state.js";
import { getUploadState } from "./state/upload-state.js";

function trimString(value) {
  return typeof value === "string" ? value.trim() : "";
}

function stripExtension(filename) {
  const normalized = trimString(filename);
  if (!normalized) {
    return "";
  }
  const index = normalized.lastIndexOf(".");
  if (index <= 0) {
    return normalized;
  }
  return normalized.slice(0, index);
}

function sanitizeFilenamePart(value) {
  return `${value || ""}`.replace(/[\\/:*?"<>|]+/g, "_").trim();
}

function basenameFromUrlLike(value) {
  const raw = trimString(value);
  if (!raw) {
    return "";
  }
  try {
    const parsed = new URL(raw, window.location.href);
    const pathname = parsed.pathname || "";
    const candidate = pathname.split("/").filter(Boolean).pop() || "";
    return decodeURIComponent(candidate);
  } catch (_err) {
    const candidate = raw.split(/[/?#]/)[0]?.split("/").filter(Boolean).pop() || "";
    return candidate;
  }
}

export function resolveOriginalPdfBaseName(state = {}) {
  const snapshot = currentJobSnapshot(state) || {};
  const uploadState = getUploadState(state);
  const requestPayload = snapshot.request_payload || {};
  const rawResponse = snapshot.raw_response || {};
  const sourceArtifact = findReadyManifestArtifact(currentJobManifest(state), "source_pdf");
  const candidates = [
    uploadState.uploadedFileName,
    rawResponse.filename,
    rawResponse.file_name,
    rawResponse.source_file_name,
    rawResponse.display_name,
    rawResponse.original_filename,
    rawResponse.original_file_name,
    rawResponse.book_summary?.source_file_name,
    rawResponse.book_summary?.title,
    requestPayload.filename,
    requestPayload.file_name,
    requestPayload.original_filename,
    requestPayload.original_file_name,
    requestPayload.source_filename,
    requestPayload.source_file_name,
    sourceArtifact?.filename,
    sourceArtifact?.file_name,
    sourceArtifact?.name,
    basenameFromUrlLike(sourceArtifact?.resource_path),
    basenameFromUrlLike(sourceArtifact?.resource_url),
  ];
  const originalName = candidates.find((value) => typeof value === "string" && value.trim()) || "";
  return sanitizeFilenamePart(stripExtension(originalName));
}

export function resolveTranslatedPdfDownloadName(state = {}, fallbackName = "") {
  const originalName = resolveOriginalPdfBaseName(state);
  return originalName ? `zh_${originalName}.pdf` : fallbackName;
}

export function resolveSourcePdfDownloadName(state = {}, fallbackName = "") {
  const originalName = resolveOriginalPdfBaseName(state);
  return originalName ? `${originalName}.pdf` : fallbackName;
}

function ensureTrailingSlash(value) {
  const trimmed = trimString(value);
  if (!trimmed) {
    return "";
  }
  return trimmed.endsWith("/") ? trimmed : `${trimmed}/`;
}

export function toAbsoluteApiUrl(value) {
  const trimmed = trimString(value);
  if (!trimmed) {
    return "";
  }
  if (/^[a-z][a-z\d+\-.]*:/i.test(trimmed)) {
    return trimmed;
  }
  if (trimmed.startsWith("/")) {
    return `${apiBase()}${trimmed}`;
  }
  return `${apiBase()}/${trimmed.replace(/^\.?\//, "")}`;
}

export function findReadyManifestArtifact(manifestPayload, artifactKey) {
  const items = Array.isArray(manifestPayload?.items) ? manifestPayload.items : [];
  return items.find((entry) => entry?.artifact_key === artifactKey && entry?.ready) || null;
}

export function hasReadyManifestArtifact(manifestPayload, artifactKey) {
  return Boolean(findReadyManifestArtifact(manifestPayload, artifactKey));
}

export function resolveManifestArtifactUrl(
  manifestPayload,
  artifactKey,
  { includeJobDir = false } = {},
) {
  const item = findReadyManifestArtifact(manifestPayload, artifactKey);
  const raw = trimString(item?.resource_url || item?.resource_path);
  if (!raw) {
    return "";
  }
  const absolute = toAbsoluteApiUrl(raw);
  if (!includeJobDir || artifactKey !== "markdown_bundle_zip") {
    return absolute;
  }
  const separator = absolute.includes("?") ? "&" : "?";
  return `${absolute}${separator}include_job_dir=true`;
}

export function resolveJobMarkdownContract(job) {
  const artifacts = job?.artifacts || {};
  const markdown = artifacts.markdown || {};
  const actions = job?.actions || {};
  const ready = Boolean(
    markdown.ready
    ?? artifacts.markdown_ready
    ?? job?.markdown_ready
    ?? actions.open_markdown?.enabled
    ?? actions.open_markdown_raw?.enabled
  );
  return {
    ready,
    jsonUrl: toAbsoluteApiUrl(markdown.json_url || markdown.json_path || actions.open_markdown?.url || actions.open_markdown?.path),
    rawUrl: toAbsoluteApiUrl(markdown.raw_url || markdown.raw_path || actions.open_markdown_raw?.url || actions.open_markdown_raw?.path),
    imagesBaseUrl: ensureTrailingSlash(toAbsoluteApiUrl(
      markdown.images_base_url || markdown.images_base_path || artifacts.markdown_images_base_url
    )),
    fileName: trimString(markdown.file_name),
    sizeBytes: Number.isFinite(Number(markdown.size_bytes)) ? Number(markdown.size_bytes) : null,
  };
}

export function resolveMarkdownAssetUrl(imagesBaseUrl, relativePath) {
  const target = trimString(relativePath);
  if (!target) {
    return "";
  }
  if (/^(?:data:|blob:|https?:\/\/|#)/i.test(target)) {
    return target;
  }
  if (target.startsWith("/")) {
    return toAbsoluteApiUrl(target);
  }
  const base = ensureTrailingSlash(imagesBaseUrl);
  if (!base) {
    return target;
  }
  return new URL(target, base).toString();
}

function normalizeMarkdownImageTarget(rawTarget) {
  const trimmed = trimString(rawTarget);
  if (!trimmed) {
    return "";
  }
  let normalized = trimmed;
  const titleIndex = normalized.search(/\s+["']/);
  if (titleIndex > 0) {
    normalized = normalized.slice(0, titleIndex);
  }
  if (normalized.startsWith("<") && normalized.endsWith(">")) {
    normalized = normalized.slice(1, -1).trim();
  }
  return normalized;
}

export function collectMarkdownImageRefs(content) {
  const text = `${content || ""}`;
  if (!text.trim()) {
    return [];
  }
  const refs = [];
  const seen = new Set();

  const pushRef = (candidate) => {
    const normalized = normalizeMarkdownImageTarget(candidate);
    if (!normalized || seen.has(normalized)) {
      return;
    }
    seen.add(normalized);
    refs.push(normalized);
  };

  const htmlImgPattern = /<img\b[^>]*\bsrc=(["'])(.*?)\1[^>]*>/gi;
  for (const match of text.matchAll(htmlImgPattern)) {
    pushRef(match[2]);
  }

  const markdownImgPattern = /!\[[^\]]*]\(([^)]+)\)/g;
  for (const match of text.matchAll(markdownImgPattern)) {
    pushRef(match[1]);
  }

  return refs;
}
