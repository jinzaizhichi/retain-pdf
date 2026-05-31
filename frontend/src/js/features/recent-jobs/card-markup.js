import { recentJobCardMarkup } from "./card-template.js";

export function buildRecentJobsMarkup(items) {
  return (Array.isArray(items) ? items : []).map((item) => recentJobCardMarkup(item)).join("");
}
