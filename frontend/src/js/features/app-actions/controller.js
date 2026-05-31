import { resetMissingUploadState, setSubmitBusy } from "./view.js";
import { withTimeout } from "../../async-timeout.js";

const DEEPSEEK_BALANCE_CHECK_TIMEOUT_MS = 12000;

export function mountAppActionsFeature({
  state,
  apiBase,
  apiPrefix,
  buildApiEndpoint,
  isMockMode,
  openSetupDialog,
  renderJob,
  setText,
  submitJobRequest,
  openDesktopOutputDirectory,
  resetUploadedFile,
  currentWorkflow,
  workflowNeedsCredentials,
  workflowNeedsUpload,
  currentRenderSourceJobId,
  currentBudgetState,
  collectRunPayload,
  validateBeforeSubmit,
  getBrowserCredentialsFeature,
  getJobRuntimeFeature,
}) {
  function setSubmitBusyState(busy) {
    state.submitBusy = !!busy;
    setSubmitBusy(busy);
  }

  function isMissingUploadError(error) {
    const message = `${error?.message || error || ""}`;
    return message.includes("upload not found");
  }

  function handleMissingUploadError() {
    resetMissingUploadState({ state, resetUploadedFile, setText });
  }

  function needsDeepSeekBudgetCheck(workflow) {
    const budget = currentBudgetState?.();
    return workflowNeedsUpload(workflow) && Boolean(budget?.visible);
  }

  async function ensureDeepSeekBudgetReady(workflow) {
    if (!needsDeepSeekBudgetCheck(workflow)) {
      return true;
    }
    const credentialsFeature = getBrowserCredentialsFeature?.();
    setText("error-box", "正在检测 DeepSeek 余额…");
    try {
      const result = await withTimeout(
        credentialsFeature?.refreshDeepSeekBalance?.({ silent: true }) || Promise.resolve(null),
        DEEPSEEK_BALANCE_CHECK_TIMEOUT_MS,
        "DeepSeek 余额检测超时，请稍后重试或在接口设置中检测。",
      );
      if (result?.status === "missing_key") {
        setText("error-box", "请先填写 DeepSeek API Key。");
        return false;
      }
      if (result?.status === "network_error") {
        setText("error-box", "DeepSeek 余额检测失败，请稍后重试或在接口设置中检测。");
        return false;
      }
    } catch (error) {
      setText("error-box", error?.message || "DeepSeek 余额检测失败，请稍后重试。");
      return false;
    }
    const budget = currentBudgetState?.();
    if (budget?.blocking) {
      setText("error-box", `余额不足：${budget.message}。请充值后再提交。`);
      return false;
    }
    if (budget?.visible && !budget.balanceChecked) {
      setText("error-box", "无法确认 DeepSeek 余额，请先在接口设置中完成检测。");
      return false;
    }
    return true;
  }

  async function submitForm(event) {
    event.preventDefault();
    const workflow = currentWorkflow();
    if (isMockMode()) {
      setSubmitBusyState(true);
      setText("error-box", "-");
      try {
        const payload = await submitJobRequest(apiPrefix, { workflow, source: {}, mock: true });
        state.currentJobStartedAt = new Date().toISOString();
        state.currentJobFinishedAt = "";
        renderJob(payload);
        getJobRuntimeFeature()?.startPolling(payload.job_id);
      } catch (err) {
        setText("error-box", err.message);
      } finally {
        setSubmitBusyState(false);
      }
      return;
    }
    if (state.desktopMode && !state.desktopConfigured && workflowNeedsCredentials(workflow)) {
      openSetupDialog();
      setText("error-box", "请先完成首次配置。");
      return;
    }
    if (workflowNeedsUpload(workflow) && !state.uploadId) {
      setText("error-box", "请先选择并上传 PDF 文件");
      return;
    }
    if (!workflowNeedsUpload(workflow) && !currentRenderSourceJobId()) {
      setText("error-box", "请先在开发者设置里填写 Render 源任务 ID。");
      return;
    }
    if (!validateBeforeSubmit?.()) {
      return;
    }
    setSubmitBusyState(true);
    if (!(await ensureDeepSeekBudgetReady(workflow))) {
      setSubmitBusyState(false);
      return;
    }
    if (workflowNeedsCredentials(workflow) && !(await getBrowserCredentialsFeature()?.ensureOcrCredentialsReady({
      onMissingToken: () => {
        setText("error-box", "请先填写当前 OCR Provider 凭证。");
        if (!state.desktopMode) {
          getBrowserCredentialsFeature()?.openBrowserCredentialsDialog();
        }
      },
      onInvalidToken: (result) => {
        setText("error-box", result.summary || "OCR Provider 凭证校验未通过。");
        if (!state.desktopMode) {
          getBrowserCredentialsFeature()?.openBrowserCredentialsDialog();
        }
      },
    }))) {
      setSubmitBusyState(false);
      return;
    }

    setText("error-box", "-");

    try {
      const runPayload = collectRunPayload();
      const payload = await submitJobRequest(apiPrefix, runPayload);
      document.dispatchEvent(new CustomEvent("retainpdf:library-job-created", {
        detail: { job: payload },
      }));
      [200, 1500, 4000].forEach((delay) => {
        window.setTimeout(() => {
          document.dispatchEvent(new CustomEvent("retainpdf:library-refresh-requested", {
            detail: { delay: 0 },
          }));
        }, delay);
      });
      document.dispatchEvent(new CustomEvent("retainpdf:open-translation-workflow"));
      state.currentJobStartedAt = new Date().toISOString();
      state.currentJobFinishedAt = "";
      renderJob(payload);
      getJobRuntimeFeature()?.startPolling(payload.job_id);
    } catch (err) {
      if (isMissingUploadError(err)) {
        handleMissingUploadError();
        return;
      }
      setText("error-box", err.message);
    } finally {
      setSubmitBusyState(false);
    }
  }

  async function checkApiConnectivity() {
    try {
      const resp = await fetch(buildApiEndpoint("", "health"));
      if (!resp.ok) {
        throw new Error(`health ${resp.status}`);
      }
      return true;
    } catch (_err) {
      const message = `当前前端无法连接后端。API Base: ${apiBase()}。请确认本地服务已经启动，然后重试。`;
      setText("error-box", message);
      throw new Error(message);
    }
  }

  async function handleOpenOutputDir() {
    try {
      await openDesktopOutputDirectory();
    } catch (err) {
      setText("error-box", err.message || String(err));
    }
  }

  return {
    checkApiConnectivity,
    handleOpenOutputDir,
    submitForm,
  };
}
