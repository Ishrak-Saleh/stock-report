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
    var eye = t.closest("[data-toggle-password]");
    if (eye) {   // show or hide what is typed in the password field next to the button
      var field = eye.parentElement.querySelector("input"), shown = field.type === "password";
      field.type = shown ? "text" : "password";
      eye.setAttribute("aria-pressed", shown ? "true" : "false");
      eye.setAttribute("aria-label", shown ? "Hide password" : "Show password");
      eye.title = shown ? "Hide password" : "Show password";
      return;
    }
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
        navigator.clipboard.writeText(src.textContent).then(function () { say(copy.dataset.done || "Copied. Paste it into your email."); }, function () { say("Select the text and press Ctrl+C."); });
      } else { say("Select the text and press Ctrl+C."); }
      return;
    }

    if (t.closest("#theme-toggle")) {
      var light = document.documentElement.getAttribute("data-theme") === "light";
      var swap = function () {
        if (light) document.documentElement.removeAttribute("data-theme"); else document.documentElement.setAttribute("data-theme", "light");
      };
      // One short cross-fade where the browser can do it; an instant switch elsewhere or when motion is reduced.
      if (document.startViewTransition && !matchMedia("(prefers-reduced-motion: reduce)").matches) document.startViewTransition(swap); else swap();
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


  /* ---- chart hover: a crosshair and a tooltip, from the data the server put on the chart ---- */
  function fmtNum(n) { return Number(n).toLocaleString("en-US"); }
  document.addEventListener("pointermove", function (e) {
    var hit = e.target.closest && e.target.closest(".chit");
    if (!hit) return;
    var wrap = hit.closest("[data-chart]"), svg = hit.ownerSVGElement;
    var data = wrap._d || (wrap._d = JSON.parse(wrap.dataset.chart));
    var r = svg.getBoundingClientRect(), W = +svg.dataset.w, L = +svg.dataset.l, PW = +svg.dataset.pw;
    var span = (data.x1 - data.x0) || 1;
    var d = Math.max(data.x0, Math.min(data.x1, Math.round(data.x0 + (((e.clientX - r.left) * (W / r.width) - L) / PW) * span)));
    var X = L + ((d - data.x0) / span) * PW, xh = svg.querySelector(".xhair");
    xh.setAttribute("x1", X); xh.setAttribute("x2", X); xh.setAttribute("visibility", "visible");
    var when = new Date(data.today + "T12:00:00"); when.setDate(when.getDate() + d);
    var name = when.toLocaleDateString("en-US", { month: "short", day: "numeric" });
    var title = d === 0 ? "Today, " + name : (d > 0 ? "Day " + d : (-d) + " days ago") + ", " + name;
    var tip = wrap.querySelector(".tip"), rows = data.series.map(function (s) {
      return '<div class="tr"><span><i class="sw ' + s.cls + '"></i>' + s.name + '</span><b>' + fmtNum(s.v[d - data.x0]) + '</b></div>';
    }).join("");
    tip.hidden = false; tip.innerHTML = "<b>" + title + "</b>" + rows;
    var left = (X / W) * r.width + 12;
    if (left + tip.offsetWidth > r.width) left = (X / W) * r.width - tip.offsetWidth - 12;
    tip.style.left = Math.max(0, left) + "px";
  });
  document.addEventListener("pointerleave", function (e) {
    if (!(e.target.classList && e.target.classList.contains("chit"))) return;
    var wrap = e.target.closest("[data-chart]");
    wrap.querySelector(".xhair").setAttribute("visibility", "hidden"); wrap.querySelector(".tip").hidden = true;
  }, true);

  /* ---- match editor: every unit must be assigned before Save turns on ---- */
  function splitUpdate(form) {
    var total = +form.dataset.total, sum = 0;
    form.querySelectorAll("input[name^='u_']").forEach(function (i) { sum += Math.max(0, parseInt(i.value, 10) || 0); });
    var ok = sum === total, good = form.querySelector("[data-ok]"), bad = form.querySelector("[data-bad]");
    good.hidden = !ok; bad.hidden = ok;
    (ok ? good : bad).querySelector("[data-txt]").textContent = sum + " of " + total + " units assigned" +
      (ok ? "" : ". " + (sum > total ? "Remove " + (sum - total) : "Assign " + (total - sum) + " more") + ".");
    form.querySelector("[data-save]").disabled = !ok;
  }
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-step]");
    if (!b) return;
    var form = b.closest("[data-split]"), input = b.parentElement.querySelector("input");
    input.value = Math.max(0, (parseInt(input.value, 10) || 0) + (+b.dataset.step));
    if (form) splitUpdate(form);
  });

  /* ---- adjustment dialog: say what the new stock and days left will be before saving ---- */
  function adjustUpdate(form) {
    var stock = +form.dataset.stock, burn = +form.dataset.burn, units = Math.max(0, parseInt(form.units.value, 10) || 0);
    var kind = form.querySelector("input[name=kind]:checked"), sign = +kind.dataset.sign, pick = form.querySelector("select[name=variant]");
    if (pick && kind.value === "sale") units *= +pick.selectedOptions[0].dataset.per;  // a bundle sale means more units
    var next = Math.max(0, stock + sign * units);
    form.querySelector("[data-dir]").textContent = (sign > 0 ? "Adds " : "Removes ") + units + " unit" + (units === 1 ? "" : "s");
    var days = burn > 0 ? " That is " + (next / burn).toFixed(1) + " days at " + burn + " a day." : "";
    form.querySelector("[data-preview] span").textContent = "Stock goes from " + fmtNum(stock) + " to " + fmtNum(next) + "." + days;
  }

  /* ---- settings: show the reorder line while the numbers are typed ---- */
  function forecastUpdate(form) {
    var n = function (name) { return parseInt(form[name].value, 10) || 0; }, panel = form.closest(".panel");
    panel.querySelector("[data-line]").textContent = (n("lead_time") + n("safety_days")) + " days";
    panel.querySelector("[data-cover]").textContent = (n("target_days") + n("lead_time")) + " days of sales";
  }

  document.addEventListener("input", function (e) {
    var f = e.target.closest("form");
    if (!f) return;
    if (f.matches("[data-split]")) splitUpdate(f);
    else if (f.matches("[data-adjust]")) adjustUpdate(f);
    else if (f.matches("[data-forecast]")) forecastUpdate(f);
  });
  document.addEventListener("change", function (e) {
    var f = e.target.closest("form");
    if (f && f.matches("[data-adjust]")) adjustUpdate(f);
  });
  function initDialog(root) {
    root.querySelectorAll("[data-split]").forEach(splitUpdate);
    root.querySelectorAll("[data-adjust]").forEach(adjustUpdate);
  }
  document.body.addEventListener("htmx:afterSwap", function (e) { if (e.target === host) initDialog(host); });

  /* Sign up: the confirm box complains until it matches the password. */
  document.addEventListener("input", function (e) {
    var f = e.target.form, c = f && f.elements.confirm, p = f && f.elements.password;
    if (!c || !p || (e.target !== c && e.target !== p)) return;
    c.setCustomValidity(c.value && c.value !== p.value ? "The two passwords do not match." : "");
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
