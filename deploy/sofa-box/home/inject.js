/* Sofa Box: added to every app and web page the box opens (Sofa's TV pages too), in a script world of
   its own so sites can't see or break it. The Home key, Back, the pointer hiding when it's still, and
   the Sofa bar (mouse to the top edge, or the Menu key): Home, Back, Reload, smaller and bigger, the address,
   whether Sofa Shield is on, Add to Home, Close. It talks to the box's agent through window.__sofaBox (a DevTools
   binding); what it shows of the box comes as window.__sofaBoxVars. */
(function () {
  if (window.__sofaBoxBar) return;
  window.__sofaBoxBar = true;
  var send = function (o) { try { window.__sofaBox(JSON.stringify(o)); } catch (e) {} };
  var editing = function (el) { return el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)); };

  // ---- the pointer hides when it's still (a TV), and comes back when the mouse moves
  var still = 0, hiddenPtr = false;
  function pointer(show) {
    if (show === !hiddenPtr) return;
    hiddenPtr = !show;
    if (hiddenPtr) document.documentElement.setAttribute("data-sofa-nocursor", "");
    else document.documentElement.removeAttribute("data-sofa-nocursor");
  }
  // the box's own pointer, not the plain black arrow: white with a dark edge and a pink glow, pink over what can be
  // pressed. Drawn here (a PNG: the kind of picture every Chromium takes as a pointer).
  function arrow(fill) {
    try {
      var c = document.createElement("canvas"); c.width = c.height = 36;
      var g = c.getContext("2d");
      g.beginPath(); g.moveTo(5, 3); g.lineTo(5, 27); g.lineTo(11.5, 21); g.lineTo(16, 31); g.lineTo(20.5, 29); g.lineTo(16, 19.5);
      g.lineTo(25, 19.5); g.closePath();
      g.shadowColor = "rgba(255,46,136,.85)"; g.shadowBlur = 6;
      g.fillStyle = fill; g.fill();
      g.shadowBlur = 0; g.lineJoin = "round"; g.lineWidth = 2; g.strokeStyle = "#0D0D10"; g.stroke();
      return c.toDataURL("image/png");
    } catch (e) { return null; }
  }
  function pointerStyle() {
    var plain = arrow("#FFFFFF"), press = arrow("#FF2E88");
    if (!plain || !press) return "";
    return " html, body { cursor: url(" + plain + ") 5 3, auto; }" +
      " a[href], button, [role=button], [role=link], [role=menuitem], [role=tab], [role=option], summary, label, select," +
      " input[type=button], input[type=submit], input[type=checkbox], input[type=radio] { cursor: url(" + press + ") 5 3, pointer; }";
  }
  function addStyle() {
    if (document.getElementById("sofa-box-style")) return;
    var st = document.createElement("style"); st.id = "sofa-box-style";
    st.textContent = "html[data-sofa-nocursor], html[data-sofa-nocursor] * { cursor: none !important; }" + pointerStyle();
    // Sites made for a mouse: the remote's arrows move between their links and buttons (the browser's spatial
    // navigation), so show where you are, even where a site hides it. Not on Sofa's pages, or on apps made for
    // TVs (YouTube's): they show their own.
    if (!/\.localhost$|^127\.0\.0\.1$/.test(location.hostname) && !/Cobalt|SMART-TV|Tizen|Web0S/.test(navigator.userAgent))
      st.textContent += " a:focus-visible, button:focus-visible, input:focus-visible, select:focus-visible, textarea:focus-visible," +
        " [role=button]:focus-visible, [role=link]:focus-visible, [role=menuitem]:focus-visible, [role=tab]:focus-visible," +
        " [role=option]:focus-visible { outline: 3px solid #FF2E88 !important; outline-offset: 2px !important; }";
    (document.head || document.documentElement).appendChild(st);
  }

  // ---- the Sofa bar
  var host, root, bar, addr, open = false, hideTimer = 0, buttons = [], focusAt = 0, typed = false;
  var ICONS = {
    home: "M3 11.5 12 4l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z",
    back: "M15 5l-7 7 7 7", reload: "M20 12a8 8 0 1 1-2.3-5.6M20 4v5h-5",
    add: "M12 5v14M5 12h14", close: "M6 6l12 12M18 6 6 18",
    zoomout: "M10.5 17a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13zM20 20l-4.8-4.8M7.5 10.5h6",
    zoomin: "M10.5 17a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13zM20 20l-4.8-4.8M7.5 10.5h6M10.5 7.5v6",
    shield: "M12 3l7 3v6c0 4.4-3 7.6-7 9-4-1.4-7-4.6-7-9V6z"
  };
  var vars = window.__sofaBoxVars || {};
  // smaller and bigger, as a TV's browser has it: the page's own zoom, for as long as the tab is open
  var ZOOMS = [0.67, 0.8, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2], zoomAt = 3;
  try { zoomAt = Math.max(0, ZOOMS.indexOf(+sessionStorage.getItem("__sofaBoxZoom") || 1)); } catch (e) {}
  function zoomTo(i) {
    zoomAt = Math.max(0, Math.min(ZOOMS.length - 1, i));
    document.documentElement.style.zoom = ZOOMS[zoomAt] === 1 ? "" : String(ZOOMS[zoomAt]);
    try { sessionStorage.setItem("__sofaBoxZoom", String(ZOOMS[zoomAt])); } catch (e) {}
    if (root) toast("Size " + Math.round(ZOOMS[zoomAt] * 100) + "%");
  }
  if (zoomAt !== 3) document.addEventListener("DOMContentLoaded", function () { zoomTo(zoomAt); });
  function svg(name) {
    return '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="' + ICONS[name] + '"/></svg>';
  }
  function build() {
    host = document.createElement("sofa-box-bar");
    host.style.cssText = "all: initial; position: fixed; z-index: 2147483647; top: 0; left: 0; right: 0; pointer-events: none;";
    root = host.attachShadow({ mode: "closed" });
    root.innerHTML = '<style>' +
      ':host { all: initial; }' +
      '.bar { pointer-events: auto; margin: 0 auto; width: min(880px, 94vw); display: flex; align-items: center; gap: 8px; padding: 10px;' +
      ' font: 600 15px/1.2 system-ui, sans-serif; color: #EDEFF6; background: rgba(12,15,24,.88); backdrop-filter: blur(16px);' +
      ' border: 1px solid rgba(255,255,255,.12); border-top: 0; border-radius: 0 0 18px 18px; box-shadow: 0 18px 40px rgba(0,0,0,.45);' +
      ' transform: translateY(-110%); transition: transform .28s cubic-bezier(.2,.8,.2,1); }' +
      '.bar.on { transform: none; }' +
      'button { all: unset; display: grid; place-items: center; width: 44px; height: 44px; border-radius: 12px; color: #EDEFF6; cursor: pointer; }' +
      'button:hover, button.f { background: rgba(255,255,255,.14); }' +
      'button.f { box-shadow: 0 0 0 2px var(--a, #F4B740); }' +
      'button.add { width: auto; padding: 0 14px; gap: 6px; display: flex; background: var(--a, #F4B740); color: #1A1300; }' +
      'button.shield { width: auto; padding: 0 12px; gap: 6px; display: flex; color: #9BF5B9; font: 600 13px system-ui, sans-serif; }' +
      'button.shield.off { color: #9A9AA6; }' +
      'input { all: unset; flex: 1; min-width: 0; height: 44px; padding: 0 14px; border-radius: 12px; background: rgba(255,255,255,.08);' +
      ' color: #EDEFF6; font: 500 15px system-ui, sans-serif; }' +
      'input:focus, input.f { box-shadow: 0 0 0 2px var(--a, #F4B740); }' +
      '.toast { position: fixed; left: 50%; top: 84px; transform: translateX(-50%); padding: 10px 18px; border-radius: 999px;' +
      ' background: #EDEFF6; color: #0A0E1A; font: 600 15px system-ui, sans-serif; opacity: 0; transition: opacity .3s; }' +
      '.toast.on { opacity: 1; }' +
      '</style><div class="bar" part="bar">' +
      '<button data-a="home" title="Home">' + svg("home") + '</button>' +
      '<button data-a="back" title="Back">' + svg("back") + '</button>' +
      '<button data-a="reload" title="Reload">' + svg("reload") + '</button>' +
      '<button data-a="smaller" title="Smaller">' + svg("zoomout") + '</button>' +
      '<button data-a="bigger" title="Bigger">' + svg("zoomin") + '</button>' +
      '<input data-a="addr" spellcheck="false" aria-label="Address">' +
      '<button data-a="shield" class="shield' + (vars.shield === false ? ' off' : '') + '" title="Sofa Shield">' + svg("shield") +
        '<span>' + (vars.shield === false ? 'Shield off' : 'Shield on') + '</span></button>' +
      '<button data-a="add" class="add" title="Add to Home">' + svg("add") + '<span>Add to Home</span></button>' +
      '<button data-a="close" title="Close">' + svg("close") + '</button></div><div class="toast"></div>';
    bar = root.querySelector(".bar"); addr = root.querySelector("input");
    buttons = [].slice.call(root.querySelectorAll("button, input"));
    root.addEventListener("click", function (e) {
      var b = e.target.closest && e.target.closest("button"); if (b) act(b.dataset.a);
    });
    addr.addEventListener("keydown", function (e) {
      if (e.key === "Enter") { e.preventDefault(); e.stopPropagation(); go(addr.value); }
      else if (e.key.length === 1 || e.key === "Backspace" || e.key === "Delete") typed = true;   // typing: the arrows edit
    });
    bar.addEventListener("mouseleave", function () { schedule(1200); });
    bar.addEventListener("mouseenter", function () { clearTimeout(hideTimer); });
    (document.documentElement || document).appendChild(host);
  }
  function toast(text) {
    var t = root.querySelector(".toast"); t.textContent = text; t.classList.add("on");
    setTimeout(function () { t.classList.remove("on"); }, 2600);
  }
  function go(text) {
    text = (text || "").trim(); if (!text) return;
    var url = /^[a-z]+:\/\//i.test(text) ? text
      : /^(localhost|\d{1,3}(\.\d{1,3}){3})(:\d+)?(\/|$)/i.test(text) ? "http://" + text         // a computer at home
      : /^[^\s]+\.[a-z]{2,}(:\d+)?(\/|$)/i.test(text) ? "https://" + text
      : "https://duckduckgo.com/?q=" + encodeURIComponent(text);
    show(false); location.href = url;
  }
  function act(a) {
    if (a === "home") { show(false); send({ a: "home" }); }
    else if (a === "back") { show(false); if (history.length > 1) history.back(); else send({ a: "home" }); }
    else if (a === "reload") { show(false); location.reload(); }
    else if (a === "addr") { addr.focus(); addr.select(); }
    else if (a === "smaller" || a === "bigger") { zoomTo(zoomAt + (a === "bigger" ? 1 : -1)); schedule(8000); }
    else if (a === "shield") { toast(vars.shield === false ? "Sofa Shield is off: Settings, Sofa Shield" : "Sofa Shield keeps known ad and tracker sites out"); schedule(4000); }
    else if (a === "add") {
      var icon = document.querySelector('link[rel~="apple-touch-icon"], link[rel="manifest"], link[rel~="icon"]');
      send({ a: "add", url: location.href, title: document.title, icon: icon ? icon.href : "" });
      toast("Added to Home");
      schedule(2200);
    }
    else if (a === "close") { show(false); send({ a: "close" }); }
  }
  function focusOn(i) {
    focusAt = (i + buttons.length) % buttons.length;
    typed = false;
    buttons.forEach(function (b, n) { b.classList.toggle("f", n === focusAt); });
    if (buttons[focusAt] === addr) addr.focus(); else if (root.activeElement === addr) addr.blur();
  }
  function schedule(ms) { clearTimeout(hideTimer); hideTimer = setTimeout(function () { show(false); }, ms); }
  function show(on, withKeys) {
    if (!host || !document.documentElement.contains(host)) build();
    open = on;
    bar.classList.toggle("on", on);
    if (on) {
      addr.value = location.href.replace(/^https?:\/\//, "").replace(/\/$/, "");
      if (withKeys) focusOn(0); else buttons.forEach(function (b) { b.classList.remove("f"); });
      schedule(withKeys ? 8000 : 3500);
    } else { clearTimeout(hideTimer); if (root && root.activeElement) root.activeElement.blur(); }
  }

  // ---- a video you can hear starts here: the box pauses the music another app plays (not both at once)
  document.addEventListener("play", function (e) {
    var v = e.target;
    if (v && v.tagName === "VIDEO" && !v.muted && v.volume > 0) send({ a: "video" });
  }, true);

  // ---- keys: Home everywhere, Menu for the bar, Back when the site doesn't use it
  var superAlone = false;
  window.addEventListener("keydown", function (e) {
    var k = e.key;
    if (k === "Meta" || k === "OS") { superAlone = true; return; }
    superAlone = false;
    if (k === "BrowserHome" || k === "F1" || k === "HomePage") { e.preventDefault(); e.stopImmediatePropagation(); if (open) show(false); send({ a: "home" }); return; }
    if (k === "ContextMenu" || k === "F2" || k === "Menu") { e.preventDefault(); e.stopImmediatePropagation(); show(!open, true); return; }
    if (open) {                                       // the bar has the keys while it's open
      if (k === "ArrowLeft" || k === "ArrowRight") { if (!(root.activeElement === addr && typed)) { e.preventDefault(); e.stopImmediatePropagation(); focusOn(focusAt + (k === "ArrowRight" ? 1 : -1)); } }
      else if (k === "Enter" && buttons[focusAt] !== addr) { e.preventDefault(); e.stopImmediatePropagation(); act(buttons[focusAt].dataset.a); }
      else if (k === "Escape" || k === "BrowserBack") { e.preventDefault(); e.stopImmediatePropagation(); show(false); }
      else if (k === "ArrowUp" || k === "ArrowDown") { e.preventDefault(); e.stopImmediatePropagation(); }
      schedule(8000);
    }
  }, true);
  window.addEventListener("keydown", function (e) {      // after the site: Back if nothing else took it
    if (e.defaultPrevented || open || editing(document.activeElement)) return;
    if (e.key === "Backspace" || e.key === "Escape") {
      if (document.fullscreenElement) return;
      e.preventDefault();
      if (history.length > 1) history.back(); else send({ a: "home" });
    }
  });
  window.addEventListener("keyup", function (e) {
    if ((e.key === "Meta" || e.key === "OS") && superAlone) { superAlone = false; if (open) show(false); send({ a: "home" }); }
  }, true);

  // ---- a remote's key: the pointer goes (it's the remote you're using now)
  window.addEventListener("keydown", function (e) {
    if (/^(Arrow|Enter|Escape|Backspace|BrowserBack|GoBack|MediaPlayPause)/.test(e.key) && !open) { clearTimeout(still); pointer(false); }
  }, true);

  // ---- the mouse: the bar at the top edge, the pointer when it moves
  window.addEventListener("mousemove", function (e) {
    if (hiddenPtr && e.clientX >= innerWidth - 2 && e.clientY >= innerHeight - 2) return;   // (the box parking it: not a mouse)
    pointer(true);
    clearTimeout(still); still = setTimeout(function () { if (!open) pointer(false); }, 3000);
    if (e.clientY <= 3 && !open) show(true, false);
  }, true);

  document.addEventListener("visibilitychange", function () { if (document.hidden && open) show(false); });   // gone behind Home
  // ---- this page, for the Browser's start page (the box keeps only the browser's own sites)
  function visit() {
    var icon = document.querySelector('link[rel~="apple-touch-icon"], link[rel~="icon"]');
    send({ a: "visit", url: location.href, title: document.title, icon: icon ? icon.href : "" });
  }
  if (window === window.top) {
    if (document.readyState === "complete") setTimeout(visit, 800); else window.addEventListener("load", function () { setTimeout(visit, 800); });
  }
  function start() { addStyle(); still = setTimeout(function () { pointer(false); }, 3000); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
