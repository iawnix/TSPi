"use strict";

// The browser renders the canonical ResearchMap document directly. Keep this
// dictionary limited to labels used by the current shell so old state names do
// not quietly reappear in the UI.
(function attachExplorerI18n(global) {
  const storageKey = "ts-explorer-locale";
  const dictionaries = {
    en: {
      "brand.title": "TS Research Explorer",
      "brand.protocol": "Research Kernel",
      "controls.workspace": "Workspace",
      "controls.language": "Switch to Chinese",
      "controls.theme.dark": "Use dark theme",
      "controls.refresh": "Refresh workspace",
      "auth.title": "Access token required",
      "auth.description": "Enter the token configured for this TS Web server.",
      "auth.tokenLabel": "Access token",
      "auth.reveal": "Show token",
      "auth.memoryOnly": "The token is kept in memory and cleared when this page closes.",
      "auth.insecure": "This connection is not encrypted. Use HTTPS before entering a token on an untrusted network.",
      "auth.invalid": "The token was rejected. Check it and try again.",
      "auth.connect": "Connect",
      "nav.research": "Research",
      "nav.roadmap": "Research Map",
      "nav.conclusions": "Claims",
      "nav.files": "Research Files",
      "nav.assurance": "Assurance",
      "nav.validation": "Gates",
      "nav.findings": "Findings",
      "nav.operations": "Operations",
      "nav.activity": "ResearchNodes",
      "nav.workspaceAria": "Research workspace",
      "detail.close": "Close details",
      "detail.details": "Details",
      "detail.record": "Record",
    },
    zh: {
      "brand.title": "TS 研究浏览器",
      "brand.protocol": "研究内核",
      "controls.workspace": "工作区",
      "controls.language": "切换到英文",
      "controls.theme.dark": "切换到深色主题",
      "controls.refresh": "刷新工作区",
      "auth.title": "需要访问令牌",
      "auth.description": "请输入为此 TS Web 服务配置的令牌。",
      "auth.tokenLabel": "访问令牌",
      "auth.reveal": "显示令牌",
      "auth.memoryOnly": "令牌仅保存在页面内存中，关闭页面后即清除。",
      "auth.insecure": "当前连接未加密。在不可信网络中输入令牌前，请先启用 HTTPS。",
      "auth.invalid": "令牌被拒绝，请检查后重试。",
      "auth.connect": "连接",
      "nav.research": "研究",
      "nav.roadmap": "研究地图",
      "nav.conclusions": "Claim",
      "nav.files": "研究文件",
      "nav.assurance": "评估",
      "nav.validation": "Gate",
      "nav.findings": "Finding",
      "nav.operations": "运行",
      "nav.activity": "ResearchNode",
      "nav.workspaceAria": "研究工作区",
      "detail.close": "关闭详情",
      "detail.details": "详情",
      "detail.record": "记录",
    },
  };

  let locale = "en";
  try {
    const saved = localStorage.getItem(storageKey);
    if (saved === "zh" || saved === "en") locale = saved;
  } catch (_error) {}

  function t(key, fallback = key, variables = null) {
    const text = dictionaries[locale][key] || dictionaries.en[key] || fallback;
    if (!variables || typeof text !== "string") return text;
    return text.replace(/\{\{(\w+)\}\}/g, (_match, name) => String(variables[name] ?? ""));
  }

  function status(value) {
    return String(value || "unknown").replaceAll("_", " ");
  }

  function apply(root = document) {
    root.querySelectorAll("[data-i18n]").forEach(node => {
      node.textContent = t(node.dataset.i18n, node.textContent);
    });
    root.querySelectorAll("[data-i18n-aria-label]").forEach(node => {
      node.setAttribute("aria-label", t(node.dataset.i18nAriaLabel, node.getAttribute("aria-label") || ""));
    });
    root.querySelectorAll("[data-i18n-title]").forEach(node => {
      node.setAttribute("title", t(node.dataset.i18nTitle, node.getAttribute("title") || ""));
    });
  }

  function setLocale(next) {
    locale = next === "zh" ? "zh" : "en";
    document.documentElement.lang = locale;
    document.title = t("brand.title", "TS Research Explorer");
    try { localStorage.setItem(storageKey, locale); } catch (_error) {}
    apply();
  }

  global.TSExplorerI18n = Object.freeze({
    t,
    status,
    apply,
    setLocale,
    getLocale: () => locale,
    storageKey,
  });
})(window);
