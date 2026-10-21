// Applies the saved or system theme before the first paint. A classic script, because the page's security
// policy forbids inline scripts and a module would run too late.
(function () {
  function savedTheme() {
    try {
      return window.localStorage.getItem("blank-space-theme");
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
