/* Runs before the page paints, so the saved theme never flashes. Dark is the default. */
try {
  var t = localStorage.getItem("sr-theme");
  if (t === "light") document.documentElement.setAttribute("data-theme", "light");
} catch (e) {}
