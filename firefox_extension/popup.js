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
const lookupStatusValue = document.getElementById("lookupStatusValue");
const lookupMatchesValue = document.getElementById("lookupMatchesValue");
const falsePositiveButton = document.getElementById("falsePositiveButton");
const whitelistButton = document.getElementById("whitelistButton");
const reportButton = document.getElementById("reportButton");
const protectionSummary = document.getElementById("protectionSummary");
const protectionToggleButton = document.getElementById("protectionToggleButton");
const installPromptPanel = document.getElementById("installPromptPanel");

let activeTab = null;
let currentLanguage = DEFAULT_UI_LANGUAGE;
let currentState = null;
let protectionEnabled = false;
let showInstallProtectionPrompt = false;

function setPopupTone(tone) {
  document.body.classList.remove("tone-benign", "tone-high");
  if (tone === "benign") {
    document.body.classList.add("tone-benign");
    return;
  }
  if (tone === "high") {
    document.body.classList.add("tone-high");
  }
}

function setButtonTone(button, tone) {
  button.classList.remove("button-allow", "button-disallow");
  if (tone === "allow") {
    button.classList.add("button-allow");
    return;
  }
  if (tone === "disallow") {
    button.classList.add("button-disallow");
  }
}

function setActionVariant(button, variant) {
  button.classList.remove("ghost", "action-danger", "action-safe", "action-undo", "action-whitelist");
  if (variant === "danger") {
    button.classList.add("action-danger");
    return;
  }
  if (variant === "safe") {
    button.classList.add("action-safe");
    return;
  }
  if (variant === "whitelist") {
    button.classList.add("action-whitelist");
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
  document.getElementById("installPromptLabel").textContent = t(currentLanguage, "popupInstallPromptLabel");
  document.getElementById("installPromptTitle").textContent = t(currentLanguage, "popupInstallPromptTitle");
  document.getElementById("installPromptBody").textContent = t(currentLanguage, "popupInstallPromptBody");
  document.getElementById("installAllowButton").textContent = t(currentLanguage, "popupProtectionAllow");
  document.getElementById("installDisallowButton").textContent = t(currentLanguage, "popupProtectionDisallow");
  document.getElementById("riskLabelText").textContent = t(currentLanguage, "popupMetricRiskLevel");
  document.getElementById("scoreLabelText").textContent = t(currentLanguage, "popupMetricPhishingScore");
  document.getElementById("errorLabelText").textContent = t(currentLanguage, "popupMetricReconError");
  document.getElementById("thresholdLabelText").textContent = t(currentLanguage, "popupMetricThreshold");
  document.getElementById("predictionLabelText").textContent = t(currentLanguage, "popupDetailPrediction");
  document.getElementById("errorOnlyLabelText").textContent = t(currentLanguage, "popupDetailErrorOnly");
  document.getElementById("marginLabelText").textContent = t(currentLanguage, "popupDetailThresholdMargin");
  document.getElementById("lookupStatusLabelText").textContent = t(currentLanguage, "popupDetailLookupStatus");
  document.getElementById("lookupMatchesLabelText").textContent = t(currentLanguage, "popupDetailLookupMatches");
  document.getElementById("falsePositiveButton").textContent = t(currentLanguage, "popupActionFalsePositive");
  document.getElementById("whitelistButton").textContent = t(currentLanguage, "popupActionWhitelist");
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
  setButtonTone(protectionToggleButton, protectionEnabled ? "disallow" : "allow");
  document.getElementById("rescanButton").disabled = !protectionEnabled;
}

function renderInstallPrompt() {
  installPromptPanel.classList.toggle("hidden", !showInstallProtectionPrompt);
}

function setStatus(message, url = "") {
  statusLine.textContent = message;
  urlLine.textContent = url;
}

function formatLookupStatus(lookup) {
  if (!lookup || lookup.status === "skipped") {
    return t(currentLanguage, "popupLookupUnavailable");
  }
  if (lookup.status === "error") {
    return t(currentLanguage, "popupLookupError");
  }
  if (lookup.status !== "complete") {
    return t(currentLanguage, "popupLookupPending");
  }
  return lookup.found
    ? t(currentLanguage, "popupLookupMatched")
    : t(currentLanguage, "popupLookupNoMatch");
}

function renderReady(state) {
  currentState = state;
  const summary = state.summary;
  const isHighRisk = summary.riskLevel === "HIGH";
  const isDangerTone = Boolean(summary.isPhishing || isHighRisk);
  const isMarkedSafe = Boolean(state.decision?.markedSafe || state.feedback?.falsePositiveReportedAt);
  const isReportedPhishing = Boolean(state.feedback?.siteReportedAt);
  const detailedCheck = state.detailedCheck || {};
  metrics.classList.remove("hidden");
  details.classList.remove("hidden");
  fullCheckActions.classList.remove("hidden");
  falsePositiveButton.hidden = !isHighRisk;
  whitelistButton.hidden = !isHighRisk;
  falsePositiveButton.disabled = false;
  whitelistButton.disabled = false;
  falsePositiveButton.textContent = isMarkedSafe
    ? t(currentLanguage, "popupActionUndoFalsePositive")
    : t(currentLanguage, "popupActionFalsePositive");
  setActionVariant(falsePositiveButton, isMarkedSafe ? "undo" : "safe");
  whitelistButton.textContent = t(currentLanguage, "popupActionWhitelist");
  setActionVariant(whitelistButton, "whitelist");
  reportButton.hidden = isHighRisk;
  actions.classList.toggle("hidden", falsePositiveButton.hidden && whitelistButton.hidden && reportButton.hidden);
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
  const lookup = state.lookup || null;
  const baseStatus = isReportedPhishing
    ? t(currentLanguage, "popupStatusReported")
    : isMarkedSafe
      ? t(currentLanguage, "popupStatusMarkedSafe")
      : summary.isPhishing
        ? t(currentLanguage, "popupStatusSuspicious")
        : t(currentLanguage, "popupStatusBenign");
  const lookupSuffix = lookup?.status === "complete" && lookup.found
    ? ` ${t(currentLanguage, "popupStatusLookupMatched", { count: String(lookup.matchCount || 0) })}`
    : "";
  setPopupTone(isDangerTone ? "high" : "benign");
  setStatus(
    `${baseStatus}${lookupSuffix}`.trim(),
    state.url
  );
  riskValue.textContent = riskLabel(currentLanguage, summary.riskLevel);
  scoreValue.textContent = `${summary.phishingPercent}%`;
  errorValue.textContent = summary.reconstructionError.toFixed(4);
  thresholdValue.textContent = summary.threshold.toFixed(4);
  predictionValue.textContent = summary.prediction;
  errorOnlyValue.textContent = summary.errorOnlyPrediction;
  marginValue.textContent = summary.thresholdMargin.toFixed(4);
  lookupStatusValue.textContent = formatLookupStatus(lookup);
  lookupMatchesValue.textContent = lookup?.status === "complete"
    ? String(lookup.matchCount || 0)
    : lookup?.status === "error"
      ? "--"
      : "0";
}

function renderWhitelisted(state) {
  currentState = state;
  setPopupTone("benign");
  metrics.classList.add("hidden");
  details.classList.add("hidden");
  fullCheckActions.classList.add("hidden");
  actions.classList.add("hidden");
  setStatus(t(currentLanguage, "popupStatusWhitelisted"), state.url || "");
}

function renderError(state) {
  currentState = state;
  setPopupTone("high");
  metrics.classList.add("hidden");
  details.classList.add("hidden");
  fullCheckActions.classList.add("hidden");
  actions.classList.add("hidden");
  setStatus(state.error || t(currentLanguage, "popupStatusUnhealthy", { error: "unknown error" }), state.url || "");
}

function renderScanning(url) {
  currentState = null;
  setPopupTone(null);
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
  const promptState = await api.storage.local.get({ showInstallProtectionPrompt: false });
  showInstallProtectionPrompt = Boolean(promptState.showInstallProtectionPrompt);
  renderProtectionControls();
  renderInstallPrompt();

  if (!activeTab || !/^https?:\/\//i.test(activeTab.url || "")) {
    currentState = null;
    setPopupTone(null);
    metrics.classList.add("hidden");
    details.classList.add("hidden");
    fullCheckActions.classList.add("hidden");
    actions.classList.add("hidden");
    setStatus(t(currentLanguage, "popupCantScan"), activeTab?.url || "");
    return;
  }

  if (!protectionEnabled) {
    currentState = null;
    setPopupTone(null);
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

document.getElementById("installAllowButton").addEventListener("click", async () => {
  await api.runtime.sendMessage({
    type: "surfphish:set-protection-enabled",
    enabled: true
  });
  showInstallProtectionPrompt = false;
  await api.storage.local.set({ showInstallProtectionPrompt: false });
  refreshState();
});

document.getElementById("installDisallowButton").addEventListener("click", async () => {
  await api.runtime.sendMessage({
    type: "surfphish:set-protection-enabled",
    enabled: false
  });
  showInstallProtectionPrompt = false;
  await api.storage.local.set({ showInstallProtectionPrompt: false });
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

document.getElementById("whitelistButton").addEventListener("click", async () => {
  if (!activeTab?.id) {
    return;
  }
  const response = await api.runtime.sendMessage({
    type: "surfphish:add-url-to-whitelist",
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
