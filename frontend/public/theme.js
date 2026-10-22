// Runs before the first paint: applies the saved or system theme, and starts every load at the top. A classic script,
// because the page's security policy forbids inline scripts and a module would run too late.
(function () {
  // The browser would restore the old scroll position on a reload, but the page grows as the map and the site index
  // load, so it landed somewhere a little different each time.
  if ("scrollRestoration" in window.history) window.history.scrollRestoration = "manual";
  function savedTheme() {
    try {
      return window.localStorage.getItem("walk-in-theme");
    } catch {
      return null;
    }
  }
  var saved = savedTheme();
  var prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  var theme = saved === "light" || saved === "dark" ? saved : prefersDark ? "dark" : "light";
  document.documentElement.dataset.theme = theme;
  var meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", theme === "dark" ? "#0d111c" : "#f5f4ef");
})();
