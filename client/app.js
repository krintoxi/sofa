/* Sofa web client: library, player and server admin. Talks to the Sofa server's JSON API. */
(function () {
"use strict";

const $ = (s, el) => (el || document).querySelector(s);
const view = $("#view");

/* ---------- small helpers ---------- */
const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const artSrc = p => p ? p.split("/").map((s, i) => i < 3 ? s : encodeURIComponent(s)).join("/") : "";
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
const epCode = ep => ep.s == null ? "Extra" : (ep.s === 0 ? "Special " : "S" + ep.s + " ") + "E" + ep.e + (ep.e2 ? "–" + ep.e2 : "");

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

let session = null, LIB = { shows: [], movies: [] }, progress = {};
const byId = new Map();
let shows = [], movies = [];

/* ---------- index the library ---------- */
function indexLibrary(lib) {
  LIB = lib; shows = lib.shows; movies = lib.movies; byId.clear();
  shows.forEach(show => {
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
  movies.forEach(m => byId.set(m.id, m));
}

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
const title = item => item.title || (item.kind === "episode" ? "Episode " + item.e : "Untitled");
function subtitleFor(item) {
  if (item.kind === "episode") return epCode(item) + ", " + title(item);
  if (item.kind === "extra") return title(item);
  return [item.year, item.collection].filter(Boolean).join(", ");
}

/* ---------- ambient room light ---------- */
let glowFront = $("#glowA"), glowBack = $("#glowB"), glowSrc = "";
function setGlow(path) {
  const s = artSrc(path);
  if (s === glowSrc) return;
  glowSrc = s;
  if (!s) { glowFront.classList.remove("on"); return; }
  const next = glowBack;
  next.onload = () => { next.classList.add("on"); glowFront.classList.remove("on"); glowBack = glowFront; glowFront = next; };
  next.src = s;
}

/* ---------- markup builders ---------- */
function frameImg(path, alt, fallbackText) {
  return (path ? `<img src="${esc(artSrc(path))}" alt="${esc(alt || "")}" loading="lazy" decoding="async">` : "") +
    `<span class="placeholder">${esc(fallbackText || "")}</span>`;
}
function posterCard(show) {
  return `<a class="card poster" href="#/show/${encodeURIComponent(show.id)}">
    <span class="frame${show.poster ? "" : " noimg"}">${frameImg(show.poster, show.name, show.name)}</span>
    <span class="t1">${esc(show.name)}</span>
    <span class="t2">${plural(show.regularSeasons, "season")}, ${plural(show.count, "episode")}</span></a>`;
}
function movieCard(m) {
  return `<button class="card poster" data-play="${esc(m.id)}">
    <span class="frame${m.poster ? "" : " noimg"}">${frameImg(m.poster, m.title, m.title)}
      ${pct(m.id) && !isDone(m.id) ? `<span class="progress"><i style="width:${pct(m.id)}%"></i></span>` : ""}
      ${isDone(m.id) ? `<span class="seen-badge">${icon("i-check")}</span>` : ""}</span>
    <span class="t1">${esc(m.title)}</span>
    <span class="t2">${esc(m.year || "")}</span></button>`;
}
function thumbFor(item) {
  const owner = item.show || item;
  if (item.thumb) return frameImg(item.thumb, title(item), "");
  const art = owner.backdrop || owner.poster;
  return (art ? `<img class="bg-art" src="${esc(artSrc(art))}" alt="" loading="lazy" decoding="async">` : "") +
    `<span class="bg-num">${esc(item.kind === "episode" ? epCode(item) : item.kind === "movie" ? "" : "Extra")}</span>`;
}
function wideCard(item, label) {
  const owner = item.show || item;
  return `<button class="card wide" data-play="${esc(item.id)}">
    <span class="frame">${thumbFor(item)}
      ${pct(item.id) && !isDone(item.id) ? `<span class="progress"><i style="width:${pct(item.id)}%"></i></span>` : ""}
      <span class="play-glyph">${icon("i-play")}</span></span>
    <span class="t1">${esc(owner.name || owner.title)}</span>
    <span class="t2">${esc(label || subtitleFor(item))}</span></button>`;
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
    show.rating ? `<span>Rated <b>${esc(show.rating)}</b> on TVmaze</span>` : ""
  ].join("");
  let action = "";
  if (nx) {
    const verb = nx.resume ? "Resume" : nx.fresh ? "Play" : "Play next";
    action = `<button class="btn primary" data-play="${esc(nx.ep.id)}">${icon("i-play")}${verb} <small>${esc(epCode(nx.ep))}</small></button>`;
  }
  return `<section class="hero${short ? " short" : ""}">
    ${show.backdrop ? `<img class="hero-bg" src="${esc(artSrc(show.backdrop))}" alt="">` : ""}
    <div class="hero-body">
      ${show.logo ? `<img class="hero-logo" src="${esc(artSrc(show.logo))}" alt="${esc(show.name)}">` : `<h1>${esc(show.name)}</h1>`}
      <p class="facts">${facts}</p>
      ${show.summary ? `<p class="summary${short ? "" : " clamp"}">${esc(show.summary)}</p>` : ""}
      <div class="actions">${action}${short ? "" : `<a class="btn" href="#/show/${encodeURIComponent(show.id)}">Episodes</a>`}</div>
    </div></section>`;
}

/* ---------- library views ---------- */
function viewHome() {
  if (!shows.length && !movies.length) return viewEmptyLibrary();
  const recentShow = shows.slice().sort((a, b) => lastTouched(b) - lastTouched(a))[0];
  const featured = recentShow && lastTouched(recentShow) ? recentShow : shows[Math.floor(Date.now() / 864e5) % Math.max(1, shows.length)];
  setGlow(featured && (featured.backdrop || featured.poster));
  const cont = Object.keys(progress).filter(id => byId.has(id) && inProgress(id))
    .sort((a, b) => progress[b].at - progress[a].at).slice(0, 14).map(id => byId.get(id));
  const nextUps = shows.map(s => ({ s, n: upNext(s) }))
    .filter(x => x.n && !x.n.fresh && !x.n.resume).sort((a, b) => lastTouched(b.s) - lastTouched(a.s))
    .map(x => wideCard(x.n.ep));
  const added = shows.flatMap(s => s.order).sort((a, b) => b.added - a.added).slice(0, 14);
  return (featured ? heroFor(featured) : "") +
    rail("Continue watching", "wide", cont.map(i => wideCard(i))) +
    rail("Next up", "wide", nextUps) +
    rail("Shows", "posters", shows.map(posterCard), "#/shows") +
    rail("Movies", "posters", movies.map(movieCard), "#/movies") +
    rail("Recently added", "wide", added.map(i => wideCard(i)));
}
function viewEmptyLibrary() {
  setGlow("");
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
function viewShows() {
  setGlow(shows[0] && shows[0].backdrop);
  const sort = SORTS[prefs.get("sort", "name")] ? prefs.get("sort", "name") : "name";
  const list = shows.slice().sort(SORTS[sort][1]);
  return `<section class="page"><div class="page-head"><h1>Shows</h1><span class="count">${plural(shows.length, "show")}</span>
    <div class="sorter" role="group" aria-label="Sort shows">${Object.keys(SORTS).map(k =>
      `<button data-sort="${k}" aria-pressed="${k === sort}">${SORTS[k][0]}</button>`).join("")}</div></div>
    <div class="grid">${list.map(posterCard).join("")}</div></section>`;
}
function viewMovies() {
  setGlow(movies[0] && (movies[0].backdrop || movies[0].poster));
  const groups = new Map();
  movies.forEach(m => { const k = m.collection || ""; if (!groups.has(k)) groups.set(k, []); groups.get(k).push(m); });
  let html = `<section class="page"><div class="page-head"><h1>Movies</h1><span class="count">${plural(movies.length, "movie")}</span></div>`;
  if (!movies.length) html += `<p class="count">No movies yet. Drop one in the Inbox, named like "Title (1999)".</p>`;
  groups.forEach((list, name) => {
    html += (name ? `<h2 class="collection-title">${esc(name)}</h2>` : "") +
      `<div class="grid">${list.sort((a, b) => (a.year || 0) - (b.year || 0)).map(movieCard).join("")}</div>`;
  });
  return html + "</section>";
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
  return `<article class="episode${done ? " watched" : ""}">
    <button class="ep-thumb" data-play="${esc(ep.id)}" aria-label="Play ${esc(title(ep))}">${thumbFor(ep)}
      ${pct(ep.id) && !done ? `<span class="progress"><i style="width:${pct(ep.id)}%"></i></span>` : ""}
      ${done ? `<span class="seen-badge">${icon("i-check")}</span>` : ""}
      <span class="play-glyph">${icon("i-play")}</span></button>
    <div class="ep-text">
      ${label ? `<div class="t2">${esc(label)}</div>` : ""}
      <h3><span class="num">${esc(ep.kind === "episode" ? (ep.s === 0 ? "S" : "") + ep.e + (ep.e2 ? "–" + ep.e2 : "") : "")}</span>${esc(title(ep))}</h3>
      <p class="ep-meta">${meta}</p>
      ${ep.summary ? `<p class="ep-sum clamp">${esc(ep.summary)}</p>` : ""}
    </div>
    <button class="tick" data-watched="${esc(ep.id)}" aria-pressed="${done}" aria-label="${done ? "Mark as not watched" : "Mark as watched"}" title="${done ? "Watched" : "Mark as watched"}">${icon("i-check")}</button>
  </article>`;
}
function viewShow(id, seasonKey) {
  const show = byId.get(id);
  if (!show || !show.seasons) return viewMissing();
  setGlow(show.backdrop || show.poster);
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
      <div class="episodes" role="tabpanel">${items.map(i => episodeRow(i)).join("")}</div>
    </div>`;
}
function viewSearch(q) {
  const needle = q.trim().toLowerCase();
  if (!needle) return viewHome();
  setGlow("");
  const hit = s => (s || "").toLowerCase().includes(needle);
  const sh = shows.filter(s => hit(s.name));
  const mv = movies.filter(m => hit(m.title) || hit(m.collection));
  const eps = [];
  shows.forEach(s => s.seasons.forEach(se => se.episodes.forEach(ep => { if (hit(ep.title)) eps.push(ep); })));
  shows.forEach(s => s.extras.forEach(x => { if (hit(x.title)) eps.push(x); }));
  const total = sh.length + mv.length + eps.length;
  return `<section class="page"><div class="page-head"><h1>${esc(q.trim())}</h1><span class="count">${plural(total, "result")}</span></div>
    ${total ? "" : `<p class="count">Nothing matches "${esc(q.trim())}". Try part of an episode title.</p>`}
    ${sh.length || mv.length ? `<div class="grid">${sh.map(posterCard).join("")}${mv.map(movieCard).join("")}</div>` : ""}
    ${eps.length ? `<div class="episodes" style="margin-top:28px">${eps.slice(0, 80).map(ep =>
      episodeRow(ep, ep.show.name + ", " + epCode(ep))).join("")}</div>` : ""}
  </section>`;
}
function viewMissing() {
  return `<section class="empty"><h1>That page isn't here</h1><p>The show may have been renamed or removed.</p>
    <p><a class="btn" href="#/">Go home</a></p></section>`;
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
  if (e.target.id !== "liveSearch") return;
  liveQuery = e.target.value;
  const pos = e.target.selectionStart;
  rerender();
  const box = $("#liveSearch"); if (box) { box.focus(); box.setSelectionRange(pos, pos); }
});

/* ---------- sign in and first-run setup ---------- */
function authView(kind) {
  $("#nav").hidden = $("#searchBox").hidden = $("#who").hidden = true;
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
  </form></section>`;
  const form = $("#authForm");
  form.name.focus();
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

/* ---------- server (admin) page ---------- */
let adminData = null, adminTimer = 0;
async function loadAdmin() {
  try {
    adminData = await api("/api/admin/status");
    adminData.live = (await api("/api/live")).playlists;
  } catch (e) { adminData = { error: e.message }; }
  if (location.hash.startsWith("#/server") && !Player.isOpen()) { const y = scrollY; view.innerHTML = viewServer(); scrollTo(0, y); }
}
function viewServer() {
  setGlow("");
  clearTimeout(adminTimer);
  adminTimer = setTimeout(() => { if (location.hash.startsWith("#/server")) loadAdmin(); }, 10000);
  if (!adminData) { loadAdmin(); return `<section class="admin"><div class="admin-head"><h1>Server</h1></div><p class="admin-lede">Loading…</p></section>`; }
  if (adminData.error) return `<section class="admin"><div class="admin-head"><h1>Server</h1></div><p class="admin-lede">${esc(adminData.error)}</p></section>`;
  const d = adminData, s = d.server, L = d.library, port = s.port;
  const addr = [];
  s.lan.forEach(ip => addr.push(`<div><b>At home</b><code>http://${esc(ip)}:${port}</code><br><span>Any phone, laptop or TV browser on your Wi-Fi.</span></div>`));
  s.tailscale.forEach(ip => addr.push(`<div><b>Away from home</b><code>http://${esc(ip)}:${port}</code><br><span>From any device signed in to your Tailscale.</span></div>`));
  addr.push(`<div><b>TVs</b><span>${s.dlna ? `Roku Media Player, VLC and most smart TVs list "${esc(s.name)}" on their own.` : "TV sharing is off (see Settings)."}</span></div>`);
  const actRow = a => `<li class="${a.kind === "review" ? "review" : ""}"><span>${esc(a.message)}</span><span class="when">${esc(ago(a.at))}</span></li>`;
  const streams = d.streams.length ? d.streams.map(x => `<li><span><b>${esc(x.who)}</b> is watching ${esc(x.title || x.item)}</span><span class="when">${esc({ direct: "Original file", remux: "Repackaged live", transcode: "Converted live" }[x.mode] || x.mode)}</span></li>`).join("")
    : `<li class="empty-row">Nobody is watching right now.</li>`;
  const inbox = d.inbox.length ? d.inbox.map(x => `<li><span>${esc(x.name)}</span><span class="when">${x.state === "copying" ? "Still copying" : "Sorting soon"}</span></li>`).join("")
    : `<li class="empty-row">Empty. Drop shows and movies here and they'll be filed within a minute.</li>`;
  const review = d.review.length ? d.review.map(actRow).join("") : `<li class="empty-row">Nothing needs your attention.</li>`;
  const users = d.users.map(u => `<li><span><b>${esc(u.name)}</b>${u.admin ? " (admin)" : ""}<br><span class="when">${u.seen ? "Last seen " + esc(ago(u.seen)) : "Hasn't signed in yet"}</span></span>
    <span class="row-actions"><button class="mini" data-user-pass="${u.id}" data-user-name="${esc(u.name)}">New password</button>${u.id !== session.user.id ? `<button class="mini danger" data-user-del="${u.id}" data-user-name="${esc(u.name)}">Remove</button>` : ""}</span></li>`).join("");
  const sw = (key, on, label, hint) => `<div class="toggle"><div><b>${label}</b><span>${hint}</span></div>
    <button class="switch" role="switch" aria-checked="${!!on}" aria-label="${esc(label)}" data-setting="${key}"></button></div>`;
  const ff = s.ffmpeg;
  return `<section class="admin">
    <div class="admin-head"><h1>Server</h1><span class="pill">Running</span>${ff ? "" : `<span class="pill warn">Can't convert video yet</span>`}</div>
    <p class="admin-lede">${esc(s.name)} on ${esc(s.host)}, Sofa ${esc(s.version)}, up since ${esc(new Date(s.started * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }))}.</p>
    <div class="panels">
      <div class="panel"><h2>How to watch</h2><p class="hint">Open one of these addresses and sign in.</p><div class="addr">${addr.join("")}</div></div>
      <div class="panel"><h2>Library</h2><p class="hint">Updated ${esc(ago(L.generated))}${L.scanning ? ", checking now" : ""}.</p>
        <div class="stats"><div class="stat"><b>${L.shows}</b><span>shows</span></div><div class="stat"><b>${L.episodes}</b><span>episodes</span></div>
        <div class="stat"><b>${L.movies}</b><span>movies</span></div>${L.disk ? `<div class="stat"><b>${bytes(L.disk.free)}</b><span>free space</span></div>` : ""}</div>
        <dl class="kv"><dt>Drop new things in</dt><dd><code>${esc(L.folders.inbox)}</code></dd><dt>Shows</dt><dd><code>${esc(L.folders.shows)}</code></dd>
        <dt>Movies</dt><dd><code>${esc(L.folders.movies)}</code></dd><dt>Needs a look</dt><dd><code>${esc(L.folders.review)}</code></dd></dl>
        <div class="actions" style="margin-top:16px"><button class="btn" data-admin="scan">Check for new files now</button></div></div>
      <div class="panel"><h2>Inbox</h2><p class="hint">Sofa waits until a copy finishes, then names and files it.</p><ul class="list">${inbox}</ul></div>
      <div class="panel"><h2>Needs your help</h2><p class="hint">Files Sofa couldn't identify are in the Needs Review folder. Rename and drop them in the Inbox again.</p><ul class="list">${review}</ul></div>
      <div class="panel"><h2>Watching now</h2><p class="hint">"Repackaged" and "converted" mean Sofa is adapting the file for that device as it plays.</p><ul class="list">${streams}</ul></div>
      <div class="panel"><h2>People</h2><p class="hint">Everyone gets their own sign-in and their own "continue watching".</p><ul class="list">${users}</ul>
        <form class="inline-form" id="addUser"><label class="field"><span>Name</span><input name="name" required maxlength="40"></label>
        <label class="field"><span>Password</span><input name="password" type="password" required minlength="8" autocomplete="new-password"></label>
        <button class="btn" type="submit">Add</button><label class="check"><input type="checkbox" name="admin"> Can manage the server</label>
        <div class="form-error" role="alert" style="grid-column:1/-1"></div></form></div>
      <div class="panel"><h2>Settings</h2>
        ${sw("dlna", s.dlna, "Share with TVs", "Lets Roku, Fire TV (VLC) and smart TVs at home browse without signing in.")}
        ${sw("tvmaze", d.settings.tvmaze, "Look up show details", "Summaries, episode titles and missing artwork from TVmaze.")}
        <div class="toggle"><div><b>Video conversion</b><span>${ff ? "Ready (ffmpeg " + esc(ff) + "). Files any device can't play are adapted as they stream." : "ffmpeg isn't installed, so only files a device already supports will play."}</span></div></div>
        <div class="toggle"><div><b>Backups</b><span>${d.backups.length ? "Last backup " + esc(ago(d.backups[0].made)) + ". " : "No backup yet. "}Accounts, watch history and settings are saved every night at ${esc(d.settings.backup_time)} to <code>${esc(d.backup_folder)}</code>, keeping ${esc(d.settings.backup_keep)}. Your shows and movies aren't included.</span></div>
          <button class="mini" data-admin="backup">Back up now</button></div>
        <div class="toggle"><div><b>Remote access</b><span>${s.remote === "public" ? "Accepting internet connections. Keep Sofa behind HTTPS." : "Home network and Tailscale only. See docs/remote-access.md to change this."}</span></div></div>
      </div>
      <div class="panel"><h2>Live TV channel lists</h2><p class="hint">M3U playlists of free channels. Sofa re-downloads them twice a day.</p>
        <ul class="list">${(d.live || []).map(p => `<li><span><b>${esc(p.name)}</b><br><span class="when">${p.error ? "Problem: " + esc(p.error) : plural(p.count || 0, "channel")}</span></span>
          <button class="mini danger" data-live-remove="${esc(p.url)}">Remove</button></li>`).join("") || `<li class="empty-row">No channel lists yet.</li>`}</ul>
        <div class="presets">${PRESETS.filter(p => !(d.live || []).some(x => x.url === p[1])).map(p => `<button class="mini" data-preset="${esc(p[1])}" data-name="${esc(p[0])}">+ ${esc(p[0])}</button>`).join("")}</div>
        <form class="inline-form" id="addList"><label class="field"><span>Name</span><input name="name" maxlength="60" placeholder="My channels"></label>
        <label class="field"><span>M3U link</span><input name="url" type="url" required placeholder="https://…/list.m3u"></label>
        <button class="btn" type="submit">Add</button><div class="form-error" role="alert" style="grid-column:1/-1"></div></form></div>
      <div class="panel wide"><h2>Activity</h2><ul class="list">${d.activity.slice(0, 25).map(actRow).join("") || `<li class="empty-row">Nothing yet.</li>`}</ul></div>
    </div></section>`;
}
async function adminAction(fn) {
  try { await fn(); } catch (e) { alertBox(e.message); }
  loadAdmin();
}
function alertBox(msg) { dialog(`<h2>That didn't work</h2><p>${esc(msg)}</p>`); }

/* ---------- router ---------- */
function route() {
  if (!session || !session.user) return;
  const hash = decodeURIComponent(location.hash.replace(/^#\/?/, ""));
  const [name, ...rest] = hash.split("/");
  let html, nav = "";
  if (name === "show") { const arg = rest.join("/"); const cut = arg.lastIndexOf("|"); html = viewShow(cut > 0 ? arg.slice(0, cut) : arg, cut > 0 ? arg.slice(cut + 1) : null); nav = "shows"; }
  else if (name === "shows") { html = viewShows(); nav = "shows"; }
  else if (name === "movies") { html = viewMovies(); nav = "movies"; }
  else if (name === "search") html = viewSearch(rest.join("/"));
  else if (name === "live") { html = viewLive(); nav = "live"; }
  else if (name === "server" && session.user.admin) { html = viewServer(); nav = "server"; }
  else { html = viewHome(); nav = "home"; }
  document.querySelectorAll("[data-nav]").forEach(a => { if (a.dataset.nav === nav) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); });
  view.innerHTML = html;
  updateNudges();
}
function rerender() { const y = scrollY; route(); scrollTo(0, y); }
window.addEventListener("hashchange", () => { route(); scrollTo(0, 0); });

/* ---------- interactions ---------- */
document.addEventListener("click", e => {
  const t = e.target.closest("[data-play],[data-watched],[data-season],[data-sort],[data-nudge],[data-season-watched],[data-dismiss],[data-admin],[data-setting],[data-user-pass],[data-user-del],[data-live],[data-fav],[data-group],[data-preset],[data-live-remove]");
  if (!t) return;
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
  else if (t.dataset.dismiss) { t.closest(".dialog-scrim").remove(); }
  else if (t.dataset.admin === "backup") { t.disabled = true; t.textContent = "Backing up…"; adminAction(() => api("/api/admin/backup", {})); }
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
document.addEventListener("submit", e => {
  if (e.target.id === "addList") {
    e.preventDefault();
    const f = e.target, err = $(".form-error", f);
    err.textContent = "Downloading the list…";
    api("/api/admin/live", { add: { name: f.name.value, url: f.url.value } })
      .then(r => { f.reset(); liveData = null; loadAdmin(); })
      .catch(ex => { err.textContent = ex.message; });
    return;
  }
  if (e.target.id !== "addUser") return;
  e.preventDefault();
  const f = e.target, err = $(".form-error", f);
  api("/api/admin/users", { name: f.name.value, password: f.password.value, admin: f.admin.checked })
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
document.addEventListener("error", e => {
  const img = e.target;
  if (img.tagName !== "IMG") return;
  const f = img.closest(".frame"); if (f) f.classList.add("noimg");
  img.remove();
}, true);

let searchTimer;
$("#q").addEventListener("input", e => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    const v = e.target.value;
    const target = v.trim() ? "#/search/" + encodeURIComponent(v) : "#/";
    if (location.hash.startsWith("#/search/")) { history.replaceState(null, "", target); route(); }
    else location.hash = target;
  }, 180);
});
$("#signOut").addEventListener("click", async () => { await api("/api/logout", {}).catch(() => {}); location.hash = "#/"; boot(); });

function dialog(html) {
  const d = document.createElement("div");
  d.className = "dialog-scrim";
  d.innerHTML = `<div class="dialog" role="alertdialog" aria-modal="true">${html}<div class="actions"><button class="btn primary" data-dismiss="1">OK</button></div></div>`;
  d.addEventListener("click", e => { if (e.target === d) d.remove(); });
  document.body.appendChild(d);
  $("[data-dismiss]", d).focus();
}

/* ---------- TV remote: arrow keys move focus to the nearest thing in that direction ---------- */
const FOCUSABLE = "a[href], button:not([disabled]):not([tabindex='-1']), input, select, [tabindex='0']";
document.addEventListener("keydown", e => {
  const dir = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key];
  if (!dir || Player.isOpen() || e.metaKey || e.ctrlKey || e.altKey) return;
  const active = document.activeElement;
  if (active && (active.tagName === "INPUT" && active.type !== "checkbox" && (dir[0] !== 0 || active.type === "range"))) return;
  document.body.classList.add("tv-nav");
  const els = [...document.querySelectorAll(FOCUSABLE)].filter(el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && !el.closest("[hidden]"); });
  if (!active || active === document.body || !els.includes(active)) { const first = $(".hero .btn, .card, .seasons button, .episode .ep-thumb") || els[0]; if (first) { e.preventDefault(); first.focus(); } return; }
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
  if (best) { e.preventDefault(); best.focus({ preventScroll: true }); best.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" }); }
});
document.addEventListener("mousedown", () => document.body.classList.remove("tv-nav"));

/* ---------- player ---------- */
const Player = (function () {
  const el = $("#player"), video = $("video", el), canvas = $("canvas", el), ctx = canvas.getContext("2d");
  const scrub = $(".scrub", el), fill = $(".fill", el), buf = $(".buf", el), knob = $(".knob", el), hoverTime = $(".hover-time", el);
  const timeEl = $(".p-time", el), modeEl = $(".p-mode", el), chip = $(".p-chip", el), nextCard = $(".p-next", el), errorBox = $(".p-error", el);
  const flash = $(".p-flash", el), toggleBtn = $('[data-act="toggle"]', el), volume = $(".vol input", el);
  const ccBtn = $('[data-act="cc"]', el), ccMenu = $(".cc-menu", el);
  const SPEEDS = [1, 1.25, 1.5, 2, 0.75];
  const caps = {
    mkv: !!(video.canPlayType('video/x-matroska; codecs="avc1.64001F, mp4a.40.2"') || video.canPlayType("video/x-matroska")),
    hevc: !!video.canPlayType('video/mp4; codecs="hvc1.1.6.L93.B0"'),
    ac3: !!video.canPlayType('audio/mp4; codecs="ac-3"'),
    vp9: !!video.canPlayType('video/webm; codecs="vp9"')
  };
  const nativeHls = !!video.canPlayType("application/vnd.apple.mpegurl");
  let item = null, next = null, plan = null, offset = 0, hlsSession = null, subIndex = -1;
  let lastSave = 0, idleTimer = 0, ambientTimer = 0, nextHidden = false, dragging = false, returnFocus = null;

  if ("filter" in ctx) ctx.filter = "blur(1.5px)";
  volume.value = prefs.get("volume", 1);
  video.volume = +volume.value;
  video.muted = prefs.get("muted", false);
  setAmbient(prefs.get("ambient", true));

  const live = () => plan && plan.mode !== "direct";
  const now = () => offset + (video.currentTime || 0);
  const total = () => (plan && plan.duration) || (isFinite(video.duration) ? video.duration : 0);

  async function open(it) {
    if (!it) return;
    if (hls) { hls.destroy(); hls = null; }
    el.classList.remove("is-live"); liveList_ = null;
    video.removeAttribute("src"); video.load();
    returnFocus = document.activeElement;
    item = it; next = nextAfter(it); nextHidden = false; subIndex = prefs.get("subs", false) ? 0 : -1;
    errorBox.hidden = chip.hidden = nextCard.hidden = ccMenu.hidden = true;
    const owner = it.show || it;
    $(".p-show", el).textContent = owner.name || it.title;
    $(".p-title", el).textContent = it.kind === "movie" ? (it.year || "") : subtitleFor(it);
    $('[data-act="next"]', el).hidden = !next;
    el.hidden = false;
    document.body.style.overflow = "hidden";
    video.playbackRate = 1; $(".speed", el).textContent = "1×";
    try {
      plan = await api("/api/play/" + encodeURIComponent(it.id) + "?" + Object.keys(caps).map(k => k + "=" + (caps[k] ? 1 : 0)).join("&"));
    } catch (e) { return showError("This video can't be played", e.message); }
    if (plan.mode === "unsupported") return showError("This video can't be played here", plan.message);
    modeEl.hidden = plan.mode === "direct";
    modeEl.textContent = plan.mode === "remux" ? "Repackaged" : "Converted";
    ccBtn.hidden = !plan.subtitles.length;
    const p = prog(it.id);
    const resumeAt = p && !p.done && p.t > 30 && (!plan.duration || p.t < plan.duration - 30) ? p.t : 0;
    await load(resumeAt);
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
    if (plan.mode === "direct") {
      offset = 0;
      if (!video.getAttribute("src")) {
        video.src = plan.url;
        await new Promise(r => { video.addEventListener("loadedmetadata", r, { once: true }); video.addEventListener("error", r, { once: true }); });
      }
      if (at) video.currentTime = at;
    } else if (nativeHls) {
      try {
        const h = await api("/api/hls/" + encodeURIComponent(item.id) + "?mode=" + plan.mode + "&t=" + at.toFixed(1) + (hlsSession ? "&replace=" + hlsSession : ""));
        hlsSession = h.session; offset = at; video.src = h.url;
      } catch (e) { return showError("This video can't be played right now", e.message); }
    } else {
      offset = at;
      video.src = plan.url + "&t=" + at.toFixed(1);
    }
    setSubtitles(subIndex);
    video.play().catch(() => {});
    paint();
  }
  function seekTo(t) {
    t = Math.max(0, Math.min(total() ? total() - 1 : t, t));
    if (!live()) { video.currentTime = t; return; }
    const bufferedEnd = video.buffered.length ? offset + video.buffered.end(video.buffered.length - 1) : 0;
    if (t >= offset && t <= bufferedEnd) video.currentTime = t - offset;   // already have it
    else load(t);
  }
  function close() {
    if (hls) { hls.destroy(); hls = null; }
    el.classList.remove("is-live"); liveList_ = null;
    save(true);
    video.pause();
    video.removeAttribute("src"); video.load();
    [...video.querySelectorAll("track")].forEach(t => t.remove());
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    el.hidden = true; document.body.style.overflow = "";
    stopAmbient();
    item = null; plan = null; hlsSession = null;
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
  function playNext() { if (!next) return; save(true); const n = next; hlsSession = null; video.removeAttribute("src"); open(n); }
  function showError(heading, msg) {
    errorBox.innerHTML = `<h2>${esc(heading)}</h2><p>${esc(msg || "")}</p><button class="btn" data-act="close">Back to library</button>`;
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
    tr.src = s.url + (offset ? "?offset=" + offset.toFixed(2) : "");
    tr.default = true;
    video.appendChild(tr);
    tr.addEventListener("load", () => { tr.track.mode = "showing"; });
    tr.track.mode = "showing";
  }
  function ccMenuOpen() {
    ccMenu.innerHTML = [`<button role="menuitemradio" aria-checked="${subIndex < 0}" data-sub="-1">Off</button>`]
      .concat(plan.subtitles.map((s, i) => `<button role="menuitemradio" aria-checked="${i === subIndex}" data-sub="${i}">${esc(s.label)}</button>`)).join("");
    ccMenu.hidden = false;
    $("[aria-checked='true']", ccMenu).focus();
  }
  ccMenu.addEventListener("click", e => {
    const b = e.target.closest("[data-sub]"); if (!b) return;
    setSubtitles(+b.dataset.sub); prefs.set("subs", subIndex >= 0); ccMenu.hidden = true; ccBtn.focus();
  });
  function paint() {
    const d = total(), t = now();
    const r = d ? Math.min(1, t / d) : 0;
    if (!dragging) { fill.style.width = r * 100 + "%"; knob.style.left = r * 100 + "%"; }
    scrub.setAttribute("aria-valuemax", Math.floor(d)); scrub.setAttribute("aria-valuenow", Math.floor(t));
    scrub.setAttribute("aria-valuetext", clock(t) + " of " + clock(d));
    timeEl.textContent = clock(t) + " / " + clock(d);
    if (video.buffered.length && d) buf.style.width = Math.min(100, ((offset + video.buffered.end(video.buffered.length - 1)) / d) * 100) + "%";
    const left = d - t;
    if (next && d && left <= 30 && left > 0 && !nextHidden) {
      if (nextCard.hidden) {
        $(".frame", nextCard).innerHTML = thumbFor(next);
        $(".name", nextCard).textContent = subtitleFor(next);
        nextCard.hidden = false;
      }
      $(".label", nextCard).textContent = "Up next in " + Math.ceil(left) + "s";
    } else if (!nextCard.hidden && left > 30) nextCard.hidden = true;
  }
  function setPlayingUI() {
    const playing = !video.paused;
    $("use", toggleBtn).setAttribute("href", playing ? "#i-pause" : "#i-play");
    toggleBtn.setAttribute("aria-label", playing ? "Pause" : "Play");
    if (playing && el.classList.contains("ambient")) startAmbient(); else stopAmbient();
  }
  function toggle() {
    if (video.paused) video.play().catch(() => {}); else video.pause();
    $("use", flash).setAttribute("href", video.paused ? "#i-pause" : "#i-play");
    flash.classList.remove("go"); void flash.offsetWidth; flash.classList.add("go");
  }
  function seekBy(s) { if (total()) seekTo(now() + s); wake(); }
  function wake() {
    el.classList.remove("idle");
    clearTimeout(idleTimer);
    idleTimer = setTimeout(() => { if (!video.paused && !dragging && ccMenu.hidden) el.classList.add("idle"); }, 2800);
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

  video.addEventListener("timeupdate", () => { paint(); save(false); });
  video.addEventListener("progress", paint);
  video.addEventListener("durationchange", paint);
  video.addEventListener("play", () => { setPlayingUI(); wake(); });
  video.addEventListener("pause", () => { setPlayingUI(); save(true); wake(); });
  video.addEventListener("ended", () => { save(true); if (next && !nextHidden) playNext(); else wake(); });
  video.addEventListener("error", () => {
    if (el.classList.contains("is-live") && video.getAttribute("src")) return showError("This channel isn't available right now", "Free channels come and go. Try another one, or try this one later.");
    if (!item || !video.getAttribute("src")) return;
    showError("This video stopped", "The file may have moved, or the server couldn't read it. Go back and try again; if it keeps happening, check the Server page.");
  });
  video.addEventListener("click", toggle);
  video.addEventListener("dblclick", () => fullscreen());
  el.addEventListener("mousemove", wake);

  scrub.addEventListener("pointerdown", e => {
    dragging = true; scrub.classList.add("drag"); scrub.setPointerCapture(e.pointerId);
    const r = ratioAt(e.clientX); fill.style.width = knob.style.left = r * 100 + "%";
  });
  scrub.addEventListener("pointermove", e => {
    const r = ratioAt(e.clientX);
    hoverTime.textContent = clock(r * total()); hoverTime.style.left = r * 100 + "%";
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
    if (a === "close") close();
    else if (a === "toggle") toggle();
    else if (a === "rew") seekBy(-10);
    else if (a === "fwd") seekBy(30);
    else if (a === "mute") video.muted = !video.muted;
    else if (a === "next") { if (el.classList.contains("is-live")) zap(1); else playNext(); }
    else if (a === "cancel-next") { nextHidden = true; nextCard.hidden = true; }
    else if (a === "restart") { seekTo(0); chip.hidden = true; }
    else if (a === "full") fullscreen();
    else if (a === "ambient") setAmbient(!el.classList.contains("ambient"));
    else if (a === "cc") { if (ccMenu.hidden) ccMenuOpen(); else ccMenu.hidden = true; }
    else if (a === "speed") {
      const i = (SPEEDS.indexOf(video.playbackRate) + 1) % SPEEDS.length;
      video.playbackRate = SPEEDS[i]; b.textContent = SPEEDS[i] + "×";
    }
  });
  document.addEventListener("keydown", e => {
    if (el.hidden || e.metaKey || e.ctrlKey || e.altKey) return;
    const k = e.key;
    if (k === "Escape" && !ccMenu.hidden) { ccMenu.hidden = true; ccBtn.focus(); return; }
    const onButton = e.target.closest && e.target.closest("button") && (k === " " || k === "Enter");
    if (onButton) return;
    const controlsHidden = el.classList.contains("idle");
    const map = {
      " ": toggle, k: toggle, Enter: toggle, MediaPlayPause: toggle,
      ArrowLeft: () => seekBy(-10), j: () => seekBy(-10), ArrowRight: () => seekBy(10), l: () => seekBy(30),
      MediaRewind: () => seekBy(-10), MediaFastForward: () => seekBy(30),
      ArrowUp: () => { video.volume = Math.min(1, video.volume + 0.1); volume.value = video.volume; },
      ArrowDown: () => { video.volume = Math.max(0, video.volume - 0.1); volume.value = video.volume; },
      f: fullscreen, m: () => { video.muted = !video.muted; }, n: playNext, c: () => { if (plan && plan.subtitles.length) ccMenuOpen(); },
      PageUp: () => zap(-1), PageDown: () => zap(1), ChannelUp: () => zap(-1), ChannelDown: () => zap(1),
      Escape: () => { if (!document.fullscreenElement) close(); }, Backspace: () => close(), GoBack: () => close()
    };
    if (e.target === volume && /^Arrow/.test(k)) return;
    // With controls showing, arrows move between buttons (TV remotes); hidden, they seek.
    if (!controlsHidden && /^Arrow(Up|Down)$/.test(k) && e.target.closest && e.target.closest(".p-row")) return;
    if (map[k]) { e.preventDefault(); map[k](); wake(); }
  });
  window.addEventListener("pagehide", () => save(true));
  let hls = null, liveList_ = null, liveIdx = 0;
  function loadHlsJs() {
    if (window.Hls) return Promise.resolve();
    return new Promise((res, rej) => { const sc = document.createElement("script"); sc.src = "/client/vendor/hls.min.js"; sc.onload = res; sc.onerror = rej; document.head.appendChild(sc); });
  }
  async function openLive(ch, list) {
    if (!ch) return;
    returnFocus = returnFocus || document.activeElement;
    liveList_ = list || [ch]; liveIdx = Math.max(0, liveList_.indexOf(ch));
    item = null; plan = { mode: "live", subtitles: [] }; offset = 0; next = null;
    el.classList.add("is-live");
    errorBox.hidden = chip.hidden = nextCard.hidden = ccMenu.hidden = true;
    ccBtn.hidden = true;
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
  return { open, openLive, zap, isLive: () => el.classList.contains("is-live"), isOpen: () => !el.hidden };
})();

/* ---------- boot ---------- */
async function reloadLibrary() {
  const [lib, prog] = await Promise.all([api("/api/library"), api("/api/progress")]);
  progress = prog; indexLibrary(lib);
  $("#foot").textContent = "Library updated " + new Date(lib.generated * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) + ". New files in the Inbox show up on their own.";
}
let refreshing = 0;
async function boot() {
  try { session = await api("/api/session"); }
  catch (e) { view.innerHTML = `<section class="empty"><h1>Can't reach the server</h1><p>${esc(e.message)}</p></section>`; return; }
  document.title = session.name;
  $("#brandName").textContent = session.name;
  if (session.needs_setup) return authView("setup");
  if (!session.user) return authView("login");
  $("#nav").hidden = $("#searchBox").hidden = $("#who").hidden = false;
  $("#navServer").hidden = !session.user.admin;
  $("#whoName").textContent = session.user.name;
  view.innerHTML = "";
  await reloadLibrary();
  route();
  // Pick up new episodes while the page stays open.
  if (!refreshing) refreshing = setInterval(async () => {
    if (Player.isOpen()) return;
    try { const lib = await api("/api/library"); if (lib.generated !== LIB.generated) { indexLibrary(lib); rerender(); } } catch (e) {}
  }, 60000);
}
boot();
})();
