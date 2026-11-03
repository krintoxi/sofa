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
  function tick() {
    const d = new Date();
    $("#clock").textContent = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
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
  async function open(body) {
    try {
      const r = await api("/box/api/open", body);
      if (r.url) window.open(r.url, "_blank");             // a preview on a computer: a tab of its own
    } catch (e) { toast(e.message); }
  }
  async function openSofa(body) {
    // Sofa on this box starts the first time it's opened (up to a minute on a small board): say so, not a still screen
    let waited = false;
    const slow = setTimeout(() => { waited = true; toast("Starting Sofa… the first time takes up to a minute.", 60000); }, 1200);
    try {
      const r = await api("/box/api/sofa/open", body || {});
      clearTimeout(slow); if (waited) untoast();
      if (r.ask) { location.hash = "#/sofa" + (body && body.hash ? "?then=" + encodeURIComponent(body.hash) : ""); return; }
      if (r.url) window.open(r.url, "_blank");
    } catch (e) { clearTimeout(slow); toast(e.message); }
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
  function appIcon(a) {
    if (a.icon_url) return `<img src="${esc(a.icon_url)}" alt="" loading="lazy" onload="if(this.naturalWidth&&this.naturalWidth<64)this.parentNode.classList.add('tiny')" onerror="this.parentNode.classList.add('mono');this.replaceWith(document.createTextNode('${esc((a.name || "?")[0])}'))">`;
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
  function spotlight(watch) {
    const s = sofa || {}, first = s.items && s.items[0];
    if (first) return `<section class="hero">${first.backdrop ? `<img class="hero-bg" src="${esc(artSrc(first.backdrop, 1280))}" alt="" onerror="this.remove()">` : ""}
        <span class="kicker">Continue watching · ${esc(s.name || "Sofa")}</span><h2>${esc(first.title)}</h2><p>${esc(first.sub)}</p>
        <div class="bar"><i style="width:${first.pct}%"></i></div>
        <div class="row-actions"><button class="btn primary" data-sofa-hash="${esc(first.hash)}">${icon("#i-play")}Resume</button>
        <button class="btn" data-app="sofa">Open Sofa</button></div></section>`;
    // Nothing to resume: the box itself, with what's on it to watch
    const picks = watch.filter(a => a.kind !== "builtin").slice(0, 5);
    const head = s.found && s.signedIn ? "Welcome back" + (s.user ? ", " + esc(s.user) : "") : s.found ? "Sign in to " + esc(s.name || "Sofa") : "What's on tonight?";
    const sub = s.found && s.signedIn ? "Pick something in Sofa, or open an app." : s.found ? "Open Sofa and sign in with your phone."
      : data.servers ? "Sofa, Live TV and your apps are all here." : "Open Sofa to pick where it plays from, or watch free Live TV straight away.";
    return `<section class="hero spot"><div class="spot-logo">${icon("#mark")}</div>
      <span class="kicker">${s.found ? esc(s.name || "Sofa") : "Your Sofa Box"}</span><h2>${head}</h2><p>${sub}</p>
      <div class="row-actions"><button class="btn primary" data-app="sofa">${icon("#i-sofa")}Open Sofa</button><button class="btn" data-app="live">${icon("#i-live")}Live TV</button>
        ${picks.length ? "" : `<button class="btn" data-go="#/store">${icon("#i-store")}Get your apps</button>`}</div>
      ${picks.length ? `<div class="spot-apps">${picks.map(a => `<button class="mini-app" style="--c:${esc(a.color || "")}" data-app="${esc(a.id)}" title="${esc(a.name)}"><span class="ic${a.icon_url ? "" : " mono"}">${appIcon(a)}</span></button>`).join("")}
        <button class="mini-app more" data-go="#/store" title="More apps">${icon("#i-plus")}</button></div>` : ""}</section>`;
  }
  function viewHome() {
    const apps = data.apps.filter(a => !a.hidden);
    const watch = apps.filter(a => WATCH.has(a.category)).map(a => Object.assign({ about: ABOUT[a.id] }, a));
    const rest = apps.filter(a => !WATCH.has(a.category));
    const s = sofa || {};
    const running = (data.running || []).filter(r => r.app !== "home");
    return `<div class="home view-in">${spotlight(watch)}
      <h2 class="row-title">Watch</h2><div class="rail watch-row">${watch.map(a => appTile(a, true)).join("")}
        <button class="tile app wide add" data-go="#/store"><span class="ic">${icon("#i-plus")}</span><b>Add apps</b><small>Netflix, YouTube, Prime…</small></button></div>
      ${inputsRow()}
      ${s.items && s.items.length > 1 ? `<h2 class="row-title">Continue watching <small>${esc(s.name || "Sofa")}</small></h2><div class="rail">${s.items.slice(1).map(it => `<button class="tile poster" data-sofa-hash="${esc(it.hash)}">
          <img src="${esc(artSrc(it.art, 480))}" alt="" loading="lazy" onerror="this.style.visibility='hidden'"><span class="bar"><i style="width:${it.pct}%"></i></span>
          <span class="meta"><b>${esc(it.title)}</b><small>${esc(it.sub)}</small></span></button>`).join("")}</div>` : ""}
      ${running.length ? `<h2 class="row-title">Open now <small>Home brings you back here; they keep playing</small></h2><div class="rail open-now">${running.map(r => {
          const a = data.apps.find(x => x.id === r.app) || { id: r.app, name: r.title || r.app, color: "var(--a)" };
          return `<button class="tile app" style="--c:${esc(a.color || "")}" data-target="${esc(r.target)}"><span class="ic${!a.icon_url && !BUILTIN_ICON[a.id] ? " mono" : ""}">${appIcon(a)}</span>
            <b>${esc(r.title || a.name)}</b><small>${esc(a.name || "")}</small><span class="x" data-close="${esc(r.target)}" title="Close">${icon("#i-close")}</span></button>`; }).join("")}</div>` : ""}
      <h2 class="row-title">Your apps <small>${rest.length}</small></h2><div class="rail">${rest.map(a => appTile(a)).join("")}
        <button class="tile app" data-go="#/store"><span class="ic plus">${icon("#i-plus")}</span><b>Get more</b></button></div>
      ${games && games.games.length ? `<h2 class="row-title">Games</h2><div class="rail">${games.games.map(g => `<button class="tile app" style="--c:${esc(g.color)}" data-game="${esc(g.id)}"><span class="ic emoji">${esc(g.emoji || g.name[0])}</span><b>${esc(g.name)}</b></button>`).join("")}</div>` : ""}
    </div>`;
  }

  function viewStore() {
    if (!storeData) { api("/box/api/store").then(st => { storeData = st; render(true); setTimeout(refreshStoreIcons, 6000); }).catch(e => toast(e.message)); return `<h1 class="page">App Store</h1><p class="lede">Loading…</p>`; }
    const tile = e => `<button class="tile app${e.installed ? " have" : ""}" style="--c:${esc(e.color)}" data-store="${esc(e.id)}">
        ${e.installed ? `<i class="badge">On Home</i>` : e.drm ? `<i class="badge warn" title="Uses DRM">DRM</i>` : ""}<span class="ic${e.icon_url ? "" : " mono"}">${e.icon_url ? `<img src="${esc(e.icon_url)}" alt="" loading="lazy">` : esc(e.name.replace(/^the\s+/i, "")[0].toUpperCase())}</span><b>${esc(e.name)}</b></button>`;
    return `<div class="view-in"><h1 class="page">App Store</h1>
      <p class="lede">Apps open full screen, with no browser around them. Press OK to put one on Home.</p>
      <div class="store-detail" id="storeDetail"></div>
      ${storeData.sections.map(sec => `<h2 class="row-title">${esc(sec.name)}${sec.about ? ` <small>${esc(sec.about)}</small>` : ""}</h2><div class="rail">${sec.apps.map(tile).join("")}</div>`).join("")}
      <h2 class="row-title">Any website</h2>
      <div class="add-site"><input class="field" id="siteUrl" placeholder="Type an address: radio.example.com" spellcheck="false">
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
    box.innerHTML = `<span class="ic${e.icon_url ? "" : " mono"}">${e.icon_url ? `<img src="${esc(e.icon_url)}" alt="">` : esc(e.name[0])}</span><div><h3>${esc(e.name)}</h3><p>${esc(e.about || "")}${e.drm ? ` <span class="warn">Uses DRM: on a Pi 3 the picture may be smaller, and some services may not play.</span>` : ""}</p>
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

  function viewGames() {
    if (!games) return `<h1 class="page">Games</h1><p class="lede">Loading…</p>`;
    return `<div class="view-in"><h1 class="page">Games</h1><p class="lede">Small games that run well on the box. Arrows and OK, or a controller.</p>
      <div class="grid">${games.games.map(g => `<button class="tile" style="--c:${esc(g.color)}" data-game="${esc(g.id)}"><span class="ic">${esc(g.emoji || g.name[0])}</span>
        <b>${esc(g.name)}</b><small>${esc(g.about)}</small></button>`).join("")}</div></div>`;
  }

  function viewBrowser() {
    const web = data.apps.filter(a => a.kind === "web" && !a.hidden).slice(0, 10);
    const quick = [["DuckDuckGo", "https://duckduckgo.com", "#DE5833"], ["Wikipedia", "https://en.wikipedia.org", "#BBBBBB"],
                   ["YouTube", "https://www.youtube.com", "#FF3B30"], ["Reddit", "https://www.reddit.com", "#FF4500"], ["Archive.org", "https://archive.org", "#9BA4B5"]];
    return `<div class="browser-start view-in"><h1 class="page">Browser</h1>
      <input class="field big" id="address" placeholder="Search, or type an address" spellcheck="false" autocomplete="off">
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
      v.innerHTML = `<img src="/box/files/raw?root=${encodeURIComponent(filesAt.root)}&path=${encodeURIComponent(filePath(name))}" alt="">`;
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
    try { boxInfo = await api("/box/api/info"); boxInfo.shield = await api("/box/api/shield"); } catch (e) { boxInfo = { error: e.message }; }
    if (location.hash.startsWith("#/settings") || location.hash.startsWith("#/welcome")) render(true);
  }
  function viewSettings() {
    if (!servers) loadServers();
    if (!setup) loadSetup().then(() => { if (location.hash.startsWith("#/settings")) render(true); });
    setupLive();
    if (!boxInfo) { loadInfo(); return `<h1 class="page">Settings</h1><p class="lede">Loading…</p>`; }
    if (boxInfo.error) return `<h1 class="page">Settings</h1><p class="lede">${esc(boxInfo.error)}</p>`;
    const b = boxInfo, s = b.settings, th = data.theme;
    const pick = (key, v, label) => `<button class="choice" data-set="${key}" data-value="${v}" aria-pressed="${String(s[key]) === v}">${label}</button>`;
    return `<div class="settings view-in"><h1 class="page">Settings</h1>
      <section class="card"><h3>Look</h3><p>The home screen and the boot screen.</p>
        <div class="themes">${THEMES.map(t => `<button class="theme" data-theme-pick="${t[0]}" aria-pressed="${th === t[0]}" style="--sw-bg:${t[2]};--sw-a:${t[3]};--sw-a2:${t[4]}"><i></i><b>${t[1]}</b></button>`).join("")}</div>
        <div class="add-site"><input class="field" id="boxName" maxlength="30" value="${esc(s.boot_text || "")}" placeholder="The box's name (under the logo): Living room"><button class="btn" data-save-name="1">Save</button></div></section>
      <section class="card" id="sofaCard"><div class="toggle-row"><div><h3>Sofa</h3><p>Where Sofa plays from. Open one, make it the one Sofa opens with, or remove it.</p></div>
        <div class="choices"><button class="choice" data-ask="0" aria-pressed="${!!(servers && !servers.ask)}">Open the same one</button><button class="choice" data-ask="1" aria-pressed="${!!(servers && servers.ask)}">Ask each time</button></div></div>
        ${servers && !servers.error ? `<div class="srv-list">${(servers.servers || []).map(x => `<div class="srv-row">${serverBtn(x)}
          <button class="mini" data-default="${esc(x.id)}"${servers.default === x.id && !servers.ask ? " disabled" : ""}>Opens with this</button>
          ${x.where === "box" ? "" : `<button class="mini" data-forget-server="${esc(x.id)}">Remove</button>`}</div>`).join("") || `<p>None yet.</p>`}</div>` : `<p>Loading…</p>`}
        <div class="choices" style="margin-top:.8rem"><button class="btn" data-go="#/sofa">${icon("#i-plus")}Add a server</button></div></section>
      <section class="card"><div class="toggle-row"><div><h3>Sofa Shield</h3><p>Keeps ads and trackers out of every app and the browser${b.shield.on ? ": " + b.shield.sites.toLocaleString() + " sites blocked" : ""}.</p></div>
        <button class="switch" role="switch" aria-checked="${!!b.shield.wanted}" data-shield="1" aria-label="Sofa Shield"></button></div></section>
      <section class="card"><h3>Picture and sound</h3><p>${b.learned_720 && s.quality === "auto" ? "Videos come as 720p: 1080p dropped frames here. " : ""}Sofa sends what the box plays smoothly.</p>
        <div class="choices">${pick("quality", "auto", "Picture: automatic")}${pick("quality", "1080", "1080p")}${pick("quality", "720", "720p")}</div>
        <div class="choices" style="margin-top:.6rem">${pick("audio", "auto", "Sound: TV or soundbar")}${pick("audio", "passthrough", "AV receiver (surround)")}</div>
        <p style="margin-top:1rem">Performance: <b>${b.light ? "light" : "full"}</b>${s.performance === "auto" ? " (chosen for this board)" : ""}. The light look leaves out the effects that are slow to draw, and keeps fewer apps open.</p>
        <div class="choices">${pick("performance", "auto", "Automatic")}${pick("performance", "light", "Light")}${pick("performance", "full", "Full")}</div></section>
      <section class="card"><h3>Network</h3><p>${b.wifi ? "Wi-Fi: <b>" + esc(b.wifi) + "</b>." : "Not on Wi-Fi (a network cable is best for video)."} This box: ${esc(b.address || "")}.</p>
        <div id="wifi"><button class="btn" data-action="wifi-scan">Find Wi-Fi networks</button></div></section>
      <section class="card"><h3>Remotes and Bluetooth</h3>
        <div class="remote-row"><div id="phoneBox" class="phone-mini">${phoneBox()}</div>
          <div><p><b>Your phone is a remote:</b> scan the code with its camera (iPhone or Android). It works the box like a remote, types into it, and has a touchpad. Add it to the phone's Home Screen to keep it handy.</p>
          <p><b>A Bluetooth remote</b> (a Fire TV remote: hold Home for 10 seconds), a game controller, a keyboard, speakers or headphones: put it in pairing mode, then <b>Look for devices</b>. A 2.4 GHz keyboard and mouse work as soon as their USB dongle is in.</p>
          <div class="choices"><button class="btn" data-bt-look="1">Look for devices</button><button class="btn" data-action="tv-on">Turn the TV on</button><button class="mini" data-phones-forget="1">Forget phones</button></div></div></div>
        <div id="btList" class="bt-list">${btList()}</div></section>
      <section class="card"><h3>Time zone</h3><p>The clock on Home: <b>${esc(((setup || {}).timezone || "UTC").replace(/_/g, " "))}</b>.</p>
        <div class="choices zones">${ZONES.map(z => `<button class="choice" data-tz="${z}" aria-pressed="${z === (setup || {}).timezone}">${esc(z.split("/").pop().replace(/_/g, " "))}</button>`).join("")}</div></section>
      <section class="card"><h3>Apps on Home</h3><p>Hide the ones you don't use, or move them.</p><div class="applist"><ul>${data.apps.map((a, i) => `<li>
        <span class="name">${esc(a.name)}</span><button class="mini" data-move="${esc(a.id)}" data-by="-1"${i ? "" : " disabled"}>←</button>
        <button class="mini" data-move="${esc(a.id)}" data-by="1"${i === data.apps.length - 1 ? " disabled" : ""}>→</button>
        <button class="mini" data-hide="${esc(a.id)}">${a.hidden ? "Show" : "Hide"}</button>${a.kind === "web" ? `<button class="mini" data-remove="${esc(a.id)}">Remove</button>` : ""}</li>`).join("")}</ul></div></section>
      <section class="card"><h3>About this box</h3><dl class="facts"><dt>Model</dt><dd>${esc(b.model)}</dd><dt>Memory</dt><dd>${b.memory ? Math.round(b.memory / 1048576) + " MB" : "?"}</dd>
        <dt>Picture</dt><dd>${b.board && b.board.tv_height ? "TV at " + b.board.tv_height + "p · " : ""}videos up to ${b.max_height}p${b.max_height >= 2160 ? " (4K)" : ""}</dd>
        <dt>Temperature</dt><dd>${b.temperature != null ? b.temperature + " °C" : "?"}</dd><dt>Software</dt><dd>Sofa Box OS ${esc(b.version)}</dd></dl>
        <div class="choices" style="margin-top:1rem"><button class="btn" data-action="restart">Restart Sofa Box</button><button class="btn" data-action="reboot">Restart the box</button>
        <button class="btn" data-go="#/welcome">Setup steps again</button></div></section>
      <section class="card"><h3>Software</h3>${b.newest ? `<p class="update-ready"><b>Sofa Box OS ${esc(b.newest)} is ready.</b> Update the box to get it.</p>` : ""}
        <p>This is <b>Sofa Box OS ${esc(b.version)}</b>. The newest one comes from GitHub; the box restarts by itself when it's done. <b>Reset</b> puts it back to how it came:
        your apps, sign-ins, Wi-Fi, Bluetooth devices and the files in Downloads, Videos, Music and Pictures go, and it starts at the setup steps (for a new owner, or a fresh start).</p>
        <div class="choices"><button class="btn${b.newest ? " primary" : ""}" data-action="update">Update the box</button><button class="btn danger" data-action="factory-reset">Reset to how it came</button></div></section></div>`;
  }

  // ---- the first start: how you'll work it, the internet, Bluetooth, the box itself, your apps; then Home.
  // A new box may have nothing to press with: the phone remote (a QR code), a Bluetooth remote held in
  // pairing mode (it pairs by itself) or a keyboard's dongle all work from the first screen.
  let step = 0, picks = null, setup = null, setupTimer = 0, wifiPick = null;
  const STEPS = ["Hello", "Internet", "Bluetooth", "Your box", "Apps"];
  const POPULAR = ["netflix", "youtube-tv", "prime-video", "disney-plus", "max", "hulu", "peacock", "paramount-plus", "apple-tv",
                   "pluto", "tubi", "roku-channel", "crunchyroll", "twitch", "spotify", "pandora", "youtube-music", "pbs-kids"];
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
    if (!location.hash.startsWith("#/welcome") && !location.hash.startsWith("#/settings")) return;
    setupTimer = setTimeout(async () => {
      await loadSetup(location.hash.startsWith("#/welcome") && (step === 0 || step === 2) || btLooking > Date.now());
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
    if (!r.url && r.problem) return `<p class="small"><b>The box couldn't make its own Wi-Fi for your phone.</b> It tries again by itself.</p>
      <p class="small">The quickest way on: <b>plug a network cable</b> from your router into the box, and the code to scan shows here.
      Or plug in a USB keyboard and press <b>Start</b>, then choose your Wi-Fi.</p><p class="small">(${esc(r.problem)})</p>`;
    if (!r.url) return `<p class="looking small"><i class="spin"></i>No network yet: in a few seconds the box makes its own Wi-Fi, and a code to scan shows here.</p>`;
    return hs ? `<div class="qr-steps"><div><span class="qr">${qr(hs.wifi_qr)}</span><b>1. Join its Wi-Fi</b><small>${esc(hs.ssid)} · password ${esc(hs.password)}</small></div>
        <div><span class="qr">${qr(r.pair_url)}</span><b>2. Then scan this</b><small>or open ${esc(r.url.replace(/^http:\/\//, ""))}, code ${esc(r.code)}</small></div></div>`
      : `<span class="qr big">${qr(r.pair_url)}</span><b>Scan with your phone's camera</b><small>or open <b>${esc(r.url.replace(/^http:\/\//, ""))}</b> and type <b>${esc(r.code)}</b></small>
        ${r.phones ? `<small class="okay">✓ ${r.phones === 1 ? "A phone is" : r.phones + " phones are"} connected</small>` : ""}`;
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
    return n.wired ? `<p class="okay big">✓ Connected with a cable</p>` : n.wifi ? `<p class="okay big">✓ Connected to ${esc(n.wifi)}</p>`
      : n.hotspot ? `<p class="small">On its own Wi-Fi for now (${esc(n.hotspot.ssid)}). Pick your home Wi-Fi below, or on your phone (Wi-Fi tab).</p>` : `<p class="small">Not connected yet.</p>`;
  }
  function viewWelcome() {
    document.documentElement.classList.add("setup");
    if (!setup) { loadSetup(true).then(() => render(true)); }
    setupLive();
    const steps = `<div class="setup-steps">${STEPS.map((n, i) => `<i class="${i < step ? "done" : i === step ? "on" : ""}"><em>${i < step ? "✓" : i + 1}</em><b>${n}</b></i>`).join("")}</div>`;
    const top = `<div class="setup-top"><span class="setup-brand">${icon("#mark")}<b>Sofa</b><span>Box</span></span>${steps}</div>`;
    const nav = (back, next, label) => `<div class="setup-nav">${back ? `<button class="btn" data-step="${step - 1}">Back</button>` : "<span></span>"}
      <button class="btn primary big" ${next}>${label}</button></div>`;
    if (step === 0) return `<div class="setup view-in">${top}<div class="setup-body hello">
        <div class="hello-head"><h1>Hello. Let's set up your Sofa Box.</h1><p>It takes two minutes. Use whatever's in your hand:</p></div>
        <div class="ways">
          <section class="way phone"><h3><span>📱</span>Your phone</h3><div id="phoneBox">${phoneBox()}</div></section>
          <section class="way"><h3><span>📺</span>A remote or controller</h3>
            <p><b>Fire TV remote</b> (or another Bluetooth remote): hold its <b>Home</b> button for 10 seconds. It pairs by itself.</p>
            <p><b>Game controller:</b> put it in pairing mode.</p><div id="btList" class="bt-list small-list">${btList()}</div></section>
          <section class="way"><h3><span>⌨</span>Keyboard and mouse</h3><p>Plug the USB dongle into the box. They work straight away.</p>
            <p class="small">Press <b>OK</b> or <b>Enter</b> to start.</p></section>
        </div></div>${nav(false, `data-step="1"`, "Start")}</div>`;
    if (step === 1) {
      const n = (setup || {}).network || {};
      const nets = (n.networks || []).slice(0, 12);
      return `<div class="setup view-in">${top}<div class="setup-body"><h1>Internet</h1>
        <div id="netState">${netState()}</div>
        ${n.wired ? "" : `<div class="wifi-list">${nets.map(w => `<button class="wifi-row${wifiPick === w.ssid ? " on" : ""}" data-wifi-pick="${esc(w.ssid)}" data-secure="${w.secure ? 1 : 0}">
            <span class="bars b${Math.min(4, Math.ceil(w.signal / 25))}"><i></i><i></i><i></i><i></i></span><b>${esc(w.ssid)}</b>${w.secure ? "<small>🔒</small>" : ""}${w.on ? `<i class="pill">✓</i>` : ""}</button>`).join("")
            || `<p class="small">Looking for Wi-Fi…</p>`}</div>
          <div class="wifi-join" ${wifiPick ? "" : "hidden"}><input class="field" id="wifiPass" type="password" placeholder="Password for ${esc(wifiPick || "")}" spellcheck="false">
            <button class="btn primary" data-wifi-go="1">Join</button></div>
          <p class="small">Typing a password with a remote? Use your phone: the <b>Keyboard</b> tab types into the box. <button class="mini" data-wifi-rescan="1">Look again</button></p>`}
        </div>${nav(true, `data-step="2"`, n.wired || n.wifi ? "Next" : "Skip for now")}</div>`;
    }
    if (step === 2) return `<div class="setup view-in">${top}<div class="setup-body"><h1>Bluetooth</h1>
        <p class="lede">Remotes, game controllers, speakers and headphones. Put one in pairing mode: it shows here, and OK pairs it (remotes and controllers pair by themselves).</p>
        <div id="btList" class="bt-list">${btList()}</div></div>${nav(true, `data-step="3"`, "Next")}</div>`;
    if (step === 3) {
      const sz = (setup || {}).timezone || "UTC";
      return `<div class="setup view-in">${top}<div class="setup-body"><h1>Your box</h1>
        <div class="box-grid"><section><h3>Its name</h3><p class="small">On the boot screen, and to phones looking for it.</p>
            <div class="add-site"><input class="field" id="boxName" maxlength="30" value="${esc((setup || {}).name || "")}" placeholder="Living room"><button class="btn" data-save-name="1">Save</button></div>
          <h3>Time zone</h3><p class="small">${(setup || {}).tz_set ? "Set" + (sz ? ": <b>" + esc(sz.replace(/_/g, " ")) + "</b>" : "") + ". " : ""}${(setup || {}).tz_set ? "" : "Your phone sets it when it connects. Or pick:"}</p>
            <div class="choices zones">${ZONES.map(z => `<button class="choice" data-tz="${z}" aria-pressed="${z === sz}">${esc(z.split("/").pop().replace(/_/g, " "))}</button>`).join("")}</div></section>
          <section><h3>Its look</h3><div class="themes two">${THEMES.map(t => `<button class="theme" data-theme-pick="${t[0]}" aria-pressed="${data.theme === t[0]}" style="--sw-bg:${t[2]};--sw-a:${t[3]};--sw-a2:${t[4]}"><i></i><b>${t[1]}</b></button>`).join("")}</div></section></div>
        </div>${nav(true, `data-step="4"`, "Next")}</div>`;
    }
    if (!storeData) { api("/box/api/store").then(st => { storeData = st; render(true); }).catch(() => {}); return `<div class="setup view-in">${top}<div class="setup-body"><h1>Your apps</h1><p class="lede">Loading…</p></div></div>`; }
    const all = storeData.sections.flatMap(x => x.apps), have = new Set(data.apps.map(a => a.id));
    if (!picks) picks = new Set(all.filter(e => have.has(e.id)).map(e => e.id));
    const list = POPULAR.map(id => all.find(e => e.id === id)).filter(Boolean);
    return `<div class="setup view-in">${top}<div class="setup-body"><h1>What do you watch?</h1>
      <p class="lede">Pick your streaming apps: they go on Home, ready to sign in. Sofa and free Live TV are there already. The App Store has more.</p>
      <div class="pick-grid">${list.map(e => `<button class="tile app pick${picks.has(e.id) ? " on" : ""}" style="--c:${esc(e.color)}" data-pick="${esc(e.id)}" aria-pressed="${picks.has(e.id)}">
        <i class="tick">${icon("#i-check")}</i><span class="ic${e.icon_url ? "" : " mono"}">${e.icon_url ? `<img src="${esc(e.icon_url)}" alt="">` : esc(e.name.replace(/^the\s+/i, "")[0].toUpperCase())}</span><b>${esc(e.name)}</b></button>`).join("")}</div>
      </div>${nav(true, `data-done="1"`, picks.size ? "Add " + picks.size + " and finish" : "Finish")}</div>`;
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
    sheet(`<h3>${esc(label)}</h3><input class="field" id="sheetText" value="${esc(value)}" spellcheck="false"><button class="btn primary" data-sheet="ok">OK</button><button class="btn" data-sheet="close">Cancel</button>`,
      a => { if (a === "ok") then($("#sheetText").value); else closeSheet(); });
    const i = $("#sheetText"); if (i) { i.focus(); i.select(); }
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
    if (cur) cur.classList.remove("f");
    cur = el; el.classList.add("f");
    if (el.tagName === "INPUT") el.focus(); else { if (document.activeElement && document.activeElement.tagName === "INPUT") document.activeElement.blur(); el.focus({ preventScroll: true }); }
    el.scrollIntoView({ block: "nearest", inline: "nearest", behavior: document.documentElement.classList.contains("lite") ? "auto" : "smooth" });
    if (el.dataset.store) storeDetail(el.dataset.store);
  }
  function move(dx, dy) {
    const list = focusables().filter(e => e.offsetParent !== null);
    if (!cur || !document.contains(cur) || !list.includes(cur)) return focus(list.find(e => e.closest("#view")) || list[0]);
    const a = cur.getBoundingClientRect(), ax = a.left + a.width / 2, ay = a.top + a.height / 2;
    let best = null, bestScore = Infinity;
    list.forEach(el => {
      if (el === cur) return;
      const b = el.getBoundingClientRect(), bx = b.left + b.width / 2, by = b.top + b.height / 2;
      const along = dx ? (bx - ax) * dx : (by - ay) * dy, across = dx ? Math.abs(by - ay) : Math.abs(bx - ax);
      if (along <= 4) return;
      const score = along + across * 2.4;
      if (score < bestScore) { bestScore = score; best = el; }
    });
    if (best) focus(best);
  }
  function back() {
    if ($(".viewer")) { $(".viewer").remove(); return; }
    if (location.hash.startsWith("#/welcome")) { if (step > 0 && !$(".sheet-back")) { step--; render(true); } return; }
    if (closeSheet()) return;
    if (location.hash.startsWith("#/files") && filesAt.path) { filesAt.path = filesAt.path.split("/").slice(0, -1).join("/"); loadFiles(); return; }
    if (location.hash && location.hash !== "#/") { location.hash = "#/"; return; }
  }
  document.addEventListener("keydown", e => {
    const k = e.key, typing = document.activeElement && document.activeElement.tagName === "INPUT";
    if (k === "ArrowLeft" || k === "ArrowRight") { if (typing && document.activeElement.value) return; e.preventDefault(); move(k === "ArrowRight" ? 1 : -1, 0); }
    else if (k === "ArrowUp" || k === "ArrowDown") { e.preventDefault(); move(0, k === "ArrowDown" ? 1 : -1); }
    else if (k === "Enter" && !typing) { e.preventDefault(); if (cur) cur.click(); }
    else if (k === "Enter" && typing) { e.preventDefault(); submit(document.activeElement); }
    else if ((k === "Escape" || k === "BrowserBack" || (k === "Backspace" && !typing))) { e.preventDefault(); back(); }
    else if (k === "BrowserHome" || k === "F1") { e.preventDefault(); closeSheet(); location.hash = "#/"; }
    else if ((k === "ContextMenu" || k === "F2") && cur && cur.dataset.app) { e.preventDefault(); appMenu(cur.dataset.app); }
    else if (!typing && k.length === 1 && /\S/.test(k) && !e.ctrlKey && !e.metaKey && !e.altKey && (location.hash === "" || location.hash === "#/")) {
      e.preventDefault(); location.hash = "#/browser"; setTimeout(() => { const a = $("#address"); if (a) { a.value = k; focus(a); } }, 60);   // type to search
    }
  });
  document.addEventListener("mouseover", e => { const t = e.target.closest("button, .tabs a, input"); if (t && t !== cur && !t.closest(".sheet-back") === !$(".sheet-back")) { if (cur) cur.classList.remove("f"); cur = t; t.classList.add("f"); if (t.dataset.store) storeDetail(t.dataset.store); } });
  document.addEventListener("contextmenu", e => { const t = e.target.closest("[data-app]"); if (t) { e.preventDefault(); appMenu(t.dataset.app); } });
  function submit(input) {
    if (input.id === "address") go(input.value);
    else if (input.id === "siteUrl") $("[data-add-site]").click();
    else if (input.id === "boxName") $("[data-save-name]").click();
    else if (input.id === "sheetText") $("[data-sheet='ok']").click();
    else if (input.id === "wifiPass") $("[data-wifi-go]").click();
    else if (input.dataset.wifiPass !== undefined) $("[data-wifi-join]").click();
  }

  // ---------------------------------------------------------------- what the buttons do
  document.addEventListener("click", async e => {
    const t = e.target.closest("button, a"); if (!t) return;
    if (t.dataset.sheet && sheetHandler) { e.preventDefault(); return sheetHandler(t.dataset.sheet); }
    const closeBtn = e.target.closest("[data-close]");
    if (closeBtn) { e.preventDefault(); e.stopPropagation(); await api("/box/api/close", { target: closeBtn.dataset.close }).catch(() => {}); await loadApps(); return render(true); }
    const d = t.dataset;
    try {
      if (d.app) { const a = data.apps.find(x => x.id === d.app) || { id: d.app, kind: "web" }; openApp(a); }
      else if (d.go) location.hash = d.go;
      else if (d.sofaHash) open({ id: "sofa", hash: d.sofaHash });
      else if (d.target) await api("/box/api/front", { target: d.target }).catch(() => open({ id: (data.running.find(r => r.target === d.target) || {}).app || "browser" }));
      else if (d.url) open({ url: d.url });
      else if (d.game) open({ url: location.origin + "/box/games/" + d.game + "/" });
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
        render(true); }
      else if (d.shield) { const on = t.getAttribute("aria-checked") !== "true"; t.setAttribute("aria-checked", on); boxInfo.shield = await api("/box/api/shield", { on });
        toast(on ? "Sofa Shield is on: ads and trackers are kept out." : "Sofa Shield is off."); }
      else if (d.move) await moveApp(d.move, +d.by);
      else if (d.hide) await hideApp(d.hide);
      else if (d.action) await action(d.action, t);
      else if (d.wifi) { const pass = `<input class="field" data-wifi-pass="1" type="password" placeholder="Password for ${esc(d.wifi)}">`;
        $("#wifi").innerHTML = `<div class="add-site">${d.secure === "1" ? pass : ""}<button class="btn primary" data-wifi-join="${esc(d.wifi)}">Join ${esc(d.wifi)}</button></div>`;
        focus($("#wifi input, #wifi button")); }
      else if (d.wifiJoin) { toast("Joining " + d.wifiJoin + "…"); const pw = $("[data-wifi-pass]");
        const r = await api("/box/api/action/wifi-connect", { ssid: d.wifiJoin, password: pw ? pw.value : "" }); toast(r.message || (r.ok ? "Connected." : "That didn't work.")); boxInfo = null; loadInfo(); }
      else if (d.step) {
        step = +d.step; render(true);
        if (step === 1 && setup && !(setup.network.wired || setup.network.wifi) && !(setup.network.networks || []).length) {
          const r = await api("/box/api/action/wifi-scan", {}); setup.network.networks = r.networks || []; render(true);
        }
      }
      else if (d.wifiPick) {
        wifiPick = d.wifiPick;
        if (d.secure === "0") { toast("Joining " + wifiPick + "…"); const r = await api("/box/api/action/wifi-connect", { ssid: wifiPick }); toast(r.message); await loadSetup(); }
        render(true); const pw = $("#wifiPass"); if (pw && d.secure !== "0") focus(pw);
      }
      else if (d.wifiGo) { toast("Joining " + wifiPick + "…"); const r = await api("/box/api/action/wifi-connect", { ssid: wifiPick, password: ($("#wifiPass") || {}).value || "" });
        toast(r.message || (r.ok ? "Connected." : "That didn't work.")); if (r.ok) wifiPick = null; await loadSetup(); render(true); }
      else if (d.wifiRescan) { toast("Looking for Wi-Fi…"); const r = await api("/box/api/action/wifi-scan", {}); if (setup) setup.network.networks = r.networks || []; render(true); }
      else if (d.bt) { const dev = ((setup || {}).bluetooth || { devices: [] }).devices.find(x => x.mac === d.bt);
        if (dev && dev.paired) toast(dev.name + " is paired already."); else { await api("/box/api/bt/pair", { mac: d.bt }); toast("Pairing…"); } }
      else if (d.btForget) confirmSheet("Forget this device?", async () => { closeSheet(); await api("/box/api/bt/forget", { mac: d.btForget }); await loadSetup(); render(true); })
      else if (d.btLook) { btLooking = Date.now() + 30000; await loadSetup(true); render(true); toast("Looking for devices in pairing mode…"); }
      else if (d.tz) { const r = await api("/box/api/timezone", { tz: d.tz }); toast("Time zone: " + r.timezone.replace(/_/g, " ")); await loadSetup(); render(true); }
      else if (d.phonesForget) confirmSheet("Every phone has to scan the code again. Go ahead?", async () => { closeSheet(); await api("/box/api/remote/forget", {}); await loadSetup(); render(true); });
      else if (d.pick) { picks.has(d.pick) ? picks.delete(d.pick) : picks.add(d.pick); t.classList.toggle("on", picks.has(d.pick)); t.setAttribute("aria-pressed", picks.has(d.pick));
        const done = $("[data-done]"); if (done) done.textContent = picks.size ? "Add " + picks.size + " and finish" : "Finish: to Home"; }
      else if (d.done) {
        const have = new Set(data.apps.map(a => a.id)), add = [...(picks || [])].filter(id => !have.has(id));
        t.disabled = true; t.textContent = add.length ? "Adding…" : "Here we go";
        for (const id of add) await api("/box/api/apps/install", { store_id: id }).catch(() => {});
        await api("/box/api/settings", { welcomed: true }); data.welcomed = true; storeData = null; await loadApps();
        document.documentElement.classList.remove("setup"); location.hash = "#/";
        if (add.length) toast(add.length === 1 ? "Your app is on Home." : add.length + " apps are on Home.");
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
  let armed = "";
  async function action(a, t) {
    if ((a === "restart" || a === "reboot" || a === "choose" || a === "factory-reset" || a === "update") && armed !== a) {
      armed = a; t.textContent = a === "factory-reset" ? "Everything goes: press again to reset" : "Press again to be sure"; return;
    }
    armed = "";
    if (a === "wifi-scan") { $("#wifi").innerHTML = `<p class="lede">Looking…</p>`; }
    const r = await api("/box/api/action/" + a, {});
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
  const TABS = { "": "home", store: "store", games: "games", files: "files", browser: "browser", settings: "settings", welcome: "", sofa: "home" };
  function render(keep) {
    const name = (location.hash.replace(/^#\/?/, "").split(/[/?]/)[0]) || "";
    const html = name === "store" ? viewStore() : name === "games" ? viewGames() : name === "files" ? viewFiles()
      : name === "browser" ? viewBrowser() : name === "settings" ? viewSettings() : name === "welcome" ? viewWelcome()
      : name === "sofa" ? viewSofa() : viewHome();
    const keepKey = keep && cur && document.contains(cur) ? keyOf(cur) : null;
    if (name !== "welcome") document.documentElement.classList.remove("setup");
    view.innerHTML = html;
    if (keep) $$(".view-in", view).forEach(v => v.classList.remove("view-in"));
    $$(".tabs a").forEach(a => a.setAttribute("aria-current", TABS[name] === a.dataset.tab ? "page" : "false"));
    const again = keepKey && $(keepKey);
    focus(again || $(name === "browser" ? "#address" : name === "store" ? "[data-store]" : name === "sofa" ? "#view .srv, #view .mini"
      : name === "welcome" ? "#view .btn.primary, #view .tile" : "#view .hero .btn, #view .tile, #view button, #view input") || $(".tabs a"));
    hint(name === "files" ? [["OK", "Open or play"], ["Menu", "Rename, move, delete"], ["Back", "Up a folder"]]
      : name === "sofa" ? [["OK", "Use this one"], ["Back", "Home screen"]]
      : name === "browser" ? [["OK", "Go"], ["Menu", "on a site: the Sofa bar"], ["Home", "Back here from any app"]]
      : name === "" ? [["OK", "Open"], ["Menu", "Move, hide or remove an app"], ["Home", "Back here from any app"], ["Type", "to search the web"]]
      : [["OK", "Choose"], ["Back", "Home screen"]]);
  }
  function keyOf(el) {
    for (const a of ["app", "store", "game", "file", "root", "set", "themePick", "move", "hide", "action", "target", "go", "url", "server", "pick", "addFound", "drive", "disc", "default", "forgetServer", "ask", "bt", "wifiPick", "tz", "step", "btLook"]) {
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
    await loadApps(); await loadSofa();
    if (!$(".sheet-back")) render(true);
  });

  // ---------------------------------------------------------------- the opening
  async function intro() {
    const el = $("#intro");
    let seen = false;
    try { seen = sessionStorage.getItem("sofaBoxIntro"); sessionStorage.setItem("sofaBoxIntro", "1"); } catch (e) {}
    if (seen) { el.remove(); return; }
    const lines = document.documentElement.dataset.theme === "terminal"
      ? ["> mount /media … ok", "> sofa-box-agent … up", "> shield: hosts loaded", "> handshake sofa … ok", "> launching home_"]
      : document.documentElement.dataset.theme === "pirate" ? ["Raising the flag…", "Charting the apps…", "All hands on deck."]
      : ["Waking up…", "Finding Sofa…", "Loading your apps…"];
    for (const l of lines) { $("#introTick").textContent = l; await new Promise(r => setTimeout(r, 320)); }
    el.classList.add("gone"); setTimeout(() => el.remove(), 800);
  }

  async function start() {
    await loadApps();
    const opening = intro();
    api("/box/api/games").then(g => { games = g; if (!location.hash || location.hash === "#/" || location.hash === "#/games") render(true); }).catch(() => {});
    await loadSofa();
    if (data.welcomed === false && !location.hash) location.hash = "#/welcome";
    render();
    await opening;
    const shieldEl = $("#shield");
    api("/box/api/shield").then(s => { if (s.on) { shieldEl.hidden = false; $("b", shieldEl).textContent = s.sites > 999 ? Math.round(s.sites / 1000) + "k" : s.sites; shieldEl.title = "Sofa Shield: " + s.sites + " sites blocked"; } }).catch(() => {});
  }
  start();
})();
