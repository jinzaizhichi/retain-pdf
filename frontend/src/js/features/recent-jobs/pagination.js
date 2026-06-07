export const RECENT_JOBS_PAGE_SIZE = 24;

export function dedupeRecentJobs(items) {
  const seen = new Set();
  const result = [];
  for (const item of Array.isArray(items) ? items : []) {
    const jobId = `${item?.job_id || ""}`.trim();
    if (!jobId || seen.has(jobId)) {
      continue;
    }
    seen.add(jobId);
    result.push(item);
  }
  return result;
}

export function isPrimaryRecentJob(item) {
  const workflow = `${item?.workflow || item?.job_type || ""}`.trim();
  const jobId = `${item?.job_id || ""}`.trim();
  if (workflow === "ocr") {
    return false;
  }
  if (jobId.endsWith("-ocr")) {
    return false;
  }
  return true;
}

export async function collectRecentJobsPage({
  fetchJobList,
  fetchLibraryBookList,
  apiPrefix,
  startOffset,
  pageSize,
  existingJobIds = new Set(),
  query = "",
}) {
  const fetchLimit = Math.max(pageSize, 20);
  const collected = [];
  const seenJobIds = new Set(existingJobIds);
  let latestInvocationSummary = null;
  let nextOffset = startOffset;
  let hasMore = true;

  while (collected.length < pageSize) {
    const payload = fetchLibraryBookList
      ? await fetchLibraryBookList(apiPrefix, { limit: fetchLimit, offset: nextOffset, q: query })
      : await fetchJobList(apiPrefix, { limit: fetchLimit, offset: nextOffset, q: query });
    latestInvocationSummary = payload?.invocation_summary || latestInvocationSummary;
    const items = Array.isArray(payload?.items) ? payload.items : [];
    if (items.length === 0) {
      hasMore = false;
      break;
    }

    for (const item of items) {
      if (!isPrimaryRecentJob(item)) {
        continue;
      }
      const jobId = `${item?.job_id || ""}`.trim();
      if (!jobId || seenJobIds.has(jobId)) {
        continue;
      }
      seenJobIds.add(jobId);
      collected.push(item);
      if (collected.length >= pageSize) {
        break;
      }
    }

    nextOffset += fetchLimit;

    if (!hasMore || collected.length >= pageSize) {
      break;
    }
    if (items.length === 0) {
      hasMore = false;
      break;
    }
  }

  return {
    collected,
    hasMore,
    latestInvocationSummary,
    nextOffset,
  };
}
