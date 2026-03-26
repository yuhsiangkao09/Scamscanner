const api = globalThis.browser ?? globalThis.chrome;
const { DEFAULT_UI_LANGUAGE, normalizeUiLanguage, riskLabel, t } = globalThis.SurfPhishI18n;

let root;
let shadow;
let currentState = null;
let captureUiState = null;
let bannerAutoHideTimer = null;
let consentMode = "page";
let emailCheckManualMode = false;
let activeResultMode = null;
let emailCheckState = {
  status: "idle",
  error: "",
  result: null
};
const HIGH_RISK_BANNER_AUTOHIDE_MS = 10000;
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
      .gmail-shell {
        position: fixed;
        right: 16px;
        bottom: 16px;
        width: min(286px, calc(100vw - 24px));
        pointer-events: auto;
      }
      .gmail-panel {
        display: grid;
        gap: 8px;
        padding: 11px 12px;
        border-radius: 16px;
        border: 1px solid rgba(15, 118, 110, 0.24);
        background: linear-gradient(180deg, rgba(240, 253, 250, 0.98), rgba(236, 253, 245, 0.98));
        box-shadow: 0 18px 42px rgba(15, 118, 110, 0.16);
      }
      .gmail-label {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.07em;
        text-transform: uppercase;
        color: var(--ps-success);
      }
      .gmail-label::before {
        content: "";
        width: 8px;
        height: 8px;
        border-radius: 999px;
        background: currentColor;
        box-shadow: 0 0 0 4px rgba(15, 118, 110, 0.14);
      }
      .gmail-title {
        margin: 0;
        font-size: 15px;
        font-weight: 700;
        line-height: 1.3;
        color: #0f3f3d;
      }
      .gmail-helper {
        margin: 0;
        color: #0f766e;
        font-size: 11px;
        line-height: 1.45;
      }
      .gmail-helper.disabled {
        color: var(--ps-muted);
      }
      .gmail-check-button {
        background: #155e75;
        color: #f8fbff;
        box-shadow: 0 14px 28px rgba(21, 94, 117, 0.18);
        padding: 11px 14px;
        font-size: 13px;
      }
      .gmail-check-button:disabled {
        opacity: 0.7;
        cursor: default;
        box-shadow: none;
        background: #64748b;
        color: #eef2f7;
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
      .danger-mark {
        display: none;
        align-items: center;
        justify-content: center;
        width: 36px;
        height: 36px;
        border-radius: 12px;
        background: linear-gradient(135deg, rgba(185, 28, 28, 0.16), rgba(239, 68, 68, 0.28));
        border: 1px solid rgba(185, 28, 28, 0.24);
        color: var(--ps-danger);
        box-shadow: 0 12px 24px rgba(185, 28, 28, 0.16);
      }
      .danger-mark svg {
        width: 18px;
        height: 18px;
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
        background: #155e75;
        color: #f8fbff;
        font: inherit;
        font-weight: 700;
        cursor: pointer;
        box-shadow: 0 14px 28px rgba(21, 94, 117, 0.18);
      }
      .primary-action:disabled {
        opacity: 0.6;
        cursor: default;
        box-shadow: none;
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
      .dialog-button.success {
        background: #15803d;
        color: #f6fff8;
      }
      .dialog-button.secondary {
        background: var(--ps-soft);
        color: var(--ps-ink);
        border: 1px solid var(--ps-line);
      }
      .dialog-button.danger {
        background: #b91c1c;
        color: #fff7f7;
        box-shadow: 0 14px 24px rgba(185, 28, 28, 0.18);
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
          <div class="eyebrow">
            <span class="danger-mark" id="dangerMark" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none">
                <path d="M12 3.5 21 20.5H3L12 3.5Z" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
                <path d="M12 9V13.5" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
                <circle cx="12" cy="17" r="1.2" fill="currentColor"/>
              </svg>
            </span>
            <span class="dot"></span>
            <span id="statusLabel">Risk</span>
          </div>
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
    <div class="gmail-shell hidden" id="gmailShell">
      <section class="gmail-panel">
        <span class="gmail-label" id="gmailLabel">Gmail Email Check</span>
        <h2 class="gmail-title" id="gmailTitle">Check the open email with SurfPhish</h2>
        <p class="gmail-helper" id="gmailHelper">Analyze only the email currently open in Gmail, including the visible message view.</p>
        <button class="primary-action gmail-check-button" id="gmailCheckButton" type="button">Check this email</button>
      </section>
    </div>
    <section class="overlay hidden" id="consentOverlay" aria-live="assertive">
      <article class="dialog">
        <h2 id="consentTitle">Full Check</h2>
        <p id="consentBody">To continue, SurfPhish needs your permission to send this page's full data, including DOM and a full-page screenshot, for full inspection.</p>
        <div class="dialog-actions">
          <button class="dialog-button success" id="allowConsentButton" type="button">Allow</button>
          <button class="dialog-button danger" id="cancelConsentButton" type="button">Cancel</button>
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
          <button class="dialog-button danger" id="leaveResultActionButton" type="button">Leave this site</button>
          <button class="dialog-button primary" id="closeResultActionButton" type="button">Close</button>
        </div>
      </article>
    </section>
  `;

  shadow.getElementById("closeButton").addEventListener("click", () => {
    hideBanner();
  });
    shadow.getElementById("detailButton").addEventListener("click", () => {
      showConsentOverlay("", "page");
    });
    shadow.getElementById("gmailCheckButton").addEventListener("click", () => {
      showConsentOverlay("", "email", { manual: false });
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
      if (consentMode === "email") {
        requestEmailCheck(true);
        return;
    }
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
  shadow.getElementById("gmailLabel").textContent = t(lang, "emailCheckLabel");
  shadow.getElementById("gmailTitle").textContent = t(lang, "emailCheckTitle");
  shadow.getElementById("gmailHelper").textContent = t(lang, "emailCheckHelper");
  setConsentMode(consentMode);
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
  clearBannerAutoHideTimer();
  shadow.getElementById("bannerShell").classList.add("hidden");
}

function clearBannerAutoHideTimer() {
  if (!bannerAutoHideTimer) {
    return;
  }
  window.clearTimeout(bannerAutoHideTimer);
  bannerAutoHideTimer = null;
}

function scheduleBannerAutoHide(state) {
  clearBannerAutoHideTimer();
  if (String(state?.summary?.riskLevel || "").toUpperCase() !== "HIGH") {
    return;
  }
  bannerAutoHideTimer = window.setTimeout(() => {
    bannerAutoHideTimer = null;
    shadow?.getElementById("bannerShell")?.classList.add("hidden");
  }, HIGH_RISK_BANNER_AUTOHIDE_MS);
}

function setConsentMode(mode = "page") {
  consentMode = mode === "email" ? "email" : "page";
  const lang = currentLanguage();
  const prefix = consentMode === "email" ? "emailConsent" : "consent";
  shadow.getElementById("consentTitle").textContent = t(lang, `${prefix}Title`);
  shadow.getElementById("consentBody").textContent = t(lang, `${prefix}Body`);
  shadow.getElementById("allowConsentButton").textContent = t(lang, `${prefix}Allow`);
  shadow.getElementById("cancelConsentButton").textContent = t(lang, `${prefix}Cancel`);
}

function showConsentOverlay(message = "", mode = consentMode, options = {}) {
  setConsentMode(mode);
  emailCheckManualMode = consentMode === "email" ? Boolean(options.manual) : false;
  shadow.getElementById("consentStatus").textContent = message;
  shadow.getElementById("consentOverlay").classList.remove("hidden");
}

function hideConsentOverlay() {
  shadow.getElementById("consentOverlay").classList.add("hidden");
  shadow.getElementById("consentStatus").textContent = "";
  shadow.getElementById("consentStatus").classList.remove("busy");
  shadow.getElementById("allowConsentButton").disabled = false;
  shadow.getElementById("cancelConsentButton").disabled = false;
  setConsentMode("page");
  emailCheckManualMode = false;
}

function showFullCheckResults(analysis, errorMessage = "", options = {}) {
  const lang = currentLanguage();
  const errorText = shadow.getElementById("resultErrorText");
  const summaryGrid = shadow.getElementById("resultSummaryGrid");
  const summarySection = shadow.getElementById("resultSummarySection");
  const actionSection = shadow.getElementById("resultActionSection");
  const signalsSection = shadow.getElementById("resultSignalsSection");
  const signalsList = shadow.getElementById("resultSignalsList");
  const leaveButton = shadow.getElementById("leaveResultActionButton");
  const titleKey = options.titleKey || "fullCheckResultTitle";
  const introKey = options.introKey || "fullCheckResultIntro";
  const leaveKey = options.leaveKey || "fullCheckResultLeave";
  activeResultMode = options.mode === "email" ? "email" : "page";

  shadow.getElementById("resultTitle").textContent = t(lang, titleKey);
  shadow.getElementById("resultIntro").textContent = t(lang, introKey);
  leaveButton.textContent = t(lang, leaveKey);
  leaveButton.classList.toggle("hidden", Boolean(options.hideLeaveAction));

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
  activeResultMode = null;
}

function normalizeWhitespace(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function isGmailPage() {
  return window.location.hostname === "mail.google.com";
}

function isElementVisible(element) {
  if (!(element instanceof Element)) {
    return false;
  }
  const rect = element.getBoundingClientRect();
  if (rect.width < 8 || rect.height < 8) {
    return false;
  }
  const style = window.getComputedStyle(element);
  if (style.visibility === "hidden" || style.display === "none" || Number(style.opacity || "1") === 0) {
    return false;
  }
  return rect.bottom > 0 && rect.right > 0 && rect.top < window.innerHeight && rect.left < window.innerWidth;
}

function getVisibleTextLength(element) {
  return normalizeWhitespace(element?.innerText || element?.textContent || "").length;
}

function findFirstVisible(selectors, scope = document) {
  for (const selector of selectors) {
    const match = Array.from(scope.querySelectorAll(selector)).find((element) => isElementVisible(element));
    if (match) {
      return match;
    }
  }
  return null;
}

function pickLargestVisible(selectors, scope = document) {
  let best = null;
  let bestScore = -1;
  for (const selector of selectors) {
    for (const element of scope.querySelectorAll(selector)) {
      if (!isElementVisible(element)) {
        continue;
      }
      const score = getVisibleTextLength(element);
      if (score > bestScore) {
        best = element;
        bestScore = score;
      }
    }
  }
  return best;
}

function findGmailBodyElement() {
  return pickLargestVisible([
    "div.a3s.aiL",
    "div.a3s",
    "div.ii.gt",
    "div[data-message-id] div.a3s",
    "div[role='main'] div.a3s"
  ]);
}

function findGmailSubjectElement() {
  return findFirstVisible([
    "h2[data-thread-perm-id]",
    "h2.hP",
    "div[role='main'] h2"
  ]);
}

function findGmailMessageContainer(bodyElement) {
  if (!bodyElement) {
    return null;
  }
  return (
    bodyElement.closest("div[data-message-id]")
    || bodyElement.closest("div.adn")
    || bodyElement.closest("div[role='listitem']")
    || bodyElement.closest("div[role='main']")
    || bodyElement.parentElement
    || document.body
  );
}

function findGmailSenderElement(scope = document) {
  return findFirstVisible([
    ".gD[email]",
    "span[email][name]",
    "span[email]",
    "[data-hovercard-id][email]"
  ], scope);
}

function extractSenderInfo(scope = document) {
  const senderElement = findGmailSenderElement(scope) || findGmailSenderElement(document);
  if (!senderElement) {
    return { name: "", email: "", element: null };
  }
  return {
    name: normalizeWhitespace(
      senderElement.getAttribute("name")
      || senderElement.getAttribute("data-name")
      || senderElement.textContent
    ),
    email: normalizeWhitespace(
      senderElement.getAttribute("email")
      || senderElement.getAttribute("data-hovercard-id")
      || ""
    ),
    element: senderElement
  };
}

function extractGmailWarnings(scope = document) {
  const warnings = new Set();
  for (const selector of ["[role='alert']", ".aT", ".qh", ".qj", ".ajy"]) {
    for (const element of scope.querySelectorAll(selector)) {
      if (!isElementVisible(element)) {
        continue;
      }
      const text = normalizeWhitespace(element.innerText || element.textContent || "");
      if (text && text.length > 8) {
        warnings.add(text.slice(0, 500));
      }
    }
  }
  return Array.from(warnings).slice(0, 10);
}

function extractGmailAttachments(scope = document) {
  const attachments = new Set();
  for (const element of scope.querySelectorAll("[download_url], [data-tooltip*='Download'], div[command*='view=att']")) {
    if (!isElementVisible(element)) {
      continue;
    }
    const text = normalizeWhitespace(
      element.getAttribute("download_url")
      || element.getAttribute("aria-label")
      || element.innerText
      || element.textContent
      || ""
    );
    if (text) {
      attachments.add(text.slice(0, 240));
    }
  }
  return Array.from(attachments).slice(0, 20);
}

function extractEmailLinks(bodyElement) {
  const links = [];
  const seen = new Set();
  for (const anchor of bodyElement?.querySelectorAll?.("a[href]") || []) {
    const href = String(anchor.href || anchor.getAttribute("href") || "").trim();
    if (!href || seen.has(href)) {
      continue;
    }
    seen.add(href);
    links.push({
      text: normalizeWhitespace(anchor.innerText || anchor.textContent || "").slice(0, 200),
      href: href.slice(0, 500)
    });
    if (links.length >= 30) {
      break;
    }
  }
  return links;
}

function buildCaptureRect(elements) {
  const rects = elements
    .filter((element) => isElementVisible(element))
    .map((element) => element.getBoundingClientRect())
    .filter((rect) => rect.width > 0 && rect.height > 0);
  if (!rects.length) {
    return null;
  }
  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;
  const left = Math.max(0, Math.min(...rects.map((rect) => rect.left)) - 16);
  const top = Math.max(0, Math.min(...rects.map((rect) => rect.top)) - 16);
  const right = Math.min(viewportWidth, Math.max(...rects.map((rect) => rect.right)) + 16);
  const bottom = Math.min(viewportHeight, Math.max(...rects.map((rect) => rect.bottom)) + 16);

  return {
    x: Math.max(0, Math.round(left)),
    y: Math.max(0, Math.round(top)),
    width: Math.max(1, Math.round(right - left)),
    height: Math.max(1, Math.round(bottom - top)),
    viewportWidth,
    viewportHeight,
    devicePixelRatio: window.devicePixelRatio || 1
  };
}

function buildEmailPageContext(messageContainer, bodyElement, subjectElement) {
  return {
    url: window.location.href,
    title: document.title || "",
    provider: "gmail",
    subjectVisible: Boolean(subjectElement),
    bodyChars: getVisibleTextLength(bodyElement),
    bodyNodeCount: bodyElement?.querySelectorAll?.("*")?.length || 0,
    messageNodeCount: messageContainer?.querySelectorAll?.("*")?.length || 0,
    capturedAt: new Date().toISOString()
  };
}

function collectOpenGmailMessagePayload() {
  if (!isGmailPage()) {
    return null;
  }

  const bodyElement = findGmailBodyElement();
  const subjectElement = findGmailSubjectElement();
  if (!bodyElement || (!subjectElement && getVisibleTextLength(bodyElement) < 40)) {
    return null;
  }

  const messageContainer = findGmailMessageContainer(bodyElement);
  const senderInfo = extractSenderInfo(messageContainer || document);
  const attachments = extractGmailAttachments(messageContainer || document);

  return {
    provider: "gmail",
    pageUrl: window.location.href,
    senderName: senderInfo.name,
    senderEmail: senderInfo.email,
    subject: normalizeWhitespace(subjectElement?.innerText || subjectElement?.textContent || ""),
    bodyText: normalizeWhitespace(bodyElement.innerText || bodyElement.textContent || ""),
    links: extractEmailLinks(bodyElement),
    attachments,
    warnings: extractGmailWarnings(messageContainer || document),
    pageContext: buildEmailPageContext(messageContainer, bodyElement, subjectElement),
    captureRect: buildCaptureRect([
      subjectElement,
      senderInfo.element,
      bodyElement,
      ...(messageContainer ? Array.from(messageContainer.querySelectorAll("[download_url]")).slice(0, 3) : [])
    ].filter(Boolean))
  };
}

function updateGmailAssistantUi() {
  if (!shadow) {
    return;
  }
  const gmailShell = shadow.getElementById("gmailShell");
  const gmailCheckButton = shadow.getElementById("gmailCheckButton");
  const gmailHelper = shadow.getElementById("gmailHelper");
  if (!gmailShell || !gmailCheckButton) {
    return;
  }

  const payload = collectOpenGmailMessagePayload();
  const protectionEnabled = Boolean(currentDisplayOptions.protectionEnabled);
  const shouldShow = Boolean(payload) && protectionEnabled;
  gmailShell.classList.toggle("hidden", !shouldShow);
  if (!shouldShow) {
    if (!protectionEnabled) {
      emailCheckState = {
        status: "idle",
        error: "",
        result: null
      };
      if (consentMode === "email" && !emailCheckManualMode) {
        hideConsentOverlay();
      }
      if (activeResultMode === "email" && !emailCheckManualMode) {
        hideFullCheckResults();
      }
    }
    if (emailCheckState.status !== "running") {
      emailCheckState = {
        status: "idle",
        error: "",
        result: null
      };
    }
    return;
  }

  const lang = currentLanguage();
  gmailCheckButton.disabled = emailCheckState.status === "running" || !protectionEnabled;
  if (emailCheckState.status === "running") {
    gmailCheckButton.textContent = t(lang, "emailCheckRunning");
    gmailHelper.textContent = t(lang, "emailCheckHelper");
    gmailHelper.classList.remove("disabled");
    return;
  }
  gmailCheckButton.textContent = t(lang, "emailCheckAction");
  gmailHelper.textContent = protectionEnabled
    ? t(lang, "emailCheckHelper")
    : t(lang, "emailCheckEnableProtection");
  gmailHelper.classList.toggle("disabled", !protectionEnabled);
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
      showConsentOverlay("", "page");
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

async function requestEmailCheck(allowNow) {
  const lang = currentLanguage();
  const manual = emailCheckManualMode;
  setConsentBusy(true, t(lang, "emailConsentSending"));
  emailCheckState = {
    status: "running",
    error: "",
    result: null
  };
  updateGmailAssistantUi();

    try {
      const response = await api.runtime.sendMessage({
        type: "surfphish:request-email-check",
        allowNow: Boolean(allowNow),
        manual
      });

    if (response?.requiresConsent) {
      showConsentOverlay("", "email");
      setConsentBusy(false, "");
      emailCheckState = {
        status: "idle",
        error: "",
        result: null
      };
      updateGmailAssistantUi();
      return;
    }

    if (!response?.ok) {
      const errorMessage = response?.error || t(lang, "emailConsentFailed");
      setConsentBusy(false, errorMessage);
      emailCheckState = {
        status: "error",
        error: errorMessage,
        result: null
      };
      updateGmailAssistantUi();
      return;
    }

    hideConsentOverlay();
    emailCheckState = {
      status: "complete",
      error: "",
      result: response.result || null
    };
    updateGmailAssistantUi();
      showFullCheckResults(
        response.result?.full_check_analysis || null,
        response.result?.full_check_analysis_error?.message || t(lang, "emailResultUnavailable"),
        {
          titleKey: "emailResultTitle",
          introKey: "emailResultIntro",
          hideLeaveAction: true,
          mode: "email"
        }
      );
  } catch (error) {
    const errorMessage = error.message || t(lang, "emailConsentFailed");
    setConsentBusy(false, errorMessage);
    emailCheckState = {
      status: "error",
      error: errorMessage,
      result: null
    };
    updateGmailAssistantUi();
  }
}

function renderBanner(state) {
  const lang = currentLanguage();
  const card = shadow.getElementById("card");
  const dangerMark = shadow.getElementById("dangerMark");
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
  dangerMark.style.display = isBenign ? "none" : "inline-flex";

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
  scheduleBannerAutoHide(state);
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
  const preserveEmailConsentOverlay = consentMode === "email"
    && (emailCheckManualMode || emailCheckState.status === "running");
  const preserveEmailResultOverlay = activeResultMode === "email";

  if (!payload?.showBanner || !currentState) {
    hideBanner();
    if (!preserveEmailConsentOverlay) {
      hideConsentOverlay();
    }
    if (!preserveEmailResultOverlay) {
      hideFullCheckResults();
    }
    updateGmailAssistantUi();
    return;
  }

  if (currentState.status === "error") {
    hideBanner();
    if (!preserveEmailConsentOverlay) {
      hideConsentOverlay();
    }
    if (!preserveEmailResultOverlay) {
      hideFullCheckResults();
    }
    updateGmailAssistantUi();
    return;
  }

  if (currentState.status !== "ready") {
    hideBanner();
    if (!preserveEmailConsentOverlay) {
      hideConsentOverlay();
    }
    if (!preserveEmailResultOverlay) {
      hideFullCheckResults();
    }
    updateGmailAssistantUi();
    return;
  }

  if (currentState.status === "whitelisted") {
    hideBanner();
    if (!preserveEmailConsentOverlay) {
      hideConsentOverlay();
    }
    if (!preserveEmailResultOverlay) {
      hideFullCheckResults();
    }
    updateGmailAssistantUi();
    return;
  }

  if (String(currentState.summary?.riskLevel || "").toUpperCase() === "LOW") {
    hideBanner();
    const detailedStatus = String(currentState.detailedCheck?.status || "");
    if (!["running", "complete", "error"].includes(detailedStatus)) {
      if (!preserveEmailConsentOverlay) {
        hideConsentOverlay();
      }
      if (!preserveEmailResultOverlay) {
        hideFullCheckResults();
      }
    }
    updateGmailAssistantUi();
    return;
  }

  renderBanner(currentState);
  updateGmailAssistantUi();
}

function sanitizeClonedDomForStructure(rootElement) {
  const nodeStack = [rootElement];
  while (nodeStack.length) {
    const node = nodeStack.pop();
    if (!node) {
      continue;
    }

    if (node.nodeType === Node.TEXT_NODE) {
      node.textContent = "";
      continue;
    }

    if (node.nodeType === Node.COMMENT_NODE) {
      node.textContent = "";
      continue;
    }

    if (node.nodeType !== Node.ELEMENT_NODE) {
      continue;
    }

    for (const attr of Array.from(node.attributes || [])) {
      node.setAttribute(attr.name, "1");
    }

    const children = Array.from(node.childNodes || []);
    for (let index = children.length - 1; index >= 0; index -= 1) {
      nodeStack.push(children[index]);
    }
  }
}

function buildSerializedHtml(options = {}) {
  const includeFullHtml = Boolean(options.includeFullHtml);
  const doctype = document.doctype
    ? new XMLSerializer().serializeToString(document.doctype)
    : "<!DOCTYPE html>";
  const clonedRoot = document.documentElement.cloneNode(true);
  clonedRoot.querySelector("#surfphish-root")?.remove();
  if (!includeFullHtml) {
    sanitizeClonedDomForStructure(clonedRoot);
  }
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

async function buildCompressedPagePayload(options = {}) {
  const includeFullHtml = Boolean(options.includeFullHtml);
  const html = buildSerializedHtml({ includeFullHtml });
  const pageContext = buildPageContext(html);
  const fallbackPayload = {
    sourceUrl: window.location.href,
    html,
    htmlEncoding: "identity",
    pageContext,
    payloadMode: includeFullHtml ? "full_html" : "dom_structure"
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
      pageContext,
      payloadMode: includeFullHtml ? "full_html" : "dom_structure"
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

function handleRuntimeMessage(message) {
  if (message?.type === "surfphish:show-full-check-consent") {
    ensureUi();
    applyStaticText();
    showConsentOverlay("", "page");
    return Promise.resolve({ ok: true });
  }
  if (message?.type === "surfphish:show-email-check-consent") {
    ensureUi();
    applyStaticText();
    showConsentOverlay("", "email", { manual: Boolean(message.manual) });
    return Promise.resolve({ ok: true });
  }
  if (message?.type === "surfphish:collect-email-payload") {
    return Promise.resolve(collectOpenGmailMessagePayload());
  }
    if (message?.type === "surfphish:collect-page-payload") {
      return buildCompressedPagePayload({
        includeFullHtml: Boolean(message.fullHtml)
      });
    }
  if (message?.type === "surfphish:prepare-email-capture") {
    hideExtensionUiForCapture();
    return Promise.resolve({ ok: true });
  }
  if (message?.type === "surfphish:restore-email-capture") {
    restoreExtensionUiAfterCapture();
    return Promise.resolve({ ok: true });
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
  if (message?.type === "surfphish:scan-update") {
    renderState(message.payload);
    return Promise.resolve(undefined);
  }
  return null;
}

api.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  const handled = handleRuntimeMessage(message);
  if (!handled) {
    return false;
  }
  handled
    .then((result) => sendResponse(result))
    .catch((error) => sendResponse({ ok: false, error: error?.message || String(error) }));
  return true;
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

window.setInterval(() => {
  if (!root) {
    return;
  }
  updateGmailAssistantUi();
}, 1500);
