const api = globalThis.browser ?? globalThis.chrome;
const { DEFAULT_UI_LANGUAGE, normalizeUiLanguage, riskLabel, t } = globalThis.SurfPhishI18n;

const statusLine = document.getElementById("statusLine");
const urlLine = document.getElementById("urlLine");
const metrics = document.getElementById("metrics");
const details = document.getElementById("details");
const fullCheckActions = document.getElementById("fullCheckActions");
const fullCheckButton = document.getElementById("fullCheckButton");
const actions = document.getElementById("actions");
const riskValue = document.getElementById("riskValue");
const scoreValue = document.getElementById("scoreValue");
const errorValue = document.getElementById("errorValue");
const thresholdValue = document.getElementById("thresholdValue");
const predictionValue = document.getElementById("predictionValue");
const errorOnlyValue = document.getElementById("errorOnlyValue");
const marginValue = document.getElementById("marginValue");
const falsePositiveButton = document.getElementById("falsePositiveButton");
const reportButton = document.getElementById("reportButton");
const protectionSummary = document.getElementById("protectionSummary");
const protectionToggleButton = document.getElementById("protectionToggleButton");

let activeTab = null;
let currentLanguage = DEFAULT_UI_LANGUAGE;
let currentState = null;
let protectionEnabled = false;

function setActionVariant(button, variant) {
  button.classList.remove("ghost", "action-danger", "action-safe", "action-undo");
  if (variant === "danger") {
    button.classList.add("action-danger");
    return;
  }
  if (variant === "safe") {
    button.classList.add("action-safe");
    return;
  }
  button.classList.add("ghost", "action-undo");
}

function applyStaticText() {
  document.documentElement.lang = currentLanguage === "en" ? "en" : "zh-Hant";
  document.title = t(currentLanguage, "brandName");
  document.getElementById("eyebrowText").textContent = t(currentLanguage, "popupEyebrow");
  document.getElementById("brandHeading").textContent = t(currentLanguage, "brandName");
  document.getElementById("rescanButton").textContent = t(currentLanguage, "popupRescan");
  document.getElementById("protectionLabel").textContent = t(currentLanguage, "popupProtectionTitle");
  document.getElementById("riskLabelText").textContent = t(currentLanguage, "popupMetricRiskLevel");
  document.getElementById("scoreLabelText").textContent = t(currentLanguage, "popupMetricPhishingScore");
  document.getElementById("errorLabelText").textContent = t(currentLanguage, "popupMetricReconError");
  document.getElementById("thresholdLabelText").textContent = t(currentLanguage, "popupMetricThreshold");
  document.getElementById("predictionLabelText").textContent = t(currentLanguage, "popupDetailPrediction");
  document.getElementById("errorOnlyLabelText").textContent = t(currentLanguage, "popupDetailErrorOnly");
  document.getElementById("marginLabelText").textContent = t(currentLanguage, "popupDetailThresholdMargin");
  document.getElementById("falsePositiveButton").textContent = t(currentLanguage, "popupActionFalsePositive");
  document.getElementById("reportButton").textContent = t(currentLanguage, "popupActionReport");
  document.getElementById("fullCheckButton").textContent = t(currentLanguage, "bannerActionDetailedCheck");
  document.getElementById("optionsButton").textContent = t(currentLanguage, "popupSettings");
  document.getElementById("healthButton").textContent = t(currentLanguage, "popupPingApi");
  renderProtectionControls();
}

function renderProtectionControls() {
  protectionSummary.textContent = protectionEnabled
    ? t(currentLanguage, "popupProtectionOn")
    : t(currentLanguage, "popupProtectionOff");
  protectionToggleButton.textContent = protectionEnabled
    ? t(currentLanguage, "popupProtectionDisallow")
    : t(currentLanguage, "popupProtectionAllow");
  document.getElementById("rescanButton").disabled = !protectionEnabled;
}

function setStatus(message, url = "") {
  statusLine.textContent = message;
  urlLine.textContent = url;
}

function renderReady(state) {
  currentState = state;
  const summary = state.summary;
  const isHighRisk = summary.riskLevel === "HIGH";
  const isMarkedSafe = Boolean(state.decision?.markedSafe || state.feedback?.falsePositiveReportedAt);
  const isReportedPhishing = Boolean(state.feedback?.siteReportedAt);
  const detailedCheck = state.detailedCheck || {};
  metrics.classList.remove("hidden");
  details.classList.remove("hidden");
  fullCheckActions.classList.remove("hidden");
  falsePositiveButton.hidden = !isHighRisk;
  falsePositiveButton.disabled = false;
  falsePositiveButton.textContent = isMarkedSafe
    ? t(currentLanguage, "popupActionUndoFalsePositive")
    : t(currentLanguage, "popupActionFalsePositive");
  setActionVariant(falsePositiveButton, isMarkedSafe ? "undo" : "safe");
  reportButton.hidden = isHighRisk;
  actions.classList.toggle("hidden", falsePositiveButton.hidden && reportButton.hidden);
  reportButton.disabled = false;
  reportButton.textContent = isReportedPhishing
    ? t(currentLanguage, "popupActionUndoReport")
    : t(currentLanguage, "popupActionReport");
  setActionVariant(reportButton, isReportedPhishing ? "undo" : "danger");
  if (detailedCheck.status === "running") {
    fullCheckButton.disabled = true;
    fullCheckButton.textContent = t(currentLanguage, "bannerActionDetailedChecking");
  } else if (detailedCheck.status === "complete") {
    fullCheckButton.disabled = false;
    fullCheckButton.textContent = t(currentLanguage, "bannerActionDetailedDone");
  } else {
    fullCheckButton.disabled = false;
    fullCheckButton.textContent = t(currentLanguage, "bannerActionDetailedCheck");
  }
  setStatus(
    isReportedPhishing
      ? t(currentLanguage, "popupStatusReported")
      : isMarkedSafe
        ? t(currentLanguage, "popupStatusMarkedSafe")
        : summary.isPhishing
          ? t(currentLanguage, "popupStatusSuspicious")
          : t(currentLanguage, "popupStatusBenign"),
    state.url
  );
  riskValue.textContent = riskLabel(currentLanguage, summary.riskLevel);
  scoreValue.textContent = `${summary.phishingPercent}%`;
  errorValue.textContent = summary.reconstructionError.toFixed(4);
  thresholdValue.textContent = summary.threshold.toFixed(4);
  predictionValue.textContent = summary.prediction;
  errorOnlyValue.textContent = summary.errorOnlyPrediction;
  marginValue.textContent = summary.thresholdMargin.toFixed(4);
}

function renderWhitelisted(state) {
  currentState = state;
  metrics.classList.add("hidden");
  details.classList.add("hidden");
  fullCheckActions.classList.add("hidden");
  actions.classList.add("hidden");
  setStatus(t(currentLanguage, "popupStatusWhitelisted"), state.url || "");
}

function renderError(state) {
  currentState = state;
  metrics.classList.add("hidden");
  details.classList.add("hidden");
  fullCheckActions.classList.add("hidden");
  actions.classList.add("hidden");
  setStatus(state.error || t(currentLanguage, "popupStatusUnhealthy", { error: "unknown error" }), state.url || "");
}

function renderScanning(url) {
  currentState = null;
  metrics.classList.add("hidden");
  details.classList.add("hidden");
  fullCheckActions.classList.add("hidden");
  actions.classList.add("hidden");
  setStatus(t(currentLanguage, "popupStatusScanning"), url);
}

async function refreshState() {
  const [tab] = await api.tabs.query({ active: true, currentWindow: true });
  activeTab = tab || null;
  const protectionStatus = await api.runtime.sendMessage({ type: "surfphish:get-protection-status" });
  protectionEnabled = Boolean(protectionStatus?.enabled);
  renderProtectionControls();

  if (!activeTab || !/^https?:\/\//i.test(activeTab.url || "")) {
    currentState = null;
    metrics.classList.add("hidden");
    details.classList.add("hidden");
    fullCheckActions.classList.add("hidden");
    actions.classList.add("hidden");
    setStatus(t(currentLanguage, "popupCantScan"), activeTab?.url || "");
    return;
  }

  if (!protectionEnabled) {
    currentState = null;
    metrics.classList.add("hidden");
    details.classList.add("hidden");
    fullCheckActions.classList.add("hidden");
    actions.classList.add("hidden");
    setStatus(t(currentLanguage, "popupStatusProtectionDisabled"), activeTab.url);
    return;
  }

  const state = await api.runtime.sendMessage({
    type: "surfphish:get-scan-state",
    tabId: activeTab.id
  });

  if (!state) {
    renderScanning(activeTab.url);
    return;
  }
  if (state.status === "scanning") {
    renderScanning(activeTab.url);
    return;
  }
  if (state.status === "whitelisted") {
    renderWhitelisted(state);
    return;
  }
  if (state.status === "error") {
    renderError(state);
    return;
  }
  if (state.status !== "ready") {
    renderScanning(activeTab.url);
    return;
  }
  renderReady(state);
}

async function initializeLanguage() {
  const settings = await api.storage.local.get({ uiLanguage: DEFAULT_UI_LANGUAGE });
  currentLanguage = normalizeUiLanguage(settings.uiLanguage);
  applyStaticText();
  setStatus(t(currentLanguage, "popupOpening"));
}

document.getElementById("rescanButton").addEventListener("click", async () => {
  if (!activeTab?.id || !protectionEnabled) {
    return;
  }
  renderScanning(activeTab.url);
  await api.runtime.sendMessage({
    type: "surfphish:rescan-tab",
    tabId: activeTab.id
  });
  refreshState();
});

protectionToggleButton.addEventListener("click", async () => {
  const response = await api.runtime.sendMessage({
    type: "surfphish:set-protection-enabled",
    enabled: !protectionEnabled
  });
  if (!response?.ok) {
    return;
  }
  protectionEnabled = Boolean(response.enabled);
  renderProtectionControls();
  if (protectionEnabled && activeTab?.url) {
    renderScanning(activeTab.url);
  }
  refreshState();
});

document.getElementById("optionsButton").addEventListener("click", () => {
  api.runtime.openOptionsPage();
});

fullCheckButton.addEventListener("click", async () => {
  if (!activeTab?.id || !protectionEnabled) {
    return;
  }
  await api.tabs.sendMessage(activeTab.id, {
    type: "surfphish:show-full-check-consent"
  }).catch(() => {});
  window.close();
});

document.getElementById("falsePositiveButton").addEventListener("click", async () => {
  if (!activeTab?.id) {
    return;
  }
  const shouldUndo = Boolean(currentState?.decision?.markedSafe || currentState?.feedback?.falsePositiveReportedAt);
  const response = await api.runtime.sendMessage(shouldUndo
    ? {
        type: "surfphish:clear-user-site-decision",
        source: "popup",
        tabId: activeTab.id,
        url: activeTab.url
      }
    : {
        type: "surfphish:mark-false-positive",
        source: "popup",
        tabId: activeTab.id
      });
  if (response?.ok) {
    refreshState();
  }
});

document.getElementById("reportButton").addEventListener("click", async () => {
  if (!activeTab?.id) {
    return;
  }
  const shouldUndo = Boolean(currentState?.feedback?.siteReportedAt);
  const response = await api.runtime.sendMessage(shouldUndo
    ? {
        type: "surfphish:clear-user-site-decision",
        source: "popup",
        tabId: activeTab.id,
        url: activeTab.url
      }
    : {
        type: "surfphish:report-site",
        source: "popup",
        tabId: activeTab.id
      });
  if (response?.ok) {
    refreshState();
  }
});

document.getElementById("healthButton").addEventListener("click", async () => {
  const result = await api.runtime.sendMessage({ type: "surfphish:ping-api" });
  if (result.ok) {
    setStatus(
      t(currentLanguage, "popupStatusHealthy", { model: result.payload.model || "unknown" }),
      activeTab?.url || ""
    );
  } else {
    setStatus(
      t(currentLanguage, "popupStatusUnhealthy", { error: result.error || "unknown error" }),
      activeTab?.url || ""
    );
  }
});

api.storage.onChanged.addListener((changes, areaName) => {
  if (areaName !== "local" || !changes.uiLanguage) {
    return;
  }
  currentLanguage = normalizeUiLanguage(changes.uiLanguage.newValue);
  applyStaticText();
  refreshState();
});

initializeLanguage().then(() => {
  refreshState();
  const refreshTimer = setInterval(refreshState, 1500);
  window.addEventListener("unload", () => clearInterval(refreshTimer));
});
