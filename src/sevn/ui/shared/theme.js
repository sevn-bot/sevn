/**
 * Shared sevn.bot tri-state theme (system / light / dark).
 * Persisted in localStorage; sets data-theme-pref and data-theme on documentElement.
 */
(function (global) {
  const THEME_CYCLE = ["system", "light", "dark"];
  const DEFAULT_STORAGE_KEY = "sevn-theme";

  function applyTheme(pref, storageKey) {
    const root = document.documentElement;
    root.setAttribute("data-theme-pref", pref);
    let resolved = pref;
    if (pref === "system") {
      resolved = window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
    }
    root.setAttribute("data-theme", resolved);
    const label = document.querySelector("[data-sevn-theme-label]");
    if (label) label.textContent = pref;
    try {
      localStorage.setItem(storageKey, pref);
    } catch (_e) {
      /* ignore */
    }
  }

  /**
   * @param {{ storageKey?: string, cycleButtonSelector?: string, labelSelector?: string }} [opts]
   */
  function initSevnTheme(opts) {
    const storageKey = (opts && opts.storageKey) || DEFAULT_STORAGE_KEY;
    const buttonSel = (opts && opts.cycleButtonSelector) || "[data-sevn-theme-toggle]";
    let pref = "system";
    try {
      const saved = localStorage.getItem(storageKey);
      if (saved && THEME_CYCLE.includes(saved)) pref = saved;
    } catch (_e) {
      /* ignore */
    }
    applyTheme(pref, storageKey);
    window.matchMedia("(prefers-color-scheme: light)").addEventListener("change", () => {
      if (document.documentElement.getAttribute("data-theme-pref") === "system") {
        applyTheme("system", storageKey);
      }
    });
    document.querySelectorAll(buttonSel).forEach((btn) => {
      btn.addEventListener("click", () => {
        const cur = document.documentElement.getAttribute("data-theme-pref") || "system";
        const idx = THEME_CYCLE.indexOf(cur);
        applyTheme(THEME_CYCLE[(idx + 1) % THEME_CYCLE.length], storageKey);
      });
    });
  }

  global.initSevnTheme = initSevnTheme;
  global.applySevnTheme = applyTheme;
})(typeof window !== "undefined" ? window : globalThis);
