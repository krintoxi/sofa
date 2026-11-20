/* Edge Music on the box: the box's own app, made for a remote and a Pi.
   The catalogue and the account come from the agent (/box/api/music/*, boxmusic.py), which asks Edge Music; this page
   only plays the song (an <audio> pointed at Edge Music) and shows covers at the size they're drawn (art.php?w=).
   Nothing moves by itself and a press changes only the ring: on a Pi 3 the browser draws every pixel on the CPU. */
(function () {
  "use strict";
  const $ = (s, r) => (r || document).querySelector(s), $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const view = $("#view"), nowEl = $("#now"), bar = $("#bar"), audio = $("#audio"), toastEl = $("#toast");
  const api = async (path, body) => {
    const r = await fetch("/box/api/music/" + path, body === undefined ? {} :
      { method: "POST", headers: { "Content-Type": "application/json", "X-Sofa-Box": "1" }, body: JSON.stringify(body) });
    return r.json();
  };
  const ICON = {
    play: '<svg viewBox="0 0 24 24"><path d="M7 4.5v15l13-7.5z"/></svg>', pause: '<svg viewBox="0 0 24 24"><path d="M6 4.5h4.5v15H6zM13.5 4.5H18v15h-4.5z"/></svg>',
    prev: '<svg viewBox="0 0 24 24"><path d="M5 5h2.5v14H5zM20 5v14L9 12z"/></svg>', next: '<svg viewBox="0 0 24 24"><path d="M16.5 5H19v14h-2.5zM4 5v14l11-7z"/></svg>',
    heart: '<svg viewBox="0 0 24 24"><path d="M12 20.5 4.6 13a4.9 4.9 0 0 1 7-6.9l.4.4.4-.4a4.9 4.9 0 0 1 7 6.9z"/></svg>',
    shuffle: '<svg viewBox="0 0 24 24"><path d="M16.5 3 21 7l-4.5 4V8.3h-1.7l-2.4 3.2-1.5-2 2.4-3.2c.4-.5.9-.8 1.5-.8h1.7zM3 5.5h3.6c.6 0 1.1.3 1.5.8l6.7 9.4h1.7V13l4.5 4-4.5 4v-2.8h-1.7c-.6 0-1.1-.3-1.5-.8L6.600 8H3zM3 15.700h3.600l1.300-1.800 1.500 2-1.300 1.800c-.4.500-.9.800-1.500.800H3z"/></svg>'
  };

  let cat = { tracks: [], albums: [], stations: [] }, byId = {}, artists = [], acc = { linked: false };
  let stack = [{ name: "home" }], lists = {}, query = "";
  let queue = [], qi = -1, shuffle = false, fails = 0, noted = null, pollTimer = null;

  // ---- small things
  const art = (url, w) => url ? url + "&w=" + w : "";
  const cover = (url, w, name) => url ? `<img class="cv" loading="lazy" decoding="async" alt="" src="${esc(art(url, w))}">`
    : `<div class="cv blank" aria-hidden="true">${esc((name || "?").trim().charAt(0).toUpperCase())}</div>`;
  const clock = s => { s = Math.max(0, Math.floor(s || 0)); return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"); };
  const fold = s => String(s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
  const liked = id => (acc.likedIds || []).indexOf(id) >= 0;
  let toastTimer = null;
  function toast(text) {
    toastEl.textContent = text; toastEl.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { toastEl.hidden = true; }, 3200);
  }

  // ---- what's drawn
  function songCard(id, ctx, i) {
    const t = byId[id];
    return `<button class="card" data-f data-k="s:${esc(ctx)}:${i}" data-ctx="${esc(ctx)}" data-i="${i}">${cover(t.art, 320, t.title)}<b>${esc(t.title)}</b><small>${esc(t.artist)}</small></button>`;
  }
  function songRow(id, ctx, i) {
    const t = byId[id], on = queue[qi] === id;
    return `<button class="song${on ? " on" : ""}" data-f data-k="s:${esc(ctx)}:${i}" data-ctx="${esc(ctx)}" data-i="${i}" data-id="${esc(id)}">${cover(t.art, 160, t.title)}` +
      `<b>${liked(id) ? '<i class="heart" aria-label="Liked">♥</i>' : ""}${esc(t.title)}</b><span>${esc(t.artist)}</span><time>${t.seconds ? clock(t.seconds) : ""}</time></button>`;
  }
  const goCard = (go, title, sub, url, round) =>
    `<button class="card${round ? " round" : ""}" data-f data-k="${esc(go)}" data-go="${esc(go)}">${cover(url, 320, title)}<b>${esc(title)}</b><small>${esc(sub)}</small></button>`;
  const count = n => n + (n === 1 ? " song" : " songs");
  const albumCard = a => goCard("album:" + a.id, a.title, a.artist, a.art);
  const stationCard = s => goCard("station:" + s.id, s.name, s.line || count(s.trackIds.length), s.art);
  const artistCard = a => goCard("artist:" + a.name, a.name, count(a.ids.length), a.art, true);
  function list(key, ids) { lists[key] = ids.filter(i => byId[i]); return lists[key]; }

  const VIEWS = {
    home() {
      let h = "";
      const row = (title, cards) => cards.length ? `<h2>${esc(title)}</h2><div class="row">${cards.join("")}</div>` : "";
      if (!cat.tracks.length) return `<h1>Edge Music</h1><p class="empty">${esc(cat.error || "Getting the music…")}</p>`;
      if (acc.linked) {
        h += row("Songs you like", list("liked", acc.likedIds || []).slice(0, 14).map((id, i) => songCard(id, "liked", i)));
        h += row("Played lately", list("recent", acc.recentIds || []).slice(0, 14).map((id, i) => songCard(id, "recent", i)));
      }
      h += row("Albums", cat.albums.map(albumCard));
      h += row("Stations", cat.stations.slice(0, 16).map(stationCard));
      h += row("Artists", artists.map(artistCard));
      h += row("Songs", list("all", cat.tracks.map(t => t.id)).slice(0, 14).map((id, i) => songCard(id, "all", i)));
      return h;
    },
    songs() { return `<h1>Songs</h1><div class="songs">${list("all", cat.tracks.map(t => t.id)).map((id, i) => songRow(id, "all", i)).join("")}</div>`; },
    albums() { return `<h1>Albums</h1><div class="grid">${cat.albums.map(albumCard).join("")}</div>`; },
    artists() { return `<h1>Artists</h1><div class="grid">${artists.map(artistCard).join("")}</div>`; },
    stations() { return `<h1>Stations</h1><div class="grid">${cat.stations.map(stationCard).join("")}</div>`; },
    set(v) {             // an album, an artist, a station, a playlist, the liked songs
      const [kind, id] = [v.kind, v.id];
      let title = "", sub = "", url = null, ids = [], label = kind;
      if (kind === "album") { const a = cat.albums.find(x => x.id === id); if (a) { title = a.title; sub = a.artist; url = a.art; ids = a.trackIds; } }
      else if (kind === "station") { const s = cat.stations.find(x => x.id === id); if (s) { title = s.name; sub = s.line; url = s.art; ids = s.trackIds; } }
      else if (kind === "artist") { const a = artists.find(x => x.name === id); if (a) { title = a.name; url = a.art; ids = a.ids; } }
      else if (kind === "playlist") { const p = (acc.playlists || []).find(x => x.id === id); if (p) { title = p.name; ids = p.trackIds; url = (byId[ids[0]] || {}).art; } }
      else if (kind === "liked") { title = "Songs you like"; ids = acc.likedIds || []; url = (byId[ids[0]] || {}).art; label = "yours"; }
      const key = kind + ":" + (id || ""); ids = list(key, ids);
      if (!ids.length) return `<h1>${esc(title || "Nothing here")}</h1><p class="empty">There's nothing to play here yet.</p>`;
      return `<div class="hero">${cover(url, 480, title)}<div><div class="kind">${esc(label)}</div><h1>${esc(title)}</h1>` +
        `<div class="sub">${esc([sub, count(ids.length)].filter(Boolean).join(" · "))}</div>` +
        `<div class="acts"><button class="btn go" data-f data-k="play" data-ctx="${esc(key)}" data-i="0">Play</button>` +
        `<button class="btn" data-f data-k="mix" data-ctx="${esc(key)}" data-i="mix">Shuffle</button></div></div></div>` +
        `<div class="songs">${ids.map((i, n) => songRow(i, key, n)).join("")}</div>`;
    },
    search() {
      const keys = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789".split("").map(c => `<button data-f data-k="key:${c}" data-key="${c}">${c}</button>`).join("") +
        `<button class="wide" data-f data-k="key:space" data-key=" ">Space</button><button class="wide" data-f data-k="key:del" data-key="del">Delete</button>` +
        `<button class="wide" data-f data-k="key:clear" data-key="clear">Clear</button>`;
      return `<h1>Search</h1><div class="find"><div><div class="typed" id="typed">${esc(query)}</div><div class="keys">${keys}</div></div><div id="found">${found()}</div></div>`;
    },
    account() {
      if (acc.linked) {
        const lists_ = (acc.playlists || []).map(p => goCard("playlist:" + p.id, p.name, count(p.trackIds.length), (byId[p.trackIds[0]] || {}).art)).join("");
        return `<h1>${esc(acc.name || "Your account")}</h1><p class="sub">Signed in on this box${acc.offline ? " (Edge Music can't be reached right now)" : ""}. ` +
          `${acc.canEdit ? "Songs you like here are liked everywhere." : "This box can listen, but not change your library."}</p>` +
          `<div class="acts"><button class="btn go" data-f data-k="liked" data-go="liked:">Songs you like</button><button class="btn" data-f data-k="out" data-act="signout">Sign out of this box</button></div>` +
          (lists_ ? `<h2>Your playlists</h2><div class="row">${lists_}</div>` : "");
      }
      const p = acc.pairing;
      if (!p) return `<h1>Sign in</h1><p class="sub" style="max-width:38rem">Listen without signing in, or sign in to see the songs you like and your playlists, and to like songs from the sofa. ` +
        `You'll type a code on your phone: the box never sees your password.</p>` +
        (acc.message ? `<p class="empty">${esc(acc.message)}</p>` : "") +
        `<div class="acts"><button class="btn go" data-f data-k="code" data-act="code">Get a code</button></div>`;
      return `<h1>Sign in</h1><div class="link"><div class="qr">${qr(p.url)}</div><div><div class="steps">On your phone, open <b>${esc(p.at)}</b><br>(or point its camera at the square), sign in, and type:</div>` +
        `<div class="code">${esc(p.code)}</div><div class="steps">This page moves on by itself once the code is in.</div>` +
        `<div class="acts"><button class="btn" data-f data-k="cancel" data-act="cancel">Cancel</button></div></div></div>`;
    }
  };

  function qr(text) {
    if (!window.qrcode || !text) return "";
    try { const q = window.qrcode(0, "M"); q.addData(text); q.make(); return q.createSvgTag({ cellSize: 4, margin: 0, scalable: true }); } catch (e) { return ""; }
  }
  function found() {
    const q = fold(query).trim();
    if (!q) return `<p class="empty">Pick letters with the remote, or type on a keyboard or your phone.</p>`;
    const ids = list("search", cat.tracks.filter(t => fold(t.title + " " + t.artist + " " + (t.genre || "") + " " + (t.mood || "")).indexOf(q) >= 0).map(t => t.id)).slice(0, 40);
    const who = artists.filter(a => fold(a.name).indexOf(q) >= 0).map(a => `<button class="btn" data-f data-k="artist:${esc(a.name)}" data-go="artist:${esc(a.name)}">${esc(a.name)}</button>`).join("");
    if (!ids.length && !who) return `<p class="empty">Nothing called that.</p>`;
    return (who ? `<div class="acts" style="margin:0 0 1rem">${who}</div>` : "") + `<div class="songs">${ids.map((id, i) => songRow(id, "search", i)).join("")}</div>`;
  }

  // ---- views and the ring
  // The ring is a class (as on Home), not :focus alone: a tab the box has just brought forward isn't always the
  // window's focus yet, and the ring must be there before the first press.
  let ringOn = null;
  const here = () => (ringOn && document.contains(ringOn) ? ringOn : document.activeElement);
  function ring(el, scroll) {
    if (!el) return;
    if (ringOn && ringOn !== el) ringOn.classList.remove("f");
    ringOn = el; el.classList.add("f");
    el.focus({ preventScroll: true });
    if (scroll) el.scrollIntoView({ block: "nearest", inline: "nearest" });
  }
  document.addEventListener("focusin", e => { const t = e.target.closest && e.target.closest("[data-f]"); if (t && t !== ringOn) ring(t); });
  const top = () => stack[stack.length - 1];
  function draw(focusKey) {
    const v = top();
    view.innerHTML = (VIEWS[v.name] || VIEWS.home)(v);
    $$("#tabs [data-tab]").forEach(b => b.toggleAttribute("aria-current", false));
    const tab = $(`#tabs [data-tab="${v.tab || v.name}"]`); if (tab) tab.setAttribute("aria-current", "page");
    $("#tabAccount").textContent = acc.linked ? (acc.name || "Account").slice(0, 18) : "Sign in";
    clearInterval(pollTimer); pollTimer = null;
    if (v.name === "account" && !acc.linked && acc.pairing) pollTimer = setInterval(poll, 3000);
    if (nowEl.hidden) focusOn(focusKey);
  }
  function focusOn(key) {
    let el = key && $$("[data-k]", view).find(e => e.dataset.k === key);
    el = el || $("[data-f]", view) || $("#tabs [aria-current]") || $("#tabs [data-f]");
    ring(el, true);
    if (!key) window.scrollTo(0, 0);
  }
  function go(v) {
    const a = here(); top().key = a && a.dataset ? a.dataset.k : null;
    if (["home", "songs", "albums", "artists", "stations", "search", "account"].indexOf(v.name) >= 0) stack = v.name === "home" ? [] : [{ name: "home" }];
    stack.push(v); draw();
  }
  function back() {                      // one step; false on the app's Home (Back goes to the box's Home there)
    if (!nowEl.hidden) { showNow(false); return true; }
    if (stack.length < 2) return false;
    if (top().name === "account" && acc.pairing) api("link", { cancel: true }).catch(() => {});
    stack.pop(); draw(top().key); return true;
  }

  function scope() { return nowEl.hidden ? $$("[data-f]").filter(e => !nowEl.contains(e) && e.getClientRects().length > 0) : $$("[data-f]", nowEl); }
  function move(dir) {
    const all = scope(), cur = ringOn && all.indexOf(ringOn) >= 0 ? ringOn : document.activeElement;
    if (!cur || all.indexOf(cur) < 0) { ring(all[0], true); return; }
    const c = cur.getBoundingClientRect(), horiz = dir === "left" || dir === "right";
    let best = null, bestScore = Infinity, bestLoose = null, looseScore = Infinity;
    for (const el of all) {
      if (el === cur) continue;
      const r = el.getBoundingClientRect();
      const ahead = dir === "left" ? c.left - r.right : dir === "right" ? r.left - c.right : dir === "up" ? c.top - r.bottom : r.top - c.bottom;
      if (ahead < -2) continue;
      const over = horiz ? Math.min(c.bottom, r.bottom) - Math.max(c.top, r.top) : Math.min(c.right, r.right) - Math.max(c.left, r.left);
      const side = horiz ? Math.abs(r.top - c.top) : Math.abs(r.left - c.left);
      if (over > 2) { const s = ahead * 4 + side; if (s < bestScore) { best = el; bestScore = s; } }
      else if (!horiz) { const s = ahead * 4 + side; if (s < looseScore) { bestLoose = el; looseScore = s; } }
    }
    const to = best || bestLoose;
    if (to) ring(to, true);
  }

  // ---- playing
  function playFrom(ctx, i) {
    let ids = (lists[ctx] || []).slice();
    if (!ids.length) return;
    if (i === "mix") { shuffle = true; i = Math.floor(Math.random() * ids.length); }
    const first = ids[i];
    if (shuffle) { ids = ids.filter(x => x !== first).sort(() => Math.random() - .5); ids.unshift(first); i = 0; }
    queue = ids; start(i);
  }
  function start(i) {
    if (!queue.length) return;
    qi = (i + queue.length) % queue.length;
    const t = byId[queue[qi]];
    if (!t) return;
    noted = null;
    audio.src = t.stream; audio.play().catch(() => {});
    session(t); drawBar(); if (!nowEl.hidden) drawNow();
    $$(".song.on", view).forEach(e => e.classList.remove("on"));
    $$(".song", view).filter(e => e.dataset.id === t.id).forEach(e => e.classList.add("on"));
  }
  const current = () => byId[queue[qi]];
  function toggle() { if (!current()) return; if (audio.paused) audio.play().catch(() => {}); else audio.pause(); }
  function step(n) { if (!current()) return; if (n < 0 && audio.currentTime > 4) { audio.currentTime = 0; return; } start(qi + n); }
  function seekBy(s) { if (current() && isFinite(audio.duration)) audio.currentTime = Math.max(0, Math.min(audio.duration - 1, audio.currentTime + s)); }

  function session(t) {
    const ms = navigator.mediaSession;
    if (!ms || !window.MediaMetadata) return;
    ms.metadata = new MediaMetadata({ title: t.title, artist: t.artist, album: "Edge Music", artwork: t.art ? [
      { src: art(t.art, 320), sizes: "320x320", type: "image/jpeg" }, { src: art(t.art, 640), sizes: "640x640", type: "image/jpeg" }] : [] });
  }
  if (navigator.mediaSession) {
    const ms = navigator.mediaSession, set = (a, fn) => { try { ms.setActionHandler(a, fn); } catch (e) { /* not in this browser */ } };
    set("play", () => audio.play().catch(() => {})); set("pause", () => audio.pause()); set("stop", () => audio.pause());
    set("previoustrack", () => step(-1)); set("nexttrack", () => step(1));
    set("seekbackward", d => seekBy(-(d.seekOffset || 10))); set("seekforward", d => seekBy(d.seekOffset || 10));
    set("seekto", d => { if (isFinite(d.seekTime)) audio.currentTime = d.seekTime; });
  }

  function drawBar() {
    const t = current();
    bar.hidden = !t || !nowEl.hidden;
    document.body.classList.toggle("playing", !!t);
    if (!t) return;
    bar.innerHTML = `${t.art ? `<img alt="" src="${esc(art(t.art, 160))}">` : "<i></i>"}<div><b>${esc(t.title)}</b><span>${esc(t.artist)}</span></div><em>${audio.paused ? "Paused" : "Playing"}</em>`;
  }
  function drawNow() {
    const t = current();
    if (!t) return;
    const up = byId[queue[(qi + 1) % queue.length]];
    const had = nowEl.contains(here()) ? here().dataset.k : null;   // the ring stays where it was
    nowEl.innerHTML = `${cover(t.art, 640, t.title)}<div><div class="kind">Now playing</div><h1>${esc(t.title)}</h1><div class="by">${esc(t.artist)}</div>` +
      `<button class="seek" data-f data-k="seek" data-seek aria-label="Left and right move through the song"><time id="at">0:00</time><i><u id="fill"></u></i><time id="len">${t.seconds ? clock(t.seconds) : ""}</time></button>` +
      `<div class="ctl"><button data-f data-k="prev" data-act="prev" aria-label="Previous">${ICON.prev}</button>` +
      `<button class="main" data-f data-k="pp" data-act="toggle" aria-label="Play or pause" id="pp">${audio.paused ? ICON.play : ICON.pause}</button>` +
      `<button data-f data-k="next" data-act="next" aria-label="Next">${ICON.next}</button>` +
      `<button data-f data-k="like" data-act="like" aria-label="Like" aria-pressed="${liked(t.id)}">${ICON.heart}</button>` +
      `<button data-f data-k="shuffle" data-act="shuffle" aria-label="Shuffle" aria-pressed="${shuffle}">${ICON.shuffle}</button></div>` +
      (up && queue.length > 1 ? `<div class="next">Next: <b>${esc(up.title)}</b> · ${esc(up.artist)}</div>` : "") + `</div>`;
    ring(had && $(`[data-k="${had}"]`, nowEl));
    tick(true);
  }
  let nowFrom = null;
  function showNow(on, focusKey) {
    if (on && !current()) return;
    if (on) { nowFrom = here(); nowEl.hidden = false; drawNow(); ring($(`[data-k="${focusKey || "pp"}"]`, nowEl)); }
    else { nowEl.hidden = true; nowEl.innerHTML = ""; if (nowFrom && document.contains(nowFrom)) ring(nowFrom); else focusOn(top().key); }
    drawBar();
  }
  let lastTick = 0;
  function tick(force) {
    if (nowEl.hidden) return;
    const n = Date.now();
    if (!force && n - lastTick < 900) return;      // once a second is plenty: every redraw is the CPU's
    lastTick = n;
    const at = $("#at"), fill = $("#fill"), len = $("#len"), d = isFinite(audio.duration) ? audio.duration : (current() || {}).seconds || 0;
    if (at) at.textContent = clock(audio.currentTime);
    if (len && d) len.textContent = clock(d);
    if (fill) fill.style.transform = "scaleX(" + (d ? Math.min(1, audio.currentTime / d) : 0) + ")";
  }
  function playState() {
    const pp = $("#pp"); if (pp) pp.innerHTML = audio.paused ? ICON.play : ICON.pause;
    drawBar();
    if (navigator.mediaSession) navigator.mediaSession.playbackState = current() ? (audio.paused ? "paused" : "playing") : "none";
  }
  audio.addEventListener("play", playState); audio.addEventListener("pause", playState);
  audio.addEventListener("playing", () => { fails = 0; });
  audio.addEventListener("ended", () => start(qi + 1));
  audio.addEventListener("timeupdate", () => {
    tick();
    const t = current();
    if (t && noted !== t.id && audio.currentTime > 20) {     // it was listened to: the account's Played lately
      noted = t.id;
      if (acc.linked && acc.canEdit) api("taste", { action: "played", id: t.id }).catch(() => {});
    }
    if (navigator.mediaSession && navigator.mediaSession.setPositionState && isFinite(audio.duration) && audio.duration > 0) {
      try { navigator.mediaSession.setPositionState({ duration: audio.duration, position: Math.min(audio.currentTime, audio.duration), playbackRate: 1 }); } catch (e) { /* a stream of no known length */ }
    }
  });
  audio.addEventListener("error", () => {
    if (!current()) return;
    fails += 1;
    if (fails >= 3 || queue.length < 2) { toast("Edge Music isn't playing right now. Try again in a while."); audio.removeAttribute("src"); playState(); return; }
    toast("That song wouldn't play. On to the next."); start(qi + 1);
  });

  async function like() {
    const t = current(); if (!t) return;
    if (!acc.linked) { toast("Sign in to keep the songs you like."); return; }
    const was = liked(t.id), btn = $('[data-act="like"]', nowEl);
    acc.likedIds = (acc.likedIds || []).filter(i => i !== t.id); if (!was) acc.likedIds.unshift(t.id);
    if (btn) btn.setAttribute("aria-pressed", String(!was));
    let r; try { r = await api("taste", { action: was ? "unlike" : "like", id: t.id }); } catch (e) { r = { ok: false, message: "The box isn't answering." }; }
    if (!r.ok) {                         // it wasn't saved: shown as it was
      acc.likedIds = acc.likedIds.filter(i => i !== t.id); if (was) acc.likedIds.unshift(t.id);
      if (btn) btn.setAttribute("aria-pressed", String(was));
      toast(r.message || "That wasn't saved.");
    }
  }

  // ---- signing in
  async function poll() {
    let r; try { r = await api("link/poll", {}); } catch (e) { return; }
    if (r.linked) { clearInterval(pollTimer); pollTimer = null; await account(); toast("Signed in" + (acc.name ? " as " + acc.name : "") + "."); go({ name: "home" }); }
    else if (!r.pairing) { acc.pairing = null; acc.message = r.message || "That code ran out. Get a new one."; if (top().name === "account") draw("code"); }
  }
  async function act(a) {
    if (a === "toggle") toggle(); else if (a === "prev") step(-1); else if (a === "next") step(1); else if (a === "like") like();
    else if (a === "shuffle") { shuffle = !shuffle; const b = $('[data-act="shuffle"]', nowEl); if (b) b.setAttribute("aria-pressed", String(shuffle)); }
    else if (a === "code") {
      let r; try { r = await api("link", {}); } catch (e) { r = { ok: false, message: "The box isn't answering." }; }
      if (r.linked) { await account(); draw(); return; }
      acc.pairing = r.pairing || null; acc.message = r.ok ? "" : r.message; draw(r.pairing ? "cancel" : "code");
    } else if (a === "cancel") { api("link", { cancel: true }).catch(() => {}); acc.pairing = null; acc.message = ""; draw("code"); }
    else if (a === "signout") { try { await api("unlink", {}); } catch (e) { /* asked again from Account */ } acc = { linked: false }; toast("Signed out of this box."); draw(); }
  }

  // ---- presses
  document.addEventListener("click", e => {
    const b = e.target.closest("button"); if (!b) return;
    const d = b.dataset;
    if (b === bar) showNow(true);
    else if (d.tab) go({ name: d.tab });
    else if (d.go) { const i = d.go.indexOf(":"); go({ name: "set", kind: d.go.slice(0, i), id: d.go.slice(i + 1), tab: top().tab || top().name }); }
    else if (d.ctx) { playFrom(d.ctx, d.i === "mix" ? "mix" : +d.i); if (d.k === "play" || d.k === "mix") showNow(true); }
    else if (d.key !== undefined) type(d.key);
    else if (d.act) act(d.act);
  });
  function type(k) {
    if (k === "del") query = query.slice(0, -1); else if (k === "clear") query = ""; else if (query.length < 40) query += k;
    const typed = $("#typed"), box = $("#found"); if (typed) typed.textContent = query; if (box) box.innerHTML = found();
  }
  const ARROW = { ArrowLeft: "left", ArrowRight: "right", ArrowUp: "up", ArrowDown: "down" };
  document.addEventListener("keydown", e => {
    const k = e.key, took = () => { e.preventDefault(); e.stopPropagation(); };
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (ARROW[k]) {
      took();
      const a = here();
      if (a && a.dataset && a.dataset.seek !== undefined && (k === "ArrowLeft" || k === "ArrowRight")) { seekBy(k === "ArrowLeft" ? -10 : 10); tick(true); return; }
      move(ARROW[k]); return;
    }
    if (k === "Enter" || k === "Select") {            // OK: the thing in the ring (however the remote's key arrives)
      const a = here();
      if (a && a.dataset && a.hasAttribute("data-f")) { took(); if (!e.repeat) a.click(); }
      return;
    }
    if (k === "MediaPlayPause" || k === "MediaPlay" || k === "MediaPause") { took(); toggle(); return; }
    if (k === "MediaTrackNext") { took(); step(1); return; }
    if (k === "MediaTrackPrevious") { took(); step(-1); return; }
    if (k === "MediaStop") { took(); audio.pause(); return; }
    const searching = nowEl.hidden && top().name === "search";
    if (searching && k === "Backspace" && query) { took(); type("del"); return; }
    if (k === "Escape" || k === "Backspace" || k === "BrowserBack" || k === "GoBack") {
      took();
      // On the app's Home, Back is the box's Home screen, asked for by name: left to the browser it would step back
      // through the tab's history to the empty page the tab began as, and the music would stop.
      if (!back() && !e.repeat) fetch("/box/api/home", { method: "POST", headers: { "Content-Type": "application/json", "X-Sofa-Box": "1" }, body: "{}" }).catch(() => {});
      return;
    }
    if (searching && k.length === 1 && /[\w \-'.&]/.test(k)) { took(); type(k.toUpperCase()); }
  });

  // ---- the catalogue and the account
  function setCatalog(c) {
    cat = { tracks: c.tracks || [], albums: c.albums || [], stations: c.stations || [], error: c.error };
    byId = {}; cat.tracks.forEach(t => { byId[t.id] = t; });
    const by = {};
    cat.tracks.forEach(t => { const n = t.artist || "Unknown"; (by[n] = by[n] || { name: n, ids: [], art: t.art }).ids.push(t.id); if (!by[n].art) by[n].art = t.art; });
    artists = Object.keys(by).map(n => by[n]).sort((a, b) => b.ids.length - a.ids.length);
  }
  async function account() { try { const a = await api("account"); acc = a && typeof a === "object" ? a : { linked: false }; } catch (e) { /* as it was */ } }
  let loadedAt = 0;
  async function load(first) {
    const a = here(), key = a && a.dataset ? a.dataset.k : null;
    try { const [c] = await Promise.all([api("catalog"), account()]); setCatalog(c); loadedAt = Date.now(); }
    catch (e) { if (first) setCatalog({ error: "The box isn't answering. Try again in a moment." }); else return; }
    if (first || top().name !== "account") draw(first ? null : key);
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden && Date.now() - loadedAt > 600000) load(false); });
  fetch("/box/api/apps").then(r => r.json()).then(d => { if (d && d.theme) document.documentElement.dataset.theme = d.theme; }).catch(() => {});
  draw(); load(true);
  window.EdgeMusicBox = { state: () => ({ view: top().name, stack: stack.length, playing: !!current() && !audio.paused, track: (current() || {}).id || null, queue: queue.length, now: !nowEl.hidden, linked: !!acc.linked }) };
})();
