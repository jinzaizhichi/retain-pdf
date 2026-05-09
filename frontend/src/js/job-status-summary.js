function numberOrNull(value) {
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

function firstNonEmpty(...values) {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return "";
}

function stageKeyOf(payload) {
  return firstNonEmpty(payload.current_stage, payload.stage, payload.runtime?.current_stage).toLowerCase();
}

const USER_STAGE_FLOW = [
  {
    key: "ocr",
    label: "OCR 解析",
    detail: "正在识别 PDF 内容",
    matches: ["ocr", "parse", "mineru", "paddle", "normaliz", "document"],
  },
  {
    key: "translate",
    label: "翻译",
    detail: "正在翻译正文内容",
    matches: ["translat"],
  },
  {
    key: "render",
    label: "渲染",
    detail: "正在生成翻译后的 PDF",
    matches: ["render", "sav"],
  },
];

const USER_STAGE_TOTAL = USER_STAGE_FLOW.length + 1;

const DETAIL_TEXT_MAP = [
  {
    matches: ["queue", "queued", "pending", "执行槽位", "排队"],
    detail: "排队中，等待可用执行槽位",
  },
  {
    matches: ["启动 ocr", "ocr 子任务", "ocr job"],
    detail: "正在启动 OCR 子任务",
  },
  {
    matches: ["normaliz", "标准化", "standard", "document"],
    detail: "正在整理 OCR 结果",
  },
  {
    matches: ["continuation_review", "跨栏", "跨页", "连续段"],
    detail: "正在判断跨栏/跨页连续段",
  },
  {
    matches: ["page_policies", "页面策略", "块分类", "分类"],
    detail: "正在判断正文与保留排版内容",
  },
  {
    matches: ["garbled", "乱码"],
    detail: "正在修复乱码候选段",
  },
  {
    matches: ["翻译完成", "开始渲染", "render", "渲染", "生成 pdf"],
    detail: "正在生成翻译后的 PDF",
  },
  {
    matches: ["ocr 完成", "开始翻译", "translat", "翻译"],
    detail: "正在翻译正文内容",
  },
  {
    matches: ["sav", "保存"],
    detail: "正在保存结果文件",
  },
];

function normalizedStageText(payload) {
  const stageKey = stageKeyOf(payload);
  const detail = firstNonEmpty(payload.stage_detail, payload.runtime?.current_stage);
  return `${stageKey} ${detail}`.toLowerCase();
}

function detailForPayload(payload, fallback) {
  const rawDetail = firstNonEmpty(payload.stage_detail, payload.runtime?.current_stage);
  const text = `${stageKeyOf(payload)} ${rawDetail}`.toLowerCase();
  const mapped = DETAIL_TEXT_MAP.find((item) => item.matches.some((keyword) => text.includes(keyword)));
  if (mapped) {
    return mapped.detail;
  }
  return rawDetail || fallback;
}

function userStageFlowIndex(text) {
  if (["render", "渲染", "生成 pdf", "sav", "保存"].some((keyword) => text.includes(keyword))) {
    return USER_STAGE_FLOW.findIndex((stage) => stage.key === "render");
  }
  if ([
    "translat",
    "开始翻译",
    "翻译",
    "continuation_review",
    "page_policies",
    "garbled",
    "跨栏",
    "跨页",
    "连续段",
    "页面策略",
    "块分类",
    "乱码",
  ].some((keyword) => text.includes(keyword))) {
    return USER_STAGE_FLOW.findIndex((stage) => stage.key === "translate");
  }
  if (["ocr", "parse", "mineru", "paddle", "normaliz", "standard", "document", "标准化"].some((keyword) => text.includes(keyword))) {
    return USER_STAGE_FLOW.findIndex((stage) => stage.key === "ocr");
  }
  return -1;
}

function userStageFor(payload) {
  const text = normalizedStageText(payload);
  if (payload.status === "succeeded") {
    return {
      key: "done",
      label: "完成",
      detail: "翻译 PDF 已生成",
      step: USER_STAGE_TOTAL,
      total: USER_STAGE_TOTAL,
    };
  }
  if (payload.status === "failed") {
    return {
      key: "failed",
      label: "失败",
      detail: "任务失败，请查看详情",
      step: null,
      total: USER_STAGE_TOTAL,
    };
  }
  if (payload.status === "canceled") {
    return {
      key: "canceled",
      label: "已取消",
      detail: "任务已取消",
      step: null,
      total: USER_STAGE_TOTAL,
    };
  }
  if (payload.status === "queued" || text.includes("queue") || text.includes("pending") || text.includes("排队")) {
    return {
      key: "queued",
      label: "排队中",
      detail: detailForPayload(payload, "等待可用执行槽位"),
      step: null,
      total: USER_STAGE_TOTAL,
    };
  }
  const matchIndex = userStageFlowIndex(text);
  if (matchIndex >= 0) {
    const stage = USER_STAGE_FLOW[matchIndex];
    return {
      ...stage,
      detail: detailForPayload(payload, stage.detail),
      step: matchIndex + 1,
      total: USER_STAGE_TOTAL,
    };
  }
  if (payload.status === "running") {
    return {
      key: "running",
      label: "处理中",
      detail: detailForPayload(payload, "正在处理任务"),
      step: null,
      total: USER_STAGE_TOTAL,
    };
  }
  return {
    key: "idle",
    label: "等待中",
    detail: "等待任务开始",
    step: null,
    total: USER_STAGE_TOTAL,
  };
}

function userStageLabel(payload) {
  const stage = userStageFor(payload);
  if (stage.step && stage.total && payload.status !== "succeeded") {
    return `第 ${stage.step}/${stage.total} 步 · ${stage.label}`;
  }
  return stage.label;
}

export function summarizeStageProgressText(payload) {
  const current = numberOrNull(payload.progress_current ?? payload.progress?.current);
  const total = numberOrNull(payload.progress_total ?? payload.progress?.total);
  if (current === null || total === null || total <= 0) {
    return "";
  }
  const stageKey = stageKeyOf(payload);
  const stage = userStageFor(payload);
  if (stageKey.includes("continuation") || stageKey.includes("page_policies")) {
    return `第 ${current}/${total} 页`;
  }
  if (stage.key === "translate") {
    return `第 ${current}/${total} 批`;
  }
  if (stage.key === "ocr") {
    return `第 ${current}/${total} 页`;
  }
  if (stage.key === "render") {
    return `第 ${current}/${total} 页`;
  }
  return `进度 ${current}/${total}`;
}

export function summarizeStageLabel(payload) {
  return userStageLabel(payload);
}

export function summarizeStageKey(payload) {
  return userStageFor(payload).key;
}

export function summarizeStageDetail(payload) {
  const failureDetail = firstNonEmpty(payload.failure?.summary);
  if (failureDetail) {
    return failureDetail;
  }
  const stage = userStageFor(payload);
  return stage.detail || stage.label || "-";
}
