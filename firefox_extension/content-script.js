const api = globalThis.browser ?? globalThis.chrome;
const { DEFAULT_UI_LANGUAGE, normalizeUiLanguage, riskLabel, t } = globalThis.SurfPhishI18n;

let root;
let shadow;
let currentState = null;
let captureUiState = null;
let currentDisplayOptions = {
    showBanner: true,
    blockHighRiskInterstitial: false,
    uiLanguage: DEFAULT_UI_LANGUAGE,
    protectionEnabled: false
};

function currentLanguage() {
  return normalizeUiLanguage(currentDisplayOptions.uiLanguage);
}

function ensureUi() {
  if (root) {
    return;
  }

  root = document.createElement("div");
  root.id = "surfphish-root";
  root.style.all = "initial";
  root.style.position = "fixed";
  root.style.inset = "0";
  root.style.zIndex = "2147483647";
  root.style.pointerEvents = "none";

  shadow = root.attachShadow({ mode: "open" });
  shadow.innerHTML = `
    <style>
      :host {
        all: initial;
        color-scheme: light dark;
        --ps-ink: #18212b;
        --ps-muted: #5f6b77;
        --ps-line: #d7dde4;
        --ps-surface: rgba(255, 255, 255, 0.96);
        --ps-soft: #f4f6f8;
        --ps-overlay: rgba(12, 16, 22, 0.58);
        --ps-accent: #155e75;
        --ps-success: #0f766e;
        --ps-warning: #b45309;
        --ps-danger: #b91c1c;
        --ps-shadow: 0 18px 42px rgba(23, 32, 42, 0.14);
      }
      @media (prefers-color-scheme: dark) {
        :host {
          --ps-ink: #e6edf3;
          --ps-muted: #99a6b2;
          --ps-line: #26313c;
          --ps-surface: rgba(20, 26, 33, 0.96);
          --ps-soft: #18202a;
          --ps-overlay: rgba(0, 0, 0, 0.66);
          --ps-accent: #7dd3fc;
          --ps-success: #34d399;
          --ps-warning: #f59e0b;
          --ps-danger: #f87171;
          --ps-shadow: 0 24px 60px rgba(0, 0, 0, 0.45);
        }
      }
      .hidden { display: none !important; }
      .banner-shell {
        position: fixed;
        top: 16px;
        right: 16px;
        pointer-events: auto;
      }
      .card {
        width: 320px;
        box-sizing: border-box;
        color: var(--ps-ink);
        background: var(--ps-surface);
        border: 1px solid var(--ps-line);
        border-radius: 18px;
        box-shadow: var(--ps-shadow);
        padding: 14px 14px 12px;
        backdrop-filter: blur(12px);
        font-family: "Segoe UI", "Trebuchet MS", sans-serif;
      }
      .row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
      }
      .eyebrow {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        font-size: 11px;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: var(--ps-muted);
      }
      .dot {
        width: 8px;
        height: 8px;
        border-radius: 999px;
        background: var(--ps-accent);
        box-shadow: 0 0 0 4px rgba(21, 94, 117, 0.14);
      }
      .state-medium .dot {
        background: var(--ps-warning);
        box-shadow: 0 0 0 4px rgba(180, 83, 9, 0.14);
      }
      .state-low .dot {
        background: var(--ps-success);
        box-shadow: 0 0 0 4px rgba(15, 118, 110, 0.14);
      }
      .state-high .dot {
        background: var(--ps-danger);
        box-shadow: 0 0 0 4px rgba(185, 28, 28, 0.14);
      }
      .state-error .dot {
        background: #64748b;
        box-shadow: 0 0 0 4px rgba(100, 116, 139, 0.14);
      }
      .close {
        border: 1px solid var(--ps-line);
        background: var(--ps-soft);
        color: var(--ps-ink);
        width: 28px;
        height: 28px;
        border-radius: 999px;
        cursor: pointer;
        font-size: 16px;
      }
      .title {
        margin: 10px 0 4px;
        font-size: 20px;
        line-height: 1.15;
        font-weight: 700;
      }
      .subtitle {
        margin: 0;
        color: var(--ps-muted);
        font-size: 12px;
        line-height: 1.5;
      }
      .metrics {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 10px;
        margin-top: 12px;
      }
      .metric {
        background: var(--ps-soft);
        border: 1px solid var(--ps-line);
        border-radius: 14px;
        padding: 10px;
      }
      .metric-label {
        display: block;
        font-size: 10px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--ps-muted);
      }
      .metric-value {
        display: block;
        margin-top: 4px;
        font-size: 18px;
        font-weight: 700;
      }
      .metric-value.small { font-size: 14px; }
      .action-stack {
        display: grid;
        gap: 10px;
        margin-top: 14px;
      }
      .primary-action {
        width: 100%;
        border: 0;
        border-radius: 999px;
        padding: 14px 16px;
        background: linear-gradient(135deg, var(--ps-accent), #d27947);
        color: #fff8f1;
        font: inherit;
        font-weight: 700;
        cursor: pointer;
      }
      .primary-action:disabled {
        opacity: 0.6;
        cursor: default;
      }
      .helper {
        margin: 0;
        color: var(--ps-muted);
        font-size: 11px;
        line-height: 1.45;
      }
      .overlay {
        position: fixed;
        inset: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 24px;
        box-sizing: border-box;
        background: var(--ps-overlay);
        backdrop-filter: blur(4px);
        pointer-events: auto;
      }
      .dialog {
        width: min(560px, 100%);
        box-sizing: border-box;
        color: var(--ps-ink);
        background: var(--ps-surface);
        border: 1px solid var(--ps-line);
        border-radius: 22px;
        box-shadow: var(--ps-shadow);
        padding: 24px;
        font-family: "Segoe UI", "Trebuchet MS", sans-serif;
      }
      .dialog h2 {
        margin: 0;
        font-size: 28px;
        line-height: 1.05;
      }
      .dialog p {
        margin: 12px 0 0;
        color: var(--ps-muted);
        font-size: 14px;
        line-height: 1.65;
      }
      .dialog-actions {
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        margin-top: 18px;
      }
      .dialog-button {
        border: 0;
        border-radius: 999px;
        padding: 12px 16px;
        font: inherit;
        font-weight: 700;
        cursor: pointer;
      }
      .dialog-button.primary {
        background: var(--ps-ink);
        color: var(--ps-surface);
      }
      .dialog-button.secondary {
        background: var(--ps-soft);
        color: var(--ps-ink);
        border: 1px solid var(--ps-line);
      }
      .dialog-button:disabled {
        opacity: 0.55;
        cursor: default;
      }
      .dialog-status {
        margin-top: 14px;
        color: var(--ps-muted);
        font-size: 12px;
      }
      .dialog-status.busy {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 10px 14px;
        border-radius: 999px;
        background: rgba(21, 94, 117, 0.10);
        border: 1px solid rgba(21, 94, 117, 0.22);
        color: var(--ps-accent);
        font-size: 14px;
        font-weight: 700;
      }
      .dialog-status.busy::before {
        content: "";
        width: 10px;
        height: 10px;
        border-radius: 999px;
        background: currentColor;
        animation: surfphish-pulse 1s ease-in-out infinite;
      }
      .result-dialog {
        width: min(720px, 100%);
        max-height: min(78vh, 860px);
        overflow: auto;
      }
      .result-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 10px;
        margin-top: 16px;
      }
      .result-chip {
        border: 1px solid var(--ps-line);
        border-radius: 14px;
        background: var(--ps-soft);
        padding: 12px;
      }
      .result-chip-label {
        display: block;
        color: var(--ps-muted);
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }
      .result-chip-value {
        display: block;
        margin-top: 6px;
        font-size: 18px;
        font-weight: 700;
      }
      .result-section {
        margin-top: 16px;
        padding: 14px;
        border-radius: 16px;
        border: 1px solid var(--ps-line);
        background: var(--ps-soft);
      }
      .result-section h3 {
        margin: 0;
        font-size: 14px;
      }
      .result-section p {
        margin: 8px 0 0;
        font-size: 14px;
        line-height: 1.65;
        color: var(--ps-ink);
      }
      .signal-list {
        display: grid;
        gap: 10px;
        margin-top: 10px;
      }
      .signal-card {
        border-radius: 14px;
        border: 1px solid var(--ps-line);
        background: var(--ps-surface);
        padding: 12px;
      }
      .signal-card h4 {
        margin: 0;
        font-size: 14px;
      }
      .signal-card p {
        margin: 8px 0 0;
        font-size: 13px;
        line-height: 1.6;
        color: var(--ps-muted);
      }
      .result-error {
        margin-top: 16px;
        padding: 14px;
        border-radius: 16px;
        border: 1px solid rgba(185, 28, 28, 0.28);
        background: rgba(185, 28, 28, 0.10);
        color: var(--ps-ink);
        font-size: 14px;
        line-height: 1.6;
      }
      @keyframes surfphish-pulse {
        0% { transform: scale(0.8); opacity: 0.45; }
        50% { transform: scale(1); opacity: 1; }
        100% { transform: scale(0.8); opacity: 0.45; }
      }
      @media (max-width: 720px) {
        .banner-shell {
          left: 12px;
          right: 12px;
          top: 12px;
        }
        .card {
          width: auto;
        }
        .overlay {
          padding: 16px;
        }
        .dialog-actions {
          flex-direction: column;
        }
      }
    </style>
    <div class="banner-shell hidden" id="bannerShell">
      <section class="card state-medium" id="card">
        <div class="row">
          <div class="eyebrow"><span class="dot"></span><span id="statusLabel">Risk</span></div>
          <button class="close" id="closeButton" type="button" aria-label="Hide">&times;</button>
        </div>
        <h1 class="title" id="title">This page looks suspicious</h1>
        <p class="subtitle" id="subtitle">SurfPhish detected signals that deserve a closer look.</p>
        <div class="metrics">
          <div class="metric">
            <span class="metric-label" id="scoreLabelText">Phishing Score</span>
            <span class="metric-value" id="scoreValue">0%</span>
          </div>
          <div class="metric">
            <span class="metric-label" id="riskLabelText">Risk</span>
            <span class="metric-value" id="riskValue">MEDIUM</span>
          </div>
          <div class="metric">
            <span class="metric-label" id="errorLabelText">Recon Error</span>
            <span class="metric-value small" id="errorValue">0.0000</span>
          </div>
          <div class="metric">
            <span class="metric-label" id="thresholdLabelText">Threshold</span>
            <span class="metric-value small" id="thresholdValue">0.0000</span>
          </div>
        </div>
        <div class="action-stack">
          <button class="primary-action" id="detailButton" type="button">Full Check</button>
          <p class="helper" id="detailHelper">Full check will ask for consent before sending a full-page screenshot to SurfPhish.</p>
        </div>
      </section>
    </div>
    <section class="overlay hidden" id="consentOverlay" aria-live="assertive">
      <article class="dialog">
        <h2 id="consentTitle">Full Check</h2>
        <p id="consentBody">To continue, SurfPhish needs your permission to send this page's full data, including DOM and a full-page screenshot, for full inspection.</p>
        <div class="dialog-actions">
          <button class="dialog-button primary" id="allowConsentButton" type="button">Allow</button>
          <button class="dialog-button secondary" id="cancelConsentButton" type="button">Cancel</button>
        </div>
        <p class="dialog-status" id="consentStatus"></p>
      </article>
    </section>
    <section class="overlay hidden" id="resultOverlay" aria-live="polite">
      <article class="dialog result-dialog">
        <div class="row">
          <div>
            <h2 id="resultTitle">Full Check Result</h2>
            <p id="resultIntro">SurfPhish has finished the full check and returned a visual analysis.</p>
          </div>
          <button class="close" id="closeResultButton" type="button" aria-label="Hide">&times;</button>
        </div>
        <div class="result-grid" id="resultSummaryGrid">
          <div class="result-chip">
            <span class="result-chip-label" id="resultRiskLabel">Risk</span>
            <span class="result-chip-value" id="resultRiskValue">LOW</span>
          </div>
          <div class="result-chip">
            <span class="result-chip-label" id="resultConfidenceLabel">Confidence</span>
            <span class="result-chip-value" id="resultConfidenceValue">0%</span>
          </div>
        </div>
        <section class="result-section" id="resultSummarySection">
          <h3 id="resultSummaryHeading">Summary</h3>
          <p id="resultSummaryText"></p>
        </section>
        <section class="result-section" id="resultActionSection">
          <h3 id="resultActionHeading">Recommended Action</h3>
          <p id="resultActionText"></p>
        </section>
        <section class="result-section" id="resultSignalsSection">
          <h3 id="resultSignalsHeading">Why SurfPhish thinks so</h3>
          <div class="signal-list" id="resultSignalsList"></div>
        </section>
        <div class="result-error hidden" id="resultErrorText"></div>
        <div class="dialog-actions">
          <button class="dialog-button secondary" id="leaveResultActionButton" type="button">Leave this site</button>
          <button class="dialog-button primary" id="closeResultActionButton" type="button">Close</button>
        </div>
      </article>
    </section>
  `;

  shadow.getElementById("closeButton").addEventListener("click", () => {
    hideBanner();
  });
  shadow.getElementById("detailButton").addEventListener("click", () => {
    showConsentOverlay("");
  });
  shadow.getElementById("cancelConsentButton").addEventListener("click", () => {
    hideConsentOverlay();
  });
  shadow.getElementById("closeResultButton").addEventListener("click", () => {
    hideFullCheckResults();
  });
  shadow.getElementById("leaveResultActionButton").addEventListener("click", async () => {
    try {
      await api.runtime.sendMessage({ type: "surfphish:leave-high-risk-page" });
    } catch (error) {
      // Ignore navigation errors here; the user can still close the dialog.
    }
  });
  shadow.getElementById("closeResultActionButton").addEventListener("click", () => {
    hideFullCheckResults();
  });
  shadow.getElementById("allowConsentButton").addEventListener("click", () => {
    requestDetailedCheck(true);
  });
  document.documentElement.appendChild(root);
}

function applyStaticText() {
  const lang = currentLanguage();
  shadow.getElementById("scoreLabelText").textContent = t(lang, "bannerMetricScore");
  shadow.getElementById("riskLabelText").textContent = t(lang, "bannerMetricRisk");
  shadow.getElementById("errorLabelText").textContent = t(lang, "bannerMetricError");
  shadow.getElementById("thresholdLabelText").textContent = t(lang, "bannerMetricThreshold");
  shadow.getElementById("detailHelper").textContent = t(lang, "bannerDetailedHelper");
  shadow.getElementById("consentTitle").textContent = t(lang, "consentTitle");
  shadow.getElementById("consentBody").textContent = t(lang, "consentBody");
  shadow.getElementById("allowConsentButton").textContent = t(lang, "consentAllow");
  shadow.getElementById("cancelConsentButton").textContent = t(lang, "consentCancel");
  shadow.getElementById("resultTitle").textContent = t(lang, "fullCheckResultTitle");
  shadow.getElementById("resultIntro").textContent = t(lang, "fullCheckResultIntro");
  shadow.getElementById("resultRiskLabel").textContent = t(lang, "fullCheckResultRisk");
  shadow.getElementById("resultConfidenceLabel").textContent = t(lang, "fullCheckResultConfidence");
  shadow.getElementById("resultSummaryHeading").textContent = t(lang, "fullCheckResultSummary");
  shadow.getElementById("resultActionHeading").textContent = t(lang, "fullCheckResultAction");
  shadow.getElementById("resultSignalsHeading").textContent = t(lang, "fullCheckResultSignals");
  shadow.getElementById("leaveResultActionButton").textContent = t(lang, "fullCheckResultLeave");
  shadow.getElementById("closeResultActionButton").textContent = t(lang, "fullCheckResultClose");
}

function showBanner() {
  shadow.getElementById("bannerShell").classList.remove("hidden");
}

function hideBanner() {
  shadow.getElementById("bannerShell").classList.add("hidden");
}

function showConsentOverlay(message = "") {
  shadow.getElementById("consentStatus").textContent = message;
  shadow.getElementById("consentOverlay").classList.remove("hidden");
}

function hideConsentOverlay() {
  shadow.getElementById("consentOverlay").classList.add("hidden");
  shadow.getElementById("consentStatus").textContent = "";
  shadow.getElementById("consentStatus").classList.remove("busy");
  shadow.getElementById("allowConsentButton").disabled = false;
  shadow.getElementById("cancelConsentButton").disabled = false;
}

function showFullCheckResults(analysis, errorMessage = "") {
  const lang = currentLanguage();
  const errorText = shadow.getElementById("resultErrorText");
  const summaryGrid = shadow.getElementById("resultSummaryGrid");
  const summarySection = shadow.getElementById("resultSummarySection");
  const actionSection = shadow.getElementById("resultActionSection");
  const signalsSection = shadow.getElementById("resultSignalsSection");
  const signalsList = shadow.getElementById("resultSignalsList");

  signalsList.innerHTML = "";
  errorText.textContent = "";
  errorText.classList.add("hidden");

  if (!analysis) {
    summaryGrid.classList.add("hidden");
    summarySection.classList.add("hidden");
    actionSection.classList.add("hidden");
    signalsSection.classList.add("hidden");
    errorText.textContent = errorMessage || t(lang, "fullCheckResultUnavailable");
    errorText.classList.remove("hidden");
    shadow.getElementById("resultOverlay").classList.remove("hidden");
    return;
  }

  summaryGrid.classList.remove("hidden");
  summarySection.classList.remove("hidden");
  actionSection.classList.remove("hidden");
  signalsSection.classList.remove("hidden");

  shadow.getElementById("resultRiskValue").textContent = riskLabel(
    lang,
    String(analysis.risk_level || "UNKNOWN").toUpperCase()
  );
  shadow.getElementById("resultConfidenceValue").textContent = `${Math.round(Number(analysis.confidence || 0) * 100)}%`;
  shadow.getElementById("resultSummaryText").textContent = analysis.summary || t(lang, "fullCheckResultUnavailable");
  shadow.getElementById("resultActionText").textContent = analysis.action || t(lang, "fullCheckResultUnavailable");

  for (const signal of Array.isArray(analysis.signals) ? analysis.signals : []) {
    const card = document.createElement("article");
    card.className = "signal-card";

    const heading = document.createElement("h4");
    heading.textContent = signal?.title || t(lang, "fullCheckResultSignalFallback");
    card.appendChild(heading);

    const detail = document.createElement("p");
    detail.textContent = signal?.detail || "";
    card.appendChild(detail);

    signalsList.appendChild(card);
  }

  if (!signalsList.children.length) {
    const detail = document.createElement("p");
    detail.textContent = t(lang, "fullCheckResultUnavailable");
    signalsList.appendChild(detail);
  }

  shadow.getElementById("resultOverlay").classList.remove("hidden");
}

function hideFullCheckResults() {
  shadow.getElementById("resultOverlay").classList.add("hidden");
}

function setConsentBusy(isBusy, message = "") {
  shadow.getElementById("consentStatus").textContent = message;
  shadow.getElementById("consentStatus").classList.toggle("busy", Boolean(isBusy && message));
  shadow.getElementById("allowConsentButton").disabled = isBusy;
  shadow.getElementById("cancelConsentButton").disabled = isBusy;
}

async function requestDetailedCheck(allowNow) {
  const lang = currentLanguage();

  if (!currentState?.url) {
    return;
  }

  setConsentBusy(true, t(lang, "consentSending"));

  try {
    const response = await api.runtime.sendMessage({
      type: "surfphish:request-detailed-check",
      allowNow: Boolean(allowNow)
    });

    if (response?.requiresConsent) {
      showConsentOverlay("");
      setConsentBusy(false, "");
      return;
    }

    if (!response?.ok) {
      setConsentBusy(false, response?.error || t(lang, "consentFailed"));
      return;
    }

    hideConsentOverlay();
    renderState({
      state: response.state,
      showBanner: currentDisplayOptions.showBanner,
      blockHighRiskInterstitial: false,
      uiLanguage: currentDisplayOptions.uiLanguage
    });
    showFullCheckResults(
      response.state?.detailedCheck?.analysis || null,
      response.state?.detailedCheck?.analysisError?.message || ""
    );
  } catch (error) {
    setConsentBusy(false, error.message || t(lang, "consentFailed"));
  }
}

function renderBanner(state) {
  const lang = currentLanguage();
  const card = shadow.getElementById("card");
  const statusLabel = shadow.getElementById("statusLabel");
  const title = shadow.getElementById("title");
  const subtitle = shadow.getElementById("subtitle");
  const scoreValue = shadow.getElementById("scoreValue");
  const riskValue = shadow.getElementById("riskValue");
  const errorValue = shadow.getElementById("errorValue");
  const thresholdValue = shadow.getElementById("thresholdValue");
  const detailButton = shadow.getElementById("detailButton");
  const summary = state.summary || {};
  const detailedCheck = state.detailedCheck || {};
  const isBenign = String(summary.riskLevel || "").toUpperCase() === "LOW";

  card.className = "card";
  card.classList.add(`state-${String(summary.riskLevel || "medium").toLowerCase()}`);

  statusLabel.textContent = riskLabel(lang, summary.riskLevel || "MEDIUM");
  title.textContent = isBenign
    ? t(lang, "bannerTitleBenign")
    : t(lang, "bannerTitleSuspicious");

  if (detailedCheck.status === "running") {
    subtitle.textContent = t(lang, "bannerSubtitleDetailedRunning");
    detailButton.disabled = true;
    detailButton.textContent = t(lang, "bannerActionDetailedChecking");
  } else if (detailedCheck.status === "complete") {
    subtitle.textContent = t(lang, "bannerSubtitleDetailedDone");
    detailButton.disabled = false;
    detailButton.textContent = t(lang, "bannerActionDetailedDone");
  } else if (detailedCheck.status === "error") {
    subtitle.textContent = detailedCheck.error || t(lang, "bannerSubtitleDetailedError");
    detailButton.disabled = false;
    detailButton.textContent = t(lang, "bannerActionDetailedCheck");
  } else {
    subtitle.textContent = isBenign
      ? t(lang, "bannerSubtitleBenign")
      : t(lang, "bannerSubtitleDetailedReady");
    detailButton.disabled = false;
    detailButton.textContent = t(lang, "bannerActionDetailedCheck");
  }

  scoreValue.textContent = `${summary.phishingPercent ?? 0}%`;
  riskValue.textContent = riskLabel(lang, summary.riskLevel || "MEDIUM");
  errorValue.textContent = Number(summary.reconstructionError || 0).toFixed(4);
  thresholdValue.textContent = Number(summary.threshold || 0).toFixed(4);
  showBanner();
}

function renderError(state) {
  const lang = currentLanguage();
  const card = shadow.getElementById("card");
  hideConsentOverlay();
  card.className = "card state-error";
  shadow.getElementById("statusLabel").textContent = t(lang, "bannerStatusError");
  shadow.getElementById("title").textContent = t(lang, "bannerTitleError");
  shadow.getElementById("subtitle").textContent = state.error || t(lang, "bannerSubtitleError");
  shadow.getElementById("scoreValue").textContent = "--";
  shadow.getElementById("riskValue").textContent = riskLabel(lang, "ERROR");
  shadow.getElementById("errorValue").textContent = "--";
  shadow.getElementById("thresholdValue").textContent = "--";
  shadow.getElementById("detailButton").disabled = true;
  shadow.getElementById("detailButton").textContent = t(lang, "bannerActionDetailedCheck");
  showBanner();
}

function renderState(payload) {
  ensureUi();
  currentDisplayOptions = {
    showBanner: Boolean(payload?.showBanner),
    blockHighRiskInterstitial: false,
    uiLanguage: normalizeUiLanguage(payload?.uiLanguage),
    protectionEnabled: Boolean(payload?.protectionEnabled)
  };
  currentState = payload?.state || null;
  applyStaticText();

  if (!payload?.showBanner || !currentState) {
    hideBanner();
    hideConsentOverlay();
    hideFullCheckResults();
    return;
  }

  if (currentState.status === "error") {
    hideBanner();
    hideConsentOverlay();
    hideFullCheckResults();
    return;
  }

  if (currentState.status !== "ready") {
    hideBanner();
    hideConsentOverlay();
    hideFullCheckResults();
    return;
  }

  if (currentState.status === "whitelisted") {
    hideBanner();
    hideConsentOverlay();
    hideFullCheckResults();
    return;
  }

  if (String(currentState.summary?.riskLevel || "").toUpperCase() === "LOW") {
    hideBanner();
    hideConsentOverlay();
    hideFullCheckResults();
    return;
  }

  renderBanner(currentState);
}

function buildSerializedHtml() {
  const doctype = document.doctype
    ? new XMLSerializer().serializeToString(document.doctype)
    : "<!DOCTYPE html>";
  const clonedRoot = document.documentElement.cloneNode(true);
  clonedRoot.querySelector("#surfphish-root")?.remove();
  return `${doctype}\n${clonedRoot.outerHTML}`;
}

function estimateVisibleTextLength() {
  const text = (document.body?.innerText || document.documentElement?.innerText || "").trim();
  return text.length;
}

function buildPageContext(htmlText) {
  return {
    url: window.location.href,
    title: document.title || "",
    lang: document.documentElement.lang || "",
    charset: document.characterSet || "",
    htmlChars: htmlText.length,
    nodeCount: document.querySelectorAll("*").length,
    linkCount: document.links.length,
    formCount: document.forms.length,
    iframeCount: document.querySelectorAll("iframe").length,
    visibleTextChars: estimateVisibleTextLength(),
    capturedAt: new Date().toISOString()
  };
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  const chunkSize = 0x8000;
  for (let index = 0; index < bytes.length; index += chunkSize) {
    const slice = bytes.subarray(index, index + chunkSize);
    binary += String.fromCharCode(...slice);
  }
  return btoa(binary);
}

function delayReject(ms, message) {
  return new Promise((_, reject) => {
    window.setTimeout(() => reject(new Error(message)), ms);
  });
}

async function gzipHtmlToBase64(html) {
  const encoder = new TextEncoder();
  const stream = new CompressionStream("gzip");
  const writer = stream.writable.getWriter();
  await writer.write(encoder.encode(html));
  await writer.close();
  const compressed = await new Response(stream.readable).arrayBuffer();
  return arrayBufferToBase64(compressed);
}

async function buildCompressedPagePayload() {
  const html = buildSerializedHtml();
  const pageContext = buildPageContext(html);
  const fallbackPayload = {
    sourceUrl: window.location.href,
    html,
    htmlEncoding: "identity",
    pageContext
  };

  if (typeof CompressionStream !== "function" || html.length < 200000) {
    return fallbackPayload;
  }

  try {
    const htmlGzipBase64 = await Promise.race([
      gzipHtmlToBase64(html),
      delayReject(2500, "DOM compression timed out")
    ]);
    return {
      sourceUrl: window.location.href,
      htmlGzipBase64,
      htmlEncoding: "gzip+base64",
      pageContext
    };
  } catch (error) {
    return fallbackPayload;
  }
}

function getCaptureMetrics() {
  const scrollingElement = document.scrollingElement || document.documentElement;
  return {
    documentWidth: Math.max(
      scrollingElement.scrollWidth,
      document.documentElement.scrollWidth,
      document.body?.scrollWidth || 0
    ),
    documentHeight: Math.max(
      scrollingElement.scrollHeight,
      document.documentElement.scrollHeight,
      document.body?.scrollHeight || 0
    ),
    viewportWidth: window.innerWidth,
    viewportHeight: window.innerHeight,
    scrollX: window.scrollX,
    scrollY: window.scrollY
  };
}

async function setCaptureScroll(x, y) {
  window.scrollTo(x, y);
  await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  return {
    x: window.scrollX,
    y: window.scrollY
  };
}

function hideExtensionUiForCapture() {
  if (!root || captureUiState) {
    return;
  }
  captureUiState = {
    visibility: root.style.visibility,
    pointerEvents: root.style.pointerEvents
  };
  root.style.visibility = "hidden";
  root.style.pointerEvents = "none";
}

function restoreExtensionUiAfterCapture() {
  if (!root || !captureUiState) {
    return;
  }
  root.style.visibility = captureUiState.visibility;
  root.style.pointerEvents = captureUiState.pointerEvents;
  captureUiState = null;
}

api.runtime.onMessage.addListener((message) => {
  if (message?.type === "surfphish:show-full-check-consent") {
    ensureUi();
    applyStaticText();
    showConsentOverlay("");
    return Promise.resolve({ ok: true });
  }
  if (message?.type === "surfphish:collect-page-payload") {
    return buildCompressedPagePayload();
  }
  if (message?.type === "surfphish:prepare-fullpage-capture") {
    hideExtensionUiForCapture();
    return Promise.resolve(getCaptureMetrics());
  }
  if (message?.type === "surfphish:set-fullpage-capture-scroll") {
    return setCaptureScroll(Number(message.x || 0), Number(message.y || 0));
  }
  if (message?.type === "surfphish:restore-fullpage-capture-scroll") {
    return setCaptureScroll(Number(message.x || 0), Number(message.y || 0)).then((result) => {
      restoreExtensionUiAfterCapture();
      return result;
    });
  }
  if (message?.type !== "surfphish:scan-update") {
    return undefined;
  }
  renderState(message.payload);
  return undefined;
});

api.runtime.sendMessage({ type: "surfphish:get-current-tab-state" })
  .then((payload) => {
    if (payload) {
      renderState(payload);
    }
  })
  .catch(() => {
    // Ignore initialization failures when the background script is restarting.
  });
