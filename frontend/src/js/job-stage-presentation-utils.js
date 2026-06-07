export function stageRank(stageKey) {
  return {
    queued: 0,
    ocr: 1,
    translate: 2,
    render: 3,
    done: 4,
  }[stageKey] ?? 0;
}

export function numberOrNull(value) {
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

export function firstNumber(...values) {
  for (const value of values) {
    const num = numberOrNull(value);
    if (num !== null) {
      return num;
    }
  }
  return null;
}

export function progressUnitPriority(unit = "") {
  switch (`${unit || ""}`.trim()) {
    case "page":
    case "batch":
      return 3;
    case "percent":
      return 2;
    case "step":
      return 1;
    default:
      return 0;
  }
}

export function eventIdentity(item = {}) {
  const seq = Number(item.seq);
  const ts = Date.parse(item.ts || item.created_at || "");
  return {
    seq: Number.isFinite(seq) ? seq : null,
    ts: Number.isFinite(ts) ? ts : null,
  };
}

export function eventLaneOf(item = {}) {
  const payload = item?.payload && typeof item.payload === "object" ? item.payload : {};
  return `${item?.lane || payload.lane || ""}`.trim().toLowerCase();
}

export function isMainLaneEvent(item = {}) {
  const lane = eventLaneOf(item);
  return !lane || lane === "main";
}

export function normalizeUserStage(value = "") {
  const stage = `${value || ""}`.trim().toLowerCase();
  return stage === "translation" ? "translate" : stage;
}

function normalizeDisplayStage(value = "") {
  const stage = normalizeUserStage(value);
  return stage === "translating" ? "translate" : stage;
}

export function canonicalStageOf(payload = {}) {
  const nestedPayload = payload?.payload && typeof payload.payload === "object" ? payload.payload : {};
  const candidates = [
    payload.display_stage,
    nestedPayload.display_stage,
    payload.user_stage,
    nestedPayload.user_stage,
    payload.stage,
    nestedPayload.stage,
  ];
  for (let index = 0; index < candidates.length; index += 1) {
    const normalized = index < 2 ? normalizeDisplayStage(candidates[index]) : normalizeUserStage(candidates[index]);
    if (["ocr", "translate", "render", "done"].includes(normalized)) {
      return normalized;
    }
  }
  return "";
}

export function progressUnitOf(payload = {}) {
  const nestedPayload = payload?.payload && typeof payload.payload === "object" ? payload.payload : {};
  return `${payload?.progress_unit
    || payload?.progress?.unit
    || nestedPayload.progress_unit
    || nestedPayload.progress?.unit
    || ""}`.trim().toLowerCase();
}

export function compareProgressEventOrder(previous, next) {
  if (!previous) {
    return 1;
  }
  const previousSeq = Number(previous.seq);
  const nextSeq = Number(next.seq);
  if (Number.isFinite(previousSeq) && Number.isFinite(nextSeq) && nextSeq !== previousSeq) {
    return nextSeq > previousSeq ? 1 : -1;
  }
  const previousTs = Date.parse(previous.ts || "");
  const nextTs = Date.parse(next.ts || "");
  if (Number.isFinite(previousTs) && Number.isFinite(nextTs) && nextTs !== previousTs) {
    return nextTs > previousTs ? 1 : -1;
  }
  return 1;
}
