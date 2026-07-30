(() => {
  const STORAGE_KEY = "pv-theme";

  function currentTheme() {
    return document.documentElement.getAttribute("data-theme") === "dark"
      ? "dark"
      : "light";
  }

  function applyTheme(theme) {
    const next = theme === "dark" ? "dark" : "light";
    document.documentElement.setAttribute("data-theme", next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch (_) {
      /* ignore quota / private mode */
    }

    document.querySelectorAll("#theme-toggle, .theme-toggle").forEach((button) => {
      button.setAttribute(
        "aria-label",
        next === "dark" ? "Switch to light mode" : "Switch to dark mode"
      );
    });

    window.dispatchEvent(
      new CustomEvent("pv-theme-change", { detail: { theme: next } })
    );
  }

  function initTheme() {
    const buttons = document.querySelectorAll("#theme-toggle, .theme-toggle");
    if (!buttons.length) return;

    applyTheme(currentTheme());

    buttons.forEach((button) => {
      button.addEventListener("click", () => {
        applyTheme(currentTheme() === "dark" ? "light" : "dark");
      });
    });
  }

  window.PVTheme = { applyTheme, currentTheme, STORAGE_KEY };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initTheme);
  } else {
    initTheme();
  }
})();
