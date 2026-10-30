/* Runs before the page paints, so the saved theme never flashes. Dark is the default.
   It also paints the page color on <html> at once, so there is no white screen while app.css is still loading;
   app.js removes these two inline values once the stylesheet is in charge (so the theme switch can change them). */
try {
  var light = localStorage.getItem("sr-theme") === "light";
  if (light) document.documentElement.setAttribute("data-theme", "light");
  document.documentElement.style.backgroundColor = light ? "#f8f8f8" : "#0f0f0f";
  document.documentElement.style.colorScheme = light ? "light" : "dark";
} catch (e) {}
