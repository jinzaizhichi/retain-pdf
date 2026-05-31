import { resolveAnimationPathForStage } from "./job-status-card-visuals.js";

const LOTTIE_WEB_PATH = "./vendor/lottie-web/build/player/lottie.min.js";
let lottieLoaderPromise = null;

function loadLottieWeb() {
  if (window.lottie) {
    return Promise.resolve(window.lottie);
  }
  if (lottieLoaderPromise) {
    return lottieLoaderPromise;
  }
  lottieLoaderPromise = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = LOTTIE_WEB_PATH;
    script.async = true;
    script.onload = () => window.lottie ? resolve(window.lottie) : reject(new Error("lottie unavailable"));
    script.onerror = () => reject(new Error("failed to load lottie-web"));
    document.head.appendChild(script);
  });
  return lottieLoaderPromise;
}

export function createStatusStageAnimationController(host) {
  let stageAnimation = null;
  let stageAnimationKey = "";
  let stageAnimationLoadingKey = "";
  let stageAnimationDesiredKey = "";
  let playbackSpeed = 1;
  let lastProgressSample = null;

  function applyPlaybackSpeed() {
    stageAnimation?.setSpeed?.(playbackSpeed);
  }

  function speedForProgressDelta(stageKey, previous, next) {
    if (!["ocr", "translate", "render"].includes(stageKey) || !previous || previous.stageKey !== stageKey || previous.total !== next.total) {
      return 1;
    }
    const elapsedSeconds = Math.max(0.25, (next.time - previous.time) / 1000);
    const delta = next.current - previous.current;
    if (!Number.isFinite(delta) || delta <= 0) {
      return 0.75;
    }
    const unitsPerSecond = delta / elapsedSeconds;
    if (stageKey === "render") {
      if (next.progressUnit === "step") {
        return Math.min(1.6, Math.max(0.85, 0.85 + delta * 0.25));
      }
      if (next.progressUnit === "percent") {
        return Math.min(2, Math.max(0.8, 0.8 + unitsPerSecond / 10));
      }
      if (unitsPerSecond >= 18) {
        return 2.8;
      }
      if (unitsPerSecond >= 8) {
        return 2.2;
      }
      if (unitsPerSecond >= 3) {
        return 1.55;
      }
      if (unitsPerSecond >= 1) {
        return 1.15;
      }
      return 0.8;
    }
    if (stageKey === "ocr") {
      if (unitsPerSecond >= 20) {
        return 2.4;
      }
      if (unitsPerSecond >= 8) {
        return 1.8;
      }
      if (unitsPerSecond >= 2) {
        return 1.25;
      }
      return 0.85;
    }
    if (unitsPerSecond >= 50) {
      return 3;
    }
    if (unitsPerSecond >= 20) {
      return 2.4;
    }
    if (unitsPerSecond >= 8) {
      return 1.8;
    }
    if (unitsPerSecond >= 2) {
      return 1.25;
    }
    return 0.85;
  }

  function syncProgressSpeed({ stageKey = "", current = NaN, total = NaN, progressUnit = "" } = {}) {
    const normalizedStageKey = `${stageKey || ""}`.trim();
    const numericCurrent = Number(current);
    const numericTotal = Number(total);
    if (!["ocr", "translate", "render"].includes(normalizedStageKey) || !Number.isFinite(numericCurrent) || !Number.isFinite(numericTotal) || numericTotal <= 0) {
      lastProgressSample = null;
      playbackSpeed = 1;
      applyPlaybackSpeed();
      return;
    }
    const nextSample = {
      stageKey: normalizedStageKey,
      current: numericCurrent,
      total: numericTotal,
      progressUnit: `${progressUnit || ""}`.trim(),
      time: Date.now(),
    };
    playbackSpeed = speedForProgressDelta(normalizedStageKey, lastProgressSample, nextSample);
    lastProgressSample = nextSample;
    applyPlaybackSpeed();
  }

  function clearStageAnimation() {
    const container = host.querySelector("#status-stage-lottie");
    stageAnimation?.destroy?.();
    stageAnimation = null;
    stageAnimationKey = "";
    if (container) {
      container.innerHTML = "";
      container.classList.remove("is-fallback");
    }
  }

  function ensureStageAnimation(stageKey, animationPath) {
    const container = host.querySelector("#status-stage-lottie");
    if (!container || !animationPath || stageAnimationKey === stageKey || stageAnimationLoadingKey === stageKey) {
      return;
    }
    stageAnimationLoadingKey = stageKey;
    container.classList.remove("is-fallback");
    if (stageAnimationKey !== stageKey) {
      clearStageAnimation();
    }
    loadLottieWeb()
      .then((lottie) => {
        if (stageAnimationDesiredKey !== stageKey) {
          return;
        }
        if (stageAnimationKey !== stageKey) {
          stageAnimation?.destroy?.();
          container.innerHTML = "";
        }
        if (stageAnimationDesiredKey !== stageKey) {
          return;
        }
        stageAnimation = lottie.loadAnimation({
          container,
          renderer: "svg",
          loop: true,
          autoplay: true,
          path: animationPath,
        });
        applyPlaybackSpeed();
        stageAnimationKey = stageKey;
      })
      .catch(() => {
        if (stageAnimationDesiredKey !== stageKey) {
          return;
        }
        container.classList.add("is-fallback");
      })
      .finally(() => {
        if (stageAnimationLoadingKey === stageKey) {
          stageAnimationLoadingKey = "";
        }
      });
  }

  function setStageVisualMode(stageKey) {
    const normalized = `${stageKey || ""}`.trim();
    const animationPath = resolveAnimationPathForStage(normalized);
    stageAnimationDesiredKey = animationPath ? normalized : "";
    host.classList.toggle("has-stage-animation", Boolean(animationPath));
    host.classList.toggle("is-translation-stage", normalized === "translate");
    host.dataset.visualStageKey = normalized;
    host.querySelector("#status-stage-animation")?.classList.toggle("hidden", !animationPath);
    if (animationPath) {
      ensureStageAnimation(normalized, animationPath);
      stageAnimation?.play?.();
      return;
    }
    clearStageAnimation();
  }

  return {
    clear: clearStageAnimation,
    syncProgressSpeed,
    setStageVisualMode,
  };
}
