// Applies the saved theme before the app loads, so the page never flashes the wrong colors.
(function () {
  try {
    var saved = localStorage.getItem("tg-theme") || "system";
    var dark = saved === "dark" || (saved === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.classList.toggle("dark", dark);
  } catch (e) {}
})();
