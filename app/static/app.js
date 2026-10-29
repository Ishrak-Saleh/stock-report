/* Small behaviors the pages need. Server pages do the work; this only opens dialogs, menus and copies text. */
(function () {
  var host = document.getElementById("modal-host");

  function openDialog() {
    var d = host && host.querySelector("dialog");
    if (d && !d.open) d.showModal();
  }
  document.body.addEventListener("htmx:afterSwap", function (e) { if (e.target === host) openDialog(); });

  function closePops() {
    document.querySelectorAll(".pop").forEach(function (p) { p.hidden = true; });
    document.querySelectorAll("[data-pop]").forEach(function (b) { b.setAttribute("aria-expanded", "false"); });
  }

  document.addEventListener("click", function (e) {
    var t = e.target;
    var dlg = t.closest("dialog.modal");
    if (t.tagName === "DIALOG" && t.classList.contains("modal")) { t.close(); return; }      // click on the backdrop
    var close = t.closest("[data-close]");
    if (close && dlg) { dlg.close(); return; }

    var pop = t.closest("[data-pop]");
    if (pop) {
      var menu = pop.parentElement.querySelector(".pop"), was = !menu.hidden;
      closePops();
      if (!was) { menu.hidden = false; pop.setAttribute("aria-expanded", "true"); }
      return;
    }
    if (!t.closest(".pop")) closePops();

    var copy = t.closest("[data-copy]");
    if (copy) {
      var src = document.getElementById(copy.dataset.copy), state = document.getElementById("copy-state");
      var say = function (m) { if (state) state.textContent = m; };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(src.textContent).then(function () { say("Copied. Paste it into your email."); }, function () { say("Select the text and press Ctrl+C."); });
      } else { say("Select the text and press Ctrl+C."); }
      return;
    }

    if (t.closest("#theme-toggle")) {
      var light = document.documentElement.getAttribute("data-theme") === "light";
      if (light) document.documentElement.removeAttribute("data-theme"); else document.documentElement.setAttribute("data-theme", "light");
      try { localStorage.setItem("sr-theme", light ? "dark" : "light"); } catch (err) {}
      return;
    }

    var row = t.closest("[data-href]");
    if (row && !t.closest("a, button, input, select, label")) { window.location = row.dataset.href; }
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closePops();
    if ((e.key === "Enter" || e.key === " ") && e.target.dataset && e.target.dataset.href) { e.preventDefault(); window.location = e.target.dataset.href; }
  });

  /* Picking an order size fills the units box, then the box asks the server for the days of stock. */
  document.addEventListener("change", function (e) {
    var r = e.target;
    if (r.name === "plan") {
      var u = document.getElementById("n-units");
      if (u) { u.value = r.value; u.dispatchEvent(new Event("input", { bubbles: true })); }
    }
  });
})();
