/** Shared frontend utilities: theme toggle, language preference, toast notifications, CSRF fetch */

window.CitizenApp = (() => {
  const THEME_KEY = "citizen_theme";
  const LANG_KEY = "citizen_lang";

  function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute("content") : "";
  }

  function showToast(message, type = "info") {
    const container = document.getElementById("toast-container");
    if (!container) return;
    const colors = {
      success: "bg-emerald-600 text-white border-emerald-700",
      error: "bg-rose-600 text-white border-rose-700",
      warning: "bg-amber-600 text-white border-amber-700",
      info: "bg-slate-800 text-white border-slate-700",
    };
    const toast = document.createElement("div");
    toast.setAttribute("role", "status");
    toast.className = `px-4 py-3 rounded-lg shadow-lg border text-sm font-medium flex items-center gap-2 transition-all duration-300 ${colors[type] || colors.info}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = "0";
      setTimeout(() => toast.remove(), 300);
    }, 3600);
  }

  async function apiFetch(url, options = {}) {
    const headers = new Headers(options.headers || {});
    const csrfToken = getCsrfToken();
    if (csrfToken) {
      headers.set("X-CSRFToken", csrfToken);
    }
    if (!(options.body instanceof FormData) && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    const resp = await fetch(url, { ...options, headers });
    return resp;
  }

  function initTheme() {
    const saved = localStorage.getItem(THEME_KEY);
    const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    const isDark = saved ? saved === "dark" : prefersDark;
    document.documentElement.classList.toggle("dark", isDark);
    updateThemeIcon(isDark);
  }

  function updateThemeIcon(isDark) {
    const sun = document.getElementById("icon-sun");
    const moon = document.getElementById("icon-moon");
    if (sun && moon) {
      sun.classList.toggle("hidden", !isDark);
      moon.classList.toggle("hidden", isDark);
    }
  }

  function toggleTheme() {
    const isDark = !document.documentElement.classList.contains("dark");
    document.documentElement.classList.toggle("dark", isDark);
    localStorage.setItem(THEME_KEY, isDark ? "dark" : "light");
    updateThemeIcon(isDark);
  }

  function getLanguage() {
    return localStorage.getItem(LANG_KEY) || "auto";
  }

  function setLanguage(lang) {
    localStorage.setItem(LANG_KEY, lang);
    const sel = document.getElementById("global-lang-select");
    if (sel) sel.value = lang;
    window.dispatchEvent(new CustomEvent("citizen-lang-changed", { detail: { lang } }));
  }

  function escapeHtml(str) {
    return String(str || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  document.addEventListener("DOMContentLoaded", () => {
    initTheme();
    const themeBtn = document.getElementById("theme-toggle-btn");
    if (themeBtn) themeBtn.addEventListener("click", toggleTheme);

    const langSelect = document.getElementById("global-lang-select");
    if (langSelect) {
      langSelect.value = getLanguage();
      langSelect.addEventListener("change", (e) => setLanguage(e.target.value));
    }

    const mobileBtn = document.getElementById("mobile-menu-btn");
    const mobileMenu = document.getElementById("mobile-menu");
    if (mobileBtn && mobileMenu) {
      mobileBtn.addEventListener("click", () => {
        const expanded = mobileMenu.classList.toggle("hidden") === false;
        mobileBtn.setAttribute("aria-expanded", String(expanded));
      });
    }
  });

  return {
    getCsrfToken,
    showToast,
    apiFetch,
    getLanguage,
    setLanguage,
    escapeHtml,
  };
})();
