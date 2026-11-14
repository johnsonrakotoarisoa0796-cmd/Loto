(() => {
  "use strict";
  const KEY = "loto-lab-theme";
  const root = document.documentElement;
  const media = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  const allowed = new Set(["auto", "light", "dark"]);

  function readPreference() {
    try {
      const value = localStorage.getItem(KEY) || root.dataset.themePreference || "auto";
      return allowed.has(value) ? value : "auto";
    } catch (_) {
      return "auto";
    }
  }

  function apply(preference, persist = false) {
    const value = allowed.has(preference) ? preference : "auto";
    const theme = value === "auto" ? (media && media.matches ? "dark" : "light") : value;
    root.dataset.themePreference = value;
    root.dataset.theme = theme;
    document.querySelectorAll("#theme-select").forEach((select) => {
      if (select.value !== value) select.value = value;
    });
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", theme === "dark" ? "#0b1220" : "#101827");
    if (persist) {
      try { localStorage.setItem(KEY, value); } catch (_) { /* Private browsing may disable storage. */ }
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    apply(readPreference());
    document.querySelectorAll("#theme-select").forEach((select) => {
      select.addEventListener("change", () => apply(select.value, true));
    });
  });

  if (media) {
    const onSystemChange = () => {
      if (readPreference() === "auto") apply("auto");
    };
    if (media.addEventListener) media.addEventListener("change", onSystemChange);
    else if (media.addListener) media.addListener(onSystemChange);
  }
})();
