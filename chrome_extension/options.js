const api = globalThis.browser ?? globalThis.chrome;
const { DEFAULT_UI_LANGUAGE, normalizeUiLanguage, t } = globalThis.SurfPhishI18n;

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
  whitelistRules: ["7uc9we0gs0w6arve4ara.duckdns.org"]
};

const feedback = document.getElementById("feedback");
const whitelistList = document.getElementById("whitelistList");
let currentLanguage = DEFAULT_UI_LANGUAGE;
let customWhitelistRules = [];
let saveTimer = null;

function applyStaticText() {
  document.documentElement.lang = currentLanguage === "en" ? "en" : "zh-Hant";
  document.title = t(currentLanguage, "optionsTitle");
  document.getElementById("optionsEyebrow").textContent = t(currentLanguage, "optionsEyebrow");
  document.getElementById("optionsHeading").textContent = t(currentLanguage, "brandName");
  document.getElementById("optionsLede").textContent = t(currentLanguage, "optionsLede");
  document.getElementById("apiBaseUrlLabel").textContent = t(currentLanguage, "optionsApiBaseUrl");
  document.getElementById("apiBaseUrlHelp").textContent = t(currentLanguage, "optionsApiBaseUrlHelp");
  document.getElementById("scanTimeoutLabel").textContent = t(currentLanguage, "optionsScanTimeout");
  document.getElementById("scanTimeoutHelp").textContent = t(currentLanguage, "optionsScanTimeoutHelp");
  document.getElementById("uiLanguageLabel").textContent = t(currentLanguage, "optionsUiLanguage");
  document.getElementById("uiLanguageHelp").textContent = t(currentLanguage, "optionsUiLanguageHelp");
  document.getElementById("autoScanLabel").textContent = t(currentLanguage, "optionsAutoScan");
  document.getElementById("autoScanHelp").textContent = t(currentLanguage, "optionsAutoScanHelp");
  document.getElementById("showBannerLabel").textContent = t(currentLanguage, "optionsShowBanner");
  document.getElementById("showBannerHelp").textContent = t(currentLanguage, "optionsShowBannerHelp");
  document.getElementById("blockHighRiskLabel").textContent = t(currentLanguage, "optionsBlockHighRisk");
  document.getElementById("blockHighRiskHelp").textContent = t(currentLanguage, "optionsBlockHighRiskHelp");
  document.getElementById("insecureFetchLabel").textContent = t(currentLanguage, "optionsInsecureFetch");
  document.getElementById("insecureFetchHelp").textContent = t(currentLanguage, "optionsInsecureFetchHelp");
  document.getElementById("badgeOnLowRiskLabel").textContent = t(currentLanguage, "optionsBadgeLow");
  document.getElementById("badgeOnLowRiskHelp").textContent = t(currentLanguage, "optionsBadgeLowHelp");
  document.getElementById("testButton").textContent = t(currentLanguage, "optionsPingApi");
  document.getElementById("whitelistEyebrow").textContent = t(currentLanguage, "optionsWhitelistTitle");
  document.getElementById("whitelistHeading").textContent = t(currentLanguage, "optionsWhitelistTitle");
  document.getElementById("whitelistLede").textContent = t(currentLanguage, "optionsWhitelistLede");
  document.getElementById("clearWhitelistButton").textContent = t(currentLanguage, "optionsWhitelistClear");

  const languageSelect = document.getElementById("uiLanguage");
  languageSelect.options[0].textContent = t(currentLanguage, "languageOptionZhTW");
  languageSelect.options[1].textContent = t(currentLanguage, "languageOptionEn");
}

function createWhitelistRow(rule) {
  const row = document.createElement("div");
  row.className = "whitelist-row";

  const left = document.createElement("div");
  left.className = "whitelist-main";

  const code = document.createElement("code");
  code.className = "whitelist-url";
  code.textContent = rule;

  left.appendChild(code);

  row.appendChild(left);

  const button = document.createElement("button");
  button.className = "ghost";
  button.type = "button";
  button.textContent = t(currentLanguage, "optionsWhitelistRemove");
  button.addEventListener("click", async () => {
    customWhitelistRules = customWhitelistRules.filter((entry) => entry !== rule);
    await api.storage.local.set({ whitelistRules: customWhitelistRules });
    feedback.textContent = t(currentLanguage, "optionsChangesApplied");
    renderWhitelist();
  });
  row.appendChild(button);

  return row;
}

function renderWhitelist() {
  whitelistList.innerHTML = "";

  if (!customWhitelistRules.length) {
    const empty = document.createElement("p");
    empty.className = "whitelist-empty";
    empty.textContent = t(currentLanguage, "optionsWhitelistEmpty");
    whitelistList.appendChild(empty);
    return;
  }

  for (const rule of customWhitelistRules) {
    whitelistList.appendChild(createWhitelistRow(rule));
  }
}

function collectSettingsFromForm() {
  return {
    apiBaseUrl: document.getElementById("apiBaseUrl").value.trim() || DEFAULT_SETTINGS.apiBaseUrl,
    scanTimeout: Number(document.getElementById("scanTimeout").value || DEFAULT_SETTINGS.scanTimeout),
    uiLanguage: normalizeUiLanguage(document.getElementById("uiLanguage").value),
    autoScan: document.getElementById("autoScan").checked,
    showBanner: document.getElementById("showBanner").checked,
    blockHighRiskInterstitial: document.getElementById("blockHighRiskInterstitial").checked,
    insecureFetch: document.getElementById("insecureFetch").checked,
    badgeOnLowRisk: document.getElementById("badgeOnLowRisk").checked
  };
}

async function persistSettings(immediate = false) {
  if (!immediate) {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => persistSettings(true), 250);
    return;
  }

  const nextSettings = collectSettingsFromForm();
  currentLanguage = nextSettings.uiLanguage;
  await api.storage.local.set(nextSettings);
  applyStaticText();
  renderWhitelist();
  feedback.textContent = t(currentLanguage, "optionsChangesApplied");
}

async function loadSettings() {
  const settings = await api.runtime.sendMessage({ type: "surfphish:get-settings" });
  const merged = {
    ...DEFAULT_SETTINGS,
    ...settings
  };

  currentLanguage = normalizeUiLanguage(merged.uiLanguage);
  customWhitelistRules = Array.isArray(merged.whitelistRules) ? merged.whitelistRules.slice() : [];

  document.getElementById("apiBaseUrl").value = merged.apiBaseUrl;
  document.getElementById("scanTimeout").value = merged.scanTimeout;
  document.getElementById("uiLanguage").value = currentLanguage;
  document.getElementById("autoScan").checked = merged.autoScan;
  document.getElementById("showBanner").checked = merged.showBanner;
  document.getElementById("blockHighRiskInterstitial").checked = merged.blockHighRiskInterstitial;
  document.getElementById("insecureFetch").checked = merged.insecureFetch;
  document.getElementById("badgeOnLowRisk").checked = merged.badgeOnLowRisk;

  applyStaticText();
  renderWhitelist();
  feedback.textContent = t(currentLanguage, "optionsInstantApply");
}

async function pingApi() {
  const apiBaseUrl = document.getElementById("apiBaseUrl").value.trim() || DEFAULT_SETTINGS.apiBaseUrl;
  await api.storage.local.set({ apiBaseUrl });
  feedback.textContent = t(currentLanguage, "optionsPingingApi");
  try {
    const response = await fetch(`${apiBaseUrl.replace(/\/+$/, "")}/health`);
    const payload = await response.json();
    feedback.textContent = response.ok
      ? t(currentLanguage, "optionsApiHealthy", {
          model: payload.model || "unknown",
          device: payload.device || "unknown"
        })
      : t(currentLanguage, "optionsApiResponded", { status: response.status });
  } catch (error) {
    feedback.textContent = t(currentLanguage, "optionsApiUnreachable", { error: error.message });
  }
}

for (const id of [
  "apiBaseUrl",
  "scanTimeout",
  "uiLanguage",
  "autoScan",
  "showBanner",
  "blockHighRiskInterstitial",
  "insecureFetch",
  "badgeOnLowRisk"
]) {
  const element = document.getElementById(id);
  const eventName = ["apiBaseUrl", "scanTimeout"].includes(id) ? "input" : "change";
  element.addEventListener(eventName, () => {
    if (id === "uiLanguage") {
      currentLanguage = normalizeUiLanguage(element.value);
      applyStaticText();
      renderWhitelist();
    }
    persistSettings();
  });
}

document.getElementById("testButton").addEventListener("click", pingApi);
document.getElementById("clearWhitelistButton").addEventListener("click", async () => {
  customWhitelistRules = [];
  await api.storage.local.set({ whitelistRules: [] });
  renderWhitelist();
  feedback.textContent = t(currentLanguage, "optionsWhitelistCleared");
});

api.storage.onChanged.addListener((changes, areaName) => {
  if (areaName !== "local") {
    return;
  }
  if (changes.uiLanguage) {
    currentLanguage = normalizeUiLanguage(changes.uiLanguage.newValue);
    document.getElementById("uiLanguage").value = currentLanguage;
    applyStaticText();
  }
  if (changes.whitelistRules) {
    customWhitelistRules = Array.isArray(changes.whitelistRules.newValue) ? changes.whitelistRules.newValue.slice() : [];
    renderWhitelist();
  }
});

loadSettings();
