function closeDeletePopovers(list, exceptItem = null) {
  list.querySelectorAll(".recent-job-item.is-confirming-delete").forEach((node) => {
    if (node !== exceptItem) {
      node.classList.remove("is-confirming-delete");
    }
  });
}

export function bindRecentJobsListEvents(list) {
  if (!list || list.__retainPdfRecentJobBound) {
    return;
  }
  list.__retainPdfRecentJobBound = true;
  list.addEventListener("click", (event) => {
    const cancelButton = event.target?.closest?.(".recent-job-delete-cancel");
    if (cancelButton && list.contains(cancelButton)) {
      event.preventDefault();
      event.stopPropagation();
      cancelButton.closest(".recent-job-item")?.classList.remove("is-confirming-delete");
      return;
    }
    const confirmButton = event.target?.closest?.(".recent-job-delete-confirm");
    if (confirmButton && list.contains(confirmButton)) {
      event.preventDefault();
      event.stopPropagation();
      const item = confirmButton.closest(".recent-job-item");
      item?.classList.remove("is-confirming-delete");
      list.__retainPdfRecentJobDelete?.(item?.dataset.jobId || "");
      return;
    }
    const deleteButton = event.target?.closest?.(".recent-job-delete");
    if (deleteButton && list.contains(deleteButton)) {
      event.preventDefault();
      event.stopPropagation();
      const item = deleteButton.closest(".recent-job-item");
      closeDeletePopovers(list, item);
      item?.classList.toggle("is-confirming-delete");
      return;
    }
    const readerButton = event.target?.closest?.(".recent-job-reader");
    if (readerButton && list.contains(readerButton)) {
      event.preventDefault();
      event.stopPropagation();
      const item = readerButton.closest(".recent-job-item");
      list.__retainPdfRecentJobReader?.(item?.dataset.jobId || "");
      return;
    }
    const button = event.target?.closest?.(".recent-job-item");
    if (!button || !list.contains(button)) {
      closeDeletePopovers(list);
      return;
    }
    event.preventDefault();
    closeDeletePopovers(list);
    list.__retainPdfRecentJobSelect?.(button.dataset.jobId || "");
  });
  list.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") {
      return;
    }
    const item = event.target?.closest?.(".recent-job-item");
    if (!item || !list.contains(item)) {
      return;
    }
    event.preventDefault();
    list.__retainPdfRecentJobSelect?.(item.dataset.jobId || "");
  });
}
