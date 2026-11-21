/* RFI Trail context help (0.8.0).
   Point at anything and press ?  (or F1), or press the "? Help" button and then click anything.
   The explanations come from window.NT_HELP: a list of [css selector, title, html text].
   The nearest matching item under the pointer wins; if there is none, the item's own tooltip text is shown. */
(function () {
  if (window.__ntHelpLoaded) return;
  window.__ntHelpLoaded = true;
  var lastX = 200, lastY = 200, pop = null, tgt = null, mode = false, btn = null;

  var css = document.createElement("style");
  css.textContent =
    "#ntHelpBtn{position:fixed;right:14px;bottom:14px;z-index:2147483000;background:#14233a;color:#fff;border:2px solid #fff;border-radius:22px;padding:8px 16px;font:800 16px/1.2 -apple-system,Helvetica,Arial,sans-serif;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.45)}" +
    "#ntHelpBtn.on{background:#1b5fd6}" +
    "#ntHelpPop{position:fixed;z-index:2147483001;width:min(480px,92vw);max-height:80vh;overflow:auto;background:#fff;color:#0b1a30;border:3px solid #1b5fd6;border-radius:12px;box-shadow:0 6px 24px rgba(0,0,0,.5);padding:12px 16px 12px;font:600 16px/1.45 -apple-system,Helvetica,Arial,sans-serif}" +
    "#ntHelpPop h3{margin:0 0 6px;font:850 19px/1.25 -apple-system,Helvetica,Arial,sans-serif;padding-right:28px;color:#0b1a30}" +
    "#ntHelpPop p{margin:6px 0}" +
    "#ntHelpPop ul{margin:6px 0 6px 20px;padding:0}" +
    "#ntHelpPop b{font-weight:850}" +
    "#ntHelpPop .x{position:absolute;top:6px;right:8px;border:0;background:#e8eef7;border-radius:14px;width:28px;height:28px;font:800 16px/28px sans-serif;cursor:pointer;color:#0b1a30}" +
    "#ntHelpPop .ft{margin-top:10px;padding-top:8px;border-top:1px solid #d5dde6;font:600 13.5px/1.4 sans-serif;color:#4a5868}" +
    "#ntHelpPop .ft a{color:#1b5fd6;font-weight:800}" +
    ".nt-help-target{outline:4px solid #1b5fd6 !important;outline-offset:2px !important}" +
    "html.nt-help-mode,html.nt-help-mode *{cursor:help !important}" +
    "body.car #ntHelpBtn{display:none}" +
    "@media print{#ntHelpBtn,#ntHelpPop{display:none !important}}";
  document.head.appendChild(css);

  function inPop(el) { return !!(el && el.closest && (el.closest("#ntHelpPop") || el.closest("#ntHelpBtn"))); }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function typing(el) {
    if (!el || !el.tagName) return false;
    var t = el.tagName;
    if (t === "TEXTAREA" || t === "SELECT" || el.isContentEditable) return true;
    if (t === "INPUT") return !/^(checkbox|radio|range|button|submit|reset|color|file)$/i.test(el.type || "text");
    return false;
  }
  function find(el) {
    var list = window.NT_HELP || [];
    for (var a = el; a && a.nodeType === 1; a = a.parentElement) {
      for (var i = 0; i < list.length; i++) {
        if (list[i][0] === "body") continue;                // the page-wide entry is the very last resort
        try { if (a.matches(list[i][0])) return { title: list[i][1], html: list[i][2], el: a }; } catch (e) {}
      }
    }
    var t = el && el.closest ? el.closest("[title]") : null;
    if (t && t.getAttribute("title")) {
      var label = (t.textContent || "").replace(/\s+/g, " ").trim().slice(0, 40) || t.id || "This item";
      return { title: label, html: "<p>" + esc(t.getAttribute("title")) + "</p>", el: t, plain: true };
    }
    for (var j = 0; j < list.length; j++) if (list[j][0] === "body") return { title: list[j][1], html: list[j][2], el: document.body };
    return null;
  }
  function close() {
    if (pop) { pop.remove(); pop = null; }
    if (tgt) { tgt.classList.remove("nt-help-target"); tgt = null; }
  }
  function show(el, x, y) {
    close();
    if (!el) return;
    var h = find(el), guide = window.NT_HELP_GUIDE;
    var title, html;
    if (h) { title = h.title; html = h.html; tgt = h.el; }
    else {
      title = "No explanation for this yet";
      html = "<p>There is no help text for this exact spot yet. Try pointing at the nearest button, box or label and press <b>?</b> again.</p>";
    }
    pop = document.createElement("div"); pop.id = "ntHelpPop";
    pop.innerHTML = '<button class="x" title="Close (Esc)">&times;</button><h3>' + esc(title) + "</h3>" + html +
      '<div class="ft">Close with <b>Esc</b> or a click anywhere else. Point at anything and press <b>?</b> (or <b>F1</b>) for its explanation.' +
      (guide ? ' &middot; <a href="' + guide + '" target="_blank">Open the full guide</a>' : "") + "</div>";
    document.body.appendChild(pop);
    pop.querySelector(".x").onclick = close;
    if (tgt && tgt !== document.body && tgt !== document.documentElement) tgt.classList.add("nt-help-target");
    var w = pop.offsetWidth, hh = pop.offsetHeight, vw = innerWidth, vh = innerHeight;
    var px = x + 18, py = y + 18;
    if (px + w > vw - 8) px = Math.max(8, x - w - 18);
    if (px + w > vw - 8) px = Math.max(8, vw - w - 8);
    if (py + hh > vh - 8) py = Math.max(8, vh - hh - 8);
    pop.style.left = px + "px"; pop.style.top = py + "px";
  }
  function pointTarget() {
    var el = document.elementFromPoint(lastX, lastY);
    return inPop(el) ? null : el;
  }
  function setMode(on) {
    mode = on;
    document.documentElement.classList.toggle("nt-help-mode", on);
    if (btn) { btn.classList.toggle("on", on); btn.textContent = on ? "Help is ON: click anything (Esc ends)" : "? Help"; }
    if (!on) close();
  }

  document.addEventListener("mousemove", function (e) { lastX = e.clientX; lastY = e.clientY; }, true);
  document.addEventListener("touchstart", function (e) { var t = e.touches && e.touches[0]; if (t) { lastX = t.clientX; lastY = t.clientY; } }, true);

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { if (pop || mode) { setMode(false); close(); e.stopPropagation(); } return; }
    var isQ = (e.key === "?" || (e.key === "/" && e.shiftKey)) && !e.ctrlKey && !e.metaKey && !e.altKey;
    var isF1 = e.key === "F1";
    if (!isQ && !isF1) return;
    var ae = document.activeElement;
    if (isQ && typing(ae)) return;                      // let people type a question mark into a box
    e.preventDefault();
    var el = (isF1 && ae && ae !== document.body && typing(ae)) ? ae : pointTarget();
    if (!el) el = ae || document.body;
    var r = el.getBoundingClientRect ? el.getBoundingClientRect() : null;
    var x = (isF1 && el === ae && r) ? r.left : lastX, y = (isF1 && el === ae && r) ? r.bottom : lastY;
    show(el, x, y);
  }, true);

  function swallow(e) {
    if (!mode || inPop(e.target)) return;
    e.preventDefault(); e.stopPropagation(); if (e.stopImmediatePropagation) e.stopImmediatePropagation();
    if (e.type === "click") show(e.target, e.clientX, e.clientY);
  }
  ["pointerdown", "pointerup", "mousedown", "mouseup", "click", "dblclick", "touchend"].forEach(function (t) { document.addEventListener(t, swallow, true); });
  document.addEventListener("mousedown", function (e) { if (pop && !mode && !inPop(e.target)) close(); }, true);

  function addBtn() {
    if (document.getElementById("ntHelpBtn") || !document.body) return;
    btn = document.createElement("button"); btn.id = "ntHelpBtn"; btn.type = "button";
    btn.textContent = "? Help";
    btn.title = "Press this, then click anything to see what it is and how it works. Or point at anything and press the ? key (F1 also works).";
    btn.onclick = function (e) { e.stopPropagation(); setMode(!mode); };
    if (document.getElementById("map") && document.querySelector(".leaflet-container")) btn.style.bottom = "34px";
    document.body.appendChild(btn);
  }
  if (document.body) addBtn(); else document.addEventListener("DOMContentLoaded", addBtn);
  window.ntHelpShow = show;
})();
