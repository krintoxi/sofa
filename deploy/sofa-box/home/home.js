/* Sofa Box home screen: the box's apps, Sofa's "continue watching", the store, games, files, the browser's
   start page and the settings, worked with a TV remote, a game controller, or a keyboard and mouse.
   It runs in the box's first tab (http://127.0.0.1:8091/box/home); the agent opens apps as other tabs. */
(function () {
  "use strict";
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => [...(r || document).querySelectorAll(s)];
  const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const view = $("#view");
  const BUILTIN_ICON = { sofa: "#i-sofa", live: "#i-live", browser: "#i-browser", store: "#i-store", games: "#i-games", files: "#i-files", settings: "#i-settings" };
  const WATCH = new Set(["watch", "stream", "video", "media"]);              // the store's sections that are for watching
  const THEMES = [["street", "Street", "#0D0D10", "#FF2E88", "#E8FF3A"], ["terminal", "Terminal", "#020604", "#39FF88", "#00E0FF"],
                  ["pirate", "Pirate", "#0A1220", "#E6B450", "#C0392B"], ["sofa", "Sofa", "#0A0E1A", "#F4B740", "#3CC8D8"]];
  let data = { apps: [], running: [], devices: { drives: [], disc: null, n: 0 } }, sofa = null, storeData = null, games = null, boxInfo = null, servers = null;

  async function api(path, body) {
    const r = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json", "X-Sofa-Box": "1" }, body: JSON.stringify(body) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || "That didn't work.");
    return j;
  }
  let toastTimer = 0;
  function toast(text, ms) { const t = $("#toast"); t.textContent = text; t.classList.add("on"); clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove("on"), ms || 2800); }
  const untoast = () => { clearTimeout(toastTimer); $("#toast").classList.remove("on"); };
  const icon = (id, cls) => `<svg${cls ? ` class="${cls}"` : ""}><use href="${id === "#mark" ? "#m-" + (document.documentElement.dataset.theme || "street") : id}"/></svg>`;

  // ---------------------------------------------------------------- the look
  function applyTheme(name) {
    const t = THEMES.some(x => x[0] === name) ? name : (["midnight", "cinema", "ocean", "forest", "grape", "oled"].includes(name) ? "sofa" : "street");
    document.documentElement.dataset.theme = t;
    $$("use[href^='#mark']").forEach(u => u.setAttribute("href", "#m-" + t));
    $$("svg use").forEach(u => { if (u.getAttribute("href") === "#mark") u.setAttribute("href", "#m-" + t); });
  }
  const greeting = h => h < 5 ? "Good night" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
  function clockParts(d) {                  // "5:55" and "AM" (or "17:55" and nothing, where the clock is 24-hour)
    const t = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }), m = t.match(/^(.*?)\s*([AaPp])\.?\s?[Mm]\.?$/);
    return m ? [m[1], m[2].toUpperCase() + "M"] : [t, ""];
  }
  function tick() {
    const d = new Date(), [hm, ap] = clockParts(d);
    const sc = $("#sClock");
    if (sc) sc.innerHTML = esc(hm) + (ap ? "<small>" + ap + "</small>" : "");
    $("#clock").textContent = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    const big = $("#mClock");
    if (!big) return;
    big.innerHTML = esc(hm) + (ap ? "<small>" + ap + "</small>" : "");
    $("#mDate").textContent = d.toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" });
    $("#mHi").firstChild.textContent = greeting(d.getHours());
  }
  setInterval(tick, 10000); tick();

  // The pointer hides when it's still (a TV), and shows when the mouse moves.
  let still = 0;
  document.addEventListener("mousemove", () => {
    document.documentElement.removeAttribute("data-nocursor");
    clearTimeout(still); still = setTimeout(() => document.documentElement.setAttribute("data-nocursor", ""), 3000);
  });
  still = setTimeout(() => document.documentElement.setAttribute("data-nocursor", ""), 3000);

  // ---------------------------------------------------------------- data
  let devicesN = null;
  async function loadApps() {
    const before = data.devices;
    try { data = await api("/box/api/apps"); } catch (e) { /* the agent is restarting */ }
    data.devices = data.devices || { drives: [], disc: null, n: 0 };
    if (devicesN !== null && data.devices.n !== devicesN && before) {        // something plugged in (or a disc put in)
      const newDrive = data.devices.drives.find(d => !(before.drives || []).some(b => b.dev === d.dev));
      if (newDrive) toast("USB drive " + newDrive.label + " is ready.");
      else if (data.devices.disc && !before.disc) toast("A " + DISC[data.devices.disc.kind] + " is in.");
    }
    devicesN = data.devices.n;
    applyTheme(data.theme);
    document.documentElement.classList.toggle("lite", !!data.slow);
    return data;
  }
  const artSrc = (p, w) => {
    if (!p) return "";
    const [path, v] = p.split("?");
    return ((sofa && sofa.base) || "") + path.split("/").map((s, i) => i < 3 ? s : encodeURIComponent(s)).join("/") + "?w=" + w + "&r=2" + (v ? "&" + v : "");
  };
  const DISC = { dvd: "DVD", bluray: "Blu-ray", cd: "music CD", data: "disc" };
  async function loadSofa() {        // what you were watching, from the Sofa it opens with (the agent asks it)
    try { sofa = await api("/box/api/sofa/continue"); } catch (e) { sofa = { found: false }; }
    return sofa;
  }

  // ---------------------------------------------------------------- opening things
  // While an app loads (behind Home: the agent brings it forward once it has something to show), Home says so: its
  // icon on its colour, not a blank page. One that's open already comes straight back, with nothing in between.
  let openingTimer = 0;
  function opening(app, text) {
    const el = $("#opening");
    clearTimeout(openingTimer);
    if (!app) { el.classList.remove("on"); openingTimer = setTimeout(() => { el.hidden = true; }, 300); return; }
    if ((data.running || []).some(r => r.app === app.id)) return;
    el.style.setProperty("--c", app.color || "var(--a)");
    const ic = $(".op-ic", el);
    ic.className = "op-ic" + (!app.icon_url && !BUILTIN_ICON[app.id] ? " mono" : "");
    ic.innerHTML = appIcon(app);
    $("b", el).textContent = text || "Opening " + app.name + "…";
    el.hidden = false; void el.offsetWidth; el.classList.add("on");
    openingTimer = setTimeout(() => opening(null), 70000);                    // never left up
  }
  async function open(body) {
    opening(body.id && data.apps.find(a => a.id === body.id));
    try {
      const r = await api("/box/api/open", body);
      if (r.url) { opening(null); window.open(r.url, "_blank"); }          // a preview on a computer: a tab of its own
      else setTimeout(() => opening(null), 800);                            // (Home is behind the app by then)
    } catch (e) { opening(null); toast(e.message); }
  }
  async function openSofa(body) {
    // Sofa on this box starts the first time it's opened (up to a minute on a small board): say so, not a still screen
    const app = data.apps.find(a => a.id === (body && body.live ? "live" : "sofa"));
    opening(app);
    const slow = setTimeout(() => opening(app, "Starting Sofa… the first time takes up to a minute."), 1500);
    try {
      const r = await api("/box/api/sofa/open", body || {});
      clearTimeout(slow);
      if (r.ask) { opening(null); location.hash = "#/sofa" + (body && body.hash ? "?then=" + encodeURIComponent(body.hash) : ""); return; }
      if (r.url) { opening(null); window.open(r.url, "_blank"); } else setTimeout(() => opening(null), 800);
    } catch (e) { clearTimeout(slow); opening(null); toast(e.message); }
  }
  const openApp = (app, hash) => {
    if (app.id === "sofa") return openSofa(hash ? { hash } : {});
    if (app.id === "live") return openSofa({ hash: "#/live", live: true });
    if (app.kind === "builtin") { location.hash = app.url.split("#")[1] || "/"; return; }
    open(hash ? { id: app.id, hash } : { id: app.id });
  };

  // ---------------------------------------------------------------- pieces
  // An app's picture: its own icon (fetched from the site and kept), drawn icons for the box's own, else its
  // first letter. Tiles carry the app's colour: a glow of it behind the icon, and the frame when focused.
  // Every app icon, as it loads: a small one sits in the middle of its tile; a light one (a white logo on clear,
  // which vanishes on the tile's white) gets the app's colour behind it.
  window.sofaIcon = img => {
    const box = img.parentNode;
    if (!box) return;
    if (img.naturalWidth && img.naturalWidth < 64) box.classList.add("tiny");
    try {
      const c = document.createElement("canvas"), g = c.getContext("2d");
      c.width = c.height = 16; g.drawImage(img, 0, 0, 16, 16);
      const px = g.getImageData(0, 0, 16, 16).data;
      let solid = 0, light = 0;
      for (let i = 0; i < px.length; i += 4) if (px[i + 3] > 40) { solid++; if (px[i] + px[i + 1] + px[i + 2] > 690) light++; }
      if (solid < 6) {                     // nothing in it (some sites' icons are empty): the app's first letter
        const b = box.closest("button") && box.closest("button").querySelector("b");
        box.classList.add("mono"); box.classList.remove("tiny");
        img.replaceWith(document.createTextNode(((b && b.textContent) || "").replace(/^the\s+/i, "").charAt(0).toUpperCase()));
      } else if (solid < 230 && light / solid > 0.7) box.classList.add("light");
    } catch (e) { /* an icon from elsewhere: as it is */ }
  };
  function appIcon(a) {
    if (a.icon_url) return `<img decoding="async" src="${esc(a.icon_url)}" alt="" loading="lazy" onload="sofaIcon(this)" onerror="this.parentNode.classList.add('mono');this.replaceWith(document.createTextNode('${esc((a.name || "?")[0])}'))">`;
    if (BUILTIN_ICON[a.id]) return icon(BUILTIN_ICON[a.id]);
    return esc((a.name || "?").replace(/^the\s+/i, "")[0].toUpperCase());
  }
  function appTile(a, wide) {
    const running = (data.running || []).some(r => r.app === a.id);
    const mono = !a.icon_url && !BUILTIN_ICON[a.id];
    return `<button class="tile app${wide ? " wide" : ""}${a.hidden ? " off" : ""}${a.kind === "builtin" ? " own" : ""}" style="--c:${esc(a.color || "")}" data-app="${esc(a.id)}">
      ${running ? `<i class="dot" title="Open"></i>` : ""}<span class="ic${mono ? " mono" : ""}">${appIcon(a)}</span><b>${esc(a.name)}</b>${wide && a.about ? `<small>${esc(a.about)}</small>` : ""}</button>`;
  }
  function hint(parts) {
    $("#hint").innerHTML = parts.map(p => `<span><kbd>${esc(p[0])}</kbd>${esc(p[1])}</span>`).join("");
  }

  // ---------------------------------------------------------------- views
  const ABOUT = { sofa: "Your shows and films", live: "Free channels, no setup" };
  function inputsRow() {
    const dv = data.devices || {}, drives = dv.drives || [], disc = dv.disc;
    if (!drives.length && !disc) return "";
    return `<h2 class="row-title">Plugged in <small>USB drives and discs</small></h2><div class="rail inputs-row">
      ${disc ? `<button class="tile app wide input" style="--c:#7C5CFF" data-disc="${esc(disc.kind)}"><span class="ic">${icon("#i-disc")}</span>
        <b>${esc(disc.label)}</b><small>${disc.kind === "data" ? "Open in Files" : "Play the " + esc(DISC[disc.kind])}</small></button>` : ""}
      ${drives.map(d => `<button class="tile app wide input" style="--c:#2BB673" data-drive="${esc(d.root)}" data-dev="${esc(d.dev)}"><span class="ic">${icon("#i-usb")}</span>
        <b>${esc(d.label)}</b><small>${d.size ? size(d.size) + " · " : ""}Open in Files</small></button>`).join("")}</div>`;
  }
  // Home's top: the time and day, a hello, what to do next (resume, Sofa, Live TV), and the weather.
  function masthead(watch) {
    const s = sofa || {}, first = s.items && s.items[0], d = new Date(), [hm, ap] = clockParts(d);
    const who = s.found && s.signedIn && s.user ? ", " + s.user : "";
    const sub = first ? `Pick up where you left off: <b>${esc(first.title)}</b>${first.sub ? " · " + esc(first.sub) : ""}`
      : s.found && s.signedIn ? "Pick something in Sofa, or open an app." : s.found ? "Open Sofa and sign in with your phone."
      : data.servers ? "Sofa, Live TV and your apps are all here." : "Open Sofa to pick where it plays from, or watch free Live TV straight away.";
    const noApps = !watch.some(a => a.kind !== "builtin");
    return `<section class="mast${first && first.backdrop ? " has-art" : ""}">
      ${first && first.backdrop ? `<img decoding="async" class="mast-art" src="${esc(artSrc(first.backdrop, 1280))}" alt="" onerror="this.remove()">` : `<div class="mast-logo">${icon("#mark")}</div>`}
      <div class="mast-main">
        <div class="mast-date" id="mDate">${esc(d.toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" }))}</div>
        <div class="mast-clock" id="mClock">${esc(hm)}${ap ? "<small>" + ap + "</small>" : ""}</div>
        <h2 class="mast-hi" id="mHi">${greeting(d.getHours())}<span>${esc(who)}</span></h2>
        <p class="mast-sub">${sub}</p>
        ${first ? `<div class="bar"><i style="width:${first.pct}%"></i></div>` : ""}
        <div class="row-actions">${first ? `<button class="btn primary" data-sofa-hash="${esc(first.hash)}">${icon("#i-play")}Resume</button>
          <button class="btn" data-app="sofa">${icon("#i-sofa")}Open Sofa</button>` : `<button class="btn primary" data-app="sofa">${icon("#i-sofa")}Open Sofa</button>`}
          <button class="btn" data-app="live">${icon("#i-live")}Live TV</button>${noApps ? `<button class="btn" data-go="#/store">${icon("#i-store")}Get your apps</button>` : ""}</div>
      </div>
      <div class="wx" id="wx">${weatherCard()}</div></section>`;
  }

  // ---------------------------------------------------------------- the weather (the agent asks MET Norway)
  let weather = null, wxFound = [];
  const WX = [[/thunder/, "Thunder", "bolt"], [/sleet/, "Sleet", "sleet"], [/snow/, "Snow", "snow"], [/heavyrain/, "Heavy rain", "rain"],
              [/rainshowers/, "Showers", "rain"], [/lightrain/, "Light rain", "rain"], [/rain/, "Rain", "rain"], [/fog/, "Fog", "fog"],
              [/^cloudy/, "Cloudy", "cloud"], [/partlycloudy/, "Partly cloudy", "part"], [/fair/, "Mostly clear", "fair"], [/clearsky/, "Clear", "clear"]];
  const wxOf = sym => WX.find(w => w[0].test(sym || "")) || [null, "", "cloud"];
  function wxIcon(sym, cls) {                 // drawn here: a sun or moon, a cloud, and what falls from it
    const kind = wxOf(sym)[2], night = /_night|_polartwilight/.test(sym || "");
    const sky = (x, y, r) => night ? `<path class="m" d="M${x + r * .35} ${y - r}a${r} ${r} 0 1 0 ${r * .65} ${r * 1.75} ${r * .82} ${r * .82} 0 0 1-${r * .65}-${r * 1.75}z"/>`
      : `<g class="sun"><circle class="s" cx="${x}" cy="${y}" r="${r * .62}"/><path class="r" d="${[0, 45, 90, 135, 180, 225, 270, 315].map(a => {
          const c = Math.cos(a * Math.PI / 180), s = Math.sin(a * Math.PI / 180);
          return `M${(x + c * r * .9).toFixed(1)} ${(y + s * r * .9).toFixed(1)}L${(x + c * r * 1.22).toFixed(1)} ${(y + s * r * 1.22).toFixed(1)}`; }).join("")}"/></g>`;
    const cloud = (dy, c) => `<path class="${c || "c"}" transform="translate(0 ${dy})" d="M19 46h25a9 9 0 0 0 1-18 13 13 0 0 0-25-3 10.5 10.5 0 0 0-1 21z"/>`;
    const fall = { rain: `<path class="d" d="M24 51l-2 6M33 51l-2 6M42 51l-2 6"/>`, snow: `<g class="n"><circle cx="23" cy="54" r="2"/><circle cx="32" cy="57" r="2"/><circle cx="41" cy="54" r="2"/></g>`,
                   sleet: `<path class="d" d="M24 51l-2 6M40 51l-2 6"/><circle class="n" cx="32" cy="56" r="2"/>`, bolt: `<path class="b" d="M33 46l-7 10h6l-3 8 9-12h-6l3-6z"/>` };
    const art = kind === "clear" ? sky(32, 32, 14) : kind === "fair" ? sky(26, 26, 12) + cloud(6, "c2")
      : kind === "part" ? sky(24, 24, 11) + cloud(4) : kind === "fog" ? cloud(-6, "c2") + `<path class="f" d="M14 46h36M18 53h28M22 60h20"/>`
      : kind === "cloud" ? cloud(-8, "c2") + cloud(0) : cloud(-6) + (fall[kind] || "");
    return `<svg class="wxi${cls ? " " + cls : ""}" viewBox="0 0 64 64" aria-hidden="true">${art}</svg>`;
  }
  function weatherCard() {
    const w = weather;
    if (!w || w.off) return "";
    if (!w.ok) return `<div class="wx-card quiet"><p>${esc(w.message || "No weather just now.")}</p></div>`;
    const hour = t => new Date(t * 1000).toLocaleTimeString([], { hour: "numeric" }).replace(/\s?([AP])\.?\s?M\.?/i, (m, x) => x.toLowerCase() + "m");
    return `<div class="wx-card">
      <div class="wx-now">${wxIcon(w.symbol, "big")}<div><div class="wx-temp">${w.temp}°<small>${esc(w.units)}</small></div><div class="wx-text">${esc(wxOf(w.symbol)[1])}</div></div></div>
      <div class="wx-meta"><span class="wx-place">${esc(w.place)}</span><span>↑ ${w.high}°&nbsp;&nbsp;↓ ${w.low}°</span></div>
      ${w.hours && w.hours.length ? `<div class="wx-hours">${w.hours.map(h => `<div><small>${esc(hour(h.t))}</small>${wxIcon(h.symbol)}<b>${h.temp}°</b></div>`).join("")}</div>` : ""}</div>`;
  }
  async function loadWeather() {
    try { weather = await api("/box/api/weather"); } catch (e) { return; }
    const el = $("#wx");
    if (el) el.innerHTML = weatherCard();
  }
  setInterval(() => { if (!document.hidden) loadWeather(); }, 15 * 60000);
  function viewHome() {
    const apps = data.apps.filter(a => !a.hidden);
    const watch = apps.filter(a => WATCH.has(a.category)).map(a => Object.assign({ about: ABOUT[a.id] }, a));
    const rest = apps.filter(a => !WATCH.has(a.category));
    const s = sofa || {};
    const running = (data.running || []).filter(r => r.app !== "home");
    return `<div class="home view-in">${masthead(watch)}
      <h2 class="row-title">Watch</h2><div class="rail watch-row">${watch.map(a => appTile(a, true)).join("")}
        <button class="tile app wide add" data-go="#/store"><span class="ic">${icon("#i-plus")}</span><b>Add apps</b><small>Netflix, YouTube, Prime…</small></button></div>
      ${inputsRow()}
      ${s.items && s.items.length > 1 ? `<h2 class="row-title">Continue watching <small>${esc(s.name || "Sofa")}</small></h2><div class="rail">${s.items.slice(1).map(it => `<button class="tile poster" data-sofa-hash="${esc(it.hash)}">
          <img decoding="async" src="${esc(artSrc(it.art, 480))}" alt="" loading="lazy" onerror="this.style.visibility='hidden'"><span class="bar"><i style="width:${it.pct}%"></i></span>
          <span class="meta"><b>${esc(it.title)}</b><small>${esc(it.sub)}</small></span></button>`).join("")}</div>` : ""}
      ${running.length ? `<h2 class="row-title">Open now <small>Home brings you back here; they keep playing</small></h2><div class="rail open-now">${running.map(r => {
          const a = data.apps.find(x => x.id === r.app) || { id: r.app, name: r.title || r.app, color: "var(--a)" };
          return `<button class="tile app" style="--c:${esc(a.color || "")}" data-target="${esc(r.target)}"><span class="ic${!a.icon_url && !BUILTIN_ICON[a.id] ? " mono" : ""}">${appIcon(a)}</span>
            <b>${esc(r.title || a.name)}</b><small>${esc(a.name || "")}</small><span class="x" data-close="${esc(r.target)}" title="Close">${icon("#i-close")}</span></button>`; }).join("")}</div>` : ""}
      <h2 class="row-title">Your apps <small>${rest.length}</small></h2><div class="rail">${rest.map(a => appTile(a)).join("")}
        <button class="tile app" data-go="#/store"><span class="ic plus">${icon("#i-plus")}</span><b>Get more</b></button></div>
      ${games && games.games.length ? `<h2 class="row-title">Games</h2><div class="rail">${(games.native || []).filter(g => g.installed).map(g => `<button class="tile app" style="--c:${esc(g.color)}" data-play="${esc(g.id)}"><span class="ic emoji">${gameIc(g)}</span><b>${esc(g.name)}</b></button>`).join("")}${games.games.map(g => `<button class="tile app" style="--c:${esc(g.color)}" data-game="${esc(g.id)}"><span class="ic emoji">${esc(g.emoji || g.name[0])}</span><b>${esc(g.name)}</b></button>`).join("")}
        <button class="tile app" data-go="#/games"><span class="ic plus">${icon("#i-plus")}</span><b>More games</b></button></div>` : ""}
    </div>`;
  }

  function viewStore() {
    if (!storeData) { api("/box/api/store").then(st => { storeData = st; render(true); setTimeout(refreshStoreIcons, 6000); }).catch(e => toast(e.message)); return `<h1 class="page">App Store</h1><p class="lede">Loading…</p>`; }
    const tile = e => `<button class="tile app${e.installed ? " have" : ""}" style="--c:${esc(e.color)}" data-store="${esc(e.id)}">
        ${e.installed ? `<i class="badge">On Home</i>` : e.drm ? `<i class="badge warn" title="Uses DRM">DRM</i>` : ""}<span class="ic${e.icon_url ? "" : " mono"}">${e.icon_url ? `<img decoding="async" src="${esc(e.icon_url)}" alt="" loading="lazy" onload="sofaIcon(this)">` : esc(e.name.replace(/^the\s+/i, "")[0].toUpperCase())}</span><b>${esc(e.name)}</b></button>`;
    return `<div class="view-in"><h1 class="page">App Store</h1>
      <p class="lede">Apps open full screen, with no browser around them. Press OK to put one on Home.</p>
      <div class="store-detail" id="storeDetail"></div>
      ${storeData.sections.map(sec => `<h2 class="row-title">${esc(sec.name)}${sec.about ? ` <small>${esc(sec.about)}</small>` : ""}</h2><div class="rail">${sec.apps.map(tile).join("")}</div>`).join("")}
      <h2 class="row-title">Any website</h2>
      <div class="add-site"><input class="field" id="siteUrl" aria-label="A site's address" placeholder="Type an address: radio.example.com" spellcheck="false">
        <button class="btn primary" data-add-site="1">Add to Home</button></div></div>`;
  }
  async function refreshStoreIcons() {        // the store's icons arrive one by one: show the new ones
    if (!location.hash.startsWith("#/store")) return;
    try {
      const st = await api("/box/api/store");
      const had = storeData ? storeData.sections.flatMap(x => x.apps).filter(e => e.icon_url).length : 0;
      if (st.sections.flatMap(x => x.apps).filter(e => e.icon_url).length > had) { storeData = st; render(true); setTimeout(refreshStoreIcons, 6000); }
    } catch (e) {}
  }
  function storeDetail(id) {
    const box = $("#storeDetail"); if (!box || !storeData) return;
    const e = storeData.sections.flatMap(s => s.apps).find(x => x.id === id); if (!e) return;
    box.style.setProperty("--c", e.color);
    box.innerHTML = `<span class="ic${e.icon_url ? "" : " mono"}">${e.icon_url ? `<img decoding="async" src="${esc(e.icon_url)}" alt="" onload="sofaIcon(this)">` : esc(e.name[0])}</span><div><h3>${esc(e.name)}</h3><p>${esc(e.about || "")}${e.drm ? ` <span class="warn">Uses DRM: on a Pi 3 the picture may be smaller, and some services may not play.</span>` : ""}</p>
      <p class="addr">${esc(e.url.replace(/^https?:\/\//, ""))}</p></div>
      <div>${e.installed ? `<button class="btn primary" data-app="${esc(e.id)}">Open</button> <button class="btn" data-remove="${esc(e.id)}">Remove</button>`
        : `<button class="btn primary" data-install="${esc(e.id)}">Add to Home</button>`}</div>`;
  }

  // ---- Sofa: where it plays from
  const KIND = { sofa: "Sofa", jellyfin: "Jellyfin", emby: "Emby", plex: "Plex" };
  async function loadServers(scan) {
    try { servers = await api(scan ? "/box/api/sofa/scan" : "/box/api/sofa", scan ? {} : undefined); } catch (e) { servers = { error: e.message }; }
    if (location.hash.startsWith("#/sofa") || location.hash.startsWith("#/settings")) render(true);
  }
  const serverBtn = (x, extra) => `<button class="srv" data-server="${esc(x.id)}"${extra || ""}><span class="srv-ic k-${esc(x.kind)}">${x.where === "box" ? icon("#i-box") : x.kind === "sofa" ? icon("#i-sofa") : esc(KIND[x.kind][0])}</span>
    <span><b>${esc(x.name)}</b><small>${esc(x.about || (KIND[x.kind] + " · " + (x.url || "").replace(/^https?:\/\//, "")))}</small></span>${servers && servers.default === x.id && !servers.ask ? `<i class="pill">Opens</i>` : ""}</button>`;
  function viewSofa() {
    if (!servers) { loadServers(true); return `<div class="chooser view-in"><h1 class="page">Where's your Sofa?</h1><p class="lede">Looking around your home…</p></div>`; }
    if (servers.error) return `<h1 class="page">Sofa</h1><p class="lede">${esc(servers.error)}</p>`;
    const added = servers.servers || [];
    const home = added.filter(x => x.kind === "sofa" && x.where === "home"), net = added.filter(x => x.kind === "sofa" && x.where === "internet");
    const other = added.filter(x => x.kind !== "sofa");
    const card = (cls, ic, title, about, body) => `<section class="choose-card ${cls}"><div class="cc-head"><span class="cc-ic">${icon(ic)}</span><div><h3>${title}</h3><p>${about}</p></div></div><div class="cc-body">${body}</div></section>`;
    const foundBtn = x => `<button class="srv found" data-add-found="${esc(x.url)}" data-kind="${esc(x.kind)}"><span class="srv-ic k-${esc(x.kind)}">${x.kind === "sofa" ? icon("#i-sofa") : esc(KIND[x.kind][0])}</span>
      <span><b>${esc(x.name)}</b><small>Found: ${esc(x.url.replace(/^https?:\/\//, ""))}</small></span><i class="pill new">New</i></button>`;
    return `<div class="chooser view-in"><h1 class="page">Where's your Sofa?</h1>
      <p class="lede">Pick where Sofa plays from. Add as many as you like and switch any time: Sofa remembers you on each one.</p>
      <div class="choose-grid">
        ${card("c-home", "#i-house", "Sofa at home", "A Sofa computer on this network.",
          home.map(x => serverBtn(x)).join("") + (servers.found || []).map(foundBtn).join("") +
          (home.length || (servers.found || []).length ? "" : `<p class="none">None found yet. Is the Sofa computer on?</p>`) +
          `<button class="mini" data-type-server="home">Type its address</button>`)}
        ${card("c-net", "#i-globe", "Sofa on the internet", "A share link someone sent you, or your own Sofa from outside.",
          net.map(x => serverBtn(x)).join("") + (servers.featured || []).map(x => serverBtn(Object.assign({}, x, { about: x.about || "Free to watch" }), ` data-featured="${esc(x.url)}"`)).join("") +
          `<button class="mini" data-type-server="internet">Paste a link</button>`)}
        ${servers.local ? card("c-box", "#i-box", "This box", "No server? Sofa runs right here.",
          serverBtn({ id: "box", kind: "sofa", where: "box", name: "Sofa on this box", about: "Free Live TV, and videos on this box and USB drives." })) : ""}
        ${card("c-other", "#i-server", "Other servers", "Jellyfin, Emby or Plex, if that's what you use.",
          other.map(x => serverBtn(x)).join("") + (servers.others || []).map(foundBtn).join("") +
          `<button class="mini" data-type-server="other">Type its address</button><button class="mini" data-scan="1">Look again</button>`)}
      </div></div>`;
  }
  async function pickServer(id) {
    const x = (servers.servers || []).find(s => s.id === id) || { id, name: "Sofa on this box" };
    sheet(`<h3>Open Sofa from ${esc(x.name)}</h3><p class="sheet-note">Every time, or should the box ask each time you open Sofa?</p>
      <button class="btn primary" data-sheet="always">Every time</button><button class="btn" data-sheet="ask">Ask me each time</button>
      <p class="sheet-note small">You can change this in Settings → Sofa.</p>`, async a => {
      closeSheet();
      try {
        await api("/box/api/sofa/choose", { id, remember: a === "always" });
        servers = null; await loadApps();
        const then = decodeURIComponent((location.hash.split("?then=")[1] || ""));
        if (location.hash.startsWith("#/sofa")) location.hash = "#/";
        await openSofa({ id, hash: then });
      } catch (e) { toast(e.message); }
    });
  }
  async function addServer(body) {
    toast("Checking…");
    const r = await api("/box/api/sofa/add", body);
    servers = null; await loadServers();
    return r.server;
  }

  // ---------------------------------------------------------------- asleep: the screensaver (the phone's power button)
  // The time and the weather, over the art of what you've been watching, crossfading; the card drifts to a new spot
  // every minute so nothing burns into the TV. Any key, the mouse, or a touch on the phone wakes the box.
  let sleepTimer = 0;
  function viewSleep() {
    document.documentElement.classList.add("asleep");
    const arts = [...new Set(((sofa || {}).items || []).map(i => i.backdrop).filter(Boolean))].slice(0, 8);
    const d = new Date(), [hm, ap] = clockParts(d), w = weather && weather.ok ? weather : null;
    clearInterval(sleepTimer);
    let n = 0;
    sleepTimer = setInterval(() => {
      if (!location.hash.startsWith("#/sleep")) return clearInterval(sleepTimer);
      n++;
      const imgs = Array.from(document.querySelectorAll(".sleep-art"));
      if (imgs.length > 1 && n % 3 === 0) {
        const on = imgs.findIndex(i => i.classList.contains("on"));
        imgs.forEach((im, i) => im.classList.toggle("on", i === (on + 1) % imgs.length));
      }
      const card = $(".sleep-card");
      if (card && n % 6 === 0) { card.style.left = (5 + Math.random() * 52) + "vw"; card.style.bottom = (8 + Math.random() * 46) + "vh"; }
    }, 10000);
    return `<div class="sleep">${arts.map((a, i) => `<img decoding="async" class="sleep-art${i ? "" : " on"}" src="${esc(artSrc(a, 1280))}" alt="" onerror="this.remove()">`).join("")}
      <div class="sleep-card"><div class="sleep-clock" id="sClock">${esc(hm)}${ap ? "<small>" + ap + "</small>" : ""}</div>
        <div class="sleep-date">${esc(d.toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" }))}</div>
        ${w ? `<div class="sleep-wx">${wxIcon(w.symbol)}<b>${w.temp}°</b><span>${esc(w.place)}</span></div>` : ""}
        <div class="sleep-mark">${icon("#mark")}<b>Sofa</b><span>Box</span></div></div>
      <p class="sleep-hint">Press any key, or touch your phone, to wake it</p></div>`;
  }
  function wakeUp(e) {
    if (!location.hash.startsWith("#/sleep")) return;
    if (e) { e.preventDefault(); e.stopPropagation(); }
    api("/box/api/sleep", { wake: true }).catch(() => {});
    location.hash = "#/";
  }
  for (const ev of ["keydown", "mousedown", "wheel", "touchstart"]) window.addEventListener(ev, wakeUp, { capture: true, passive: false });

  // ---------------------------------------------------------------- Games: the small ones in the page, and games
  // that run on the box itself (installed from the list when asked, played offline with a controller)
  const PAD_NAMES = { xbox: "Xbox controller", playstation: "PlayStation controller", nintendo: "Nintendo controller", "8bitdo": "8BitDo controller", generic: "Controller" };
  const PAD_HOME = { xbox: "the Xbox button", playstation: "the PS button" };
  function webGameTile(g) {
    return `<button class="tile game" style="--c:${esc(g.color)}" data-game="${esc(g.id)}"><span class="ic">${esc(g.emoji || g.name[0])}</span>
      <b>${esc(g.name)}</b><small>${esc(g.about)}</small></button>`;
  }
  // a game's own picture (games/icons/), or its emoji
  function gameIc(g) { return g.icon ? `<img decoding="async" class="game-ic" src="/box/games/${esc(g.icon)}" alt="">` : esc(g.emoji || g.name[0]); }
  function nativeTile(g) {
    return `<button class="tile game" style="--c:${esc(g.color)}" data-play="${esc(g.id)}"><span class="ic">${gameIc(g)}</span>
      <b>${esc(g.name)}</b><small>${esc(g.about)}</small>${g.playing ? `<span class="meta">Playing now</span>` : ""}</button>`;
  }
  function getTile(g, job) {
    const busy = job && job.id === g.id;
    const meta = busy ? `<i class="spin"></i>${job.action === "install" ? "Getting it: a few minutes" : "Removing it…"}`
      : !g.fits ? `Needs a Raspberry Pi ${g.pi} or 5` : `Free · about ${g.mb >= 1000 ? (g.mb / 1000).toFixed(1) + " GB" : g.mb + " MB"}${g.mouse ? " · the stick is its mouse" : ""}`;
    return `<button class="tile game get${g.fits ? "" : " off"}" style="--c:${esc(g.color)}" data-game-get="${esc(g.id)}"${g.fits ? "" : " disabled"}>
      <span class="ic">${gameIc(g)}</span><b>${esc(g.name)}</b><small>${esc(g.about)}</small>
      ${g.note ? `<small class="note">${esc(g.note)}</small>` : ""}<span class="meta">${meta}</span></button>`;
  }
  function padsCard() {
    const pads = games.pads || [];
    if (pads.length) {
      const home = PAD_HOME[pads[0].kind] || "Home";
      return `<div class="pads">${pads.map(p => `<span class="pad-chip"><b><i class="pad-ic">🎮</i>${esc(PAD_NAMES[p.kind] || "Controller")}</b><small>${esc(p.name)}</small></span>`).join("")}
        <p class="small">Ready: every game here works with it from the start. To come back from a game, hold <b>${esc(home)}</b> for a second.</p></div>`;
    }
    return `<section class="card pads-card"><h3>Connect a controller</h3>
      <p class="small">Put it in pairing mode, then <b>Look for controllers</b>: it pairs by itself, and the box knows which kind it is.</p>
      <ul class="pair-how"><li><b>Xbox:</b> hold the small pair button on top until the Xbox button flashes fast.</li>
        <li><b>PlayStation:</b> hold Create (or Share) and the PS button until the light flashes.</li>
        <li><b>8BitDo and others:</b> hold the pair button, or Start with X or Y (its manual says).</li></ul>
      <p class="small">A USB cable, or a controller with its own USB dongle, works as soon as it's plugged in.</p>
      <div class="choices"><button class="btn" data-bt-look="1">Look for controllers</button></div>
      <div id="btList" class="bt-list small-list">${btList()}</div></section>`;
  }
  function viewGames() {
    if (!games) return `<h1 class="page">Games</h1><p class="lede">Loading…</p>`;
    setupLive();
    const job = games.job && games.job.state === "working" ? games.job : null;
    const native = games.native || [], have = native.filter(g => g.installed), more = native.filter(g => !g.installed);
    return `<div class="view-in"><h1 class="page">Games</h1><p class="lede">Play on the TV with a controller. Once a game is on the box, it plays without the internet.</p>
      ${padsCard()}
      <h2 class="row-title">On the box</h2><div class="grid games">${have.map(nativeTile).join("")}${games.games.map(webGameTile).join("")}</div>
      ${more.length ? `<h2 class="row-title">Get more games <small>free and open source</small></h2><div class="grid games">${more.map(g => getTile(g, job)).join("")}</div>` : ""}
      ${have.length ? `<h2 class="row-title">Remove a game</h2><div class="choices">${have.map(g => `<button class="mini" data-game-remove="${esc(g.id)}">${esc(g.name)} <small>about ${g.mb} MB</small></button>`).join("")}</div>` : ""}
      ${games.free_mb != null ? `<p class="small">${(games.free_mb / 1024).toFixed(1)} GB free on the box.</p>` : ""}</div>`;
  }
  async function loadGames() {
    const g = await api("/box/api/games").catch(() => null);
    if (!g) return false;
    const changed = JSON.stringify(g) !== JSON.stringify(games);
    games = g;
    return changed;
  }
  setInterval(async () => {                    // Games: a game on its way, controllers coming and going
    if (document.hidden || $(".sheet-back") || location.hash !== "#/games") return;
    if (await loadGames()) render(true);
  }, 3000);

  function viewBrowser() {
    const web = data.apps.filter(a => a.kind === "web" && !a.hidden).slice(0, 10);
    const quick = [["DuckDuckGo", "https://duckduckgo.com", "#DE5833"], ["Wikipedia", "https://en.wikipedia.org", "#BBBBBB"],
                   ["YouTube", "https://www.youtube.com", "#FF3B30"], ["Reddit", "https://www.reddit.com", "#FF4500"]];
    return `<div class="browser-start view-in"><h1 class="page">Browser</h1>
      <input class="field big" id="address" aria-label="Search, or type an address" placeholder="Search, or type an address" spellcheck="false" autocomplete="off">
      <div class="grid">${quick.map(q => `<button class="tile" style="--c:${q[2]}" data-url="${esc(q[1])}"><span class="ic">${esc(q[0][0])}</span><b>${esc(q[0])}</b></button>`).join("")}
        ${web.map(a => appTile(a)).join("")}</div>
      <div class="hint-card">On any site, press <b>Menu</b> (or move the mouse to the top) for the Sofa bar: <b>Home</b>, <b>Back</b>,
        the address, and <b>Add to Home</b> to make the site an app. Sofa Shield keeps ads and trackers out.</div></div>`;
  }
  function go(text) {
    text = (text || "").trim(); if (!text) return;
    const url = /^[a-z]+:\/\//i.test(text) ? text
      : /^(localhost|\d{1,3}(\.\d{1,3}){3})(:\d+)?(\/|$)/i.test(text) ? "http://" + text           // a computer at home
      : /^[^\s]+\.[a-z]{2,}(:\d+)?(\/|$)/i.test(text) ? "https://" + text : "https://duckduckgo.com/?q=" + encodeURIComponent(text);
    open({ url });
  }

  // ---- files
  let filesAt = { root: "downloads", path: "" }, filesData = null, roots = null;
  async function loadFiles() {
    try {
      if (!roots) roots = (await api("/box/api/files")).roots;
      filesData = await api("/box/api/files/list?root=" + encodeURIComponent(filesAt.root) + "&path=" + encodeURIComponent(filesAt.path));
    } catch (e) { filesData = { error: e.message }; }
    if (location.hash.startsWith("#/files")) render(true);
  }
  const size = n => n == null ? "" : n > 1e9 ? (n / 1e9).toFixed(1) + " GB" : n > 1e6 ? Math.round(n / 1e6) + " MB" : Math.max(1, Math.round(n / 1e3)) + " KB";
  const KIND_ICON = { folder: "#i-folder", video: "#i-video", audio: "#i-audio", image: "#i-image", file: "#i-file", archive: "#i-file" };
  function viewFiles() {
    if (!filesData) { loadFiles(); return `<h1 class="page">Files</h1><p class="lede">Loading…</p>`; }
    const parts = filesAt.path ? filesAt.path.split("/") : [];
    return `<div class="view-in"><h1 class="page">Files</h1><div class="files">
      <div class="places">${(roots || []).map(r => `<button class="place" data-root="${esc(r.id)}" aria-current="${r.id === filesAt.root}">${icon(r.drive ? "#i-usb" : "#i-folder")}<b>${esc(r.name)}</b></button>`).join("")}</div>
      <div>${filesData.error ? `<p class="empty">${esc(filesData.error)}</p>` : `
        <div class="crumbs"><button data-crumb="">${esc(filesData.root.name)}</button>${parts.map((p, i) => `› <button data-crumb="${esc(parts.slice(0, i + 1).join("/"))}">${esc(p)}</button>`).join("")}
          <span class="free">${size(filesData.free)} free</span> <button class="mini" data-newfolder="1">New folder</button></div>
        <div class="flist">${filesData.items.length ? filesData.items.map(it => `<button class="fitem ${it.dir ? "folder" : ""}" data-file="${esc(it.name)}" data-kind="${it.kind}">
          ${icon(KIND_ICON[it.kind] || "#i-file")}<b>${esc(it.name)}</b><span class="size">${it.dir ? "" : size(it.size)}</span>
          <span class="when">${new Date(it.mtime * 1000).toLocaleDateString()}</span></button>`).join("") : `<p class="empty">Nothing here yet. Downloads from the browser land in Downloads; plug in a USB drive and it shows on the left.</p>`}</div>`}
      </div></div></div>`;
  }
  const filePath = name => (filesAt.path ? filesAt.path + "/" : "") + name;
  function fileOpen(name, kind) {
    if (kind === "folder") { filesAt.path = filePath(name); loadFiles(); return; }
    if (kind === "video" || kind === "audio") { api("/box/api/files/play", { root: filesAt.root, path: filePath(name) }).catch(e => toast(e.message)); return; }
    if (kind === "image") {
      const v = document.createElement("div"); v.className = "viewer";
      v.innerHTML = `<img decoding="async" src="/box/files/raw?root=${encodeURIComponent(filesAt.root)}&path=${encodeURIComponent(filePath(name))}" alt="">`;
      v.addEventListener("click", () => v.remove()); document.body.appendChild(v); return;
    }
    fileMenu(name, kind);
  }
  function fileMenu(name, kind) {
    sheet(`<h3>${esc(name)}</h3>
      ${kind !== "file" && kind !== "archive" ? `<button class="btn primary" data-sheet="open">${kind === "folder" ? "Open" : kind === "image" ? "Look" : "Play"}</button>` : ""}
      <button class="btn" data-sheet="rename">Rename</button><button class="btn" data-sheet="move">Move to…</button>
      <button class="btn danger" data-sheet="delete">Delete</button><button class="btn" data-sheet="close">Cancel</button>`, async a => {
      if (a === "open") { closeSheet(); fileOpen(name, kind); }
      else if (a === "rename") askText("New name", name, async v => { await fileDo("rename", { name: v }); });
      else if (a === "move") pickPlace(async to => { await fileDo("move", { to_root: to, to_path: "" }); });
      else if (a === "delete") confirmSheet("Delete " + name + "?" + (kind === "folder" ? " Everything in it goes too." : ""), async () => { await fileDo("delete", {}); });
      else closeSheet();
    });
    async function fileDo(action, extra) {
      try { await api("/box/api/files/" + action, Object.assign({ root: filesAt.root, path: filePath(name) }, extra)); closeSheet(); toast("Done."); loadFiles(); }
      catch (e) { toast(e.message); }
    }
  }

  // ---- settings
  async function loadInfo() {
    try { const [info, shield] = await Promise.all([api("/box/api/info"), api("/box/api/shield")]); info.shield = shield; boxInfo = info; }
    catch (e) { boxInfo = { error: e.message }; }
    if (location.hash.startsWith("#/settings")) refreshPane(); else if (location.hash.startsWith("#/welcome")) render(true);
  }
  // Sofa on this box, from anywhere: the box opens its own Sofa to the internet (an address, the router, a certificate,
  // the internet let in, a look from outside), the way Sofa does on any computer, in a few presses.
  let thisBox = null, thisBoxTimer = 0;
  async function loadThisBox() {
    try { thisBox = await api("/box/api/thisbox/internet"); } catch (e) { thisBox = { error: e.message }; }
    const busy = thisBox.progress && thisBox.progress.busy;
    const card = $("#thisBoxCard");
    if (card) card.outerHTML = thisBoxCard();
    clearTimeout(thisBoxTimer);
    if (busy || (thisBox.internet && thisBox.internet.outside && thisBox.internet.outside.busy)) thisBoxTimer = setTimeout(loadThisBox, 3000);
  }
  function thisBoxCard() {
    if (!thisBox) { setTimeout(loadThisBox, 0); return `<section class="card" id="thisBoxCard"><h3>Sofa on this box, from anywhere</h3><p class="small">Loading…</p></section>`; }
    const t = thisBox, n = t.internet || {}, h = n.https || {}, o = n.outside || {}, pr = t.progress || {};
    const head = `<section class="card" id="thisBoxCard"><h3>Sofa on this box, from anywhere</h3>`;
    if (!t.available) return "";
    if (!t.running) return head + `<p>Sofa on this box (This box) plays your USB drives and free Live TV. ${t.public ? "It's open to the internet; it starts with the box." : "Open it once (Sofa → This box), and it can be opened to the internet from here too, so you can watch it anywhere."}</p></section>`;
    const tick = (v, yes, no) => v === true ? `<li class="okay">✓ ${yes}</li>` : v === false ? `<li class="bad">✗ ${no}</li>` : "";
    const open = n.remote === "public", where = h.domain ? "https://" + h.domain : "";
    const lan = t.address || "the box";
    return head + `<p>${open ? `Open to the internet at <b>${esc(where)}</b>: sign in there from anywhere (everyone needs their own account; the Server page stays home-only).`
        : "Watch Sofa on this box away from home, from a phone or a computer, at your own address: a free one from duckdns.org, or your own domain. Everything goes over HTTPS, and everyone signs in."}</p>
      ${pr.busy ? `<p class="small looking"><i class="spin"></i><span>${esc(pr.step || "Working")}…</span></p>` : ""}${pr.error ? `<p class="small bad">${esc(pr.error)}</p>` : ""}
      ${open ? "" : `<p class="small">Your address: on your phone, sign in at <b>duckdns.org</b>, make a name, and copy its token. Or use a domain you own (point it at your home).</p>
        <div class="add-site"><input class="field" id="tbDomain" aria-label="Your address (yourname.duckdns.org)" value="${esc(h.domain || "")}" placeholder="yourname.duckdns.org" spellcheck="false" autocomplete="off">
          <input class="field" id="tbToken" aria-label="DuckDNS token" type="password" placeholder="${n.duckdns_token ? "DuckDNS token: saved" : "DuckDNS token"}" autocomplete="off"></div>`}
      <ul class="tb-checks">${h.domain && n.public_ip ? tick(n.points_here, esc(h.domain) + " points at your home", esc(h.domain) + " doesn't point at your home yet") : ""}
        ${n.upnp && n.upnp.at ? tick(n.upnp.ok, "The router sends the ports to the box", "The router didn't take the request: in its settings, forward port <b>443</b> to " + esc(lan) + ":" + esc(t.https_port) + (n.dns_check ? "" : " and <b>80</b> to " + esc(lan) + ":" + esc(t.port))) : ""}
        ${h.mode === "letsencrypt" && (h.trusted || h.error) ? tick(h.trusted, "Certificate from Let's Encrypt", "No certificate yet") : ""}
        ${o.at && o.reach ? tick(o.reach.ok, "Answers from the internet", esc(o.reach.message)) : ""}
        ${o.shared ? `<li class="bad">✗ Your internet provider shares one address between homes: no port can be opened. Ask them for a public address, or use Tailscale.</li>` : ""}</ul>
      <div class="choices">${open ? `<button class="btn" data-tb="check">Check from outside</button><button class="btn danger" data-tb="close">Make it home only</button>`
        : `<button class="btn primary" data-tb="open"${pr.busy ? " disabled" : ""}>Open it to the internet</button>`}</div></section>`;
  }
  // Settings, as on a TV: what there is to set down the left, the one you're on beside it. Only that one is drawn, so
  // the page stays small and every press quick on a Pi 3 (all of it on one page was 13 cards and 5,000 pixels tall).
  // Moving along the list shows each; OK or Right goes into it; Back comes out to the list.
  const SET_TABS = [["network", "Wi-Fi and network", "#i-globe"], ["remotes", "Remotes and Bluetooth", "#i-games"],
    ["sofa", "Sofa", "#i-sofa"], ["picture", "Picture and sound", "#i-video"], ["home", "Home screen", "#i-house"],
    ["shield", "Sofa Shield", "#i-shield"], ["box", "This box", "#i-box"], ["software", "Software", "#i-settings"],
    ["help", "Help", "#i-file"]];
  let setTab = "network", setTabTimer = 0, wifiNets = null, wifiAt = 0;
  function viewSettings() {
    if (!servers) loadServers();
    if (!setup) loadSetup().then(() => { if (location.hash.startsWith("#/settings")) refreshPane(); });
    setupLive();
    const want = location.hash.split("/")[2];
    if (want && SET_TABS.some(t => t[0] === want)) setTab = want;
    return `<div class="settings view-in"><h1 class="page">Settings</h1><div class="set-grid">
      <nav class="set-nav" aria-label="Settings">${SET_TABS.map(([id, label, ic]) => `<button class="set-tab" data-set-tab="${id}" aria-current="${id === setTab}">${icon(ic)}<span>${label}</span></button>`).join("")}</nav>
      <div class="set-pane" id="setPane">${setPane()}</div></div></div>`;
  }
  function showTab(id) {
    if (id === setTab || !$("#setPane")) return;
    setTab = id;
    $$(".set-tab").forEach(t => t.setAttribute("aria-current", t.dataset.setTab === id));
    $("#setPane").innerHTML = setPane();
    if (scrollY > 0) window.scrollTo(0, 0);
    history.replaceState(null, "", "#/settings/" + id);
  }
  function refreshPane() {                    // new data for Settings: only the part on screen is drawn again
    const pane = $("#setPane");
    if (!pane) return render(true);
    const had = cur && pane.contains(cur) ? keyOf(cur) : null;
    pane.innerHTML = setPane();
    if (had && $(had)) focus($(had));
    else if (!cur || !document.contains(cur)) focus($(`[data-set-tab="${setTab}"]`));
  }
  function setPane() {
    if (!boxInfo) { loadInfo(); return `<p class="lede">Loading…</p>`; }
    if (boxInfo.error) return `<p class="lede">${esc(boxInfo.error)}</p>`;
    const b = boxInfo, s = b.settings || {}, sh = b.shield || {}, th = data.theme;
    const pick = (key, v, label) => `<button class="choice" data-set="${key}" data-value="${v}" aria-pressed="${String(s[key]) === v}">${label}</button>`;
    const head = (title, text) => `<h2 class="pane-title">${title}</h2>${text ? `<p class="lede">${text}</p>` : ""}`;
    if (setTab === "network") {
      if (!wifiNets || Date.now() - wifiAt > 60000) scanWifi();
      return head("Wi-Fi and network", b.wired ? "Connected with a cable: the best for video." : b.wifi ? `Connected to <b>${esc(b.wifi)}</b>.` : "Not connected yet.") +
        `<section class="card"><div class="row-head"><h3>Wi-Fi networks</h3><button class="mini" data-wifi-rescan="1">Look again</button></div>
        <div id="wifi" class="wifi-list">${wifiRows(wifiNets, b.wifi)}</div></section>
        <section class="card"><h3>This box on the network</h3><dl class="facts"><dt>Address</dt><dd>${esc(b.address || "?")}</dd>
          <dt>Name</dt><dd>${esc(s.boot_text || "Sofa Box")}</dd></dl></section>`;
    }
    if (setTab === "remotes") return head("Remotes and Bluetooth", "Your phone, a Bluetooth remote, a game controller, a keyboard, speakers or headphones.") +
      `<section class="card"><div class="remote-row"><div id="phoneBox" class="phone-mini">${phoneBox()}</div>
        <div><p><b>Your phone is a remote:</b> scan the code with its camera (iPhone or Android). It works the box like a remote, types into it, and has a touchpad. Add it to the phone's Home Screen to keep it handy.</p>
        ${secureLine()}</div></div></section>
      <section class="card"><h3>Bluetooth</h3><p>Put it in pairing mode (a Fire TV remote: hold Home for 10 seconds), then <b>Look for devices</b>. A 2.4 GHz keyboard and mouse work as soon as their USB dongle is in.</p>
        <div class="choices"><button class="btn primary" data-bt-look="1">Look for devices</button><button class="btn" data-action="tv-on">Turn the TV on</button><button class="mini" data-phones-forget="1">Forget phones</button></div>
        <div id="btList" class="bt-list">${btList()}</div></section>`;
    if (setTab === "sofa") return head("Sofa", "Where Sofa plays from. Open one, make it the one Sofa opens with, or remove it.") +
      `<section class="card" id="sofaCard"><div class="choices"><button class="choice" data-ask="0" aria-pressed="${!!(servers && !servers.ask)}">Open the same one</button><button class="choice" data-ask="1" aria-pressed="${!!(servers && servers.ask)}">Ask each time</button></div>
        ${servers && !servers.error ? `<div class="srv-list">${(servers.servers || []).map(x => `<div class="srv-row">${serverBtn(x)}
          <button class="mini" data-default="${esc(x.id)}"${servers.default === x.id && !servers.ask ? " disabled" : ""}>Opens with this</button>
          ${x.where === "box" ? "" : `<button class="mini" data-forget-server="${esc(x.id)}">Remove</button>`}</div>`).join("") || `<p>None yet.</p>`}</div>` : `<p>Loading…</p>`}
        <div class="choices" style="margin-top:.8rem"><button class="btn" data-go="#/sofa">${icon("#i-plus")}Add a server</button></div></section>
      ${thisBoxCard()}`;
    if (setTab === "picture") return head("Picture and sound", (b.learned_720 && s.quality === "auto" ? "Videos come as 720p: 1080p dropped frames here. " : "") + "Sofa sends what the box plays smoothly.") +
      `<section class="card"><h3>Picture</h3><div class="choices">${pick("quality", "auto", "Automatic")}${pick("quality", "1080", "1080p")}${pick("quality", "720", "720p")}</div></section>
      <section class="card"><h3>Sound</h3><div class="choices">${pick("audio", "auto", "TV or soundbar")}${pick("audio", "passthrough", "AV receiver (surround)")}</div>
        <div class="choices" style="margin-top:.6rem">${pick("boot_sound", "on", "Sound at start: on")}${pick("boot_sound", "off", "Off")}</div></section>
      <section class="card"><h3>Performance: ${b.light ? "light" : "full"}</h3><p>${s.performance === "auto" ? (b.learned_lite ? "The box chose it: the full look answered the remote slowly here. " : "Chosen for this board. ") : ""}The light look leaves out the effects that are slow to draw, and keeps fewer apps open. Automatic measures how quickly the box answers and picks the light look when it needs to.</p>
        <div class="choices">${pick("performance", "auto", "Automatic")}${pick("performance", "light", "Light")}${pick("performance", "full", "Full")}</div></section>`;
    if (setTab === "home") return head("Home screen", "Its look, the weather, and which apps it shows.") +
      `<section class="card"><h3>Look</h3><div class="themes">${THEMES.map(t => `<button class="theme" data-theme-pick="${t[0]}" aria-pressed="${th === t[0]}" style="--sw-bg:${t[2]};--sw-a:${t[3]};--sw-a2:${t[4]}"><i></i><b>${t[1]}</b></button>`).join("")}</div></section>
      <section class="card"><h3>Weather</h3><p>${s.weather === "off" ? "Off: Home shows no weather." : b.weather_place
          ? `For <b>${esc(b.weather_place.name)}</b>${b.weather_picked ? "" : " (the city of the box's time zone)"}, from MET Norway, every half hour.` : "Pick a town or city for it."}</p>
        <div class="choices">${pick("weather", "on", "On")}${pick("weather", "off", "Off")}<span class="gap"></span>${pick("weather_units", "auto", "°C or °F: automatic")}${pick("weather_units", "c", "°C")}${pick("weather_units", "f", "°F")}</div>
        <div class="add-site" style="margin-top:.8rem"><input class="field" id="wxPlace" aria-label="A town or city" maxlength="80" placeholder="Another town or city: Miami" spellcheck="false"><button class="btn" data-wx-find="1">Find</button>
          ${b.weather_picked ? `<button class="mini" data-wx-reset="1">The time zone's city</button>` : ""}</div>
        <div class="choices" id="wxFound" style="margin-top:.6rem"></div></section>
      <section class="card"><h3>Apps on Home</h3><p>Hide the ones you don't use, or move them. (Menu on an app on Home does it too.)</p><div class="applist"><ul>${data.apps.map((a, i) => `<li>
        <span class="name">${esc(a.name)}</span><button class="mini" data-move="${esc(a.id)}" data-by="-1"${i ? "" : " disabled"}>←</button>
        <button class="mini" data-move="${esc(a.id)}" data-by="1"${i === data.apps.length - 1 ? " disabled" : ""}>→</button>
        <button class="mini" data-hide="${esc(a.id)}">${a.hidden ? "Show" : "Hide"}</button>${a.kind === "web" ? `<button class="mini" data-remove="${esc(a.id)}">Remove</button>` : ""}</li>`).join("")}</ul></div></section>`;
    if (setTab === "shield") return head("Sofa Shield", "Keeps ads and trackers out of every app and the browser.") +
      `<section class="card"><div class="toggle-row"><div><h3>${sh.on ? "On" : "Off"}</h3><p>${sh.on ? (sh.sites || 0).toLocaleString() + " sites kept out." : "Switch it on to keep ads and trackers out."}</p></div>
        <button class="switch" role="switch" aria-checked="${!!sh.wanted}" data-shield="1" aria-label="Sofa Shield"></button></div></section>`;
    if (setTab === "box") return head("This box", "Its name, its clock, and what it is.") +
      `<section class="card"><h3>Its name</h3><p>On the boot screen, and to phones looking for it.</p>
        <div class="add-site"><input class="field" id="boxName" aria-label="The box's name" maxlength="30" value="${esc(s.boot_text || "")}" placeholder="Living room"><button class="btn" data-save-name="1">Save</button></div></section>
      <section class="card"><h3>Time zone: ${esc(((setup || {}).timezone || "UTC").replace(/_/g, " "))}</h3>
        <div class="choices zones">${ZONES.map(z => `<button class="choice" data-tz="${z}" aria-pressed="${z === (setup || {}).timezone}">${esc(z.split("/").pop().replace(/_/g, " "))}</button>`).join("")}</div></section>
      <section class="card"><h3>About</h3><dl class="facts"><dt>Model</dt><dd>${esc(b.model)}</dd><dt>Memory</dt><dd>${b.memory ? Math.round(b.memory / 1048576) + " MB" : "?"}</dd>
        <dt>Picture</dt><dd>${b.board && b.board.tv_height ? "TV at " + b.board.tv_height + "p · " : ""}videos up to ${b.max_height}p${b.max_height >= 2160 ? " (4K)" : ""}</dd>
        <dt>Temperature</dt><dd>${b.temperature != null ? b.temperature + " °C" : "?"}</dd><dt>Software</dt><dd>Sofa Box OS ${esc(b.version)}</dd></dl>
        <div class="choices" style="margin-top:1rem"><button class="btn" data-action="restart">Restart Sofa Box</button><button class="btn" data-action="reboot">Restart the box</button>
        <button class="btn" data-go="#/welcome">Setup steps again</button></div></section>`;
    if (setTab === "software") return head("Software", `This is <b>Sofa Box OS ${esc(b.version)}</b>.`) +
      `<section class="card">${b.newest ? `<p class="update-ready"><b>Sofa Box OS ${esc(b.newest)} is ready.</b> Update the box to get it.</p>` : ""}
        <p>The newest one comes from GitHub; the box restarts by itself when it's done.</p>
        <div class="choices"><button class="btn${b.newest ? " primary" : ""}" data-action="update">Update the box</button></div></section>
      <section class="card"><h3>Reset to how it came</h3><p>Your apps, sign-ins, Wi-Fi, Bluetooth devices and the files in Downloads, Videos, Music and Pictures go,
        and it starts at the setup steps (for a new owner, or a fresh start).</p><div class="choices"><button class="btn danger" data-action="factory-reset">Reset to how it came</button></div></section>`;
    return head("Help", "Something not working?") +
      `<section class="card"><p><b>Send a report</b> sends the Sofa Box team what the box checks and what it has logged since it started,
        so we can see what went wrong. No titles, passwords or codes are in it. Send it before you restart the box: a restart clears the logs. (Your phone's remote has it too.)</p>
        <div class="choices"><button class="btn primary" data-action="send-report">Send a report</button></div><p class="small" id="reportNo">${lastReport ? "Last report: number <b>" + esc(lastReport) + "</b>." : ""}</p></section>`;
  }

  // ---- Wi-Fi: one list (Settings and the setup's Internet step), and joining from it: the password typed with the remote
  // on the TV's own keyboard, and how the joining goes, right there (the agent joins after answering; it takes a while).
  async function scanWifi() {
    wifiAt = Date.now();
    try { const r = await api("/box/api/action/wifi-scan", {}); wifiNets = r.networks || []; } catch (e) { wifiNets = wifiNets || []; }
    const el = $("#wifi");
    if (el) { const had = cur && el.contains(cur) ? keyOf(cur) : null; el.innerHTML = wifiRows(wifiNets, (boxInfo || {}).wifi); if (had && $(had)) focus($(had)); }
  }
  function wifiRows(nets, on) {
    if (!nets) return `<p class="small looking"><i class="spin"></i>Looking for Wi-Fi…</p>`;
    if (!nets.length) return `<p class="small">No Wi-Fi found. <b>Look again</b>, or plug in a network cable.</p>`;
    const list = nets.slice().sort((x, y) => (y.ssid === on) - (x.ssid === on) || y.signal - x.signal).slice(0, 14);
    return list.map(w => `<button class="wifi-row${w.ssid === on ? " on" : ""}" data-wifi-pick="${esc(w.ssid)}" data-secure="${w.secure ? 1 : 0}">
      <span class="bars b${Math.max(1, Math.min(4, Math.ceil(w.signal / 25)))}"><i></i><i></i><i></i><i></i></span><b>${esc(w.ssid)}</b>
      ${w.ssid === on ? `<i class="pill">Connected</i>` : w.secure ? `<small class="lock" aria-label="password">🔒</small>` : `<small>Open</small>`}</button>`).join("");
  }
  function joinWifi(ssid, secure) {
    if ((boxInfo || {}).wifi === ssid && location.hash.startsWith("#/settings")) return toast("The box is on " + ssid + " already.");
    sheet(`<h3>Join ${esc(ssid)}</h3>${secure ? `<div class="kb-field"><input class="field kb-target" id="kbText" type="password" autocomplete="off" spellcheck="false" placeholder="Its password">
        <button class="mini" data-kb="show">Show</button></div>${kbHtml()}` : `<p class="sheet-note">An open network: no password.</p>`}
      <p class="small kb-msg" id="kbMsg" role="status"></p>
      <div class="sheet-row"><button class="btn primary" data-sheet="join">Join</button><button class="btn" data-sheet="close">Cancel</button></div>`, async a => {
      if (a !== "join") return closeSheet();
      const msg = $("#kbMsg"), btn = $(".sheet [data-sheet='join']"), pw = ($("#kbText") || {}).value || "";
      if (secure && pw.length < 8) { msg.textContent = "A Wi-Fi password has at least 8 characters."; return; }
      btn.disabled = true; msg.innerHTML = `<i class="spin"></i> Joining ${esc(ssid)}… up to a minute.`;
      let r;
      try { r = await api("/box/api/action/wifi-connect", { ssid, password: pw }); } catch (e) { r = { ok: false, message: e.message }; }
      const end = Date.now() + 90000;
      while (r.ok && r.pending && Date.now() < end) {          // how it goes: the agent's answer comes before the joining
        await new Promise(res => setTimeout(res, 1500));
        const j = ((await loadSetup()) || {}).network ? setup.network.joining : null;
        if (j && j.ssid === ssid && j.state !== "joining") r = { ok: j.state === "joined", message: j.message };
      }
      if (!$(".sheet-back")) return;
      if (r.ok && !r.pending) {
        msg.innerHTML = `<b class="okay">✓ ${esc(r.message || "Connected.")}</b>`;
        boxInfo = null; wifiNets = null;
        setTimeout(() => { closeSheet(); if (location.hash.startsWith("#/settings")) loadInfo(); else render(true); }, 1400);
        return;
      }
      btn.disabled = false;
      msg.innerHTML = `<b class="bad">${esc(r.pending ? "It's taking longer than it should. Look again in a moment." : r.message || "That didn't work.")}</b>`;
      if ($(".sheet .kb-key")) focus($(".sheet [data-kb='q']") || $(".sheet .kb-key"));
    });
    if (secure) focus($(".sheet [data-kb='q']"));
  }

  // ---- the TV's own keyboard: typing with the remote (or a controller), in any field on the box's screens. OK on a
  // field opens it; a real keyboard types as before. Letters, numbers, and the symbols passwords use.
  const KB_ROWS = ["1234567890", "qwertyuiop", "asdfghjkl@", "zxcvbnm.-_"];
  const KB_SYMS = ["1234567890", "!@#$%^&*()", "-_=+[]{};:", "'\",.<>/?~`"];
  let kbShift = false, kbSym = false;
  function kbHtml() {
    kbShift = false; kbSym = false;
    return `<div class="kb" role="group" aria-label="Keyboard">${KB_ROWS.map(r => `<div class="kb-row">${[...r].map(c => `<button class="kb-key" data-kb="${esc(c)}">${esc(c)}</button>`).join("")}</div>`).join("")}
      <div class="kb-row"><button class="kb-key wide" data-kb="shift">⇧ ABC</button><button class="kb-key wide" data-kb="sym">#+=</button>
        <button class="kb-key space" data-kb="space">Space</button><button class="kb-key wide" data-kb="bksp">⌫ Delete</button></div></div>`;
  }
  function kbLabels() {
    const rows = kbSym ? KB_SYMS : KB_ROWS;
    $$(".kb .kb-row").slice(0, 4).forEach((row, i) => [...row.children].forEach((b, j) => {
      const c = rows[i][j], ch = kbShift && !kbSym ? c.toUpperCase() : c;
      b.dataset.kb = ch; b.textContent = ch;
    }));
    const sh = $(".kb [data-kb='shift']"); if (sh) sh.classList.toggle("on", kbShift);
    const sy = $(".kb [data-kb='sym']"); if (sy) { sy.classList.toggle("on", kbSym); sy.textContent = kbSym ? "ABC" : "#+="; }
  }
  function kbPress(k) {
    const f = $(".sheet .kb-target"); if (!f) return;
    if (k === "shift") { kbShift = !kbShift; return kbLabels(); }
    if (k === "sym") { kbSym = !kbSym; kbShift = false; return kbLabels(); }
    if (k === "show") { f.type = f.type === "password" ? "text" : "password"; const b = $(".sheet [data-kb='show']"); if (b) b.textContent = f.type === "password" ? "Show" : "Hide"; return; }
    if (k === "bksp") f.value = f.value.slice(0, -1);
    else if (f.value.length < (+f.maxLength > 0 ? +f.maxLength : 128)) f.value += k === "space" ? " " : k;
    if (kbShift && k.length === 1) { kbShift = false; kbLabels(); }
  }
  function typeSheet(input) {                  // a field on a page: its keyboard in a sheet, Done puts the text back
    const label = input.getAttribute("aria-label") || input.placeholder || "Type";
    sheet(`<h3>${esc(label.split(":")[0])}</h3><div class="kb-field"><input class="field kb-target" id="kbText" value="${esc(input.value)}" maxlength="${input.maxLength > 0 ? input.maxLength : 200}"
        type="${input.type === "password" ? "password" : "text"}" spellcheck="false" autocomplete="off"></div>${kbHtml()}
      <div class="sheet-row"><button class="btn primary" data-sheet="ok">Done</button><button class="btn" data-sheet="close">Cancel</button></div>`, a => {
      const v = ($("#kbText") || {}).value;
      closeSheet();
      if (a === "ok" && document.contains(input)) { input.value = v; input.dataset.typed = "1"; focus(input);
        if (input.id !== "tbDomain" && input.id !== "tbToken") submit(input); }
    });
    focus($(".sheet [data-kb='q']"));
  }

  // ---- the first start: how you'll work it, the internet, Bluetooth, the box itself, your apps; then Home.
  // A new box may have nothing to press with: the phone remote (a QR code), a Bluetooth remote held in
  // pairing mode (it pairs by itself) or a keyboard's dongle all work from the first screen.
  let step = 0, savedStep = 0, picks = null, setup = null, setupTimer = 0, wifiPick = null;
  const STEPS = ["Hello", "Internet", "Your box", "Apps"];       // (more Bluetooth devices: Settings, or Games, later)
  // The setup's apps: the few most people use, all on one screen (the App Store has the rest)
  const POPULAR = ["netflix", "youtube-tv", "prime-video", "disney-plus", "max", "hulu", "apple-tv", "spotify"];
  const ZONES = ["America/New_York", "America/Chicago", "America/Denver", "America/Phoenix", "America/Los_Angeles", "America/Anchorage",
                 "Pacific/Honolulu", "America/Toronto", "America/Mexico_City", "America/Havana", "America/Puerto_Rico", "America/Bogota",
                 "America/Lima", "America/Sao_Paulo", "America/Argentina/Buenos_Aires", "Europe/London", "Europe/Dublin", "Europe/Madrid",
                 "Europe/Paris", "Europe/Berlin", "Europe/Rome", "Europe/Athens", "Europe/Moscow", "Africa/Lagos", "Africa/Johannesburg",
                 "Asia/Dubai", "Asia/Kolkata", "Asia/Shanghai", "Asia/Tokyo", "Australia/Sydney", "Pacific/Auckland", "UTC"];
  const BT_ICON = { remote: "📺", controller: "🎮", keyboard: "⌨", mouse: "🖱", audio: "🎧", other: "•" };
  function qr(text) {
    if (!window.qrcode || !text) return "";
    const q = window.qrcode(0, "M"); q.addData(text); q.make();
    return q.createSvgTag({ cellSize: 4, margin: 2, scalable: true });
  }
  let setupFails = 0;
  async function loadSetup(scan) {
    try { setup = await api("/box/api/setup" + (scan ? "?scan=1" : "")); setupFails = 0; } catch (e) { setupFails++; /* the agent is restarting */ }
    return setup;
  }
  function setupLive() {                         // the parts that change by themselves, redrawn in place
    clearTimeout(setupTimer);
    if (!location.hash.startsWith("#/welcome") && !location.hash.startsWith("#/settings") && location.hash !== "#/games") return;
    setupTimer = setTimeout(async () => {
      await loadSetup(location.hash.startsWith("#/welcome") && step === 0 || btLooking > Date.now());
      autoStep();
      for (const [id, html] of [["phoneBox", phoneBox()], ["btList", btList()], ["netState", netState()]]) {
        const el = $("#" + id); if (!el || el.dataset.html === html) continue;
        const had = cur && el.contains(cur) ? keyOf(cur) : null;
        el.innerHTML = html; el.dataset.html = html;
        if (had && $(had)) focus($(had));
      }
      setupLive();
    }, 2500);
  }
  function phoneBox() {
    const r = (setup || {}).remote;
    if (!r) return setupFails > 3 ? `<p class="small">The box's helper isn't answering yet. If this stays, restart the box (unplug it for a moment).</p>`
      : `<p class="small looking"><i class="spin"></i>Getting ready…</p>`;
    const hs = r.hotspot;
    const n = (setup || {}).network || {}, sec = (setup || {}).secure || {}, now = Date.now() / 1000;
    const j = n.joining && now - n.joining.at < 600 ? n.joining : null;
    const waiting = text => `<p class="small looking"><i class="spin"></i><span>${text}</span></p>`;
    // joining a home Wi-Fi: the codes for its own Wi-Fi are about to stop working, so none shows. (First: between its
    // own Wi-Fi and yours the box has no address for a moment, which isn't "no network yet, making its own".)
    if (j && j.state === "joining") return codeSteps(2) + waiting(`The box is joining <b>${esc(j.ssid)}</b>: looking for it, then connecting. Up to a minute.`);
    if (!r.url && j && j.state === "joined" && now - j.at < 120)
      return codeSteps(3) + waiting(`Connected to <b>${esc(j.ssid)}</b>. Getting the box's address there… a few seconds.`);
    if (!r.url && j && j.state === "failed" && now - j.at < 120)
      return codeSteps(2) + `<p class="small"><b>${esc(j.message || "That didn't work.")}</b></p>` + waiting("The box's own Wi-Fi is coming back, so your phone can try again…");
    if (!r.url && r.problem) return `<p class="small"><b>The box couldn't make its own Wi-Fi for your phone.</b> It tries again by itself.</p>
      <p class="small">The quickest way on: <b>plug a network cable</b> from your router into the box, and the code to scan shows here.
      Or plug in a USB keyboard and press <b>Start</b>, then choose your Wi-Fi.</p><p class="small">(${esc(r.problem)})</p>`;
    if (!r.url) return `<p class="looking small"><i class="spin"></i>No network yet: in a few seconds the box makes its own Wi-Fi, and a code to scan shows here.</p>`;
    const address = esc(r.url.replace(/^http:\/\//, ""));
    // without a cable or Wi-Fi: one code at a time, each gone once its step is done
    if (hs) return setupCodes(r, hs, n, address, waiting);
    const fresh = j && j.state === "joined" && now - j.at < 600;
    // just joined: the secure (https) code follows within seconds, so not the plain one first and then a swap
    // ("error" too: just after joining, the box's DNS may not be ready, and it tries again in 30 seconds)
    if (fresh && now - j.at < 300 && !/^https:/.test(r.url) && (sec.state === "working" || sec.state === "error"))
      return codeSteps(3) + waiting(now - j.at < 45 ? "Connected. Getting the remote's secure address for your phone… a few seconds."
        : "Connected. The remote's secure address is taking longer than usual: the box keeps trying. (Your Wi-Fi may still be getting the box online.)");
    const open = r.home_at && now - r.home_at < 15;              // a remote open on the home Wi-Fi now
    return (fresh ? codeSteps(3) : "") + qrRow(r.pair_url, `
      <b>${fresh ? (n.from_phone && now - n.from_phone < 900 ? "Last step: scan this with your phone's camera to keep it as the remote"
        : "Scan this to keep your phone as the remote") : "Scan with your phone's camera"}</b><small>${fresh && n.from_phone && now - n.from_phone < 900
        ? "(if the Setup Assistant carried on by itself on your phone, there's nothing to scan)" : `or open <b>${address}</b> and type <b>${esc(r.code)}</b>`}</small>
      ${open ? `<p class="okay small">✓ Your phone is the remote</p>` : waiting("Waiting for your phone to scan this…")}
      ${/^https:/.test(r.url) ? "" : `<p class="small">iPhone says it isn't secure? Settings → Apps → Safari → turn off <b>Not Secure Connection Warning</b>.</p>`}`);
  }
  // A code to scan with what to do beside it (not under it: the setup's first step fits on the TV)
  const qrRow = (text, beside) => `<div class="qr-row"><span class="qr big">${qr(text)}</span><div class="qr-text">${beside}</div></div>`;
  // The phone's way in at the setup, as steps: join the box's Wi-Fi, open the remote, give the box your Wi-Fi, keep
  // the remote (a new code once it's on your Wi-Fi). Each shows only its own code, and says what the box waits for.
  // (the phone's side is the Sofa Setup Assistant: it connects to the box, opens, takes your Wi-Fi, then stays as the remote)
  const CODE_STEPS = ["Connect your phone", "Open the Setup Assistant", "Choose your Wi-Fi", "Keep the remote"];
  let codesShown = null, joinedAt = 0;                      // "wifi" | "remote", shown again on request for a minute
  function codeSteps(at) {
    return `<ol class="code-steps">${CODE_STEPS.map((t, i) => `<li class="${i < at ? "done" : i === at ? "on" : ""}"><em>${i < at ? "✓" : i + 1}</em>${t}</li>`).join("")}</ol>`;
  }
  function setupCodes(r, hs, n, address, waiting) {
    const now = Date.now() / 1000, asked = codesShown && codesShown.until > Date.now() ? codesShown.which : null;
    const remote = n.phone_at && now - n.phone_at < 15;      // a remote open on a phone on the box's Wi-Fi
    const joined = (n.clients || 0) > 0;                      // a phone (or something) on the box's Wi-Fi
    if (!joined) joinedAt = 0; else if (!joinedAt) joinedAt = now;
    const stage = asked || (remote ? "details" : joined ? "remote" : "wifi");
    if (stage === "remote" && !asked && now - joinedAt < 20) return codeSteps(1) + `<p class="okay big">✓ Your phone is on the box's Wi-Fi</p>
      ${waiting("The Setup Assistant opens on your phone by itself: a sheet pops up. A few seconds…")}
      <button class="mini" data-codes="remote">It didn't open? Show the code</button>`;
    if (stage === "wifi") return codeSteps(0) + qrRow(hs.wifi_qr, `
      <b>Scan with your phone's camera: it connects your phone to the box</b><small>(the box's own Wi-Fi, ${esc(hs.ssid)} · password ${esc(hs.password)})</small>
      ${waiting("Waiting for your phone to join…")}`);
    if (stage === "remote") return codeSteps(1) + qrRow(r.pair_url, `
      <b>${joined ? "It didn't open by itself? Scan" : "Scan"} this: the Sofa Setup Assistant opens on your phone</b><small>or open ${address} and type ${esc(r.code)}</small>
      ${waiting("Waiting for the remote to open on your phone…")}<button class="mini" data-codes="wifi">Show the Wi-Fi code again</button>`);
    return codeSteps(2) + `<p class="okay big">✓ The Setup Assistant is open on your phone</p>
      <p class="small">On your phone: pick your home Wi-Fi, type its password, <b>Join</b>.</p>
      ${waiting("Waiting for your Wi-Fi details…")}<button class="mini" data-codes="remote">Show the remote's code again</button>`;
  }
  function secureLine() {                // the phone remote over https: through the relay (or the box's own certificate)
    const sec = (setup || {}).secure;
    if (!sec) return "";
    if (sec.relay) {
      const what = { ready: `on, through <b>${esc(sec.where || "the Sofa Box service")}</b>: phones open it from anywhere`,
        working: "connecting to the Sofa Box service…", error: "the Sofa Box service can't be reached now; the box keeps trying, and phones at home use plain http:// meanwhile",
        off: "off" }[sec.state] || "";
      return `<p class="small"><b>Secure phone remote:</b> ${what}. A secure (https) address for the remote, for any phone, at home or away. Your phone's taps and typing pass through the Sofa Box service on their way to the box (nothing's kept), and it still needs the code on the TV.
        <button class="mini" data-secure="${sec.state === "off" ? 1 : 0}">${sec.state === "off" ? "Switch on" : "Switch off"}</button></p>`;
    }
    const what = { ready: `on, at <b>${esc(sec.name || "")}</b>`, working: "getting the box its name and certificate…",
      router: "on, but this router won't let the box's name point at it (\"DNS rebinding protection\"), so the remote stays plain http://",
      error: "the certificate service can't be reached now; the box tries again by itself, and the remote stays plain http:// meanwhile",
      off: "off" }[sec.state] || "";
    return `<p class="small"><b>Secure phone remote:</b> ${what}. It's for phones whose browser only opens secure (https) pages. The box gets its own name and certificate from the Sofa Box certificate service, sending only a random id and its address on this network.
      <button class="mini" data-secure="${sec.state === "off" ? 1 : 0}">${sec.state === "off" ? "Switch on" : "Switch off"}</button></p>`;
  }
  let btLooking = 0;
  function btList() {
    const b = (setup || {}).bluetooth || { devices: [] };
    const rows = b.devices.map(d => `<button class="bt-row${d.paired ? " paired" : ""}" data-bt="${esc(d.mac)}"><span class="bt-ic">${BT_ICON[d.kind] || "•"}</span>
      <span><b>${esc(d.name)}</b><small>${d.state === "pairing" ? "Pairing…" : d.paired ? (d.connected ? "Connected" : "Paired") : d.state === "failed" ? "Didn't pair: put it in pairing mode, then OK" : "OK to pair"}</small></span>
      ${d.paired ? `<i class="pill">✓</i>` : ""}</button>`).join("");
    return (rows || (b.scanning ? "" : `<p class="small">Nothing found yet.</p>`)) + (b.scanning ? `<p class="small looking"><i class="spin"></i>Looking for devices in pairing mode…</p>` : "");
  }
  function netState() {
    const n = (setup || {}).network || {};
    const j = n.joining && Date.now() / 1000 - n.joining.at < 600 ? n.joining : null;   // a home Wi-Fi it was just asked to join
    if (j && j.state === "joining") return `<p class="small looking"><i class="spin"></i><span>Joining <b>${esc(j.ssid)}</b>… It takes up to a minute.
      A phone on the box's own Wi-Fi goes back to yours now: when this says connected, scan the new code here.</span></p>`;
    const failed = j && j.state === "failed" ? `<p class="small"><b>${esc(j.message)}</b> ${n.hotspot ? `The box's own Wi-Fi (${esc(n.hotspot.ssid)}) is back:
      your phone can join it again with code 1 on the first screen, or pick the Wi-Fi again below.` : "Pick it again below."}</p>` : "";
    // just joined: the phone that was on the box's own Wi-Fi needs the box's new address, so the code is right here
    const rescan = j && j.state === "joined" && (setup || {}).remote && setup.remote.url ? `<div class="qr-again">${phoneBox()}
      <small>Your phone again: scan this code (the box is on your Wi-Fi now).</small></div>` : "";
    return failed + (n.wired ? `<p class="okay big">✓ Connected with a cable</p>` : n.wifi ? `<p class="okay big">✓ Connected to ${esc(n.wifi)}</p>${rescan}`
      : n.hotspot ? `<p class="small">On its own Wi-Fi for now (${esc(n.hotspot.ssid)}). Pick your home Wi-Fi below, or on your phone (Wi-Fi tab).</p>` : `<p class="small">Not connected yet.</p>`);
  }
  // The setup goes on by itself once a step is done: the phone has the remote on your Wi-Fi (Hello's four codes), or
  // the box got online at the Internet step. Only when it happens there (not on coming back to a step done already).
  const notYet = {};
  function autoStep() {
    if (!location.hash.startsWith("#/welcome") || data.welcomed !== false || $(".sheet-back") || $(".auto-next")) return;
    const n = (setup || {}).network || {}, r = (setup || {}).remote || {}, now = Date.now() / 1000;
    const online = !!(n.wired || n.wifi);
    // (a phone with the remote on the home network: the box is on it too)
    const done = step === 0 ? !r.hotspot && !!r.home_at && now - r.home_at < 15 : step === 1 ? online : false;
    if (!done) { if (step <= 1) notYet[step] = true; return; }
    if (!notYet[step]) return;
    notYet[step] = false;
    const from = step, body = $(".setup-body");
    if (body) body.insertAdjacentHTML("beforeend", `<p class="okay big auto-next">✓ ${from === 0 ? "Your phone is the remote, and the box is online." : "Online."} Next: your box…</p>`);
    setTimeout(() => { if (location.hash.startsWith("#/welcome") && step === from) { step = 2; render(); } }, 1800);   // (focus: Next)
  }
  function viewWelcome() {
    document.documentElement.classList.add("setup");
    if (data.welcomed === false && step !== savedStep) {           // (kept on the box: a restart goes on from here)
      savedStep = step; api("/box/api/settings", { setup_step: step }).catch(() => {});
    }
    if (!setup) { loadSetup(true).then(() => render(true)); }
    setupLive();
    const steps = `<div class="setup-steps">${STEPS.map((n, i) => `<i class="${i < step ? "done" : i === step ? "on" : ""}"><em>${i < step ? "✓" : i + 1}</em><b>${n}</b></i>`).join("")}</div>`;
    const top = `<div class="setup-top"><span class="setup-brand">${icon("#mark")}<b>Sofa</b><span>Box</span></span>${steps}</div>`;
    const online = !!(setup && setup.network && (setup.network.wired || setup.network.wifi));   // Start skips Internet then
    const nav = (back, next, label) => `<div class="setup-nav">${back ? `<button class="btn" data-step="${step === 2 && online ? 0 : step - 1}">Back</button>` : "<span></span>"}
      <button class="btn primary big" ${next}>${label}</button></div>`;
    if (step === 0) return `<div class="setup view-in">${top}<div class="setup-body hello">
        <div class="hello-head"><h1>Let's set up your Sofa Box.</h1><p>About two minutes. Use whatever's in your hand.</p></div>
        <div class="ways">
          <section class="way phone"><h3>${icon("#i-phone")}With your phone<i class="pill">Easiest</i></h3><div id="phoneBox">${phoneBox()}</div></section>
          <div class="ways-side">
            <section class="way"><h3>${icon("#i-remote")}A remote or controller</h3>
              <p><b>Fire TV remote:</b> hold <b>Home</b> for 10 seconds. <b>Controller:</b> its pairing mode. Either pairs by itself.</p>
              <div id="btList" class="bt-list small-list">${btList()}</div></section>
            <section class="way"><h3>${icon("#i-keyboard")}A keyboard</h3><p>Plug its USB dongle into the box, then press <b>Enter</b>.</p></section>
          </div>
        </div></div>${nav(false, `data-step="${online ? 2 : 1}"`, "Start")}</div>`;
    if (step === 1) {
      const n = (setup || {}).network || {};
      const nets = (n.networks || []).slice(0, 12);
      return `<div class="setup view-in">${top}<div class="setup-body"><h1>Internet</h1>
        <div id="netState">${netState()}</div>
        ${n.wired || n.wifi ? "" : `<div class="wifi-list" id="wifi">${wifiRows(nets.length ? nets : wifiNets, null)}</div>
          <p class="small">Pick yours: its password goes in with the remote, or from your phone (the remote's <b>Keyboard</b> tab).
            <button class="mini" data-wifi-rescan="1">Look again</button></p>`}
        </div>${nav(true, `data-step="2"`, n.wired || n.wifi ? "Next" : "Skip for now")}</div>`;
    }
    if (step === 2) {
      const sz = (setup || {}).timezone || "UTC";
      return `<div class="setup view-in">${top}<div class="setup-body"><h1>Your box</h1>
        <div class="box-grid"><section><h3>Its name</h3><p class="small">On the boot screen, and to phones looking for it.</p>
            <div class="add-site"><input class="field" id="boxName" aria-label="The box's name" maxlength="30" value="${esc((setup || {}).name || "")}" placeholder="Living room"><button class="btn" data-save-name="1">Save</button></div>
          <h3>Time zone</h3><p class="small">${(setup || {}).tz_set ? "Set" + (sz ? ": <b>" + esc(sz.replace(/_/g, " ")) + "</b>" : "") + ". " : ""}${(setup || {}).tz_set ? "" : "Your phone sets it when it connects. Or pick:"}</p>
            <div class="choices zones">${ZONES.map(z => `<button class="choice" data-tz="${z}" aria-pressed="${z === sz}">${esc(z.split("/").pop().replace(/_/g, " "))}</button>`).join("")}</div></section>
          <section><h3>Its look</h3><div class="themes two">${THEMES.map(t => `<button class="theme" data-theme-pick="${t[0]}" aria-pressed="${data.theme === t[0]}" style="--sw-bg:${t[2]};--sw-a:${t[3]};--sw-a2:${t[4]}"><i></i><b>${t[1]}</b></button>`).join("")}</div></section></div>
        </div>${nav(true, `data-step="3"`, "Next")}</div>`;
    }
    if (!storeData) { api("/box/api/store").then(st => { storeData = st; render(true); }).catch(() => {}); return `<div class="setup view-in">${top}<div class="setup-body"><h1>Your apps</h1><p class="lede">Loading…</p></div></div>`; }
    const all = storeData.sections.flatMap(x => x.apps), have = new Set(data.apps.map(a => a.id));
    if (!picks) picks = new Set(all.filter(e => have.has(e.id)).map(e => e.id));
    const list = POPULAR.map(id => all.find(e => e.id === id)).filter(Boolean);
    return `<div class="setup view-in">${top}<div class="setup-body"><h1>What do you watch?</h1>
      <p class="lede">Pick the ones you use: they go on Home, ready to sign in. Sofa and free Live TV are there already; the App Store has many more, any time.</p>
      <div class="pick-grid">${list.map(e => `<button class="tile app pick${picks.has(e.id) ? " on" : ""}" style="--c:${esc(e.color)}" data-pick="${esc(e.id)}" aria-pressed="${picks.has(e.id)}">
        <i class="tick">${icon("#i-check")}</i><span class="ic${e.icon_url ? "" : " mono"}">${e.icon_url ? `<img decoding="async" src="${esc(e.icon_url)}" alt="" onload="sofaIcon(this)">` : esc(e.name.replace(/^the\s+/i, "")[0].toUpperCase())}</span><b>${esc(e.name)}</b></button>`).join("")}</div>
      </div>${nav(true, `data-done="1"`, (n => n ? "Add " + n + " and finish" : "Finish")([...picks].filter(id => !have.has(id)).length))}</div>`;
  }

  // ---------------------------------------------------------------- sheets (menus over the page)
  let sheetHandler = null, sheetReturn = null;
  function sheet(html, handler) {
    closeSheet();
    sheetReturn = cur;
    const back = document.createElement("div"); back.className = "sheet-back";
    back.innerHTML = `<div class="sheet">${html}</div>`;
    back.addEventListener("click", e => { if (e.target === back) closeSheet(); });
    document.body.appendChild(back);
    sheetHandler = handler;
    focus($(".sheet button, .sheet input", back));
  }
  function closeSheet() {
    const s = $(".sheet-back"); if (!s) return false;
    s.remove(); sheetHandler = null;
    if (sheetReturn && document.contains(sheetReturn)) focus(sheetReturn);
    return true;
  }
  function askText(label, value, then) {
    sheet(`<h3>${esc(label)}</h3><div class="kb-field"><input class="field kb-target" id="sheetText" value="${esc(value)}" spellcheck="false" autocomplete="off"></div>${kbHtml()}
      <div class="sheet-row"><button class="btn primary" data-sheet="ok">OK</button><button class="btn" data-sheet="close">Cancel</button></div>`,
      a => { if (a === "ok") then($("#sheetText").value); else closeSheet(); });
    focus($(".sheet [data-kb='q']"));
  }
  function confirmSheet(text, then) {
    sheet(`<h3>${esc(text)}</h3><button class="btn danger" data-sheet="yes">Yes</button><button class="btn" data-sheet="close">No</button>`, a => { if (a === "yes") then(); else closeSheet(); });
  }
  function pickPlace(then) {
    sheet(`<h3>Move to</h3>${(roots || []).filter(r => r.id !== filesAt.root).map(r => `<button class="btn" data-sheet="${esc(r.id)}">${esc(r.name)}</button>`).join("")}<button class="btn" data-sheet="close">Cancel</button>`,
      a => { if (a === "close") closeSheet(); else then(a); });
  }
  function appMenu(id) {
    const a = data.apps.find(x => x.id === id); if (!a) return;
    const i = data.apps.indexOf(a);
    sheet(`<h3>${esc(a.name)}</h3><button class="btn primary" data-sheet="open">Open</button>
      ${i > 0 ? `<button class="btn" data-sheet="left">Move left</button>` : ""}${i < data.apps.length - 1 ? `<button class="btn" data-sheet="right">Move right</button>` : ""}
      <button class="btn" data-sheet="hide">Hide from Home</button>${a.kind === "web" ? `<button class="btn danger" data-sheet="remove">Remove</button>` : ""}
      <button class="btn" data-sheet="close">Cancel</button>`, async act => {
      closeSheet();
      if (act === "open") openApp(a);
      else if (act === "left" || act === "right") await moveApp(id, act === "left" ? -1 : 1);
      else if (act === "hide") await hideApp(id);
      else if (act === "remove") { await api("/box/api/apps/remove", { id }); toast(a.name + " is off Home."); await loadApps(); render(true); }
    });
  }
  async function moveApp(id, by) {
    const ids = data.apps.map(a => a.id), i = ids.indexOf(id), j = i + by;
    if (j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    await api("/box/api/apps/arrange", { order: ids }); await loadApps(); render(true);
    focus($(`[data-app="${CSS.escape(id)}"], [data-move="${CSS.escape(id)}"][data-by="${by}"]`));
  }
  async function hideApp(id) {
    const hidden = data.apps.filter(a => a.hidden).map(a => a.id);
    const now = hidden.includes(id) ? hidden.filter(x => x !== id) : hidden.concat(id);
    await api("/box/api/apps/arrange", { hidden: now }); await loadApps(); render(true);
  }

  // ---------------------------------------------------------------- the remote, the keyboard, the mouse
  let cur = null;
  const focusables = () => {
    const sheetEl = $(".sheet");
    if (sheetEl) return $$("button:not([disabled]), input", sheetEl);
    return $$(".tabs a").concat($$("#view button:not([disabled]), #view input, #view a[href]"));
  };
  function focus(el) {
    if (!el) return;
    const prev = cur;
    if (cur) cur.classList.remove("f");
    cur = el; el.classList.add("f");
    if (el.tagName === "INPUT") el.focus({ preventScroll: true }); else { if (document.activeElement && document.activeElement.tagName === "INPUT") document.activeElement.blur(); el.focus({ preventScroll: true }); }
    reveal(el, prev);
    if (el.dataset.store) storeDetail(el.dataset.store);
    if (el.dataset.setTab) { clearTimeout(setTabTimer); setTabTimer = setTimeout(() => { if (cur === el) showTab(el.dataset.setTab); }, 110); }
  }
  // Scrolling the way a TV's home screen does, smoothly (it's the compositor's work, light even on a Pi 3): a new row
  // comes up under the top bar with its title, the same place every time; along a row, the next tile peeks in;
  // anything else just clears the top bar and the hints at the bottom.
  function reveal(el, prev) {
    const how = { behavior: "smooth" };
    if (el.closest(".sheet, .viewer")) return el.scrollIntoView(Object.assign({ block: "nearest", inline: "nearest" }, how));
    const rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
    const rail = el.closest(".rail");
    if (rail) {
      const r = rail.getBoundingClientRect(), b = el.getBoundingClientRect(), pad = Math.min(r.width * .12, 9 * rem);
      const dx = b.left < r.left + pad ? b.left - r.left - pad : b.right > r.right - pad ? b.right - r.right + pad : 0;
      if (Math.abs(dx) > 1) rail.scrollBy(Object.assign({ left: dx }, how));
    }
    if (!el.closest("#view")) return;
    if (el.closest(".set-nav")) { if (scrollY > 0) window.scrollTo(Object.assign({ top: 0 }, how)); return; }    // (it stays put: sticky)
    const bar = $(".top"), top = (bar && getComputedStyle(bar).display !== "none" ? bar.getBoundingClientRect().bottom : 0) + .6 * rem;
    const hint = $("#hint"), bottom = innerHeight - (hint && getComputedStyle(hint).display !== "none" ? hint.offsetHeight : 0) - .6 * rem;
    if (el.closest(".mast")) {                                                            // Home's top: all the way up
      if (scrollY > 0) window.scrollTo(Object.assign({ top: 0 }, how));
      return;
    }
    if (rail && prev && prev.closest && prev.closest(".rail") === rail) return;          // along the same row
    const title = rail && rail.previousElementSibling && rail.previousElementSibling.classList.contains("row-title") ? rail.previousElementSibling : null;
    const box = (title || rail || el).getBoundingClientRect(), end = (rail || el).getBoundingClientRect().bottom;
    const dy = rail ? box.top - top : box.top < top ? box.top - top : end > bottom ? Math.min(end - bottom, box.top - top) : 0;
    if (Math.abs(dy) > 1) window.scrollBy(Object.assign({ top: dy }, how));
  }
  function move(dx, dy) {
    const list = focusables().filter(e => e.offsetParent !== null);
    if (!cur || !document.contains(cur) || !list.includes(cur)) return focus(list.find(e => e.closest("#view")) || list[0]);
    const a = cur.getBoundingClientRect(), ax = a.left + a.width / 2, ay = a.top + a.height / 2;
    const nearest = among => {
      let best = null, bestScore = Infinity;
      among.forEach(el => {
        if (el === cur) return;
        const b = el.getBoundingClientRect(), bx = b.left + b.width / 2, by = b.top + b.height / 2;
        const along = dx ? (bx - ax) * dx : (by - ay) * dy, across = dx ? Math.abs(by - ay) : Math.abs(bx - ax);
        if (along <= 4) return;
        const score = along + across * 2.4;
        if (score < bestScore) { bestScore = score; best = el; }
      });
      return best;
    };
    // Within the page first: the top bar stays on screen while rows above have scrolled away, and Up from a row
    // means the row above it (the top bar only from the first one)
    const inPage = cur.closest("#view") ? nearest(list.filter(e => e.closest("#view"))) : null;
    let best = inPage || nearest(list);
    if (best && best.closest(".set-nav") && cur.closest("#setPane")) best = $(".set-tab[aria-current='true']") || best;
    if (best) focus(best);
  }
  function back() {
    if ($(".viewer")) { $(".viewer").remove(); return; }
    if (location.hash.startsWith("#/welcome")) { if (step > 0 && !$(".sheet-back")) { step--; render(true); } return; }
    if (closeSheet()) return;
    if (cur && cur.closest("#setPane")) { focus($(".set-tab[aria-current='true']")); return; }
    if (location.hash.startsWith("#/files") && filesAt.path) { filesAt.path = filesAt.path.split("/").slice(0, -1).join("/"); loadFiles(); return; }
    if (location.hash && location.hash !== "#/") { location.hash = "#/"; return; }
  }
  document.addEventListener("keydown", e => {
    const k = e.key, typing = document.activeElement && document.activeElement.tagName === "INPUT", field = typing ? document.activeElement : null;
    const kb = $(".sheet .kb-target");
    if (kb && !typing && !e.ctrlKey && !e.metaKey && !e.altKey && (k.length === 1 || k === "Backspace")) {   // a real keyboard, the TV's open
      e.preventDefault(); return kbPress(k === "Backspace" ? "bksp" : k === " " ? "space" : k);
    }
    if (k === "ArrowLeft" || k === "ArrowRight") { if (typing && field.value && field.dataset.typed) return; e.preventDefault(); move(k === "ArrowRight" ? 1 : -1, 0); }
    else if (k === "ArrowUp" || k === "ArrowDown") { e.preventDefault(); move(0, k === "ArrowDown" ? 1 : -1); }
    else if (k === "Enter" && !typing) { e.preventDefault(); if (cur) cur.click(); }
    else if (k === "Enter" && typing) { e.preventDefault();
      if (!field.dataset.typed && !field.closest(".sheet") && field.type !== "file") typeSheet(field); else submit(field); }
    else if ((k === "Escape" || k === "BrowserBack" || (k === "Backspace" && !typing))) { e.preventDefault(); back(); }
    else if (k === "BrowserHome" || k === "F1") { e.preventDefault(); closeSheet(); location.hash = "#/"; }
    else if ((k === "ContextMenu" || k === "F2") && cur && cur.dataset.app) { e.preventDefault(); appMenu(cur.dataset.app); }
    else if (!typing && k.length === 1 && /\S/.test(k) && !e.ctrlKey && !e.metaKey && !e.altKey && (location.hash === "" || location.hash === "#/")) {
      e.preventDefault(); location.hash = "#/browser"; setTimeout(() => { const a = $("#address"); if (a) { a.value = k; focus(a); } }, 60);   // type to search
    }
  });
  document.addEventListener("input", e => { if (e.target.tagName === "INPUT") e.target.dataset.typed = "1"; });
  document.addEventListener("mouseover", e => { const t = e.target.closest("button, .tabs a, input"); if (t && t !== cur && !t.closest(".sheet-back") === !$(".sheet-back")) { if (cur) cur.classList.remove("f"); cur = t; t.classList.add("f"); if (t.dataset.store) storeDetail(t.dataset.store); } });
  document.addEventListener("contextmenu", e => { const t = e.target.closest("[data-app]"); if (t) { e.preventDefault(); appMenu(t.dataset.app); } });
  function submit(input) {
    if (input.classList.contains("kb-target")) { const ok = $(".sheet [data-sheet='join'], .sheet [data-sheet='ok']"); if (ok) ok.click(); }
    else if (input.id === "address") go(input.value);
    else if (input.id === "siteUrl") $("[data-add-site]").click();
    else if (input.id === "boxName") $("[data-save-name]").click();
    else if (input.id === "wxPlace") $("[data-wx-find]").click();
    else if (input.id === "tbDomain" || input.id === "tbToken") $("[data-tb='open']").click();
    else if (input.id === "sheetText") $("[data-sheet='ok']").click();
  }

  // ---------------------------------------------------------------- what the buttons do
  document.addEventListener("click", async e => {
    const t = e.target.closest("button, a"); if (!t) return;
    if (t.dataset.kb !== undefined) { e.preventDefault(); return kbPress(t.dataset.kb); }
    if (t.dataset.sheet && sheetHandler) { e.preventDefault(); return sheetHandler(t.dataset.sheet); }
    const closeBtn = e.target.closest("[data-close]");
    if (closeBtn) { e.preventDefault(); e.stopPropagation(); await api("/box/api/close", { target: closeBtn.dataset.close }).catch(() => {}); await loadApps(); return render(true); }
    const d = t.dataset;
    try {
      if (d.setTab) { showTab(d.setTab); const f = $("#setPane button:not([disabled]), #setPane input"); if (f) focus(f); }
      else if (d.app) { const a = data.apps.find(x => x.id === d.app) || { id: d.app, kind: "web" }; openApp(a); }
      else if (d.go) location.hash = d.go;
      else if (d.sofaHash) open({ id: "sofa", hash: d.sofaHash });
      else if (d.target) await api("/box/api/front", { target: d.target }).catch(() => open({ id: (data.running.find(r => r.target === d.target) || {}).app || "browser" }));
      else if (d.url) open({ url: d.url });
      else if (d.game) open({ url: location.origin + "/box/games/" + d.game + "/" });
      else if (d.play) { const g = (games.native || []).find(x => x.id === d.play) || { name: d.play };
        await api("/box/api/games", { action: "play", id: d.play });
        toast("Starting " + g.name + "… To come back, hold Home for a second."); }
      else if (d.gameGet) { const g = games.native.find(x => x.id === d.gameGet);
        if (games.job && games.job.state === "working") return toast("One game at a time: the other is on its way.");
        const r = await api("/box/api/games", { action: "install", id: d.gameGet }); games.job = r.job;
        toast("Getting " + g.name + ": a few minutes. You can keep using the box."); render(true); }
      else if (d.gameRemove) { const g = games.native.find(x => x.id === d.gameRemove);
        if (armed !== "game-" + g.id) { armed = "game-" + g.id; t.innerHTML = "Press again to remove " + esc(g.name); return; }
        armed = ""; const r = await api("/box/api/games", { action: "remove", id: g.id }); games.job = r.job; render(true); }
      else if (d.store) { const e2 = storeData.sections.flatMap(s => s.apps).find(x => x.id === d.store);
        if (e2.installed) openApp(data.apps.find(a => a.id === e2.id) || { id: e2.id, kind: "web" }); else await install({ store_id: e2.id }, e2.name); }
      else if (d.install) await install({ store_id: d.install }, d.install);
      else if (d.remove) { await api("/box/api/apps/remove", { id: d.remove }); storeData = null; await loadApps(); toast("Removed from Home."); render(true); }
      else if (d.addSite) { const u = $("#siteUrl").value; if (u.trim()) await install({ url: u }, u); }
      else if (d.root) { filesAt = { root: d.root, path: "" }; loadFiles(); }
      else if (d.crumb !== undefined) { filesAt.path = d.crumb; loadFiles(); }
      else if (d.file) { if (d.kind === "folder" || d.kind === "video" || d.kind === "audio" || d.kind === "image") fileOpen(d.file, d.kind); else fileMenu(d.file, d.kind); }
      else if (d.newfolder) askText("New folder", "", async v => { await api("/box/api/files/folder", { root: filesAt.root, path: filesAt.path, name: v }); closeSheet(); loadFiles(); });
      else if (d.themePick) { await api("/box/api/settings", { theme: d.themePick }); data.theme = d.themePick; applyTheme(d.themePick);
        $$("[data-theme-pick]").forEach(b => b.setAttribute("aria-pressed", b === t)); api("/box/api/action/apply-boot", {}).catch(() => {}); }
      else if (d.saveName) { await api("/box/api/settings", { boot_text: $("#boxName").value }); api("/box/api/action/apply-boot", {}).catch(() => {}); toast("Saved: the boot screen shows it from the next start."); }
      else if (d.set) { boxInfo = Object.assign(boxInfo, await api("/box/api/settings", { [d.set]: d.value })); boxInfo.shield = await api("/box/api/shield");
        if (d.set === "performance") { await loadApps(); toast("The browser takes it fully from the box's next start."); }
        if (d.set.startsWith("weather")) loadWeather();
        refreshPane(); }
      else if (d.wxFind) { const q = ($("#wxPlace") || {}).value || ""; $("#wxFound").innerHTML = `<p class="small">Looking…</p>`;
        const r = await api("/box/api/weather/places?q=" + encodeURIComponent(q)); wxFound = r.places || [];
        $("#wxFound").innerHTML = wxFound.length ? wxFound.map((p, i) => `<button class="choice" data-wx-pick="${i}">${esc(p.name)}<small> ${esc(p.where)}</small></button>`).join("")
          : `<p class="small">${esc(r.message || "Nothing by that name. Try the nearest town or city.")}</p>`; focus($("#wxFound button")); }
      else if (d.wxPick) { const p = wxFound[+d.wxPick]; boxInfo = Object.assign(boxInfo, await api("/box/api/settings", { weather_place: p }));
        toast("The weather is for " + p.name + " now."); loadWeather(); render(true); }
      else if (d.tb) {
        const body = { action: d.tb };
        if (d.tb === "open") { body.domain = ($("#tbDomain") || {}).value || ""; body.token = ($("#tbToken") || {}).value || ""; }
        if (d.tb === "close" && armed !== "tb-close") { armed = "tb-close"; t.textContent = "Press again: home only"; return; }
        armed = "";
        const r = await api("/box/api/thisbox/internet", body); toast(r.message || (r.ok ? "Done." : "That didn't work."));
        setTimeout(loadThisBox, 1500); }
      else if (d.wxReset) { boxInfo = Object.assign(boxInfo, await api("/box/api/settings", { weather_place: null })); loadWeather(); render(true); }
      else if (d.shield) { const on = t.getAttribute("aria-checked") !== "true"; t.setAttribute("aria-checked", on); boxInfo.shield = await api("/box/api/shield", { on });
        toast(on ? "Sofa Shield is on: ads and trackers are kept out." : "Sofa Shield is off."); }
      else if (d.move) await moveApp(d.move, +d.by);
      else if (d.hide) await hideApp(d.hide);
      else if (d.action) await action(d.action, t);
      else if (d.step) {
        step = +d.step; render(true);
        if (step === 1 && setup && !(setup.network.wired || setup.network.wifi) && !(setup.network.networks || []).length) {
          const r = await api("/box/api/action/wifi-scan", {}).catch(() => ({}));
          setup.network.networks = wifiNets = r.networks || []; wifiAt = Date.now(); render(true);
        }
      }
      else if (d.wifiPick) joinWifi(d.wifiPick, d.secure === "1");
      else if (d.codes) { codesShown = { which: d.codes, until: Date.now() + 60000 }; render(true); }
      else if (d.wifiRescan) { wifiNets = null; const el = $("#wifi"); if (el) el.innerHTML = wifiRows(null); await scanWifi();
        if (setup && setup.network) setup.network.networks = wifiNets; if (location.hash.startsWith("#/welcome")) render(true); }
      else if (d.bt) { const dev = ((setup || {}).bluetooth || { devices: [] }).devices.find(x => x.mac === d.bt);
        if (dev && dev.paired) toast(dev.name + " is paired already."); else { await api("/box/api/bt/pair", { mac: d.bt }); toast("Pairing…"); } }
      else if (d.btForget) confirmSheet("Forget this device?", async () => { closeSheet(); await api("/box/api/bt/forget", { mac: d.btForget }); await loadSetup(); render(true); })
      else if (d.btLook) { btLooking = Date.now() + 30000; await loadSetup(true); render(true); toast("Looking for devices in pairing mode…"); }
      else if (d.tz) { const r = await api("/box/api/timezone", { tz: d.tz }); toast("Time zone: " + r.timezone.replace(/_/g, " ")); await loadSetup(); render(true); }
      else if (d.secure !== undefined) { await api("/box/api/settings", { secure_remote: d.secure === "1" }); await loadSetup(); render(true);
        toast(d.secure === "1" ? "Secure phone remote on: it takes a minute." : "Secure phone remote off: phones use http:// again."); }
      else if (d.phonesForget) confirmSheet("Every phone has to scan the code again. Go ahead?", async () => { closeSheet(); await api("/box/api/remote/forget", {}); await loadSetup(); render(true); });
      else if (d.pick) { picks.has(d.pick) ? picks.delete(d.pick) : picks.add(d.pick); t.classList.toggle("on", picks.has(d.pick)); t.setAttribute("aria-pressed", picks.has(d.pick));
        const done = $("[data-done]"); if (done) done.textContent = picks.size ? "Add " + picks.size + " and finish" : "Finish: to Home"; }
      else if (d.done) {
        const have = new Set(data.apps.map(a => a.id)), add = [...(picks || [])].filter(id => !have.has(id));
        t.disabled = true; t.textContent = add.length ? "Adding…" : "Here we go";
        for (const id of add) await api("/box/api/apps/install", { store_id: id }).catch(() => {});
        await api("/box/api/settings", { welcomed: true }); data.welcomed = true; storeData = null; await loadApps();
        document.documentElement.classList.remove("setup"); location.hash = "#/";
        toast((add.length ? (add.length === 1 ? "Your app is on Home. " : add.length + " apps are on Home. ") : "All set. ")
          + "Speakers, headphones or more controllers: Settings → Remotes and Bluetooth, or Games.");
      }
      else if (d.server) {
        if (location.hash.startsWith("#/sofa")) await pickServer(d.server); else await openSofa({ id: d.server });
      }
      else if (d.addFound) { const x = await addServer({ entry: { url: d.addFound, kind: d.kind } }); if (x) await pickServer(x.id); }
      else if (d.featured) { const x = await addServer({ entry: { url: d.featured, featured: true } }); if (x) await pickServer(x.id); }
      else if (d.typeServer) askText(d.typeServer === "internet" ? "Paste the link (a share link works)" : d.typeServer === "other" ? "Its address (Jellyfin, Emby or Plex)" : "Its address: 192.168.1.20",
        "", async v => { try { const x = await addServer({ url: v }); closeSheet(); if (x) await pickServer(x.id); } catch (ex) { toast(ex.message); } });
      else if (d.scan) { servers = null; render(true); await loadServers(true); }
      else if (d.ask !== undefined) { const st = servers || {}; await api("/box/api/sofa/choose", { id: st.default, remember: d.ask === "0" && !!st.default });
        if (d.ask === "0" && !st.default) toast("Pick the one Sofa opens with: Opens with this."); servers = null; await loadServers(); await loadApps(); }
      else if (d.default) { await api("/box/api/sofa/choose", { id: d.default, remember: true }); servers = null; await loadServers(); await loadApps(); toast("Sofa opens with that one now."); }
      else if (d.forgetServer) confirmSheet("Remove this server from the box?", async () => { closeSheet(); await api("/box/api/sofa/remove", { id: d.forgetServer }); servers = null; await loadServers(); await loadApps(); });
      else if (d.disc) { if (d.disc === "data") { location.hash = "#/files"; } else { await api("/box/api/disc/play", {}); } }
      else if (d.drive) { filesAt = { root: d.drive, path: "" }; roots = null; filesData = null; location.hash = "#/files"; }
    } catch (ex) { toast(ex.message); }
  });
  async function install(body, name) {
    const r = await api("/box/api/apps/install", body);
    toast((r.app && r.app.name || name) + " is on Home.");
    storeData = null; await loadApps(); render(true);
  }
  let armed = "", lastReport = "";
  async function action(a, t) {
    if ((a === "restart" || a === "reboot" || a === "choose" || a === "factory-reset" || a === "update" || a === "send-report") && armed !== a) {
      armed = a; t.textContent = a === "factory-reset" ? "Everything goes: press again to reset" : a === "send-report" ? "Press again to send it" : "Press again to be sure"; return;
    }
    armed = "";
    if (a === "wifi-scan") { $("#wifi").innerHTML = `<p class="lede">Looking…</p>`; }
    if (a === "send-report") { t.textContent = "Send a report"; toast("Putting the report together and sending it…", 120000); }
    const r = await api("/box/api/action/" + a, {});
    if (a === "send-report") {
      if (r.ok && r.report) { lastReport = r.report; const n = $("#reportNo"); if (n) n.innerHTML = "Last report: number <b>" + esc(r.report) + "</b>."; }
      toast(r.message || "That didn't work.", 15000); return;
    }
    if (a === "wifi-scan") {
      $("#wifi").innerHTML = r.ok && r.networks.length ? `<div class="choices">${r.networks.map(n => `<button class="choice" data-wifi="${esc(n.ssid)}" data-secure="${n.secure ? 1 : 0}">${esc(n.ssid)} · ${n.signal}%</button>`).join("")}</div>`
        : `<p class="lede">${esc(r.message || "No networks found.")}</p>`;
      focus($("#wifi button"));
      return;
    }
    if (r.go) { location.href = r.go; return; }
    toast(r.message || (r.ok ? "Done." : "That didn't work."));
  }

  // ---------------------------------------------------------------- the router
  const TABS = { "": "home", store: "store", games: "games", files: "files", browser: "browser", settings: "settings", welcome: "", sofa: "home", sleep: "" };
  function render(keep) {
    const name = (location.hash.replace(/^#\/?/, "").split(/[/?]/)[0]) || "";
    const html = name === "store" ? viewStore() : name === "games" ? viewGames() : name === "files" ? viewFiles()
      : name === "browser" ? viewBrowser() : name === "settings" ? viewSettings() : name === "welcome" ? viewWelcome()
      : name === "sofa" ? viewSofa() : name === "sleep" ? viewSleep() : viewHome();
    if (name !== "sleep") document.documentElement.classList.remove("asleep");
    const keepKey = keep && cur && document.contains(cur) ? keyOf(cur) : null;
    if (name !== "welcome") document.documentElement.classList.remove("setup");
    view.innerHTML = html;
    if (keep) $$(".view-in", view).forEach(v => v.classList.remove("view-in"));
    $$(".tabs a").forEach(a => a.setAttribute("aria-current", TABS[name] === a.dataset.tab ? "page" : "false"));
    document.documentElement.dataset.page = name || "home";
    const again = keepKey && $(keepKey);
    focus(again || $(name === "browser" ? "#address" : name === "store" ? "[data-store]" : name === "sofa" ? "#view .srv, #view .mini"
      : name === "welcome" ? "#view .btn.primary, #view .tile" : name === "settings" ? ".set-tab[aria-current='true']"
      : "#view .mast .btn, #view .tile, #view button, #view input") || $(".tabs a"));
    hint(name === "files" ? [["OK", "Open or play"], ["Menu", "Rename, move, delete"], ["Back", "Up a folder"]]
      : name === "sofa" ? [["OK", "Use this one"], ["Back", "Home screen"]]
      : name === "browser" ? [["OK", "Go"], ["Menu", "on a site: the Sofa bar"], ["Home", "Back here from any app"]]
      : name === "" ? [["OK", "Open"], ["Menu", "Move, hide or remove an app"], ["Home", "Back here from any app"], ["Type", "to search the web"]]
      : [["OK", "Choose"], ["Back", "Home screen"]]);
  }
  function keyOf(el) {
    for (const a of ["app", "store", "game", "play", "gameGet", "gameRemove", "file", "root", "set", "themePick", "move", "hide", "action", "target", "go", "url", "server", "pick", "addFound", "drive", "disc", "default", "forgetServer", "ask", "bt", "wifiPick", "tz", "step", "btLook", "setTab", "wifiRescan", "kb"]) {
      if (el.dataset[a] !== undefined) {
        const attr = "data-" + a.replace(/[A-Z]/g, c => "-" + c.toLowerCase());
        return `[${attr}="${CSS.escape(el.dataset[a])}"]` + (el.dataset.by ? `[data-by="${el.dataset.by}"]` : "") + (el.dataset.value ? `[data-value="${el.dataset.value}"]` : "");
      }
    }
    return el.id ? "#" + el.id : null;
  }
  window.addEventListener("hashchange", () => { closeSheet(); if (location.hash.startsWith("#/sofa")) servers = null; render(); });
  setInterval(async () => {                    // drives and discs come and go: Home shows them
    if (document.hidden || $(".sheet-back")) return;
    const n = data.devices && data.devices.n;
    await loadApps();
    if (data.devices.n !== n && (!location.hash || location.hash === "#/")) render(true);
  }, 5000);

  // Back on Home (the agent brings this tab forward): fresh lists of apps and what's open.
  let lastRefresh = 0;
  document.addEventListener("visibilitychange", async () => {
    if (document.hidden || Date.now() - lastRefresh < 1500) return;
    lastRefresh = Date.now();
    opening(null);
    await loadApps(); await loadSofa();
    if (!$(".sheet-back")) render(true);
  });

  // ---------------------------------------------------------------- the opening
  function chime() {                    // the box's sound as it starts: four soft rising notes (Settings → Picture and sound)
    try {
      const ac = new (window.AudioContext || window.webkitAudioContext)(), t = ac.currentTime + 0.05;
      [523.25, 659.25, 783.99, 1046.5].forEach((f, i) => {
        const o = ac.createOscillator(), g = ac.createGain(), at = t + i * 0.13;
        o.type = "triangle"; o.frequency.value = f;
        g.gain.setValueAtTime(0, at); g.gain.linearRampToValueAtTime(0.16, at + 0.02); g.gain.exponentialRampToValueAtTime(0.0001, at + 0.9);
        o.connect(g); g.connect(ac.destination); o.start(at); o.stop(at + 1);
      });
      setTimeout(() => ac.close(), 2200);
    } catch (e) { /* no sound: the box starts all the same */ }
  }
  async function intro() {
    const el = $("#intro");
    let seen = false;
    try { seen = sessionStorage.getItem("sofaBoxIntro"); sessionStorage.setItem("sofaBoxIntro", "1"); } catch (e) {}
    if (seen) { el.remove(); return; }
    if (data.boot_sound !== "off") chime();
    const lines = document.documentElement.dataset.theme === "terminal"
      ? ["> mount /media … ok", "> sofa-box-agent … up", "> shield: hosts loaded", "> handshake sofa … ok", "> launching home_"]
      : document.documentElement.dataset.theme === "pirate" ? ["Raising the flag…", "Charting the apps…", "All hands on deck."]
      : ["Waking up…", "Finding Sofa…", "Loading your apps…"];
    for (const l of lines) { $("#introTick").textContent = l; await new Promise(r => setTimeout(r, 320)); }
    el.classList.add("gone"); setTimeout(() => el.remove(), 800);
  }

  async function start() {
    try { history.scrollRestoration = "manual"; } catch (e) {}       // (a TV app: each page from its top, not where it was)
    await loadApps();
    const introDone = intro();
    loadWeather();
    api("/box/api/games").then(g => { games = g; if (!location.hash || location.hash === "#/" || location.hash === "#/games") render(true); }).catch(() => {});
    await loadSofa();
    if (data.welcomed === false && !location.hash) { location.hash = "#/welcome"; step = savedStep = data.setup_step || 0; }
    render();
    await introDone;
    const shieldEl = $("#shield");
    api("/box/api/shield").then(s => { if (s.on) { shieldEl.hidden = false; $("b", shieldEl).textContent = s.sites > 999 ? Math.round(s.sites / 1000) + "k" : s.sites; shieldEl.title = "Sofa Shield: " + s.sites + " sites blocked"; } }).catch(() => {});
  }
  start();
})();
