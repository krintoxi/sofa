/* Sofa Box home screen: the box's apps, Sofa's "continue watching", the store, games, files, the browser's
   start page and the settings, worked with a TV remote, a game controller, or a keyboard and mouse.
   It runs in the box's first tab (http://127.0.0.1:8091/box/home); the agent opens apps as other tabs. */
(function () {
  "use strict";
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => [...(r || document).querySelectorAll(s)];
  const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const view = $("#view");
  const BUILTIN_ICON = { sofa: "#m-sofa", browser: "#i-browser", store: "#i-store", games: "#i-games", files: "#i-files", settings: "#i-settings" };
  const THEMES = [["street", "Street", "#0D0D10", "#FF2E88", "#E8FF3A"], ["terminal", "Terminal", "#020604", "#39FF88", "#00E0FF"],
                  ["pirate", "Pirate", "#0A1220", "#E6B450", "#C0392B"], ["sofa", "Sofa", "#0A0E1A", "#F4B740", "#3CC8D8"]];
  let data = { apps: [], running: [] }, sofa = null, storeData = null, games = null, boxInfo = null;

  async function api(path, body) {
    const r = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || "That didn't work.");
    return j;
  }
  let toastTimer = 0;
  function toast(text) { const t = $("#toast"); t.textContent = text; t.classList.add("on"); clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove("on"), 2800); }
  const icon = (id, cls) => `<svg${cls ? ` class="${cls}"` : ""}><use href="${id}"/></svg>`;

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
  async function loadApps() {
    try { data = await api("/box/api/apps"); } catch (e) { /* the agent is restarting */ }
    applyTheme(data.theme);
    document.documentElement.classList.toggle("lite", !!data.slow);
    return data;
  }
  const artSrc = (p, w) => {
    if (!p) return "";
    const [path, v] = p.split("?");
    return path.split("/").map((s, i) => i < 3 ? s : encodeURIComponent(s)).join("/") + "?w=" + w + "&r=2" + (v ? "&" + v : "");
  };
  async function loadSofa() {
    if (!data.sofa) return (sofa = { found: false });
    try {
      const s = await (await fetch("/api/session")).json();
      if (!s.user) return (sofa = { found: true, name: s.name, signedIn: false });
      const [lib, prog] = await Promise.all([api("/api/library"), api("/api/progress")]);
      const byId = new Map();
      lib.shows.forEach(sh => sh.seasons.forEach(se => se.episodes.forEach(ep => byId.set(ep.id, {
        title: sh.name, sub: "S" + ep.s + " E" + ep.e + " · " + (ep.title || ""), art: ep.thumb || sh.backdrop || sh.poster,
        backdrop: sh.backdrop || ep.thumb, hash: "#/show/" + encodeURIComponent(sh.id) }))));
      lib.movies.forEach(m => byId.set(m.id, { title: m.title, sub: m.year ? String(m.year) : "", art: m.backdrop || m.poster,
        backdrop: m.backdrop || m.poster, hash: "#/movie/" + encodeURIComponent(m.id) }));
      const items = Object.entries(prog).filter(([id, p]) => byId.has(id) && !p.done && p.t > 30 && p.d && p.t < p.d - 30)
        .sort((a, b) => b[1].at - a[1].at).slice(0, 12).map(([id, p]) => Object.assign({ id, pct: Math.round(100 * p.t / p.d) }, byId.get(id)));
      return (sofa = { found: true, signedIn: true, name: s.name, user: s.user.name, items });
    } catch (e) { return (sofa = { found: false }); }
  }

  // ---------------------------------------------------------------- opening things
  async function open(body) {
    try {
      const r = await api("/box/api/open", body);
      if (r.url) window.open(r.url, "_blank");             // a preview on a computer: a tab of its own
    } catch (e) { toast(e.message); }
  }
  const openApp = (app, hash) => {
    if (app.kind === "builtin" && app.id !== "sofa") { location.hash = app.url.split("#")[1] || "/"; return; }
    open(hash ? { id: app.id, hash } : { id: app.id });
  };

  // ---------------------------------------------------------------- pieces
  function appTile(a, extra) {
    const running = (data.running || []).some(r => r.app === a.id);
    const ic = a.icon_url ? `<img src="${esc(a.icon_url)}" alt="" onerror="this.replaceWith(document.createTextNode('${esc((a.name || "?")[0])}'))">`
      : BUILTIN_ICON[a.id] ? icon(a.id === "sofa" ? "#m-sofa" : BUILTIN_ICON[a.id]) : esc((a.name || "?")[0]);
    return `<button class="tile${a.hidden ? " off" : ""}" style="--c:${esc(a.color || "")}" data-app="${esc(a.id)}"${extra || ""}>
      ${running ? `<i class="dot" title="Open"></i>` : ""}<span class="ic">${ic}</span><b>${esc(a.name)}</b></button>`;
  }
  function hint(parts) {
    $("#hint").innerHTML = parts.map(p => `<span><kbd>${esc(p[0])}</kbd>${esc(p[1])}</span>`).join("");
  }

  // ---------------------------------------------------------------- views
  function viewHome() {
    const apps = data.apps.filter(a => !a.hidden);
    const s = sofa || {};
    const first = s.items && s.items[0];
    const hero = first ? `<section class="hero">${first.backdrop ? `<img class="hero-bg" src="${esc(artSrc(first.backdrop, 1280))}" alt="">` : ""}
        <span class="kicker">Continue watching</span><h2>${esc(first.title)}</h2><p>${esc(first.sub)}</p>
        <div class="bar"><i style="width:${first.pct}%"></i></div>
        <div class="row-actions"><button class="btn primary" data-sofa-hash="${esc(first.hash)}">${icon("#i-play")}Resume</button>
        <button class="btn" data-app="sofa">Open Sofa</button></div></section>`
      : `<section class="hero"><span class="kicker">${s.found ? (s.signedIn ? "Sofa" : "Sofa is here") : "Looking for Sofa"}</span>
        <h2>${s.found ? (s.signedIn ? "Welcome back" + (s.user ? ", " + esc(s.user) : "") : "Sign in to " + esc(s.name || "Sofa")) : "Your Sofa box"}</h2>
        <p>${s.found ? (s.signedIn ? "Pick something in Sofa, or open an app." : "Open Sofa and sign in with your phone.") : "Is the Sofa computer on? The box keeps looking. Your apps work anyway."}</p>
        <div class="row-actions"><button class="btn primary" data-app="sofa">${icon("#m-sofa")}Open Sofa</button><button class="btn" data-go="#/store">${icon("#i-store")}Get apps</button></div></section>`;
    const running = (data.running || []).filter(r => r.app !== "home");
    return `<div class="home view-in">${hero}
      <h2 class="row-title">Apps <small>${apps.length}</small></h2><div class="rail">${apps.map(a => appTile(a)).join("")}
        <button class="tile" data-go="#/store"><span class="ic" style="background:var(--tile);color:var(--a)">+</span><b>Get more</b></button></div>
      ${s.items && s.items.length > 1 ? `<h2 class="row-title">Continue watching</h2><div class="rail">${s.items.slice(1).map(it => `<button class="tile poster" data-sofa-hash="${esc(it.hash)}">
          <img src="${esc(artSrc(it.art, 480))}" alt="" loading="lazy"><span class="bar"><i style="width:${it.pct}%"></i></span>
          <span class="meta"><b>${esc(it.title)}</b><small>${esc(it.sub)}</small></span></button>`).join("")}</div>` : ""}
      ${running.length ? `<h2 class="row-title">Open now <small>Home brings you back here; they keep playing</small></h2><div class="rail open-now">${running.map(r => {
          const a = data.apps.find(x => x.id === r.app) || { id: r.app, name: r.title || r.app, color: "var(--a)" };
          return `<button class="tile" style="--c:${esc(a.color || "")}" data-target="${esc(r.target)}"><span class="ic">${a.icon_url ? `<img src="${esc(a.icon_url)}" alt="">` : BUILTIN_ICON[a.id] ? icon(BUILTIN_ICON[a.id]) : esc((a.name || "?")[0])}</span>
            <b>${esc(r.title || a.name)}</b><small>${esc(a.name || "")}</small><span class="x" data-close="${esc(r.target)}" title="Close">${icon("#i-close")}</span></button>`; }).join("")}</div>` : ""}
      ${games && games.games.length ? `<h2 class="row-title">Games</h2><div class="rail">${games.games.map(g => `<button class="tile" style="--c:${esc(g.color)}" data-game="${esc(g.id)}"><span class="ic">${esc(g.emoji || g.name[0])}</span><b>${esc(g.name)}</b></button>`).join("")}</div>` : ""}
    </div>`;
  }

  function viewStore() {
    if (!storeData) { api("/box/api/store").then(s => { storeData = s; render(); }).catch(e => toast(e.message)); return `<h1 class="page">App Store</h1><p class="lede">Loading…</p>`; }
    return `<div class="view-in"><h1 class="page">App Store</h1>
      <p class="lede">Apps open full screen, with no browser around them. Press OK to put one on the Home screen.</p>
      <div class="store-detail" id="storeDetail"></div>
      ${storeData.sections.map(sec => `<h2 class="row-title">${esc(sec.name)}</h2><div class="rail">${sec.apps.map(e => `<button class="tile" style="--c:${esc(e.color)}" data-store="${esc(e.id)}">
          ${e.installed ? `<i class="badge">On Home</i>` : e.drm ? `<i class="badge warn">DRM</i>` : ""}<span class="ic">${esc(e.name[0])}</span><b>${esc(e.name)}</b></button>`).join("")}</div>`).join("")}
      <h2 class="row-title">Any website</h2>
      <div class="add-site"><input class="field" id="siteUrl" placeholder="Type an address: radio.example.com" spellcheck="false">
        <button class="btn primary" data-add-site="1">Add to Home</button></div></div>`;
  }
  function storeDetail(id) {
    const box = $("#storeDetail"); if (!box || !storeData) return;
    const e = storeData.sections.flatMap(s => s.apps).find(x => x.id === id); if (!e) return;
    box.style.setProperty("--c", e.color);
    box.innerHTML = `<span class="ic">${esc(e.name[0])}</span><div><h3>${esc(e.name)}</h3><p>${esc(e.about || "")}${e.drm ? ` <span class="warn">Needs DRM: on a Pi 3 it may not play.</span>` : ""}</p>
      <p>${esc(e.url.replace(/^https?:\/\//, ""))}</p></div>
      <div>${e.installed ? `<button class="btn primary" data-app="${esc(e.id)}">Open</button> <button class="btn" data-remove="${esc(e.id)}">Remove</button>`
        : `<button class="btn primary" data-install="${esc(e.id)}">Add to Home</button>`}</div>`;
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
    if (!boxInfo) { loadInfo(); return `<h1 class="page">Settings</h1><p class="lede">Loading…</p>`; }
    if (boxInfo.error) return `<h1 class="page">Settings</h1><p class="lede">${esc(boxInfo.error)}</p>`;
    const b = boxInfo, s = b.settings, th = data.theme;
    const pick = (key, v, label) => `<button class="choice" data-set="${key}" data-value="${v}" aria-pressed="${String(s[key]) === v}">${label}</button>`;
    return `<div class="settings view-in"><h1 class="page">Settings</h1>
      <section class="card"><h3>Look</h3><p>The home screen and the boot screen.</p>
        <div class="themes">${THEMES.map(t => `<button class="theme" data-theme-pick="${t[0]}" aria-pressed="${th === t[0]}" style="--sw-bg:${t[2]};--sw-a:${t[3]};--sw-a2:${t[4]}"><i></i><b>${t[1]}</b></button>`).join("")}</div>
        <div class="add-site"><input class="field" id="boxName" maxlength="30" value="${esc(s.boot_text || "")}" placeholder="The box's name (under the logo): Living room"><button class="btn" data-save-name="1">Save</button></div></section>
      <section class="card"><div class="toggle-row"><div><h3>Sofa Shield</h3><p>Keeps ads and trackers out of every app and the browser${b.shield.on ? ": " + b.shield.sites.toLocaleString() + " sites blocked" : ""}.</p></div>
        <button class="switch" role="switch" aria-checked="${!!b.shield.wanted}" data-shield="1" aria-label="Sofa Shield"></button></div></section>
      <section class="card"><h3>Picture and sound</h3><p>${b.learned_720 && s.quality === "auto" ? "Videos come as 720p: 1080p dropped frames here. " : ""}Sofa sends what the box plays smoothly.</p>
        <div class="choices">${pick("quality", "auto", "Picture: automatic")}${pick("quality", "1080", "1080p")}${pick("quality", "720", "720p")}</div>
        <div class="choices" style="margin-top:.6rem">${pick("audio", "auto", "Sound: TV or soundbar")}${pick("audio", "passthrough", "AV receiver (surround)")}</div></section>
      <section class="card"><h3>Network</h3><p>${b.wifi ? "Wi-Fi: <b>" + esc(b.wifi) + "</b>." : "Not on Wi-Fi (a network cable is best for video)."} This box: ${esc(b.address || "")}.</p>
        <div id="wifi"><button class="btn" data-action="wifi-scan">Find Wi-Fi networks</button></div></section>
      <section class="card"><h3>Remotes and controllers</h3><p>${b.controllers.length ? "Paired: " + b.controllers.map(esc).join(", ") + "." : "A 2.4 GHz keyboard and mouse work as soon as their USB dongle is in. Bluetooth controllers pair here."}</p>
        <div class="choices"><button class="btn" data-action="pair-controller">Pair a controller</button><button class="btn" data-action="tv-on">Turn the TV on</button></div></section>
      <section class="card"><h3>Apps on Home</h3><p>Hide the ones you don't use, or move them.</p><div class="applist"><ul>${data.apps.map((a, i) => `<li>
        <span class="name">${esc(a.name)}</span><button class="mini" data-move="${esc(a.id)}" data-by="-1"${i ? "" : " disabled"}>←</button>
        <button class="mini" data-move="${esc(a.id)}" data-by="1"${i === data.apps.length - 1 ? " disabled" : ""}>→</button>
        <button class="mini" data-hide="${esc(a.id)}">${a.hidden ? "Show" : "Hide"}</button>${a.kind === "web" ? `<button class="mini" data-remove="${esc(a.id)}">Remove</button>` : ""}</li>`).join("")}</ul></div></section>
      <section class="card"><h3>Sofa</h3><p>${b.server ? "Plays from " + esc(b.server_name || "Sofa") + " at " + esc(b.server.replace(/^https?:\/\//, "")) + "." : "No Sofa found yet."}</p>
        <button class="btn" data-action="choose">Use another Sofa</button></section>
      <section class="card"><h3>About this box</h3><dl class="facts"><dt>Model</dt><dd>${esc(b.model)}</dd><dt>Memory</dt><dd>${b.memory ? Math.round(b.memory / 1048576) + " MB" : "?"}</dd>
        <dt>Temperature</dt><dd>${b.temperature != null ? b.temperature + " °C" : "?"}</dd><dt>Version</dt><dd>${esc(b.version)}</dd></dl>
        <div class="choices" style="margin-top:1rem"><button class="btn" data-action="restart">Restart Sofa Box</button><button class="btn" data-action="reboot">Restart the box</button>
        <button class="btn" data-go="#/welcome">First-start steps again</button></div></section></div>`;
  }

  // ---- the first start
  let step = 0;
  function viewWelcome() {
    const steps = `<div class="steps">${[0, 1, 2, 3].map(i => `<i class="${i <= step ? "on" : ""}"></i>`).join("")}</div>`;
    if (step === 0) return `<div class="welcome view-in">${steps}<h1>Welcome to your Sofa Box</h1>
      <p>Your shows and films from Sofa, your apps, music, games and a browser, with no ads and nothing watching you.</p>
      <div class="inputs"><div><b>⌨</b>A 2.4 GHz keyboard and mouse: plug in the dongle</div><div><b>🎮</b>A game controller: pair it in Settings</div><div><b>📺</b>The TV's remote over HDMI, or your phone</div></div>
      <button class="btn primary" data-step="1">Let's go</button></div>`;
    if (step === 1) {
      const b = boxInfo || {};
      return `<div class="welcome view-in">${steps}<h1>Internet</h1><p>${b.wifi ? "Connected to <b>" + esc(b.wifi) + "</b>." : b.address ? "Connected (" + esc(b.address) + "). A cable is best for video." : "Not connected yet: pick your Wi-Fi."}</p>
        <div id="wifi"><button class="btn" data-action="wifi-scan">Find Wi-Fi networks</button></div><button class="btn primary" data-step="2">Next</button></div>`;
    }
    if (step === 2) {
      const s = sofa || {};
      return `<div class="welcome view-in">${steps}<h1>Sofa</h1><p>${s.found ? "Found " + esc(s.name || "Sofa") + "." + (s.signedIn ? " Signed in." : " Open it and sign in with your phone: it shows a code.") : "Looking for the Sofa computer on your network…"}</p>
        ${s.found ? "" : `<div class="add-site"><input class="field" id="sofaAddr" placeholder="Or type its address: 192.168.1.20" spellcheck="false"><button class="btn" data-sofa-addr="1">Use it</button></div>`}
        <button class="btn primary" data-step="3">Next</button></div>`;
    }
    return `<div class="welcome view-in">${steps}<h1>Your look</h1><p>Change it any time in Settings.</p>
      <div class="themes" style="width:min(44rem,100%)">${THEMES.map(t => `<button class="theme" data-theme-pick="${t[0]}" aria-pressed="${data.theme === t[0]}" style="--sw-bg:${t[2]};--sw-a:${t[3]};--sw-a2:${t[4]}"><i></i><b>${t[1]}</b></button>`).join("")}</div>
      <button class="btn primary" data-done="1">Done: to the home screen</button></div>`;
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
    el.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" });
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
    else if (input.id === "sofaAddr") $("[data-sofa-addr]").click();
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
      else if (d.target) open({ id: (data.running.find(r => r.target === d.target) || {}).app || "browser" });
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
      else if (d.set) { boxInfo = Object.assign(boxInfo, await api("/box/api/settings", { [d.set]: d.value })); boxInfo.shield = await api("/box/api/shield"); render(true); }
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
      else if (d.step) { step = +d.step; if (step === 1 && !boxInfo) await loadInfo(); if (step === 2) await loadSofa(); render(true); }
      else if (d.sofaAddr) { const r = await fetch("/box/choose", { method: "POST", body: $("#sofaAddr").value }).then(x => x.json());
        if (r.url) { toast("Found Sofa."); await loadApps(); await loadSofa(); render(true); } else toast("No Sofa answered there."); }
      else if (d.done) { await api("/box/api/settings", { welcomed: true }); data.welcomed = true; location.hash = "#/"; }
    } catch (ex) { toast(ex.message); }
  });
  async function install(body, name) {
    const r = await api("/box/api/apps/install", body);
    toast((r.app && r.app.name || name) + " is on Home.");
    storeData = null; await loadApps(); render(true);
  }
  let armed = "";
  async function action(a, t) {
    if ((a === "restart" || a === "reboot" || a === "choose") && armed !== a) { armed = a; t.textContent = "Press again to be sure"; return; }
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
  const TABS = { "": "home", store: "store", games: "games", files: "files", browser: "browser", settings: "settings", welcome: "" };
  function render(keep) {
    const name = (location.hash.replace(/^#\/?/, "").split("/")[0]) || "";
    const html = name === "store" ? viewStore() : name === "games" ? viewGames() : name === "files" ? viewFiles()
      : name === "browser" ? viewBrowser() : name === "settings" ? viewSettings() : name === "welcome" ? viewWelcome() : viewHome();
    const keepKey = keep && cur && document.contains(cur) ? keyOf(cur) : null;
    view.innerHTML = html;
    if (keep) $$(".view-in", view).forEach(v => v.classList.remove("view-in"));
    $$(".tabs a").forEach(a => a.setAttribute("aria-current", TABS[name] === a.dataset.tab ? "page" : "false"));
    const again = keepKey && $(keepKey);
    focus(again || $(name === "browser" ? "#address" : name === "store" ? "[data-store]" : "#view .hero .btn, #view .tile, #view button, #view input") || $(".tabs a"));
    hint(name === "files" ? [["OK", "Open or play"], ["Menu", "Rename, move, delete"], ["Back", "Up a folder"]]
      : name === "browser" ? [["OK", "Go"], ["Menu", "on a site: the Sofa bar"], ["Home", "Back here from any app"]]
      : name === "" ? [["OK", "Open"], ["Menu", "Move, hide or remove an app"], ["Home", "Back here from any app"], ["Type", "to search the web"]]
      : [["OK", "Choose"], ["Back", "Home screen"]]);
  }
  function keyOf(el) {
    for (const a of ["app", "store", "game", "file", "root", "set", "themePick", "move", "hide", "action", "target", "go", "url"]) {
      if (el.dataset[a] !== undefined) {
        const attr = "data-" + a.replace(/[A-Z]/g, c => "-" + c.toLowerCase());
        return `[${attr}="${CSS.escape(el.dataset[a])}"]` + (el.dataset.by ? `[data-by="${el.dataset.by}"]` : "") + (el.dataset.value ? `[data-value="${el.dataset.value}"]` : "");
      }
    }
    return el.id ? "#" + el.id : null;
  }
  window.addEventListener("hashchange", () => { closeSheet(); render(); });

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
