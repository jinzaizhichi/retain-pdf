import { buildFrontendPageUrl } from "../../config.js";
import { resolveManifestArtifactUrl } from "../../job-artifacts.js";
import {
  currentJobManifest,
  currentJobSnapshot,
} from "../job-runtime/runtime-state.js";
import {
  resolveJobActions,
  resolveJobSourcePdfAction,
} from "../../job.js";

export function jobIdFromReaderUrl(url) {
  const raw = `${url || ""}`.trim();
  if (!raw) {
    return "";
  }
  try {
    return new URL(raw, window.location.href).searchParams.get("job_id")?.trim() || "";
  } catch (_err) {
    return "";
  }
}

export function currentReaderArtifactUrls(state) {
  const manifest = currentJobManifest(state);
  const job = currentJobSnapshot(state);
  const actions = job ? resolveJobActions(job) : null;
  const sourcePdfAction = job ? resolveJobSourcePdfAction(job, manifest) : null;
  const sourcePdf = sourcePdfAction?.url || resolveManifestArtifactUrl(manifest, "source_pdf");
  const translatedPdf = actions?.pdf || resolveManifestArtifactUrl(manifest, "pdf")
    || resolveManifestArtifactUrl(manifest, "translated_pdf")
    || resolveManifestArtifactUrl(manifest, "result_pdf");
  return { sourcePdf, translatedPdf };
}

export function buildReaderPageUrl(jobId) {
  const normalizedJobId = `${jobId || ""}`.trim();
  if (!normalizedJobId) {
    return "";
  }
  return buildFrontendPageUrl("./reader.html", {
    job_id: normalizedJobId,
  });
}

export function buildReaderRouteUrl(jobId) {
  const normalizedJobId = `${jobId || ""}`.trim();
  const url = new URL(window.location.href);
  if (!normalizedJobId) {
    url.searchParams.delete("view");
    url.searchParams.delete("job_id");
    return url.toString();
  }
  url.searchParams.set("job_id", normalizedJobId);
  url.searchParams.set("view", "reader");
  return url.toString();
}

export function requestedReaderJobIdFromLocation() {
  const url = new URL(window.location.href);
  const view = `${url.searchParams.get("view") || ""}`.trim();
  const jobId = `${url.searchParams.get("job_id") || ""}`.trim();
  return view === "reader" && jobId ? jobId : "";
}
