import { buildApiHeaders, isMockMode } from "../config.js";
import { unwrapEnvelope } from "../job.js";
import { getMockJobList } from "../mock.js";
import { buildApiEndpoint } from "./http.js";

export async function fetchLibraryBookList(apiPrefix, { limit = 40, offset = 0, q = "" } = {}) {
  if (isMockMode()) {
    return getMockJobList();
  }
  const params = new URLSearchParams();
  params.set("limit", `${limit}`);
  params.set("offset", `${offset}`);
  if (`${q || ""}`.trim()) {
    params.set("q", `${q || ""}`.trim());
  }
  const resp = await fetch(`${buildApiEndpoint(apiPrefix, "library/books")}?${params.toString()}`, {
    headers: buildApiHeaders(),
  });
  if (!resp.ok) {
    throw new Error(`读取图书馆失败，请稍后重试。(${resp.status})`);
  }
  return unwrapEnvelope(await resp.json());
}

export async function deleteLibraryBook(apiPrefix, jobId, { force = false } = {}) {
  const normalizedJobId = `${jobId || ""}`.trim().replace(/-ocr$/, "");
  if (!normalizedJobId) {
    throw new Error("删除失败: 缺少 job_id");
  }
  const params = force ? "?force=true" : "";
  const resp = await fetch(`${buildApiEndpoint(apiPrefix, `library/books/${encodeURIComponent(normalizedJobId)}`)}${params}`, {
    method: "DELETE",
    headers: buildApiHeaders(),
  });
  if (!resp.ok) {
    throw new Error(`删除任务失败，请稍后重试。(${resp.status})`);
  }
  return unwrapEnvelope(await resp.json());
}
