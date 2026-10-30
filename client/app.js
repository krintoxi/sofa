/* Sofa web client: library, player and server admin. Talks to the Sofa server's JSON API. */
(function () {
"use strict";

const $ = (s, el) => (el || document).querySelector(s);
const view = $("#view");

/* ---------- small helpers ---------- */
const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
// &r=2: a new address so browsers drop images cached before the 2026-10-20 resize fix.
const artSrc = (p, w) => {            // p: "/art/<key>/<path>?v=<date of the picture>"
  if (!p) return "";
  const [path, v] = p.split("?");
  return path.split("/").map((s, i) => i < 3 ? s : encodeURIComponent(s)).join("/") + (w ? "?w=" + w + "&r=2" : "?r=2") + (v ? "&" + v : "");
};
const icon = id => `<svg><use href="#${id}"/></svg>`;
function clock(sec) {
  sec = Math.max(0, Math.floor(sec || 0));
  const h = Math.floor(sec / 3600), m = Math.floor(sec / 60) % 60, s = sec % 60;
  return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(s).padStart(2, "0");
}
const plural = (n, w) => n + " " + w + (n === 1 ? "" : "s");
const fmtDate = d => d ? new Date(d + "T12:00:00").toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) : "";
const ago = t => {
  const s = Math.max(1, Math.floor(Date.now() / 1000 - t));
  if (s < 60) return "just now";
  if (s < 3600) return Math.floor(s / 60) + " min ago";
  if (s < 86400) return Math.floor(s / 3600) + " h ago";
  return new Date(t * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" });
};
const bytes = n => n > 1e12 ? (n / 1e12).toFixed(1) + " TB" : n > 1e9 ? Math.round(n / 1e9) + " GB" : Math.round(n / 1e6) + " MB";
const seasonName = n => n === 0 ? "Specials" : "Season " + n;
/* When an episode airs: "today", "tomorrow", "Friday" this week, otherwise the date. */
const airDay = d => {
  const days = Math.round((new Date(d + "T12:00:00") - new Date().setHours(12, 0, 0, 0)) / 864e5);
  return days === 0 ? "today" : days === 1 ? "tomorrow" : days > 1 && days < 7 ? new Date(d + "T12:00:00").toLocaleDateString(undefined, { weekday: "long" }) : fmtDate(d);
};
const epCode = ep => ep.s == null ? "Extra" : (ep.s === 0 ? "Special " : "S" + ep.s + " ") + "E" + ep.e + (ep.e2 ? "–" + ep.e2 : "");

const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;     // the device asks for less motion
const prefs = {
  get(k, d) { try { const v = localStorage.getItem("sofa." + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem("sofa." + k, JSON.stringify(v)); } catch (e) {} }
};

/* ---------- API ---------- */
async function api(path, body) {
  const opts = body === undefined ? { credentials: "same-origin" }
    : { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-Sofa": "1" }, body: JSON.stringify(body) };
  const r = await fetch(path, opts);
  let data = {};
  try { data = await r.json(); } catch (e) {}
  if (r.status === 401 && session && session.user) { location.reload(); }
  if (!r.ok) { const err = new Error(data.error || "Something went wrong (" + r.status + ")."); err.status = r.status; throw err; }
  return data;
}

/* TV mode: Fire TV (Silk), Android TV and smart-TV browsers get bigger targets, no blur/zoom effects,
   always-visible row arrows and a full-screen player. ?tv=1 / ?tv=0 forces it on this device. */
const tvParam = new URLSearchParams(location.search).get("tv");
if (tvParam === "1" || tvParam === "0") prefs.set("tv", tvParam === "1");
const NATIVE = window.SofaNative || null;      // inside the Fire TV app
const FIRE_TV = /\bAFT\w*\b/.test(navigator.userAgent);         // a Fire TV: Silk, or the app's own browser
const TV = NATIVE ? true : prefs.get("tv", /AFT[A-Z0-9]+|Android TV|GoogleTV|BRAVIA|SMART-TV|SmartTV|Tizen|Web0S|webOS|CrKey|HbbTV/i.test(navigator.userAgent));
if (TV) document.documentElement.classList.add("tv");

let session = null, LIB = { shows: [], movies: [] }, progress = {};
const byId = new Map();
let shows = [], movies = [], adultShows = [], adultMovies = [], favs = new Set();

/* ---------- themes (per device; the server sets the default) ---------- */
const THEMES = [["midnight", "Midnight", "#0A0E1A", "#F4B740"], ["cinema", "Cinema", "#0B0708", "#E5484D"],
  ["ocean", "Ocean", "#04131A", "#3CC8D8"], ["forest", "Forest", "#0A120D", "#8BD46E"],
  ["grape", "Grape", "#100A1A", "#C792FF"], ["oled", "Pure black", "#000000", "#F4B740"]];
/* A choice about how Sofa looks: this device's own if it made one, else the profile's (made on any of
   its screens), else Sofa's. Choosing saves it for both. */
function lookPref(key, def) {
  const mine = prefs.get(key, null);
  if (mine !== null) return mine;
  const look = session && session.user && session.user.prefs && session.user.prefs.look;
  return look && look[key] != null ? look[key] : def;
}
function saveLook(key, value) {
  prefs.set(key, value);
  if (session && session.user && !session.user.guest)
    api("/api/me/prefs", { look: { [key]: value } }).then(r => { session.user.prefs = r.prefs; }).catch(() => {});
}
// An accent colour of your own on any theme: buttons, the progress bar, focus, the logo.
const ACCENTS = ["#F4B740", "#FF8A3D", "#E5484D", "#FF5CA8", "#C792FF", "#8B8CFF", "#4DA3FF", "#3CC8D8", "#2EC4A6", "#8BD46E", "#D7E35A", "#EDEFF6"];
function applyAccent(hex) {
  const st = document.documentElement.style;
  if (!/^#[0-9a-f]{6}$/i.test(hex || "")) { ["--amber", "--accent-rgb", "--amber-hi", "--amber-ink"].forEach(k => st.removeProperty(k)); return; }
  const n = parseInt(hex.slice(1), 16), c = [n >> 16, (n >> 8) & 255, n & 255];
  const hi = c.map(v => Math.min(255, Math.round(v + (255 - v) * 0.18)));
  const light = (0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]) > 150;
  st.setProperty("--amber", hex); st.setProperty("--accent-rgb", c.join(","));
  st.setProperty("--amber-hi", "rgb(" + hi.join(",") + ")"); st.setProperty("--amber-ink", light ? "#1A1300" : "#FFFFFF");
}
// Animations: lively (everything), calm (no drifting, no rows sliding in), off.
function applyMotion(m) {
  document.documentElement.classList.toggle("motion-calm", m === "calm");
  document.documentElement.classList.toggle("motion-off", m === "off");
}
const motion = () => REDUCED ? "off" : lookPref("motion", "lively");
function applyLook() {
  applyTheme(lookPref("theme", (session && session.theme) || "midnight"));
  applyAccent(lookPref("accent", ""));
  applyMotion(motion());
  try { localStorage.setItem("sofa.splashBoot", JSON.stringify(lookPref("splash", "full"))); } catch (e) {}  // for the next start
}
function applyTheme(name) {
  if (!THEMES.some(t => t[0] === name)) name = "midnight";
  if (name === "midnight") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", name);
}
applyTheme(prefs.get("theme", "midnight"));
applyAccent(prefs.get("accent", ""));
applyMotion(REDUCED ? "off" : prefs.get("motion", "lively"));
function appearanceDialog() {
  const cur = lookPref("theme", (session && session.theme) || "midnight"), sub = prefs.get("subSize", "m");
  const accent = (lookPref("accent", "") || "").toUpperCase(), mo = motion(), splash = lookPref("splash", "full");
  const choice = (attr, v, label, on) => `<button ${attr}="${v}" aria-pressed="${on}">${label}</button>`;
  const d = openDialog(`<h2>Look and feel</h2><p>Yours, on every screen you use. Everyone can pick their own.</p>
    <div class="themes">${THEMES.map(t => `<button class="theme-swatch" data-theme-pick="${t[0]}" aria-pressed="${t[0] === cur}"
      style="--sw-bg:${t[2]};--sw-ac:${t[3]}"><i></i><span>${esc(t[1])}</span></button>`).join("")}</div>
    <h3 class="dlg-sub">Accent colour</h3>
    <div class="accents" role="group" aria-label="Accent colour">
      <button class="accent-dot theme-own" data-accent-pick="" aria-pressed="${!accent}" aria-label="The theme's own" title="The theme's own"></button>
      ${ACCENTS.map(a => `<button class="accent-dot" data-accent-pick="${a}" aria-pressed="${accent === a}" style="--dot:${a}" aria-label="${a}"></button>`).join("")}
      ${TV ? "" : `<label class="accent-dot custom" title="Any colour" style="--dot:${accent && !ACCENTS.includes(accent) ? accent : "transparent"}"><input type="color" data-accent-custom="1" value="${accent || "#F4B740"}" aria-label="Any colour"></label>`}
    </div>
    <h3 class="dlg-sub">Animations</h3>
    <div class="sorter inline" role="group" aria-label="Animations">${choice("data-motion", "lively", "Lively", mo === "lively")}${choice("data-motion", "calm", "Calm", mo === "calm")}${choice("data-motion", "off", "Off", mo === "off")}</div>
    <h3 class="dlg-sub">Loading screen</h3>
    <div class="sorter inline" role="group" aria-label="Loading screen">${choice("data-splash", "full", "Sofa's", splash === "full")}${choice("data-splash", "quick", "Quick", splash === "quick")}${choice("data-splash", "off", "None", splash === "off")}</div>
    <h3 class="dlg-sub">Subtitle size</h3>
    <div class="sorter inline" role="group" aria-label="Subtitle size">${[["s", "Small"], ["m", "Medium"], ["l", "Large"], ["xl", "Huge"]].map(x =>
      `<button data-sub-size="${x[0]}" aria-pressed="${x[0] === sub}">${x[1]}</button>`).join("")}</div>
    <h3 class="dlg-sub">Home</h3>
    ${session && session.user && !session.user.guest ? `<div class="toggle"><div><b>What's on Home</b><span>Which rows, in which order. Yours on every screen.</span></div><button class="btn" data-home-edit="1">Arrange</button></div>` : ""}
    <div class="toggle"><div><b>Play the banner</b><span>The featured title at the top of Home plays a few silent seconds.</span></div>
      <button class="switch" role="switch" aria-checked="${prefs.get("bannerClips", true) !== false}" data-banner-toggle="1" aria-label="Play the banner"></button></div>
    <div class="toggle"><div><b>Trailers</b><span>A show's or movie's page plays three minutes of it, from somewhere in the middle, behind the title.</span></div>
      <button class="switch" role="switch" aria-checked="${prefs.get("trailers", true) !== false}" data-trailer-toggle="1" aria-label="Trailers"></button></div>
    <div class="toggle"><div><b>Hide spoilers</b><span>Pictures and descriptions of episodes you haven't watched stay blurred until you point at them.</span></div>
      <button class="switch" role="switch" aria-checked="${!!prefs.get("noSpoilers", false)}" data-spoiler-toggle="1" aria-label="Hide spoilers"></button></div>
    <h3 class="dlg-sub">This device</h3>
    ${TV ? "" : `<div class="toggle"><div><b>Sofa as an app</b><span>${installHint()}</span></div>${installPrompt ? `<button class="btn" data-install-app="1">Install</button>` : ""}</div>`}
    <label class="field"><span>Its name, for playing on it from your phone</span><input data-screen-name="1" maxlength="40" value="${esc(prefs.get("screenName", ""))}" placeholder="${esc(Screens.defaultName())}"></label>
    <h3 class="dlg-sub">TV mode</h3>
    <div class="toggle"><div><b>Big buttons for a remote</b><span>Turns on by itself on Fire TV, Android TV and smart TVs.</span></div>
      <button class="switch" role="switch" aria-checked="${TV}" data-tv-toggle="1" aria-label="TV mode"></button></div>
    <div class="actions"><button class="btn primary" data-dismiss="1">Done</button></div>`);
  const custom = $("[data-accent-custom]", d);
  if (custom) custom.addEventListener("change", () => {
    saveLook("accent", custom.value.toUpperCase()); applyAccent(custom.value);
    custom.parentElement.style.setProperty("--dot", custom.value);
    d.querySelectorAll("[data-accent-pick]").forEach(b => b.setAttribute("aria-pressed", "false"));
  });
  const nameBox = $("[data-screen-name]", d);
  if (nameBox) nameBox.addEventListener("change", () => prefs.set("screenName", nameBox.value.trim()));
  d.addEventListener("click", e => {
    const t = e.target.closest("[data-theme-pick],[data-sub-size],[data-tv-toggle],[data-banner-toggle],[data-trailer-toggle],[data-spoiler-toggle],[data-install-app],[data-accent-pick],[data-motion],[data-splash]"); if (!t) return;
    const pressOnly = (sel) => d.querySelectorAll(sel).forEach(b => b.setAttribute("aria-pressed", b === t));
    if (t.dataset.accentPick !== undefined) { saveLook("accent", t.dataset.accentPick || null); applyAccent(t.dataset.accentPick); pressOnly("[data-accent-pick]"); return; }
    if (t.dataset.motion) { saveLook("motion", t.dataset.motion); applyMotion(t.dataset.motion); pressOnly("[data-motion]"); return; }
    if (t.dataset.splash) { saveLook("splash", t.dataset.splash); applyLook(); pressOnly("[data-splash]"); return; }
    if (t.dataset.installApp && installPrompt) { installPrompt.prompt(); installPrompt.userChoice.finally(() => { installPrompt = null; t.remove(); }); return; }
    if (t.dataset.spoilerToggle) { const on = !prefs.get("noSpoilers", false); prefs.set("noSpoilers", on); t.setAttribute("aria-checked", on); applySpoilers(); return; }
    if (t.dataset.trailerToggle) { const on = prefs.get("trailers", true) === false; prefs.set("trailers", on); t.setAttribute("aria-checked", on);
      if (!on) stopTrailer(); return; }
    if (t.dataset.bannerToggle) { const on = prefs.get("bannerClips", true) === false; prefs.set("bannerClips", on); t.setAttribute("aria-checked", on);
      if (!on) document.querySelectorAll(".hero-clip").forEach(dropClip); return; }
    if (t.dataset.themePick) { saveLook("theme", t.dataset.themePick); applyTheme(t.dataset.themePick);
      d.querySelectorAll("[data-theme-pick]").forEach(b => b.setAttribute("aria-pressed", b === t)); }
    else if (t.dataset.subSize) { prefs.set("subSize", t.dataset.subSize); applySubSize();
      d.querySelectorAll("[data-sub-size]").forEach(b => b.setAttribute("aria-pressed", b === t)); }
    else { prefs.set("tv", !TV); location.reload(); }
  });
}
/* Sofa as an app: an icon on the home screen that opens it without the browser around it. */
let installPrompt = null;
window.addEventListener("beforeinstallprompt", e => { e.preventDefault(); installPrompt = e; });
const standalone = () => matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
if (standalone()) document.documentElement.classList.add("standalone");
function installHint() {
  const ua = navigator.userAgent;
  if (standalone()) return "Installed: you're using it now.";
  if (installPrompt) return "Put Sofa on this device's home screen or in its apps, with its own icon.";
  if (/iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)) return "In Safari, press Share, then Add to Home Screen. Sofa then opens full screen, like an app.";
  if (/Android/.test(ua)) return "In the browser's menu, press Add to Home screen: Sofa gets its own icon.";
  return "In the browser's menu, look for Install Sofa or Create shortcut: Sofa gets its own icon and window.";
}
/* "Install Sofa": once on a phone or tablet (again after two weeks if they said not now), and on computers whose
   browser can install it. One tap where the browser allows it, otherwise the two steps for this device. */
function installOffer(asked) {
  const ua = navigator.userAgent, coarse = matchMedia("(pointer: coarse)").matches;
  if (standalone() || NATIVE || TV || /SofaBox|SofaApp/.test(ua) || !session || !session.user) return;
  if (!asked && !coarse && !installPrompt) return;
  if ((!asked && Date.now() - prefs.get("installAsk", 0) < 14 * 864e5) || document.querySelector(".install-sheet,.dialog-scrim")) return;
  const ios = /iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
  const share = `<svg viewBox="0 0 24 24" class="share-ico" aria-label="Share"><path d="M12 3v12M7.5 7.5 12 3l4.5 4.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="M8 10H6.5A1.5 1.5 0 0 0 5 11.5v8A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5v-8a1.5 1.5 0 0 0-1.5-1.5H16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>`;
  const how = installPrompt ? `<p>Sofa on your home screen, full screen, with its own icon.</p>`
    : ios && /CriOS|FxiOS|EdgiOS/.test(ua) ? `<ol><li>Tap ${share} <b>Share</b> (in the address bar or the menu)</li><li>Choose <b>Add to Home Screen</b></li></ol>`
    : ios ? `<ol><li>Tap ${share} <b>Share</b> ${/iPad/.test(ua) || /Macintosh/.test(ua) ? "at the top" : "at the bottom of the screen"}</li><li>Scroll down a little and choose <b>Add to Home Screen</b></li></ol>`
    : `<ol><li>Tap the browser's menu <b>⋮</b> (top right)</li><li>Choose <b>Add to Home screen</b> or <b>Install app</b></li></ol>`;
  const sheet = document.createElement("div");
  sheet.className = "install-sheet" + (ios && !installPrompt && !/iPad|Macintosh/.test(ua) ? " points-down" : "");
  sheet.setAttribute("role", "dialog"); sheet.setAttribute("aria-label", "Install Sofa");
  sheet.innerHTML = `<img src="/client/icons/icon-192.png" alt="" width="56" height="56"><div class="is-body"><b>Install Sofa</b>${how}
    <div class="row-actions">${installPrompt ? `<button class="btn primary" data-install-go="1">Install</button>` : ""}<button class="btn ghost" data-install-later="1">${installPrompt ? "Not now" : "Got it"}</button></div></div>`;
  document.body.appendChild(sheet);
  requestAnimationFrame(() => sheet.classList.add("on"));
  const close = () => { prefs.set("installAsk", Date.now()); sheet.classList.remove("on"); setTimeout(() => sheet.remove(), 400); };
  sheet.addEventListener("click", async e => {
    if (e.target.closest("[data-install-later]")) return close();
    if (e.target.closest("[data-install-go]") && installPrompt) {
      installPrompt.prompt();
      const choice = await installPrompt.userChoice.catch(() => ({}));
      installPrompt = null; close();
      if (choice.outcome === "accepted") toast("Sofa is on your home screen now.");
    }
  });
}
window.addEventListener("appinstalled", () => { prefs.set("installAsk", Date.now()); const s = $(".install-sheet"); if (s) s.remove(); });
function applySubSize() { document.documentElement.dataset.subs = prefs.get("subSize", "m"); document.documentElement.dataset.subStyle = prefs.get("subStyle", "box"); }
function applySpoilers() { document.documentElement.dataset.nospoil = prefs.get("noSpoilers", false) ? "1" : "0"; }
applySpoilers();
applySubSize();

/* ---------- index the library ---------- */
function indexLibrary(lib) {
  LIB = lib; shows = lib.shows; movies = lib.movies; byId.clear();
  adultShows = (lib.adult || {}).shows || []; adultMovies = (lib.adult || {}).movies || [];
  favs = new Set(lib.likes || []);
  shows.concat(adultShows).forEach(show => {
    byId.set(show.id, show);
    show.order = [];
    show.seasons.sort((a, b) => (a.n === 0) - (b.n === 0) || a.n - b.n);
    show.seasons.forEach(season => season.episodes.forEach(ep => {
      ep.show = show; ep.season = season;
      byId.set(ep.id, ep);
      if (season.n !== 0) show.order.push(ep);
    }));
    show.extras.forEach(x => { x.show = show; byId.set(x.id, x); });
    show.count = show.seasons.reduce((n, s) => n + s.episodes.length, 0);
    show.regularSeasons = show.seasons.filter(s => s.n !== 0).length;
  });
  movies.concat(adultMovies).forEach(m => byId.set(m.id, m));
  shows.concat(movies).forEach(x => { x.genres = normGenres(x.genres); });
  const week = Date.now() - 7 * 864e5;
  LIB.manyNew = shows.filter(s => s.added * 1000 > week).length > shows.length / 2;     // a new library: no "New" everywhere
}
/* Genres come from TVmaze, TMDB, the iTunes Store and .nfo files, each with its own names for the same
   thing: one name each, and pairs like "Action & Adventure" or "Sci-Fi & Fantasy" become both. */
const GENRE_NAMES = { "science-fiction": "Science Fiction", "sci-fi": "Science Fiction", "scifi": "Science Fiction", "sf": "Science Fiction",
  "children": "Kids", "kids": "Kids", "children's": "Kids", "musicals": "Musical", "music documentaries": "Documentary",
  "documentaries": "Documentary", "docuseries": "Documentary", "animated": "Animation", "cartoon": "Animation", "cartoons": "Animation",
  "romantic": "Romance", "suspense": "Thriller", "tv movie": "TV Movie", "film-noir": "Film Noir", "soap": "Soap Opera" };
function normGenres(list) {
  const out = [];
  (list || []).forEach(g => String(g).split(/\s*(?:&|\/|,|;|\band\b)\s*/i).forEach(part => {
    part = part.trim(); if (!part || part.length > 30) return;
    const k = part.toLowerCase();
    const name = GENRE_NAMES[k] || (k === "fi" ? "" : part.replace(/(^|[\s-])\w/g, c => c.toUpperCase()));
    if (name && !out.includes(name)) out.push(name);
  }));
  return out;
}
const notAdult = item => !(item.adult || (item.show && item.show.adult));

/* ---------- watch progress (kept on the server, per person) ---------- */
const prog = id => progress[id] || null;
const isDone = id => !!(progress[id] && progress[id].done);
const pct = id => { const p = prog(id); return p && p.d ? Math.min(100, (p.t / p.d) * 100) : 0; };
const inProgress = id => { const p = prog(id); return !!(p && !p.done && p.t > 30); };
const pending = {};
function setProgress(id, rec, now) {
  if (rec) progress[id] = Object.assign(rec, { at: Date.now() }); else delete progress[id];
  clearTimeout(pending[id]);
  const send = () => api("/api/progress/" + encodeURIComponent(id), rec ? { t: rec.t, d: rec.d, done: rec.done } : { clear: true }).catch(() => {});
  if (now) send(); else pending[id] = setTimeout(send, 1500);
}
function setWatched(id, on) {
  const p = progress[id] || { t: 0, d: 0 };
  if (!on && !p.d) return setProgress(id, null, true);
  setProgress(id, { t: on ? p.d || p.t : 0, d: p.d, done: on }, true);
}

function nextAfter(ep) {
  if (!ep.show || ep.kind !== "episode" || ep.season.n === 0) return null;
  const i = ep.show.order.indexOf(ep);
  return i >= 0 ? ep.show.order[i + 1] || null : null;
}
function upNext(show) {
  let resume = null, last = null;
  show.order.forEach(ep => {
    const p = prog(ep.id);
    if (!p) return;
    if (inProgress(ep.id) && (!resume || p.at > prog(resume.id).at)) resume = ep;
    if (p.done && (!last || p.at > prog(last.id).at)) last = ep;
  });
  if (resume && (!last || prog(resume.id).at >= prog(last.id).at)) return { ep: resume, resume: true };
  if (last) {
    let n = nextAfter(last);
    while (n && isDone(n.id)) n = nextAfter(n);
    return n ? { ep: n, resume: inProgress(n.id) } : null;
  }
  return show.order[0] ? { ep: show.order[0], resume: false, fresh: true } : null;
}
function lastTouched(show) {
  let t = 0;
  show.order.concat(show.extras).forEach(ep => { const p = prog(ep.id); if (p && p.at > t) t = p.at; });
  return t;
}
/* "Remove from Continue watching": the show or movie leaves Continue watching and Next up until it's
   watched again (kept with the watch progress, per person, as "hide:<id>"). */
const ownerOf = item => item.kind === "episode" && item.show ? item.show : item;
const touchedAt = x => x.seasons ? lastTouched(x) : (prog(x.id) || {}).at || 0;
function hiddenFromRows(item) {
  const x = ownerOf(item), h = progress["hide:" + x.id];
  return !!h && h.at >= touchedAt(x);
}
function inRows(item) {
  const x = ownerOf(item);
  if (hiddenFromRows(x)) return false;
  if (!x.seasons) return inProgress(x.id);
  const nx = upNext(x);
  return !!nx && !nx.fresh;
}
function forget(item) {
  const x = ownerOf(item);
  setProgress("hide:" + x.id, { t: 0, d: 0, done: false }, true);
  progress["hide:" + x.id].at = Math.max(Date.now(), touchedAt(x) + 1);      // a TV's clock may be behind the server's
}
/* New episodes: episodes of a show you watch that arrived after you last watched it. */
function newEpisodes(show) {
  const seen = lastTouched(show);
  if (!seen) return [];
  return show.order.filter(ep => ep.added * 1000 > seen && !prog(ep.id));
}
const title = item => item.title || (item.kind === "episode" ? "Episode " + item.e : "Untitled");
function subtitleFor(item) {
  if (item.kind === "episode") return epCode(item) + ", " + title(item);
  if (item.kind === "extra") return title(item);
  if (item.kind === "musicvideo") return item.artist;
  return [item.year, item.collection].filter(Boolean).join(", ");
}

/* ---------- ambient room light ---------- */
let glowFront = $("#glowA"), glowBack = $("#glowB"), glowSrc = "";
function setGlow(path) {
  const s = artSrc(path, 240);   // it's blurred: tiny is plenty
  if (s === glowSrc) return;
  glowSrc = s;
  if (!s) { glowFront.classList.remove("on"); return; }
  const next = glowBack;
  next.onload = () => { next.classList.add("on"); glowFront.classList.remove("on"); glowBack = glowFront; glowFront = next; };
  next.src = s;
}

/* ---------- markup builders ---------- */
const hue = text => { let h = 0; for (const c of String(text || "")) h = (h * 31 + c.charCodeAt(0)) % 360; return h; };
/* A cover that's a still from the video (no service knew the title) is dressed as a poster: the whole
   frame over a soft copy of itself, with the title, instead of a wide picture cut down to a narrow slice. */
const dressed = x => x.poster_still && x.poster && !x.adult;
const stillPoster = (x, w) => `<img class="sp-bg" src="${esc(artSrc(x.poster, 240))}" alt="" loading="lazy" decoding="async" aria-hidden="true">
  <img class="sp-pic" src="${esc(artSrc(x.poster, w || 480))}" alt="${esc(x.name || x.title)}" loading="lazy" decoding="async">
  <span class="sp-text"><b>${esc(x.name || x.title)}</b>${yearOf(x) ? `<small>${yearOf(x)}</small>` : ""}</span>`;
function frameImg(path, alt, fallbackText, w) {
  return (path ? `<img src="${esc(artSrc(path, w || 360))}" alt="${esc(alt || "")}" loading="lazy" decoding="async">` : "") +
    `<span class="placeholder" style="--h:${hue(fallbackText || alt)}">${esc(fallbackText || "")}</span>`;
}
const quality = h => !h ? "" : h >= 2000 ? "4K" : h >= 1000 ? "HD" : h >= 700 ? "720p" : "SD";
const dur = s => s ? (s >= 3600 ? Math.floor(s / 3600) + " h " + Math.round(s % 3600 / 60) + " min" : Math.max(1, Math.round(s / 60)) + " min") : "";
/* "New" on a show's card: episodes that came after you last watched it, or a show that arrived this week. */
function newBadge(show) {
  if (!show.order) return "";
  const n = newEpisodes(show).length;
  if (n) return `<span class="new-badge">${n > 1 ? n + " new" : "New episode"}</span>`;
  return !LIB.manyNew && !lastTouched(show) && show.added * 1000 > Date.now() - 7 * 864e5 ? `<span class="new-badge">New</span>` : "";
}
function posterCard(show, sub) {
  return `<a class="card ${show.adult ? "scene" : "poster"}" href="#/show/${encodeURIComponent(show.id)}"${show.order && show.order[0] ? ` data-pv="${esc(show.order[0].id)}" data-pop="${esc(show.id)}"` : ""}>
    <span class="frame${show.poster ? "" : " noimg"}${dressed(show) ? " still-poster" : ""}">${dressed(show) ? stillPoster(show) : frameImg(show.poster, show.name, show.name)}${newBadge(show)}</span>
    <span class="t1">${esc(show.name)}</span>
    <span class="t2">${typeof sub === "string" ? esc(sub) : plural(show.regularSeasons, "season") + ", " + plural(show.count, "episode")}</span></a>`;
}
function movieCard(m) {
  return `<a class="card ${m.adult ? "scene" : "poster"}" href="#/movie/${encodeURIComponent(m.id)}" data-pv="${esc(m.id)}" data-pop="${esc(m.id)}">
    <span class="frame${m.poster ? "" : " noimg"}${dressed(m) ? " still-poster" : ""}">${dressed(m) ? stillPoster(m) : frameImg(m.poster, m.title, m.title)}
      ${pct(m.id) && !isDone(m.id) ? `<span class="progress"><i style="width:${pct(m.id)}%"></i></span>` : ""}
      ${isDone(m.id) ? `<span class="seen-badge">${icon("i-check")}</span>` : ""}
      ${m.adult && (m.duration || m.height) ? `<span class="dur-badge">${esc([quality(m.height), m.duration ? clock(m.duration) : ""].filter(Boolean).join(" · "))}</span>` : ""}
      ${m.adult && favs.has(m.id) ? `<span class="fav-badge">♥</span>` : ""}</span>
    <span class="t1">${esc(m.title)}</span>
    <span class="t2">${esc([m.year, m.studio].filter(Boolean).join(" · "))}</span></a>`;
}
function collectionCard(name, list) {
  const art = list.find(m => m.poster);
  return `<a class="card ${list.some(m => m.adult) ? "scene" : "poster"} collection" href="#/collection/${encodeURIComponent(name)}">
    <span class="frame${art ? "" : " noimg"}">${art ? frameImg(art.poster, name, name) : `<span class="placeholder">${esc(name)}</span>`}
      <span class="stack-badge">${list.length}</span></span>
    <span class="t1">${esc(name)}</span><span class="t2">${plural(list.length, "movie")}</span></a>`;
}
function thumbFor(item) {
  const owner = item.show || item;
  const code = item.kind === "episode" ? epCode(item) : item.kind === "movie" ? "" : "Extra";
  if (item.thumb) return frameImg(item.thumb, title(item), "", 480) + (code ? `<span class="code-chip">${esc(code)}</span>` : "");
  const art = owner.backdrop || owner.poster;
  return (art ? `<img class="bg-art${owner.backdrop ? "" : " from-poster"}" src="${esc(artSrc(art, 480))}" alt="" loading="lazy" decoding="async">`
              : `<span class="placeholder" style="--h:${hue(owner.name || owner.title)}"></span>`) +
    (code ? `<span class="code-chip">${esc(code)}</span>` : "");
}
function wideCard(item, label) {
  const owner = item.show || item;
  return `<button class="card wide${item.kind === "episode" && !prog(item.id) ? " unseen" : ""}" data-play="${esc(item.id)}" data-pv="${esc(item.id)}" data-pop="${esc(item.id)}">
    <span class="frame">${thumbFor(item)}
      ${pct(item.id) && !isDone(item.id) ? `<span class="progress"><i style="width:${pct(item.id)}%"></i></span>` : ""}
      <span class="play-glyph">${icon("i-play")}</span></span>
    <span class="t1">${esc(owner.name || owner.title)}</span>
    <span class="t2">${esc(label || subtitleFor(item))}</span></button>`;
}
/* Long grids (hundreds of movies) draw the first cards straight away and the rest as you scroll
   near the end (the TV remote scrolls too), so pages open quickly on a TV stick or an old computer. */
let gridSeq = 0;
const gridRest = new Map();
const GRID_FIRST = 90, GRID_STEP = 120;
function grid(cards) {
  if (cards.length <= GRID_FIRST + 30) return `<div class="grid">${cards.join("")}</div>`;
  const id = ++gridSeq;
  gridRest.set(id, cards.slice(GRID_FIRST));
  return `<div class="grid" data-grid="${id}">${cards.slice(0, GRID_FIRST).join("")}</div><div class="grid-more" data-more="${id}" aria-hidden="true"></div>`;
}
const gridWatch = "IntersectionObserver" in window ? new IntersectionObserver(entries => entries.forEach(en => {
  if (!en.isIntersecting) return;
  const id = +en.target.dataset.more, rest = gridRest.get(id), g = document.querySelector(`[data-grid="${id}"]`);
  if (!rest || !g) { gridWatch.unobserve(en.target); en.target.remove(); return; }
  g.insertAdjacentHTML("beforeend", rest.splice(0, GRID_STEP).join(""));
  if (!rest.length) { gridRest.delete(id); gridWatch.unobserve(en.target); en.target.remove(); }
  else { gridWatch.unobserve(en.target); gridWatch.observe(en.target); }       // still in view: next batch
}), { rootMargin: "900px 0px" }) : null;
function watchGrids() {
  document.querySelectorAll(".grid-more").forEach(m => {
    if (gridWatch) gridWatch.observe(m);
    else { const g = document.querySelector(`[data-grid="${m.dataset.more}"]`); if (g) g.insertAdjacentHTML("beforeend", (gridRest.get(+m.dataset.more) || []).join("")); m.remove(); }
  });
}
/* Lively: a row's cards slide in, one after another, as it comes into view. */
const railSeen = "IntersectionObserver" in window ? new IntersectionObserver(entries => entries.forEach(en => {
  if (!en.isIntersecting) return;
  const r = en.target; r.classList.add("rail-in"); railSeen.unobserve(r);
  setTimeout(() => r.classList.remove("rail-watch"), 1500);      // done: the cards' own hover and focus effects again
}), { rootMargin: "0px 0px -8% 0px" }) : null;
function revealRails(root) {
  if (!railSeen || motion() !== "lively" || document.documentElement.classList.contains("box-lite")) {
    (root || document).querySelectorAll(".row:not(.rail-in)").forEach(r => r.classList.add("rail-in")); return;
  }
  (root || document).querySelectorAll(".row:not(.rail-in):not(.rail-watch)").forEach(r => {
    r.classList.add("rail-watch");
    r.querySelectorAll(".rail > *").forEach((c, i) => c.style.setProperty("--i", Math.min(i, 9)));
    railSeen.observe(r);
  });
}
function rail(titleText, kind, cards, link) {
  if (!cards.length) return "";
  return `<section class="row"><div class="row-head"><h2>${esc(titleText)}</h2>${link ? `<a href="${link}">See all</a>` : ""}</div>
    <div class="rail-wrap"><button class="nudge prev" data-nudge="-1" aria-label="Scroll left" tabindex="-1">${icon("i-back")}</button>
    <div class="rail ${kind}">${cards.join("")}</div>
    <button class="nudge next" data-nudge="1" aria-label="Scroll right" tabindex="-1">${icon("i-next-arrow")}</button></div></section>`;
}
function years(show) {
  if (!show.premiered) return "";
  const a = show.premiered.slice(0, 4), b = show.ended ? show.ended.slice(0, 4) : "now";
  return a === b ? a : a + " to " + b;
}
function heroFor(show, short) {
  const nx = upNext(show);
  const facts = [
    show.network && years(show) ? `<span><b>${esc(show.network)}</b>, ${esc(years(show))}</span>` : "",
    `<span>${plural(show.regularSeasons, "season")}, ${plural(show.count, "episode")}</span>`,
    show.genres && show.genres.length ? `<span>${esc(show.genres.join(", "))}</span>` : "",
    show.rating ? `<span>Rated <b>${esc(show.rating)}</b> on TVmaze</span>` : "",
    show.next_air ? `<span class="next-air">New episode ${esc(airDay(show.next_air.aired))}</span>` : ""
  ].join("");
  let action = "";
  if (nx) {
    const verb = nx.resume ? "Resume" : nx.fresh ? "Play" : "Play next";
    action = `<button class="btn primary" data-play="${esc(nx.ep.id)}">${icon("i-play")}${verb} <small>${esc(epCode(nx.ep))}</small></button>`;
  }
  return `<section class="hero${short ? " short" : ""}"${short ? ` data-trailer="${esc(trailerFor(show))}"` : ""}>${short ? trailerCtl() : ""}
    ${show.backdrop || (show.poster_still && show.poster) ? `<img class="hero-bg" src="${esc(artSrc(show.backdrop || show.poster, 1280))}" alt="">`
      : show.poster ? `<img class="hero-bg blur" src="${esc(artSrc(show.poster, 480))}" alt="">` : ""}
    <div class="hero-body">
      ${show.logo ? `<img class="hero-logo" src="${esc(artSrc(show.logo, 720))}" alt="${esc(show.name)}">` : `<h1>${esc(show.name)}</h1>`}
      <p class="facts">${facts}</p>
      ${show.summary ? `<p class="summary${short ? "" : " clamp"}">${esc(show.summary)}</p>` : ""}
      <div class="actions">${action}${short ? "" : `<a class="btn" href="#/show/${encodeURIComponent(show.id)}">Episodes</a>`}${show.adult ? "" : listBtn(show.id)}${short && inRows(show) ? forgetBtn(show) : ""}
        ${short && session.user.admin ? `<button class="btn ghost" data-fix="${esc(show.id)}">${show.source ? "Fix details" : "Find details"}</button>
          <button class="btn ghost" data-manage="${esc(show.id)}">${icon("i-more")}Manage</button>${kidsBtn(show)}` : ""}</div>
    </div></section>`;
}

/* ---------- library views ---------- */
/* Home's featured carousel: what you're in the middle of first, then new arrivals with good artwork. */
function heroSlides() {
  const touched = shows.filter(s => lastTouched(s) && !hiddenFromRows(s)).sort((a, b) => lastTouched(b) - lastTouched(a)).slice(0, 2);
  const fresh = shows.concat(movies).filter(x => x.backdrop).sort((a, b) => b.added - a.added);
  const day = Math.floor(Date.now() / 864e5), pool = shows.concat(movies).filter(x => x.backdrop);
  const out = [];
  touched.concat(fresh.slice(0, 3), pool.length ? [pool[day % pool.length]] : []).forEach(x => { if (x && !out.includes(x) && out.length < 6) out.push(x); });
  if (!out.length) out.push(shows[0] || movies[0]);
  return out;
}
function heroSlide(x, i) {
  const isShow = !!x.seasons;
  let facts, action, more;
  if (isShow) {
    const nx = upNext(x);
    facts = [x.network && years(x) ? `<span><b>${esc(x.network)}</b> · ${esc(years(x))}</span>` : "", `<span>${plural(x.regularSeasons, "season")}</span>`,
             x.genres && x.genres.length ? `<span>${esc(x.genres.slice(0, 3).join(" · "))}</span>` : ""].join("");
    action = nx ? `<button class="btn primary" data-play="${esc(nx.ep.id)}">${icon("i-play")}${nx.resume ? "Resume" : nx.fresh ? "Play" : "Play next"} <small>${esc(epCode(nx.ep))}</small></button>` : "";
    more = `<a class="btn" href="#/show/${encodeURIComponent(x.id)}">Episodes</a>`;
  } else {
    facts = [x.year ? `<span><b>${esc(x.year)}</b></span>` : "", x.runtime ? `<span>${esc(dur(x.runtime * 60))}</span>` : "",
             x.genres && x.genres.length ? `<span>${esc(x.genres.slice(0, 3).join(" · "))}</span>` : ""].join("");
    action = `<button class="btn primary" data-play="${esc(x.id)}">${icon("i-play")}${inProgress(x.id) ? "Resume" : "Play"}</button>`;
    more = `<a class="btn" href="#/movie/${encodeURIComponent(x.id)}">More info</a>`;
  }
  const name = x.name || x.title, clipId = isShow ? (upNext(x) || { ep: x.order[0] || {} }).ep.id : x.id;
  return `<div class="slide${i ? "" : " on"}" data-glow="${esc(x.backdrop || x.poster || "")}"${clipId ? ` data-clip="${esc(clipId)}"` : ""} aria-hidden="${i ? "true" : "false"}">
    ${x.backdrop ? `<img class="hero-bg" src="${esc(artSrc(x.backdrop, 1280))}" alt=""${i ? ` loading="lazy"` : ""}>`
      : x.poster ? `<img class="hero-bg blur" src="${esc(artSrc(x.poster, 480))}" alt="">` : `<span class="hero-bg placeholder" style="--h:${hue(name)}"></span>`}
    <div class="hero-body"><p class="eyebrow">${isShow ? (lastTouched(x) ? "Continue the series" : "Series") : "Movie"}</p>
      ${x.logo ? `<img class="hero-logo" src="${esc(artSrc(x.logo, 720))}" alt="${esc(name)}">` : `<h1>${esc(name)}</h1>`}
      <p class="facts">${facts}</p>
      ${x.summary ? `<p class="summary clamp">${esc(x.summary)}</p>` : ""}
      <div class="actions">${action}${more}</div></div></div>`;
}
function heroCarousel() {
  const slides = heroSlides();
  return `<section class="hero carousel" aria-roledescription="carousel" aria-label="Featured">${slides.map(heroSlide).join("")}
    ${slides.length > 1 ? `<div class="hero-dots" role="group" aria-label="Choose a featured title">${slides.map((x, i) =>
      `<button data-slide="${i}" aria-label="${esc(x.name || x.title)}" aria-pressed="${!i}" tabindex="-1"></button>`).join("")}</div>` : ""}</section>`;
}
let heroTimer = 0;
function showSlide(i) {
  const h = $(".hero.carousel"); if (!h) return;
  const slides = [...h.querySelectorAll(".slide")]; if (!slides.length) return;
  i = (i + slides.length) % slides.length;
  slides.forEach((s, n) => { s.classList.toggle("on", n === i); s.setAttribute("aria-hidden", n !== i); });
  h.querySelectorAll("[data-slide]").forEach((d, n) => d.setAttribute("aria-pressed", n === i));
  h.dataset.at = i;
  setGlow(slides[i].dataset.glow);
  heroClip(slides[i]);
}
/* The banner plays: after a moment, a few silent seconds of the featured title fade in behind it,
   then the next title comes on. */
let clipTimer = 0;
function heroClip(slide) {
  clearTimeout(clipTimer);
  document.querySelectorAll(".hero-clip").forEach(v => { if (!slide.contains(v)) dropClip(v); });
  const h = slide.closest(".hero.carousel"); if (h) delete h.dataset.playing;
  if (motion() === "off" || !slide.dataset.clip || prefs.get("bannerClips", true) === false) return;
  clipTimer = setTimeout(() => {
    if (!document.contains(slide) || !slide.classList.contains("on") || Player.isOpen() || document.hidden || slide.querySelector(".hero-clip")) return;
    const v = clipVideo(slide.dataset.clip, true);
    v.className = "hero-clip"; v.loop = false;
    v.addEventListener("playing", () => { v.classList.add("on"); if (h) h.dataset.playing = "1"; }, { once: true });
    v.addEventListener("ended", () => {
      v.classList.remove("on");
      setTimeout(() => { dropClip(v); if (h && document.contains(h)) { delete h.dataset.playing; if (h.querySelectorAll(".slide").length > 1) showSlide(+(h.dataset.at || 0) + 1); } }, 1200);
    });
    slide.querySelector(".hero-bg").after(v);
  }, 2600);
}
function startHero() {
  clearInterval(heroTimer);
  const h = $(".hero.carousel"); if (h && $(".slide.on", h)) heroClip($(".slide.on", h));
  if (!h || h.querySelectorAll(".slide").length < 2) return;
  heroTimer = setInterval(() => {
    if (!document.contains(h)) return clearInterval(heroTimer);
    if (h.matches(":hover") || h.contains(document.activeElement) || Player.isOpen() || document.hidden || h.dataset.playing) return;
    showSlide(+(h.dataset.at || 0) + 1);
  }, 9000);
}
/* Trailers: on a show's or movie's page, after a moment, three minutes of the title itself, from a random
   spot (not the opening, not the end), play behind the banner without sound until you turn it on.
   A file the device plays as it is costs the server nothing, and one in another container is repackaged
   on the fly (cheap); one that would need converting on a slow server plays its short preview clip instead.
   A show's trailer comes from a random episode of its first season, so it gives nothing away. */
const TRAILER_SECONDS = 180;
let trailerTimer = 0, trailerHash = "";
function trailerFor(x) {
  if (!x.seasons) return x.id;
  const season = x.seasons.find(s => s.n > 0 && s.episodes.length) || x.seasons.find(s => s.episodes.length);
  const eps = season ? season.episodes : [];
  return eps.length ? eps[Math.floor(Math.random() * eps.length)].id : "";
}
const trailerCtl = () => `<div class="trailer-ctl" hidden>
  <button class="round" data-trailer-sound="1" aria-label="Sound on" title="Sound">${icon("i-mute")}</button>
  <button class="round" data-trailer-replay="1" aria-label="Play the trailer again" title="Play the trailer again" hidden>${icon("i-repeat")}</button></div>`;
function stopTrailer() {
  clearTimeout(trailerTimer);
  document.querySelectorAll("video.trailer").forEach(dropClip);
  document.querySelectorAll(".hero.trailer-on").forEach(h => h.classList.remove("trailer-on"));
}
function trailerSoundBtn(v) {
  const b = $("[data-trailer-sound]"); if (!b) return;
  b.innerHTML = icon(v && !v.muted ? "i-vol" : "i-mute");
  b.setAttribute("aria-label", v && !v.muted ? "Sound off" : "Sound on");
}
function endTrailer(v) {
  const hero = v.closest(".hero"), ctl = hero && $(".trailer-ctl", hero);
  v.classList.remove("on");
  if (hero) hero.classList.remove("trailer-on");
  if (ctl) { $("[data-trailer-sound]", ctl).hidden = true; $("[data-trailer-replay]", ctl).hidden = false; }
  setTimeout(() => dropClip(v), 1300);
}
function keepTrailer(v) {
  const hero = $(".hero[data-trailer]");
  if (!hero) return dropClip(v);
  hero.dataset.trailer = v.dataset.id;
  const bg = $(".hero-bg", hero);
  if (bg) bg.after(v); else hero.prepend(v);
  if (!v.classList.contains("on")) return;
  hero.classList.add("trailer-on");
  const ctl = $(".trailer-ctl", hero);
  if (ctl) ctl.hidden = false;
  trailerSoundBtn(v);
}
function startTrailer(now) {
  stopTrailer();
  trailerHash = location.hash;
  const hero = $(".hero[data-trailer]");
  if (!hero || !hero.dataset.trailer || REDUCED || prefs.get("trailers", true) === false) return;
  trailerTimer = setTimeout(async () => {
    const id = hero.dataset.trailer;
    let plan;
    try { plan = await api("/api/play/" + encodeURIComponent(id) + "?trailer=1&" + Player.capsQuery()); } catch (e) { return; }
    if (!document.contains(hero) || Player.isOpen() || document.hidden || $("video.trailer", hero)) return;
    const d = plan.duration || 0;
    let src = "/media/" + encodeURIComponent(id) + "/preview.mp4?hd=1";
    if (d >= 8 * 60 && plan.trailer !== "clip" && plan.mode !== "unsupported") {
      const from = Math.round(Math.min(d * (0.12 + Math.random() * 0.5), d - TRAILER_SECONDS - 120));
      src = plan.trailer === "direct" ? plan.url + "?trailer=1#t=" + from
        : "/media/" + encodeURIComponent(id) + "/stream?trailer=1&mode=" + plan.mode + "&t=" + from + (plan.mode === "transcode" ? "&h=480" : "");
    }
    const v = document.createElement("video");
    v.className = "hero-clip trailer"; v.dataset.id = id; v.playsInline = true; v.preload = "auto"; v.setAttribute("playsinline", "");
    v.muted = !prefs.get("trailerSound", false);
    const ctl = $(".trailer-ctl", hero);
    let start = null;
    v.addEventListener("playing", () => {
      v.classList.add("on"); hero.classList.add("trailer-on");
      if (ctl) { ctl.hidden = false; $("[data-trailer-sound]", ctl).hidden = false; $("[data-trailer-replay]", ctl).hidden = true; }
      trailerSoundBtn(v);
    }, { once: true });
    v.addEventListener("timeupdate", () => {
      if (start === null && v.currentTime > 0) start = v.currentTime;
      if (start !== null && v.currentTime - start >= TRAILER_SECONDS) endTrailer(v);
    });
    v.addEventListener("ended", () => endTrailer(v));
    v.addEventListener("error", () => { dropClip(v); hero.classList.remove("trailer-on"); }, { once: true });
    v.src = src;
    const bg = $(".hero-bg", hero);
    if (bg) bg.after(v); else hero.prepend(v);
    v.play().catch(() => { if (!v.muted) { v.muted = true; trailerSoundBtn(v); v.play().catch(() => {}); } });
  }, now ? 0 : 2500);
}
function viewHome() {
  if (!shows.length && !movies.length) return viewEmptyLibrary();
  const slides = heroSlides();
  setGlow(slides[0] && (slides[0].backdrop || slides[0].poster));
  const cont = Object.keys(progress).filter(id => byId.has(id) && inProgress(id) && notAdult(byId.get(id)) && !hiddenFromRows(byId.get(id)))
    .sort((a, b) => progress[b].at - progress[a].at).slice(0, 14).map(id => byId.get(id));
  const fresh = shows.map(s => ({ s, eps: newEpisodes(s) })).filter(x => x.eps.length && !hiddenFromRows(x.s))
    .sort((a, b) => Math.max(...b.eps.map(e => e.added)) - Math.max(...a.eps.map(e => e.added)));
  const freshShows = new Set(fresh.map(x => x.s));
  const nextUps = shows.map(s => ({ s, n: upNext(s) }))
    .filter(x => x.n && !x.n.fresh && !x.n.resume && !freshShows.has(x.s) && !hiddenFromRows(x.s)).sort((a, b) => lastTouched(b.s) - lastTouched(a.s))
    .map(x => wideCard(x.n.ep));
  const newEps = fresh.map(x => {                       // plays what comes next for you; says how many are new
    const nx = upNext(x.s), ep = nx && !nx.fresh ? nx.ep : x.eps[0];
    return wideCard(ep, (x.eps.length > 1 ? plural(x.eps.length, "new episode") : "New episode " + epCode(x.eps[0])) +
      (ep !== x.eps[0] ? " · next for you: " + epCode(ep) : ""));
  });
  const added = shows.flatMap(s => s.order).sort((a, b) => b.added - a.added).slice(0, 14);
  const newMovies = movies.slice().sort((a, b) => b.added - a.added).slice(0, 14);
  // A different few each day (the same all day, so rows don't jump about).
  const day = Math.floor(Date.now() / 864e5), mix = list => list.map(x => [x, hue(x.id + day)]).sort((a, b) => a[1] - b[1]).map(p => p[0]);
  const minutes = x => x.runtime || (x.duration ? x.duration / 60 : 0);
  const films = movies.filter(m => m.collection !== "Home Videos");
  const shortOnes = mix(films.filter(m => !prog(m.id) && minutes(m) && minutes(m) <= 95)
    .concat(shows.filter(s => !lastTouched(s) && s.runtime && s.runtime <= 30))).slice(0, 20);
  const unseenMovies = mix(films.filter(m => !prog(m.id) && !newMovies.includes(m))).slice(0, 20);
  const rows = {
    banner: heroCarousel,
    continue: () => rail("Continue watching", "wide", cont.map(i => wideCard(i))),
    "new-episodes": () => rail("New episodes", "wide", newEps),
    "coming-up": () => rail("Coming up", "posters", shows.filter(s => s.next_air && lastTouched(s) && (new Date(s.next_air.aired + "T12:00:00") - Date.now()) < 31 * 864e5)
      .sort((a, b) => a.next_air.aired.localeCompare(b.next_air.aired))
      .map(s => posterCard(s, epCode({ kind: "episode", s: s.next_air.s, e: s.next_air.e }) + " · " + airDay(s.next_air.aired)))),
    "next-up": () => rail("Next up", "wide", nextUps),
    "my-list": () => rail("My List", "posters", myList().map(x => x.seasons ? posterCard(x) : movieCard(x)), "#/mylist"),
    because: becauseYouWatched,
    shows: () => rail("Shows", "posters", shows.slice().sort((a, b) => lastTouched(b) - lastTouched(a) || b.added - a.added).slice(0, 30).map(posterCard), "#/shows"),
    "new-movies": () => rail("New movies", "posters", newMovies.map(movieCard), "#/movies"),
    short: () => shortOnes.length >= 4 ? rail("Something short", "posters", shortOnes.map(x => x.seasons ? posterCard(x) : movieCard(x))) : "",
    unseen: () => unseenMovies.length >= 6 ? rail("Movies you haven't seen", "posters", unseenMovies.map(movieCard), "#/movies") : "",
    "recent-episodes": () => rail("Recently added episodes", "wide", added.map(i => wideCard(i))),
    genres: () => [...genreMap(shows.concat(movies))].filter(([, l]) => l.length >= 3).slice(0, 6).map(([g, l]) =>
      rail(g, "posters", l.slice(0, 20).map(x => x.seasons ? posterCard(x) : movieCard(x)),
           (l.some(x => x.seasons) && !l.some(x => !x.seasons) ? "#/shows/" : "#/movies/") + encodeURIComponent(g))).join("")
  };
  const { order, hidden } = homeLayout();
  return appOffer() + order.filter(id => !hidden.has(id)).map(id => rows[id]()).join("") +
    (session.user.guest ? "" : `<div class="home-edit"><button class="btn ghost" data-home-edit="1">${icon("i-palette")}Arrange Home</button></div>`);
}
/* What's on Home, and in which order: each profile's own (on every screen), or Sofa's. The banner stays
   at the top when it's on. */
const HOME_ROWS = [["banner", "Featured banner"], ["continue", "Continue watching"], ["new-episodes", "New episodes"],
  ["coming-up", "Coming up"], ["next-up", "Next up"], ["my-list", "My List"], ["because", "Because you watched…"],
  ["shows", "Shows"], ["new-movies", "New movies"], ["short", "Something short"], ["unseen", "Movies you haven't seen"],
  ["recent-episodes", "Recently added episodes"], ["genres", "A row for each genre"]];
function homeLayout() {
  const mine = (session && session.user && session.user.prefs && session.user.prefs.home) || {};
  const known = HOME_ROWS.map(r => r[0]);
  const order = (mine.order || []).filter((id, i, a) => known.includes(id) && a.indexOf(id) === i && id !== "banner");
  known.forEach((id, i) => { if (id !== "banner" && !order.includes(id)) order.splice(Math.min(i, order.length), 0, id); });   // rows Sofa added since
  return { order: ["banner"].concat(order), hidden: new Set(mine.hidden || []) };
}
let homeSave = 0;
function saveHome(layout) {
  session.user.prefs = Object.assign({}, session.user.prefs, { home: layout ? { order: layout.order, hidden: [...layout.hidden] } : undefined });
  if (!layout) delete session.user.prefs.home;
  clearTimeout(homeSave);
  homeSave = setTimeout(() => api("/api/me/prefs", { home: layout ? session.user.prefs.home : null }).catch(e => toast(e.message)), 400);
}
function homeDialog() {
  const label = id => (HOME_ROWS.find(r => r[0] === id) || [id, id])[1];
  const list = () => { const { order, hidden } = homeLayout(); return order.map((id, i) => `<li class="home-row${hidden.has(id) ? " off" : ""}">
      <span class="grip">${i ? i : "★"}</span><b>${esc(label(id))}</b>
      ${id === "banner" ? `<span class="spacer"></span><span class="spacer"></span>` : `<button class="mini" data-row-move="${id}" data-by="-1" aria-label="Move ${esc(label(id))} up"${i <= 1 ? " disabled" : ""}>↑</button>
      <button class="mini" data-row-move="${id}" data-by="1" aria-label="Move ${esc(label(id))} down"${i === order.length - 1 ? " disabled" : ""}>↓</button>`}
      <button class="switch" role="switch" aria-checked="${!hidden.has(id)}" data-row-show="${id}" aria-label="Show ${esc(label(id))}"></button></li>`).join(""); };
  const d = openDialog(`<h2>Arrange Home</h2><p>What ${esc(session.user.name)} sees on Home, top to bottom, on every screen. Rows with nothing in them don't show.</p>
    <ol class="home-rows">${list()}</ol>
    <div class="actions"><button class="btn ghost" data-home-reset="1">Sofa's own</button><button class="btn primary" data-dismiss="1">Done</button></div>`);
  d.addEventListener("click", e => {
    const t = e.target.closest("[data-row-move],[data-row-show],[data-home-reset]"); if (!t) return;
    const lay = homeLayout(), key = t.dataset.rowMove ? `[data-row-move="${t.dataset.rowMove}"][data-by="${t.dataset.by}"]` : t.dataset.rowShow ? `[data-row-show="${t.dataset.rowShow}"]` : "[data-home-reset]";
    if (t.dataset.homeReset) saveHome(null);
    else if (t.dataset.rowShow) { const id = t.dataset.rowShow; if (lay.hidden.has(id)) lay.hidden.delete(id); else lay.hidden.add(id); saveHome(lay); }
    else {
      const i = lay.order.indexOf(t.dataset.rowMove), j = i + +t.dataset.by;
      if (j < 1 || j >= lay.order.length) return;
      [lay.order[i], lay.order[j]] = [lay.order[j], lay.order[i]]; saveHome(lay);
    }
    $(".home-rows", d).innerHTML = list();
    const again = $(key, d); (again && !again.disabled ? again : $("[data-dismiss]", d)).focus();
    if (location.hash === "#/" || !location.hash) rerender();
  });
}
document.addEventListener("click", e => { if (e.target.closest("[data-home-edit]")) { if (document.querySelector(".dialog-scrim")) history.back(); setTimeout(homeDialog, 60); } });
/* ---------- Sofa's Fire TV app ----------
   In Silk on a Fire TV: "Install the Sofa app". Sofa keeps the app on its computer and installs it on this
   Fire TV over the home network (it asks once, on the TV). Inside the app: "Update" when Sofa has a newer one. */
let appsInfo = null;
// Builds before 5 didn't say their number (they're 4 or older).
const appVersion = () => { try { return NATIVE && NATIVE.appVersion ? +NATIVE.appVersion() : 4; } catch (e) { return 4; } };
function appOffer() {
  if (!FIRE_TV || session.user.guest || Date.now() - prefs.get("appOfferHidden", 0) < 30 * 864e5) return "";
  const latest = appsInfo && appsInfo.firetv && appsInfo.firetv.version;
  if (NATIVE && !(latest && latest > appVersion())) return "";
  const [title, text, go] = NATIVE
    ? ["A newer Sofa app is ready", "It updates in a few seconds and opens again.", "Update the app"]
    : ["Sofa has an app for this Fire TV", "It plays your files as they are, so videos start straight away and never stop to convert. Sofa puts it on this Fire TV for you.", "Install the Sofa app"];
  return `<section class="app-offer"><div><b>${title}</b><span>${text}</span></div>
    <div class="row-actions"><button class="btn primary" data-app-install="1">${go}</button><button class="btn ghost" data-app-later="1">Not now</button></div></section>`;
}
function appInstallDialog() {
  const update = !!NATIVE;
  const d = openDialog(`<h2>${update ? "Update the Sofa app" : "Install the Sofa app"}</h2>
    ${update ? `<p>Sofa puts the newer app on this Fire TV, then opens it again.</p>` : `<ol class="app-steps">
      <li>On this Fire TV, turn on <b>ADB debugging</b>: Settings (⚙) → My Fire TV → Developer options → ADB debugging → On.
        <span class="hint">No Developer options? Settings → My Fire TV → About, press OK on the Fire TV's name 7 times, then go back.</span></li>
      <li>Come back here and press <b>Install</b>. The TV asks "Allow USB debugging?": tick <b>Always allow from this computer</b>, then <b>OK</b>.</li>
    </ol>`}
    <p class="app-progress" role="status" hidden></p><div class="up-bar app-bar" hidden><i></i></div>
    <div class="other-way" hidden><p class="hint">Or the other way: install <b>Downloader</b> from the Amazon Appstore, allow it under
      Settings → My Fire TV → Developer options → Install unknown apps, open it, and type <code>${esc(location.origin)}/firetv</code></p></div>
    <div class="actions"><button class="btn primary" data-app-go="1">${update ? "Update" : "Install"}</button><button class="btn ghost" data-dismiss="1">Close</button></div>`);
  const msg = $(".app-progress", d), bar = $(".app-bar", d), go = $("[data-app-go]", d);
  go.focus();
  const show = st => {
    msg.hidden = false; msg.textContent = st.message || "";
    msg.classList.toggle("bad", st.state === "failed"); msg.classList.toggle("good", st.state === "done");
    bar.hidden = st.progress == null || st.state !== "copying";
    if (!bar.hidden) $("i", bar).style.width = Math.round(st.progress * 100) + "%";
    $(".other-way", d).hidden = st.state !== "failed" || update;
  };
  go.addEventListener("click", async () => {
    go.disabled = true;
    let st;
    try { st = await api("/api/apps/firetv/install", {}); } catch (e) { show({ state: "failed", message: e.message }); go.disabled = false; return; }
    show(st);
    while (d.isConnected && !["done", "failed"].includes(st.state)) {
      await new Promise(r => setTimeout(r, 700));
      try { st = await api("/api/apps/firetv/install"); show(st); } catch (e) {}
    }
    go.disabled = false;
    if (st.state === "done") {
      prefs.set("appOfferHidden", Date.now()); document.querySelectorAll(".app-offer").forEach(x => x.remove());
      go.textContent = update ? "Update" : "Install again"; $("[data-dismiss]", d).focus();
    }
    else { go.textContent = "Try again"; go.focus(); }
  });
}
document.addEventListener("click", e => {
  const b = e.target.closest("[data-app-install],[data-app-later],[data-apps-fetch]"); if (!b) return;
  if (b.dataset.appLater) { prefs.set("appOfferHidden", Date.now()); const s = b.closest(".app-offer"); if (s) s.remove(); return; }
  if (b.dataset.appsFetch) {
    api("/api/admin/apps/fetch", {}).then(() => toast("Getting the newest Fire TV app. It shows here in a minute."), err => toast(err.message));
    return;
  }
  appInstallDialog();
});
/* Phones: the bottom bar has Home, Shows, Movies, My List and More; More has the rest. */
function viewMore() {
  setGlow("");
  const row = (href, ic, label, sub, attr) => `<${href ? `a href="${href}"` : `button ${attr}`} class="more-row">${icon(ic)}<span><b>${label}</b>${sub ? `<small>${sub}</small>` : ""}</span></${href ? "a" : "button"}>`;
  const u = session.user;
  return `<section class="more-page"><div class="more-me">${avatar(u, "")}<div><b>${esc(u.name)}</b><small>${u.guest ? "Guest" : u.kids ? "Kids profile" : u.admin ? "Runs this Sofa" : "Profile"}</small></div></div>
    <div class="more-list">
      ${row("#/music", "i-music", "Music", "Albums, artists, stations")}
      ${u.kids ? "" : row("#/live", "i-live", "Live TV", "Free channels")}
      ${u.adult && !$("#navAdult").hidden ? row("#/adult", "i-lock", "Adult", "") : ""}
      ${row("#/search", "i-search", "Search", "")}
    </div>
    <div class="more-list">
      ${u.guest ? "" : row("", "i-palette", "Theme", "Colours, subtitles, this device", 'data-more="theme"')}
      ${u.guest ? "" : row("", "i-tv", "Pair a TV", "Sign a TV in with this phone", 'data-more="pair"')}
      ${standalone() ? "" : row("", "i-phone", "Install Sofa", "On the home screen, like an app", 'data-more="install"')}
      ${u.admin ? row("#/server", "i-gear", "Server", "Library, people, internet, updates") : ""}
      ${window.SofaBox ? row("#/box", "i-tv", "This Sofa box", "Picture, sound, boot screen, Wi-Fi, controllers") : ""}
      ${row("", "i-exit", u.guest ? "Leave" : "Sign out", "", 'data-more="out"')}
    </div></section>`;
}
document.addEventListener("click", e => {
  const b = e.target.closest("[data-more]"); if (!b) return;
  const a = b.dataset.more;
  if (a === "theme") appearanceDialog();
  else if (a === "pair") location.hash = "#/pair";
  else if (a === "out") signOut();
  else if (a === "install") { prefs.set("installAsk", 0); installOffer(true); }
});
/* ---------- this Sofa box (a Raspberry Pi on the TV): its own settings, from the sofa ----------
   Only on the box: its agent (127.0.0.1:8091, the page's own address there) answers /box/api/... */
let boxData = null, boxNets = null, boxNet = null, boxMsg = "", boxArmed = "";
async function loadBox(after) {
  try { boxData = await (await fetch("/box/api/info")).json(); } catch (e) { boxData = { error: "The box doesn't answer." }; }
  if (after) after();
  if (location.hash === "#/box" && !Player.isOpen() && !document.querySelector(".dialog-scrim")) {
    const a = document.activeElement, key = a && a.dataset && a.dataset.boxKey;
    const y = scrollY; view.innerHTML = viewBox(); scrollTo(0, y);
    const again = key && $(`[data-box-key="${CSS.escape(key)}"]`); if (again) again.focus({ preventScroll: true });
  }
}
async function boxPost(path, body) {
  const r = await fetch("/box/api/" + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  return r.json();
}
function viewBox() {
  setGlow("");
  if (!boxData) { loadBox(); return `<section class="admin box-page"><div class="admin-head"><h1>This Sofa box</h1></div><p class="admin-lede">Loading…</p></section>`; }
  if (boxData.error) return `<section class="admin box-page"><div class="admin-head"><h1>This Sofa box</h1></div><p class="admin-lede">${esc(boxData.error)}</p></section>`;
  const b = boxData, s = b.settings;
  const pick = (key, value, label) => `<button data-box-set="${key}" data-box-value="${value}" data-box-key="${key}-${value}" aria-pressed="${String(s[key]) === String(value)}">${label}</button>`;
  const act = (a, label, cls) => `<button class="btn${cls ? " " + cls : ""}" data-box-act="${a}" data-box-key="act-${a}">${boxArmed === a ? "Press again to " + label.toLowerCase() : label}</button>`;
  const facts = [b.model, b.address, b.temperature != null ? b.temperature + " °C" : "", b.memory ? Math.round(b.memory / 1048576) + " MB" : ""].filter(Boolean);
  const themes = THEMES.map(t => `<button class="theme-swatch" data-box-set="theme" data-box-value="${t[0]}" data-box-key="theme-${t[0]}" aria-pressed="${s.theme === t[0]}"
      style="--sw-bg:${t[2]};--sw-ac:${t[3]}"><i></i><span>${esc(t[1])}</span></button>`).join("");
  return `<section class="admin box-page"><div class="admin-head"><h1>This Sofa box</h1><span class="pill">Version ${esc(b.version)}</span></div>
    <p class="admin-lede">${facts.map(esc).join(" · ")}${b.server ? ` · plays from ${esc(b.server_name || "Sofa")} (${esc(b.server.replace(/^https?:\/\//, ""))})` : ""}</p>
    ${boxMsg ? `<div class="box-msg" role="status">${esc(boxMsg)}</div>` : ""}
    <div class="panels">
      <div class="panel"><h2>Picture</h2>
        <p class="hint">Sofa sends videos the box can play smoothly. ${b.slow_board ? "A Raspberry Pi 3 plays up to 1080p H.264; Sofa converts the rest for it." : ""}</p>
        <div class="sorter inline" role="group" aria-label="Picture">${pick("quality", "auto", "Automatic")}${pick("quality", "1080", "1080p")}${pick("quality", "720", "720p")}</div>
        ${b.learned_720 && s.quality === "auto" ? `<p class="hint box-note">Videos come as 720p: at 1080p this box dropped frames.</p>${act("forget-720", "Try 1080p again")}` : ""}
      </div>
      <div class="panel"><h2>Sound</h2>
        <p class="hint">Surround goes as it is to an AV receiver or soundbar that decodes it; otherwise the box mixes it for the TV.</p>
        <div class="sorter inline" role="group" aria-label="Sound">${pick("audio", "auto", "TV or soundbar")}${pick("audio", "passthrough", "AV receiver (surround)")}</div>
      </div>
      <div class="panel wide"><h2>Boot screen</h2>
        <p class="hint">What the TV shows while the box starts: Sofa's own loading screen in a colour of your choice, with a name under it.</p>
        <div class="box-boot"><img src="/box/splash.png?phase=0.45&amp;v=${encodeURIComponent(s.theme + s.boot_text)}" alt="The boot screen">
          <div><div class="themes">${themes}</div>
            <label class="field"><span>Name under the logo</span><input data-box-text="boot_text" data-box-key="boot-text" maxlength="30" value="${esc(s.boot_text || "")}" placeholder="Living room"></label>
            ${act("apply-boot", "Use it from the next start", "primary")}</div></div>
      </div>
      <div class="panel"><h2>Wi-Fi</h2>
        <p class="hint">${b.wifi ? `Connected to <b>${esc(b.wifi)}</b>.` : "Not on Wi-Fi (a network cable works best for video)."}</p>
        ${boxNets ? (boxNets.length ? `<div class="box-nets">${boxNets.map(n => `<button class="box-net" data-box-net="${esc(n.ssid)}" data-box-key="net-${esc(n.ssid)}" aria-pressed="${boxNet === n.ssid}"><b>${esc(n.ssid)}</b><small>${n.signal}%${n.secure ? " · password" : ""}</small></button>`).join("")}</div>` : `<p class="hint">No networks found.</p>`) : ""}
        ${boxNet ? `<label class="field"><span>Password for ${esc(boxNet)}</span><input type="password" data-box-key="wifi-pass" id="boxWifiPass" autocomplete="off"></label>${act("wifi-connect", "Connect", "primary")}` : act("wifi-scan", boxNets ? "Look again" : "Find networks")}
      </div>
      <div class="panel"><h2>Controllers and remotes</h2>
        <p class="hint">${b.controllers.length ? "Paired: " + b.controllers.map(esc).join(", ") + "." : "No game controllers paired yet."} The TV's own remote works over HDMI when the TV's CEC is on (VIERA Link, Anynet+, SimpLink).</p>
        <div class="row-btns">${act("pair-controller", "Pair a controller")}${act("tv-on", "Turn the TV on")}</div>
      </div>
      <div class="panel wide"><h2>The box</h2>
        <p class="hint">To check everything over SSH: <code>sofa-box doctor</code>.</p>
        <div class="row-btns">${act("choose", "Use another Sofa")}${act("restart", "Restart Sofa")}${act("reboot", "Restart the box")}</div>
      </div>
    </div></section>`;
}
document.addEventListener("click", async e => {
  const t = e.target.closest("[data-box-set],[data-box-act],[data-box-net]"); if (!t) return;
  e.preventDefault();
  if (t.dataset.boxSet) {
    const v = t.dataset.boxValue;
    boxData = Object.assign(await boxPost("settings", { [t.dataset.boxSet]: v }), {});
    boxMsg = t.dataset.boxSet === "theme" ? "Colour chosen: press “Use it from the next start” to keep it." : "Saved.";
    return loadBox();
  }
  if (t.dataset.boxNet) { boxNet = t.dataset.boxNet; loadBox(() => {}); setTimeout(() => { const p = $("#boxWifiPass"); if (p) p.focus(); }, 300); return; }
  const a = t.dataset.boxAct;
  if ((a === "reboot" || a === "restart" || a === "choose") && boxArmed !== a) { boxArmed = a; return loadBox(); }   // twice, so a stray OK doesn't
  boxArmed = "";
  if (a === "apply-boot") {
    const input = $("[data-box-text]");
    if (input) await boxPost("settings", { boot_text: input.value });
  }
  boxMsg = a === "wifi-scan" ? "Looking for networks…" : a === "wifi-connect" ? "Connecting…" : "";
  if (boxMsg) loadBox();
  const body = a === "wifi-connect" ? { ssid: boxNet, password: ($("#boxWifiPass") || {}).value || "" } : {};
  let r;
  try { r = await boxPost("action/" + a, body); } catch (err) { r = { ok: false, message: "The box doesn't answer." }; }
  if (a === "wifi-scan") boxNets = r.networks || [];
  if (a === "wifi-connect" && r.ok) { boxNet = null; boxNets = null; }
  if (r.go) { location.href = r.go; return; }
  boxMsg = r.message || (r.ok ? (a === "restart" || a === "reboot" ? "Restarting…" : "Done.") : "That didn't work.");
  loadBox();
});
document.addEventListener("change", e => {
  const t = e.target.closest("[data-box-text]"); if (!t) return;
  boxPost("settings", { [t.dataset.boxText]: t.value }).then(d => { boxData = d; boxMsg = "Saved."; loadBox(); });
});
function viewEmptyLibrary() {
  setGlow("");
  if (LIB.reading) return `<section class="empty"><i class="reading-spin" aria-hidden="true"></i><h1>Sofa is reading your library</h1>
    <p>It just started. Your shows and movies appear here in a moment, by themselves.</p></section>`;
  return `<section class="empty"><h1>Nothing to watch yet</h1>
    <p>Drop shows and movies into the <b>Inbox</b> folder on the server. Sofa names them, files them and adds artwork within a minute.</p>
    ${session.user.admin ? `<p><a class="btn" href="#/server">Open the Server page</a></p>` : ""}</section>`;
}
const SORTS = {
  name: ["Name", (a, b) => a.name.localeCompare(b.name)],
  added: ["Recently added", (a, b) => b.added - a.added],
  size: ["Most episodes", (a, b) => b.count - a.count],
  year: ["Premiered", (a, b) => (a.premiered || "9").localeCompare(b.premiered || "9")]
};
/* Genres: from TVmaze (shows), and TMDB, the iTunes Store or .nfo files (movies). */
function genreMap(list) {
  const m = new Map();
  list.forEach(x => (x.genres || []).forEach(g => { if (!m.has(g)) m.set(g, []); m.get(g).push(x); }));
  return new Map([...m].sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0])));
}
function genreChips(map, base, current) {
  if (!map.size) return "";
  return `<div class="chips genre-chips" role="group" aria-label="Genres"><a class="chip" href="${base}" aria-current="${!current}">All</a>${[...map].map(([g, l]) =>
    `<a class="chip" href="${base}/${encodeURIComponent(g)}" aria-current="${g === current}">${esc(g)} <small>${l.length}</small></a>`).join("")}</div>`;
}
/* Filters on the Shows and Movies pages: a genre, what you've watched, and a box that matches names,
   genres, networks, studios, collections and years. A genre also lists titles with its name in the title
   (Adventure Time under Adventure), apart, since the services don't always file them there. */
let pageFilter = "", seenFilter = "all", filterPage = "";
const SEEN = { all: "All", new: "Not started", watching: "Watching", done: "Watched" };
function seenState(x) {
  if (x.seasons) {
    if (!lastTouched(x)) return "new";
    return x.order.length && x.order.every(ep => isDone(ep.id)) ? "done" : "watching";
  }
  return isDone(x.id) ? "done" : prog(x.id) ? "watching" : "new";
}
function filterMatch(x, q) {
  if (!q) return true;
  return [x.name, x.title, x.network, x.studio, x.collection, String(yearOf(x) || "")].concat(x.genres || [])
    .some(v => fold(v).includes(q));
}
function filterTools(kind) {
  const seen = seenFilter;
  return `<div class="filter-tools"><button class="btn" data-surprise="${kind}">${icon("i-shuffle")}Surprise me</button><input id="pageFilter" type="search" placeholder="Filter by name, genre, network or year" aria-label="Filter ${kind}" value="${esc(pageFilter)}" autocomplete="off">
    <div class="sorter" role="group" aria-label="What you've watched">${Object.keys(SEEN).map(k =>
      `<button data-seen="${k}" aria-pressed="${k === seen}">${SEEN[k]}</button>`).join("")}</div></div>`;
}
function applyFilters(list) {
  const seen = seenFilter, q = fold(pageFilter).trim();
  return list.filter(x => (seen === "all" || seenState(x) === seen) && filterMatch(x, q));
}
function namedLike(all, genre, already) {
  const g = fold(genre).trim();
  if (!g) return [];
  return all.filter(x => !already.includes(x) && (" " + fold(x.name || x.title).replace(/[^a-z0-9]+/g, " ") + " ").includes(" " + g + " "));
}
function viewShows(genre) {
  const gm = genreMap(shows);
  if (genre && !gm.has(genre)) genre = null;
  const pool = genre ? gm.get(genre) : shows;
  setGlow(pool[0] && pool[0].backdrop);
  const sort = SORTS[prefs.get("sort", "name")] ? prefs.get("sort", "name") : "name";
  const list = applyFilters(pool).sort(SORTS[sort][1]);
  const named = genre ? applyFilters(namedLike(shows, genre, pool)).sort(SORTS[sort][1]) : [];
  return `<section class="page"><div class="page-head"><h1>${esc(genre || "Shows")}</h1><span class="count">${plural(list.length, "show")}</span>
    <div class="sorter" role="group" aria-label="Sort shows">${Object.keys(SORTS).map(k =>
      `<button data-sort="${k}" aria-pressed="${k === sort}">${SORTS[k][0]}</button>`).join("")}</div></div>
    ${genreChips(gm, "#/shows", genre)}
    ${filterTools("shows")}
    ${list.length ? grid(list.map(posterCard)) : `<p class="count">No shows match.${pageFilter || seenFilter !== "all" ? " Try clearing the filter." : ""}</p>`}
    ${named.length ? `<h2 class="collection-title">With "${esc(genre)}" in the name</h2><div class="grid">${named.map(posterCard).join("")}</div>` : ""}</section>`;
}
const MSORTS = {
  name: ["Name", (a, b) => a.title.localeCompare(b.title)],
  added: ["Recently added", (a, b) => b.added - a.added],
  year: ["Year", (a, b) => (b.year || 0) - (a.year || 0)]
};
function collections(list) {
  const groups = new Map();
  list.forEach(m => { if (m.collection) { if (!groups.has(m.collection)) groups.set(m.collection, []); groups.get(m.collection).push(m); } });
  return groups;
}
function viewMovies(list, heading, base, genre) {
  list = list || movies; heading = heading || "Movies"; base = base || "#/movies";
  const all = list, gm = genreMap(list);
  if (genre && gm.has(genre)) { list = gm.get(genre); heading = genre; } else genre = null;
  setGlow(list[0] && (list[0].backdrop || list[0].poster));
  const sort = MSORTS[prefs.get("msort", "name")] ? prefs.get("msort", "name") : "name";
  const filtering = !!pageFilter.trim() || seenFilter !== "all";
  const shown = applyFilters(list), groups = collections(shown);
  const sorted = shown.sort(MSORTS[sort][1]);
  const named = genre ? applyFilters(namedLike(all, genre, list)).sort(MSORTS[sort][1]) : [];
  let html = `<section class="page"><div class="page-head"><h1>${esc(heading)}</h1><span class="count">${plural(shown.length, "movie")}</span>
    <div class="sorter" role="group" aria-label="Sort movies">${Object.keys(MSORTS).map(k =>
      `<button data-msort="${k}" aria-pressed="${k === sort}">${MSORTS[k][0]}</button>`).join("")}</div></div>`;
  html += genreChips(gm, base, genre);
  if (list.length) html += filterTools("movies");
  if (!list.length) html += `<p class="count">No movies yet. Drop one in the Inbox, named like "Title (1999)".</p>`;
  else if (!shown.length) html += `<p class="count">No movies match. Try clearing the filter.</p>`;
  if (groups.size && !genre && !filtering) html += `<h2 class="collection-title">Collections</h2><div class="grid">${[...groups].sort((a, b) => a[0].localeCompare(b[0]))
    .map(([name, l]) => collectionCard(name, l)).join("")}</div><h2 class="collection-title">All movies</h2>`;
  return html + grid(sorted.map(movieCard)) +
    (named.length ? `<h2 class="collection-title">With "${esc(genre)}" in the name</h2><div class="grid">${named.map(movieCard).join("")}</div>` : "") + `</section>`;
}
function viewCollection(name) {
  const list = movies.concat(adultMovies).filter(m => m.collection === name).sort((a, b) => (a.year || 0) - (b.year || 0));
  if (!list.length) return viewMissing();
  const art = list.find(m => m.backdrop) || list.find(m => m.poster);
  setGlow(art && (art.backdrop || art.poster));
  const next = list.find(m => !isDone(m.id)) || list[0];
  return `<section class="hero short">${art && art.backdrop ? `<img class="hero-bg" src="${esc(artSrc(art.backdrop, 1280))}" alt="">` : ""}
    <div class="hero-body"><h1>${esc(name)}</h1><p class="facts"><span>${plural(list.length, "movie")}</span>
    <span>${esc([list[0].year, list[list.length - 1].year].filter(Boolean).filter((y, i, a) => a.indexOf(y) === i).join(" to "))}</span>
    <span>${list.filter(m => isDone(m.id)).length} watched</span></p>
    <div class="actions"><button class="btn primary" data-play="${esc(next.id)}">${icon("i-play")}${inProgress(next.id) ? "Resume" : "Play"} <small>${esc(next.title)}</small></button></div></div></section>
    <section class="page${list.some(m => m.adult) ? " adult-page" : ""}"><div class="grid">${list.map(movieCard).join("")}</div></section>`;
}
function viewMovie(id) {
  const m = byId.get(id);
  if (!m || m.kind !== "movie") return viewMissing();
  setGlow(m.adult ? "" : m.backdrop || m.poster);
  const p = prog(m.id), resume = inProgress(m.id);
  const link = (kind, v) => `<a href="#/adult/${kind}/${encodeURIComponent(v)}">${esc(v)}</a>`;
  const runtime = m.runtime || (p && p.d ? Math.round(p.d / 60) : null);
  const facts = [m.year ? `<span><b>${esc(m.year)}</b></span>` : "", runtime ? `<span>${Math.floor(runtime / 60) ? Math.floor(runtime / 60) + " h " : ""}${runtime % 60} min</span>` : "",
    m.certificate ? `<span class="cert">${esc(m.certificate)}</span>` : "", m.genres && m.genres.length ? `<span>${esc(m.genres.join(", "))}</span>` : "",
    m.studio ? `<span>${m.adult ? link("studio", m.studio) : esc(m.studio)}</span>` : "", m.date && m.adult ? `<span>${esc(fmtDate(m.date))}</span>` : "",
    m.adult && m.height ? `<span class="cert">${esc(quality(m.height))}</span>` : "",
    m.adult && m.category ? `<a href="#/adult/category/${encodeURIComponent(m.category)}">${esc(m.category)}</a>` : "",
    m.rating ? `<span>Rated <b>${esc(Number(m.rating).toFixed(1))}</b></span>` : "",
    m.collection ? `<a href="#/collection/${encodeURIComponent(m.collection)}">${esc(m.collection)}</a>` : ""].join("");
  const sibs = m.collection ? movies.concat(adultMovies).filter(x => x.collection === m.collection && x.id !== m.id)
    : m.adult && m.studio ? adultMovies.filter(x => x.studio === m.studio && x.id !== m.id).slice(0, 20) : [];
  return `<section class="hero movie-hero" data-trailer="${esc(m.id)}">${trailerCtl()}
    ${m.backdrop || ((m.adult || m.poster_still) && m.poster) ? `<img class="hero-bg" src="${esc(artSrc(m.backdrop || m.poster, 1280))}" alt="">` : m.poster ? `<img class="hero-bg blur" src="${esc(artSrc(m.poster, 480))}" alt="">` : ""}
    <div class="hero-body movie-body${m.adult ? " scene-body" : ""}">
      <span class="frame poster-frame${m.poster ? "" : " noimg"}${dressed(m) ? " still-poster" : ""}">${dressed(m) ? stillPoster(m, 720) : frameImg(m.poster, m.title, m.title, m.adult ? 720 : 480)}</span>
      <div>
        ${m.logo ? `<img class="hero-logo" src="${esc(artSrc(m.logo, 720))}" alt="${esc(m.title)}">` : `<h1>${esc(m.title)}</h1>`}
        ${m.tagline ? `<p class="tagline">${esc(m.tagline)}</p>` : ""}
        <p class="facts">${facts}</p>
        ${m.performers && m.performers.length ? `<p class="facts"><span>With ${m.adult ? m.performers.map(x => link("performer", x)).join(", ") : esc(m.performers.join(", "))}</span></p>` : ""}
        ${m.adult && m.genres && m.genres.length ? `<p class="tag-cloud small">${m.genres.slice(0, 12).map(g => `<a class="tag-chip" href="#/adult/tag/${encodeURIComponent(g)}">${esc(g)}</a>`).join("")}</p>` : ""}
        ${m.summary ? `<p class="summary">${esc(m.summary)}</p>` : ""}
        <div class="actions">
          <button class="btn primary" data-play="${esc(m.id)}">${icon("i-play")}${resume ? "Resume" : "Play"}${resume ? ` <small>${esc(clock(p.d - p.t))} left</small>` : ""}</button>
          ${resume ? `<button class="btn" data-play-start="${esc(m.id)}">Start over</button>` : ""}
          ${inRows(m) ? forgetBtn(m) : ""}
          <button class="btn ghost" data-watched="${esc(m.id)}" aria-pressed="${isDone(m.id)}">${icon("i-check")}${isDone(m.id) ? "Watched" : "Mark watched"}</button>
          ${TV ? "" : `<button class="btn ghost" data-download="${esc(m.id)}">${icon("i-download")}Download</button>`}
          ${m.adult ? `<button class="btn ghost heart-btn" data-like="${esc(m.id)}" aria-pressed="${favs.has(m.id)}">♥ ${favs.has(m.id) ? "In Favorites" : "Favorite"}</button>` : listBtn(m.id)}
          ${session.user.admin ? `<button class="btn ghost" data-fix="${esc(m.id)}">${m.source ? "Fix details" : "Find details"}</button>
            <button class="btn ghost" data-manage="${esc(m.id)}">${icon("i-more")}Manage</button>${kidsBtn(m)}` : ""}
        </div>
        ${session.user.admin ? `<p class="fileline">${esc(m.file)}${m.source ? " · details from " + esc(m.source) : " · no details found yet"}</p>` : ""}
      </div></div></section>
    ${sibs.length ? rail("More " + (m.collection ? "in " + m.collection : "from " + m.studio), m.adult ? "scenes" : "posters", sibs.map(movieCard)) : ""}
    ${likeThisRail(m, sibs)}`;
}
/* ---------- the Adult section ---------- */
let adultQuery = "", adultList = [];
const ASORTS = {
  newest: ["Newest", (a, b) => b.added - a.added],
  date: ["Release date", (a, b) => (b.date || String(b.year || "")).localeCompare(a.date || String(a.year || ""))],
  name: ["Name", (a, b) => a.title.localeCompare(b.title)],
  longest: ["Longest", (a, b) => (b.duration || 0) - (a.duration || 0)]
};
function adultGroups(key) {
  const m = new Map();
  adultMovies.forEach(x => {
    const vals = key === "studio" ? [x.studio] : key === "performer" ? x.performers || [] : x.genres || [];
    vals.filter(Boolean).forEach(v => { if (!m.has(v)) m.set(v, []); m.get(v).push(x); });
  });
  return m;
}
function groupCard(kind, name, list) {
  const art = list.find(x => x.poster);
  return `<a class="card scene group-card" href="#/adult/${kind}/${encodeURIComponent(name)}" data-pv="${esc((list.find(x => x.duration) || list[0]).id)}">
    <span class="frame${art ? "" : " noimg"}">${art ? frameImg(art.poster, name, name) : `<span class="placeholder">${esc(name)}</span>`}
      <span class="stack-badge">${list.length}</span>${favs.has((kind === "performer" ? "perf:" : "studio:") + name) ? `<span class="fav-badge">♥</span>` : ""}</span>
    <span class="t1">${esc(name)}</span><span class="t2">${plural(list.length, "video")}</span></a>`;
}
function adultHero(list) {
  if (!list.length) return "";
  const slide = (x, i) => {
    const isShow = !!x.seasons, nx = isShow ? upNext(x) : null, name = x.name || x.title;
    const facts = [x.category, isShow ? plural(x.count, "episode") : x.duration ? dur(x.duration) : "", isShow ? "" : quality(x.height),
      x.studio].filter(Boolean).map(f => `<span>${esc(f)}</span>`).join("");
    const play = isShow ? nx && nx.ep.id : x.id;
    const clipId = isShow ? (nx || { ep: x.order[0] || {} }).ep.id : x.id;
    return `<div class="slide${i ? "" : " on"}" data-glow=""${clipId ? ` data-clip="${esc(clipId)}"` : ""} aria-hidden="${i ? "true" : "false"}">
      <img class="hero-bg" src="${esc(artSrc(x.backdrop || x.poster, 1280))}" alt=""${i ? ` loading="lazy"` : ""}>
      <div class="hero-body"><p class="eyebrow">${isShow ? "Series" : "New in Adult"}</p><h1>${esc(name)}</h1>
        <p class="facts">${facts}</p>
        ${x.performers && x.performers.length ? `<p class="facts"><span>With ${esc(x.performers.slice(0, 4).join(", "))}</span></p>` : ""}
        <div class="actions">${play ? `<button class="btn primary" data-play="${esc(play)}">${icon("i-play")}${inProgress(play) ? "Resume" : "Play"}</button>` : ""}
          <a class="btn" href="#/${isShow ? "show" : "movie"}/${encodeURIComponent(x.id)}">More info</a></div></div></div>`;
  };
  return `<section class="hero carousel adult-hero" aria-roledescription="carousel" aria-label="Featured">${list.map(slide).join("")}
    ${list.length > 1 ? `<div class="hero-dots" role="group" aria-label="Choose a featured title">${list.map((x, i) =>
      `<button data-slide="${i}" aria-label="${esc(x.name || x.title)}" aria-pressed="${!i}" tabindex="-1"></button>`).join("")}</div>` : ""}</section>`;
}
function adultMatch(x) {
  const q = adultQuery.trim().toLowerCase();
  if (!q) return true;
  return [x.title, x.name, x.studio, x.category].concat(x.performers || [], x.genres || []).some(v => (v || "").toLowerCase().includes(q));
}
function adultGrid(list, shows_) {
  const sort = ASORTS[prefs.get("asort", "newest")] ? prefs.get("asort", "newest") : "newest";
  adultList = list.filter(adultMatch).sort(ASORTS[sort][1]);
  const sh = (shows_ || []).filter(adultMatch);
  return `<div class="grid-tools"><div class="sorter" role="group" aria-label="Sort">${Object.keys(ASORTS).map(k =>
      `<button data-asort="${k}" aria-pressed="${k === sort}">${ASORTS[k][0]}</button>`).join("")}</div>
      ${adultList.length ? `<button class="btn" data-adult-play="all">${icon("i-play")}Play all</button><button class="btn" data-adult-play="shuffle">${icon("i-shuffle")}Shuffle</button>` : ""}</div>
    ${sh.length ? `<h2 class="collection-title">Series</h2><div class="grid">${sh.map(posterCard).join("")}</div>` : ""}
    ${sh.length && adultList.length ? `<h2 class="collection-title">Videos</h2>` : ""}
    ${grid(adultList.map(movieCard))}
    ${!adultList.length && !sh.length ? `<p class="count">${adultQuery ? `Nothing matches "${esc(adultQuery)}".` : "Nothing here yet."}</p>` : ""}`;
}
function viewAdult(rest) {
  setGlow("");
  if (!session.user.adult) return viewMissing();
  rest = rest || [];
  const tab = rest[0] || "all", arg = rest.slice(1).join("/");
  const cats = (LIB.adult && LIB.adult.categories) || [];
  const here = tab === "category" ? "category/" + arg : tab;
  const chips = [["all", "All"]].concat(cats.map(c => ["category/" + c, c]), [["studios", "Studios"], ["performers", "Performers"], ["tags", "Tags"], ["favorites", "Favorites"]]);
  const total = adultMovies.length + adultShows.reduce((n, s) => n + s.count, 0);
  let body = "", title = "Adult", sub = plural(total, "video"), hero = "";
  if (!total) body = `<p class="count" style="max-width:64ch">Nothing here yet. Drop adult videos into the <b>Inbox/XXX</b> folder on the server, or folders of them (keep your own folders like Hentai, Series, Collections: each becomes a category). ${session.user.admin ? `Or use <b>Add a link</b> to save a video from a website.` : ""} Only people allowed on the Server page can see this section; guests and TVs never can.</p>`;
  else if (tab === "all" && adultQuery) body = adultGrid(adultMovies, adultShows);
  else if (tab === "all") {
    const cont = Object.keys(progress).filter(id => byId.has(id) && inProgress(id) && !notAdult(byId.get(id)) && !hiddenFromRows(byId.get(id)))
      .sort((a, b) => progress[b].at - progress[a].at).slice(0, 14).map(id => byId.get(id));
    const fresh = adultMovies.concat(adultShows).sort((a, b) => b.added - a.added).slice(0, 20);
    const card = x => x.seasons ? posterCard(x) : movieCard(x);
    const perCat = cats.map(c => {
      const l = adultShows.filter(x => x.category === c).concat(adultMovies.filter(x => x.category === c).sort((a, b) => b.added - a.added));
      return rail(c, "scenes", l.slice(0, 24).map(card), "#/adult/category/" + encodeURIComponent(c));
    }).join("");
    const liked = adultMovies.filter(x => favs.has(x.id));
    const studios = [...adultGroups("studio")].sort((a, b) => b[1].length - a[1].length).slice(0, 16);
    const people = [...adultGroups("performer")].sort((a, b) => (favs.has("perf:" + b[0]) - favs.has("perf:" + a[0])) || b[1].length - a[1].length).slice(0, 16);
    hero = adultHero(fresh.filter(x => x.poster).slice(0, 6));
    body = rail("Continue watching", "wide", cont.map(i => wideCard(i))) +
      rail("New arrivals", "scenes", fresh.map(card)) + perCat +
      rail("Your favorites", "scenes", liked.map(movieCard), "#/adult/favorites") +
      rail("Studios", "scenes", studios.map(([n, l]) => groupCard("studio", n, l)), "#/adult/studios") +
      rail("Performers", "scenes", people.map(([n, l]) => groupCard("performer", n, l)), "#/adult/performers") +
      `<section class="row"><div class="row-head"><h2>Everything</h2></div>${adultGrid(adultMovies, [])}</section>`;
  } else if (tab === "category") {
    title = arg; const mv = adultMovies.filter(x => x.category === arg), sh = adultShows.filter(x => x.category === arg);
    sub = [sh.length ? sh.length + " series" : "", mv.length ? plural(mv.length, "video") : ""].filter(Boolean).join(" · ") || "Empty";
    const cols = collections(mv);
    body = (sh.length ? `<h2 class="collection-title">Series</h2><div class="grid">${sh.map(posterCard).join("")}</div>` : "") +
      (cols.size ? `<h2 class="collection-title">Collections</h2><div class="grid">${[...cols].map(([n, l]) => collectionCard(n, l)).join("")}</div>` : "") +
      (mv.length ? `<h2 class="collection-title">${sh.length || cols.size ? "Videos" : "All videos"}</h2>` + adultGrid(mv) : "");
  } else if (tab === "studios" || tab === "performers") {
    const kind = tab === "studios" ? "studio" : "performer", g = [...adultGroups(kind)].filter(([n, l]) => adultMatch({ title: n }) || l.some(adultMatch));
    g.sort((a, b) => (favs.has("perf:" + b[0]) - favs.has("perf:" + a[0])) || b[1].length - a[1].length || a[0].localeCompare(b[0]));
    body = g.length ? `<div class="grid">${g.map(([n, l]) => groupCard(kind, n, l)).join("")}</div>`
      : `<p class="count">No ${tab} yet. Sofa reads them from file names like <code>Studio.21.03.14.Jane.Doe.Title.mp4</code>, from .nfo files, from links you save, and from ThePornDB (Server, Settings).</p>`;
  } else if (tab === "tags") {
    const g = [...adultGroups("tag")].sort((a, b) => b[1].length - a[1].length);
    body = g.length ? `<div class="tag-cloud">${g.map(([n, l]) => `<a class="tag-chip" href="#/adult/tag/${encodeURIComponent(n)}">${esc(n)} <small>${l.length}</small></a>`).join("")}</div>`
      : `<p class="count">No tags yet. They come from links you save, .nfo files and ThePornDB.</p>`;
  } else if (tab === "favorites") {
    const mv = adultMovies.filter(x => favs.has(x.id)), people = [...adultGroups("performer")].filter(([n]) => favs.has("perf:" + n));
    body = (people.length ? `<h2 class="collection-title">Performers</h2><div class="grid">${people.map(([n, l]) => groupCard("performer", n, l)).join("")}</div><h2 class="collection-title">Videos</h2>` : "")
      + (mv.length ? adultGrid(mv) : `<p class="count">Press the ♥ on a video or a performer to keep it here.</p>`);
  } else if (tab === "studio" || tab === "performer" || tab === "tag") {
    const list = adultMovies.filter(x => tab === "studio" ? x.studio === arg : tab === "performer" ? (x.performers || []).includes(arg) : (x.genres || []).includes(arg));
    title = arg; sub = plural(list.length, "video") + " · " + { studio: "studio", performer: "performer", tag: "tag" }[tab];
    const key = (tab === "performer" ? "perf:" : tab === "studio" ? "studio:" : "");
    body = (key ? `<p><button class="btn ghost heart-btn" data-like="${esc(key + arg)}" aria-pressed="${favs.has(key + arg)}">♥ ${favs.has(key + arg) ? "In Favorites" : "Add to Favorites"}</button></p>` : "") + adultGrid(list);
  } else return viewMissing();
  return `${hero}<section class="page adult-page${hero ? " under-hero" : ""}"><div class="page-head"><h1>${esc(title)}</h1><span class="count">${esc(sub)}</span>
      <div class="adult-tools"><input id="adultSearch" type="search" placeholder="Search titles, studios, people, tags" aria-label="Search the Adult section" value="${esc(adultQuery)}">
      ${session.user.admin ? `<button class="btn" data-add-link="adult">+ Add a link</button><button class="btn" data-send-files="adult">+ Send files</button>` : ""}</div></div>
    <div class="chips" role="group" aria-label="Adult section">${chips.map(c => `<button data-adult-nav="${esc(c[0])}" aria-pressed="${c[0] === here}">${esc(c[1])}</button>`).join("")}</div>
    ${body}</section>`;
}
function episodeRow(ep, label) {
  const p = prog(ep.id), done = isDone(ep.id);
  const runtime = ep.runtime || (p && p.d ? Math.round(p.d / 60) : null);
  const meta = [
    runtime ? `<span>${runtime} min</span>` : "",
    ep.aired ? `<span>Aired ${esc(fmtDate(ep.aired))}</span>` : "",
    inProgress(ep.id) ? `<span>${esc(clock(p.d - p.t))} left</span>` : "",
    ep.subs ? `<span>Subtitles</span>` : ""
  ].join("");
  return `<article class="episode${done ? " watched" : p ? "" : " unseen"}">
    <button class="ep-thumb" data-play="${esc(ep.id)}" data-pv="${esc(ep.id)}" aria-label="Play ${esc(title(ep))}">${thumbFor(ep)}
      ${pct(ep.id) && !done ? `<span class="progress"><i style="width:${pct(ep.id)}%"></i></span>` : ""}
      ${done ? `<span class="seen-badge">${icon("i-check")}</span>` : ""}
      <span class="play-glyph">${icon("i-play")}</span></button>
    <div class="ep-text">
      ${label ? `<div class="t2">${esc(label)}</div>` : ""}
      <h3><span class="num">${esc(ep.kind === "episode" ? (ep.s === 0 ? "S" : "") + ep.e + (ep.e2 ? "–" + ep.e2 : "") : "")}</span>${esc(title(ep))}</h3>
      <p class="ep-meta">${meta}${TV ? "" : `<button class="ep-dl" data-download="${esc(ep.id)}" aria-label="Download ${esc(title(ep))}">${icon("i-download")}Download</button>`}</p>
      ${ep.summary ? `<p class="ep-sum clamp">${esc(ep.summary)}</p>` : ""}
    </div>
    <button class="tick" data-watched="${esc(ep.id)}" aria-pressed="${done}" aria-label="${done ? "Mark as not watched" : "Mark as watched"}" title="${done ? "Watched" : "Mark as watched"}">${icon("i-check")}</button>
    ${session.user.admin ? `<button class="tick" data-manage="${esc(ep.id)}" aria-label="Manage this episode" title="Move, delete or new picture">${icon("i-more")}</button>` : ""}
  </article>`;
}
/* The episode guide under a season: episodes that have aired but aren't in the library, and the next one
   to air (from what TVmaze listed, so nothing is looked up for it). */
function guideRows(show, season) {
  if (!season) return "";
  const gaps = (show.missing || []).filter(m => m.s === season.n);
  const next = show.next_air && show.next_air.s === season.n ? show.next_air : null;
  const others = season === show.seasons[show.seasons.length - 1] ? (show.seasons_absent || []) : [];
  if (!gaps.length && !next && !others.length) return "";
  const row = (m, when) => `<li><span class="num">${esc(m.e)}</span><span class="t">${esc(m.title || "Episode " + m.e)}</span><span class="when">${esc(when)}</span></li>`;
  return `<div class="guide">
    ${gaps.length ? `<h3>Not in your library <small>${plural(gaps.length, "episode")}</small></h3><ul>${gaps.slice(0, 60).map(m => row(m, "aired " + fmtDate(m.aired))).join("")}</ul>
      ${gaps.length > 60 ? `<p class="count">and ${gaps.length - 60} more</p>` : ""}` : ""}
    ${next ? `<h3>Coming up</h3><ul>${row(next, "airs " + airDay(next.aired))}</ul>` : ""}
    ${others.length ? `<p class="count">Also aired, not in your library: ${others.map(o => esc(seasonName(o.n)) + " (" + plural(o.count, "episode") + ")").join(", ")}.</p>` : ""}</div>`;
}
function viewShow(id, seasonKey) {
  const show = byId.get(id);
  if (!show || !show.seasons) return viewMissing();
  setGlow(show.adult ? "" : show.backdrop || show.poster);
  const tabs = show.seasons.map(s => ({ key: String(s.n), label: seasonName(s.n), season: s }));
  if (show.extras.length) tabs.push({ key: "extras", label: "Extras" });
  let current = tabs.find(t => t.key === seasonKey);
  if (!current) {
    const nx = upNext(show);
    current = (nx && tabs.find(t => t.season === nx.ep.season)) || tabs.find(t => t.key !== "0") || tabs[0];
  }
  const items = current.key === "extras" ? show.extras : current.season.episodes;
  const done = items.filter(i => isDone(i.id)).length;
  const poster = (current.season && current.season.poster) || show.poster;
  return heroFor(show, true) +
    `<div class="seasons" role="tablist" aria-label="Seasons">${tabs.map(t =>
      `<button role="tab" aria-selected="${t === current}" data-season="${esc(t.key)}">${esc(t.label)}</button>`).join("")}</div>
    <div class="season-body">
      <aside class="season-side">
        <span class="frame${poster ? "" : " noimg"}">${frameImg(poster, current.label, show.name)}</span>
        <h2>${esc(current.label)}</h2>
        <p>${plural(items.length, current.key === "extras" ? "video" : "episode")}, ${done} watched</p>
        <button class="btn" data-season-watched="${esc(current.key)}">${done === items.length ? "Mark all not watched" : "Mark all watched"}</button>
      </aside>
      <div class="episodes" role="tabpanel">${items.map(i => episodeRow(i)).join("")}${guideRows(show, current.season)}</div>
    </div>` + likeThisRail(show);
}
/* Search: accents and case don't matter; whole titles and word starts come first; genres, networks,
   collections and years count too. The Adult section has its own search, inside it. */
const fold = s => String(s || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
function searchAll(q) {
  const n = fold(q).trim();
  if (!n) return { sh: [], mv: [], eps: [] };
  const score = text => {
    const t = fold(text);
    if (!t) return 0;
    if (t === n) return 100;
    if (t.startsWith(n)) return 85;
    if (t.split(/[^a-z0-9]+/).some(w => w && w.startsWith(n))) return 60;
    return t.includes(n) ? 30 : 0;
  };
  const best = pairs => pairs.filter(p => p[1] > 0).sort((a, b) => b[1] - a[1]).map(p => p[0]);
  const sh = best(shows.map(s => [s, Math.max(score(s.name), score((s.genres || []).join(" ")) * .5, score(s.network) * .45,
    String(years(s) || "").includes(n) && /^\d{4}$/.test(n) ? 40 : 0)]));
  const mv = best(movies.map(m => [m, Math.max(score(m.title), score(m.collection) * .7, score((m.genres || []).join(" ")) * .5,
    String(m.year) === n ? 45 : 0, score(m.studio) * .4)]));
  const eps = [];
  shows.forEach(s => s.seasons.forEach(se => se.episodes.forEach(ep => { const v = score(ep.title) * .8; if (v) eps.push([ep, v]); })));
  shows.forEach(s => s.extras.forEach(x => { const v = score(x.title) * .6; if (v) eps.push([x, v]); }));
  return { sh, mv, eps: best(eps) };
}
/* The search page: results for the header's search box, and on a TV (no room for a box in the header)
   a big box of its own, with results as you type. */
function viewSearch(q) {
  setGlow("");
  return `<section class="page search-page"><div class="page-head"><h1>Search</h1></div>
    <input id="pageSearch" type="search" placeholder="Shows, movies, episodes, genres, years" aria-label="Search" value="${esc(q)}" autocomplete="off">
    <div id="searchResults">${searchResults(q)}</div></section>`;
}
function searchResults(q) {
  if (!q.trim()) return `<p class="count">Type part of a title, an episode name, a genre or a year.</p>`;
  const { sh, mv, eps } = searchAll(q);
  const total = sh.length + mv.length + eps.length;
  return `<p class="count">${plural(total, "result")} for "${esc(q.trim())}"</p>
    ${total ? "" : `<p class="count">Nothing matches. Try part of an episode title.</p>`}
    ${sh.length || mv.length ? grid(sh.map(posterCard).concat(mv.map(movieCard))) : ""}
    ${eps.length ? `<div class="episodes" style="margin-top:28px">${eps.slice(0, 80).map(ep =>
      episodeRow(ep, ep.show.name + ", " + epCode(ep))).join("")}</div>` : ""}`;
}
let pageSearchTimer = 0;
function viewMyList() {
  const list = myList();
  setGlow(list[0] && (list[0].backdrop || list[0].poster));
  return `<section class="page"><div class="page-head"><h1>My List</h1><span class="count">${plural(list.length, "title")}</span></div>
    ${list.length ? `<div class="grid">${list.map(x => x.seasons ? posterCard(x) : movieCard(x)).join("")}</div>`
      : `<p class="count" style="max-width:56ch">Nothing here yet. Press <b>+ My List</b> on a show or a movie (or on the card that opens when you point at one) to keep it here for later.</p>`}</section>`;
}
function viewMissing() {
  return `<section class="empty"><h1>That page isn't here</h1><p>The show may have been renamed or removed.</p>
    <p><a class="btn" href="#/">Go home</a></p></section>`;
}

/* ---------- suggestions: "More like this" and "Because you watched" ----------
   Worked out here from what Sofa knows about each title (no service, nothing leaves the house):
   shared genres count most, then the same collection or TV network, then how close the years are.
   In the Adult section: the same studio, performers, tags and category. */
const yearOf = x => x.year || (x.premiered ? +String(x.premiered).slice(0, 4) : 0);
const setOf = list => new Set((list || []).map(fold));
function similarity(a, b) {
  if (a === b || !!a.adult !== !!b.adult) return 0;
  let s = 0;
  const ga = setOf(a.genres), gb = setOf(b.genres);
  if (ga.size && gb.size) {
    let both = 0; ga.forEach(g => { if (gb.has(g)) both++; });
    s += 4 * both / (ga.size + gb.size - both);
  }
  if (a.collection && a.collection === b.collection) s += 3;
  if (a.network && a.network === b.network) s += .8;
  const ya = yearOf(a), yb = yearOf(b);
  if (ya && yb) s += Math.abs(ya - yb) <= 4 ? .7 : Math.abs(ya - yb) <= 10 ? .3 : 0;
  if (!!a.seasons === !!b.seasons) s += .3;
  if (a.adult) {
    if (a.studio && a.studio === b.studio) s += 2.5;
    const pa = setOf(a.performers), pb = setOf(b.performers);
    pa.forEach(p => { if (pb.has(p)) s += 2; });
    if (a.category && a.category === b.category) s += .6;
  }
  if (b.seasons ? b.order.every(ep => isDone(ep.id)) : isDone(b.id)) s *= .6;          // seen it already: lower
  return s;
}
function similarTo(x, limit, skip) {
  const pool = x.adult ? adultShows.concat(adultMovies) : shows.concat(movies);
  const minimum = x.adult ? 1.6 : 1.2;                       // something real in common, not just "also a movie"
  return pool.filter(y => y !== x && !(skip || []).includes(y)).map(y => [y, similarity(x, y)])
    .filter(p => p[1] >= minimum).sort((a, b) => b[1] - a[1]).slice(0, limit || 18).map(p => p[0]);
}
function likeThisRail(x, skip) {
  const list = similarTo(x, 18, skip);
  return list.length >= 2 ? rail("More like this", x.adult ? "scenes" : "posters", list.map(y => y.seasons ? posterCard(y) : movieCard(y))) : "";
}
function becauseYouWatched() {
  const seen = [];                                          // the last titles someone watched (not adult), newest first
  Object.keys(progress).sort((a, b) => progress[b].at - progress[a].at).forEach(id => {
    const it = byId.get(id); if (!it || !notAdult(it)) return;
    const owner = it.kind === "episode" ? it.show : it;
    if (owner && (owner.seasons || owner.kind === "movie") && !seen.includes(owner)) seen.push(owner);
  });
  return seen.slice(0, 2).map(x => {
    const list = similarTo(x, 18);
    return list.length >= 4 ? rail("Because you watched " + (x.name || x.title), "posters", list.map(y => y.seasons ? posterCard(y) : movieCard(y))) : "";
  }).join("");
}

/* ---------- favorites (♥) ---------- */
const kidsBtn = x => session.user.admin && session.kids_profiles && !x.adult ? (on => `<button class="btn ghost" data-kids-title="${esc(x.id)}" aria-pressed="${on}" title="${(LIB.kids_choices || {})[x.id] !== undefined ? "Set by an admin" : "From its rating and genres"}">${on ? icon("i-check") : ""}For kids</button>`)((LIB.for_kids || []).includes(x.id)) : "";
const forgetBtn = x => `<button class="btn ghost" data-forget="${esc(x.id)}" title="Remove from Continue watching">${icon("i-close")}<span>Remove from Continue watching</span></button>`;
const listBtn = id => `<button class="btn ghost list-btn" data-like="${esc(id)}" aria-pressed="${favs.has(id)}">${favs.has(id) ? icon("i-check") + "My List" : "+ My List"}</button>`;
const roundListBtn = id => `<button class="round list-round${favs.has(id) ? " on" : ""}" data-like="${esc(id)}" aria-pressed="${favs.has(id)}" aria-label="${favs.has(id) ? "Remove from My List" : "Add to My List"}">${favs.has(id) ? icon("i-check") : `<b aria-hidden="true">+</b>`}</button>`;
function myList() {
  return (LIB.likes || []).map(id => byId.get(id)).filter(x => x && (x.seasons || x.kind === "movie") && !x.adult);
}
async function toggleFav(key, btn) {
  const on = !favs.has(key);
  if (on) favs.add(key); else favs.delete(key);
  LIB.likes = (LIB.likes || []).filter(k => k !== key); if (on) LIB.likes.unshift(key);
  if (btn) {
    btn.setAttribute("aria-pressed", on);
    if (btn.classList.contains("heart-btn")) btn.textContent = "♥ " + (on ? "In Favorites" : "Favorite");
    if (btn.classList.contains("list-btn")) btn.innerHTML = on ? icon("i-check") + "My List" : "+ My List";
    if (btn.classList.contains("list-round")) { btn.classList.toggle("on", on); btn.innerHTML = on ? icon("i-check") : `<b aria-hidden="true">+</b>`; }
    if (!btn.closest(".pop")) toast(on ? "Added to " + (btn.classList.contains("heart-btn") ? "Favorites" : "My List") + "." : "Removed.");
  }
  try { await api("/api/like/" + encodeURIComponent(key), { on }); } catch (e) { toast(e.message); }
}

/* ---------- hover previews: a short, silent clip of the video ----------
   With a mouse, pointing at a card opens a bigger card over it that plays the clip, with Play and More info.
   With a TV remote (or the keyboard), the focused card plays its clip in place. */
let pvCard = null, pvTimer = 0, pop = null;
const fineHover = matchMedia("(hover: hover) and (pointer: fine)").matches && !TV;
function clipVideo(id, hd) {
  const v = document.createElement("video");
  v.className = "pv"; v.muted = true; v.loop = true; v.playsInline = true; v.preload = "auto";
  v.setAttribute("muted", ""); v.setAttribute("playsinline", ""); v.setAttribute("aria-hidden", "true");
  v.addEventListener("playing", () => v.classList.add("on"), { once: true });
  v.addEventListener("error", () => v.remove(), { once: true });
  v.src = "/media/" + encodeURIComponent(id) + "/preview.mp4" + (hd ? "?hd=1" : "");
  v.play().catch(() => {});
  return v;
}
function dropClip(v) { if (v) { v.pause(); v.removeAttribute("src"); v.load(); v.remove(); } }
function stopPreview() {
  clearTimeout(pvTimer);
  if (pvCard) dropClip(pvCard.querySelector("video.pv"));
  pvCard = null;
  closePop();
}
function startPreview(card) {
  stopPreview();
  pvCard = card;
  pvTimer = setTimeout(() => {
    if (pvCard !== card || Player.isOpen() || !document.contains(card)) return;
    if (fineHover && card.dataset.pop) return openPop(card);
    const frame = card.querySelector(".frame") || card;
    frame.appendChild(clipVideo(card.dataset.pv));
  }, TV ? 900 : 650);
}
function popInfo(x) {
  if (x.seasons) {                                      // a show
    const nx = upNext(x);
    return { title: x.name, art: x.backdrop || x.poster, play: nx && nx.ep.id, verb: nx && nx.resume ? "Resume" : "Play",
      more: "#/show/" + encodeURIComponent(x.id), sub: nx && !nx.fresh ? epCode(nx.ep) + (nx.ep.title ? " · " + nx.ep.title : "") : "",
      facts: [years(x), plural(x.regularSeasons, "season"), x.adult ? x.category : ""], tags: x.genres || [] };
  }
  if (x.kind === "episode") {
    const sh = x.show || {};
    return { title: sh.name || x.show_name, art: x.thumb || sh.backdrop || sh.poster, play: x.id, verb: inProgress(x.id) ? "Resume" : "Play",
      more: "#/show/" + encodeURIComponent(sh.id || x.show_id), sub: epCode(x) + (x.title ? " · " + x.title : ""),
      facts: [x.runtime ? dur(x.runtime * 60) : x.duration ? dur(x.duration) : "", quality(x.height)], tags: sh.genres || [], id: x.id };
  }
  return { title: x.title, art: x.backdrop || x.poster, play: x.id, verb: inProgress(x.id) ? "Resume" : "Play",   // a movie
    more: "#/movie/" + encodeURIComponent(x.id), sub: x.adult ? (x.performers || []).slice(0, 3).join(", ") : x.tagline || "",
    facts: [x.year, x.runtime ? dur(x.runtime * 60) : x.duration ? dur(x.duration) : "", quality(x.height), x.adult ? x.studio : x.certificate],
    tags: x.genres || [], id: x.id };
}
function closePop() {
  if (!pop) return;
  const p = pop; pop = null;
  dropClip(p.querySelector("video"));
  p.classList.remove("on");
  setTimeout(() => p.remove(), 220);
}
function openPop(card) {
  closePop();
  const x = byId.get(card.dataset.pop), frame = card.querySelector(".frame");
  if (!x || !frame) return;
  const info = popInfo(x), r = frame.getBoundingClientRect();
  const w = Math.min(470, Math.max(320, r.width * 1.5)), mh = w * 9 / 16, h = mh + 150;
  const left = Math.max(14, Math.min(innerWidth - w - 14, r.left + r.width / 2 - w / 2));
  const top = Math.max(76, Math.min(innerHeight - h - 14, r.top + r.height / 2 - mh / 2 - 12));
  const p = pct(info.id || info.play);
  const el = document.createElement("div");
  el.className = "pop";
  el.style.cssText = `left:${left}px;top:${top}px;width:${w}px;transform-origin:${r.left + r.width / 2 - left}px ${r.top + r.height / 2 - top}px`;
  el.innerHTML = `<a class="pop-media" href="${esc(info.more)}" tabindex="-1">${info.art ? `<img src="${esc(artSrc(info.art, 720))}" alt="">` : `<span class="placeholder" style="--h:${hue(info.title)}">${esc(info.title)}</span>`}
      ${p && !isDone(info.id || info.play) ? `<span class="progress"><i style="width:${p}%"></i></span>` : ""}</a>
    <div class="pop-body">
      <div class="pop-actions">${info.play ? `<button class="round primary" data-play="${esc(info.play)}" aria-label="${info.verb}">${icon("i-play")}</button>` : ""}
        <a class="round" href="${esc(info.more)}" aria-label="More info">${icon("i-info")}</a>
        ${x.adult || (x.show && x.show.adult) ? `<button class="round${favs.has(x.id) ? " on" : ""}" data-like="${esc(x.id)}" aria-pressed="${favs.has(x.id)}" aria-label="Favorite">♥</button>`
          : roundListBtn(x.kind === "episode" && x.show ? x.show.id : x.id)}
        ${inRows(x) ? `<button class="round" data-forget="${esc(ownerOf(x).id)}" aria-label="Remove from Continue watching" title="Remove from Continue watching">${icon("i-close")}</button>` : ""}
        <span class="pop-verb">${esc(info.verb)}</span></div>
      <p class="pop-title">${esc(info.title)}</p>
      ${info.sub ? `<p class="pop-sub">${esc(info.sub)}</p>` : ""}
      <p class="pop-facts">${info.facts.filter(Boolean).map(f => `<span>${esc(f)}</span>`).join("")}</p>
      ${info.tags.length ? `<p class="pop-tags">${info.tags.slice(0, 3).map(esc).join('<i aria-hidden="true">•</i>')}</p>` : ""}
    </div>`;
  el.querySelector(".pop-media").appendChild(clipVideo(card.dataset.pv));
  el.addEventListener("mouseleave", () => { if (pop === el) { pvCard = null; closePop(); } });
  el.addEventListener("click", e => { if (e.target.closest("a, button")) setTimeout(closePop, 0); });
  document.body.appendChild(el);
  requestAnimationFrame(() => requestAnimationFrame(() => el.classList.add("on")));
  pop = el;
}
document.addEventListener("mouseover", e => {
  if (!fineHover || (pop && pop.contains(e.target))) return;
  const c = e.target.closest && e.target.closest("[data-pv]");
  if (c === pvCard) return;
  if (c && !Player.isOpen()) startPreview(c); else stopPreview();
});
document.addEventListener("focusin", e => {
  if (fineHover && !e.target.matches(":focus-visible")) return;       // a mouse click, not the keyboard
  if (pop && pop.contains(e.target)) return;
  const c = e.target.closest && e.target.closest("[data-pv]");
  if (c === pvCard) return;
  if (c && !Player.isOpen()) startPreview(c); else stopPreview();
});
document.addEventListener("scroll", () => { if (pop) { pvCard = null; closePop(); } }, true);
window.addEventListener("hashchange", stopPreview);
document.addEventListener("mouseleave", stopPreview);

/* ---------- save a video from a link (admins) ---------- */
/* ---------- download for a trip ----------
   A file this device plays as it is downloads as it is; anything else gets a travel copy first
   (720p MP4 with its subtitles), made on the Sofa computer in the background. */
function downloadDialog(id) {
  const it = byId.get(id); if (!it) return;
  const name = it.kind === "episode" ? (it.show ? it.show.name + " · " : "") + epCode(it) + (it.title ? " · " + it.title : "") : title(it);
  const d = openDialog(`<h2>Download</h2><p class="count">${esc(name)}</p><div class="dl-body"><p class="hint">Checking…</p></div>
    <div class="actions"><button class="btn ghost" data-dismiss="1">Close</button></div>`);
  const url = "/media/" + encodeURIComponent(id);
  let timer = 0;
  async function paint() {
    if (!document.contains(d)) return;
    let r;
    try { r = await api("/api/travel/" + encodeURIComponent(id) + "?" + Player.capsQuery()); }
    catch (e) { $(".dl-body", d).innerHTML = `<p class="form-error">${esc(e.message)}</p>`; return; }
    const gb = r.duration ? r.duration / 3600 * 0.9 : 0;
    const est = gb ? (gb < 1 ? Math.max(50, Math.round(gb * 1000)) + " MB" : gb.toFixed(1) + " GB") : "";
    let html;
    if (r.direct) html = `<p>This file plays on this device as it is.</p>
      <p><a class="btn primary" href="${url}/file?download=1" download>${icon("i-download")}Download (${bytes(r.size)})</a></p>`;
    else if (r.state === "ready") html = `<p>The travel copy is ready: 720p MP4 with its subtitles, for any phone, tablet or laptop.</p>
      <p><a class="btn primary" href="${url}/travel.mp4" download>${icon("i-download")}Download (${bytes(r.copy_size)})</a></p>`;
    else if (r.state === "queued" || r.state === "working") {
      html = `<p>${r.state === "queued" ? "Waiting its turn to be made…" : "Making the travel copy… " + Math.round((r.progress || 0) * 100) + "%"}</p>
        <span class="up-bar"><i style="width:${Math.round((r.progress || 0) * 100)}%"></i></span>
        <p class="hint">You can close this; Sofa carries on. Come back here to download it.</p>`;
      timer = setTimeout(paint, 3000);
    } else html = `${r.state === "failed" ? `<p class="form-error">That didn't work: ${esc(r.error || "")}</p>` : ""}
      <p>This ${esc((r.ext || "").toUpperCase())} file won't play on this device by itself. Sofa can make a travel copy: 720p MP4 with its subtitles${est ? ", about " + est : ""}.</p>
      <p><button class="btn primary" data-make-travel="1">Make a travel copy</button></p>
      <p class="hint">Or <a href="${url}/file?download=1" download>download the original</a> (${bytes(r.size)}) for a player like VLC.</p>`;
    $(".dl-body", d).innerHTML = html;
  }
  d.addEventListener("click", async e => {
    if (!e.target.closest("[data-make-travel]")) return;
    try { await api("/api/travel/" + encodeURIComponent(id), {}); } catch (ex) { toast(ex.message); }
    clearTimeout(timer); paint();
  });
  paint();
}

/* ---------- send files from this device to the Inbox (admins) ----------
   A phone's videos, a laptop's downloads: each file goes up in one piece, with its progress, and Sofa
   files it like anything dropped in the Inbox. */
function sendFilesDialog(adult) {
  const d = openDialog(`<h2>Send files to the Inbox</h2>
    <p>Videos, music, subtitles. Sofa names and files them as usual${adult ? ", in the Adult section" : ""}.</p>
    <label class="drop-zone"><input type="file" multiple accept="video/*,audio/*,.mkv,.avi,.wmv,.flv,.srt,.vtt,.ass,.ssa,.sub,.idx,.nfo" hidden>
      <b>Choose files</b><span>or drop them here</span></label>
    ${session.user.adult && !adult ? `<label class="check"><input type="checkbox" name="adult"> Put them in the Adult section</label>` : ""}
    <ul class="upload-list"></ul>
    <div class="actions"><button class="btn ghost" data-dismiss="1">Close</button></div>`);
  const list = $(".upload-list", d), input = $("input[type=file]", d), zone = $(".drop-zone", d);
  let queue = [], busy = false;
  const toAdult = () => adult || !!($("input[name=adult]", d) || {}).checked;
  async function next() {
    if (busy || !queue.length) return;
    busy = true;
    const { file, row } = queue.shift(), bar = $("i", row), note = $(".up-note", row), a = toAdult();
    try {
      const c = await api("/api/admin/upload/check?name=" + encodeURIComponent(file.name) + "&size=" + file.size + "&adult=" + (a ? 1 : 0));
      if (!c.ok) throw new Error(c.problem);
      await new Promise((res, rej) => {
        const x = new XMLHttpRequest();
        x.open("POST", "/api/admin/upload?name=" + encodeURIComponent(file.name) + "&adult=" + (a ? 1 : 0));
        x.setRequestHeader("X-Sofa", "1");
        x.upload.onprogress = e => { if (e.lengthComputable) { bar.style.width = (e.loaded / e.total * 100) + "%"; note.textContent = bytes(e.loaded) + " of " + bytes(e.total); } };
        x.onload = () => { let r = {}; try { r = JSON.parse(x.responseText); } catch (e) {} x.status === 200 ? res() : rej(new Error(r.error || "The upload didn't work (" + x.status + ").")); };
        x.onerror = () => rej(new Error("The connection dropped. Try again."));
        x.send(file);
      });
      row.classList.add("done"); bar.style.width = "100%"; note.textContent = "In the Inbox. Sofa files it in a minute.";
    } catch (e) { row.classList.add("failed"); note.textContent = e.message; }
    busy = false; next();
  }
  function add(files) {
    [...files].forEach(file => {
      const row = document.createElement("li");
      row.innerHTML = `<b>${esc(file.name)}</b><span class="up-bar"><i></i></span><span class="up-note">${esc(bytes(file.size))}, waiting</span>`;
      list.appendChild(row); queue.push({ file, row });
    });
    next();
  }
  input.addEventListener("change", () => { add(input.files); input.value = ""; });
  zone.addEventListener("dragover", e => { e.preventDefault(); zone.classList.add("over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("over"));
  zone.addEventListener("drop", e => { e.preventDefault(); zone.classList.remove("over"); add(e.dataTransfer.files); });
}
function addLinkDialog(adult, url) {
  const d = openDialog(`<h2>Save a video from a link</h2>
    <p>Paste the address of a video page (YouTube, Vimeo and well over a thousand other sites${session.user.adult ? ", including the free adult video sites" : ""}). Sofa downloads it, names it and files it.</p>
    <form class="link-form"><input name="url" type="url" required placeholder="https://…" value="${esc(url || "")}" aria-label="Link">
      ${session.user.adult ? `<label class="check"><input type="checkbox" name="adult"${adult ? " checked" : ""}> Put it in the Adult section</label>` : ""}
      <label class="check"><input type="checkbox" name="playlist"> It's a playlist: save every video (up to 50)</label>
      <div class="form-error" role="alert"></div>
      <div class="actions"><button class="btn primary" type="submit">Save it</button><button class="btn ghost" type="button" data-dismiss="1">Cancel</button></div></form>
    <p class="hint">Only save videos you're allowed to keep. Progress is on the Server page, under Downloads.</p>`);
  const f = $(".link-form", d);
  f.addEventListener("submit", async e => {
    e.preventDefault();
    try {
      const r = await api("/api/admin/downloads", { add: { url: f.url.value, adult: !!(f.adult && f.adult.checked), playlist: f.playlist.checked } });
      closeDialog(); toast(r.note || "Saving it now. It shows up in a few minutes.");
      if (location.hash.startsWith("#/server")) loadAdmin();
    } catch (ex) { $(".form-error", f).textContent = ex.message; }
  });
}

/* ---------- live TV ---------- */
const PRESETS = [
  ["United States", "https://iptv-org.github.io/iptv/countries/us.m3u"],
  ["Cuba", "https://iptv-org.github.io/iptv/countries/cu.m3u"],
  ["Spanish-language", "https://iptv-org.github.io/iptv/languages/spa.m3u"],
  ["News", "https://iptv-org.github.io/iptv/categories/news.m3u"],
  ["Movies", "https://iptv-org.github.io/iptv/categories/movies.m3u"],
  ["Kids", "https://iptv-org.github.io/iptv/categories/kids.m3u"]
];
let liveData = null, liveGroup = prefs.get("liveGroup", "Favorites"), liveQuery = "";
async function loadLive() {
  try { liveData = await api("/api/live"); } catch (e) { liveData = { error: e.message, channels: [], playlists: [] }; }
  if (location.hash.startsWith("#/live")) rerender();
}
function liveList() {
  const q = liveQuery.trim().toLowerCase();
  return liveData.channels.filter(c =>
    (q ? c.name.toLowerCase().includes(q) : liveGroup === "All" ? true : liveGroup === "Favorites" ? c.fav : c.group === liveGroup));
}
function channelCard(c) {
  return `<div class="chan"><button class="card" data-live="${esc(c.id)}" style="display:block;width:100%">
      <span class="logo">${c.logo ? `<img src="${esc(c.logo)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : `<span>${esc(c.name)}</span>`}</span>
      <span class="t1">${esc(c.name)}</span><span class="t2">${esc(c.group)}</span></button>
    <button class="star" data-fav="${esc(c.id)}" aria-pressed="${c.fav}" aria-label="${c.fav ? "Remove from favorites" : "Add to favorites"}">★</button></div>`;
}
function viewLive() {
  setGlow("");
  if (session.offline) return `<section class="page"><div class="page-head"><h1>Live TV</h1></div>
    <p class="count" style="max-width:60ch">Live TV channels come from the internet, and Sofa is set to work offline. Everything in your library plays as usual.
    ${session.user.admin ? `An admin can switch Work offline off under Server, Settings, Privacy.` : ""}</p></section>`;
  if (!liveData) { loadLive(); return `<section class="page"><div class="page-head"><h1>Live TV</h1></div><p class="count">Loading channels…</p></section>`; }
  const head = `<div class="page-head"><h1>Live TV</h1><span class="count">${plural(liveData.channels.length, "channel")}</span></div>`;
  if (!liveData.channels.length) {
    return `<section class="page">${head}<p class="count" style="max-width:62ch">Free channels come from channel lists (M3U playlists), like the ones collected at github.com/iptv-org/iptv.
      ${session.user.admin ? "Add a list below, or any M3U link on the Server page." : "Ask whoever manages this server to add a channel list."}</p>
      ${session.user.admin ? `<div class="presets">${PRESETS.map(p => `<button class="btn" data-preset="${esc(p[1])}" data-name="${esc(p[0])}">Add ${esc(p[0])}</button>`).join("")}</div>` : ""}</section>`;
  }
  const groups = [...new Set(liveData.channels.map(c => c.group))].sort((a, b) => a.localeCompare(b));
  if (liveGroup !== "All" && liveGroup !== "Favorites" && !groups.includes(liveGroup)) liveGroup = "All";
  if (liveGroup === "Favorites" && !liveData.channels.some(c => c.fav)) liveGroup = "All";
  const list = liveList();
  const chips = ["Favorites", "All"].concat(groups).map(g => `<button data-group="${esc(g)}" aria-pressed="${!liveQuery && g === liveGroup}">${esc(g)}</button>`).join("");
  return `<section class="page">${head}
    <div class="live-tools"><input id="liveSearch" type="search" placeholder="Find a channel" aria-label="Find a channel" value="${esc(liveQuery)}"></div>
    <div class="chips" role="group" aria-label="Channel groups">${chips}</div>
    <div class="channels">${list.slice(0, 600).map(channelCard).join("")}</div>
    ${list.length > 600 ? `<p class="count">Showing 600 of ${list.length}. Search or pick a group to narrow it down.</p>` : ""}
    ${!list.length ? `<p class="count">No channels here yet. Tap the star on a channel to add it to Favorites.</p>` : ""}</section>`;
}
document.addEventListener("input", e => {
  if (e.target.id === "pageFilter") {
    pageFilter = e.target.value; const pos = e.target.selectionStart; rerender();
    const box = $("#pageFilter"); if (box) { box.focus(); box.setSelectionRange(pos, pos); }
    return;
  }
  if (e.target.id === "pageSearch") {
    clearTimeout(pageSearchTimer);
    pageSearchTimer = setTimeout(() => {
      const q = e.target.value, box = $("#searchResults"); if (!box) return;
      history.replaceState(null, "", "#/search/" + encodeURIComponent(q));
      gridRest.clear(); box.innerHTML = searchResults(q); watchGrids();
    }, 350);
    return;
  }
  if (e.target.id === "adultSearch") {
    adultQuery = e.target.value; const pos = e.target.selectionStart; rerender();
    const box = $("#adultSearch"); if (box) { box.focus(); box.setSelectionRange(pos, pos); }
    return;
  }
  if (e.target.id !== "liveSearch") return;
  liveQuery = e.target.value;
  const pos = e.target.selectionStart;
  rerender();
  const box = $("#liveSearch"); if (box) { box.focus(); box.setSelectionRange(pos, pos); }
});

/* ---------- sign in and first-run setup ---------- */
function authView(kind) {
  $("#nav").hidden = $("#searchBox").hidden = $("#searchBtn").hidden = $("#who").hidden = $("#castBtn").hidden = true;
  setGlow("");
  const setup = kind === "setup";
  view.innerHTML = `<section class="auth"><form class="auth-card" id="authForm" autocomplete="on">
    <h1>${setup ? "Welcome to Sofa" : "Sign in"}</h1>
    <p>${setup ? "Create the admin account. You'll use it to sign in and to add everyone else in the house."
               : "Sign in to " + esc(session.name) + "."}</p>
    <label class="field"><span>Name</span><input name="name" autocomplete="username" required maxlength="40"></label>
    <label class="field"><span>Password</span><input name="password" type="password" autocomplete="${setup ? "new-password" : "current-password"}" required minlength="${setup ? 8 : 1}"></label>
    ${setup ? `<label class="field"><span>Password again</span><input name="again" type="password" autocomplete="new-password" required></label>` : ""}
    <div class="form-error" role="alert"></div>
    <button class="btn primary" type="submit">${setup ? "Create account" : "Sign in"}</button>
    ${!setup && session.guest_available ? `<button class="btn ghost" type="button" id="asGuest">Watch as a guest</button>` : ""}
    ${setup ? "" : `<button class="btn ghost" type="button" id="withPhone">Sign in with your phone</button>`}
    <p class="credit">Project by <a href="https://edgeventure.uk" target="_blank" rel="noopener">EdgeVenture.uk</a></p>
  </form></section>`;
  const form = $("#authForm");
  const wp = $("#withPhone");
  if (wp) wp.addEventListener("click", () => phoneSignIn());
  if (!setup && TV) return phoneSignIn();          // a TV: no typing with the remote
  form.name.focus();
  const g = $("#asGuest");
  if (g) g.addEventListener("click", async () => { try { await api("/api/guest", {}); boot(); } catch (ex) { $(".form-error", form).textContent = ex.message; } });
  form.addEventListener("submit", async e => {
    e.preventDefault();
    const err = $(".form-error", form);
    if (setup && form.password.value !== form.again.value) { err.textContent = "The passwords don't match."; return; }
    err.textContent = "";
    try {
      await api(setup ? "/api/setup" : "/api/login", { name: form.name.value, password: form.password.value });
      boot();
    } catch (ex) { err.textContent = ex.message; }
  });
}

/* ---------- sign in with your phone ----------
   The TV shows a code and a QR code; on a phone signed in to Sofa, the code (or the QR) opens a page to
   approve it and pick the profile; the TV notices within a couple of seconds and is signed in. */
let pairTimer = 0;
async function phoneSignIn() {
  clearTimeout(pairTimer);
  let r;
  try { r = await api("/api/pair/start", { name: Screens.name() }); }
  catch (e) { const err = $(".form-error"); if (err) err.textContent = e.message; return; }
  let short = location.host;                     // Sofa's address as the phone reaches it (on a Sofa box, not the box's own)
  try { short = new URL(r.url).host; } catch (e) {}
  view.innerHTML = `<section class="auth"><div class="auth-card pair-card">
    <h1>Sign in with your phone</h1>
    <p>On your phone, open Sofa (<b>${esc(short)}</b>), signed in, and scan this, or go to <b>Pair a TV</b> and type the code.</p>
    <div class="pair-row"><div class="pair-qr" id="pairQr" data-url="${esc(r.url)}"></div>
      <div class="pair-code" aria-label="Code">${esc(r.code.slice(0, 3))}<span></span>${esc(r.code.slice(3))}</div></div>
    <p class="hint">The code works for 10 minutes. Waiting for your phone…</p>
    <button class="btn ghost" type="button" id="withPassword">Use a name and password instead</button></div></section>`;
  const box = $("#pairQr"), draw = () => { const q = window.qrcode(0, "M"); q.addData(box.dataset.url); q.make(); box.innerHTML = q.createSvgTag({ cellSize: 5, margin: 2, scalable: true }); };
  if (window.qrcode) draw(); else { const sc = document.createElement("script"); sc.src = "/client/vendor/qrcode.js"; sc.onload = draw; document.head.appendChild(sc); }
  $("#withPassword").addEventListener("click", () => { clearTimeout(pairTimer); authView("login"); $("#authForm").name.focus(); });
  $("#withPassword").focus();
  const started = Date.now();
  const check = async () => {
    if (!$(".pair-card")) return;
    try {
      const p = await api("/api/pair/poll?poll=" + encodeURIComponent(r.poll));
      if (p.state === "approved") { toast("Signed in as " + p.user.name + "."); boot(); return; }
      if (p.state === "expired" || Date.now() - started > r.expires * 1000) return phoneSignIn();
    } catch (e) {}
    pairTimer = setTimeout(check, 2000);
  };
  pairTimer = setTimeout(check, 2000);
}
/* The phone's side: approve a TV's code and pick who it's for. */
function viewPair(code) {
  setGlow("");
  if (!code) return `<section class="page pair-page"><div class="page-head"><h1>Pair a TV</h1></div>
    <p class="count">Type the code the TV shows.</p>
    <form class="pair-form" id="pairForm"><input name="code" inputmode="numeric" pattern="[0-9 ]*" maxlength="7" autocomplete="off" aria-label="Code" placeholder="123 456">
      <button class="btn primary">Next</button></form><div class="form-error" role="alert"></div></section>`;
  setTimeout(async () => {
    const box = $("#pairBody"); if (!box) return;
    try {
      const r = await api("/api/pair/" + encodeURIComponent(code));
      box.innerHTML = `<p>Sign in <b>${esc(r.device)}</b> as:</p>
        <div class="profiles">${r.profiles.map(p => `<button class="profile" data-pair-profile="${p.id}" data-pair-code="${esc(code)}">
          <span class="tile">${avatar(p)}</span><span class="pname">${esc(p.name)}</span>${p.kids ? `<span class="kids-tag">Kids</span>` : ""}${p.id === r.me ? `<span class="me">You</span>` : ""}</button>`).join("")}</div>`;
      const mine = $(`[data-pair-profile="${r.me}"]`, box); if (mine) mine.focus();
    } catch (e) { box.innerHTML = `<p class="form-error">${esc(e.message)}</p><p><a class="btn" href="#/pair">Type a code</a></p>`; }
  }, 0);
  return `<section class="page pair-page"><div class="page-head"><h1>Pair a TV</h1><span class="count">Code ${esc(code.slice(0, 3) + " " + code.slice(3))}</span></div>
    <div id="pairBody"><p class="count">Looking…</p></div></section>`;
}
document.addEventListener("submit", e => {
  if (e.target.id !== "pairForm") return;
  e.preventDefault();
  const code = e.target.code.value.replace(/\D/g, "");
  if (code.length !== 6) { $(".pair-page .form-error").textContent = "The code has 6 digits."; return; }
  location.hash = "#/pair/" + code;
});

/* ---------- server (admin) page ---------- */
let adminData = null, adminTimer = 0, adminTab = "overview", activityKind = "all";
const SRV_TABS = [["overview", "Overview"], ["library", "Library"], ["storage", "Storage"], ["convert", "Converting"], ["downloads", "Downloads"], ["live", "Live TV"],
  ["people", "People"], ["settings", "Settings"], ["internet", "Internet"], ["update", "Updates"], ["activity", "Activity"]];
async function loadAdmin() {
  try {
    const d = await api("/api/admin/status");
    d.live = (await api("/api/live")).playlists;
    if (adminTab === "library") { d.missing = (await api("/api/admin/missing")).items; d.intros = await api("/api/admin/intros"); d.duplicates = (await api("/api/admin/duplicates")).groups; }
    if (adminTab === "convert") d.convert = await api("/api/admin/convert");
    if (adminTab === "downloads") d.downloads = await api("/api/admin/downloads");
    if (adminTab === "storage") d.storage = await api("/api/admin/storage");
    if (adminTab === "people") d.sessions = (await api("/api/admin/sessions")).sessions;
    if (adminTab === "internet") d.internet = await api("/api/admin/internet");
    adminData = d;
  } catch (e) { adminData = { error: e.message }; }
  const typing = document.activeElement && document.activeElement.closest && document.activeElement.closest(".net-form");
  if (location.hash.startsWith("#/server") && !Player.isOpen() && !document.querySelector(".dialog-scrim") && !typing) {
    const active = document.activeElement, keep = active && active.id;
    const y = scrollY; view.innerHTML = viewServer(adminTab); scrollTo(0, y); drawGuestQr();
    if (keep && $("#" + keep)) $("#" + keep).focus();
  }
}
function viewServer(tab) {
  setGlow("");
  if (tab && SRV_TABS.some(t => t[0] === tab) && tab !== adminTab) { adminTab = tab; if (adminData) loadAdmin(); }
  else if (adminData && !adminData.error && ((adminTab === "downloads" && !adminData.downloads) || (adminTab === "convert" && !adminData.convert) ||
           (adminTab === "library" && !adminData.intros) || (adminTab === "internet" && !adminData.internet))) loadAdmin();
  clearTimeout(adminTimer);
  const busy = adminData && adminData.convert && adminData.convert.counts && adminData.convert.counts.working;
  const upd = (adminData && adminData.update && adminData.update.running) ||
    (adminData && adminData.storage && adminData.storage.transfers.some(t => t.state === "copying" || t.state === "checking")) ||
    (adminData && adminData.downloads && (adminData.downloads.rows.some(r => r.state === "working") ||
      (adminData.downloads.installing || {}).running)) || (adminData && adminData.internet && adminData.internet.https.busy);
  adminTimer = setTimeout(() => { if (location.hash.startsWith("#/server")) loadAdmin(); }, busy || upd ? 3000 : 10000);
  const tabs = `<nav class="srv-tabs" aria-label="Server sections">${SRV_TABS.map(t => `<button data-srv-tab="${t[0]}" aria-current="${t[0] === adminTab ? "page" : "false"}">${t[1]}${
    t[0] === "update" && adminData && adminData.update && adminData.update.available ? ` <i class="dot" aria-label="update available"></i>` : ""}${
    t[0] === "library" && adminData && adminData.library && adminData.library.missing ? ` <i class="num">${adminData.library.missing}</i>` : ""}</button>`).join("")}</nav>`;
  const head = d => `<div class="admin-head"><h1>Server</h1>${d && d.server ? `<span class="pill">Running</span>${d.server.ffmpeg ? "" : `<span class="pill warn">Can't convert video yet</span>`}` : ""}</div>`;
  if (!adminData) { loadAdmin(); return `<section class="admin">${head()}${tabs}<p class="admin-lede">Loading…</p></section>`; }
  if (adminData.error) return `<section class="admin">${head()}${tabs}<p class="admin-lede">${esc(adminData.error)}</p></section>`;
  const d = adminData;
  const body = { overview: srvOverview, library: srvLibrary, storage: srvStorage, convert: srvConvert, downloads: srvDownloads, live: srvLive, people: srvPeople,
                 settings: srvSettings, internet: srvInternet, update: srvUpdate, activity: srvActivity }[adminTab](d);
  return `<section class="admin">${head(d)}<p class="admin-lede">${esc(d.server.name)} on ${esc(d.server.host)} · Sofa ${esc(d.server.version)} · up since ${esc(new Date(d.server.started * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }))}</p>
    ${tabs}${body}</section>`;
}
const actRow = a => `<li class="${a.kind === "review" || a.kind === "playback" ? "review" : ""}"><span>${esc(a.message)}</span><span class="when">${esc(ago(a.at))}</span></li>`;
const srvSwitch = (key, on, label, hint) => `<div class="toggle"><div><b>${label}</b><span>${hint}</span></div>
  <button class="switch" role="switch" aria-checked="${!!on}" aria-label="${esc(label)}" data-setting="${key}"></button></div>`;
const STREAM_MODE = { direct: "Original file", remux: "Repackaged live", transcode: "Converted live" };

function srvOverview(d) {
  const s = d.server, L = d.library, port = s.port;
  const addr = [];
  s.lan.forEach(ip => addr.push(`<div><b>At home</b><code>http://${esc(ip)}:${port}</code><span>Any phone, laptop or TV browser on your Wi-Fi.</span></div>`));
  s.tailscale.forEach(ip => addr.push(`<div><b>Away from home</b><code>http://${esc(ip)}:${port}</code><span>From any device signed in to your Tailscale.</span></div>`));
  addr.push(`<div><b>TVs</b><span>${s.dlna ? `Roku Media Player, VLC and most smart TVs list "${esc(s.name)}" by themselves.` : "TV sharing is off (see Settings)."}</span></div>`);
  const streams = d.streams.length ? d.streams.map(x => `<li><span><b>${esc(x.who)}</b> is watching ${esc(x.title || x.item)}</span><span class="when" title="${x.speed ? "Converting " + x.speed + "× as fast as it plays" + (x.speed < 1.1 ? ": too slow, it will stop now and then" : "") : ""}">${esc([STREAM_MODE[x.mode] || x.mode, x.height ? x.height + "p" : "", x.speed ? x.speed + "× speed" : ""].filter(Boolean).join(" · "))}</span></li>`).join("")
    : `<li class="empty-row">Nobody is watching right now.</li>`;
  const inbox = d.inbox.length ? d.inbox.map(x => `<li><span>${esc(x.name)}</span><span class="when">${x.state === "copying" ? "Still copying" : "Sorting soon"}</span></li>`).join("")
    : `<li class="empty-row">Empty. Drop shows and movies here and they're filed within a minute.</li>`;
  const c = d.convert || { counts: {} };
  const alerts = [];
  if (d.update && d.update.available) alerts.push(`<div class="alert"><b>A new version of Sofa is ready${d.update.latest ? " (" + esc(d.update.latest) + ")" : ""}.</b><span>Your media and settings stay as they are.</span><button class="btn primary" data-srv-tab="update">See the update</button></div>`);
  if (L.adult && !session.user.adult) alerts.push(`<div class="alert"><b>There ${L.adult === 1 ? "is 1 title" : "are " + L.adult + " titles"} in the Adult section.</b><span>Nobody sees it until it's switched on for them, admins included. Switch it on for yourself here, and for others under People.</span><button class="btn primary" data-enable-adult="1">Show me the Adult section</button></div>`);
  if (L.missing) alerts.push(`<div class="alert soft"><b>${plural(L.missing, "title")} without details or artwork.</b><span>Pick the right match in a couple of clicks.</span><button class="btn" data-srv-tab="library">Fix them</button></div>`);
  if (d.internet_problem) alerts.push(`<div class="alert"><b>Sofa can't reach secure websites.</b><span>${esc(d.internet_problem)} Then press "Look up missing details again" under Library.</span></div>`);
  if (!s.ffmpeg) alerts.push(`<div class="alert"><b>ffmpeg isn't installed.</b><span>Only files a device already supports will play. On a Mac: <code>brew install ffmpeg</code>, then restart Sofa.</span></div>`);
  if (d.review.length) alerts.push(`<div class="alert soft"><b>${plural(d.review.length, "file")} in Needs Review.</b><span>Sofa couldn't tell what they are.</span><button class="btn" data-srv-tab="library">Have a look</button></div>`);
  return `${alerts.join("")}
    <div class="stats big">
      <a class="stat" href="#/shows"><b>${L.shows}</b><span>shows · ${L.episodes} episodes</span></a>
      <a class="stat" href="#/movies"><b>${L.movies}</b><span>movies</span></a>
      ${L.adult ? `<div class="stat"><b>${L.adult}</b><span>in Adult</span></div>` : ""}
      <a class="stat" href="#/music"><b>${L.tracks}</b><span>songs</span></a>
      ${L.disk ? `<div class="stat"><b>${bytes(L.disk.free)}</b><span>free of ${bytes(L.disk.total)}</span></div>` : ""}
      <button class="stat" data-srv-tab="convert"><b>${(c.counts.queued || 0) + (c.counts.working || 0)}</b><span>${c.counts.working ? "converting now" : "waiting to convert"}</span></button>
    </div>
    <div class="panels">
      <div class="panel"><h2>How to watch</h2><p class="hint">Open one of these addresses and sign in.</p><div class="addr">${addr.join("")}</div></div>
      ${s.lan.length ? appsPanel(`http://${s.lan[0]}:${port}`, d.apps) : ""}
      <div class="panel"><h2>Watching now</h2><p class="hint">"Repackaged" and "converted" mean Sofa is adapting the file for that device as it plays.</p><ul class="list">${streams}</ul></div>
      <div class="panel"><h2>Inbox</h2><p class="hint">Sofa waits until a copy finishes, then names and files it. Put adult content in <code>Inbox/XXX</code>.</p>
        <div class="actions"><button class="btn" data-send-files="normal">Send files from this device</button></div><ul class="list">${inbox}</ul>
        <div class="actions" style="margin-top:14px"><button class="btn" data-admin="inbox">Sort the Inbox now</button><button class="btn" data-admin="scan">Check for new files</button></div></div>
      <div class="panel"><h2>Latest</h2><ul class="list">${d.activity.slice(0, 8).map(actRow).join("") || `<li class="empty-row">Nothing yet.</li>`}</ul>
        <div class="actions" style="margin-top:14px"><button class="btn" data-srv-tab="activity">All activity</button></div></div>
      ${machinePanel(d.machine)}
    </div>`;
}
/* Sofa's own TV apps: they play MKV, HEVC and Dolby sound as they are, so this computer converts less. */
function appsPanel(base, a) {
  const ft = a && a.firetv;
  const kept = ft ? `On this computer: version ${esc(ft.version || "?")} (${bytes(ft.size)}), ready for your Fire TVs.`
    : a && a.offline ? "Not on this computer: Sofa is offline. Put sofa-firetv.apk in Sofa's data/apps folder yourself."
    : "Not on this computer yet: Sofa gets it from GitHub by itself a minute after starting.";
  return `<div class="panel"><h2>Apps</h2><p class="hint">Sofa's own apps for TVs. They play most files as they are, so this computer hardly converts anything. Sign in by approving a code on your phone.</p>
    <div class="addr apps">
      <div><b>Fire TV</b><span>Easiest: open Sofa in Silk on the Fire TV and press <b>Install the Sofa app</b> on Home. Or with the Downloader app (allowed under Settings → My Fire TV → Developer options → Install unknown apps), type:</span>
        <code>${esc(base)}/firetv</code><span>${kept}${a && !a.offline ? ` <button class="mini" data-apps-fetch="1">Get the newest now</button>` : ""}${a && a.error ? ` <span class="bad">Last try: ${esc(a.error)}</span>` : ""}</span></div>
      <div><b>Roku</b><code>${esc(base)}/roku.zip</code><span>Put the Roku in developer mode (on its remote: Home ×3, Up ×2, Right, Left, Right, Left, Right), download this file on a computer, and upload it on the page at the address the Roku shows.</span></div>
      <div><b>Raspberry Pi</b><code>curl -fsSL ${esc(base)}/sofa-box/install.sh | sudo sh -s ${esc(base)}</code><span>Makes a Pi on the TV a Sofa box: it starts straight into Sofa, with its own player. Run this on the Pi, or write the ready-made card from the <a href="https://github.com/krintoxi/sofa/releases" target="_blank" rel="noopener">releases page</a> (Raspberry Pi Imager, Use custom). The TV's remote, your phone or a game controller work it.</span></div>
    </div></div>`;
}
const ENC_NAMES = { h264_videotoolbox: "Apple VideoToolbox", libx264: "x264" };
function machinePanel(m) {
  if (!m) return "";
  const bad = m.damaged || [];
  const speeds = Object.entries(m.speeds || {}).map(([k, v]) => `<div class="stat"><b>${v && !bad.includes(k) ? Math.round(v) : "—"}</b><span>${esc(ENC_NAMES[k] || k)}${bad.includes(k) ? ": makes damaged pictures on this computer (lines across), not used" : v ? " frames/s" : ": doesn't work here"}${m.best === k ? " · in use" : ""}</span></div>`).join("");
  const gs = m.gentle_setting === true ? "on" : m.gentle_setting === false ? "off" : "auto";
  return `<div class="panel wide"><h2>This computer</h2>
    <p class="hint">${esc(m.cpu)} · ${m.cores} cores${m.memory ? " · " + bytes(m.memory) + " memory" : ""} · ${esc(m.system)}${m.modern_cpu === false ? " · an older processor" : ""}</p>
    ${speeds ? `<p class="hint">Converting 1080p video (tested ${esc(ago(m.measured))}); Sofa uses the faster way:</p><div class="stats">${speeds}</div>`
      : `<p class="hint">Sofa tests how fast this computer converts video a minute after starting.</p>`}
    ${bad.includes("h264_videotoolbox") ? `<div class="warn-box"><b>Apple's video converter draws lines across the picture on this Mac</b>
      <p>That happens on older Macs running a newer macOS. Sofa doesn't use it any more: previews are made again, and video converted while you watch is fine.
      Videos Sofa converted to MP4 before may have those lines too. Sofa kept their originals, so it can convert them again properly (in the background; they show under Converting).</p>
      <button class="btn" data-redo-damaged="1">Convert them again</button></div>` : ""}
    <div class="toggle"><div><b>Gentle mode ${m.gentle ? "is on" : "is off"}</b><span>For older computers: video converted while you watch is 720p at most, and converting files, making previews ahead of time and finding intros wait for the quiet hours (${esc(m.quiet_hours)}). What someone is watching is still done straight away.</span></div>
      <select data-setting-select="gentle" aria-label="Gentle mode">${[["auto", "Automatic" + (gs === "auto" ? (m.gentle ? " (on)" : " (off)") : "")], ["on", "On"], ["off", "Off"]].map(o =>
        `<option value="${o[0]}"${gs === o[0] ? " selected" : ""}>${o[1]}</option>`).join("")}</select></div>
    <form class="inline-form" data-quiet-form="1"><label class="field"><span>Quiet hours</span><input name="v" value="${esc(m.quiet_hours)}" pattern="\\d\\d:\\d\\d-\\d\\d:\\d\\d" aria-label="Quiet hours"></label>
      <button class="btn">Save</button><button class="btn ghost" type="button" data-machine-test="1">Test the speed again</button></form></div>`;
}
/* The same episode or movie more than once: the best copy is kept (sharpest, then MP4, then biggest),
   the others go to Deleted (emptied when you're sure). */
function dupesPanel(groups) {
  if (!groups) return `<div class="panel wide"><h2>Duplicates</h2><p class="hint">Looking…</p></div>`;
  if (!groups.length) return `<div class="panel wide"><h2>Duplicates</h2><p class="hint">Nothing is here twice.</p></div>`;
  const spare = groups.reduce((n, g) => n + g.spare, 0);
  const copy = (c, i) => `${i ? "" : `<b class="tag ok">keep</b> `}${esc(c.file)} · ${esc([quality(c.height), (c.ext || "").toUpperCase(), c.size ? bytes(c.size) : "", c.where].filter(Boolean).join(" · "))}`;
  return `<div class="panel wide"><h2>Duplicates</h2>
    <p class="hint">${plural(groups.length, "title")} ${groups.length === 1 ? "is" : "are"} here more than once; the spare copies use ${bytes(spare)}. Sofa keeps the best copy of each (the sharpest picture, then MP4, then the bigger file) and puts the others in Deleted, which you empty when you're sure.</p>
    <div class="actions"><button class="btn" data-dupes="*">Keep the best of each (frees ${bytes(spare)})</button></div>
    <ul class="list">${groups.slice(0, 60).map(g => `<li><span><b>${esc(g.title)}</b><br><span class="when">${g.copies.map(copy).join("<br>")}</span></span>
      <button class="mini" data-dupes="${esc(g.key)}">Keep the best</button></li>`).join("")}</ul></div>`;
}
function srvLibrary(d) {
  const L = d.library, f = L.folders;
  const folders = [["Inbox (drop things here)", f.inbox], ["Shows", f.shows], ["Movies", f.movies], ["Adult", f.adult], ["Music", f.music],
    ["Music videos", f.musicvideos], ["Needs Review", f.review], ["Converted originals", f.originals], ["Deleted", L.deleted_folder]];
  const missing = d.missing ? (d.missing.length ? d.missing.map(m => `<li><span><b>${esc(m.title)}</b>${m.year ? " (" + esc(m.year) + ")" : ""}<br><span class="when">${m.kind === "show" ? "Show" : "Movie"}${m.adult ? " · Adult" : ""}</span></span>
      <button class="mini" data-fix="${esc(m.id)}">Find details</button></li>`).join("") : `<li class="empty-row">Everything has details. Nice.</li>`) : `<li class="empty-row">Loading…</li>`;
  return `<div class="panels">
    <div class="panel"><h2>Library</h2><p class="hint">Updated ${esc(ago(L.generated))}${L.scanning ? ", checking now" : ""}. Sofa notices new files by itself within a minute.</p>
      <div class="stats"><div class="stat"><b>${L.shows}</b><span>shows</span></div><div class="stat"><b>${L.episodes}</b><span>episodes</span></div>
      <div class="stat"><b>${L.movies}</b><span>movies</span></div><div class="stat"><b>${L.albums}</b><span>albums</span></div></div>
      <div class="actions"><button class="btn" data-admin="scan">Check for new files now</button><button class="btn" data-admin="inbox">Sort the Inbox now</button></div></div>
    <div class="panel"><h2>Folders</h2><p class="hint">Where everything lives on this computer. You can also put things there by hand (see docs/folder-structure.md).</p>
      <dl class="kv">${folders.map(x => `<dt>${esc(x[0])}</dt><dd><code>${esc(x[1])}</code></dd>`).join("")}</dl></div>
    <div class="panel wide"><h2>Missing details</h2><p class="hint">Sofa found nothing about these. Click <b>Find details</b>, search, and pick the right one; the artwork and description follow. You can also do it from any show or movie page.</p>
      <ul class="list two-col">${missing}</ul></div>
    ${dupesPanel(d.duplicates)}
    <div class="panel wide"><h2>Needs your help</h2><p class="hint">Files Sofa couldn't identify are in the Needs Review folder. Rename them like <code>Show Name S01E02.mkv</code> or <code>Movie Title (1999).mkv</code> and drop them in the Inbox again.</p>
      <ul class="list">${d.review.length ? d.review.map(actRow).join("") : `<li class="empty-row">Nothing needs your attention.</li>`}</ul></div>
    <div class="panel wide"><h2>Skip Intro</h2>
      ${d.intros ? `<p class="hint">Sofa listens to neighbouring episodes of each season for the intro and credits they share (using ${esc(d.intros.method)} fingerprints). Whatever someone starts watching is done first.</p>
      <div class="stats"><div class="stat"><b>${d.intros.checked} / ${d.intros.seasons}</b><span>seasons checked</span></div>
        <div class="stat"><b>${d.intros.intros}</b><span>episodes with Skip Intro</span></div><div class="stat"><b>${d.intros.credits}</b><span>with credits found</span></div></div>
      <p class="hint">${d.intros.working ? "Listening to " + esc(d.intros.working) + " now." : d.intros.checked < d.intros.seasons ? "Waiting for a quiet moment to carry on." : "All done."}
        Wrong or missing? In the player, Options (gear) has "Wrong intro" and "Mark the intro by hand", for one episode or the whole season.</p>
      <div class="actions"><button class="btn ghost" data-intros-recheck="1">Listen to every season again</button></div>` : `<p class="hint">Loading…</p>`}</div>
    <div class="panel"><h2>Pictures and previews</h2>
      <p class="hint">Pictures Sofa took from the videos themselves can be taken again (covers from TVmaze, TMDB, ThePornDB and ones you added stay). One title at a time: <b>Manage</b> on its page.</p>
      ${L.previews ? `<div class="stats"><div class="stat"><b>${L.previews.made} / ${L.previews.wanted}</b><span>hover previews ready</span></div>
        ${L.cache ? `<div class="stat"><b>${bytes(L.cache.bytes)}</b><span>Sofa's own pictures and previews</span></div>` : ""}</div>` : ""}
      <div class="actions"><button class="btn" data-new-pictures="1">Take new pictures for everything</button>
        <button class="btn ghost" data-free-space="1">Free up space</button><button class="btn ghost" data-retry-details="1">Look up missing details again</button></div></div>
    <div class="panel"><h2>Deleted folder</h2>
      <p class="hint">What you delete from Sofa waits here first: <code>${esc(L.deleted_folder || "")}</code>. Put something back by moving it into the Inbox.</p>
      ${L.deleted ? `<div class="stats"><div class="stat"><b>${L.deleted.files}</b><span>files</span></div><div class="stat"><b>${bytes(L.deleted.bytes)}</b><span>used</span></div></div>
      ${L.deleted.files ? `<div class="actions"><button class="btn danger" data-empty-deleted="1">Empty it for good</button></div>` : ""}` : ""}</div>
    <div class="panel wide">${srvSwitch("tidy_library", d.settings.tidy_library, "Tidy folders automatically", "Renames download-style folders (\"Heat.1995.1080p.BluRay\" becomes \"Heat (1995)\"), gives each movie in a collection its own folder, and moves stray XXX folders into Adult. Nothing is deleted.")}</div>
  </div>`;
}
/* ---------- Server → Storage: the library on more than one drive ---------- */
function spaceBar(p) {
  if (!p.total) return "";
  const used = Math.round((1 - p.free / p.total) * 100);
  return `<div class="space"><span class="space-bar"><i style="width:${used}%" class="${used > 90 ? "full" : ""}"></i></span>
    <span class="when">${bytes(p.free)} free of ${bytes(p.total)}</span></div>`;
}
function srvStorage(d) {
  const st = d.storage;
  if (!st) return `<div class="panel wide"><p class="hint">Loading…</p></div>`;
  const placeCard = p => {
    const c = p.counts || {};
    const what = [c.shows ? plural(c.shows, "show") : "", c.movies ? plural(c.movies, "movie") : "", c.adult && session.user.adult ? c.adult + " adult" : "",
      c.bytes ? bytes(c.bytes) : ""].filter(Boolean).join(" · ") || "Nothing yet";
    return `<li class="place${p.connected ? "" : " gone"}"><div class="place-main">
        <span class="place-name"><b>${esc(p.name)}</b>${p.main ? `<span class="tag">Main</span>` : ""}${p.connected ? "" : `<span class="tag bad">Not plugged in</span>`}</span>
        <span class="when"><code>${esc(p.path)}</code></span>
        <span class="when">${esc(what)}</span>${p.connected ? spaceBar(p) : `<span class="when">Its shows and movies come back when it's plugged in again.</span>`}</div>
      <div class="place-actions"><label class="check"><input type="radio" name="newTo" data-new-to="${esc(p.id)}"${st.new_to === p.id ? " checked" : ""}${p.connected ? "" : " disabled"}> New things go here</label>
        ${p.main ? "" : `<button class="mini danger" data-place-remove="${esc(p.id)}">Stop using</button>`}</div></li>`;
  };
  const warn = dr => dr.problem === "no-permission" ? `<span class="form-error">macOS isn't letting Sofa open it yet. Press "Use this drive" for the steps.</span>`
    : dr.problem === "read-only" ? `<span class="form-error">Read-only${dr.fs === "ntfs" ? " (NTFS: a Mac can't write to it; reformat as exFAT or APFS)" : ""}. Sofa can play from it but can't put new things on it.</span>`
    : dr.problem ? `<span class="form-error">${esc(dr.problem)}</span>`
    : dr.fat32 ? `<span class="hint">FAT32 can't hold files bigger than 4 GB (most movies are). exFAT or APFS is better.</span>` : "";
  const driveRow = dr => `<li class="place"><div class="place-main"><span class="place-name"><b>${esc(dr.name)}</b>${dr.fs ? `<span class="tag">${esc(dr.fs)}</span>` : ""}</span>
      <span class="when"><code>${esc(dr.path)}</code></span>${spaceBar(dr)}${warn(dr)}</div>
      <div class="place-actions"><button class="btn${dr.problem === "read-only" ? "" : " primary"}" data-drive-use="${esc(dr.path)}" data-drive-name="${esc(dr.name)}" data-drive-existing="${esc(dr.existing || "")}">${dr.existing ? "Connect its Sofa library" : "Use this drive"}</button></div></li>`;
  const tr = (st.transfers || []).map(t => `<li class="conv ${t.state === "done" ? "done" : t.state === "failed" ? "failed" : "working"}"><div class="conv-main"><b>${esc(t.title)}</b>
      <span class="when">${esc(t.from)} → ${esc(t.to)} · ${t.state === "copying" ? "Copying" : t.state === "checking" ? "Checking the copy" : t.state === "done" ? "Moved" : "Didn't work: " + esc(t.error || "")}${t.total ? " · " + bytes(t.total) : ""}</span>
      ${t.state === "copying" ? `<span class="bar-line"><i style="width:${Math.round(100 * t.done / Math.max(1, t.total))}%"></i></span>` : ""}</div>
      ${t.state === "copying" ? `<span class="when">${Math.round(100 * t.done / Math.max(1, t.total))}%</span>` : ""}</li>`).join("");
  return `<div class="panels">
    <div class="panel wide"><h2>Where your library is</h2>
      <p class="hint">Sofa shows everything on all of these as one library. A show with seasons in two places is one show. Pick where new things from the Inbox go; new episodes of a show that's already on a drive go to that drive.</p>
      <ul class="list places">${st.places.map(placeCard).join("")}</ul></div>
    ${tr ? `<div class="panel wide"><h2>Moving between drives</h2><ul class="list">${tr}</ul></div>` : ""}
    <div class="panel wide"><h2>Drives on this computer</h2>
      <p class="hint">Plug in a flash drive or an external SSD and it shows up here within a few seconds. "Use this drive" makes a <b>Sofa Library</b> folder on it (with Shows, Movies, Adult, Music inside); you can put things there by hand too. To make room on this computer, open a show or movie and press <b>Manage → Move it to another drive</b>.</p>
      <ul class="list places">${st.drives.length ? st.drives.map(driveRow).join("") : `<li class="empty-row">No other drives found. Plug one in; it appears here by itself.</li>`}</ul>
      <p class="hint">Best formats: APFS or Mac OS Extended for a drive used only with this Mac, exFAT to share it with Windows too.</p></div>
  </div>`;
}
function useDriveDialog(path, name, existing) {
  const d = openDialog(`<h2>${existing ? "Connect its Sofa library" : "Use " + esc(name) + " for Sofa"}</h2>
    <p>${existing ? "This drive already has a Sofa library on it. Sofa adds everything in it to the library." : "Sofa makes a folder on it with Shows, Movies, Adult, Music and Music Videos inside, and adds what you put there to the library."}</p>
    <form class="drive-form"><label class="field"><span>Name</span><input name="name" maxlength="40" value="${esc(name)}"></label>
      <label class="field"><span>Folder on the drive</span><input name="path" value="${esc(existing || path.replace(/\/$/, "") + "/Sofa Library")}"></label>
      <label class="check"><input type="checkbox" name="newhere"> Put new things from the Inbox here</label>
      <div class="form-error" role="alert"></div>
      <div class="actions"><button class="btn primary">${existing ? "Connect it" : "Use this drive"}</button><button class="btn ghost" type="button" data-dismiss="1">Cancel</button></div></form>`);
  const f = $(".drive-form", d);
  f.addEventListener("submit", async e => {
    e.preventDefault();
    try {
      await api("/api/admin/storage", { add: { path: f.path.value, name: f.name.value, new_here: f.newhere.checked } });
      closeDialog(); toast(f.name.value + " is part of the library now."); loadAdmin(); setTimeout(reloadLibrary, 4000);
    } catch (ex) { $(".form-error", d).textContent = ex.message; }
  });
}
function moveDriveDialog(id) {
  const x = byId.get(id); if (!x) return;
  const here = x.place || "", options = (LIB.places || []).filter(p => p.id !== here && p.connected);
  const d = openDialog(`<h2>Move it to another drive</h2><p><b>${esc(x.name || x.title)}</b> is on ${esc(((LIB.places || []).find(p => p.id === here) || { name: "this computer" }).name)}.
    Sofa copies it over in the background, checks the copy, then removes the original. Watch progress stays.</p>
    <div class="manage-list">${options.length ? options.map(p => `<button data-to="${esc(p.id)}">${icon("i-next-arrow")}<span><b>${esc(p.name)}</b></span></button>`).join("")
      : `<p class="hint">There's no other drive to move it to. Add one under Server → Storage.</p>`}</div>
    <div class="form-error" role="alert"></div><div class="actions"><button class="btn ghost" data-dismiss="1">Cancel</button></div>`);
  d.addEventListener("click", async e => {
    const b = e.target.closest("[data-to]"); if (!b) return;
    try { await api("/api/admin/storage", { move: { id, to: b.dataset.to } }); closeDialog(); toast("Moving it in the background. Server → Storage shows how far along it is."); }
    catch (ex) { $(".form-error", d).textContent = ex.message; }
  });
}
function srvConvert(d) {
  const c = d.convert || {}, counts = c.counts || {};
  const state = { queued: "Waiting", working: "Converting", done: "Done", failed: "Didn't work", gone: "File gone" };
  const rows = (c.rows || []).map(r => `<li class="conv ${r.state}"><div class="conv-main"><b>${esc(r.title || "Untitled")}</b>
      <span class="when">${esc(state[r.state] || r.state)}${r.state === "done" && r.how ? " · " + esc(r.how) : ""}${r.state === "done" && r.before && r.after ? " · " + bytes(r.before) + " → " + bytes(r.after) : ""}${r.error ? " · " + esc(r.error) : ""}</span>
      ${r.state === "working" ? `<span class="bar-line"><i style="width:${Math.round((r.progress || 0) * 100)}%"></i></span>` : ""}</div>
      <span class="row-actions">${r.state === "working" ? `<span class="when">${Math.round((r.progress || 0) * 100)}%</span>` : ""}
      ${r.state === "failed" ? `<button class="mini" data-conv-retry="${r.rid}">Try again</button>` : ""}
      ${r.state === "queued" || r.state === "working" ? `<button class="mini danger" data-conv-cancel="${r.rid}">Stop</button>` : ""}</span></li>`).join("");
  return `<div class="panels">
    <div class="panel wide"><h2>Convert to MP4</h2>
      <p class="hint">MKV, AVI and similar files have to be adapted every time they play, which can stall on some devices. Converting them once makes them play instantly everywhere. Sofa does it here, in the background, one file at a time, and pauses while someone is watching. ${c.hardware ? "This Mac's video hardware does the work, so it's quick." : d.encoder ? "Using " + esc(d.encoder) + "." : ""}</p>
      <div class="stats"><div class="stat"><b>${c.candidates == null ? "…" : c.candidates}</b><span>files could be converted</span></div>
        <div class="stat"><b>${(counts.queued || 0) + (counts.working || 0)}</b><span>waiting or converting</span></div>
        <div class="stat"><b>${counts.done || 0}</b><span>converted</span></div>
        ${c.saved > 0 ? `<div class="stat"><b>${bytes(c.saved)}</b><span>space saved</span></div>` : ""}</div>
      ${c.waiting_for_viewers === "quiet hours" ? `<p class="hint">Gentle mode: the automatic ones wait for the quiet hours (Overview → This computer). Files you ask for are converted straight away.</p>`
        : c.waiting_for_viewers ? `<p class="hint">Paused while someone watches something that's being converted live, or the computer is busy.</p>` : ""}
      <div class="actions">${c.candidates ? `<button class="btn primary" data-conv-all="1">Convert all ${c.candidates} now</button>` : ""}
        ${(c.rows || []).some(r => r.state === "done" || r.state === "failed") ? `<button class="btn" data-conv-clear="1">Clear finished</button>` : ""}</div></div>
    <div class="panel">${srvSwitch("auto_convert", d.settings.auto_convert, "Convert new files automatically", "Anything new that needs it is converted a minute or two after it arrives.")}
      ${srvSwitch("keep_originals", d.settings.keep_originals, "Keep the originals", "Moves each original to <code>" + esc(d.library.folders.originals) + "</code> instead of deleting it. Turn off to save space once you trust the results.")}</div>
    <div class="panel"><h2>Live conversion</h2><p class="hint">For files that haven't been converted yet.</p>
      <div class="toggle"><div><b>At the same time</b><span>How many people can watch converted video at once. ${c.hardware ? "A Mac with Apple silicon handles 3 or 4 easily." : "Each one uses a processor core."}</span></div>
        <select class="mini-select" data-setting-select="max_transcodes">${[1, 2, 3, 4, 6].map(n => `<option value="${n}"${+d.settings.max_transcodes === n ? " selected" : ""}>${n}</option>`).join("")}</select></div></div>
    <div class="panel wide"><h2>Queue</h2><ul class="list">${rows || `<li class="empty-row">Nothing queued.</li>`}</ul></div>
  </div>`;
}
function srvDownloads(d) {
  const x = d.downloads || { rows: [] };
  const state = { queued: "Waiting", working: "Downloading", done: "Saved; being filed", failed: "Didn't work" };
  const rows = x.rows.map(r => `<li class="conv ${r.state}"><div class="conv-main"><b>${esc(r.title || r.url || "Download")}</b>
      <span class="when">${r.adult ? "Adult · " : ""}${esc(state[r.state] || r.state)}${r.error ? " · " + esc(r.error) : ""}${r.url && r.title ? " · " + esc(r.url.replace(/^https?:\/\//, "").slice(0, 60)) : ""}</span>
      ${r.state === "working" ? `<span class="bar-line"><i style="width:${Math.round((r.progress || 0) * 100)}%"></i></span>` : ""}</div>
      <span class="row-actions">${r.state === "working" ? `<span class="when">${Math.round((r.progress || 0) * 100)}%</span>` : ""}
      ${r.state === "failed" ? `<button class="mini" data-dl-retry="${r.id}">Try again</button>` : ""}
      ${r.state === "queued" || r.state === "working" ? `<button class="mini danger" data-dl-cancel="${r.id}">Stop</button>` : ""}</span></li>`).join("");
  const here = location.origin;
  const mark = adult => "javascript:location.href=" + JSON.stringify(here + "/#/add?" + (adult ? "adult=1&" : "") + "url=") + "+encodeURIComponent(location.href)";
  return `<div class="panels">
    <div class="panel wide"><h2>Save from a link</h2>
      <p class="hint">Paste the address of a video page. Sofa downloads it with <a href="https://github.com/yt-dlp/yt-dlp" target="_blank" rel="noopener">yt-dlp</a> (free and open source; it knows YouTube, Vimeo and well over a thousand other sites, including the free adult video sites), names it and files it, in Adult if you tick the box. Only save videos you're allowed to keep.</p>
      ${(x.installing || {}).running ? `<div class="alert"><b><i class="reading-spin small" aria-hidden="true"></i>Installing yt-dlp…</b><span>${esc(x.installing.step || "")}</span></div>`
        : x.tool && x.version ? `<p class="hint">yt-dlp ${esc(x.version)} is ready${x.own ? ", and Sofa keeps it up to date" : ""}.${x.ffmpeg ? "" : " Install ffmpeg too, so picture and sound can be joined."}</p>`
        : `<div class="alert"><b>${x.tool ? "yt-dlp is there but doesn't start." : "One step first: install yt-dlp."}</b><span>Sofa gets the official copy from GitHub and keeps it up to date. If the ready-made Mac version can't run on this computer, it tries the cross-platform one with a newer Python, then Homebrew.</span>
          ${(x.installing || {}).error ? `<span class="form-error">${esc(x.installing.error)}</span>` : ""}
          <button class="btn primary" data-dl-install="1">${(x.installing || {}).error || x.tool ? "Try again" : "Install yt-dlp"}</button></div>`}
      <label class="field inline-select"><span>Use the sign-in from</span><select data-setting-select="ytdlp_cookies" aria-label="Use the sign-in from">
        ${[["", "No browser"], ["safari", "Safari"], ["chrome", "Chrome"], ["firefox", "Firefox"], ["edge", "Edge"], ["brave", "Brave"], ["file", "cookies.txt in data/bin"]].map(o =>
          `<option value="${o[0]}"${(d.settings.ytdlp_cookies || "") === o[0] ? " selected" : ""}>${o[1]}</option>`).join("")}</select></label>
      <p class="hint">For sites that want you signed in or to confirm your age: do that in a browser on the Sofa computer, then pick it here. Safari needs Full Disk Access for the program running Sofa; Firefox works without it.</p>
      <div class="actions"><button class="btn primary" data-add-link="normal">+ Add a link</button>${session.user.adult ? `<button class="btn" data-add-link="adult">+ Add a link to Adult</button>` : ""}
        <button class="btn" data-send-files="normal">Send files from this device</button>
        ${x.rows.some(r => r.state === "done" || r.state === "failed") ? `<button class="btn ghost" data-dl-clear="1">Clear finished</button>` : ""}</div>
      ${x.waiting ? `<p class="hint">Waiting while someone watches a video Sofa is converting.</p>` : ""}
      <ul class="list" style="margin-top:14px">${rows || `<li class="empty-row">Nothing yet.</li>`}</ul></div>
    <div class="panel wide"><h2>Send to Sofa from your browser</h2>
      <p class="hint">Drag a button to your bookmarks bar. On any video page, click it and Sofa's "Save a video" box opens with the link filled in.</p>
      <div class="actions"><a class="btn" href="${esc(mark(false))}" onclick="return false">Send to Sofa</a>${session.user.adult ? `<a class="btn" href="${esc(mark(true))}" onclick="return false">Send to Sofa (Adult)</a>` : ""}</div></div>
  </div>`;
}
function srvLive(d) {
  return `<div class="panels"><div class="panel wide"><h2>Live TV channel lists</h2><p class="hint">M3U playlists of free channels. Sofa re-downloads them twice a day. Click a list below to add it.</p>
    <ul class="list">${(d.live || []).map(p => `<li><span><b>${esc(p.name)}</b>${p.adult ? ` <span class="tag">Adult</span>` : ""}<br><span class="when">${p.error ? "Problem: " + esc(p.error) : plural(p.count || 0, "channel")}</span></span>
      <button class="mini danger" data-live-remove="${esc(p.url)}">Remove</button></li>`).join("") || `<li class="empty-row">No channel lists yet.</li>`}</ul>
    <div class="presets">${PRESETS.filter(p => !(d.live || []).some(x => x.url === p[1])).map(p => `<button class="mini" data-preset="${esc(p[1])}" data-name="${esc(p[0])}">+ ${esc(p[0])}</button>`).join("")}</div>
    <form class="inline-form" id="addList"><label class="field"><span>Name</span><input name="name" maxlength="60" placeholder="My channels"></label>
      <label class="field"><span>M3U link</span><input name="url" type="url" required placeholder="https://…/list.m3u"></label>
      <button class="btn" type="submit">Add</button>
      <label class="check"><input type="checkbox" name="adult"> Adult channels (only people allowed to see Adult get them; never TVs or guests)</label>
      <div class="form-error" role="alert" style="grid-column:1/-1"></div></form>
    <p class="hint" style="margin-top:14px">About adult channels: the free iptv-org lists stopped carrying adult channels in January 2024, so there's no free list Sofa can suggest. If you have an M3U link from a service you trust, add it with the Adult box ticked.</p></div></div>`;
}
function devicesPanel(list) {
  if (!list) return "";
  const kind = s => /^Paired: /.test(s.device) ? s.device.slice(8) + " (TV)" : /iPhone|iPad/.test(s.device) ? "iPhone or iPad" : /Android/.test(s.device) ? "Android"
    : /AFT|Silk/.test(s.device) ? "Fire TV" : /Macintosh/.test(s.device) ? "Mac" : /Windows/.test(s.device) ? "Windows" : s.device ? "Browser" : "A device";
  return `<div class="panel wide"><h2>Signed-in devices</h2><p class="hint">Every phone, computer and TV signed in to Sofa. Sign out one you don't recognise, or a TV you gave away. TVs signed in with a phone are named after the TV.</p>
    <ul class="list">${list.slice(0, 80).map(s => `<li><span><b>${esc(kind(s))}</b> · ${esc(s.user)}<br><span class="when">Last used ${esc(ago(s.seen))}</span></span>
      <button class="mini danger" data-session-end="${esc(s.id)}">Sign out</button></li>`).join("") || `<li class="empty-row">Nobody is signed in.</li>`}</ul></div>`;
}
function srvPeople(d) {
  const users = d.users.filter(u => !u.guest).map(u => `<li><span><b>${esc(u.name)}</b>${u.admin ? ` <span class="tag ok">admin</span>` : ""}<br><span class="when">${u.seen ? "Last seen " + esc(ago(u.seen)) : "Hasn't signed in yet"}</span></span>
    <span class="row-actions">${u.admin ? "" : `<label class="adult-toggle" title="Sees only family titles; no Adult, Live TV or Server"><span>Kids</span><button class="switch small" role="switch" aria-checked="${!!u.kids}" data-user-kids="${u.id}" aria-label="${esc(u.name)} is a Kids profile"></button></label>`}
    ${u.kids ? "" : `<label class="adult-toggle" title="Can see the Adult section"><span>Adult</span><button class="switch small" role="switch" aria-checked="${!!u.adult}" data-user-adult="${u.id}" aria-label="${esc(u.name)} can see the Adult section"></button></label>`}
    <button class="mini" data-user-pass="${u.id}" data-user-name="${esc(u.name)}">New password</button>${u.id !== session.user.id ? `<button class="mini danger" data-user-del="${u.id}" data-user-name="${esc(u.name)}">Remove</button>` : ""}</span></li>`).join("");
  return `<div class="panels">
    ${devicesPanel(d.sessions)}
    <div class="panel wide"><h2>People</h2><p class="hint">Everyone gets their own sign-in and their own "continue watching". The <b>Adult</b> switch decides who sees the Adult section (it's off for everyone until you turn it on, you included). A <b>Kids</b> profile sees only family titles (rated for children, or Kids and Family genres), and no Adult, Live TV or Server page; allow or block any title with <b>For kids</b> on its page.</p><ul class="list">${users}</ul>
      <form class="inline-form" id="addUser"><label class="field"><span>Name</span><input name="name" required maxlength="40"></label>
      <label class="field"><span>Password</span><input name="password" type="password" required minlength="8" autocomplete="new-password"></label>
      <button class="btn" type="submit">Add</button><label class="check"><input type="checkbox" name="admin"> Can manage the server</label>
      <label class="check"><input type="checkbox" name="adult"> Can see the Adult section</label>
      <div class="form-error" role="alert" style="grid-column:1/-1"></div></form></div>
    <div class="panel wide"><h2>Guests</h2><p class="hint">Visitors on your Wi-Fi scan this code to watch as "Guest": their own history and likes, no settings, never the Adult section, and it never works from outside the house. Sessions end after a day.</p>
      <div class="guest-row"><div class="qr" id="guestQr" data-url="${esc(d.guest.links[0] || "")}"></div>
      <div><div class="addr">${d.guest.links.map(l => `<div><b>Guest link</b><code>${esc(l)}</code></div>`).join("")}</div>
      <p class="hint" style="margin-top:10px">Tip: reserve this computer's address in your router so the code keeps working.</p>
      <div class="row-actions"><button class="mini" data-guest-clear="1">Clear guest history</button></div></div></div>
      ${srvSwitch("guest_access", d.guest.enabled, "Allow guests", "Turn off to make the guest code stop working.")}</div></div>`;
}
/* Internet and HTTPS: encryption, an address, the router, the certificate, then letting the internet in. */
function srvInternet(d) {
  const n = d.internet;
  if (!n) return `<p class="admin-lede">Loading…</p>`;
  const h = n.https, lan = (n.lan || [])[0] || "this computer", until = h.not_after ? new Date(h.not_after * 1000).toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" }) : "";
  const ok = (v, yes, no, unknown) => v === true ? `<span class="good">✓ ${yes}</span>` : v === false ? `<span class="bad">✗ ${no}</span>` : `<span class="hint">${unknown || ""}</span>`;
  const radio = (v, label, hint) => `<label class="net-choice"><input type="radio" name="https" value="${v}"${h.mode === v ? " checked" : ""}><span><b>${label}</b><small>${hint}</small></span></label>`;
  const where = n.remote === "public" && h.domain ? `https://${h.domain}` : "";
  const summary = n.remote === "public"
    ? `On the internet${where ? ` at <code>${esc(where)}</code>` : ""}, over HTTPS only. Everyone signs in; the Server page stays home-only.`
    : h.mode !== "off" ? `Home only, with HTTPS${h.listening ? ` on port ${esc(h.listening)}` : ""}.` : "Home network and Tailscale only. Nothing is reachable from the internet.";
  return `<div class="panels">
    <div class="panel wide"><h2>Internet and HTTPS</h2><p class="hint">${summary}</p>
      ${h.mode !== "off" && h.names.length ? `<p class="hint">Certificate for <b>${esc(h.names.join(", "))}</b>${until ? `, valid until ${esc(until)}` : ""}${h.issuer ? ` (from ${esc(h.issuer)})` : ""}.${h.mode === "letsencrypt" ? " It renews by itself." : ""}</p>` : ""}
      ${h.error ? `<div class="warn-box"><b>HTTPS problem</b><p>${esc(h.error)}</p></div>` : ""}${h.file_error ? `<div class="warn-box"><p>${esc(h.file_error)}</p></div>` : ""}
    </div>
    <form class="panel wide net-form" data-net-form="1"><h2>1. Encryption</h2>
      <div class="net-choices">
        ${radio("off", "Off", "Plain HTTP at home, like before.")}
        ${radio("self", "Sofa's own certificate", "Encrypted at home without a domain. Each browser asks once whether to trust it.")}
        ${radio("letsencrypt", "Free certificate from Let's Encrypt", "For your own address on the internet, trusted everywhere. Needs a domain (a free one works).")}
        ${radio("files", "My own certificate files", "From your company, Tailscale (tailscale cert) or anywhere else.")}
      </div>
      <h2>2. Your address</h2>
      <p class="hint">Your own domain (pointed at your home's internet address), or a free one: make a name at <a href="https://www.duckdns.org" target="_blank" rel="noopener">duckdns.org</a>, type <code>yourname.duckdns.org</code> here and paste its token. Sofa keeps it pointing at your home.</p>
      <div class="net-fields">
        <label>Domain<input name="domain" value="${esc(h.domain)}" placeholder="sofa.example.com or yourname.duckdns.org" autocomplete="off" spellcheck="false"></label>
        <label>DuckDNS token <small>(only for .duckdns.org)</small><input name="duckdns_token" type="password" placeholder="${n.duckdns_token ? "Saved (type to replace)" : "Paste it here"}" autocomplete="off"></label>
        <label>Email <small>(optional: Let's Encrypt writes if renewing ever fails)</small><input name="acme_email" type="email" value="${esc(n.acme_email)}" autocomplete="off"></label>
        <label>Certificate file <small>(own files only)</small><input name="cert_file" value="${esc(n.cert_file)}" placeholder="/path/to/fullchain.pem" spellcheck="false"></label>
        <label>Key file<input name="key_file" value="${esc(n.key_file)}" placeholder="/path/to/privkey.pem" spellcheck="false"></label>
        <label>HTTPS port <small>(on this computer)</small><input name="https_port" type="number" min="1" max="65535" value="${esc(h.port)}"></label>
      </div>
      <div class="actions"><button class="btn primary" type="submit">Save</button></div>
      ${n.duckdns.active ? `<p class="hint">DuckDNS: ${ok(n.duckdns.ok, "your address is up to date", n.duckdns.message || "not accepted", "checking…")}</p>` : ""}
    </form>
    <div class="panel wide"><h2>3. The router</h2>
      <p class="hint">The internet reaches your home at the router. It has to send two ports to this computer: <b>443</b> (HTTPS) to <code>${esc(lan)}:${esc(h.port)}</code>, and <b>80</b> to <code>${esc(lan)}:${esc(n.port)}</code> (Let's Encrypt checks your address there; browsers are sent on to HTTPS).</p>
      <div class="toggle"><div><b>Ask the router to do it (UPnP)</b><span>Most home routers can, when UPnP is on in their settings. Sofa asks again every few hours, as routers forget.${n.upnp.message ? " " + (n.upnp.ok ? `<span class="good">✓ ${esc(n.upnp.message)}</span>` : `<span class="bad">${esc(n.upnp.message)}</span>`) : ""}</span></div>
        <button class="switch" role="switch" aria-checked="${!!n.upnp.on}" data-net-upnp="1" aria-label="Ask the router to forward the ports"></button></div>
      <div class="actions"><button class="btn" data-net-ports="1">Try it now</button></div>
      <p class="hint">${n.public_ip ? `Your home's internet address: <code>${esc(n.public_ip)}</code>. ` : ""}${h.domain && n.public_ip ? ok(n.points_here, esc(h.domain) + " points here", esc(h.domain) + " doesn't point here yet (DNS can take a few minutes)") : ""}</p>
    </div>
    <div class="panel wide"><h2>4. The certificate</h2>
      ${h.mode === "letsencrypt" ? `<p class="hint">Let's Encrypt checks that ${h.domain ? `<b>${esc(h.domain)}</b>` : "your domain"} reaches this computer, then gives Sofa a certificate for 90 days. Sofa renews it by itself.</p>
        ${h.busy ? `<p class="net-step"><i class="reading-spin" aria-hidden="true"></i>${esc(h.step || "Working")}…</p>` : `<div class="actions"><button class="btn primary" data-net-cert="1"${h.domain ? "" : " disabled"}>${h.names.length ? "Renew it now" : "Get the certificate"}</button></div>`}`
      : `<p class="hint">${h.mode === "self" ? "Sofa made its own certificate for " + esc((h.names || []).join(", ")) + "." : h.mode === "files" ? "Using your files." : "Choose a kind of encryption above first."}</p>`}
      ${h.listening ? `<p class="hint">HTTPS is answering on port ${esc(h.listening)}: <code>https://${esc(h.domain || lan)}${h.domain ? "" : ":" + esc(h.listening)}</code></p>` : ""}
    </div>
    <div class="panel wide"><h2>5. Let the internet in</h2>
      <div class="toggle"><div><b>Accept connections from the internet</b><span>Only over HTTPS, and everyone signs in. New passwords need 12 characters. 8 wrong passwords from one address lock it out for 15 minutes. The Server page and admin changes stay home-only (or over Tailscale).</span></div>
        <button class="switch" role="switch" aria-checked="${n.remote === "public"}" data-net-public="1" aria-label="Accept connections from the internet"${h.mode === "off" && !n.trust_proxy ? " disabled" : ""}></button></div>
      <p class="hint">Rather not open anything? Tailscale gives your own devices a private way in: <a href="https://github.com/krintoxi/sofa/blob/main/docs/remote-access.md" target="_blank" rel="noopener">docs/remote-access.md</a>.</p>
    </div>
  </div>`;
}
async function netSave(changes) {
  try { adminData.internet = await api("/api/admin/internet", changes); rerender(); }
  catch (e) { toast(e.message); }
}
document.addEventListener("submit", e => {
  const f = e.target.closest("[data-net-form]"); if (!f) return;
  e.preventDefault();
  const v = Object.fromEntries(new FormData(f));
  if (!v.duckdns_token) delete v.duckdns_token;                    // blank: keep the saved one
  document.activeElement && document.activeElement.blur();
  netSave(v).then(() => toast("Saved."));
});
document.addEventListener("change", e => {
  if (e.target.name === "https" && e.target.closest("[data-net-form]")) netSave({ https: e.target.value });
});
document.addEventListener("click", e => {
  const b = e.target.closest("[data-net-upnp],[data-net-ports],[data-net-cert],[data-net-public]"); if (!b) return;
  if (b.dataset.netUpnp) netSave({ upnp: b.getAttribute("aria-checked") !== "true" });
  else if (b.dataset.netPorts) { toast("Asking the router…"); netSave({ open_ports: true }).then(() => setTimeout(loadAdmin, 4000)); }
  else if (b.dataset.netCert) netSave({ get_certificate: true }).then(() => setTimeout(loadAdmin, 1500));
  else if (b.dataset.netPublic) netSave({ remote: b.getAttribute("aria-checked") === "true" ? "home" : "public" });
});
function srvSettings(d) {
  const st = d.settings, s = d.server;
  const keyField = (key, label, hint, link) => `<form class="key-form" data-key-form="${key}"><div><b>${label}</b><span>${hint} ${link}</span></div>
    <div class="key-row"><input name="v" type="password" autocomplete="off" placeholder="${st[key] ? "Saved (type to replace)" : "Paste it here"}" aria-label="${esc(label)}">
    <button class="mini" type="submit">Save</button>${st[key] ? `<button class="mini danger" type="button" data-key-clear="${key}">Remove</button>` : ""}</div></form>`;
  const pv = d.privacy || {};
  return `<div class="panels">
    <div class="panel wide privacy-panel"><h2>Privacy</h2>
      <p class="hint">Sofa runs entirely on this computer: the app, the library, the pictures and the player. Nothing needs the internet to watch, from any device at home, and no outside service is told what you have or what you watch.</p>
      ${srvSwitch("no_logs", pv.no_logs, "Keep no logs", "Nothing about what happens on this server is written anywhere: no activity list, no server log file, no list of downloads or conversions, not where people signed in from. Watch progress, My List and settings are still kept (they're how Sofa works, not logs). Turning this on doesn't erase old logs: use Wipe all logs for that.")}
      ${srvSwitch("offline", pv.offline, "Work offline", "Never use the internet: no looking up details and artwork, no update checks, no saving videos from links, no Live TV channel lists. Everything already in the library keeps working, on every device at home." + (!pv.offline && !pv.online ? " <b>The internet can't be reached right now</b>; Sofa carries on without it." : ""))}
      <div class="toggle"><div><b>Wipe all logs</b><span>Erases every log Sofa has kept: the activity list, the Adult details log, the server log, finished downloads and conversions with their titles and links, and where people signed in from. The same is taken out of the backups. Erased rows are overwritten, so they can't be recovered from the files.</span></div>
        <button class="mini danger" data-wipe-logs="1">Wipe all logs</button></div></div>
    <div class="panel"><h2>This server</h2>
      <form class="key-form" data-name-form="1"><div><b>Name</b><span>What TVs and the browser tab call it.</span></div>
        <div class="key-row"><input name="v" value="${esc(s.name)}" maxlength="40" aria-label="Server name"><button class="mini" type="submit">Save</button></div></form>
      <div class="toggle"><div><b>Look</b><span>The theme every device starts with. Each person can still pick their own with the Theme button at the top.</span></div>
        <select class="mini-select" data-setting-select="theme">${THEMES.map(t => `<option value="${t[0]}"${st.theme === t[0] ? " selected" : ""}>${t[1]}</option>`).join("")}</select></div>
      ${d.awake === "unavailable" ? "" : srvSwitch("keep_awake", d.awake === "on", "Keep this computer awake", "So Sofa is always there when the TV asks. The computer won't go to sleep by itself while Sofa runs; its screen still turns off. On a Mac, also switch on System Settings → Energy → Start up automatically after a power failure.")}
      ${srvSwitch("dlna", s.dlna, "Share with TVs", "Lets Roku, Fire TV (VLC) and smart TVs at home browse without signing in. The Adult section is never shared this way.")}
      <div class="toggle"><div><b>Remote access</b><span>${s.remote === "public" ? "Accepting internet connections, over HTTPS only." : "Home network and Tailscale only."}</span></div>
        <button class="mini" data-srv-tab="internet">Internet and HTTPS</button></div>
      <div class="toggle"><div><b>Backups</b><span>${d.backups.length ? "Last backup " + esc(ago(d.backups[0].made)) + ". " : "No backup yet. "}Accounts, watch history and settings are saved every night at ${esc(st.backup_time)} to <code>${esc(d.backup_folder)}</code>, keeping ${esc(st.backup_keep)}. Your media isn't included.</span></div>
        <button class="mini" data-admin="backup">Back up now</button></div></div>
    <div class="panel"><h2>Details and artwork</h2><p class="hint">Where Sofa looks up summaries, posters and episode titles.</p>
      ${srvSwitch("tvmaze", st.tvmaze, "Shows from TVmaze", "Free, no sign-up. Summaries, episode titles and artwork.")}
      ${srvSwitch("free_movie_lookup", st.free_movie_lookup, "Movies from the iTunes Store and Wikipedia", "Free, no sign-up. Used when there's no TMDB key.")}
      ${keyField("tmdb_api_key", "TMDB key (recommended for movies)", "The best movie posters, backgrounds and collections like \"Star Wars\". Free: sign up, then copy the \"API Key\".", `<a href="https://www.themoviedb.org/settings/api" target="_blank" rel="noopener">Get a key</a>`)}
      ${keyField("theporndb_api_key", "ThePornDB token (Adult section)", "Artwork and details for adult scenes and movies.", `<a href="https://theporndb.net/user/api-tokens" target="_blank" rel="noopener">Get a token</a>`)}</div>
    <div class="panel"><h2>Video</h2>
      <div class="toggle"><div><b>Video conversion</b><span>${s.ffmpeg ? "Ready (ffmpeg " + esc(s.ffmpeg) + (d.encoder ? ", " + esc(d.encoder) : "") + "). Files a device can't play are adapted as they stream." : "ffmpeg isn't installed, so only files a device already supports will play. On a Mac: brew install ffmpeg"}</span></div></div>
      <div class="actions"><button class="btn" data-srv-tab="convert">Converting settings</button></div></div>
  </div>`;
}
function srvUpdate(d) {
  const u = d.update || {};
  const cmd = "curl -fsSL https://raw.githubusercontent.com/" + esc((u.repo || "krintoxi/sofa@main").split("@")[0]) + "/main/tools/update.sh | sh";
  let state;
  if (u.running) state = `<div class="alert"><b>Updating…</b><span>${esc(u.step || "")}</span></div>`;
  else if (u.error) state = `<div class="alert bad"><b>The update didn't work.</b><span>${esc(u.error)} The old version is still running. Try again, or use the Terminal command below.</span></div>`;
  else if (u.done) state = `<div class="alert"><b>Updated. Sofa is restarting…</b><span>This page reloads by itself in a moment.</span></div>`;
  else if (u.rolled_back) state = `<div class="alert bad"><b>The last update was undone.</b><span>${esc(u.rolled_back)}</span></div>`;
  else if (u.available) state = `<div class="alert"><b>A new version is ready${u.latest ? ": Sofa " + esc(u.latest) : ""}.</b><span>${esc(u.latest_message || "")}${u.latest_date ? " (" + esc(new Date(u.latest_date).toLocaleDateString()) + ")" : ""}</span></div>`;
  else if (u.checked) state = `<div class="alert soft"><b>You're up to date.</b><span>Checked ${esc(ago(u.checked))}.</span></div>`;
  else state = `<div class="alert soft"><b>Not checked yet.</b></div>`;
  if (u.done) setTimeout(waitForRestart, 4000);
  return `<div class="panels"><div class="panel wide"><h2>Updates</h2>
    <p class="hint">Updating replaces Sofa's own program files with the newest version from GitHub. <b>Your shows, movies, music, accounts, watch history and settings are not touched.</b> Sofa backs up its settings and keeps a copy of the old version first, so nothing is lost if something goes wrong.</p>
    ${state}${u.error && !u.running ? "" : ""}
    <dl class="kv"><dt>Running</dt><dd>Sofa ${esc(u.current || d.server.version)}${u.commit ? " (" + esc(u.commit.slice(0, 7)) + ")" : ""}</dd>
      <dt>Newest on GitHub</dt><dd>${u.latest ? "Sofa " + esc(u.latest) : "unknown"}${u.latest_commit ? " (" + esc(u.latest_commit.slice(0, 7)) + ")" : ""}</dd>
      <dt>Updates with</dt><dd>${u.method === "git" ? "git (this folder is a git clone)" : "a download from GitHub"}</dd></dl>
    <div class="actions" style="margin-top:16px">${u.available && !u.running ? `<button class="btn primary" data-update="install">Update now</button>` : ""}
      <button class="btn" data-update="check"${u.running ? " disabled" : ""}>Check again</button></div></div>
    <div class="panel wide"><h2>Updating by hand</h2><p class="hint">If the button ever fails, or on a copy of Sofa older than this page, open Terminal on this computer and paste:</p>
      <code class="cmd">${cmd}</code><p class="hint" style="margin-top:10px">It finds your Sofa folder, stops Sofa, saves a backup, updates, and starts it again. Details in the README.</p></div></div>`;
}
async function waitForRestart() {
  for (let i = 0; i < 40; i++) {
    await new Promise(r => setTimeout(r, 3000));
    try { const r = await fetch("/healthz", { cache: "no-store" }); if (r.ok) { const h = await r.json(); if (h.uptime < 60) { location.reload(); return; } } } catch (e) {}
  }
}
function srvActivity(d) {
  const kinds = ["all"].concat([...new Set(d.activity.map(a => a.kind))].sort());
  const names = { all: "Everything", inbox: "Inbox", review: "Needs review", scan: "Scans", login: "Sign-ins", account: "Accounts", settings: "Settings",
    live: "Live TV", convert: "Converting", playback: "Playback problems", update: "Updates", error: "Errors", backup: "Backups",
    download: "Downloads" };
  const list = d.activity.filter(a => activityKind === "all" || a.kind === activityKind);
  const report = `<div class="panel wide report-panel"><h2>Need help? Download a report</h2>
    <p class="hint">One text file with everything needed to see what Sofa is doing: version and tools, settings (no passwords, PINs or keys), folders and free space, what's in the Inbox and Needs Review, the queues, playback problems, this activity log with its details, and the server log. Send it to whoever helps you (you can give it straight to Claude).</p>
    <div class="actions"><a class="btn primary" id="reportLink" href="/api/admin/report" download>Download a report</a>
      ${session.user.adult ? `<label class="check"><input type="checkbox" id="reportAdult"> Include Adult details (file names, links)</label>` : ""}</div></div>`;
  const pv = d.privacy || {};
  if (pv.no_logs) return `<div class="panel wide"><h2>Activity</h2>
    <p class="hint">No logs are kept (Server, Settings, Privacy): nothing that happens here is written down.
    ${pv.problems_unlogged ? `${plural(pv.problems_unlogged, "problem")} since Sofa started; what ${pv.problems_unlogged > 1 ? "they were isn't" : "it was isn't"} kept. To find out, switch logs on for a while.` : "No problems since Sofa started."}</p></div>` +
    (d.activity.length ? `<div class="panel wide"><h2>Older activity</h2><p class="hint">From before logs were switched off. Wipe all logs (Settings) erases it.</p>
      <ul class="list">${d.activity.slice(0, 50).map(actRow).join("")}</ul></div>` : "");
  return report + `<div class="panel wide"><h2>Activity</h2><div class="chips">${kinds.map(k => `<button data-act-kind="${k}" aria-pressed="${k === activityKind}">${esc(names[k] || k)}</button>`).join("")}</div>
    <ul class="list">${list.map(actRow).join("") || `<li class="empty-row">Nothing yet.</li>`}</ul></div>`;
}
function drawGuestQr() {
  const box = $("#guestQr");
  if (!box || !box.dataset.url) return;
  const draw = () => { const q = window.qrcode(0, "M"); q.addData(box.dataset.url); q.make(); box.innerHTML = q.createSvgTag({ cellSize: 6, margin: 2, scalable: true }); };
  if (window.qrcode) return draw();
  const sc = document.createElement("script"); sc.src = "/client/vendor/qrcode.js"; sc.onload = draw; document.head.appendChild(sc);
}
async function adminAction(fn) {
  try { await fn(); } catch (e) { alertBox(e.message); }
  loadAdmin();
}
function alertBox(msg) { dialog(`<h2>That didn't work</h2><p>${esc(msg)}</p>`); }

/* ---------- router ---------- */
let enterTimer = 0;
function route(animate) {
  gridRest.clear();
  const trailer = location.hash === trailerHash ? $("video.trailer") : null;     // the same page drawn again: it keeps playing
  if (trailer) clearTimeout(trailerTimer); else stopTrailer();
  if (!session || !session.user) return;
  if (location.hash.startsWith("#/add?")) {                 // the "Send to Sofa" bookmark
    const q = new URLSearchParams(location.hash.slice(6));
    history.replaceState(null, "", "#/");
    route();
    if (session.user.admin) addLinkDialog(q.get("adult") === "1" && session.user.adult, q.get("url") || "");
    else toast("Only admins can save videos from links.");
    return;
  }
  const hash = decodeURIComponent(location.hash.replace(/^#\/?/, ""));
  const [name, ...rest] = hash.split("/");
  let html, nav = "";
  if ((name === "shows" || name === "movies") && name !== filterPage) { pageFilter = ""; seenFilter = "all"; filterPage = name; }
  if (name === "show") { const arg = rest.join("/"); const cut = arg.lastIndexOf("|"); const sid = cut > 0 ? arg.slice(0, cut) : arg;
    html = viewShow(sid, cut > 0 ? arg.slice(cut + 1) : null); nav = (byId.get(sid) || {}).adult ? "adult" : "shows"; }
  else if (name === "shows") { html = viewShows(rest.join("/") || null); nav = "shows"; }
  else if (name === "movies") { html = viewMovies(null, null, null, rest.join("/") || null); nav = "movies"; }
  else if (name === "movie") { const m = byId.get(rest.join("/")); html = viewMovie(rest.join("/")); nav = m && m.adult ? "adult" : "movies"; }
  else if (name === "collection") { html = viewCollection(rest.join("/")); nav = "movies"; }
  else if (name === "adult" && session.user.adult) { html = viewAdult(rest); nav = "adult"; }
  else if (name === "search") { html = viewSearch(rest.join("/")); nav = "search"; }
  else if (name === "mylist") { html = viewMyList(); nav = "mylist"; }
  else if (name === "pair" && !session.user.guest) html = viewPair(rest.join("").replace(/\D/g, ""));
  else if (name === "live" && !session.user.kids) { html = viewLive(); nav = "live"; }
  else if (name === "music") { html = viewMusic(rest); nav = "music"; }
  else if (name === "server" && session.user.admin) { html = viewServer(rest[0]); nav = "server"; }
  else if (name === "more") { html = viewMore(); nav = "more"; }
  else if (name === "box" && window.SofaBox) { html = viewBox(); nav = "box"; }
  else { html = viewHome(); nav = "home"; }
  $("#searchBtn").toggleAttribute("aria-current", nav === "search");
  document.querySelectorAll("[data-nav]").forEach(a => { if (a.dataset.nav === nav) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); });
  view.innerHTML = html;
  if (animate !== false) revealRails(view); else view.querySelectorAll(".row").forEach(r => r.classList.add("rail-in"));
  if (animate !== false && motion() !== "off") {
    view.classList.remove("enter"); void view.offsetWidth; view.classList.add("enter");
    clearTimeout(enterTimer); enterTimer = setTimeout(() => view.classList.remove("enter"), 1100);
  }
  watchGrids();
  updateNudges();
  startHero();
  if (trailer) keepTrailer(trailer); else if (animate !== false) startTrailer();
  if (nav === "server") drawGuestQr();
  if (nav === "search" && animate !== false && !rest.join("/")) { const b = $("#pageSearch"); if (b) b.focus(); }
}
function rerender() { const y = scrollY; route(false); scrollTo(0, y); }
window.addEventListener("hashchange", () => { route(); scrollTo(0, 0); });

/* ---------- interactions ---------- */
document.addEventListener("click", e => {
  const t = e.target.closest("[data-slide],[data-intros-recheck],[data-manage],[data-machine-test],[data-drive-use],[data-place-remove],[data-new-pictures],[data-empty-deleted],[data-free-space],[data-retry-details],[data-adult-nav],[data-asort],[data-adult-play],[data-like],[data-download],[data-surprise],[data-pair-profile],[data-session-end],[data-forget],[data-seen],[data-wipe-logs],[data-trailer-sound],[data-trailer-replay],[data-redo-damaged],[data-add-link],[data-send-files],[data-dl-retry],[data-dl-cancel],[data-dl-clear],[data-dl-install],[data-enable-adult],[data-conv-retry],[data-conv-cancel],[data-conv-all],[data-conv-clear],[data-update],[data-user-adult],[data-user-kids],[data-dupes],[data-kids-title],[data-act-kind],[data-key-clear],[data-fix],[data-msort],[data-adult-tab],[data-play-start],[data-srv-tab],[data-mlike],[data-mplay],[data-mplay-one],[data-mplay-list],[data-mshuffle-list],[data-station],[data-mtab],[data-play-mv],[data-guest-clear],[data-play],[data-watched],[data-season],[data-sort],[data-nudge],[data-season-watched],[data-dismiss],[data-admin],[data-setting],[data-user-pass],[data-user-del],[data-live],[data-fav],[data-group],[data-preset],[data-live-remove]");
  if (!t) return;
  if (t.dataset.fix) { fixDialog(t.dataset.fix); return; }
  if (t.dataset.manage) { manageDialog(t.dataset.manage); return; }
  if (t.dataset.newPictures) { if (confirm("Take new pictures from the videos for the whole library? Only pictures Sofa took itself are replaced; covers stay. It runs in the background.")) adminAction(async () => { await api("/api/admin/pictures", {}); toast("Taking new pictures in the background. They appear as they're ready."); }); return; }
  if (t.dataset.driveUse !== undefined) { useDriveDialog(t.dataset.driveUse, t.dataset.driveName, t.dataset.driveExisting); return; }
  if (t.dataset.placeRemove) { if (confirm("Stop using this drive for the library? Nothing on it is deleted; its shows and movies just leave the library.")) adminAction(() => api("/api/admin/storage", { remove: t.dataset.placeRemove })); return; }
  if (t.dataset.machineTest) { adminAction(async () => { await api("/api/admin/machine", {}); toast("Testing… it takes about half a minute; this page shows the result."); }); return; }
  if (t.dataset.freeSpace) { if (confirm("Delete Sofa's own resized pictures, scrubbing previews and hover clips? Your media isn't touched; they're made again as needed.")) adminAction(async () => { await api("/api/admin/cache", { free: true }); toast("Space freed."); }); return; }
  if (t.dataset.retryDetails) { adminAction(async () => { const r = await api("/api/admin/cache", { retry_details: true }); toast("Looking again for " + plural(r.forgotten, "title") + " Sofa found nothing about."); }); return; }
  if (t.dataset.emptyDeleted) { if (confirm("Empty the Deleted folder? The videos in it are gone for good after this.")) adminAction(async () => { await api("/api/admin/deleted", { empty: true }); toast("The Deleted folder is empty."); }); return; }
  if (t.dataset.slide) { showSlide(+t.dataset.slide); startHero(); return; }
  if (t.dataset.introsRecheck) { if (confirm("Listen to every season again? Intros you marked by hand are kept.")) adminAction(() => api("/api/admin/intros", {})); return; }
  if (t.dataset.dlRetry) { adminAction(() => api("/api/admin/downloads", { retry: t.dataset.dlRetry })); return; }
  if (t.dataset.dlCancel) { adminAction(() => api("/api/admin/downloads", { cancel: t.dataset.dlCancel })); return; }
  if (t.dataset.dlClear) { adminAction(() => api("/api/admin/downloads", { clear: true })); return; }
  if (t.dataset.dlInstall) { t.disabled = true; t.textContent = "Installing…"; adminAction(() => api("/api/admin/downloads", { install_ytdlp: true })); return; }
  if (t.dataset.enableAdult) { adminAction(async () => { await api("/api/admin/users/" + session.user.id + "/adult", { on: true }); await boot(); location.hash = "#/adult"; }); return; }
  if (t.dataset.convRetry) { adminAction(() => api("/api/admin/convert", { retry: t.dataset.convRetry })); return; }
  if (t.dataset.convCancel) { adminAction(() => api("/api/admin/convert", { cancel: t.dataset.convCancel })); return; }
  if (t.dataset.convAll) { t.disabled = true; t.textContent = "Queueing…"; adminAction(async () => { const r = await api("/api/admin/convert", { all: true }); toast(plural(r.queued, "file") + " queued for converting."); }); return; }
  if (t.dataset.convClear) { adminAction(() => api("/api/admin/convert", { clear: true })); return; }
  if (t.dataset.update === "check") { t.disabled = true; t.textContent = "Checking…"; adminAction(() => api("/api/admin/update", { check: true })); return; }
  if (t.dataset.update === "install") {
    if (!confirm("Update Sofa now? Anyone watching will be interrupted for about a minute while it restarts. Your media and settings are not touched.")) return;
    t.disabled = true; t.textContent = "Starting…"; adminAction(() => api("/api/admin/update", { install: true })); return;
  }
  if (t.dataset.dupes) {
    const all = t.dataset.dupes === "*";
    if (all && !confirm("Keep the best copy of each and put the others in Deleted?")) return;
    t.disabled = true;
    api("/api/admin/duplicates", all ? { all: true } : { keys: [t.dataset.dupes] })
      .then(r => { toast(r.copies ? r.copies + (r.copies === 1 ? " spare copy" : " spare copies") + " in Deleted (" + bytes(r.freed) + "). Empty Deleted when you're sure." : "Nothing to do."); loadAdmin(); })
      .catch(e => { t.disabled = false; toast(e.message); });
    return;
  }
  if (t.dataset.userKids) { const on = t.getAttribute("aria-checked") !== "true"; adminAction(() => api("/api/admin/users/" + t.dataset.userKids + "/kids", { on }).then(() => { session.kids_profiles = session.kids_profiles || on; })); return; }
  if (t.dataset.kidsTitle) {
    const id = t.dataset.kidsTitle, on = t.getAttribute("aria-pressed") !== "true";
    api("/api/admin/kids", { id, allow: on }).then(async () => { await reloadLibrary(); rerender(); toast(on ? "Kids profiles can watch this now." : "Kids profiles won't see this."); }).catch(e => toast(e.message));
    return;
  }
  if (t.dataset.userAdult) { const on = t.getAttribute("aria-checked") !== "true"; adminAction(async () => { await api("/api/admin/users/" + t.dataset.userAdult + "/adult", { on }); if (+t.dataset.userAdult === session.user.id) boot(); }); return; }
  if (t.dataset.actKind) { activityKind = t.dataset.actKind; rerender(); return; }
  if (t.dataset.keyClear) { if (confirm("Remove this key?")) adminAction(() => api("/api/admin/settings", { [t.dataset.keyClear]: "" })); return; }
  if (t.dataset.msort) { prefs.set("msort", t.dataset.msort); rerender(); return; }
  if (t.dataset.adultTab) { location.hash = "#/adult/" + t.dataset.adultTab; return; }
  if (t.dataset.adultNav) { location.hash = "#/adult/" + t.dataset.adultNav.split("/").map(encodeURIComponent).join("/"); return; }
  if (t.dataset.asort) { prefs.set("asort", t.dataset.asort); rerender(); return; }
  if (t.dataset.adultPlay) {
    const list = t.dataset.adultPlay === "shuffle" ? adultList.slice().sort(() => Math.random() - 0.5) : adultList.slice();
    if (list.length) Player.open(list[0], list); return;
  }
  if (t.dataset.like) { toggleFav(t.dataset.like, t); return; }
  if (t.dataset.trailerSound) {
    const v = $("video.trailer"); if (!v) return;
    v.muted = !v.muted; prefs.set("trailerSound", !v.muted); trailerSoundBtn(v); return;
  }
  if (t.dataset.trailerReplay) { t.hidden = true; startTrailer(true); return; }
  if (t.dataset.wipeLogs) {
    if (!confirm("Erase every log Sofa has kept, here and in the backups? This can't be undone.")) return;
    t.disabled = true;
    api("/api/admin/privacy", { wipe: true }).then(r => { toast("All logs are erased" + (r.backups ? ", in " + plural(r.backups, "backup") + " too." : ".")); loadAdmin(); })
      .catch(e => { t.disabled = false; toast(e.message); });
    return;
  }
  if (t.dataset.sendFiles) { sendFilesDialog(t.dataset.sendFiles === "adult"); return; }
  if (t.dataset.redoDamaged) {
    t.disabled = true;
    api("/api/admin/convert", { redo_damaged: true }).then(() => toast("Looking for them. They show under Converting in a moment.")).catch(e => toast(e.message));
    return;
  }
  if (t.dataset.seen) { seenFilter = SEEN[t.dataset.seen] ? t.dataset.seen : "all"; rerender(); const b = $(`[data-seen="${t.dataset.seen}"]`); if (b) b.focus(); return; }
  if (t.dataset.pairProfile) {
    api("/api/pair/approve", { code: t.dataset.pairCode, profile: +t.dataset.pairProfile })
      .then(() => { $("#pairBody").innerHTML = `<p><b>Done.</b> The TV signs in by itself in a moment.</p><p><a class="btn" href="#/">Back to Home</a></p>`; })
      .catch(e => toast(e.message));
    return;
  }
  if (t.dataset.sessionEnd) {
    if (!confirm("Sign this device out?")) return;
    adminAction(() => api("/api/admin/sessions", { id: t.dataset.sessionEnd }));
    return;
  }
  if (t.dataset.surprise) {                 // something you haven't watched, from what's on this page
    const hash = decodeURIComponent(location.hash.replace(/^#\/?/, "")).split("/"), genre = hash.slice(1).join("/");
    const all = t.dataset.surprise === "shows" ? shows : movies, gm = genreMap(all);
    const pool = applyFilters(genre && gm.has(genre) ? gm.get(genre) : all);
    const fresh = pool.filter(x => seenState(x) === "new"), pick = (fresh.length ? fresh : pool)[Math.floor(Math.random() * (fresh.length || pool.length))];
    if (!pick) { toast("Nothing here to pick from."); return; }
    location.hash = (pick.seasons ? "#/show/" : "#/movie/") + encodeURIComponent(pick.id);
    return;
  }
  if (t.dataset.download) { downloadDialog(t.dataset.download); return; }
  if (t.dataset.forget) {
    const x = byId.get(t.dataset.forget); if (!x) return;
    forget(x); closePop(); rerender();
    toast("Removed from Continue watching. It comes back when you watch it again."); return;
  }
  if (t.dataset.addLink) { addLinkDialog(t.dataset.addLink === "adult"); return; }
  if ((t.dataset.play || t.dataset.playStart) && Screens.target()) { e.preventDefault(); closePop(); Screens.play(t.dataset.play || t.dataset.playStart, !!t.dataset.playStart); return; }
  if (t.dataset.playStart) { setProgress(t.dataset.playStart, null, true); Player.open(byId.get(t.dataset.playStart)); return; }
  if (t.dataset.srvTab) { location.hash = "#/server/" + t.dataset.srvTab; return; }
  if (t.dataset.mlike) { e.stopPropagation(); setLike(t.dataset.mlike, !likes.has(t.dataset.mlike)); return; }
  if (t.dataset.mplay) { const ids = t.closest("[data-list]").dataset.list.split(","); MusicPlayer.play(ids, +t.dataset.idx); return; }
  if (t.dataset.mplayOne) { MusicPlayer.play([t.dataset.mplayOne], 0); return; }
  if (t.dataset.mplayList) { MusicPlayer.play(listFor(t.dataset.mplayList), 0, (mById.get(t.dataset.mplayList) || {}).title || (mById.get(t.dataset.mplayList) || {}).name || ""); return; }
  if (t.dataset.mshuffleList) { const ids = listFor(t.dataset.mshuffleList).sort(() => Math.random() - 0.5); MusicPlayer.play(ids, 0, "Shuffle"); return; }
  if (t.dataset.station) { startStation(t.dataset.station); return; }
  if (t.dataset.mtab) { location.hash = "#/music/" + t.dataset.mtab; return; }
  if (t.dataset.playMv) { Player.open(mById.get(t.dataset.playMv)); return; }
  if (t.dataset.guestClear) { if (confirm("Clear everything guests have watched and liked, and sign current guests out?")) adminAction(() => api("/api/admin/guest/clear", {})); return; }
  if (t.dataset.live) { const list = liveList(); Player.openLive(list.find(c => c.id === t.dataset.live), list); return; }
  if (t.dataset.fav) {
    const c = liveData.channels.find(x => x.id === t.dataset.fav); c.fav = !c.fav;
    api("/api/live/favorite/" + c.id, { on: c.fav }).catch(() => {});
    if (!(liveGroup === "Favorites" && !c.fav)) { t.setAttribute("aria-pressed", c.fav); return; }
    rerender(); return;
  }
  if (t.dataset.group) { liveGroup = t.dataset.group; liveQuery = ""; prefs.set("liveGroup", liveGroup); rerender(); return; }
  if (t.dataset.preset) {
    t.disabled = true; t.textContent = "Adding " + t.dataset.name + "…";
    api("/api/admin/live", { add: { name: t.dataset.name, url: t.dataset.preset } })
      .then(() => { liveData = null; liveGroup = "All"; if (location.hash.startsWith("#/server")) loadAdmin(); else loadLive(); })
      .catch(ex => alertBox(ex.message));
    return;
  }
  if (t.dataset.liveRemove) { adminAction(async () => { await api("/api/admin/live", { remove: t.dataset.liveRemove }); liveData = null; }); return; }
  if (t.dataset.play) { e.preventDefault(); Player.open(byId.get(t.dataset.play)); }
  else if (t.dataset.watched) { setWatched(t.dataset.watched, !isDone(t.dataset.watched)); rerender(); }
  else if (t.dataset.season) {
    const id = decodeURIComponent(location.hash.replace(/^#\/?show\//, "")).split("|")[0];
    history.replaceState(null, "", "#/show/" + encodeURIComponent(id + "|" + t.dataset.season));
    rerender();
  }
  else if (t.dataset.sort) { prefs.set("sort", t.dataset.sort); rerender(); }
  else if (t.dataset.nudge) { const r = t.parentElement.querySelector(".rail"); r.scrollBy({ left: r.clientWidth * 0.85 * t.dataset.nudge, behavior: "smooth" }); }
  else if (t.dataset.seasonWatched) {
    const ids = [...$(".episodes").querySelectorAll("[data-watched]")].map(b => b.dataset.watched);
    const all = ids.every(isDone);
    ids.forEach(id => setWatched(id, !all));
    rerender();
  }
  else if (t.dataset.dismiss) { history.back(); }
  else if (t.dataset.admin === "backup") { t.disabled = true; t.textContent = "Backing up…"; adminAction(() => api("/api/admin/backup", {})); }
  else if (t.dataset.admin === "inbox") { t.disabled = true; t.textContent = "Sorting…"; adminAction(async () => { const r = await api("/api/admin/inbox", {}); toast(r.filed ? plural(r.filed, "file") + " filed." : "Nothing ready to file yet (Sofa waits until copies finish)."); await reloadLibrary(); }); }
  else if (t.dataset.admin === "scan") { t.disabled = true; t.textContent = "Checking…"; adminAction(async () => { await api("/api/admin/scan", {}); await reloadLibrary(); }); }
  else if (t.dataset.setting) {
    const on = t.getAttribute("aria-checked") !== "true";
    adminAction(() => api("/api/admin/settings", { [t.dataset.setting]: on }));
  }
  else if (t.dataset.userPass) {
    const pw = prompt("New password for " + t.dataset.userName + " (8 or more characters):");
    if (pw) adminAction(() => api("/api/admin/users/" + t.dataset.userPass + "/password", { password: pw }));
  }
  else if (t.dataset.userDel) {
    if (confirm("Remove " + t.dataset.userName + "? Their watch history goes too.")) adminAction(() => api("/api/admin/users/" + t.dataset.userDel + "/delete", {}));
  }
});
document.addEventListener("change", e => {
  if (e.target.dataset.newTo !== undefined) { adminAction(async () => { await api("/api/admin/storage", { new_to: e.target.dataset.newTo }); toast("New things go there now."); }); return; }
  if (e.target.id === "reportAdult") { $("#reportLink").href = "/api/admin/report" + (e.target.checked ? "?adult=1" : ""); return; }
  const sel = e.target.closest("[data-setting-select]"); if (!sel) return;
  const v = sel.dataset.settingSelect === "max_transcodes" ? +sel.value : sel.dataset.settingSelect === "gentle" ? (sel.value === "auto" ? "auto" : sel.value === "on") : sel.value;
  adminAction(async () => { await api("/api/admin/settings", { [sel.dataset.settingSelect]: v }); if (sel.dataset.settingSelect === "theme") { session.theme = v; applyLook(); } });
});
document.addEventListener("submit", e => {
  if (e.target.dataset.quietForm) {
    e.preventDefault();
    adminAction(async () => { await api("/api/admin/settings", { quiet_hours: e.target.v.value.trim() }); toast("Saved."); });
    return;
  }
  if (e.target.dataset.keyForm || e.target.dataset.nameForm) {
    e.preventDefault();
    const key = e.target.dataset.keyForm || "name", v = e.target.v.value.trim();
    if (!v) return;
    adminAction(async () => { await api("/api/admin/settings", { [key]: v }); toast(key === "name" ? "Saved." : "Saved. Sofa is looking things up again."); if (key === "name") boot(); });
    return;
  }
  if (e.target.id === "addList") {
    e.preventDefault();
    const f = e.target, err = $(".form-error", f);
    err.textContent = "Downloading the list…";
    api("/api/admin/live", { add: { name: f.name.value, url: f.url.value, adult: f.adult.checked } })
      .then(r => { f.reset(); liveData = null; loadAdmin(); })
      .catch(ex => { err.textContent = ex.message; });
    return;
  }
  if (e.target.id !== "addUser") return;
  e.preventDefault();
  const f = e.target, err = $(".form-error", f);
  api("/api/admin/users", { name: f.name.value, password: f.password.value, admin: f.admin.checked, adult: f.adult.checked })
    .then(() => { f.reset(); loadAdmin(); })
    .catch(ex => { err.textContent = ex.message; });
});
document.addEventListener("scroll", e => { if (e.target.classList && e.target.classList.contains("rail")) updateNudges(); }, true);
function updateNudges() {
  document.querySelectorAll(".rail").forEach(r => {
    const w = r.parentElement;
    $(".prev", w).disabled = r.scrollLeft < 8;
    $(".next", w).disabled = r.scrollLeft + r.clientWidth > r.scrollWidth - 8;
  });
}
window.addEventListener("resize", updateNudges);
window.addEventListener("scroll", () => { $("#bar").classList.toggle("scrolled", scrollY > 24); }, { passive: true });
document.addEventListener("error", e => {
  const img = e.target;
  if (img.tagName !== "IMG") return;
  const f = img.closest(".frame"); if (f) f.classList.add("noimg");
  img.remove();
}, true);

/* Search as you type: a panel under the box with the best matches and their pictures.
   Enter (or "See all results") opens the full results page. Arrow keys and the remote move through it. */
let searchTimer;
const suggest = document.createElement("div");
suggest.className = "suggest"; suggest.hidden = true; suggest.setAttribute("role", "listbox"); suggest.setAttribute("aria-label", "Suggestions");
document.body.appendChild(suggest);
function closeSuggest() { suggest.hidden = true; suggest.classList.remove("on"); }
function openSuggest(q) {
  const { sh, mv, eps } = searchAll(q);
  const titles = sh.slice(0, 5).concat(mv.slice(0, 5)).sort((a, b) => sh.indexOf(a) + mv.indexOf(a) + 2 - (sh.indexOf(b) + mv.indexOf(b) + 2)).slice(0, 6);
  const row = (href, art, wide, name, sub) => `<a class="sg-item" role="option" href="${esc(href)}">
      <span class="sg-art${wide ? " wide" : ""}">${art ? `<img src="${esc(artSrc(art, 240))}" alt="" loading="lazy">` : `<span class="placeholder" style="--h:${hue(name)}"></span>`}</span>
      <span class="sg-text"><b>${esc(name)}</b><small>${esc(sub)}</small></span></a>`;
  const items = titles.map(x => x.seasons
      ? row("#/show/" + encodeURIComponent(x.id), x.poster, false, x.name, ["Show", years(x), plural(x.regularSeasons, "season")].filter(Boolean).join(" · "))
      : row("#/movie/" + encodeURIComponent(x.id), x.poster, false, x.title, ["Movie", x.year, (x.genres || [])[0]].filter(Boolean).join(" · ")))
    .concat(eps.slice(0, 4).map(ep => row("#/show/" + encodeURIComponent(ep.show.id) + "|" + (ep.kind === "extra" ? "extras" : ep.s),
      ep.thumb || ep.show.backdrop || ep.show.poster, true, title(ep), ep.show.name + " · " + epCode(ep))));
  suggest.innerHTML = (items.length ? items.join("") : `<p class="sg-none">Nothing matches "${esc(q.trim())}" yet.</p>`) +
    `<a class="sg-all" href="#/search/${encodeURIComponent(q.trim())}">See all results for "${esc(q.trim())}"</a>`;
  const r = $("#searchBox").getBoundingClientRect();
  const w = Math.min(440, innerWidth - 24);
  suggest.style.cssText = `top:${r.bottom + 8}px;left:${Math.max(12, Math.min(innerWidth - w - 12, r.right - w))}px;width:${w}px`;
  suggest.hidden = false;
  requestAnimationFrame(() => suggest.classList.add("on"));
}
$("#q").addEventListener("input", e => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { const v = e.target.value; if (v.trim()) openSuggest(v); else closeSuggest(); }, 120);
});
$("#q").addEventListener("focus", e => { if (e.target.value.trim()) openSuggest(e.target.value); });
$("#q").addEventListener("keydown", e => {
  if (e.key === "Enter" && e.target.value.trim()) { e.preventDefault(); closeSuggest(); location.hash = "#/search/" + encodeURIComponent(e.target.value.trim()); }
  else if (e.key === "Escape") { closeSuggest(); }
  else if (e.key === "ArrowDown" && !suggest.hidden) { e.preventDefault(); e.stopPropagation(); const f = $("a", suggest); if (f) f.focus(); }
});
suggest.addEventListener("keydown", e => {
  const items = [...suggest.querySelectorAll("a")], i = items.indexOf(document.activeElement);
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault(); e.stopPropagation();
    const next = i + (e.key === "ArrowDown" ? 1 : -1);
    if (next < 0) $("#q").focus(); else if (items[next]) items[next].focus();
  } else if (e.key === "Escape" || e.key === "Backspace") { e.preventDefault(); e.stopPropagation(); closeSuggest(); $("#q").focus(); }
});
suggest.addEventListener("click", e => { if (e.target.closest("a")) setTimeout(closeSuggest, 0); });
document.addEventListener("pointerdown", e => { if (!suggest.hidden && !suggest.contains(e.target) && !$("#searchBox").contains(e.target)) closeSuggest(); });
window.addEventListener("hashchange", closeSuggest);
$("#lookBtn").addEventListener("click", () => appearanceDialog());
if (window.SofaBox) {                     // on the Sofa box, its own settings are in the menu
  const a = document.createElement("a"); a.href = "#/box"; a.dataset.nav = "box"; a.className = "nav-extra";
  a.innerHTML = "<span>Box</span>"; $("#nav .nav-more").before(a);
}
async function signOut() { await api("/api/logout", {}).catch(() => {}); location.hash = "#/"; boot(); }
$("#signOut").addEventListener("click", signOut);

function dialog(html) {
  openDialog(`${html}<div class="actions"><button class="btn primary" data-dismiss="1">OK</button></div>`);
}
/* A dialog layer: Back, Escape, the scrim and any [data-dismiss] close it. Returns the dialog box. */
function openDialog(html, wide) {
  history.pushState({ sofaLayer: "dialog" }, "");
  const d = document.createElement("div");
  d.className = "dialog-scrim";
  d.innerHTML = `<div class="dialog${wide ? " wide" : ""}" role="dialog" aria-modal="true">${html}</div>`;
  d.addEventListener("click", e => { if (e.target === d) history.back(); });
  document.body.appendChild(d);
  const f = $("input, [data-dismiss], button", d); if (f) f.focus();
  return $(".dialog", d);
}
function closeDialog() { if (document.querySelector(".dialog-scrim")) history.back(); }
let toastTimer = 0;
window.SofaToast = msg => toast(msg);           // for the Sofa box agent
function toast(msg) {
  let t = $("#toast");
  if (!t) { t = document.createElement("div"); t.id = "toast"; t.className = "toast"; t.setAttribute("role", "status"); document.body.appendChild(t); }
  t.textContent = msg; t.classList.add("on");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove("on"), 4200);
}

/* ---------- fixing a show's or movie's details (admins) ---------- */
function fixDialog(id) {
  const entry = byId.get(id); if (!entry) return;
  const isShow = !!entry.seasons;
  const d = openDialog(`<h2>${entry.source ? "Fix the details" : "Find the details"}</h2>
    <p>${isShow ? "Search for the show" : "Search for the movie"} and pick the right one. Sofa downloads its artwork and description, and remembers your choice.</p>
    <form class="fix-form"><input name="q" value="${esc(entry.name || entry.title)}" aria-label="Title" autocomplete="off">
      ${isShow ? "" : `<input name="year" value="${esc(entry.year || "")}" placeholder="Year" aria-label="Year" inputmode="numeric" maxlength="4">`}
      <button class="btn primary" type="submit">Search</button></form>
    <div class="fix-results" aria-live="polite"><p class="count">Searching…</p></div>
    <div class="actions"><button class="btn" data-fix-title="1">Just use the title I typed</button>
      <button class="btn ghost" data-fix-none="1">Show no details</button><button class="btn ghost" data-dismiss="1">Cancel</button></div>`, true);
  const form = $(".fix-form", d), box = $(".fix-results", d);
  async function search() {
    box.innerHTML = `<p class="count">Searching…</p>`;
    try {
      const r = await api("/api/admin/match?id=" + encodeURIComponent(id) + "&q=" + encodeURIComponent(form.q.value) + (form.year ? "&year=" + encodeURIComponent(form.year.value) : ""));
      const tip = !isShow && !r.keys.tmdb ? `<p class="hint">Tip: add a free TMDB key on the Server page (Settings) for the best movie artwork.</p>` : "";
      box.innerHTML = r.results.length ? `<ul class="picks">${r.results.map(x => `<li><button data-pick-src="${esc(x.source)}" data-pick-id="${esc(x.id)}">
        <span class="pk-art">${x.poster ? `<img src="${esc(x.poster)}" alt="" referrerpolicy="no-referrer" loading="lazy">` : ""}</span>
        <span class="pk-text"><b>${esc(x.title)}</b><span>${esc([x.year, x.detail].filter(Boolean).join(" · "))}</span></span></button></li>`).join("")}</ul>${tip}`
        : `<p class="count">Nothing found for "${esc(form.q.value)}". Try fewer words, or another spelling.</p>${tip}`;
    } catch (e) { box.innerHTML = `<p class="form-error">${esc(e.message)}</p>`; }
  }
  async function send(body) {
    try {
      await api("/api/admin/match", Object.assign({ id }, body));
      closeDialog(); toast("Saved. New details and artwork appear in a few seconds.");
      setTimeout(reloadLibrary, 3500); setTimeout(reloadLibrary, 9000);
    } catch (e) { box.innerHTML = `<p class="form-error">${esc(e.message)}</p>`; }
  }
  form.addEventListener("submit", e => { e.preventDefault(); search(); });
  d.addEventListener("click", e => {
    const t = e.target.closest("[data-pick-src],[data-fix-title],[data-fix-none]"); if (!t) return;
    if (t.dataset.pickSrc) send({ pick: { source: t.dataset.pickSrc, id: t.dataset.pickId } });
    else if (t.dataset.fixTitle) send({ title: form.q.value, year: form.year ? form.year.value : "" });
    else send({ none: true });
  });
  search();
}

/* ---------- "Who's watching?": profiles ---------- */
const avatar = (p, id) => `<span class="av av-${(p.avatar || 0) % 8}"${id ? ` id="${id}"` : ""} aria-hidden="true">${esc((p.name || "?").trim().charAt(0).toUpperCase())}</span>`;
$("#whoBtn").addEventListener("click", () => session.profiles ? profilePicker(false) : accountDialog());
$("#castBtn").addEventListener("click", () => Screens.choose());
/* On a TV the header has room only for the avatar: Theme and Sign out are behind it. */
function accountDialog() {
  const d = openDialog(`<h2>${esc(session.user.name)}</h2>
    <div class="actions"><button class="btn" data-pick-theme="1">Theme</button><button class="btn" data-sign-out="1">${session.user.guest ? "Leave" : "Sign out"}</button>
      <button class="btn ghost" data-dismiss="1">Close</button></div>`);
  d.addEventListener("click", e => {
    if (e.target.closest("[data-pick-theme]")) { closeDialog(); setTimeout(appearanceDialog, 60); }
    else if (e.target.closest("[data-sign-out]")) { closeDialog(); signOut(); }
  });
  const f = $("[data-pick-theme]", d); if (f) f.focus();
}
async function profilePicker(auto) {
  let r;
  try { r = await api("/api/profiles"); } catch (e) { if (!auto) toast(e.message); return; }
  sessionStorage.setItem("sofaPicked", "1");
  const d = openDialog(`<div class="gate-inner"><h2>Who's watching?</h2>
    <div class="profiles">${r.profiles.map(p => `<button class="profile" data-profile="${p.id}">
      <span class="tile">${avatar(p)}${p.locked && p.id !== r.me ? `<i class="lock" aria-label="Locked">${icon("i-lock")}</i>` : ""}</span>
      <span class="pname">${esc(p.name)}</span>${p.kids ? `<span class="kids-tag">Kids</span>` : ""}${p.id === r.me ? `<span class="me">Watching now</span>` : ""}</button>`).join("")}</div>
    <div class="actions center"><button class="btn ghost" data-my-profile="1">Your profile: color and PIN</button>
      ${auto ? "" : `${TV ? "" : `<button class="btn ghost" data-go-pair="1">Pair a TV</button>`}<button class="btn ghost" data-pick-theme="1">Theme</button><button class="btn ghost" data-sign-out="1">${session.user.guest ? "Leave" : "Sign out"}</button><button class="btn ghost" data-dismiss="1">Close</button>`}</div></div>`);
  d.classList.add("gate"); d.parentElement.classList.add("gate-scrim");
  const first = $(`[data-profile="${r.me}"]`, d) || $("[data-profile]", d); if (first) first.focus();
  d.addEventListener("click", e => {
    if (e.target.closest("[data-my-profile]")) { closeDialog(); setTimeout(profileDialog, 60); return; }
    if (e.target.closest("[data-pick-theme]")) { closeDialog(); setTimeout(appearanceDialog, 60); return; }
    if (e.target.closest("[data-sign-out]")) { closeDialog(); signOut(); return; }
    if (e.target.closest("[data-go-pair]")) { closeDialog(); setTimeout(() => { location.hash = "#/pair"; }, 80); return; }
    const b = e.target.closest("[data-profile]"); if (!b) return;
    const p = r.profiles.find(x => x.id === +b.dataset.profile);
    if (p.id === r.me) { closeDialog(); return; }
    if (!p.locked) return switchTo(p, null, d);
    codePrompt(d, p);
  });
}
function codePrompt(d, p) {
  const pin = p.pin;
  $(".gate-inner", d).innerHTML = `<div class="code-head">${avatar(p)}<h2>${esc(p.name)}</h2>
      <p>${pin ? "Type the PIN for this profile." : session.user.kids ? "Leaving a Kids profile needs this profile's password (or set a PIN for it)." : "This profile can see Adult or run the server, so it needs its password."}</p></div>
    ${pin ? `<div class="pin-dots" aria-live="polite">${"<i></i>".repeat(4)}</div>
      <div class="pin-pad">${[1, 2, 3, 4, 5, 6, 7, 8, 9, "", 0, "⌫"].map(k => k === "" ? "<span></span>" : `<button data-key="${k}">${k}</button>`).join("")}</div>`
      : `<form class="code-form"><input type="password" name="code" autocomplete="current-password" aria-label="Password" placeholder="Password"><button class="btn primary">Continue</button></form>`}
    <div class="form-error" role="alert"></div>
    <div class="actions center"><button class="btn ghost" data-back-profiles="1">Back</button></div>`;
  let code = "";
  const dots = () => $(".pin-dots", d) && $(".pin-dots", d).querySelectorAll("i").forEach((i, n) => i.classList.toggle("on", n < code.length));
  const tryCode = async () => {
    const ok = await switchTo(p, code, d);
    if (!ok) { code = ""; dots(); const pd = $(".pin-dots", d); if (pd) { pd.classList.remove("shake"); void pd.offsetWidth; pd.classList.add("shake"); } }
  };
  const press = k => { if (k === "⌫") code = code.slice(0, -1); else if (code.length < 4) code += k; dots(); if (pin && code.length === 4) tryCode(); };
  d.onclick = e => {
    const k = e.target.closest("[data-key]"); if (k) return press(k.dataset.key);
    if (e.target.closest("[data-back-profiles]")) { closeDialog(); setTimeout(() => profilePicker(false), 60); }
  };
  d.onkeydown = e => { if (pin && /^\d$/.test(e.key)) { e.preventDefault(); press(e.key); } else if (pin && e.key === "Backspace") { e.preventDefault(); press("⌫"); } };
  const f = $(".code-form", d);
  if (f) { f.addEventListener("submit", e => { e.preventDefault(); code = f.code.value; tryCode(); }); f.code.focus(); }
  else $("[data-key]", d).focus();
}
async function switchTo(p, code, d) {
  try {
    await api("/api/profiles/switch", { id: p.id, code });
    closeDialog(); location.hash = "#/";
    await boot(); toast("Hi, " + p.name + ".");
    return true;
  } catch (e) { const err = $(".form-error", d); if (err) err.textContent = e.message; return false; }
}
function profileDialog() {
  const u = session.user;
  const d = openDialog(`<h2>Your profile</h2><p>How ${esc(u.name)} looks in "Who's watching?".</p>
    <div class="av-pick" role="group" aria-label="Color">${[0, 1, 2, 3, 4, 5, 6, 7].map(i => `<button data-av="${i}" aria-pressed="${u.avatar === i}" aria-label="Color ${i + 1}">${avatar({ name: u.name, avatar: i })}</button>`).join("")}</div>
    <h3 class="dlg-sub">PIN</h3>
    <p class="hint">${u.admin || u.adult ? "Your profile can see Adult or run the server, so switching to it asks for this PIN (or your password, without one)." : "With a PIN, switching to your profile asks for it."}</p>
    <form class="pin-form"><input name="pin" inputmode="numeric" maxlength="4" pattern="\\d{4}" placeholder="New PIN (4 digits)" aria-label="New PIN">
      <input name="password" type="password" autocomplete="current-password" placeholder="Your password" aria-label="Your password">
      <button class="btn primary">${u.pin ? "Change PIN" : "Set PIN"}</button>${u.pin ? `<button class="btn ghost" type="button" data-clear-pin="1">Remove PIN</button>` : ""}</form>
    <div class="form-error" role="alert"></div>
    <div class="actions"><button class="btn ghost" data-dismiss="1">Done</button></div>`);
  const err = $(".form-error", d), f = $(".pin-form", d);
  d.addEventListener("click", async e => {
    const a = e.target.closest("[data-av]");
    if (a) { try { await api("/api/profile", { avatar: +a.dataset.av }); u.avatar = +a.dataset.av; d.querySelectorAll("[data-av]").forEach(b => b.setAttribute("aria-pressed", b === a)); $("#whoAv").outerHTML = avatar(u, "whoAv"); } catch (ex) { err.textContent = ex.message; } }
    if (e.target.closest("[data-clear-pin]")) {
      try { await api("/api/profile", { pin: "", password: f.password.value }); u.pin = false; closeDialog(); toast("PIN removed."); } catch (ex) { err.textContent = ex.message; }
    }
  });
  f.addEventListener("submit", async e => {
    e.preventDefault();
    try { await api("/api/profile", { pin: f.pin.value, password: f.password.value }); u.pin = true; closeDialog(); toast("PIN saved."); } catch (ex) { err.textContent = ex.message; }
  });
}

/* ---------- managing a title (admins): new pictures, move it, delete it ---------- */
function manageDialog(id) {
  const x = byId.get(id); if (!x) return;
  const isShow = !!x.seasons, name = isShow ? x.name : x.kind === "episode" ? (x.show ? x.show.name + " · " : "") + epCode(x) + " " + title(x) : x.title;
  const owner = isShow ? x.id : x.kind === "episode" ? (x.show || {}).id : x.id;
  const d = openDialog(`<h2>Manage</h2><p class="fileline">${esc(name)}${x.file ? " · " + esc(x.file) : ""}</p>
    <div class="manage-list">
      <button data-m="pictures">${icon("i-image")}<span><b>Take new pictures from the video${isShow ? "s" : ""}</b><small>Replaces pictures Sofa took itself (like ones from the very start). Covers stay.</small></span></button>
      <button data-m="move">${icon("i-next-arrow")}<span><b>Move ${isShow ? "the whole show" : "it"} somewhere else</b><small>${isShow ? "To Shows or to an Adult category." : "It's in the wrong place, or it's actually a movie, an episode or adult."}</small></span></button>
      ${(isShow || x.kind === "movie") && (LIB.places || []).filter(p => p.connected).length > 1 ? `<button data-m="drive">${icon("i-sofa")}<span><b>Move it to another drive</b><small>Make room here, or keep a whole show on one drive.</small></span></button>` : ""}
      <button data-m="delete" class="danger">${icon("i-trash")}<span><b>Delete ${isShow ? "the whole show" : "it"}</b><small>It goes to the Deleted folder first, so you can still get it back.</small></span></button>
    </div><div class="form-error" role="alert"></div>
    <div class="actions"><button class="btn ghost" data-dismiss="1">Close</button></div>`);
  d.addEventListener("click", async e => {
    const b = e.target.closest("[data-m]"); if (!b) return;
    const err = $(".form-error", d);
    if (b.dataset.m === "pictures") {
      try { await api("/api/admin/pictures", { id: owner }); closeDialog(); toast("Taking new pictures. They show up in a minute or two."); [20000, 60000].forEach(t => setTimeout(reloadLibrary, t)); }
      catch (ex) { err.textContent = ex.message; }
    } else if (b.dataset.m === "move") { closeDialog(); setTimeout(() => moveDialog(id), 60); }
    else if (b.dataset.m === "drive") { closeDialog(); setTimeout(() => moveDriveDialog(id), 60); }
    else { closeDialog(); setTimeout(() => deleteDialog(id), 60); }
  });
}
async function relocate(id, target) {
  const x = byId.get(id), back = x && x.adult ? "#/adult" : x && (x.seasons || x.kind === "episode") ? "#/shows" : "#/movies";
  const r = await api("/api/admin/relocate", { id, target });
  closeDialog(); toast(r.message);
  await reloadLibrary();
  const here = location.hash.split("/")[2];
  if (here && !byId.has(decodeURIComponent(here))) location.hash = back; else rerender();
  [8000, 30000].forEach(t => setTimeout(async () => { await reloadLibrary(); if (!Player.isOpen()) rerender(); }, t));
}
function deleteDialog(id) {
  const x = byId.get(id); if (!x) return;
  const name = x.seasons ? x.name : x.kind === "episode" ? epCode(x) + " " + title(x) : x.title;
  const d = openDialog(`<h2>Delete ${x.seasons ? "this show" : "this video"}?</h2>
    <p><b>${esc(name)}</b> goes to the <b>Deleted</b> folder on the server${adminData && adminData.library && adminData.library.folders ? ` (<code>${esc(adminData.library.deleted_folder)}</code>)` : ""}. It's really gone only when you empty that folder (Server, Library).</p>
    <div class="form-error" role="alert"></div>
    <div class="actions"><button class="btn danger" data-really="1">Delete</button><button class="btn ghost" data-dismiss="1">Cancel</button></div>`);
  d.addEventListener("click", async e => {
    if (!e.target.closest("[data-really]")) return;
    try { await relocate(id, { kind: "delete" }); } catch (ex) { $(".form-error", d).textContent = ex.message; }
  });
}
function moveDialog(id) {
  const x = byId.get(id); if (!x) return;
  const isShow = !!x.seasons, ep = x.kind === "episode" ? x : null;
  const cats = (LIB.adult && LIB.adult.categories) || [];
  const kinds = isShow ? [["shows", "Shows"]].concat(session.user.adult ? [["adult", "Adult"]] : [])
    : [["movie", "A movie"], ["episode", "An episode"]].concat(session.user.adult ? [["adult", "Adult"]] : [], [["review", "Needs Review"]]);
  const first = isShow ? (x.adult ? "shows" : "adult") : x.adult ? "movie" : ep ? "episode" : "movie";
  const d = openDialog(`<h2>Move ${isShow ? "the show" : "it"}</h2>
    <p class="fileline">${esc(isShow ? x.name : x.file || x.title)}</p>
    <h3 class="dlg-sub">${isShow ? "Where does it belong?" : "What is it?"}</h3>
    <div class="sorter inline" role="group" aria-label="What it is">${kinds.map(k => `<button type="button" data-kind="${k[0]}" aria-pressed="${k[0] === first}">${k[1]}</button>`).join("")}</div>
    <form class="move-form">
      <div class="mv" data-for="movie"><input name="title" placeholder="Title" aria-label="Movie title" value="${esc(!isShow && !ep ? x.title || "" : "")}">
        <input name="year" placeholder="Year" aria-label="Year" inputmode="numeric" maxlength="4" value="${esc(!isShow && !ep ? x.year || "" : "")}"></div>
      <div class="mv" data-for="episode"><input name="show" list="mvShows" placeholder="Show" aria-label="Show" value="${esc(ep && ep.show ? ep.show.name : "")}">
        <datalist id="mvShows">${shows.map(s => `<option value="${esc(s.name)}">`).join("")}</datalist>
        <input name="season" placeholder="Season" aria-label="Season" inputmode="numeric" value="${esc(ep ? ep.s : "1")}">
        <input name="episode" placeholder="Episode" aria-label="Episode" inputmode="numeric" value="${esc(ep ? ep.e : "")}"></div>
      <div class="mv" data-for="adult"><input name="category" list="mvCats" placeholder="Category (Movies, Hentai, Shows, ...)" aria-label="Category" value="${esc(x.category || (isShow ? "Shows" : "Movies"))}">
        <datalist id="mvCats">${[...new Set(cats.concat(["Movies", "Hentai", "Shows", "Collections"]))].map(c => `<option value="${esc(c)}">`).join("")}</datalist>
        ${isShow ? "" : `<input name="atitle" placeholder="Title" aria-label="Title" value="${esc(x.title || "")}">`}</div>
      <div class="mv" data-for="shows"><p class="hint">The show's folder moves to Shows, with everything in it.</p></div>
      <div class="mv" data-for="review"><p class="hint">It goes to the Needs Review folder, to sort out by hand.</p></div>
      <div class="form-error" role="alert"></div>
      <div class="actions"><button class="btn primary" type="submit">Move it</button><button class="btn ghost" type="button" data-dismiss="1">Cancel</button></div>
    </form>`);
  const form = $(".move-form", d);
  let kind = first;
  const show = () => { d.querySelectorAll(".mv").forEach(m => m.hidden = m.dataset.for !== kind); d.querySelectorAll("[data-kind]").forEach(b => b.setAttribute("aria-pressed", b.dataset.kind === kind)); };
  show();
  d.addEventListener("click", e => { const b = e.target.closest("[data-kind]"); if (b) { kind = b.dataset.kind; show(); } });
  form.addEventListener("submit", async e => {
    e.preventDefault();
    const f = form.elements, target = { kind };
    if (kind === "movie") Object.assign(target, { title: f.title.value, year: f.year.value });
    if (kind === "episode") Object.assign(target, { show: f.show.value, season: f.season.value, episode: f.episode.value });
    if (kind === "adult") Object.assign(target, { category: f.category.value, title: f.atitle ? f.atitle.value : "" });
    const btn = $("button[type=submit]", form); btn.disabled = true; btn.textContent = "Moving…";
    try { await relocate(id, target); } catch (ex) { $(".form-error", form).textContent = ex.message; btn.disabled = false; btn.textContent = "Move it"; }
  });
}

/* ---------- TV remote: arrow keys move focus to the nearest thing in that direction ---------- */
const FOCUSABLE = "a[href], button:not([disabled]):not([tabindex='-1']), input, select, [tabindex='0'], [data-mplay]";
const ARROWS = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
function focusables(scope) {
  return [...scope.querySelectorAll(FOCUSABLE)].filter(el => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && !el.closest("[hidden]") && getComputedStyle(el).visibility !== "hidden";
  });
}
/* Move focus to the nearest focusable thing in direction `dir` inside `scope`. True if it moved. */
function spatialMove(dir, scope, first) {
  const els = focusables(scope), active = document.activeElement;
  if (!els.length) return false;
  if (!active || active === document.body || !els.includes(active)) {
    const f = (first && scope.querySelector(first)) || els[0];
    f.focus({ preventScroll: true }); f.scrollIntoView({ block: "nearest", inline: "nearest" }); return true;
  }
  const a = active.getBoundingClientRect(), ax = a.left + a.width / 2, ay = a.top + a.height / 2;
  let best = null, bestScore = Infinity;
  els.forEach(el => {
    if (el === active) return;
    const r = el.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2;
    const dx = x - ax, dy = y - ay, along = dx * dir[0] + dy * dir[1];
    if (along <= 4) return;
    const across = Math.abs(dir[0] ? dy : dx);
    const score = along + across * 2.5;
    if (score < bestScore) { bestScore = score; best = el; }
  });
  if (!best) return false;
  best.focus({ preventScroll: true }); best.scrollIntoView({ block: "nearest", inline: "nearest", behavior: TV ? "auto" : "smooth" });
  return true;
}
document.addEventListener("keydown", e => {
  if (e.key === "Escape" && document.querySelector(".dialog-scrim") && !Player.isOpen()) { e.preventDefault(); closeDialog(); return; }
  const dir = ARROWS[e.key];
  if (!dir || Player.isOpen() || e.metaKey || e.ctrlKey || e.altKey) return;
  const active = document.activeElement;
  if (active && (active.tagName === "INPUT" && active.type !== "checkbox" && (dir[0] !== 0 || active.type === "range"))) return;
  document.body.classList.add("tv-nav");
  const scrim = document.querySelector(".dialog-scrim");            // a dialog keeps the remote inside it
  if (spatialMove(dir, scrim || document, scrim ? null : ".hero .btn, .card, .seasons button, .episode .ep-thumb")) e.preventDefault();
});
document.addEventListener("mousedown", () => document.body.classList.remove("tv-nav"));
// "/" goes to search (a keyboard's habit, and a controller's Y on the Sofa box).
document.addEventListener("keydown", e => {
  if (e.key !== "/" || Player.isOpen() || e.metaKey || e.ctrlKey || e.altKey) return;
  const a = document.activeElement;
  if (a && (a.tagName === "INPUT" || a.tagName === "TEXTAREA" || a.tagName === "SELECT" || a.isContentEditable)) return;
  e.preventDefault(); location.hash = "#/search";
});
// Song rows and queue entries are list items: OK / Enter plays them like a click.
document.addEventListener("keydown", e => {
  if ((e.key === "Enter" || e.key === " ") && e.target.matches && e.target.matches("[data-mplay],[data-qjump]")) { e.preventDefault(); e.target.click(); }
});

/* ---------- the phone remote: "Play on" another screen ----------
   Every open Sofa page is a screen. A phone sees its person's other open screens (the TV, a laptop),
   sends one something to play and controls it from a bar at the bottom; the TV waits for commands
   and says what it's playing. It all goes through the Sofa computer, at home, and nothing is kept. */
const Screens = (function () {
  const wait = ms => new Promise(r => setTimeout(r, ms));
  const id = (() => {
    try { let v = sessionStorage.getItem("sofaScreen"); if (!v) { v = Math.random().toString(36).slice(2, 12) + Date.now().toString(36).slice(-4); sessionStorage.setItem("sofaScreen", v); } return v; }
    catch (e) { return Math.random().toString(36).slice(2, 14); }
  })();
  const ua = navigator.userAgent;
  const defaultName = () => /AFT/.test(ua) ? "Fire TV" : window.SofaBox || (TV && /Linux (aarch64|armv7l)/.test(ua) && !/Android/.test(ua)) ? "Sofa box" : TV ? "TV" : /iPhone/.test(ua) ? "iPhone" : /iPad/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1) ? "iPad"
    : /Android/.test(ua) ? "Android" : /Mac/.test(ua) ? "Mac" : /Windows/.test(ua) ? "Windows PC" : "Browser";
  const name = () => prefs.get("screenName", "") || defaultName();
  let target = null, others = [], listening = false, reported = "", bar = null, pollTimer = 0;

  async function listen() {                    // wait for commands from the person's phone, all the time
    if (listening) return; listening = true;
    while (session && session.user) {
      if (document.hidden && !TV) { await wait(3000); continue; }
      try {
        const r = await api("/api/screen/wait?id=" + id + "&name=" + encodeURIComponent(name()) + "&tv=" + (TV ? 1 : 0));
        (r.commands || []).forEach(run);
      } catch (e) { await wait(5000); }
    }
    listening = false;
  }
  function run(c) {
    if (c.cmd === "play") {
      const it = byId.get(c.item); if (!it) return;
      if (c.t === 0) setProgress(it.id, null, true);
      Player.open(it);
      if (c.from) toast("Playing from " + c.from);
    } else Player.control(c);
    setTimeout(report, 900);
  }
  function report() {                          // what this screen is playing, for the remote's bar
    const st = Player.status(), key = JSON.stringify(st);
    if (key === reported && !st.item) return;
    reported = key;
    api("/api/screen/state", { id, state: st }).catch(() => {});
  }
  setInterval(() => { if (session && session.user && (Player.isOpen() || reported !== "{}")) report(); }, 4000);

  async function refresh() {                   // this person's other screens (for the Play on button)
    clearTimeout(pollTimer);
    if (session && session.user && !document.hidden) {
      try { others = (await api("/api/screens?me=" + id)).screens || []; } catch (e) { others = []; }
      if (target && !others.some(s => s.id === target.id)) { toast(target.name + " isn't open any more."); target = null; }
      const b = $("#castBtn");
      if (b) { b.hidden = !others.length && !target; b.classList.toggle("on", !!target); b.setAttribute("aria-label", target ? "Playing on " + target.name : "Play on another screen"); }
      paint();
    }
    pollTimer = setTimeout(refresh, target ? 2000 : 20000);
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });

  function nowPlaying(s) {
    const it = s.state && s.state.item && byId.get(s.state.item);
    return it ? (s.state.paused ? "Paused: " : "Playing ") + (it.kind === "episode" ? (it.show ? it.show.name : "") + " " + epCode(it) : title(it)) : "Nothing playing";
  }
  function choose() {
    const d = openDialog(`<h2>Play on</h2><div class="cast-list">
      <button class="cast-item" data-cast="" aria-pressed="${!target}"><b>This ${esc(defaultName())}</b><span>Play here, as usual</span></button>
      ${others.map(s => `<button class="cast-item" data-cast="${esc(s.id)}" aria-pressed="${!!target && target.id === s.id}"><b>${esc(s.name)}</b><span>${esc(nowPlaying(s))}</span></button>`).join("")}</div>
      <p class="hint">${session.user.guest ? "The TVs in this house show up here while Sofa is open on them. You can pause or stop only what you started." : "A screen shows up here while Sofa is open on it, signed in as you. Give this one a name under Theme."}</p>`);
    d.addEventListener("click", e => {
      const b = e.target.closest("[data-cast]"); if (!b) return;
      const s = others.find(x => x.id === b.dataset.cast);
      target = s ? { id: s.id, name: s.name } : null;
      closeDialog(); refresh();
      if (s) toast("Now Play sends things to " + s.name + ".");
    });
  }
  async function send(command) {
    if (!target) return;
    try { await api("/api/screens/" + target.id, { command, name: name() }); setTimeout(refresh, 800); }
    catch (e) { toast(e.message); if (e.status === 404) { target = null; refresh(); } }
  }
  function paint() {                           // the remote: a bar at the bottom while playing on another screen
    if (!target) { if (bar) bar.hidden = true; document.body.classList.remove("has-remote"); return; }
    if (!bar) {
      bar = document.createElement("div"); bar.className = "remote-bar"; bar.setAttribute("role", "region"); bar.setAttribute("aria-label", "Remote");
      document.body.appendChild(bar);
      bar.addEventListener("click", e => {
        const b = e.target.closest("[data-rc]");
        if (b) { const a = b.dataset.rc; send(a === "back" ? { cmd: "skip", by: -10 } : a === "fwd" ? { cmd: "skip", by: 30 } : { cmd: a }); return; }
        const sc = e.target.closest(".rb-scrub");
        if (sc && sc.dataset.d) { const r = sc.getBoundingClientRect(); send({ cmd: "seek", t: Math.round((e.clientX - r.left) / r.width * +sc.dataset.d) }); return; }
        if (e.target.closest("[data-rc-leave]")) { target = null; refresh(); }
      });
    }
    const s = others.find(x => x.id === target.id) || { state: {} }, st = s.state || {}, it = st.item && byId.get(st.item);
    const owner = it ? it.show || it : null, art = it ? it.thumb || (owner && (owner.backdrop || owner.poster)) : "";
    bar.hidden = false; document.body.classList.add("has-remote");
    bar.innerHTML = `<div class="rb-top">${art ? `<img src="${esc(artSrc(art, 240))}" alt="">` : `<span class="rb-noart">${icon("i-cast")}</span>`}
        <div class="rb-text"><b>${esc(it ? owner.name || owner.title : "Nothing playing")}</b><span>${esc([it ? (it.kind === "episode" ? epCode(it) + (it.title ? " · " + it.title : "") : "") : "Press Play on anything", "on " + target.name].filter(Boolean).join(" · "))}</span></div>
        <button class="rb-leave" data-rc-leave="1" aria-label="Play here again" title="Play here again">${icon("i-close")}</button></div>
      ${it && st.d ? `<div class="rb-scrub" data-d="${st.d}"><i style="width:${Math.min(100, st.t / st.d * 100)}%"></i></div><div class="rb-time"><span>${clock(st.t)}</span><span>${clock(st.d)}</span></div>` : ""}
      ${it ? `<div class="rb-btns"><button data-rc="back" aria-label="Back 10 seconds">${icon("i-rew")}</button>
        <button class="rb-main" data-rc="toggle" aria-label="${st.paused ? "Play" : "Pause"}">${icon(st.paused ? "i-play" : "i-pause")}</button>
        <button data-rc="fwd" aria-label="Forward 30 seconds">${icon("i-fwd")}</button>
        ${it.kind === "episode" ? `<button data-rc="next" aria-label="Next episode">${icon("i-skip")}</button>` : ""}
        <button data-rc="stop" aria-label="Stop">${icon("i-stop")}</button></div>` : ""}`;
  }
  return {
    start() { if (!session.user.guest) listen(); refresh(); },      // a guest only sends (to the house's TVs)
    target: () => target,
    choose,
    play(itemId, fromStart) { send({ cmd: "play", item: itemId, t: fromStart ? 0 : undefined }); },
    name, defaultName
  };
})();

/* ---------- player ---------- */
const Player = (function () {
  const el = $("#player"), video = $("video", el), canvas = $("canvas", el), ctx = canvas.getContext("2d");
  const scrub = $(".scrub", el), fill = $(".fill", el), buf = $(".buf", el), knob = $(".knob", el), hoverTime = $(".hover-time", el);
  const timeEl = $(".p-time", el), modeEl = $(".p-mode", el), chip = $(".p-chip", el), nextCard = $(".p-next", el), errorBox = $(".p-error", el);
  const flash = $(".p-flash", el), toggleBtn = $('[data-act="toggle"]', el), volume = $(".vol input", el);
  const ccBtn = $('[data-act="cc"]', el), ccMenu = $(".cc-menu", el);
  const spinner = $(".p-spinner", el), pauseInfo = $(".p-pause-info", el), epsPanel = $(".p-eps", el), helpBox = $(".p-help", el);
  const seekHint = $(".p-seekhint", el), endsEl = $(".p-ends", el), epsBtn = $('[data-act="eps"]', el), pipBtn = $('[data-act="pip"]', el);
  let subDelay = 0;           // seconds the subtitles are moved (+ later, - earlier), for this video
  let audioChoice = null, burnChoice = null, pauseTimer = 0, spinTimer = 0, lastTap = { t: 0, x: 0 }, tapTimer = 0;
  const skipBtn = $(".p-skip", el), optsBox = $(".p-opts", el), stillBox = $(".p-still", el), thumbEl = $(".p-thumb", el), htLabel = $(".ht-label", el);
  let trick = null, markers = [], skipShown = null, autoNexts = 0, lastInput = Date.now(), introStart = null;
  const marksEl = document.createElement("div"); marksEl.className = "marks"; $(".track", scrub).appendChild(marksEl);
  function drawMarks() {
    const d = total();
    marksEl.innerHTML = d ? markers.map(m => `<i class="mk-${esc(m.kind)}" title="${esc(m.kind)}" style="left:${m.start / d * 100}%;width:${Math.max(0.4, (m.end - m.start) / d * 100)}%"></i>`).join("") : "";
  }
  const opt = (k, d) => prefs.get("p." + k, d), setOpt = (k, v) => prefs.set("p." + k, v);
  const SPEEDS = [1, 1.25, 1.5, 2, 0.75];
  // Converted video is HLS. Apple's own HLS player is the best there is; Android's (what Silk on a Fire TV
  // uses) treats Sofa's growing playlist as live TV: when the converter is only just ahead, it stalls and then
  // jumps forward, skipping a few seconds. hls.js waits instead, so it plays everywhere else.
  const UA = navigator.userAgent, MSE = window.ManagedMediaSource || window.MediaSource;
  const appleHls = /iPhone|iPad|iPod/.test(UA) || (/Macintosh/.test(UA) && /Safari\//.test(UA) && !/Chrome|Chromium|Edg\/|Firefox|Silk/.test(UA));
  const nativeHls = !!video.canPlayType("application/vnd.apple.mpegurl") && (appleHls || !MSE);
  // A codec counts when the element plays it and, for converted video through hls.js, so does MediaSource.
  const plays = type => !!video.canPlayType(type) && (nativeHls || !MSE || !!(MSE.isTypeSupported && MSE.isTypeSupported(type)));
  const caps = NATIVE ? JSON.parse(NATIVE.caps()) : {
    mkv: !!(video.canPlayType('video/x-matroska; codecs="avc1.64001F, mp4a.40.2"') || video.canPlayType("video/x-matroska")),
    hevc: plays('video/mp4; codecs="hvc1.1.6.L93.B0"'),
    hevc10: plays('video/mp4; codecs="hvc1.2.4.L120.B0"'),
    ac3: plays('audio/mp4; codecs="ac-3"') || plays('audio/mp4; codecs="ec-3"'),
    vp9: !!video.canPlayType('video/webm; codecs="vp9"')
  };
  let item = null, next = null, plan = null, offset = 0, hlsSession = null, subIndex = -1;
  let lastSave = 0, idleTimer = 0, ambientTimer = 0, nextHidden = false, dragging = false, returnFocus = null;

  if ("filter" in ctx) ctx.filter = "blur(1.5px)";
  volume.value = prefs.get("volume", 1);
  video.volume = +volume.value;
  video.muted = prefs.get("muted", false);
  setAmbient(TV ? false : prefs.get("ambient", true));   // the glow costs too much on TV sticks

  const live = () => plan && plan.mode !== "direct";
  const now = () => offset + (video.currentTime || 0);
  const total = () => (plan && plan.duration) || (isFinite(video.duration) ? video.duration : 0);

  let pushed = false;
  function enterHistory() {
    if (!pushed) { history.pushState({ sofaLayer: "player" }, ""); pushed = true; }
    if (TV && !document.fullscreenElement && el.requestFullscreen) el.requestFullscreen().catch(() => {});
  }
  function requestClose() { if (pushed) history.back(); else close(); }   // Back, Escape and the ← button all end here
  let playQueue = null;
  async function open(it, queue) {
    if (!it) return;
    stopTrailer();
    if (NATIVE && it.kind !== "track") return nativeOpen(it, queue);
    playQueue = queue && queue.includes(it) ? queue : null;
    MusicPlayer.pause();
    enterHistory();
    if (hls) { hls.destroy(); hls = null; }
    el.classList.remove("is-live"); liveList_ = null;
    video.removeAttribute("src"); video.load();
    returnFocus = document.activeElement;
    item = it; next = playQueue ? playQueue[playQueue.indexOf(it) + 1] || null : nextAfter(it); nextHidden = false; audioChoice = null; subDelay = 0;
    autoCap = null; stalls = []; burnChoice = null;
    errorBox.hidden = chip.hidden = nextCard.hidden = ccMenu.hidden = epsPanel.hidden = helpBox.hidden = pauseInfo.hidden = true;
    const owner = it.show || it;
    $(".p-show", el).textContent = owner.name || it.title;
    $(".p-title", el).textContent = it.kind === "movie" ? [it.year, it.studio].filter(Boolean).join(" · ") : subtitleFor(it);
    epsBtn.hidden = it.kind !== "episode";
    trick = null; markers = []; skipShown = null; skipBtn.hidden = optsBox.hidden = stillBox.hidden = true;
    loadTrick(it);
    pipBtn.hidden = TV || !document.pictureInPictureEnabled;
    showSpinner("Loading…");
    $('[data-act="next"]', el).hidden = !next;
    el.hidden = false;
    document.body.style.overflow = "hidden";
    video.playbackRate = 1; $(".speed", el).textContent = "1×";
    try {
      plan = await api("/api/play/" + encodeURIComponent(it.id) + "?" + capsQuery());
    } catch (e) { return showError("This video can't be played", e.message); }
    if (plan.mode === "unsupported") return showError("This video can't be played here", plan.message);
    plan.audio = plan.audio || []; plan.picture_subtitles = plan.picture_subtitles || []; plan.firstMode = plan.mode;
    markers = plan.markers || []; drawMarks();
    const wantAudio = prefs.get("audioLang", null), defAudio = plan.audio.find(a => a.default);
    const pickAudio = wantAudio && defAudio && defAudio.lang !== wantAudio && plan.audio.find(a => a.lang === wantAudio);
    if (pickAudio) { audioChoice = pickAudio.index; if (plan.mode === "direct") plan.mode = "remux"; }
    const wantSub = prefs.get("subLang", null);
    subIndex = prefs.get("subs", false) && plan.subtitles.length ? Math.max(0, plan.subtitles.findIndex(s => s.lang === wantSub)) : -1;
    if (plan.mode !== "direct") showSpinner("Getting the video ready…", plan.why && plan.why.length ? "Adapting " + plan.why.join(", ") + " for this device" : "");
    modeEl.hidden = plan.mode === "direct";
    modeEl.textContent = plan.mode === "remux" ? "Repackaged" : "Converted";
    modeEl.title = plan.why && plan.why.length ? "Adapted for this device: " + plan.why.join(", ") : "";
    ccBtn.hidden = !plan.subtitles.length && !plan.picture_subtitles.length && plan.audio.length < 2;
    const p = prog(it.id);
    const resumeAt = p && !p.done && p.t > 30 && (!plan.duration || p.t < plan.duration - 30) ? p.t : 0;
    await load(resumeAt);
    applyNight();
    if (resumeAt) {
      chip.firstElementChild.textContent = "Resumed at " + clock(resumeAt);
      chip.hidden = false;
      setTimeout(() => { chip.hidden = true; }, 7000);
    }
    wake();
    toggleBtn.focus();
  }
  async function load(at) {
    at = Math.max(0, at || 0);
    endHold(false); loadedAt = Date.now();
    const picture = prefs.get("quality", "") || autoCap || "";
    if (plan.mode === "direct") {
      offset = 0;
      if (!video.getAttribute("src")) {
        video.src = plan.url;
        await new Promise(r => { video.addEventListener("loadedmetadata", r, { once: true }); video.addEventListener("error", r, { once: true }); });
      }
      if (at) video.currentTime = at;
    } else if (nativeHls || await hlsJsReady()) {
      // Converted video comes as short HLS segments: steady buffering, and a closed tab can't jam the converter.
      try {
        const h = await api("/api/hls/" + encodeURIComponent(item.id) + "?mode=" + plan.mode + "&t=" + at.toFixed(1) + (hlsSession ? "&replace=" + hlsSession : "") +
                            (audioChoice != null ? "&audio=" + audioChoice : "") + (picture ? "&h=" + picture : "") +
                            (burnChoice != null ? "&burn=" + burnChoice : "") + "&" + capsQuery());
        hlsSession = h.session; offset = at;
        if (hls) { hls.destroy(); hls = null; }
        if (nativeHls) video.src = h.url;
        else {
          // The playlist grows while Sofa converts: start at its beginning (hls.js never jumps ahead to "live"
          // by itself), and keep a minute and a half behind for ←, not more (TV sticks have little memory).
          hls = new window.Hls({ startPosition: 0, maxBufferLength: 60, maxMaxBufferLength: 180, backBufferLength: 90,
                                 maxBufferHole: 0.5, manifestLoadingTimeOut: 30000,
                                 levelLoadingTimeOut: 30000, fragLoadingTimeOut: 40000 });
          hls.on(window.Hls.Events.ERROR, (_, data) => { if (data.fatal) playbackFailed(); });
          hls.loadSource(h.url); hls.attachMedia(video);
        }
      } catch (e) { return showError("This video can't be played right now", e.message); }
    } else {
      offset = at;
      video.src = (plan.mode === "direct" ? plan.url : "/media/" + encodeURIComponent(item.id) + "/stream?mode=" + plan.mode) + "&t=" + at.toFixed(1) +
                  (audioChoice != null ? "&audio=" + audioChoice : "") + (picture && plan.mode === "transcode" ? "&h=" + picture : "") +
                  (burnChoice != null ? "&burn=" + burnChoice : "") + "&" + capsQuery();
    }
    setSubtitles(subIndex);
    video.play().catch(() => {});
    paint();
  }
  /* Converted video on a computer that's only just keeping up: instead of stopping every few seconds,
     wait once for some video to be ready; if it still keeps stopping, make the picture smaller (lighter to
     convert, and to send over weak Wi-Fi). Sofa remembers that for the next video like it. */
  let holding = 0, holdTimer = 0, holdResume = false, stalls = [], autoCap = null, loadedAt = 0;
  const HOLD_FOR = 10;
  function aheadOf() {
    const b = video.buffered, t = video.currentTime;
    for (let i = 0; i < b.length; i++) if (b.start(i) <= t + 0.3 && b.end(i) > t) return b.end(i) - t;
    return 0;
  }
  function stalled() {
    if (!item || !live() || el.classList.contains("is-live") || holding || video.seeking || video.paused) return;
    if (Date.now() - loadedAt < 8000 || video.currentTime < 2 || (total() && now() > total() - 15)) return;
    // Waiting once just after starting is normal. Twice more within ten minutes: the computer can't keep up.
    if (Date.now() - loadedAt > 25000) stalls = stalls.filter(at => Date.now() - at < 600000).concat(Date.now());
    const smaller = [540, 360].find(x => x < video.videoHeight - 20);
    if (stalls.length >= 2 && plan.mode === "transcode" && !prefs.get("quality", "") && smaller) {
      stalls = []; autoCap = smaller;
      showSpinner("Making the picture a little smaller…", "This computer can't convert this video quite fast enough, so it kept stopping.");
      load(now()).then(() => {
        chip.firstElementChild.textContent = "Smaller picture, so it stops stopping (Options → Picture)";
        chip.hidden = false; setTimeout(() => { chip.hidden = true; }, 8000);
      });
      return;
    }
    holding = Date.now();
    video.pause();
    showSpinner("Getting the next part ready…", "Waiting for a few seconds of video, so it doesn't keep stopping.");
    holdTimer = setInterval(() => {
      const ahead = aheadOf();
      if (ahead >= HOLD_FOR || (total() && now() + ahead >= total() - 1) || Date.now() - holding > 30000) endHold(true);
    }, 400);
  }
  function endHold(play) {
    if (!holding) return;
    holding = 0; clearInterval(holdTimer);
    if (play) { holdResume = true; hideSpinner(); video.play().catch(() => {}); }
  }
  function userPause() {             // a pause pressed while it's waiting: stay paused when the video's ready
    if (holding) { endHold(false); hideSpinner(); setPlayingUI(); save(true); } else video.pause();
  }
  let hlsJsOk = null;
  async function hlsJsReady() {
    if (hlsJsOk === null) { try { await loadHlsJs(); hlsJsOk = window.Hls.isSupported(); } catch (e) { hlsJsOk = false; } }
    return hlsJsOk;
  }
  async function playbackFailed() {
    if (!item || el.classList.contains("is-live")) return;
    let why = "";
    try { const p = await api("/api/play/" + encodeURIComponent(item.id) + "?probe=1"); why = p.error ? p.error.message : ""; } catch (e) {}
    showError("This video stopped", why ? "The server said: " + why
      : "The file may have moved, or the server couldn't read it. An admin can convert it to MP4 from the Server page.");
  }
  function stopServerStream() { if (hlsSession) { api("/api/hls/stop", {}).catch(() => {}); hlsSession = null; } }
  function seekTo(t) {
    t = Math.max(0, Math.min(total() ? total() - 1 : t, t));
    if (!live()) { video.currentTime = t; return; }
    const bufferedEnd = video.buffered.length ? offset + video.buffered.end(video.buffered.length - 1) : 0;
    if (t >= offset && t <= bufferedEnd) video.currentTime = t - offset;   // already have it
    else load(t);
  }
  function close() {
    pushed = false; endHold(false);
    clearTimeout(sleepTimer); sleepPlan = {};
    if (hls) { hls.destroy(); hls = null; }
    el.classList.remove("is-live"); liveList_ = null;
    save(true);
    video.pause();
    video.removeAttribute("src"); video.load();
    [...video.querySelectorAll("track")].forEach(t => t.remove());
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    el.hidden = true; document.body.style.overflow = "";
    stopAmbient();
    stopServerStream();
    hideSpinner(); clearTimeout(pauseTimer); skipBtn.hidden = optsBox.hidden = stillBox.hidden = true; delete nextCard.dataset.credits;
    if (document.pictureInPictureElement) document.exitPictureInPicture().catch(() => {});
    item = null; plan = null;
    rerender();
    if (returnFocus && document.contains(returnFocus)) returnFocus.focus();
  }
  function save(force) {
    if (!item || !total()) return;
    const t = now(), d = total();
    if (!force && Date.now() - lastSave < 5000) return;
    lastSave = Date.now();
    const prev = progress[item.id] || {};
    if (t < 5 && !prev.done && !force) return;
    const finished = t / d >= 0.93 || d - t < 45;
    setProgress(item.id, { t: finished ? d : t, d, done: finished || (prev.done && t < 5) }, force);
  }
  function playNext(auto) {
    if (!next) return;
    autoNexts = auto === true && Date.now() - lastInput > 60000 ? autoNexts + 1 : 0;
    save(true); stopServerStream(); const n = next; video.removeAttribute("src"); delete nextCard.dataset.credits;
    open(n, playQueue).then(() => {
      if (autoNexts >= 3 && opt("still", true)) { video.pause(); stillBox.hidden = false; $(".btn", stillBox).focus(); }
    });
  }
  function showError(heading, msg) {
    hideSpinner();
    const canConvert = session.user.admin && item && !el.classList.contains("is-live");
    errorBox.innerHTML = `<h2>${esc(heading)}</h2><p>${esc(msg || "")}</p><div class="actions"><button class="btn" data-act="close">Back to library</button>
      ${item && !el.classList.contains("is-live") ? `<button class="btn" data-act="retry">Try again</button>` : ""}
      ${canConvert ? `<button class="btn primary" data-act="convert">Convert this file to MP4</button>` : ""}</div>`;
    errorBox.hidden = false; wake();
  }
  function setSubtitles(i) {
    [...video.querySelectorAll("track")].forEach(t => t.remove());
    subIndex = plan && i >= 0 && i < plan.subtitles.length ? i : -1;
    ccBtn.setAttribute("aria-pressed", subIndex >= 0);
    if (subIndex < 0) return;
    const s = plan.subtitles[subIndex];
    const tr = document.createElement("track");
    tr.kind = "subtitles"; tr.label = s.label; tr.srclang = (s.lang || "und").slice(0, 2);
    tr.src = s.url + (offset || subDelay ? "?offset=" + (offset - subDelay).toFixed(2) : "");
    tr.default = true;
    video.appendChild(tr);
    tr.addEventListener("load", () => { tr.track.mode = "showing"; });
    tr.track.mode = "showing";
  }
  const currentAudio = () => audioChoice != null ? audioChoice : ((plan.audio || []).find(a => a.default) || {}).index;
  function ccMenuOpen() {
    const aud = plan.audio || [];
    ccMenu.innerHTML = (aud.length > 1 ? `<div class="cc-col"><h4>Audio</h4>${aud.map(a =>
        `<button role="menuitemradio" aria-checked="${a.index === currentAudio()}" data-aud="${a.index}">${esc(a.label)}</button>`).join("")}</div>` : "") +
      `<div class="cc-col"><h4>Subtitles</h4><button role="menuitemradio" aria-checked="${subIndex < 0 && burnChoice == null}" data-sub="-1">Off</button>${
        plan.subtitles.map((s, i) => `<button role="menuitemradio" aria-checked="${i === subIndex}" data-sub="${i}">${esc(s.label)}</button>`).join("")}${
        plan.picture_subtitles.map(s => `<button role="menuitemradio" aria-checked="${s.index === burnChoice}" data-burn="${s.index}" title="Drawn onto the picture (Blu-ray and DVD subtitles are pictures). Sofa converts the video to do it.">${esc(s.label)} <small>on the picture</small></button>`).join("") ||
        (plan.subtitles.length ? "" : `<p class="cc-none">This video has no subtitles. Put a .srt file with the same name next to it.</p>`)}</div>`;
    ccMenu.hidden = false; epsPanel.hidden = true;
    $("[aria-checked='true']", ccMenu).focus();
  }
  ccMenu.addEventListener("click", e => {
    const b = e.target.closest("[data-sub],[data-aud],[data-burn]"); if (!b) return;
    const burn = b.dataset.burn != null ? +b.dataset.burn : null;
    if (burn !== burnChoice && (burn != null || burnChoice != null)) {     // drawing subtitles on (or stopping): a new stream
      burnChoice = burn; setSubtitles(-1);
      if (burn == null && b.dataset.sub !== "-1") setSubtitles(+b.dataset.sub);
      prefs.set("subs", burn != null || subIndex >= 0);
      plan.mode = burn != null ? "transcode" : audioChoice != null && plan.firstMode === "direct" ? "remux" : plan.firstMode;
      modeEl.hidden = plan.mode === "direct"; modeEl.textContent = plan.mode === "remux" ? "Repackaged" : "Converted";
      ccMenu.hidden = true; ccBtn.focus();
      showSpinner(burn != null ? "Putting the subtitles on the picture…" : "Taking the subtitles off…"); load(now());
      return;
    }
    if (burn != null) { ccMenu.hidden = true; ccBtn.focus(); return; }
    if (b.dataset.aud) {
      const idx = +b.dataset.aud, a = plan.audio.find(x => x.index === idx);
      ccMenu.hidden = true; ccBtn.focus();
      if (idx === currentAudio()) return;
      audioChoice = idx; prefs.set("audioLang", a && a.lang !== "und" ? a.lang : null);
      if (plan.mode === "direct") plan.mode = "remux";
      modeEl.hidden = false; modeEl.textContent = "Repackaged";
      showSpinner("Switching sound track…"); load(now());
      return;
    }
    setSubtitles(+b.dataset.sub); prefs.set("subs", subIndex >= 0);
    if (subIndex >= 0) prefs.set("subLang", plan.subtitles[subIndex].lang);
    ccMenu.hidden = true; ccBtn.focus();
  });

  /* scrubbing previews */
  async function loadTrick(it, again) {
    try {
      const t = await api("/media/" + encodeURIComponent(it.id) + "/trick.json");
      if (item !== it) return;
      if (t.sheets) trick = Object.assign(t, { base: "/media/" + encodeURIComponent(it.id) + "/trick/" });
      else if (t.pending && !again) setTimeout(() => { if (item === it) loadTrick(it, true); }, 25000);
    } catch (e) {}
  }
  function showThumb(sec) {
    if (!trick) { thumbEl.hidden = true; return; }
    const n = Math.min(trick.count - 1, Math.floor(sec / trick.interval)), per = trick.cols * trick.rows;
    const sheet = Math.floor(n / per), pos = n % per;
    if (sheet >= trick.sheets) { thumbEl.hidden = true; return; }
    const k = TV ? 1.25 : 1, w = trick.w * k, h = trick.h * k;
    thumbEl.style.width = w + "px"; thumbEl.style.height = h + "px";
    thumbEl.style.backgroundImage = `url("${trick.base}${sheet}.jpg")`;
    thumbEl.style.backgroundSize = `${trick.cols * w}px ${trick.rows * h}px`;
    thumbEl.style.backgroundPosition = `-${(pos % trick.cols) * w}px -${Math.floor(pos / trick.cols) * h}px`;
    const part = markers.find(m => sec >= m.start && sec < m.end);
    thumbEl.dataset.part = part ? { intro: "Intro", recap: "Recap", credits: "Credits" }[part.kind] || "" : "";
    thumbEl.hidden = false;
  }

  /* Skip Intro / Skip Recap / credits: buttons that appear at the right moment */
  const SKIP_LABEL = { intro: "Skip Intro", recap: "Skip Recap", credits: "Skip Credits" };
  function checkMarkers(t) {
    if (!markers.length || el.classList.contains("is-live")) return;
    const m = markers.find(x => t >= x.start - 0.5 && t < x.end - 1.5);
    const credits = markers.find(x => x.kind === "credits" && t >= x.start - 0.5);
    if (credits && next && !nextHidden && opt("autoplay", true)) { skipBtn.hidden = true; return showNextCard(credits); }
    if (m && m.kind !== "credits" && opt("autoskip", false) && skipShown !== m) { skipShown = m; seekTo(m.end); toast("Skipped the " + m.kind); return; }
    if (m && (m.kind !== "credits" || !next)) {
      if (skipShown !== m) { skipShown = m; skipBtn.textContent = SKIP_LABEL[m.kind]; skipBtn.dataset.to = m.end; skipBtn.hidden = false;
        if (TV && !openPanel()) skipBtn.focus({ preventScroll: true }); }    // on a TV, OK skips (like Netflix)
    } else if (!skipBtn.hidden) {
      const had = document.activeElement === skipBtn;
      skipBtn.hidden = true; skipShown = null;
      if (had) toggleBtn.focus({ preventScroll: true });
    }
  }
  function showNextCard(credits) {
    if (sleepPlan.mode === "end") return;                  // the sleep timer stops here instead
    if (!nextCard.hidden) return;
    $(".frame", nextCard).innerHTML = thumbFor(next);
    $(".name", nextCard).textContent = subtitleFor(next);
    $(".label", nextCard).textContent = "Next episode";
    $('[data-act="cancel-next"]', nextCard).textContent = "Watch credits";
    nextCard.hidden = false; nextCard.dataset.credits = "1";
    nextCard.dataset.at = Date.now();
    if (TV && !openPanel()) $(".btn.primary", nextCard).focus({ preventScroll: true });
  }

  /* sleep timer: stop at the end of this episode, or after a while */
  let sleepPlan = {}, sleepTimer = 0;
  function setSleep(v) {
    clearTimeout(sleepTimer); sleepPlan = {};
    if (v === "end") sleepPlan = { mode: "end" };
    else if (v === "30" || v === "60") {
      sleepPlan = { mode: v, at: Date.now() + v * 60000 };
      sleepTimer = setTimeout(() => goToSleep(), v * 60000);
    }
    if (v !== "off") toast(v === "end" ? "Sofa stops at the end of this one." : "Sofa stops in " + (v === "60" ? "an hour." : "30 minutes."));
  }
  function goToSleep() {
    sleepPlan = {}; nextCard.hidden = true; endHold(false); video.pause(); save(true);
    toast("Good night. The sleep timer stopped playing; press Play to carry on.");
  }

  /* the options menu */
  /* Night mode: loud scenes quieter and voices clearer, worked out on this device (a lift for speech and a
     compressor). Not on iPhone and iPad, where Safari can go silent when video sound is processed. */
  const APPLE_TOUCH = /iPad|iPhone|iPod/.test(navigator.userAgent) || (/Macintosh/.test(navigator.userAgent) && navigator.maxTouchPoints > 1);
  const nightOk = !APPLE_TOUCH && !!(window.AudioContext || window.webkitAudioContext);
  let night = null;
  async function applyNight() {
    const on = nightOk && opt("night", false);
    if (!night) {
      if (!on) return;
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      try { await ctx.resume(); } catch (e) {}
      if (ctx.state !== "running") { ctx.close(); return; }      // not allowed until a button is pressed: sound stays as it is
      const voice = ctx.createBiquadFilter(), comp = ctx.createDynamicsCompressor(), lift = ctx.createGain();
      voice.type = "peaking"; voice.frequency.value = 2500; voice.Q.value = 0.8; voice.gain.value = 5;
      comp.threshold.value = -32; comp.knee.value = 24; comp.ratio.value = 6; comp.attack.value = 0.005; comp.release.value = 0.3;
      lift.gain.value = 1.8;
      voice.connect(comp); comp.connect(lift); lift.connect(ctx.destination);
      night = { ctx, src: ctx.createMediaElementSource(video), voice };
    }
    night.src.disconnect();
    night.src.connect(on ? night.voice : night.ctx.destination);
    if (night.ctx.state !== "running") night.ctx.resume().catch(() => {});
  }
  function optsOpen() {
    const row = (key, label, hint, def) => `<div class="toggle"><div><b>${label}</b><span>${hint}</span></div>
      <button class="switch small" role="switch" aria-checked="${opt(key, def)}" data-opt="${key}" aria-label="${esc(label)}"></button></div>`;
    const info = plan && plan.mode !== "live" ? `<div class="po-info"><b>Playing</b><span>${esc({ direct: "The original file, as it is", remux: "Repackaged live for this device", transcode: "Converted live for this device" }[plan.mode] || plan.mode)}${plan.why && plan.why.length ? " (" + esc(plan.why.join(", ")) + ")" : ""}${video.videoWidth ? " · " + video.videoWidth + "×" + video.videoHeight : ""}</span></div>` : "";
    optsBox.innerHTML = `<h4>Options</h4>
      ${row("autoplay", "Play the next episode", "Starts the next one when this ends, or when the credits start.", true)}
      ${row("autoskip", "Skip intros by themselves", "Otherwise a Skip Intro button appears.", false)}
      ${row("still", "Ask \"Are you still watching?\"", "After three episodes in a row with no buttons pressed.", true)}
      ${nightOk ? row("night", "Night mode", "Loud scenes quieter, voices clearer. For late nights and thin TV speakers.", false) : ""}
      ${plan && plan.mode === "transcode" ? `<div class="toggle"><div><b>Picture</b><span>For video converted as it plays. Lower is lighter for an older computer or weak Wi-Fi.</span></div><div class="sorter inline">${[["", autoCap ? "Auto (" + autoCap + "p now)" : "Auto"], ["1080", "1080p"], ["720", "720p"], ["480", "480p"]].map(q =>
        `<button data-opt-quality="${q[0]}" aria-pressed="${prefs.get("quality", "") === q[0]}">${q[1]}</button>`).join("")}</div></div>` : ""}
      <div class="toggle"><div><b>Sleep timer</b><span>${sleepPlan.mode === "end" ? "Stops at the end of this " + (item && item.kind === "episode" ? "episode" : "video") + "." : sleepPlan.at ? "Stops at " + new Date(sleepPlan.at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) + "." : "Off."}</span></div>
        <div class="sorter inline">${[["off", "Off"], ["end", "End of this"], ["30", "30 min"], ["60", "1 hour"]].map(o =>
          `<button data-opt-sleep="${o[0]}" aria-pressed="${(sleepPlan.mode || "off") === o[0]}">${o[1]}</button>`).join("")}</div></div>
      <div class="toggle"><div><b>Speed</b></div><div class="sorter inline">${[0.75, 1, 1.25, 1.5, 2].map(s => `<button data-opt-speed="${s}" aria-pressed="${video.playbackRate === s}">${s}×</button>`).join("")}</div></div>
      <div class="toggle"><div><b>Subtitle size</b></div><div class="sorter inline">${[["s", "S"], ["m", "M"], ["l", "L"], ["xl", "XL"]].map(x => `<button data-opt-subsize="${x[0]}" aria-pressed="${prefs.get("subSize", "m") === x[0]}">${x[1]}</button>`).join("")}</div></div>
      <div class="toggle"><div><b>Subtitle style</b></div><div class="sorter inline">${[["box", "On a dark box"], ["outline", "Outlined"]].map(x => `<button data-opt-substyle="${x[0]}" aria-pressed="${prefs.get("subStyle", "box") === x[0]}">${x[1]}</button>`).join("")}</div></div>
      ${subIndex >= 0 ? `<div class="toggle"><div><b>Subtitle timing</b><span>${subDelay ? "Shown " + Math.abs(subDelay).toFixed(1) + " s " + (subDelay > 0 ? "later" : "earlier") + " than the file says." : "As the file has them. Out of sync? Move them."}</span></div>
        <div class="sorter inline"><button data-opt-subdelay="-0.5" aria-label="Subtitles earlier">− 0.5 s</button><button data-opt-subdelay="0" aria-pressed="${!subDelay}">${subDelay ? (subDelay > 0 ? "+" : "") + subDelay.toFixed(1) + " s" : "In sync"}</button><button data-opt-subdelay="0.5" aria-label="Subtitles later">+ 0.5 s</button></div></div>` : ""}
      ${info}
      ${session.user.admin && markers.length ? `<div class="po-info"><b>Intro and credits</b><span>${markers.map(m => esc(m.kind) + " " + clock(m.start) + "–" + clock(m.end)).join(", ")}</span>
        <div class="row-actions">${markers.map(m => `<button class="mini danger" data-opt-clear="${m.kind}">Wrong ${esc(m.kind)}</button>`).join("")}</div></div>` : ""}
      ${session.user.admin && item && item.kind === "episode" ? `<div class="po-info"><b>Mark the intro by hand</b>
        <span>Pause where the intro starts, press "Starts here"; then where it ends, press one of the "Ends here" buttons.${introStart != null ? " Start: " + esc(clock(introStart)) + "." : ""}</span>
        <div class="row-actions"><button class="mini" data-opt-mark="start">Starts here (${esc(clock(now()))})</button>
        <button class="mini" data-opt-mark="episode">Ends here: this episode</button><button class="mini" data-opt-mark="season">Ends here: whole season</button></div></div>` : ""}`;
    optsBox.hidden = false; ccMenu.hidden = epsPanel.hidden = true;
    const f = $("button", optsBox); if (f) f.focus();
  }
  optsBox.addEventListener("click", async e => {
    const b = e.target.closest("[data-opt],[data-opt-speed],[data-opt-subsize],[data-opt-substyle],[data-opt-subdelay],[data-opt-clear],[data-opt-mark],[data-opt-quality],[data-opt-sleep]"); if (!b) return;
    if (b.dataset.optSubstyle) { prefs.set("subStyle", b.dataset.optSubstyle); applySubSize(); optsOpen(); $(`[data-opt-substyle="${b.dataset.optSubstyle}"]`, optsBox).focus(); return; }
    if (b.dataset.optSubdelay !== undefined) {
      const step = +b.dataset.optSubdelay;
      subDelay = step ? Math.round((subDelay + step) * 10) / 10 : 0;
      setSubtitles(subIndex); optsOpen();
      const f = $(`[data-opt-subdelay="${b.dataset.optSubdelay}"]`, optsBox); if (f) f.focus();
      return;
    }
    if (b.dataset.optQuality !== undefined) {
      prefs.set("quality", b.dataset.optQuality); showSpinner("Changing the picture…"); load(now()); optsOpen(); return;
    }
    if (b.dataset.optSleep) { setSleep(b.dataset.optSleep); optsOpen(); return; }
    if (b.dataset.opt) { const on = b.getAttribute("aria-checked") !== "true"; setOpt(b.dataset.opt, on); b.setAttribute("aria-checked", on); if (b.dataset.opt === "night") applyNight(); return; }
    if (b.dataset.optSpeed) { video.playbackRate = +b.dataset.optSpeed; $(".speed", el).textContent = video.playbackRate + "×"; }
    else if (b.dataset.optSubsize) { prefs.set("subSize", b.dataset.optSubsize); applySubSize(); }
    else if (b.dataset.optClear) {
      try { await api("/api/admin/markers/" + encodeURIComponent(item.id), { kind: b.dataset.optClear, clear: true }); markers = markers.filter(m => m.kind !== b.dataset.optClear); skipBtn.hidden = true; toast("Got it. Sofa won't offer that skip on this episode."); } catch (ex) { toast(ex.message); }
    } else if (b.dataset.optMark === "start") {
      introStart = now(); toast("Intro starts at " + clock(introStart) + ". Now find where it ends.");
    } else if (b.dataset.optMark) {
      const start = introStart != null && introStart < now() ? introStart : 0, season = b.dataset.optMark === "season";
      try {
        const r = await api("/api/admin/markers/" + encodeURIComponent(item.id), { kind: "intro", start, end: now(), season });
        markers = r.markers; drawMarks(); introStart = null;
        toast("Saved: intro " + clock(start) + " to " + clock(now()) + (season ? " for " + plural(r.episodes, "episode") + "." : "."));
      } catch (ex) { toast(ex.message); }
    }
    optsOpen();
  });

  /* waiting for video: a spinner that says what's happening */
  function showSpinner(text, hint) {
    $(".p-spin-text", spinner).textContent = text || "Loading…";
    $(".p-spin-hint", spinner).textContent = hint || "";
    spinner.hidden = false;
    clearTimeout(spinTimer);
    spinTimer = setTimeout(() => {
      if (spinner.hidden || !plan || plan.mode === "direct") return;
      $(".p-spin-hint", spinner).textContent = "Still working on it. Converting can take a few seconds the first time." +
        (session.user.admin ? " Converting this file to MP4 (Server page, Converting) makes it start instantly." : "");
    }, 12000);
  }
  function hideSpinner() { spinner.hidden = true; clearTimeout(spinTimer); }

  /* paused for a moment: show what this is */
  function showPauseInfo() {
    if (!item || el.classList.contains("is-live")) return;
    const owner = item.show || item;
    pauseInfo.innerHTML = `<div class="pi-kicker">You're watching</div><h2>${esc(owner.name || item.title)}</h2>
      ${item.kind === "episode" ? `<div class="pi-sub">${esc(epCode(item))} · ${esc(title(item))}</div>` : item.year ? `<div class="pi-sub">${esc(item.year)}</div>` : ""}
      ${item.summary || owner.summary ? `<p>${esc(item.summary || owner.summary)}</p>` : ""}`;
    pauseInfo.hidden = false;
  }

  /* the episode list inside the player */
  function epsOpen(seasonN) {
    if (!item || !item.show) return;
    const show = item.show, season = show.seasons.find(s => s.n === seasonN) || item.season || show.seasons[0];
    epsPanel.innerHTML = `<div class="pe-head"><h3>${esc(show.name)}</h3><button class="ibtn" data-eps-close="1" aria-label="Close">${icon("i-back")}</button></div>
      <div class="chips">${show.seasons.map(s => `<button data-eps-season="${s.n}" aria-pressed="${s === season}">${esc(seasonName(s.n))}</button>`).join("")}</div>
      <div class="pe-list">${season.episodes.map(ep => `<button class="pe-item${ep === item ? " now" : ""}" data-eps-play="${esc(ep.id)}">
        <span class="frame">${thumbFor(ep)}${pct(ep.id) && !isDone(ep.id) ? `<span class="progress"><i style="width:${pct(ep.id)}%"></i></span>` : ""}${isDone(ep.id) ? `<span class="seen-badge">${icon("i-check")}</span>` : ""}</span>
        <span class="pe-text"><b>${esc(ep.e)}. ${esc(title(ep))}</b>${ep === item ? `<span class="now-tag">Playing</span>` : ""}${ep.summary ? `<span class="pe-sum">${esc(ep.summary)}</span>` : ""}</span></button>`).join("")}</div>`;
    epsPanel.hidden = false; ccMenu.hidden = true; helpBox.hidden = true;
    const cur = $(".pe-item.now", epsPanel) || $(".pe-item", epsPanel);
    if (cur) { cur.scrollIntoView({ block: "center" }); cur.focus({ preventScroll: true }); }
  }
  epsPanel.addEventListener("click", e => {
    const b = e.target.closest("[data-eps-play],[data-eps-season],[data-eps-close]"); if (!b) return;
    if (b.dataset.epsClose) { epsPanel.hidden = true; epsBtn.focus(); }
    else if (b.dataset.epsSeason) epsOpen(+b.dataset.epsSeason);
    else { const ep = byId.get(b.dataset.epsPlay); if (ep && ep !== item) { save(true); stopServerStream(); video.removeAttribute("src"); epsPanel.hidden = true; open(ep); } else epsPanel.hidden = true; }
  });

  const SHORTCUTS = [["Space or K", "Play / pause"], ["← / J", "Back 10 seconds"], ["→", "Forward 10 seconds"], ["L", "Forward 30 seconds"],
    ["↑ ↓", "Volume"], ["M", "Mute"], ["F", "Full screen"], ["C", "Audio and subtitles"], ["E", "Episodes"], ["N", "Next episode"],
    ["P", "Picture in picture"], ["S", "Skip intro / recap"], ["< >", "Slower / faster"], ["0 to 9", "Jump to 0% to 90%"], ["Esc", "Close"], ["?", "This list"]];
  function helpToggle() {
    if (!helpBox.hidden) { helpBox.hidden = true; return; }
    helpBox.innerHTML = `<h3>Keyboard shortcuts</h3><dl>${SHORTCUTS.map(s => `<dt><kbd>${esc(s[0])}</kbd></dt><dd>${esc(s[1])}</dd>`).join("")}</dl>
      <p>On a phone: double-tap the left or right side to skip 10 seconds.</p><button class="btn" data-help-close="1">Close</button>`;
    helpBox.hidden = false; ccMenu.hidden = epsPanel.hidden = true; $("button", helpBox).focus();
  }
  helpBox.addEventListener("click", e => { if (e.target.closest("[data-help-close]")) helpBox.hidden = true; });
  // AirPlay (Safari on iPhone, iPad and Mac): the button shows when an Apple TV or AirPlay speaker is around.
  const airBtn = $('[data-act="airplay"]', el);
  if (window.WebKitPlaybackTargetAvailabilityEvent) {
    video.addEventListener("webkitplaybacktargetavailabilitychanged", e => { airBtn.hidden = e.availability !== "available"; });
    airBtn.addEventListener("click", () => video.webkitShowPlaybackTargetPicker());
  }
  function togglePip() {
    if (document.pictureInPictureElement) document.exitPictureInPicture().catch(() => {});
    else if (video.requestPictureInPicture) video.requestPictureInPicture().catch(() => {});
  }
  function flashSeek(text, side) {
    seekHint.textContent = text; seekHint.className = "p-seekhint " + side;
    void seekHint.offsetWidth; seekHint.classList.add("go");
  }
  function paint() {
    const d = total(), t = seekTarget != null ? seekTarget : now();
    const r = d ? Math.min(1, t / d) : 0;
    if (!dragging) { fill.style.width = r * 100 + "%"; knob.style.left = r * 100 + "%"; }
    scrub.setAttribute("aria-valuemax", Math.floor(d)); scrub.setAttribute("aria-valuenow", Math.floor(t));
    scrub.setAttribute("aria-valuetext", clock(t) + " of " + clock(d));
    timeEl.textContent = clock(t) + " / " + clock(d);
    endsEl.textContent = d && !el.classList.contains("is-live") ? "ends " + new Date(Date.now() + (d - t) * 1000 / (video.playbackRate || 1)).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" }) : "";
    if (video.buffered.length && d) buf.style.width = Math.min(100, ((offset + video.buffered.end(video.buffered.length - 1)) / d) * 100) + "%";
    const left = d - t;
    if (next && d && left <= 30 && left > 0 && !nextHidden && opt("autoplay", true)) {
      if (nextCard.hidden) {
        $(".frame", nextCard).innerHTML = thumbFor(next);
        $(".name", nextCard).textContent = subtitleFor(next);
        $('[data-act="cancel-next"]', nextCard).textContent = "Hide";
        nextCard.hidden = false;
        if (TV && !openPanel()) $(".btn.primary", nextCard).focus({ preventScroll: true });
      }
      $(".label", nextCard).textContent = "Next episode in " + Math.ceil(left) + "s";
    } else if (!nextCard.hidden && nextCard.dataset.credits) {
      const wait = 10 - Math.floor((Date.now() - +nextCard.dataset.at) / 1000);    // credits: count down 10 s, then go
      $(".label", nextCard).textContent = "Next episode in " + Math.max(0, wait) + "s";
      if (wait <= 0 && !video.paused) { delete nextCard.dataset.credits; playNext(true); }
    } else if (!nextCard.hidden && left > 30) nextCard.hidden = true;
  }
  function setPlayingUI() {
    const playing = !video.paused;
    $("use", toggleBtn).setAttribute("href", playing ? "#i-pause" : "#i-play");
    toggleBtn.setAttribute("aria-label", playing ? "Pause" : "Play");
    if (playing && el.classList.contains("ambient")) startAmbient(); else stopAmbient();
  }
  function toggle() {
    if (holding || !video.paused) userPause(); else video.play().catch(() => {});
    $("use", flash).setAttribute("href", video.paused ? "#i-pause" : "#i-play");
    flash.classList.remove("go"); void flash.offsetWidth; flash.classList.add("go");
  }
  let seekTarget = null, seekTimer = 0, previewTimer = 0;
  function seekBy(s) {
    if (!total()) return wake();
    if (live() && !el.classList.contains("is-live")) {
      // Converted video: pressing →→→ quickly lands once, instead of restarting the converter on every press.
      seekTarget = Math.max(0, Math.min(total() - 1, (seekTarget != null ? seekTarget : now()) + s));
      clearTimeout(seekTimer);
      seekTimer = setTimeout(() => { const t = seekTarget; seekTarget = null; seekTo(t); }, 700);
      previewAt(seekTarget); paint();
    } else { seekTo(now() + s); previewAt(Math.max(0, now())); }
    if (!lastTap.touchDbl) flashSeek((s < 0 ? "− " : "+ ") + Math.abs(s) + " s", s < 0 ? "left" : "right");
    wake();
  }
  function previewAt(sec) {
    const d = total(); if (!d) return;
    hoverTime.style.left = Math.min(100, sec / d * 100) + "%"; htLabel.textContent = clock(sec); showThumb(sec);
    scrub.classList.add("previewing"); clearTimeout(previewTimer);
    previewTimer = setTimeout(() => scrub.classList.remove("previewing"), 1600);
  }
  function wake() {
    el.classList.remove("idle");
    clearTimeout(idleTimer);
    idleTimer = setTimeout(() => { if (!video.paused && !dragging && !openPanel()) el.classList.add("idle"); }, TV ? 6000 : 2800);
  }
  function setAmbient(on) {
    el.classList.toggle("ambient", on);
    $('[data-act="ambient"]', el).setAttribute("aria-pressed", on);
    prefs.set("ambient", on);
    if (on && !video.paused) startAmbient(); else stopAmbient();
  }
  function startAmbient() {
    if (ambientTimer) return;
    const draw = () => { try { if (video.readyState >= 2) ctx.drawImage(video, 0, 0, canvas.width, canvas.height); } catch (e) {} };
    draw(); ambientTimer = setInterval(draw, 160);
  }
  function stopAmbient() { clearInterval(ambientTimer); ambientTimer = 0; }
  function ratioAt(x) { const r = scrub.getBoundingClientRect(); return Math.max(0, Math.min(1, (x - r.left) / r.width)); }

  video.addEventListener("timeupdate", () => { paint(); save(false); checkMarkers(now()); });
  ["keydown", "pointerdown"].forEach(ev => el.addEventListener(ev, () => { lastInput = Date.now(); }, true));
  video.addEventListener("progress", paint);
  video.addEventListener("durationchange", () => { paint(); drawMarks(); });
  video.addEventListener("play", () => { if (holdResume) { holdResume = false; return; } setPlayingUI(); wake(); clearTimeout(pauseTimer); pauseInfo.hidden = true; });
  video.addEventListener("pause", () => { if (holding) return; setPlayingUI(); save(true); wake(); clearTimeout(pauseTimer);
    if (!video.ended) pauseTimer = setTimeout(() => { if (video.paused && !el.hidden && errorBox.hidden) showPauseInfo(); }, 2500); });
  video.addEventListener("waiting", () => {
    if (el.hidden || !errorBox.hidden) return;
    showSpinner(plan && plan.mode !== "direct" ? "Getting the next part ready…" : "Loading…");
    stalled();
  });
  ["playing", "canplay", "seeked"].forEach(ev => video.addEventListener(ev, () => { if (!holding && (!video.paused || ev !== "seeked")) hideSpinner(); }));
  video.addEventListener("ended", () => {
    save(true);
    if (sleepPlan.mode === "end") return goToSleep();
    if (next && !nextHidden && opt("autoplay", true)) playNext(true); else wake();
  });
  video.addEventListener("error", () => {
    if (el.classList.contains("is-live") && video.getAttribute("src")) return showError("This channel isn't available right now", "Free channels come and go. Try another one, or try this one later.");
    if (!item || (!video.getAttribute("src") && !hls)) return;
    playbackFailed();
  });
  video.addEventListener("click", e => { if (e.pointerType !== "touch" && !lastTap.touch) toggle(); lastTap.touch = false; });
  video.addEventListener("dblclick", e => { if (!lastTap.touchDbl) fullscreen(); lastTap.touchDbl = false; });
  // Phones: tap shows the controls (or pauses when they're showing); double-tap a side skips 10 seconds.
  video.addEventListener("pointerup", e => {
    if (e.pointerType !== "touch") return;
    lastTap.touch = true;
    const now_ = Date.now(), r = video.getBoundingClientRect(), side = e.clientX < r.left + r.width / 2 ? "left" : "right";
    if (now_ - lastTap.t < 320 && Math.abs(e.clientX - lastTap.x) < 80) {
      clearTimeout(tapTimer); lastTap.t = 0; lastTap.touchDbl = true;
      seekBy(side === "left" ? -10 : 10); flashSeek(side === "left" ? "− 10 s" : "+ 10 s", side); return;
    }
    lastTap.t = now_; lastTap.x = e.clientX;
    const wasIdle = el.classList.contains("idle");
    clearTimeout(tapTimer);
    tapTimer = setTimeout(() => { if (wasIdle) wake(); else toggle(); }, 330);
  });
  el.addEventListener("mousemove", wake);

  scrub.addEventListener("pointerdown", e => {
    dragging = true; scrub.classList.add("drag"); scrub.setPointerCapture(e.pointerId);
    const r = ratioAt(e.clientX); fill.style.width = knob.style.left = r * 100 + "%";
  });
  scrub.addEventListener("pointermove", e => {
    const r = ratioAt(e.clientX);
    htLabel.textContent = clock(r * total()); hoverTime.style.left = r * 100 + "%"; showThumb(r * total());
    if (dragging) fill.style.width = knob.style.left = r * 100 + "%";
  });
  scrub.addEventListener("pointerup", e => {
    if (!dragging) return;
    dragging = false; scrub.classList.remove("drag");
    if (total()) seekTo(ratioAt(e.clientX) * total());
    wake();
  });
  volume.addEventListener("input", () => { video.volume = +volume.value; video.muted = +volume.value === 0; prefs.set("volume", +volume.value); });
  video.addEventListener("volumechange", () => {
    $('[data-act="mute"] use', el).setAttribute("href", video.muted || !video.volume ? "#i-mute" : "#i-vol");
    $('[data-act="mute"]', el).setAttribute("aria-label", video.muted ? "Unmute" : "Mute");
    prefs.set("muted", video.muted);
  });
  video.dispatchEvent(new Event("volumechange"));

  function fullscreen() {
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    else if (el.requestFullscreen) el.requestFullscreen().catch(() => {});
    else if (video.webkitEnterFullscreen) video.webkitEnterFullscreen();
  }
  document.addEventListener("fullscreenchange", () => {
    const on = !!document.fullscreenElement;
    $('[data-act="full"] use', el).setAttribute("href", on ? "#i-unfull" : "#i-full");
    $('[data-act="full"]', el).setAttribute("aria-label", on ? "Exit full screen" : "Full screen");
  });

  el.addEventListener("click", e => {
    const b = e.target.closest("[data-act]"); if (!b) return;
    const a = b.dataset.act;
    if (a === "close") requestClose();
    else if (a === "toggle") toggle();
    else if (a === "rew") seekBy(-10);
    else if (a === "fwd") seekBy(30);
    else if (a === "mute") video.muted = !video.muted;
    else if (a === "next") { if (el.classList.contains("is-live")) zap(1); else playNext(); }
    else if (a === "cancel-next") { nextHidden = true; nextCard.hidden = true; delete nextCard.dataset.credits; toggleBtn.focus({ preventScroll: true }); }
    else if (a === "skip") { seekTo(+skipBtn.dataset.to); skipBtn.hidden = true; toggleBtn.focus({ preventScroll: true }); }
    else if (a === "opts") { if (optsBox.hidden) optsOpen(); else optsBox.hidden = true; }
    else if (a === "still-yes") { autoNexts = 0; stillBox.hidden = true; video.play().catch(() => {}); }
    else if (a === "restart") { seekTo(0); chip.hidden = true; }
    else if (a === "full") fullscreen();
    else if (a === "ambient") setAmbient(!el.classList.contains("ambient"));
    else if (a === "cc") { if (ccMenu.hidden) ccMenuOpen(); else ccMenu.hidden = true; }
    else if (a === "eps") { if (epsPanel.hidden) epsOpen(); else epsPanel.hidden = true; }
    else if (a === "pip") togglePip();
    else if (a === "help") helpToggle();
    else if (a === "retry") { const it = item; errorBox.hidden = true; hlsSession = null; video.removeAttribute("src"); open(it); }
    else if (a === "convert") {
      api("/api/admin/convert", { items: [item.id] }).then(r => {
        $(".p-error p", el).textContent = r.queued ? "Queued. Sofa is converting it in the background; watch its progress on the Server page (Converting). It will play directly once done."
          : "It's already queued or converted. See the Server page (Converting).";
        b.remove();
      }).catch(ex => { $(".p-error p", el).textContent = ex.message; });
    }
    else if (a === "speed") {
      const i = (SPEEDS.indexOf(video.playbackRate) + 1) % SPEEDS.length;
      video.playbackRate = SPEEDS[i]; b.textContent = SPEEDS[i] + "×";
    }
  });
  document.addEventListener("keydown", e => {
    if (el.hidden || e.metaKey || e.ctrlKey || e.altKey) return;
    const k = e.key;
    lastInput = Date.now();
    // An open panel (episodes, audio/subtitles, options, shortcuts, "still watching?", an error) keeps the remote inside it.
    const panel = openPanel();
    if (panel && ARROWS[k]) { e.preventDefault(); spatialMove(ARROWS[k], panel, ".now, [aria-checked='true'], .btn.primary, button"); wake(); return; }
    if (panel && (k === "Escape" || k === "Backspace") && panel !== errorBox && panel !== stillBox) { e.preventDefault(); closePanels(); return; }
    if ((k === "s" || k === "S") && !skipBtn.hidden) { e.preventDefault(); skipBtn.click(); return; }
    if (TV && ARROWS[k] && !panel) { e.preventDefault(); remoteArrow(k); return; }
    if (/^[0-9]$/.test(k) && total() && !el.classList.contains("is-live") && !(e.target.closest && e.target.closest("input"))) { e.preventDefault(); seekTo(total() * (+k) / 10); wake(); return; }
    const onButton = e.target.closest && e.target.closest("button") && (k === " " || k === "Enter");
    if (onButton) return;
    const controlsHidden = el.classList.contains("idle");
    const map = {
      " ": toggle, k: toggle, Enter: toggle, MediaPlayPause: toggle,
      ArrowLeft: () => seekBy(-10), j: () => seekBy(-10), ArrowRight: () => seekBy(10), l: () => seekBy(30),
      p: togglePip, e: () => { if (!epsBtn.hidden) { if (epsPanel.hidden) epsOpen(); else epsPanel.hidden = true; } }, "?": helpToggle,
      "<": () => speedBy(-1), ">": () => speedBy(1), ",": () => speedBy(-1), ".": () => speedBy(1),
      MediaRewind: () => seekBy(-10), MediaFastForward: () => seekBy(30),
      ArrowUp: () => { video.volume = Math.min(1, video.volume + 0.1); volume.value = video.volume; },
      ArrowDown: () => { video.volume = Math.max(0, video.volume - 0.1); volume.value = video.volume; },
      f: fullscreen, m: () => { video.muted = !video.muted; }, n: playNext, c: () => { if (plan && !ccBtn.hidden) { if (ccMenu.hidden) ccMenuOpen(); else ccMenu.hidden = true; } },
      PageUp: () => zap(-1), PageDown: () => zap(1), ChannelUp: () => zap(-1), ChannelDown: () => zap(1),
      Escape: () => { if (!document.fullscreenElement) requestClose(); }, Backspace: requestClose, GoBack: requestClose
    };
    if (e.target === volume && /^Arrow/.test(k)) return;
    // With controls showing, arrows move between buttons (TV remotes); hidden, they seek.
    if (!controlsHidden && /^Arrow(Up|Down)$/.test(k) && e.target.closest && e.target.closest(".p-row")) return;
    // Live TV with the controls out of the way: up/down on the remote change channel.
    if (controlsHidden && el.classList.contains("is-live") && /^Arrow(Up|Down)$/.test(k)) { e.preventDefault(); zap(k === "ArrowUp" ? -1 : 1); wake(); return; }
    if (map[k]) { e.preventDefault(); map[k](); wake(); }
  });

  /* The TV remote (Fire TV Silk, Android TV): like Netflix on a TV.
     Controls hidden: left/right skip 10 s, up/down (or OK) bring the controls up on the timeline.
     On the timeline: left/right skip, OK pauses, down goes to the buttons. Live TV: up/down change channel. */
  const panels = () => [stillBox, errorBox, helpBox, optsBox, epsPanel, ccMenu];
  function openPanel() { return panels().find(x => !x.hidden) || null; }
  function closePanels() {
    const back = !epsPanel.hidden ? epsBtn : !ccMenu.hidden ? ccBtn : !optsBox.hidden ? $('[data-act="opts"]', el) : toggleBtn;
    helpBox.hidden = optsBox.hidden = epsPanel.hidden = ccMenu.hidden = true;
    if (back && !back.hidden) back.focus(); else toggleBtn.focus();
    wake();
  }
  function remoteArrow(k) {
    const isLive = el.classList.contains("is-live"), horiz = k === "ArrowLeft" || k === "ArrowRight";
    const hidden = el.classList.contains("idle");
    document.body.classList.add("tv-nav");
    if (hidden) {
      if (isLive && !horiz) { zap(k === "ArrowUp" ? -1 : 1); wake(); return; }
      if (horiz && !isLive) { seekBy(k === "ArrowLeft" ? -10 : 10); wake(); scrub.focus({ preventScroll: true }); return; }
      wake(); (isLive ? toggleBtn : scrub).focus({ preventScroll: true }); return;
    }
    if (document.activeElement === scrub && horiz) { seekBy(k === "ArrowLeft" ? -10 : 10); wake(); return; }
    if (!spatialMove(ARROWS[k], el, isLive ? '[data-act="toggle"]' : ".scrub") && k === "ArrowUp" && document.activeElement !== skipBtn && !skipBtn.hidden) skipBtn.focus();
    wake();
  }
  scrub.addEventListener("keydown", e => {
    if ((e.key === "Enter" || e.key === " ") && !TV) return;
    if (e.key === "Enter") { e.preventDefault(); e.stopPropagation(); toggle(); wake(); }
  });
  window.addEventListener("pagehide", () => {
    save(true);
    if (hlsSession) fetch("/api/hls/stop", { method: "POST", keepalive: true, credentials: "same-origin",
                                             headers: { "Content-Type": "application/json", "X-Sofa": "1" }, body: "{}" }).catch(() => {});
  });
  function speedBy(step) {
    const list = [0.75, 1, 1.25, 1.5, 2], i = Math.max(0, list.indexOf(video.playbackRate));
    video.playbackRate = list[Math.max(0, Math.min(list.length - 1, i + step))];
    $(".speed", el).textContent = video.playbackRate + "×";
    flashSeek(video.playbackRate + "×", "mid");
  }
  let hls = null, liveList_ = null, liveIdx = 0;
  function loadHlsJs() {
    if (window.Hls) return Promise.resolve();
    return new Promise((res, rej) => { const sc = document.createElement("script"); sc.src = "/client/vendor/hls.min.js"; sc.onload = res; sc.onerror = rej; document.head.appendChild(sc); });
  }
  async function openLive(ch, list) {
    if (!ch) return;
    MusicPlayer.pause();
    enterHistory();
    returnFocus = returnFocus || document.activeElement;
    liveList_ = list || [ch]; liveIdx = Math.max(0, liveList_.indexOf(ch));
    item = null; plan = { mode: "live", subtitles: [] }; offset = 0; next = null;
    el.classList.add("is-live");
    errorBox.hidden = chip.hidden = nextCard.hidden = ccMenu.hidden = epsPanel.hidden = helpBox.hidden = pauseInfo.hidden = true;
    ccBtn.hidden = epsBtn.hidden = true; pipBtn.hidden = TV || !document.pictureInPictureEnabled;
    showSpinner("Tuning in…");
    $(".p-show", el).innerHTML = esc(ch.name) + '<span class="live-badge">LIVE</span>';
    $(".p-title", el).textContent = ch.group + (liveList_.length > 1 ? "  (Page Up / Page Down changes channel)" : "");
    $('[data-act="next"]', el).hidden = liveList_.length < 2;
    modeEl.hidden = true;
    el.hidden = false; document.body.style.overflow = "hidden";
    const src = "/live/" + ch.id + "/index.m3u8";
    if (hls) { hls.destroy(); hls = null; }
    if (nativeHls) { video.src = src; }
    else {
      try { await loadHlsJs(); } catch (e) { return showError("Live TV couldn't start", "The video library for live streams didn't load."); }
      if (!window.Hls.isSupported()) { video.src = src; }
      else {
        hls = new window.Hls({ liveDurationInfinity: true });
        hls.on(window.Hls.Events.ERROR, (_, data) => { if (data.fatal) showError(ch.name + " isn't available right now", "Free channels come and go. Try another one, or try this one later."); });
        hls.loadSource(src); hls.attachMedia(video);
      }
    }
    video.play().catch(() => {});
    wake(); toggleBtn.focus();
  }
  function zap(step) {
    if (!liveList_ || liveList_.length < 2) return;
    liveIdx = (liveIdx + step + liveList_.length) % liveList_.length;
    openLive(liveList_[liveIdx], liveList_);
  }
  window.SofaVideoOpen = () => !el.hidden;
  window.addEventListener("popstate", () => {
    const scrim = document.querySelector(".dialog-scrim");
    if (scrim) { scrim.remove(); return; }
    if (el.hidden) return;
    const panel = openPanel();
    if (panel && panel !== errorBox && panel !== stillBox) {        // Back closes the panel and keeps watching
      closePanels(); history.pushState({ sofaLayer: "player" }, ""); return;
    }
    close();
  });
  const capsQuery = () => Object.keys(caps).map(k => k + "=" + (typeof caps[k] === "number" ? caps[k] : caps[k] ? 1 : 0)).join("&");
  /* Inside the Fire TV app: Android's own player plays it (the file as it is, mostly), and says where it
     stopped when it's closed (window.sofaNativeDone). */
  let nativeItem = null, nativeQueue = null;
  async function nativeOpen(it, queue) {
    let p;
    try { p = await api("/api/play/" + encodeURIComponent(it.id) + "?" + capsQuery()); } catch (e) { toast(e.message); return; }
    let url = p.url;
    const pr = prog(it.id), start = pr && !pr.done && pr.t > 30 && (!p.duration || pr.t < p.duration - 30) ? pr.t : 0;
    if (p.mode !== "direct") {        // converted from where they left off: the app adds `offset` to what it plays
      const h = prefs.get("quality", "") || p.max_height || "";
      try { url = (await api("/api/hls/" + encodeURIComponent(it.id) + "?mode=" + p.mode + "&t=" + start.toFixed(1) + (h ? "&h=" + h : "") + "&" + capsQuery())).url; }
      catch (e) { toast(e.message); return; }
    }
    nativeItem = it; nativeQueue = queue && queue.includes(it) ? queue : null;
    const owner = it.show || it;
    const shift = p.mode === "direct" ? 0 : start;
    NATIVE.play(JSON.stringify({ item: it.id, url: location.origin + url, start: start - shift, offset: shift, duration: p.duration || 0,
      title: owner.name || it.title, sub: it.kind === "episode" ? subtitleFor(it) : "", adult: !!(it.adult || owner.adult),
      subtitles: p.subtitles.map(t => ({ url: location.origin + t.url + (shift ? "?offset=" + shift.toFixed(2) : ""), lang: t.lang, label: t.label })),
      markers: p.markers || [] }));
  }
  window.sofaNativeDone = r => {
    const it = nativeItem; nativeItem = null;
    if (!it) return;
    if (r && r.d) progress[it.id] = { t: r.done ? r.d : r.t, d: r.d, done: !!r.done, at: Date.now() };
    const next = nativeQueue ? nativeQueue[nativeQueue.indexOf(it) + 1] : nextAfter(it);
    if (r && r.ended && next && opt("autoplay", true)) return open(next, nativeQueue);
    rerender();
  };
  const nativeStatus = () => nativeItem ? JSON.parse(NATIVE.status() || "{}") : null;
  // For the phone remote: what's playing, and doing what it asks.
  const status = () => nativeItem ? nativeStatus() || {} : item && !el.classList.contains("is-live") ? { item: item.id, t: Math.round(now()), d: Math.round(total()), paused: video.paused && !holding } : {};
  function control(c) {
    if (nativeItem) return NATIVE.control(JSON.stringify(c));
    if (!item || el.classList.contains("is-live")) return;
    if (c.cmd === "toggle") toggle();
    else if (c.cmd === "pause") userPause();
    else if (c.cmd === "resume") { if (holding) endHold(true); else video.play().catch(() => {}); }
    else if (c.cmd === "seek" && c.t != null) seekTo(+c.t);
    else if (c.cmd === "skip" && c.by) seekBy(+c.by);
    else if (c.cmd === "next") playNext();
    else if (c.cmd === "stop") requestClose();
    wake();
  }
  return { open, openLive, zap, capsQuery, status, control, isLive: () => el.classList.contains("is-live"), isOpen: () => !el.hidden };
})();

/* ---------- music ---------- */
let MUSIC = null;
const mById = new Map();
let likes = new Set(), recent = [];
let musicTab = prefs.get("musicTab", "home");
async function loadMusic() {
  try {
    MUSIC = await api("/api/music");
  } catch (e) { MUSIC = { tracks: [], albums: [], artists: [], videos: [], likes: [], recent: [], error: e.message }; }
  mById.clear();
  MUSIC.tracks.forEach(t => { t.kind = "track"; mById.set(t.id, t); });
  MUSIC.albums.forEach(a => mById.set(a.id, a));
  MUSIC.artists.forEach(a => mById.set(a.id, a));
  MUSIC.videos.forEach(v => { v.kind = "musicvideo"; mById.set(v.id, v); });
  likes = new Set(MUSIC.likes || []); recent = MUSIC.recent || [];
  if (location.hash.startsWith("#/music")) rerender();
}
const durText = s => s ? clock(s) : "";
function squareCard(kind, o) {
  const round = kind === "artist";
  const href = "#/music/" + kind + "/" + encodeURIComponent(o.id);
  const sub = kind === "album" ? (o.title === "Singles" ? "Singles" : o.artist + (o.year ? ", " + o.year : ""))
    : plural(o.tracks, "song");
  return `<a class="card sq${round ? " round" : ""}" href="${href}">
    <span class="frame${o.art ? "" : " noimg"}">${frameImg(o.art, "", kind === "album" ? o.title : o.name)}</span>
    <span class="t1">${esc(kind === "album" ? (o.title === "Singles" ? o.artist : o.title) : o.name)}</span>
    <span class="t2">${esc(sub)}</span></a>`;
}
function videoCard(v) {
  return `<button class="card wide" data-play-mv="${esc(v.id)}">
    <span class="frame">${frameImg(v.thumb, "", v.title, 480)}<span class="play-glyph">${icon("i-play")}</span></span>
    <span class="t1">${esc(v.title)}</span><span class="t2">${esc(v.artist)}${v.duration ? ", " + durText(v.duration) : ""}</span></button>`;
}
function trackRows(list, opts) {
  opts = opts || {};
  const cur = MusicPlayer.currentId();
  return `<ol class="tracks" data-list="${esc(list.map(t => t.id).join(","))}">${list.map((t, i) => `
    <li class="track${t.id === cur ? " playing" : ""}" data-mplay="${esc(t.id)}" data-idx="${i}" tabindex="0">
      <span class="num">${opts.numbers ? (t.n || i + 1) : i + 1}</span>
      <span class="art">${t.art ? `<img src="${esc(artSrc(t.art, 240))}" alt="" loading="lazy">` : ""}</span>
      <span class="name"><b>${esc(t.title)}</b><span>${esc(t.artist)}</span></span>
      <span class="alb">${esc(t.album === "Singles" ? "Single" : t.album)}</span>
      <span class="dur">${esc(durText(t.duration))}</span>
      <button class="heart" data-mlike="${esc(t.id)}" aria-pressed="${likes.has(t.id)}" aria-label="${likes.has(t.id) ? "Unlike" : "Like"} ${esc(t.title)}">♥</button>
    </li>`).join("")}</ol>`;
}
function stations() {
  const count = (key) => {
    const m = new Map();
    MUSIC.tracks.forEach(t => { const v = t[key]; if (v) m.set(v, (m.get(v) || 0) + 1); });
    return [...m.entries()].filter(([, n]) => n >= 3).sort((a, b) => b[1] - a[1]).slice(0, 8);
  };
  const cap = s => s.charAt(0).toUpperCase() + s.slice(1);
  return [`<button class="station" data-station="all">Shuffle everything <small>${MUSIC.tracks.length}</small></button>`]
    .concat(likes.size ? [`<button class="station" data-station="liked">Your likes <small>${likes.size}</small></button>`] : [])
    .concat(count("genre").map(([g, n]) => `<button class="station" data-station="genre:${esc(g)}">${esc(cap(g))} <small>${n}</small></button>`))
    .concat(count("mood").map(([m, n]) => `<button class="station" data-station="mood:${esc(m)}">${esc(cap(m))} <small>${n}</small></button>`))
    .join("");
}
function startStation(key) {
  let pool = MUSIC.tracks.slice();
  let name = "Shuffle everything";
  if (key === "liked") { pool = pool.filter(t => likes.has(t.id)); name = "Your likes"; }
  else if (key.startsWith("genre:")) { const g = key.slice(6); pool = pool.filter(t => t.genre === g); name = g; }
  else if (key.startsWith("mood:")) { const m = key.slice(5); pool = pool.filter(t => t.mood === m); name = m; }
  // Liked songs come up a little sooner (Edge Music's station weighting, simplified).
  const scored = pool.map(t => ({ t, r: Math.random() + (likes.has(t.id) ? 0.35 : 0) })).sort((a, b) => b.r - a.r).map(x => x.t);
  MusicPlayer.play(scored.map(t => t.id), 0, name + " station");
}
function viewMusic(rest) {
  setGlow("");
  if (!MUSIC) { loadMusic(); return `<section class="page"><div class="page-head"><h1>Music</h1></div><p class="count">Loading…</p></section>`; }
  const [sub, id] = [rest[0], rest.slice(1).join("/")];
  if (sub === "album") return viewAlbum(mById.get(id));
  if (sub === "artist") return viewArtist(mById.get(id));
  if (sub) musicTab = sub;
  prefs.set("musicTab", musicTab);
  const tabs = [["home", "For you"], ["albums", "Albums"], ["artists", "Artists"], ["songs", "Songs"], ["videos", "Videos"], ["liked", "Liked"]];
  const head = `<div class="page-head"><h1>Music</h1><span class="count">${plural(MUSIC.tracks.length, "song")}, ${plural(MUSIC.videos.length, "video")}</span></div>
    <div class="chips music-tabs" role="tablist">${tabs.map(([k, l]) => `<button role="tab" data-mtab="${k}" aria-pressed="${k === musicTab}">${l}</button>`).join("")}</div>`;
  if (!MUSIC.tracks.length && !MUSIC.videos.length) {
    return `<section class="page">${head}<p class="count" style="max-width:60ch">No music yet. Drop songs into the Inbox (or <b>Inbox/Music</b>) and music videos into <b>Inbox/Music Videos</b>.</p></section>`;
  }
  let body = "";
  const albumsReal = MUSIC.albums.filter(a => a.title !== "Singles");
  if (musicTab === "albums") body = `<div class="squares">${MUSIC.albums.map(a => squareCard("album", a)).join("")}</div>`;
  else if (musicTab === "artists") body = `<div class="squares">${MUSIC.artists.map(a => squareCard("artist", a)).join("")}</div>`;
  else if (musicTab === "songs") body = `<div class="actions" style="margin-bottom:14px"><button class="btn primary" data-mplay-list="all">${icon("i-play")}Play all</button><button class="btn" data-station="all">${icon("i-shuffle")}Shuffle</button></div></section>` + trackRows(MUSIC.tracks) + "<section>";
  else if (musicTab === "videos") body = `<div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(280px,1fr))">${MUSIC.videos.map(videoCard).join("")}</div>`;
  else if (musicTab === "liked") {
    const liked = [...likes].map(id => mById.get(id)).filter(Boolean);
    body = liked.length ? `<div class="actions" style="margin-bottom:14px"><button class="btn primary" data-station="liked">${icon("i-play")}Play your likes</button></div></section>` + trackRows(liked) + "<section>"
      : `<p class="count">Tap ♥ on a song to keep it here.</p>`;
  } else {
    const rec = recent.map(id => mById.get(id)).filter(Boolean).slice(0, 14);
    const newest = MUSIC.albums.slice().sort((a, b) => b.added - a.added).slice(0, 12);
    body = `<div class="station-row">${stations()}</div></section>` +
      rail("Played recently", "squares-rail", rec.map(t => `<button class="card sq" data-mplay-one="${esc(t.id)}"><span class="frame${t.art ? "" : " noimg"}">${frameImg(t.art, "", t.title)}<span class="play-glyph">${icon("i-play")}</span></span><span class="t1">${esc(t.title)}</span><span class="t2">${esc(t.artist)}</span></button>`)) +
      rail("Albums", "squares-rail", albumsReal.map(a => squareCard("album", a)), "#/music/albums") +
      rail("Artists", "squares-rail", MUSIC.artists.map(a => squareCard("artist", a)), "#/music/artists") +
      rail("Music videos", "wide", MUSIC.videos.map(videoCard), "#/music/videos") +
      rail("New", "squares-rail", newest.map(a => squareCard("album", a))) + "<section>";
  }
  return `<section class="page">${head}${body}</section>`;
}
function viewAlbum(a) {
  if (!a || !a.tracks) return viewMissing();
  const list = a.tracks.map(id => mById.get(id)).filter(Boolean);
  const total = list.reduce((s, t) => s + (t.duration || 0), 0);
  setGlow(a.art);
  return `<section class="album-head"><div class="cover">${a.art ? `<img src="${esc(artSrc(a.art, 720))}" alt="">` : ""}</div>
    <div><p class="kind">${a.title === "Singles" ? "Singles" : list.length <= 3 ? "EP" : "Album"}</p>
    <h1>${esc(a.title === "Singles" ? a.artist : a.title)}</h1>
    <p class="facts"><a href="#/music/artist/${encodeURIComponent(a.artist_id)}">${esc(a.artist)}</a>${a.year ? `<span>${a.year}</span>` : ""}<span>${plural(list.length, "song")}, ${Math.round(total / 60)} min</span></p>
    <div class="actions"><button class="btn primary" data-mplay-list="${esc(a.id)}">${icon("i-play")}Play</button>
      <button class="btn" data-mshuffle-list="${esc(a.id)}">${icon("i-shuffle")}Shuffle</button></div></div></section>
    <div style="margin-top:20px">${trackRows(list, { numbers: true })}</div>`;
}
function viewArtist(ar) {
  if (!ar || ar.tracks === undefined) return viewMissing();
  const albums = MUSIC.albums.filter(a => a.artist_id === ar.id);
  const list = MUSIC.tracks.filter(t => t.artist_id === ar.id);
  const vids = MUSIC.videos.filter(v => v.artist_id === ar.id);
  setGlow(ar.art);
  return `<section class="album-head"><div class="cover round">${ar.art ? `<img src="${esc(artSrc(ar.art, 720))}" alt="">` : ""}</div>
    <div><p class="kind">Artist</p><h1>${esc(ar.name)}</h1>
    <p class="facts"><span>${plural(list.length, "song")}</span>${vids.length ? `<span>${plural(vids.length, "video")}</span>` : ""}</p>
    <div class="actions"><button class="btn primary" data-mplay-list="${esc(ar.id)}">${icon("i-play")}Play</button>
      <button class="btn" data-mshuffle-list="${esc(ar.id)}">${icon("i-shuffle")}Shuffle</button></div></div></section>
    ${rail("Albums", "squares-rail", albums.map(a => squareCard("album", a)))}
    ${vids.length ? rail("Videos", "wide", vids.map(videoCard)) : ""}
    <section class="row"><div class="row-head"><h2>Songs</h2></div></section>${trackRows(list)}`;
}
function listFor(id) {
  if (id === "all") return MUSIC.tracks.map(t => t.id);
  const o = mById.get(id);
  if (!o) return [];
  if (o.tracks && Array.isArray(o.tracks)) return o.tracks.slice();
  return MUSIC.tracks.filter(t => t.artist_id === id).map(t => t.id);
}
function setLike(id, on) {
  if (on) likes.add(id); else likes.delete(id);
  api("/api/music/like/" + encodeURIComponent(id), { on }).catch(() => {});
  document.querySelectorAll(`[data-mlike="${CSS.escape(id)}"], .mbar [data-m="like"]`).forEach(b => {
    if (b.dataset.mlike === id || (b.dataset.m === "like" && MusicPlayer.currentId() === id)) b.setAttribute("aria-pressed", on);
  });
}

const MusicPlayer = (function () {
  const audio = $("#music"), bar = $("#mbar"), qpanel = $("#qpanel"), sleepMenu = $("#sleepMenu");
  const seek = $(".line input", bar), cur = $(".cur", bar), dur = $(".dur", bar), vol = $('[data-m="volume"]', bar);
  let queue = [], idx = -1, order = [], shuffle = prefs.get("mShuffle", false), repeat = prefs.get("mRepeat", "off");
  let label = "", sleepAt = 0, sleepEnd = false, sleepTimer = 0, seeking = false;
  audio.volume = prefs.get("mVolume", 1); vol.value = audio.volume;

  const current = () => (idx >= 0 ? mById.get(queue[order[idx]]) : null);
  function buildOrder(startPos) {
    order = queue.map((_, i) => i);
    if (shuffle) {
      const first = order.splice(startPos, 1)[0];
      for (let i = order.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [order[i], order[j]] = [order[j], order[i]]; }
      order.unshift(first);
      return 0;
    }
    return startPos;
  }
  async function load(autoplay) {
    const t = current();
    if (!t) return;
    let url = "/media/" + encodeURIComponent(t.id) + "/file";
    try { const p = await api("/api/play/" + encodeURIComponent(t.id)); url = p.url; } catch (e) {}
    audio.src = url;
    if (autoplay) audio.play().catch(() => {});
    api("/api/music/played/" + encodeURIComponent(t.id), {}).catch(() => {});
    recent = [t.id].concat(recent.filter(x => x !== t.id)).slice(0, 60);
    paintNow(); save();
    if ("mediaSession" in navigator) {
      navigator.mediaSession.metadata = new MediaMetadata({ title: t.title, artist: t.artist, album: t.album === "Singles" ? "" : t.album,
        artwork: t.art ? [{ src: location.origin + artSrc(t.art, 720), sizes: "512x512", type: "image/jpeg" }] : [] });
    }
  }
  function play(ids, start, name) {
    if (!ids.length) return;
    if (window.SofaVideoOpen && window.SofaVideoOpen()) return;
    queue = ids.slice(); label = name || ""; idx = buildOrder(Math.max(0, start || 0));
    bar.hidden = false; document.body.classList.add("has-bar");
    load(true);
  }
  function step(n, auto) {
    if (!queue.length) return;
    if (auto && repeat === "one") { audio.currentTime = 0; audio.play().catch(() => {}); return; }
    if (sleepEnd && auto) { stopSleep(); audio.pause(); return; }
    let next = idx + n;
    if (next >= order.length) { if (repeat === "all" || !auto) next = 0; else { audio.pause(); return; } }
    if (next < 0) next = 0;
    if (n < 0 && audio.currentTime > 4) { audio.currentTime = 0; return; }
    idx = next; load(true);
  }
  function paintNow() {
    const t = current();
    if (!t) return;
    $(".now .art", bar).innerHTML = t.art ? `<img src="${esc(artSrc(t.art, 240))}" alt="">` : "";
    $(".now b", bar).textContent = t.title;
    $(".now div span", bar).textContent = t.artist + (label ? ", " + label : "");
    $('[data-m="like"]', bar).setAttribute("aria-pressed", likes.has(t.id));
    $('[data-m="shuffle"]', bar).setAttribute("aria-pressed", shuffle);
    $('[data-m="repeat"]', bar).setAttribute("aria-pressed", repeat !== "off");
    $('[data-m="repeat"]', bar).setAttribute("aria-label", repeat === "one" ? "Repeat this song" : repeat === "all" ? "Repeat all" : "Repeat off");
    document.querySelectorAll(".track").forEach(r => r.classList.toggle("playing", r.dataset.mplay === t.id));
    if (!qpanel.hidden) paintQueue();
  }
  function paintPlay() {
    $('[data-m="toggle"] use', bar).setAttribute("href", audio.paused ? "#i-play" : "#i-pause");
    $('[data-m="toggle"]', bar).setAttribute("aria-label", audio.paused ? "Play" : "Pause");
    if ("mediaSession" in navigator) navigator.mediaSession.playbackState = audio.paused ? "paused" : "playing";
  }
  function paintQueue() {
    const upcoming = order.slice(idx).map(i => mById.get(queue[i])).filter(Boolean);
    qpanel.innerHTML = `<h3>Up next${label ? ": " + esc(label) : ""}</h3>` + (upcoming.length
      ? upcoming.map((t, k) => `<div class="track${k === 0 ? " playing" : ""}" data-qjump="${idx + k}"><span class="art">${t.art ? `<img src="${esc(artSrc(t.art, 240))}" alt="" loading="lazy">` : ""}</span>
        <span class="name"><b>${esc(t.title)}</b><span>${esc(t.artist)}</span></span><span class="dur">${esc(durText(t.duration))}</span></div>`).join("")
      : `<p class="count">Nothing queued.</p>`);
  }
  function save() { prefs.set("mState", { queue, idx, order, label, t: audio.currentTime || 0 }); }
  function restore() {
    const s = prefs.get("mState", null);
    if (!s || !s.queue || !s.queue.length || !MUSIC) return;
    queue = s.queue.filter(id => mById.has(id));
    if (!queue.length) return;
    order = s.order && s.order.length === s.queue.length ? s.order : queue.map((_, i) => i);
    idx = Math.min(s.idx, order.length - 1); label = s.label || "";
    bar.hidden = false; document.body.classList.add("has-bar");
    load(false).then(() => { audio.addEventListener("loadedmetadata", () => { if (s.t) audio.currentTime = s.t; }, { once: true }); });
  }
  function stopSleep() { clearTimeout(sleepTimer); sleepAt = 0; sleepEnd = false; $('[data-m="sleep"]', bar).innerHTML = icon("i-moon"); }
  function setSleep(min) {
    stopSleep();
    if (min === "end") { sleepEnd = true; $('[data-m="sleep"]', bar).textContent = "End of song"; return; }
    if (!min) return;
    sleepAt = Date.now() + min * 60000;
    sleepTimer = setTimeout(() => { audio.pause(); stopSleep(); }, min * 60000);
    $('[data-m="sleep"]', bar).textContent = min + " min";
  }

  audio.addEventListener("timeupdate", () => {
    if (!seeking && audio.duration) seek.value = Math.round((audio.currentTime / audio.duration) * 1000);
    cur.textContent = clock(audio.currentTime); dur.textContent = clock(audio.duration || (current() || {}).duration || 0);
    if ("mediaSession" in navigator && audio.duration && navigator.mediaSession.setPositionState) {
      try { navigator.mediaSession.setPositionState({ duration: audio.duration, position: audio.currentTime, playbackRate: 1 }); } catch (e) {}
    }
    if (Math.floor(audio.currentTime) % 10 === 0) save();
  });
  audio.addEventListener("play", paintPlay);
  audio.addEventListener("pause", () => { paintPlay(); save(); });
  audio.addEventListener("ended", () => step(1, true));
  audio.addEventListener("error", () => { if (audio.getAttribute("src")) setTimeout(() => step(1, true), 1500); });
  seek.addEventListener("input", () => { seeking = true; });
  seek.addEventListener("change", () => { if (audio.duration) audio.currentTime = (seek.value / 1000) * audio.duration; seeking = false; });
  vol.addEventListener("input", () => { audio.volume = +vol.value; audio.muted = false; prefs.set("mVolume", audio.volume); });
  if ("mediaSession" in navigator) {
    const h = (a, f) => { try { navigator.mediaSession.setActionHandler(a, f); } catch (e) {} };
    h("play", () => audio.play()); h("pause", () => audio.pause());
    h("previoustrack", () => step(-1)); h("nexttrack", () => step(1));
    h("seekto", d => { if (d.seekTime != null) audio.currentTime = d.seekTime; });
  }
  bar.addEventListener("click", e => {
    const b = e.target.closest("[data-m]"); if (!b) return;
    const a = b.dataset.m;
    if (a === "toggle") { if (audio.paused) audio.play().catch(() => {}); else audio.pause(); }
    else if (a === "next") step(1);
    else if (a === "prev") step(-1);
    else if (a === "shuffle") {
      shuffle = !shuffle; prefs.set("mShuffle", shuffle);
      const playing = order[idx]; idx = shuffle ? buildOrder(playing) : playing;
      if (!shuffle) order = queue.map((_, i) => i);
      paintNow();
    }
    else if (a === "repeat") { repeat = { off: "all", all: "one", one: "off" }[repeat]; prefs.set("mRepeat", repeat); paintNow(); }
    else if (a === "like") { const t = current(); if (t) setLike(t.id, !likes.has(t.id)); }
    else if (a === "queue") { sleepMenu.hidden = true; qpanel.hidden = !qpanel.hidden; if (!qpanel.hidden) paintQueue(); }
    else if (a === "mute") { audio.muted = !audio.muted; $("use", b).setAttribute("href", audio.muted ? "#i-mute" : "#i-vol"); }
    else if (a === "sleep") {
      qpanel.hidden = true;
      sleepMenu.innerHTML = [[0, sleepAt || sleepEnd ? "Turn off sleep timer" : "No sleep timer"], [15, "In 15 minutes"], [30, "In 30 minutes"], [60, "In 1 hour"], ["end", "At the end of this song"]]
        .map(([v, l]) => `<button data-sleep="${v}">${l}</button>`).join("");
      sleepMenu.hidden = !sleepMenu.hidden;
    }
  });
  qpanel.addEventListener("click", e => { const r = e.target.closest("[data-qjump]"); if (r) { idx = +r.dataset.qjump; load(true); } });
  sleepMenu.addEventListener("click", e => { const b = e.target.closest("[data-sleep]"); if (!b) return; const v = b.dataset.sleep; setSleep(v === "end" ? "end" : +v); sleepMenu.hidden = true; });
  return { play, restore, currentId: () => (current() || {}).id || null, pause: () => audio.pause() };
})();

/* ---------- boot ---------- */
async function reloadLibrary() {
  const [lib, prog] = await Promise.all([api("/api/library"), api("/api/progress")]);
  progress = prog; indexLibrary(lib);
  $("#foot").innerHTML = esc(lib.reading ? "Reading the library... " : "Library updated " + new Date(lib.generated * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) + ". New files in the Inbox show up on their own. ")
    + `<a href="?tv=${TV ? 0 : 1}" class="link-btn">${TV ? "Turn off TV mode on this device" : "Use TV mode on this device"}</a>`
    + `<span class="credit">Sofa ${esc(session.version || "")} · Project by <a href="https://edgeventure.uk" target="_blank" rel="noopener">EdgeVenture.uk</a></span>`;
}
let refreshing = 0;
async function boot() {
  try { session = await api("/api/session"); }
  catch (e) { view.innerHTML = `<section class="empty"><h1>Can't reach the server</h1><p>${esc(e.message)}</p></section>`; return; }
  document.title = session.name;
  $("#brandName").textContent = session.name;
  if (session.needs_setup) return authView("setup");
  if (!session.user) return authView("login");
  $("#nav").hidden = $("#searchBox").hidden = $("#searchBtn").hidden = $("#who").hidden = false;
  $("#navServer").hidden = !session.user.admin;
  $("#navAdult").hidden = !session.user.adult;
  $('[data-nav="live"]').hidden = !!session.user.kids;
  applyLook();
  $("#whoName").textContent = session.user.name;
  $("#whoAv").outerHTML = avatar(session.user, "whoAv");
  $("#whoBtn").disabled = false;           // the menu also has Theme, Pair a TV and Sign out (all a phone has)
  $("#signOut").textContent = session.user.guest ? "Leave" : "Sign out";
  view.innerHTML = "";
  await reloadLibrary();
  route();
  Screens.start();
  setTimeout(installOffer, 3500);
  if (FIRE_TV && NATIVE) api("/api/apps").then(a => { appsInfo = a; if (!location.hash || location.hash === "#/") rerender(); }).catch(() => {});
  // On a TV, Sofa asks who's watching each time it's opened (when there's more than one profile).
  if (TV && session.profiles > 1 && !sessionStorage.getItem("sofaPicked")) setTimeout(() => profilePicker(true), 400);
  // Sofa just started and is still reading the library: look again every few seconds until it's done.
  const waitForLibrary = () => LIB.reading && setTimeout(async () => {
    try { await reloadLibrary(); if (!LIB.reading && !Player.isOpen()) rerender(); } catch (e) {}
    waitForLibrary();
  }, 3000);
  waitForLibrary();
  loadMusic().then(() => MusicPlayer.restore());
  // Pick up new episodes while the page stays open.
  if (!refreshing) refreshing = setInterval(async () => {
    if (Player.isOpen()) return;
    try { const lib = await api("/api/library?since=" + LIB.generated); if (!lib.same && lib.generated !== LIB.generated) { indexLibrary(lib); rerender(); } } catch (e) {}
  }, 60000);
}
/* ---------- game controllers (Xbox, PlayStation, 8BitDo…) ----------
   For the Sofa box (a Raspberry Pi on the TV) or any computer: the D-pad or left stick moves like a TV
   remote's arrows, A is OK, B (or View/Select) is Back, X or Start (☰) plays and pauses, LB/LT skip 10 s
   back and RB/RT 30 s on, Y is search (or subtitles while playing). */
(function gamepads() {
  if (!navigator.getGamepads || window.SofaBox) return;      // the Sofa box turns controllers into keys itself
  const DIRS = { 12: "ArrowUp", 13: "ArrowDown", 14: "ArrowLeft", 15: "ArrowRight" };
  let running = false, was = {}, repeatAt = {};
  const key = k => {
    const a = document.activeElement, ev = new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true });
    (a && a !== document.body ? a : document).dispatchEvent(ev);
    return ev.defaultPrevented;
  };
  function ok() {
    const a = document.activeElement;
    if (!key("Enter") && a && a !== document.body && a.click) a.click();   // nothing took it: press what's focused
  }
  function back() {
    if (Player.isOpen()) key("Backspace");      // closes a panel first, then the player (Escape is for leaving full screen)
    else if (document.querySelector(".dialog-scrim")) closeDialog();
    else history.back();
  }
  const playing = () => Player.isOpen();
  const press = {
    0: ok, 1: back, 8: back,
    2: () => playing() && Player.control({ cmd: "toggle" }), 9: () => playing() && Player.control({ cmd: "toggle" }),
    4: () => playing() && Player.control({ cmd: "skip", by: -10 }), 6: () => playing() && Player.control({ cmd: "skip", by: -10 }),
    5: () => playing() && Player.control({ cmd: "skip", by: 30 }), 7: () => playing() && Player.control({ cmd: "skip", by: 30 }),
    3: () => { if (playing()) key("c"); else { const q = $("#q"); if (q) { q.focus(); q.select && q.select(); } } }
  };
  function held(pad) {           // which of our buttons are down right now (the stick counts as the D-pad)
    const down = new Set();
    pad.buttons.forEach((b, i) => { if (b && (b.pressed || b.value > 0.6)) down.add(i); });
    const [x = 0, y = 0] = pad.axes;
    if (y < -0.6) down.add(12); if (y > 0.6) down.add(13); if (x < -0.6) down.add(14); if (x > 0.6) down.add(15);
    return down;
  }
  function tick() {
    const pads = [...navigator.getGamepads()].filter(Boolean);
    if (!pads.length) { running = false; return; }
    const now = performance.now(), down = new Set();
    pads.forEach(p => held(p).forEach(i => down.add(i)));
    down.forEach(i => {
      if (DIRS[i]) {             // arrows repeat while held, like a remote
        if (!was[i]) { key(DIRS[i]); repeatAt[i] = now + 420; }
        else if (now >= repeatAt[i]) { key(DIRS[i]); repeatAt[i] = now + 130; }
      } else if (!was[i] && press[i]) press[i]();
    });
    was = {}; down.forEach(i => { was[i] = true; });
    requestAnimationFrame(tick);
  }
  const start = () => { if (!running) { running = true; document.body.classList.add("tv-nav"); requestAnimationFrame(tick); } };
  window.addEventListener("gamepadconnected", start);
  if ([...navigator.getGamepads()].some(Boolean)) start();
})();
function hideSplash() {
  const sp = $("#splash"); if (!sp) return;
  const wait = sp.classList.contains("quick") ? 0 : Math.max(0, 1300 - performance.now());   // Quick: as soon as Sofa's ready
  setTimeout(() => { sp.classList.add("gone"); setTimeout(() => sp.remove(), 800); }, wait);
}
boot().finally(hideSplash);
})();
