import { $ } from "../../dom.js";
import { buildFrontendPageUrl } from "../../config.js";
import { normalizeJobPayload } from "../../job.js";
import { buildStatusDetailSnapshot } from "../../status-detail-presentation.js";
import {
  cacheSecondaryResource,
  cacheJobDiagnostics,
  cacheJobResumePlan,
  currentJobEventsFor,
  currentJobManifest,
  currentJobSnapshot,
  currentJobStageActions,
  syncCurrentJobSnapshot,
} from "../job-runtime/runtime-state.js";
import {
  renderTextBlock,
} from "./formatters.js";
import {
  activateDetailTabView,
  bindStatusDetailEvents,
  dialogComponent,
  openStatusDetailDialogView,
  readTranslationFilterQuery,
} from "./view.js";
import {
  rerunCurrentJob as rerunCurrentJobAction,
  syncRerunAction as syncRerunActionState,
} from "./resume-actions.js";
import {
  createTranslationState,
  renderTranslationEmpty,
  renderTranslationItemDetail as renderTranslationItemDetailState,
  renderTranslationItems as renderTranslationItemsState,
  renderTranslationReplay as renderTranslationReplayState,
  renderTranslationSummary as renderTranslationSummaryState,
  resetTranslationState as resetTranslationStateData,
} from "./translation-state.js";

export function mountStatusDetailFeature({
  state,
  apiPrefix,
  fetchJobPayload,
  fetchJobEvents,
  fetchJobDiagnostics,
  fetchResumePlan,
  fetchTranslationDiagnostics,
  fetchTranslationItems,
  fetchTranslationItem,
  replayTranslationItem,
  rerunJob,
  renderJob,
  startPolling,
  setText,
} = {}) {
  const translationState = createTranslationState();
  const detailState = {
    loadingPromise: null,
  };

  function buildDetailPageUrl(jobId) {
    const normalizedJobId = `${jobId || ""}`.trim();
    if (!normalizedJobId) {
      return "";
    }
    return buildFrontendPageUrl("./detail.html", {
      job_id: normalizedJobId,
    });
  }

  function getCurrentJobId() {
    return `${state?.currentJobId || ""}`.trim();
  }

  function syncRerunAction(statusText = "") {
    return syncRerunActionState({ state, statusText });
  }

  async function rerunCurrentJob() {
    await rerunCurrentJobAction({
      state,
      rerunJob,
      setText,
      startPolling,
    });
  }

  function activateDetailTab(name = "overview") {
    activateDetailTabView(name);
    if (name === "translation") {
      void ensureTranslationData();
      return;
    }
    void ensureOverviewData();
  }

  function openStatusDetailDialog(tabName = "overview") {
    openStatusDetailDialogView(tabName);
    if (tabName === "translation") {
      void ensureTranslationData();
      return;
    }
    void ensureOverviewData();
  }

  function renderOverviewSnapshot(job, eventsPayload) {
    const snapshot = buildStatusDetailSnapshot(job, eventsPayload);
    dialogComponent()?.renderSnapshot?.(snapshot);
    syncRerunAction();
  }

  async function ensureOverviewData({ force = false } = {}) {
    const jobId = getCurrentJobId();
    if (!jobId) {
      return;
    }
    if (detailState.loadingPromise && !force) {
      await detailState.loadingPromise;
      return;
    }
    const previousJob = currentJobSnapshot(state) || { job_id: jobId };
    const previousEvents = currentJobEventsFor(state, jobId);
    renderOverviewSnapshot(previousJob, previousEvents);
    detailState.loadingPromise = (async () => {
      try {
        const [payload, eventsPayload, diagnosticsPayload, resumePlan] = await Promise.all([
          fetchJobPayload ? fetchJobPayload(jobId, apiPrefix) : Promise.resolve(previousJob),
          fetchJobEvents ? fetchJobEvents(jobId, apiPrefix, 200, 0).catch(() => previousEvents) : Promise.resolve(previousEvents),
          fetchJobDiagnostics ? fetchJobDiagnostics(jobId, apiPrefix).catch(() => null) : Promise.resolve(null),
          fetchResumePlan ? fetchResumePlan(jobId, apiPrefix).catch(() => null) : Promise.resolve(null),
        ]);
        const job = {
          ...normalizeJobPayload(payload),
          diagnostics: diagnosticsPayload || undefined,
        };
        syncCurrentJobSnapshot(state, job, job.job_id || jobId, {
          startedAt: job.started_at || job.created_at || "",
          finishedAt: job.finished_at || job.updated_at || "",
        });
        cacheJobDiagnostics(state, jobId, diagnosticsPayload);
        cacheJobResumePlan(state, jobId, resumePlan);
        if (eventsPayload) {
          cacheSecondaryResource(state, "events", jobId, eventsPayload);
        }
        renderJob?.(job, eventsPayload || previousEvents, currentJobManifest(state), currentJobStageActions(state));
        renderOverviewSnapshot(job, eventsPayload || previousEvents);
      } catch (error) {
        setText?.("error-box", error.message || String(error));
      } finally {
        detailState.loadingPromise = null;
      }
    })();
    await detailState.loadingPromise;
  }

  function renderTranslationSummary() {
    renderTranslationSummaryState(translationState);
  }

  function renderTranslationItems({ loading = false, emptyText = "没有匹配的翻译 item" } = {}) {
    renderTranslationItemsState(translationState, { loading, emptyText });
  }

  function renderTranslationItemDetail({ loading = false, emptyText = "请选择左侧 item" } = {}) {
    renderTranslationItemDetailState(translationState, { loading, emptyText });
  }

  function renderTranslationReplay() {
    renderTranslationReplayState(translationState);
  }

  async function loadTranslationSummary(jobId) {
    translationState.summary = await fetchTranslationDiagnostics(jobId, apiPrefix);
    renderTranslationSummary();
  }

  async function reloadTranslationSummaryAndItems({ selectFirst = false } = {}) {
    const jobId = getCurrentJobId();
    if (!jobId) {
      resetTranslationState("");
      renderTranslationEmpty("请先选择任务");
      return;
    }
    await loadTranslationSummary(jobId);
    await loadTranslationItems(jobId, { selectFirst });
  }

  function resetTranslationState(jobId = "") {
    resetTranslationStateData(translationState, jobId);
  }

  async function loadTranslationItems(jobId, { selectFirst = false } = {}) {
    renderTranslationItems({ loading: true });
    const payload = await fetchTranslationItems(jobId, apiPrefix, translationState.query);
    translationState.list = Array.isArray(payload?.items) ? payload.items : [];
    translationState.total = Number(payload?.total || 0);
    renderTranslationItems();
    const shouldKeepCurrent = translationState.list.some((item) => item.item_id === translationState.selectedItemId);
    if (shouldKeepCurrent) {
      return;
    }
    const nextItemId = selectFirst && translationState.list.length
      ? `${translationState.list[0].item_id || ""}`.trim()
      : "";
    translationState.selectedItemId = nextItemId;
    translationState.selectedItem = null;
    translationState.replay = null;
    renderTranslationItemDetail({
      emptyText: nextItemId ? "请选择左侧 item" : "没有可查看的 item",
    });
    renderTranslationReplay();
    if (nextItemId) {
      await loadTranslationItem(jobId, nextItemId);
    }
  }

  async function loadTranslationItem(jobId, itemId) {
    if (!itemId) {
      return;
    }
    translationState.selectedItemId = itemId;
    translationState.replay = null;
    renderTranslationItems();
    renderTranslationItemDetail({ loading: true });
    renderTranslationReplay();
    translationState.selectedItem = await fetchTranslationItem(jobId, itemId, apiPrefix);
    renderTranslationItemDetail();
  }

  async function replayCurrentItem() {
    const jobId = getCurrentJobId();
    const itemId = `${translationState.selectedItemId || ""}`.trim();
    if (!jobId || !itemId) {
      return;
    }
    dialogComponent()?.renderTranslationReplay({
      hasResult: false,
      status: "重放中...",
    });
    translationState.replay = await replayTranslationItem(jobId, itemId, apiPrefix);
    renderTranslationReplay();
  }

  async function ensureTranslationData({ force = false } = {}) {
    const jobId = getCurrentJobId();
    if (!jobId) {
      resetTranslationState("");
      renderTranslationEmpty("请先选择任务");
      return;
    }
    if (translationState.jobId !== jobId) {
      resetTranslationState(jobId);
    }
    if (translationState.loaded && !force) {
      renderTranslationSummary();
      renderTranslationItems();
      renderTranslationItemDetail();
      renderTranslationReplay();
      return;
    }
    renderTranslationEmpty("正在读取翻译调试数据...");
    try {
      await reloadTranslationSummaryAndItems({ selectFirst: true });
      translationState.loaded = true;
    } catch (error) {
      renderTranslationEmpty(error.message || String(error));
    }
  }

  async function handleTranslationApply() {
    const query = readTranslationFilterQuery();
    translationState.query.finalStatus = query.finalStatus;
    translationState.query.q = query.q;
    translationState.query.offset = 0;
    translationState.loaded = true;
    renderTranslationSummary();
    try {
      await reloadTranslationSummaryAndItems({ selectFirst: true });
    } catch (error) {
      renderTranslationItems({
        loading: false,
        hasItems: false,
        emptyText: error.message || String(error),
      });
    }
  }

  async function changeTranslationPage(direction) {
    const limit = Number(translationState.query.limit || 20);
    const nextOffset = direction === "next"
      ? Number(translationState.query.offset || 0) + limit
      : Math.max(0, Number(translationState.query.offset || 0) - limit);
    if (nextOffset === Number(translationState.query.offset || 0)) {
      return;
    }
    translationState.query.offset = nextOffset;
    try {
      await loadTranslationItems(getCurrentJobId(), { selectFirst: true });
    } catch (error) {
      renderTranslationItems({
        loading: false,
        hasItems: false,
        emptyText: error.message || String(error),
      });
    }
  }

  function bindEvents() {
    bindStatusDetailEvents({
      openStatusDetailDialog,
      activateDetailTab,
      handleTranslationApply,
      changeTranslationPage,
      loadTranslationItem,
      replayCurrentItem,
      rerunCurrentJob,
      currentJobId: getCurrentJobId,
      renderTranslationItemDetail,
      renderTranslationReplay: (payload) => dialogComponent()?.renderTranslationReplay(payload),
      renderTextBlock,
    });
  }

  return {
    activateDetailTab,
    bindEvents,
    openStatusDetailDialog,
    buildDetailPageUrl,
    ensureTranslationData,
    syncRerunAction,
    ensureOverviewData,
  };
}
