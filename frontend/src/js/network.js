import { apiBase, buildApiHeaders, frontendApiKey, isMockMode } from "./config.js";
import { unwrapEnvelope } from "./job.js";
import {
  fetchMockProtected,
  getMockJobArtifactsManifest,
  getMockJobEvents,
  getMockJobList,
  getMockJobMarkdown,
  getMockJobPayload,
  submitMockJob,
  submitMockUpload,
} from "./mock.js";

export async function fetchJobPayload(jobId, apiPrefix) {
  if (isMockMode()) {
    void apiPrefix;
    return getMockJobPayload(jobId);
  }
  const resp = await fetch(`${apiBase()}${apiPrefix}/jobs/${jobId}`, {
    headers: buildApiHeaders(),
  });
  if (!resp.ok) {
    if (resp.status === 404) {
      throw new Error("未找到该任务，请检查 job_id 是否正确。");
    }
    throw new Error(`读取任务失败，请稍后重试。(${resp.status})`);
  }
  const payloadJson = await resp.json();
  return unwrapEnvelope(payloadJson);
}

export async function fetchJobEvents(jobId, apiPrefix, limit = 50, offset = 0) {
  if (isMockMode()) {
    void jobId;
    void apiPrefix;
    const payload = getMockJobEvents();
    return { ...payload, limit, offset };
  }
  const resp = await fetch(`${apiBase()}${apiPrefix}/jobs/${jobId}/events?limit=${limit}&offset=${offset}`, {
    headers: buildApiHeaders(),
  });
  if (!resp.ok) {
    if (resp.status === 404) {
      return { items: [], limit, offset };
    }
    throw new Error(`读取事件流失败，请稍后重试。(${resp.status})`);
  }
  const payloadJson = await resp.json();
  return unwrapEnvelope(payloadJson);
}

export async function fetchJobArtifactsManifest(jobId, apiPrefix) {
  if (isMockMode()) {
    void jobId;
    void apiPrefix;
    return getMockJobArtifactsManifest();
  }
  const resp = await fetch(`${apiBase()}${apiPrefix}/jobs/${jobId}/artifacts-manifest`, {
    headers: buildApiHeaders(),
  });
  if (!resp.ok) {
    if (resp.status === 404) {
      return { items: [] };
    }
    throw new Error(`读取产物清单失败，请稍后重试。(${resp.status})`);
  }
  const payloadJson = await resp.json();
  return unwrapEnvelope(payloadJson);
}

export async function fetchJobMarkdown(jobId, apiPrefix) {
  if (isMockMode()) {
    void jobId;
    void apiPrefix;
    return getMockJobMarkdown();
  }
  const resp = await fetch(`${apiBase()}${apiPrefix}/jobs/${jobId}/markdown`, {
    headers: buildApiHeaders(),
  });
  if (!resp.ok) {
    if (resp.status === 404) {
      return null;
    }
    throw new Error(`读取 Markdown 失败，请稍后重试。(${resp.status})`);
  }
  const payloadJson = await resp.json();
  return unwrapEnvelope(payloadJson);
}

export async function fetchTranslationDiagnostics(jobId, apiPrefix) {
  if (isMockMode()) {
    return {
      job_id: jobId,
      summary: {
        schema: "translation_diagnostics_v1",
        counts: {},
        final_status_counts: {},
      },
    };
  }
  const resp = await fetch(`${apiBase()}${apiPrefix}/jobs/${jobId}/translation/diagnostics`, {
    headers: buildApiHeaders(),
  });
  if (!resp.ok) {
    if (resp.status === 404) {
      throw new Error("未找到翻译调试信息，请确认该任务已完成翻译。");
    }
    throw new Error(`读取翻译调试摘要失败，请稍后重试。(${resp.status})`);
  }
  const payloadJson = await resp.json();
  return unwrapEnvelope(payloadJson);
}

export async function fetchTranslationItems(
  jobId,
  apiPrefix,
  {
    limit = 20,
    offset = 0,
    page = "",
    finalStatus = "",
    errorType = "",
    route = "",
    q = "",
  } = {},
) {
  if (isMockMode()) {
    return {
      items: [],
      total: 0,
      limit,
      offset,
    };
  }
  const params = new URLSearchParams();
  params.set("limit", `${limit}`);
  params.set("offset", `${offset}`);
  if (`${page ?? ""}`.trim()) {
    params.set("page", `${page}`.trim());
  }
  if (`${finalStatus ?? ""}`.trim()) {
    params.set("final_status", `${finalStatus}`.trim());
  }
  if (`${errorType ?? ""}`.trim()) {
    params.set("error_type", `${errorType}`.trim());
  }
  if (`${route ?? ""}`.trim()) {
    params.set("route", `${route}`.trim());
  }
  if (`${q ?? ""}`.trim()) {
    params.set("q", `${q}`.trim());
  }
  const resp = await fetch(
    `${apiBase()}${apiPrefix}/jobs/${jobId}/translation/items?${params.toString()}`,
    {
      headers: buildApiHeaders(),
    },
  );
  if (!resp.ok) {
    if (resp.status === 404) {
      return { items: [], total: 0, limit, offset };
    }
    throw new Error(`读取翻译调试列表失败，请稍后重试。(${resp.status})`);
  }
  const payloadJson = await resp.json();
  return unwrapEnvelope(payloadJson);
}

export async function fetchTranslationItem(jobId, itemId, apiPrefix) {
  if (isMockMode()) {
    return {
      job_id: jobId,
      item_id: itemId,
      page_idx: 0,
      page_number: 1,
      page_path: "",
      item: {},
    };
  }
  const resp = await fetch(`${apiBase()}${apiPrefix}/jobs/${jobId}/translation/items/${itemId}`, {
    headers: buildApiHeaders(),
  });
  if (!resp.ok) {
    if (resp.status === 404) {
      throw new Error("未找到该翻译 item，请确认 item_id 是否正确。");
    }
    throw new Error(`读取翻译 item 详情失败，请稍后重试。(${resp.status})`);
  }
  const payloadJson = await resp.json();
  return unwrapEnvelope(payloadJson);
}

export async function replayTranslationItem(jobId, itemId, apiPrefix) {
  if (isMockMode()) {
    return {
      job_id: jobId,
      item_id: itemId,
      payload: {
        policy_before: {},
        policy_after: {},
        replay_result: {},
        replay_error: null,
      },
    };
  }
  const resp = await fetch(
    `${apiBase()}${apiPrefix}/jobs/${jobId}/translation/items/${itemId}/replay`,
    {
      method: "POST",
      headers: buildApiHeaders(),
    },
  );
  if (!resp.ok) {
    const contentType = resp.headers.get("content-type") || "";
    if (resp.status === 404) {
      throw new Error("未找到该翻译 item，无法重放。");
    }
    if (contentType.includes("application/json")) {
      const errorPayload = await resp.json();
      throw new Error(`重放翻译 item 失败: ${errorPayload.message || JSON.stringify(errorPayload)}`);
    }
    const text = await resp.text();
    throw new Error(`重放翻译 item 失败: ${resp.status} ${text}`);
  }
  const payloadJson = await resp.json();
  return unwrapEnvelope(payloadJson);
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
  const normalizedScope = scope === "ocr" ? "ocr/jobs" : "jobs";
  const resp = await fetch(`${apiBase()}${apiPrefix}/${normalizedScope}?${params.toString()}`, {
    headers: buildApiHeaders(),
  });
  if (!resp.ok) {
    throw new Error(`读取最近任务失败，请稍后重试。(${resp.status})`);
  }
  const payloadJson = await resp.json();
  return unwrapEnvelope(payloadJson);
}

export function submitUploadRequest(url, form, onProgress) {
  if (isMockMode()) {
    void url;
    void form;
    onProgress?.(1, 1);
    return Promise.resolve(submitMockUpload());
  }
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.responseType = "json";
    const apiKey = frontendApiKey();
    if (apiKey) {
      xhr.setRequestHeader("X-API-KEY", apiKey);
    }

    xhr.upload.addEventListener("progress", (event) => {
      if (!onProgress) {
        return;
      }
      if (event.lengthComputable) {
        onProgress(event.loaded, event.total);
      } else {
        onProgress(NaN, NaN);
      }
    });

    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(unwrapEnvelope(xhr.response));
        return;
      }
      const message = typeof xhr.response === "object" && xhr.response
        ? (xhr.response.message || JSON.stringify(xhr.response))
        : (xhr.responseText || "");
      reject(new Error(`提交失败: ${xhr.status} ${message}`));
    });

    xhr.addEventListener("error", () => {
      reject(new Error(`提交失败: 网络错误。当前 API Base 为 ${apiBase()}，上传地址为 ${url}。请确认本地服务已经启动。`));
    });

    xhr.send(form);
  });
}

export async function submitJson(url, payload) {
  if (isMockMode()) {
    void payload;
    if (/\/jobs(?:$|\?)/.test(url)) {
      return submitMockJob();
    }
    if (/\/cancel(?:$|\?)/.test(url)) {
      return { ok: true };
    }
  }
  const resp = await fetch(url, {
    method: "POST",
    headers: buildApiHeaders({
      "Content-Type": "application/json",
    }),
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    const contentType = resp.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      const errorPayload = await resp.json();
      throw new Error(`提交失败: ${resp.status} ${errorPayload.message || JSON.stringify(errorPayload)}`);
    }
    const text = await resp.text();
    throw new Error(`提交失败: ${resp.status} ${text}`);
  }
  const payloadJson = await resp.json();
  return unwrapEnvelope(payloadJson);
}

export async function validateMineruToken(apiPrefix, payload) {
  if (isMockMode()) {
    void apiPrefix;
    void payload;
    return {
      ok: true,
      valid: true,
      summary: "mock mode: token validation skipped",
    };
  }
  return submitJson(`${apiBase()}${apiPrefix}/providers/mineru/validate-token`, payload);
}

export async function fetchProtected(url, options = {}) {
  if (isMockMode() && `${url || ""}`.startsWith("mock://")) {
    return fetchMockProtected(url);
  }
  const headers = buildApiHeaders(options.headers || {});
  return fetch(url, {
    ...options,
    headers,
  });
}
