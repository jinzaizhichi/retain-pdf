import { readActiveJobId } from "../job-runtime/active-job-storage.js";
import { isRecentJobActive } from "./card-presenter.js";

export function resolveRecoverableJobId(items = []) {
  const sourceItems = Array.isArray(items) ? items : [];
  const storedJobId = readActiveJobId();
  if (storedJobId) {
    const storedItem = sourceItems.find((item) => `${item?.job_id || ""}`.trim() === storedJobId);
    if (storedItem && !isRecentJobActive(storedItem)) {
      return "";
    }
    return storedJobId;
  }
  const activeItem = sourceItems.find(isRecentJobActive);
  return `${activeItem?.job_id || ""}`.trim();
}
