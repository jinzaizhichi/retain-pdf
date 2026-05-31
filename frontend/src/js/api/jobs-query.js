import { buildApiHeaders, isMockMode } from "../config.js";
import { unwrapEnvelope } from "../job.js";
import {
  getMockJobList,
  getMockJobPayload,
} from "../mock.js";
import { buildJobDetailEndpoint, buildJobsEndpoint } from "./http.js";

export async function fetchJobPayload(jobId, apiPrefix) {
  if (isMockMode()) {
    void apiPrefix;
    return getMockJobPayload(jobId);
  }
  const resp = await fetch(buildJobDetailEndpoint(jobId, apiPrefix), {
    headers: buildApiHeaders(),
  });
  if (!resp.ok) {
    if (resp.status === 404) {
      throw new Error("未找到该任务，请检查 job_id 是否正确。");
    }
    throw new Error(`读取任务失败，请稍后重试。(${resp.status})`);
  }
  return unwrapEnvelope(await resp.json());
}

export async function fetchJobList(
  apiPrefix,
  {
    limit = 20,
    offset = 0,
    status = "",
    workflow = "",
    provider = "",
    scope = "jobs",
    q = "",
  } = {},
) {
  if (isMockMode()) {
    void apiPrefix;
    return getMockJobList();
  }
  const params = new URLSearchParams();
  params.set("limit", `${limit}`);
  params.set("offset", `${offset}`);
  if (status) {
    params.set("status", status);
  }
  if (workflow) {
    params.set("workflow", workflow);
  }
  if (provider) {
    params.set("provider", provider);
  }
  if (`${q || ""}`.trim()) {
    params.set("q", `${q || ""}`.trim());
  }
  const resp = await fetch(`${buildJobsEndpoint(apiPrefix, scope)}?${params.toString()}`, {
    headers: buildApiHeaders(),
  });
  if (!resp.ok) {
    throw new Error(`读取最近任务失败，请稍后重试。(${resp.status})`);
  }
  return unwrapEnvelope(await resp.json());
}
