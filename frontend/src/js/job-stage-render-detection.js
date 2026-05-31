const RENDER_TEXT_MARKERS = [
  "render",
  "typst",
  "prewarm",
  "geometry",
  "overlay",
  "compile",
  "layout page",
  "page specs",
  "pdf render",
  "生成 typst",
  "渲染",
];

export function eventLooksLikeRender(item = {}) {
  const text = [
    item.stage,
    item.provider_stage,
    item.user_stage,
    item.substage,
    item.stage_detail,
    item.message,
    item.payload?.stage,
    item.payload?.provider_stage,
    item.payload?.user_stage,
    item.payload?.substage,
    item.payload?.stage_detail,
    item.payload?.message,
  ].map((value) => `${value || ""}`.toLowerCase()).join(" ");
  return RENDER_TEXT_MARKERS.some((marker) => text.includes(marker));
}

