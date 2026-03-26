const api = globalThis.browser ?? globalThis.chrome;
const { DEFAULT_UI_LANGUAGE, normalizeUiLanguage } = globalThis.SurfPhishI18n;

const DEFAULT_SETTINGS = {
  apiBaseUrl: "https://7uc9we0gs0w6arve4ara.duckdns.org",
  scanTimeout: 15,
  autoScan: true,
  showBanner: true,
  blockHighRiskInterstitial: false,
  insecureFetch: false,
  badgeOnLowRisk: true,
  protectionEnabled: false,
  uiLanguage: DEFAULT_UI_LANGUAGE,
  whitelistRules: []
};

const RECENT_SCAN_TTL_MS = 5 * 60 * 1000;
const MAX_FEEDBACK_EVENTS = 200;
const MAX_USER_SITE_DECISIONS = 500;
const MAX_STITCHED_PIXELS = 16_000_000;
const MAX_FULLPAGE_CAPTURE_SCROLLS = 6;
const CAPTURE_SETTLE_MS = 420;
const LOOKUP_API_URL = "https://ynhy80qtt6.execute-api.us-west-2.amazonaws.com/prod/lookup";
const LOOKUP_TIMEOUT_MS = 8000;
const MAX_LOOKUP_ITEMS = 10;

const tabState = new Map();
const tabTimers = new Map();
const tabTokens = new Map();
const tabBypasses = new Map();
const recentScanCache = new Map();
let settings = { ...DEFAULT_SETTINGS };
let userSiteDecisions = {};

function normalizeApiBaseUrl(value) {
  return String(value || DEFAULT_SETTINGS.apiBaseUrl).trim().replace(/\/+$/, "");
}

function isScannableUrl(url) {
  return /^https?:\/\//i.test(url || "");
}

function normalizeUiSettings(stored) {
  const migratedProtectionEnabled = typeof stored.protectionEnabled === "boolean"
    ? stored.protectionEnabled
    : ["always", "session"].includes(stored.protectionPermissionPolicy)
      || ["always", "session"].includes(stored.detailedScreenshotPermissionPolicy);
  return {
    ...DEFAULT_SETTINGS,
    ...stored,
    apiBaseUrl: normalizeApiBaseUrl(stored.apiBaseUrl ?? DEFAULT_SETTINGS.apiBaseUrl),
    protectionEnabled: migratedProtectionEnabled,
    uiLanguage: normalizeUiLanguage(stored.uiLanguage ?? DEFAULT_SETTINGS.uiLanguage),
    whitelistRules: normalizeWhitelistRules(
      stored.whitelistRules
      ?? stored.whitelistUrls
      ?? DEFAULT_SETTINGS.whitelistRules
    )
  };
}

function normalizeHostname(hostname) {
  return String(hostname || "").trim().toLowerCase().replace(/\.+$/, "");
}

function hostnameFromUrl(url) {
  if (!isScannableUrl(url)) {
    return "";
  }
  try {
    return normalizeHostname(new URL(url).hostname);
  } catch (error) {
    return "";
  }
}

function isLocalSafeHost(hostname) {
  const normalized = normalizeHostname(hostname);
  if (!normalized) {
    return false;
  }
  if (normalized === "localhost" || normalized === "127.0.0.1" || normalized === "[::1]" || normalized === "::1") {
    return true;
  }
  if (/^127\.\d+\.\d+\.\d+$/.test(normalized)) {
    return true;
  }
  if (/^10\.\d+\.\d+\.\d+$/.test(normalized)) {
    return true;
  }
  if (/^192\.168\.\d+\.\d+$/.test(normalized)) {
    return true;
  }
  const private172 = normalized.match(/^172\.(\d+)\.\d+\.\d+$/);
  if (private172) {
    const second = Number(private172[1]);
    if (second >= 16 && second <= 31) {
      return true;
    }
  }
  return false;
}

function isLocalSafeUrl(url) {
  return isLocalSafeHost(hostnameFromUrl(url));
}

function normalizeScannableUrl(url) {
  if (!isScannableUrl(url)) {
    return "";
  }
  try {
    const parsed = new URL(url);
    parsed.hash = "";
    return parsed.toString();
  } catch (error) {
    return "";
  }
}

function normalizeWhitelistRule(rule) {
  const value = String(rule || "").trim().toLowerCase();
  if (!value) {
    return null;
  }

  if (isScannableUrl(value)) {
    try {
      const parsed = new URL(value);
      parsed.hash = "";
      return parsed.toString();
    } catch (error) {
      return null;
    }
  }

  return value
    .replace(/^\*\./, "")
    .replace(/^\.+/, "")
    .replace(/\/+$/, "");
}

function normalizeWhitelistRules(rules) {
  const unique = new Set();
  for (const rule of Array.isArray(rules) ? rules : []) {
    const normalized = normalizeWhitelistRule(rule);
    if (normalized) {
      unique.add(normalized);
    }
  }
  return Array.from(unique).sort();
}

function ruleMatchesUrl(rule, url) {
  const normalizedRule = normalizeWhitelistRule(rule);
  if (!normalizedRule) {
    return false;
  }

  if (isScannableUrl(normalizedRule)) {
    const normalizedUrl = normalizeWhitelistRule(url);
    return Boolean(normalizedUrl && normalizedUrl === normalizedRule);
  }

  const hostname = hostnameFromUrl(url);
  if (!hostname) {
    return false;
  }
  return hostname === normalizedRule || hostname.endsWith(`.${normalizedRule}`);
}

function getEffectiveWhitelistRules() {
  return normalizeWhitelistRules(settings.whitelistRules || []);
}

function normalizeWhitelistEntryFromUrl(url) {
  return normalizeScannableUrl(url) || normalizeWhitelistRule(url);
}

function isWhitelistedUrl(url) {
  return isLocalSafeUrl(url) || getEffectiveWhitelistRules().some((rule) => ruleMatchesUrl(rule, url));
}

function buildWhitelistedState(url) {
  const localSafe = isLocalSafeUrl(url);
  return {
    status: "whitelisted",
    url,
    whitelistEntry: localSafe ? hostnameFromUrl(url) : normalizeWhitelistEntryFromUrl(url),
    localSafe,
    updatedAt: Date.now()
  };
}

async function recordFeedbackEvent(kind, state, extra = {}) {
  const event = {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
    kind,
    createdAt: new Date().toISOString(),
    url: state?.url || "",
    summary: state?.summary || null,
    pageContext: state?.pageContext || null,
    tabId: extra.tabId || null,
    ...extra
  };

  const stored = await api.storage.local.get({ feedbackEvents: [] });
  const nextEvents = [event, ...(Array.isArray(stored.feedbackEvents) ? stored.feedbackEvents : [])]
    .slice(0, MAX_FEEDBACK_EVENTS);
  await api.storage.local.set({ feedbackEvents: nextEvents });
  return event;
}

async function submitFeedbackToBackend(event) {
  let pagePayload = null;
  if (event.tabId && event.url && isScannableUrl(event.url)) {
    try {
      pagePayload = await withTimeout(
        api.tabs.sendMessage(event.tabId, {
          type: "surfphish:collect-page-payload"
        }),
        5000,
        "Timed out while collecting page DOM for feedback."
      );
    } catch (error) {
      console.warn("[SurfPhish] Failed to collect page DOM for feedback.", error);
    }
  }
  const response = await fetch(`${settings.apiBaseUrl}/api/feedback`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      kind: event.kind,
      source: event.source || "extension",
      url: event.url,
      source_url: pagePayload?.sourceUrl || event.url,
      html: pagePayload?.html ?? null,
      html_gzip_base64: pagePayload?.htmlGzipBase64 ?? null,
      html_encoding: pagePayload?.htmlEncoding ?? "identity",
      page_context: pagePayload?.pageContext || event.pageContext || null,
      summary: event.summary || null,
      notes: event.notes || []
    })
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.error || `Feedback API failed with ${response.status}`);
  }
  return response.json();
}

function clearBypassIfUrlChanged(tabId, url) {
  const bypass = tabBypasses.get(tabId);
  if (bypass && bypass.url !== url) {
    tabBypasses.delete(tabId);
  }
}

function getRecentScanCache(url) {
  const key = normalizeScannableUrl(url);
  if (!key) {
    return null;
  }
  const cached = recentScanCache.get(key);
  if (!cached) {
    return null;
  }
  if ((Date.now() - cached.cachedAt) > RECENT_SCAN_TTL_MS) {
    recentScanCache.delete(key);
    return null;
  }
  return cached;
}

function setRecentScanCache(url, value) {
  const key = normalizeScannableUrl(url);
  if (!key) {
    return;
  }
  recentScanCache.set(key, {
    ...value,
    cachedAt: Date.now()
  });
}

function getBypassForTab(tabId, url) {
  const bypass = tabBypasses.get(tabId);
  if (!bypass || bypass.url !== url) {
    return null;
  }
  return bypass;
}

async function loadSettings() {
  const stored = await api.storage.local.get({
    ...DEFAULT_SETTINGS,
    detailedScreenshotPermissionPolicy: "",
    userSiteDecisions: {}
  });
  settings = normalizeUiSettings(stored);
  userSiteDecisions = stored.userSiteDecisions && typeof stored.userSiteDecisions === "object"
    ? stored.userSiteDecisions
    : {};
}

function getUserSiteDecision(url) {
  const key = normalizeScannableUrl(url);
  if (!key) {
    return null;
  }
  const entry = userSiteDecisions[key];
  if (!entry || typeof entry !== "object") {
    return null;
  }
  return {
    ...entry,
    url: key
  };
}

async function persistUserSiteDecision(url, verdict, source = "unknown") {
  const key = normalizeScannableUrl(url);
  if (!key) {
    return null;
  }
  const nextDecisions = {
    ...userSiteDecisions,
    [key]: {
      verdict,
      source,
      reportedAt: new Date().toISOString(),
      updatedAt: Date.now()
    }
  };
  const entries = Object.entries(nextDecisions)
    .sort((a, b) => Number(b[1]?.updatedAt || 0) - Number(a[1]?.updatedAt || 0))
    .slice(0, MAX_USER_SITE_DECISIONS);
  userSiteDecisions = Object.fromEntries(entries);
  await api.storage.local.set({ userSiteDecisions });
  return userSiteDecisions[key] || null;
}

async function removeUserSiteDecision(url) {
  const key = normalizeScannableUrl(url);
  if (!key || !userSiteDecisions[key]) {
    return false;
  }
  const nextDecisions = { ...userSiteDecisions };
  delete nextDecisions[key];
  userSiteDecisions = nextDecisions;
  await api.storage.local.set({ userSiteDecisions });
  return true;
}

function applyRememberedDecision(state, rememberedDecision) {
  if (!rememberedDecision) {
    return state;
  }

  const nextState = {
    ...state,
    feedback: {
      ...(state.feedback || {})
    }
  };

  if (rememberedDecision.verdict === "phishing") {
    nextState.feedback.siteReportedAt = rememberedDecision.reportedAt;
    nextState.feedback.siteReportedPersisted = true;
  }

  if (rememberedDecision.verdict === "not_phishing") {
    nextState.feedback.falsePositiveReportedAt = rememberedDecision.reportedAt;
    nextState.feedback.falsePositivePersisted = true;
    nextState.decision = {
      ...(state.decision || {}),
      ignored: true,
      ignoredAt: rememberedDecision.reportedAt,
      markedSafe: true,
      rememberedSafe: true
    };
  }

  return nextState;
}

function summarizeResult(scanResult) {
  const phishingScore = Number(scanResult.phishing_score || 0);
  return {
    prediction: scanResult.prediction || "unknown",
    riskLevel: scanResult.risk_level || "UNKNOWN",
    phishingScore,
    phishingPercent: Math.round(phishingScore * 100),
    reconstructionError: Number(scanResult.reconstruction_error || 0),
    threshold: Number(scanResult.threshold || 0),
    thresholdMargin: Number((scanResult.reconstruction_error || 0) - (scanResult.threshold || 0)),
    classifierBenignScore: Number(scanResult.classifier_benign_score || 0),
    thresholdBenignScore: Number(scanResult.threshold_benign_score || 0),
    fusedBenignScore: Number(scanResult.fused_benign_score || 0),
    errorOnlyPrediction: scanResult.error_only_prediction || "unknown",
    isPhishing: Boolean(scanResult.is_phishing)
  };
}

function applyLookupRiskToSummary(summary, lookup) {
  const baseSummary = summary && typeof summary === "object" ? summary : summarizeResult({});
  if (!lookup || lookup.status !== "complete" || !lookup.found) {
    return baseSummary;
  }

  return {
    ...baseSummary,
    riskLevel: "HIGH",
    isPhishing: true,
    lookupMatched: true,
    lookupMatchCount: toFiniteNumber(lookup.matchCount, 0),
    riskSource: baseSummary.isPhishing ? "scanner+lookup" : "lookup"
  };
}

function toFiniteNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function uniqueStrings(values) {
  return Array.from(new Set(
    (Array.isArray(values) ? values : [])
      .map((value) => String(value || "").trim())
      .filter(Boolean)
  ));
}

function compactLookupCandidate(candidate) {
  if (!candidate || typeof candidate !== "object") {
    return null;
  }
  return {
    indicatorType: String(candidate.indicator_type || "").trim(),
    indicator: String(candidate.indicator || "").trim(),
    indicatorKey: String(candidate.indicator_key || "").trim(),
    matchedVia: String(candidate.matched_via || "").trim()
  };
}

function compactLookupMatch(match) {
  if (!match || typeof match !== "object") {
    return null;
  }
  return {
    indicatorType: String(match.indicator_type || "").trim(),
    indicator: String(match.indicator || "").trim(),
    matchedVia: String(match.matched_via || "").trim(),
    recordStatuses: uniqueStrings(match.record_statuses),
    sourceIds: uniqueStrings(match.source_ids),
    brands: uniqueStrings(match.brands),
    runId: String(match.run_id || "").trim(),
    rebuildRunId: String(match.rebuild_run_id || "").trim()
  };
}

function summarizeLookupPayload(payload, url, domain) {
  const candidates = (Array.isArray(payload?.candidates) ? payload.candidates : [])
    .map((candidate) => compactLookupCandidate(candidate))
    .filter(Boolean)
    .slice(0, MAX_LOOKUP_ITEMS);
  const matches = (Array.isArray(payload?.matches) ? payload.matches : [])
    .map((match) => compactLookupMatch(match))
    .filter(Boolean)
    .slice(0, MAX_LOOKUP_ITEMS);

  return {
    status: "complete",
    queriedUrl: url,
    queriedDomain: domain,
    found: Boolean(payload?.found),
    matchCount: toFiniteNumber(payload?.match_count, matches.length),
    candidateCount: toFiniteNumber(payload?.candidate_count, candidates.length),
    query: payload?.query && typeof payload.query === "object" ? payload.query : null,
    indexMetadata: payload?.index_metadata && typeof payload.index_metadata === "object"
      ? payload.index_metadata
      : null,
    matches,
    candidates,
    sourceIds: uniqueStrings(matches.flatMap((match) => match.sourceIds || [])),
    recordStatuses: uniqueStrings(matches.flatMap((match) => match.recordStatuses || [])),
    brands: uniqueStrings(matches.flatMap((match) => match.brands || [])),
    updatedAt: Date.now()
  };
}

async function lookupThreatDatabase(url) {
  const normalizedUrl = normalizeScannableUrl(url);
  const domain = hostnameFromUrl(url);
  if (!normalizedUrl) {
    return {
      status: "skipped",
      queriedUrl: url,
      queriedDomain: domain,
      updatedAt: Date.now()
    };
  }

  try {
    const response = await withTimeout(
      fetch(LOOKUP_API_URL, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          indicator: normalizedUrl,
          indicator_type: "url",
          url: normalizedUrl,
          domain: domain || undefined
        })
      }),
      LOOKUP_TIMEOUT_MS,
      "Timed out while querying the external security database."
    );
    const payload = await response.json().catch(() => null);

    if (!response.ok) {
      return {
        status: "error",
        queriedUrl: normalizedUrl,
        queriedDomain: domain,
        error: payload?.error || `Lookup API failed with ${response.status}`,
        updatedAt: Date.now()
      };
    }

    return summarizeLookupPayload(payload, normalizedUrl, domain);
  } catch (error) {
    return {
      status: "error",
      queriedUrl: normalizedUrl,
      queriedDomain: domain,
      error: error.message || "Unknown lookup error",
      updatedAt: Date.now()
    };
  }
}

function badgeAppearance(state) {
  if (!state || state.status === "idle") {
    return { text: "", color: [0, 0, 0, 0] };
  }
  if (state.status === "scanning") {
    return { text: "...", color: "#2563eb" };
  }
  if (state.status === "whitelisted") {
    return { text: "WL", color: "#0f766e" };
  }
  if (state.status === "error") {
    return { text: "ERR", color: "#6b7280" };
  }

  const riskLevel = state.summary?.riskLevel || "UNKNOWN";
  if (riskLevel === "HIGH") {
    return { text: "HI", color: "#b91c1c" };
  }
  if (riskLevel === "MEDIUM") {
    return { text: "MED", color: "#b45309" };
  }
  if (riskLevel === "LOW" && settings.badgeOnLowRisk) {
    return { text: "LOW", color: "#0f766e" };
  }
  return { text: "", color: [0, 0, 0, 0] };
}

async function applyBadge(tabId, state) {
  const appearance = badgeAppearance(state);
  await api.action.setBadgeText({ tabId, text: appearance.text });
  await api.action.setBadgeBackgroundColor({ tabId, color: appearance.color });
}

async function pushContentUpdate(tabId, state) {
  try {
    await api.tabs.sendMessage(tabId, {
      type: "surfphish:scan-update",
      payload: {
        state,
        showBanner: settings.showBanner,
        blockHighRiskInterstitial: settings.blockHighRiskInterstitial,
        uiLanguage: settings.uiLanguage
      }
    });
  } catch (error) {
    // Ignore tabs where the content script is not available yet.
  }
}

async function setTabState(tabId, nextState) {
  tabState.set(tabId, nextState);
  await applyBadge(tabId, nextState);
  await pushContentUpdate(tabId, nextState);
}

function buildErrorState(url, errorMessage, extra = {}) {
  return {
    status: "error",
    url,
    error: errorMessage,
    ...extra,
    updatedAt: Date.now()
  };
}

function buildLookupRiskState(url, lookup, errorMessage, extra = {}) {
  return {
    status: "ready",
    url,
    summary: applyLookupRiskToSummary(summarizeResult({}), lookup),
    rawResult: null,
    timings: {},
    pageContext: extra.pageContext || null,
    lookup: lookup || null,
    decision: extra.decision || null,
    detailedCheck: extra.detailedCheck || null,
    collectorError: errorMessage,
    updatedAt: Date.now()
  };
}

function withTimeout(promise, ms, message) {
  return Promise.race([
    promise,
    new Promise((_, reject) => {
      setTimeout(() => reject(new Error(message)), ms);
    })
  ]);
}

function isProtectionEnabled() {
  return Boolean(settings.protectionEnabled);
}

async function setProtectionEnabled(enabled) {
  settings.protectionEnabled = Boolean(enabled);
  await api.storage.local.set({ protectionEnabled: settings.protectionEnabled });
  return settings.protectionEnabled;
}

async function clearProtectionUiForAllTabs() {
  const tabs = await api.tabs.query({});
  await Promise.allSettled(
    tabs
      .filter((tab) => typeof tab.id === "number")
      .map((tab) => setTabState(tab.id, {
        status: "idle",
        url: tab.url || "",
        updatedAt: Date.now()
      }))
  );
}

async function syncProtectionStateAfterSettingsChange() {
  if (!isProtectionEnabled() || !settings.autoScan) {
    await clearProtectionUiForAllTabs();
    return;
  }

  const activeTab = await getActiveTab();
  if (activeTab?.id && isScannableUrl(activeTab.url)) {
    scheduleScan(activeTab.id, activeTab.url, false);
  }
}

async function collectPagePayload(tabId, url) {
  console.debug("[SurfPhish] Requesting DOM payload from tab.", { tabId, url });
  return withTimeout(
    api.tabs.sendMessage(tabId, {
      type: "surfphish:collect-page-payload"
    }),
    5000,
    "Timed out while collecting page DOM."
  );
}

async function sendScanRequest(pagePayload, extra = {}) {
  return fetch(`${settings.apiBaseUrl}/api/scan`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      source_url: pagePayload.sourceUrl,
      html: pagePayload.html ?? null,
      html_gzip_base64: pagePayload.htmlGzipBase64 ?? null,
      html_encoding: pagePayload.htmlEncoding ?? "identity",
      page_context: pagePayload.pageContext ?? null,
      debug: false,
      ...extra
    })
  });
}

async function sendEmailScanRequest(emailPayload, extra = {}) {
  return fetch(`${settings.apiBaseUrl}/api/scan/email`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      provider: emailPayload.provider || "gmail",
      page_url: emailPayload.pageUrl,
      sender_name: emailPayload.senderName || "",
      sender_email: emailPayload.senderEmail || "",
      subject: emailPayload.subject || "",
      body_text: emailPayload.bodyText || "",
      links: Array.isArray(emailPayload.links) ? emailPayload.links : [],
      attachments: Array.isArray(emailPayload.attachments) ? emailPayload.attachments : [],
      warnings: Array.isArray(emailPayload.warnings) ? emailPayload.warnings : [],
      page_context: emailPayload.pageContext || null,
      debug: false,
      ...extra
    })
  });
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function buildCapturePositions(total, viewport) {
  if (total <= viewport) {
    return [0];
  }

  const positions = [];
  const last = Math.max(total - viewport, 0);
  for (let value = 0; value < last; value += viewport) {
    positions.push(value);
  }
  positions.push(last);
  return Array.from(new Set(positions));
}

function loadImage(dataUrl) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("Failed to decode captured screenshot tile."));
    image.src = dataUrl;
  });
}

function isMissingActiveTabPermissionError(error) {
  return /activeTab permission/i.test(String(error?.message || error || ""));
}

async function captureVisibleTabWithRetry(tabId, windowId) {
  try {
    return await api.tabs.captureVisibleTab(windowId, { format: "png" });
  } catch (error) {
    if (!isMissingActiveTabPermissionError(error)) {
      throw error;
    }

    await api.tabs.update(tabId, { active: true }).catch(() => {});
    await wait(180);
    return api.tabs.captureVisibleTab(windowId, { format: "png" });
  }
}

async function captureFullPageScreenshot(tabId) {
  const tab = await api.tabs.get(tabId);
  const metrics = await withTimeout(
    api.tabs.sendMessage(tabId, {
      type: "surfphish:prepare-fullpage-capture"
    }),
    5000,
    "Timed out while preparing full-page capture."
  );

  try {
    if (!metrics?.viewportWidth || !metrics?.viewportHeight) {
      throw new Error("Page capture metrics were unavailable.");
    }

    const totalWidth = Math.max(Number(metrics.documentWidth || 0), Number(metrics.viewportWidth || 0));
    const totalHeight = Math.max(Number(metrics.documentHeight || 0), Number(metrics.viewportHeight || 0));
    const viewportWidth = Number(metrics.viewportWidth || 0);
    const viewportHeight = Number(metrics.viewportHeight || 0);
    const pixelCount = totalWidth * totalHeight;
    const scale = pixelCount > MAX_STITCHED_PIXELS
      ? Math.sqrt(MAX_STITCHED_PIXELS / pixelCount)
      : 1;

    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(totalWidth * scale));
    canvas.height = Math.max(1, Math.round(totalHeight * scale));
    const context = canvas.getContext("2d");
    if (!context) {
      throw new Error("Canvas stitching context could not be created.");
    }
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, canvas.width, canvas.height);

    const xPositions = buildCapturePositions(totalWidth, viewportWidth);
    const allYPositions = buildCapturePositions(totalHeight, viewportHeight);
    const maxVerticalTiles = Math.max(1, MAX_FULLPAGE_CAPTURE_SCROLLS + 1);
    const yPositions = allYPositions.slice(0, maxVerticalTiles);

    for (const y of yPositions) {
      for (const x of xPositions) {
        const actual = await api.tabs.sendMessage(tabId, {
          type: "surfphish:set-fullpage-capture-scroll",
          x,
          y
        });
        await wait(CAPTURE_SETTLE_MS);

        const tileDataUrl = await captureVisibleTabWithRetry(tabId, tab.windowId);
        const image = await loadImage(tileDataUrl);
        const captureX = Number(actual?.x ?? x);
        const captureY = Number(actual?.y ?? y);
        const visibleWidth = Math.min(viewportWidth, Math.max(totalWidth - captureX, 1));
        const visibleHeight = Math.min(viewportHeight, Math.max(totalHeight - captureY, 1));
        const sourceWidth = image.naturalWidth * (visibleWidth / viewportWidth);
        const sourceHeight = image.naturalHeight * (visibleHeight / viewportHeight);

        context.drawImage(
          image,
          0,
          0,
          sourceWidth,
          sourceHeight,
          Math.round(captureX * scale),
          Math.round(captureY * scale),
          Math.round(visibleWidth * scale),
          Math.round(visibleHeight * scale)
        );
      }
    }

    // Temporary debugging path kept as a quick fallback if we need to validate
    // the downstream API with a smaller single-viewport image again.
    //
    // await wait(CAPTURE_SETTLE_MS);
    // const dataUrl = await api.tabs.captureVisibleTab(tab.windowId, { format: "png" });
    // const image = await loadImage(dataUrl);

    const dataUrl = canvas.toDataURL("image/jpeg", 0.88);
    const [, imageBase64 = ""] = dataUrl.split(",", 2);
    return {
      screenshotPngBase64: imageBase64,
      screenshotFormat: "jpeg",
      screenshotWidth: canvas.width,
      screenshotHeight: canvas.height,
      screenshotScale: scale,
      screenshotCaptureMode: "scrolling-stitching",
      screenshotScrollLimit: MAX_FULLPAGE_CAPTURE_SCROLLS,
      screenshotWasScrollLimited: allYPositions.length > yPositions.length
    };
  } finally {
    await api.tabs.sendMessage(tabId, {
      type: "surfphish:restore-fullpage-capture-scroll",
      x: metrics.scrollX || 0,
      y: metrics.scrollY || 0
    }).catch(() => {});
  }
}

async function captureElementScreenshot(tabId, captureRect) {
  const tab = await api.tabs.get(tabId);
  await api.tabs.sendMessage(tabId, {
    type: "surfphish:prepare-email-capture"
  }).catch(() => {});

  try {
    const tileDataUrl = await captureVisibleTabWithRetry(tabId, tab.windowId);
    const image = await loadImage(tileDataUrl);
    const viewportWidth = Math.max(Number(captureRect?.viewportWidth || 0), 1);
    const viewportHeight = Math.max(Number(captureRect?.viewportHeight || 0), 1);
    const x = Math.max(0, Number(captureRect?.x || 0));
    const y = Math.max(0, Number(captureRect?.y || 0));
    const width = Math.max(1, Math.min(Number(captureRect?.width || 0), viewportWidth - x || viewportWidth));
    const height = Math.max(1, Math.min(Number(captureRect?.height || 0), viewportHeight - y || viewportHeight));
    const scaleX = image.naturalWidth / viewportWidth;
    const scaleY = image.naturalHeight / viewportHeight;

    const sourceX = Math.max(0, Math.round(x * scaleX));
    const sourceY = Math.max(0, Math.round(y * scaleY));
    const sourceWidth = Math.max(1, Math.round(width * scaleX));
    const sourceHeight = Math.max(1, Math.round(height * scaleY));

    const canvas = document.createElement("canvas");
    canvas.width = sourceWidth;
    canvas.height = sourceHeight;
    const context = canvas.getContext("2d");
    if (!context) {
      throw new Error("Canvas context could not be created for email capture.");
    }
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(
      image,
      sourceX,
      sourceY,
      sourceWidth,
      sourceHeight,
      0,
      0,
      sourceWidth,
      sourceHeight
    );

    const dataUrl = canvas.toDataURL("image/jpeg", 0.9);
    const [, imageBase64 = ""] = dataUrl.split(",", 2);
    return {
      screenshotPngBase64: imageBase64,
      screenshotFormat: "jpeg",
      screenshotWidth: canvas.width,
      screenshotHeight: canvas.height,
      screenshotScale: Number(captureRect?.devicePixelRatio || 1),
      screenshotCaptureMode: "gmail-message-crop"
    };
  } finally {
    await api.tabs.sendMessage(tabId, {
      type: "surfphish:restore-email-capture"
    }).catch(() => {});
  }
}

async function performDetailedCheck(tabId, allowNow = false) {
  const tab = await api.tabs.get(tabId);
  const url = tab?.url || "";
  const currentState = tabState.get(tabId);

  if (!isScannableUrl(url)) {
    return { ok: false, error: "This tab cannot be checked." };
  }

  if (!isProtectionEnabled()) {
    return { ok: false, error: "SurfPhish protection is not enabled for this browser session." };
  }

  if (!allowNow) {
    return { ok: false, requiresConsent: true };
  }

  const baseState = currentState && currentState.url === url
    ? currentState
    : {
        status: "ready",
        url,
        updatedAt: Date.now()
      };

  const runningState = {
    ...baseState,
    detailedCheck: {
      status: "running",
      startedAt: new Date().toISOString(),
      updatedAt: Date.now()
    },
    updatedAt: Date.now()
  };
  await setTabState(tabId, runningState);

  try {
    const pagePayload = await collectPagePayload(tabId, url);
    if (!pagePayload?.sourceUrl || (!pagePayload.html && !pagePayload.htmlGzipBase64)) {
      throw new Error("Page snapshot was empty or incomplete.");
    }

    const screenshotPayload = await captureFullPageScreenshot(tabId);
    const response = await sendScanRequest(pagePayload, {
      detail_level: "detailed",
      screenshot_png_base64: screenshotPayload.screenshotPngBase64,
      screenshot_format: screenshotPayload.screenshotFormat,
      screenshot_width: screenshotPayload.screenshotWidth,
      screenshot_height: screenshotPayload.screenshotHeight,
      screenshot_scale: screenshotPayload.screenshotScale,
      screenshot_capture_mode: screenshotPayload.screenshotCaptureMode
    });
    const payload = await response.json();

    if (!response.ok || !payload.result) {
      throw new Error(payload.error || `Scanner API failed with ${response.status}`);
    }

    const rememberedDecision = getUserSiteDecision(url);
    const fullCheckAnalysis = payload.result.full_check_analysis || null;
    const fullCheckAnalysisError = payload.result.full_check_analysis_error || null;
    const nextState = applyRememberedDecision({
      status: "ready",
      url,
      summary: summarizeResult(payload.result),
      rawResult: payload.result,
      timings: payload.timings || {},
      pageContext: pagePayload.pageContext || null,
      lookup: baseState.lookup || null,
      decision: baseState.decision || null,
      detailedCheck: {
        status: "complete",
        userConsented: true,
        screenshotCaptured: true,
        analysis: fullCheckAnalysis,
        analysisError: fullCheckAnalysisError,
        completedAt: new Date().toISOString(),
        updatedAt: Date.now()
      },
      updatedAt: Date.now()
    }, rememberedDecision);

    setRecentScanCache(url, {
      summary: nextState.summary,
      rawResult: nextState.rawResult,
      timings: nextState.timings,
      pageContext: nextState.pageContext,
      lookup: nextState.lookup || null
    });
    await setTabState(tabId, nextState);
    return { ok: true, state: nextState };
  } catch (error) {
    const errorMessage = isMissingActiveTabPermissionError(error)
      ? "Firefox did not grant tab capture permission for this page. Please reopen the SurfPhish popup on this tab and try Full Check again."
      : error.message;
    const failedState = {
      ...baseState,
      detailedCheck: {
        status: "error",
        error: errorMessage,
        updatedAt: Date.now()
      },
      updatedAt: Date.now()
    };
    await setTabState(tabId, failedState);
    return { ok: false, error: errorMessage, state: failedState };
  }
}

async function performEmailCheck(tabId, allowNow = false) {
  const tab = await api.tabs.get(tabId);
  const url = tab?.url || "";
  if (!isScannableUrl(url) || !/mail\.google\.com$/i.test(new URL(url).hostname)) {
    return { ok: false, error: "This tab is not an open Gmail message." };
  }
  if (!isProtectionEnabled()) {
    return { ok: false, error: "SurfPhish protection is not enabled for this browser session." };
  }
  if (!allowNow) {
    return { ok: false, requiresConsent: true };
  }

  try {
    const emailPayload = await withTimeout(
      api.tabs.sendMessage(tabId, {
        type: "surfphish:collect-email-payload"
      }),
      5000,
      "Timed out while collecting the current email."
    );

    if (!emailPayload?.pageUrl || (!emailPayload?.subject && !emailPayload?.bodyText)) {
      throw new Error("The current Gmail message could not be read.");
    }

    const screenshotPayload = emailPayload.captureRect
      ? await captureElementScreenshot(tabId, emailPayload.captureRect)
      : null;
    const response = await sendEmailScanRequest(emailPayload, {
      screenshot_png_base64: screenshotPayload?.screenshotPngBase64 || null,
      screenshot_format: screenshotPayload?.screenshotFormat || null,
      screenshot_width: screenshotPayload?.screenshotWidth || null,
      screenshot_height: screenshotPayload?.screenshotHeight || null,
      screenshot_scale: screenshotPayload?.screenshotScale || null,
      screenshot_capture_mode: screenshotPayload?.screenshotCaptureMode || null
    });
    const payload = await response.json();
    if (!response.ok || !payload.result) {
      throw new Error(payload.error || `Email analysis API failed with ${response.status}`);
    }
    return {
      ok: true,
      result: payload.result,
      timings: payload.timings || {}
    };
  } catch (error) {
    return {
      ok: false,
      error: error.message || "Email analysis failed."
    };
  }
}

async function scanTab(tabId, url, options = {}) {
  if (!isScannableUrl(url)) {
    clearBypassIfUrlChanged(tabId, url);
    await setTabState(tabId, {
      status: "idle",
      url,
      updatedAt: Date.now()
    });
    return;
  }

  if (!isProtectionEnabled()) {
    clearBypassIfUrlChanged(tabId, url);
    const nextState = {
      status: "idle",
      url,
      protectionDisabled: true,
      updatedAt: Date.now()
    };
    await setTabState(tabId, nextState);
    return nextState;
  }

  const current = tabState.get(tabId);
  if (!options.force && ["ready", "whitelisted"].includes(current?.status) && current.url === url) {
    return current;
  }

  clearBypassIfUrlChanged(tabId, url);

  if (isWhitelistedUrl(url)) {
    const nextState = buildWhitelistedState(url);
    await setTabState(tabId, nextState);
    return nextState;
  }

  if (!options.force) {
    const cached = getRecentScanCache(url);
    if (cached) {
      const rememberedDecision = getUserSiteDecision(url);
      const nextState = applyRememberedDecision({
        status: "ready",
        url,
        summary: cached.summary,
        rawResult: cached.rawResult,
        timings: cached.timings,
        pageContext: cached.pageContext,
        lookup: cached.lookup || null,
        decision: null,
        cached: true,
        cachedAt: cached.cachedAt,
        updatedAt: Date.now()
      }, rememberedDecision);
      await setTabState(tabId, nextState);
      return nextState;
    }
  }

  const scanToken = `${Date.now()}-${Math.random()}`;
  tabTokens.set(tabId, scanToken);
  const lookupPromise = lookupThreatDatabase(url);

  await setTabState(tabId, {
    status: "scanning",
    url,
    updatedAt: Date.now()
  });

  let response;
  let payload;
  let pagePayload;
  let lookup;
  try {
    pagePayload = await collectPagePayload(tabId, url);
  } catch (error) {
    lookup = await lookupPromise;
    const nextState = lookup?.status === "complete" && lookup.found
      ? buildLookupRiskState(url, lookup, `Cannot read page DOM: ${error.message}`)
      : buildErrorState(url, `Cannot read page DOM: ${error.message}`, { lookup });
    if (tabTokens.get(tabId) === scanToken) {
      await setTabState(tabId, nextState);
    }
    return nextState;
  }

  if (!pagePayload?.sourceUrl || (!pagePayload.html && !pagePayload.htmlGzipBase64)) {
    lookup = await lookupPromise;
    const nextState = lookup?.status === "complete" && lookup.found
      ? buildLookupRiskState(url, lookup, "Page snapshot was empty or incomplete.")
      : buildErrorState(url, "Page snapshot was empty or incomplete.", { lookup });
    if (tabTokens.get(tabId) === scanToken) {
      await setTabState(tabId, nextState);
    }
    return nextState;
  }

  try {
    console.debug("[SurfPhish] Sending page payload to scanner API.", {
      tabId,
      url,
      sourceUrl: pagePayload.sourceUrl,
      htmlEncoding: pagePayload.htmlEncoding,
      htmlChars: pagePayload.html?.length || 0,
      compressedChars: pagePayload.htmlGzipBase64?.length || 0
    });
    [lookup, response] = await Promise.all([
      lookupPromise,
      sendScanRequest(pagePayload, {
        detail_level: "standard"
      })
    ]);
    payload = await response.json();
    console.debug("[SurfPhish] Scanner API responded.", {
      tabId,
      url,
      ok: response.ok,
      status: response.status
    });
  } catch (error) {
    lookup = lookup || await lookupPromise;
    const nextState = lookup?.status === "complete" && lookup.found
      ? buildLookupRiskState(url, lookup, `Cannot reach scanner API: ${error.message}`, {
          pageContext: pagePayload?.pageContext || null
        })
      : buildErrorState(url, `Cannot reach scanner API: ${error.message}`, { lookup });
    if (tabTokens.get(tabId) === scanToken) {
      await setTabState(tabId, nextState);
    }
    return nextState;
  }

  if (tabTokens.get(tabId) !== scanToken) {
    return tabState.get(tabId);
  }

  if (!response.ok || !payload.result) {
    const scannerError = payload.error || `Scanner API failed with ${response.status}`;
    const nextState = lookup?.status === "complete" && lookup.found
      ? buildLookupRiskState(url, lookup || null, scannerError, {
          pageContext: pagePayload?.pageContext || null
        })
      : buildErrorState(
          url,
          scannerError,
          { lookup: lookup || null }
        );
    await setTabState(tabId, nextState);
    return nextState;
  }

  const bypass = getBypassForTab(tabId, url);
  const rememberedDecision = getUserSiteDecision(url);
  const summary = applyLookupRiskToSummary(summarizeResult(payload.result), lookup || null);
  const nextState = applyRememberedDecision({
    status: "ready",
    url,
    summary,
    rawResult: payload.result,
    timings: payload.timings || {},
    pageContext: pagePayload.pageContext || null,
    lookup: lookup || null,
    detailedCheck: current?.detailedCheck || null,
    decision: bypass
      ? {
          ignored: true,
          ignoredAt: bypass.ignoredAt
        }
      : null,
    updatedAt: Date.now()
  }, rememberedDecision);
  setRecentScanCache(url, {
    summary: nextState.summary,
    rawResult: nextState.rawResult,
    timings: nextState.timings,
    pageContext: nextState.pageContext,
    lookup: nextState.lookup || null
  });
  await setTabState(tabId, nextState);
  return nextState;
}

function scheduleScan(tabId, url, force = false) {
  const existingTimer = tabTimers.get(tabId);
  if (existingTimer) {
    clearTimeout(existingTimer);
  }

  const timerId = setTimeout(() => {
    tabTimers.delete(tabId);
    scanTab(tabId, url, { force });
  }, 450);

  tabTimers.set(tabId, timerId);
}

async function getActiveTab() {
  const [tab] = await api.tabs.query({ active: true, currentWindow: true });
  return tab || null;
}

async function leaveHighRiskPage(tabId) {
  if (!tabId) {
    return { ok: false, error: "No active tab." };
  }
  await api.tabs.update(tabId, { url: "https://www.google.com" });
  return { ok: true, action: "google" };
}

api.runtime.onInstalled.addListener(async (details) => {
  const current = await api.storage.local.get(null);
  const protectionEnabled = typeof current.protectionEnabled === "boolean"
    ? current.protectionEnabled
    : ["always", "session"].includes(current.protectionPermissionPolicy)
      || ["always", "session"].includes(current.detailedScreenshotPermissionPolicy);
  await api.storage.local.set({
    ...DEFAULT_SETTINGS,
    ...current
  });
  const installReason = typeof api.runtime.OnInstalledReason === "object"
    ? api.runtime.OnInstalledReason.INSTALL
    : "install";
  const isFreshInstall = details?.reason === installReason || !current._surfphishInstalled;
  if (isFreshInstall) {
    await api.storage.local.set({
      protectionEnabled: false,
      _surfphishInstalled: true
    });
    return;
  }
  if (protectionEnabled !== current.protectionEnabled) {
    await api.storage.local.set({ protectionEnabled });
  }
});

api.storage.onChanged.addListener((changes, areaName) => {
  if (areaName !== "local") {
    return;
  }
  const nextSettings = { ...settings };
  for (const [key, value] of Object.entries(changes)) {
    nextSettings[key] = value.newValue;
  }
  settings = normalizeUiSettings(nextSettings);
  if (changes.userSiteDecisions) {
    userSiteDecisions = changes.userSiteDecisions.newValue && typeof changes.userSiteDecisions.newValue === "object"
      ? changes.userSiteDecisions.newValue
      : {};
  }
  if (changes.protectionEnabled || changes.autoScan) {
    syncProtectionStateAfterSettingsChange().catch((error) => {
      console.warn("[SurfPhish] Failed to sync protection state after settings change.", error);
    });
  }
});

api.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.url) {
    clearBypassIfUrlChanged(tabId, changeInfo.url);
  }
  if (!settings.autoScan || !isProtectionEnabled() || changeInfo.status !== "complete") {
    return;
  }
  if (!isScannableUrl(tab.url)) {
    return;
  }
  scheduleScan(tabId, tab.url, false);
});

api.tabs.onActivated.addListener(async ({ tabId }) => {
  const tab = await api.tabs.get(tabId);
  if (!settings.autoScan || !isProtectionEnabled() || !isScannableUrl(tab.url)) {
    return;
  }
  const current = tabState.get(tabId);
  if (!current || current.url !== tab.url) {
    scheduleScan(tabId, tab.url, false);
  }
});

api.tabs.onRemoved.addListener((tabId) => {
  tabState.delete(tabId);
  tabTokens.delete(tabId);
  tabBypasses.delete(tabId);
  const timer = tabTimers.get(tabId);
  if (timer) {
    clearTimeout(timer);
    tabTimers.delete(tabId);
  }
});

api.runtime.onMessage.addListener((message, sender) => {
  if (!message || !message.type) {
    return undefined;
  }

  if (message.type === "surfphish:get-scan-state") {
    return Promise.resolve(tabState.get(message.tabId) || null);
  }

  if (message.type === "surfphish:get-current-tab-state") {
    return Promise.resolve({
      state: tabState.get(sender.tab?.id) || null,
      showBanner: settings.showBanner,
      blockHighRiskInterstitial: false,
      uiLanguage: settings.uiLanguage,
      protectionEnabled: isProtectionEnabled()
    });
  }

  if (message.type === "surfphish:rescan-tab") {
    return api.tabs.get(message.tabId).then((tab) => scanTab(message.tabId, tab.url, { force: true }));
  }

  if (message.type === "surfphish:request-detailed-check") {
    const tabId = sender.tab?.id ?? message.tabId;
    if (!tabId) {
      return Promise.resolve({ ok: false, error: "No active tab available." });
    }
    return performDetailedCheck(tabId, Boolean(message.allowNow));
  }

  if (message.type === "surfphish:request-email-check") {
    const tabId = sender.tab?.id ?? message.tabId;
    if (!tabId) {
      return Promise.resolve({ ok: false, error: "No active tab available." });
    }
    return performEmailCheck(tabId, Boolean(message.allowNow));
  }

  if (message.type === "surfphish:set-protection-enabled") {
    return setProtectionEnabled(message.enabled).then((enabled) => ({
      ok: true,
      enabled
    }));
  }

  if (message.type === "surfphish:get-protection-status") {
    return Promise.resolve({
      enabled: isProtectionEnabled()
    });
  }

  if (message.type === "surfphish:ignore-high-risk") {
    const tabId = sender.tab?.id ?? message.tabId;
    const state = tabId ? tabState.get(tabId) : null;
    if (!tabId || !state?.url) {
      return Promise.resolve({ ok: false, error: "No active tab state available." });
    }

    tabBypasses.set(tabId, {
      url: state.url,
      ignoredAt: Date.now()
    });

    const nextState = {
      ...state,
      decision: {
        ignored: true,
        ignoredAt: Date.now()
      },
      updatedAt: Date.now()
    };

    return setTabState(tabId, nextState).then(() => ({
      ok: true,
      state: nextState
    }));
  }

  if (message.type === "surfphish:mark-false-positive") {
    const tabId = sender.tab?.id ?? message.tabId;
    const state = tabId ? tabState.get(tabId) : null;
    if (!tabId || !state?.url) {
      return Promise.resolve({ ok: false, error: "No active tab state available." });
    }

    return recordFeedbackEvent("false_positive", state, {
      source: message.source || "unknown",
      tabId
    }).then(async (event) => {
      try {
        await submitFeedbackToBackend(event);
      } catch (error) {
        console.warn("[SurfPhish] Failed to submit false-positive feedback.", error);
      }
      const storedDecision = await persistUserSiteDecision(state.url, "not_phishing", message.source || "unknown");
      tabBypasses.set(tabId, {
        url: state.url,
        ignoredAt: Date.now()
      });

      const nextState = {
        ...state,
        decision: {
          ...(state.decision || {}),
          ignored: true,
          ignoredAt: Date.now(),
          markedSafe: true
        },
        feedback: {
          ...(state.feedback || {}),
          falsePositiveReportedAt: storedDecision?.reportedAt || event.createdAt,
          falsePositivePersisted: true,
          lastEventId: event.id
        },
        updatedAt: Date.now()
      };

      return setTabState(tabId, nextState).then(() => ({
        ok: true,
        state: nextState,
        event
      }));
    });
  }

  if (message.type === "surfphish:report-site") {
    const tabId = sender.tab?.id ?? message.tabId;
    const state = tabId ? tabState.get(tabId) : null;
    if (!tabId || !state?.url) {
      return Promise.resolve({ ok: false, error: "No active tab state available." });
    }

    return recordFeedbackEvent("report_site", state, {
      source: message.source || "unknown",
      tabId
    }).then(async (event) => {
      try {
        await submitFeedbackToBackend(event);
      } catch (error) {
        console.warn("[SurfPhish] Failed to submit site report.", error);
      }
      const storedDecision = await persistUserSiteDecision(state.url, "phishing", message.source || "unknown");
      const nextState = {
        ...state,
        feedback: {
          ...(state.feedback || {}),
          siteReportedAt: storedDecision?.reportedAt || event.createdAt,
          siteReportedPersisted: true,
          lastEventId: event.id
        },
        updatedAt: Date.now()
      };

      return setTabState(tabId, nextState).then(() => ({
        ok: true,
        state: nextState,
        event
      }));
    });
  }

  if (message.type === "surfphish:add-url-to-whitelist") {
    const tabId = sender.tab?.id ?? message.tabId;
    const state = tabId ? tabState.get(tabId) : null;
    const normalized = normalizeWhitelistEntryFromUrl(state?.url);
    if (!tabId || !normalized) {
      return Promise.resolve({ ok: false, error: "No active tab state available." });
    }

    const whitelistRules = normalizeWhitelistRules([...settings.whitelistRules, normalized]);
    settings.whitelistRules = whitelistRules;
    tabBypasses.delete(tabId);

    const nextState = buildWhitelistedState(state.url);
    return api.storage.local.set({ whitelistRules }).then(() => setTabState(tabId, nextState)).then(() => ({
      ok: true,
      state: nextState,
      whitelistRules
    }));
  }

  if (message.type === "surfphish:clear-user-site-decision") {
    const tabId = sender.tab?.id ?? message.tabId;
    const state = tabId ? tabState.get(tabId) : null;
    const url = state?.url || message.url || "";
    if (!tabId || !url) {
      return Promise.resolve({ ok: false, error: "No active tab state available." });
    }

    return removeUserSiteDecision(url).then(async () => {
      tabBypasses.delete(tabId);
      const refreshedState = await scanTab(tabId, url, { force: true });
      return {
        ok: true,
        state: refreshedState
      };
    });
  }

  if (message.type === "surfphish:leave-high-risk-page") {
    const tabId = sender.tab?.id;
    return leaveHighRiskPage(tabId);
  }

  if (message.type === "surfphish:get-settings") {
    return Promise.resolve({
      ...settings,
      whitelistRules: settings.whitelistRules,
      effectiveWhitelistRules: getEffectiveWhitelistRules()
    });
  }

  if (message.type === "surfphish:ping-api") {
    return fetch(`${settings.apiBaseUrl}/health`)
      .then((response) => response.json().then((payload) => ({ ok: response.ok, payload })))
      .catch((error) => ({ ok: false, error: error.message }));
  }

  return undefined;
});

loadSettings().then(async () => {
  const activeTab = await getActiveTab();
  if (activeTab?.id && settings.autoScan && isProtectionEnabled() && isScannableUrl(activeTab.url)) {
    scheduleScan(activeTab.id, activeTab.url, false);
  }
});
