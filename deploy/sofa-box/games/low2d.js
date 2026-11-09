/* Low2D: the Sofa Box's 2D engine, for the box's own page games drawn in pixels (480×270, scaled up crisp). One file,
   offline, no libraries. It loads after ../pad.js and ../low3d.js and builds on Low3D: the box's hardware probe and
   processor test (probe, bench), Input (the controller first, every controller a player, the box's echo keys
   dropped), Synth (sound and music made as it plays), its Governor, #demo and window.SofaStats (for the games check)
   and #slow=N. What it adds is the 2D part, the same for every game on it:
     game()     the pixel canvas fitted to the TV at a whole-number scale; a fixed-step loop; a light and a full tier
                picked for the box (a Pi 3 starts light) and held steady by a governor that steps down before a
                stutter shows; screen shake and hit-stop; a fade; menus, options and saves in one look; #fps,
                #tier=light|full, #test
     TileMap    tile maps drawn once into chunks and copied after; moving a box through them (solid, one-way)
     art()      sprites from rows of characters; sheet() keeps mirrored and flashed copies, made once
     Layer      backgrounds that scroll at their own pace, drawn once
     Particles  a fixed pool, drawn from a sheet of dots (nothing made while a game plays)
     Light      the dark with a hole cut for each light, coloured glows added on top, and bursts of light
     font       a pixel font with the controller's buttons in it; Label: a line drawn once and copied after
     Menu       screens of items worked with the controller (and the keys), drawn in the engine's look
     Store      saves and settings kept on the box (nothing kept in #demo)
   See ENGINE.md beside it. */
(function () {
"use strict";
if (window.Low2D) return;
const L3 = window.Low3D;
if (!L3) throw new Error("low2d.js needs ../low3d.js loaded first");
const U = L3.U, clamp = U.clamp;

function mk(w, h) { const c = document.createElement("canvas"); c.width = w; c.height = h; return c; }
function ctx(c) { const g = c && c.getContext ? c.getContext("2d") : null; if (g) g.imageSmoothingEnabled = false; return g; }

// ---------------------------------------------------------------- the looks, the pace, and keeping them steady
// The looks a game can have (it reads G.tier and decides what each one means for it):
//   light  the light map at a quarter of the screen's size, smoothed; a few coloured glows; fewer particles; the two
//          far background layers
//   full   the light map at half the size in dithered steps (the pixel look); every glow; all three layers; depth (a
//          block's side receding into the screen); a layer in front of the camera; reflections
//   rich   as full, with the light at the screen's own size, smooth; more particles and glows; more in the air
// each at 60 frames a second or a steady 30 (a frame on every other refresh, never one late: a steady 30 is better than
// an uneven 60). On its own a box goes rich 60, full 60, light 60, then full at a steady 30 (twice the time a frame is
// room for the full look), then light at 30, and never below 30. Options can hold the look, the pace or both.
const LOOKS = {
  light: { name: "light", light: 4, glows: 6, parts: 0.55, cap: 200, layers: 2, extras: 0, depth: 0, fore: 0, reflect: 0 },
  full: { name: "full", light: 2, glows: 40, parts: 1, cap: 480, layers: 3, extras: 1, depth: 1, fore: 1, reflect: 1 },
  rich: { name: "rich", light: 1, glows: 90, parts: 1.35, cap: 720, layers: 3, extras: 2, depth: 2, fore: 1, reflect: 1 }
};
const RANK = { light: 0, full: 1, rich: 2 };
const tier = (look, fps) => Object.assign({ fps }, LOOKS[look]);
// the ladder, low to high, for a look ("auto", "light", "full", "rich") and a pace ("auto", "60", "30")
function ladder(look, pace) {
  look = look || "auto"; pace = String(pace || "auto");
  if (look === "auto" && pace === "auto") return [tier("light", 30), tier("full", 30), tier("light", 60), tier("full", 60), tier("rich", 60)];
  if (look === "auto") return ["light", "full", "rich"].map(l => tier(l, +pace));
  if (pace === "auto") return [tier(look, 30), tier(look, 60)];
  return [tier(look, +pace)];
}
const TIERS = ladder("auto", "auto");
// the best rung with a look no richer than this one (the richest such look, then the faster pace)
function rungFor(lad, look) {
  let r = -1;
  for (let i = 0; i < lad.length; i++) {
    const k = RANK[lad[i].name]; if (k > RANK[look]) continue;
    if (r < 0 || k > RANK[lad[r].name] || (k === RANK[lad[r].name] && lad[i].fps > lad[r].fps)) r = i;
  }
  return r < 0 ? 0 : r;
}
// where a box starts on a ladder: {rung, top, why}. A Pi 3 (its GPU, or a 1 GB ARM board) starts light and climbs no
// higher at 60 (at a steady 30 it may have the full look); a slow processor (the test, as #slow makes it) starts light and
// may climb to full; a fast one with a GPU (a desktop, a Pi 5) starts rich; the rest start full and may climb.
function plan(p, b, slow, lad) {
  lad = lad || TIERS;
  const cpu = b && b.cpu != null ? Math.round(b.cpu * (slow || 1) * 10) / 10 : null, has60 = lad.some(t => t.fps === 60);
  let want = "full", top = "rich", why;
  if (p.family === "pi3" || (p.memory && p.memory <= 1 && /arm/.test(p.arch || ""))) { want = "light"; top = has60 ? "light" : "full"; why = p.family === "pi3" ? "a Pi 3" : "a small board (1 GB)"; }
  else if (cpu != null && cpu > 60) { want = "light"; top = "full"; why = "a slow processor (script " + cpu + " ms)"; }
  else if (cpu != null && cpu < 12 && p.webgl1 && !p.software) { want = "rich"; why = "a fast processor (script " + cpu + " ms) and a GPU"; }
  else why = cpu != null ? "room to spare (script " + cpu + " ms)" : "no test";
  const rung = rungFor(lad, want);
  return { rung, top: Math.max(rung, rungFor(lad, top)), why };
}
// Low3D's Governor, judging by the slow frames before they're late: the 90th percentile of the frame's own work in
// each 2 s window. Over 70% of the frame (or late frames, 6% of them): a rung down, before a stutter shows. Three
// calm windows (no late frames, under 35%): a rung up, but never back to one that failed twice.
function Governor(ladder, rung, top, change) {
  L3.Governor.call(this, ladder, rung, top, change);
  this.ring = new Float32Array(256); this.rn = 0; this.sorted = new Float32Array(256); this.fails = new Uint8Array(ladder.length); this.p90 = 0;
}
Governor.prototype = Object.create(L3.Governor.prototype);
Governor.prototype.constructor = Governor;
Governor.prototype.work = function (ms) {
  L3.Governor.prototype.work.call(this, ms);
  if (this.rn < 256 && performance.now() >= this.wait) this.ring[this.rn++] = ms;
};
Governor.prototype.reset = function (now) { L3.Governor.prototype.reset.call(this, now); this.rn = 0; };
Governor.prototype.hold = function (ms) { L3.Governor.prototype.hold.call(this, ms); this.rn = 0; };
Governor.prototype.judge = function (now, iv) {
  const n = this.n, lateK = n ? this.late / n : 0;
  let p90 = 0;
  if (this.rn) { const s = this.sorted.subarray(0, this.rn); s.set(this.ring.subarray(0, this.rn)); s.sort(); p90 = s[Math.min(this.rn - 1, Math.floor(this.rn * 0.9))]; }
  this.p90 = p90; this.win = now; this.n = 0; this.late = 0; this.workSum = 0; this.rn = 0;
  if (this.lock) return;
  const busy = p90 > iv * 0.7;
  if ((lateK > 0.06 || busy) && this.rung > 0) {
    this.fails[this.rung]++;
    if (this.fails[this.rung] >= 2 || this.quiet) this.top = Math.min(this.top, this.rung - 1);   // (not up there again)
    this.set(this.rung - 1, busy ? "busy " + p90.toFixed(1) + " ms of " + Math.round(iv) : "late " + Math.round(lateK * 100) + "%", now);
    this.calm = 0; this.quiet = 0;
  } else if (lateK === 0 && p90 < iv * 0.35) {
    this.calm++; if (this.quiet) this.quiet--;
    if (this.calm >= 3 && this.rung < this.top && this.fails[this.rung + 1] < 2) { this.set(this.rung + 1, "room to spare", now); this.calm = 0; this.quiet = 2; }
  } else { this.calm = 0; if (this.quiet) this.quiet--; }
};

// ---------------------------------------------------------------- a game: the canvas, the tier, the loop, the input
// Low2D.game({ id, canvas, w, h, keys: {key: button}, on(b, how, who), update(dt), draw(g, G), paused(), tier(G, t),
//   ready(G), hidden(), joined(n), left(n), menu: {...Menu's options} }) → G. Keys and the controller's buttons share
// names: a b x y lb rb lt rt start select up down left right, and back (a remote's Back, Escape, Backspace).
const BASEKEYS = { Enter: "a", NumpadEnter: "a", Escape: "back", Backspace: "back", BrowserBack: "back", GoBack: "back",
  ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right" };
const DEFAULTS = { music: 6, sound: 8, rumble: 1, shake: 2, fx: "auto", pace: "auto" };
const BOX = "sofa:box";                              // (what the box is and its test, shared by every game on the engine)
function game(o) {
  const H = location.hash || "", W = o.w || 480, HH = o.h || 270;
  const G = {
    o, w: W, h: HH, DT: 1 / 60, ready: false, frame: 0, time: 0, steps: 0,
    test: /(^|[#&-])test\b/.test(H), demo: /(^|[#&-])demo\b/.test(H), showFps: /(^|[#&-])fps\b/.test(H),
    slow: /slow=(\d+)/.test(H) ? Math.max(1, +H.match(/slow=(\d+)/)[1]) : 1,
    force: (H.match(/tier=(light|full|rich)/) || [])[1] || null, forcePace: (H.match(/pace=(30|60)/) || [])[1] || null,
    ox: 0, oy: 0, trauma: 0, stopT: 0, fadeK: 0, fadeV: 0, fadeFn: null, zoom: 1, zoomTo: 1, zoomK: 4, tilt: 0, tiltV: 0, zx: W / 2, zy: HH / 2, off: null,
    opts: Object.assign({}, DEFAULTS), probe: null, bench: null, plan: null, gov: null, ladder: TIERS, tier: TIERS[3], rung: 3,
    canvas: o.canvas, g: null, synth: new L3.Synth(), menu: null
  };
  const cv = o.canvas;
  cv.width = W; cv.height = HH;
  G.g = cv.getContext ? cv.getContext("2d", { alpha: false }) : null;
  if (G.g) G.g.imageSmoothingEnabled = false;
  // the TV: a whole-number scale when it fills enough of the screen (crisp, every pixel the same size); otherwise
  // (a 720p TV: 2.67) as big as fits, still drawn without smoothing
  G.fit = () => {
    const d = devicePixelRatio || 1, sw = innerWidth * d, sh = innerHeight * d, fit = Math.min(sw / W, sh / HH);
    let s = Math.floor(fit); if (s < 1 || s * HH < sh * 0.8 && s * W < sw * 0.8) s = fit;
    const w = W * s / d, h = HH * s / d;
    Object.assign(cv.style, { width: w + "px", height: h + "px", left: Math.round((innerWidth - w) / 2) + "px", top: Math.round((innerHeight - h) / 2) + "px" });
    G.scale = s;
  };
  // the box's tuning: what the browser is (Low3D's probe) and the processor test, once per box and browser for every game
  // on the engine (kept as "sofa:box"); each game keeps where its own governor settled
  const KEY = (o.id || "game") + ":tune2d";
  const load = k => { try { return JSON.parse(localStorage.getItem(k) || "null"); } catch (e) { return null; } };
  const keep = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* it still plays */ } };
  let tune = load(KEY);
  G.look = () => G.force || G.opts.fx || "auto";
  G.pace = () => G.forcePace || G.opts.pace || "auto";
  G.remember = () => { if (G.demo || G.force || G.forcePace) return; tune = { key: G.probe.key, ladder: G.look() + "/" + G.pace(), rung: G.gov.rung, top: G.gov.top }; keep(KEY, tune); };
  G.setTier = (r, why) => {
    G.rung = r; G.tier = G.ladder[r];
    if (o.tier) o.tier(G, G.tier);
    if (why) G.remember();
  };
  G.governor = () => {                                // the ladder from Options (or #tier, #pace), where to start, how high
    const look = G.look(), pace = G.pace();
    G.ladder = ladder(look, pace); G.plan = plan(G.probe, G.bench, G.slow, G.ladder);
    let start = G.plan.rung, top = G.plan.top;
    if (tune && tune.key === G.probe.key && tune.ladder === look + "/" + pace && tune.rung != null) { start = clamp(tune.rung, 0, G.ladder.length - 1); top = clamp(tune.top, start, G.ladder.length - 1); }
    G.gov = new Governor(G.ladder, start, top, (r, why) => G.setTier(r, why));
    if (G.ladder.length === 1) G.gov.lock = true;
    G.setTier(start, null);
    G.gov.hold(1500);
  };
  G.rows = () => [["What it is", G.probe ? G.probe.name : "–"], ["Test", G.bench ? "script " + G.bench.cpu + " ms" : "–"],
    ["Chose", G.plan ? G.ladder[G.plan.rung].name + " at " + G.ladder[G.plan.rung].fps + ": " + G.plan.why : "–"],
    ["Now", G.tier.name + ", " + G.tier.fps + " a second wanted, " + (G.gov ? G.gov.fps : 0) + " drawn"],
    ["Changes", G.gov && G.gov.log.length ? G.gov.log.slice(-3).join(" · ") : "none yet"]];
  // #demo, for the games check: the game sets SofaStats.demo when it plays itself
  window.SofaStats = {
    get ready() { return G.ready; },
    get tier() { return G.ready ? "2D " + G.tier.name + ", " + G.tier.fps + " fps (rung " + G.rung + " of " + (G.ladder.length - 1) + ")" : null; },
    get fps() { return G.gov ? G.gov.fps : 0; },
    get workMs() { return G.gov ? Math.round(G.gov.workMs * 100) / 100 : 0; },
    demo: false
  };
  // shake (it grows with each knock and fades; Options: off, gentle, full), hit-stop (the world holds a moment), a fade
  G.shake = k => { const m = G.opts.shake === 0 ? 0 : G.opts.shake === 1 ? 0.5 : 1; if (m) G.trauma = Math.min(1, G.trauma + k * m); };
  G.stop = ms => { G.stopT = Math.max(G.stopT, Math.min(0.12, ms / 1000)); };
  G.fade = (fn, speed) => { if (G.fadeFn) return; G.fadeFn = fn || (() => {}); G.fadeV = speed || 4; };
  // the camera's moments: zoom(to, x, y, speed) leans in on a point (1: back to the whole view); tilt(a) knocks it
  // round a little (radians, springing back). Off with screen shake.
  G.zoomOn = (to, x, y, k) => { G.zoomTo = to; if (x != null) { G.zx = x; G.zy = y; } G.zoomK = k || 4; };
  G.tiltBy = a => { if (G.opts.shake) G.tiltV += a * (G.opts.shake === 1 ? 0.5 : 1); };
  G.rumble = (s, w, ms, who) => { if (!G.opts.rumble || G.demo) return; const p = who ? G.input.player(who) : window.SofaPad; if (p && p.rumble) p.rumble(s, w, ms); };
  G.options = (opts) => {                              // the engine's own options: volumes, rumble, shake, the look, the pace
    const was = G.opts.fx + "/" + G.opts.pace;
    Object.assign(G.opts, opts || {});
    G.synth.volume(G.opts.music / 10, G.opts.sound / 10);
    if (G.gov && G.opts.fx + "/" + G.opts.pace !== was) G.governor();
  };

  // input: Low3D's (the controller first, every controller a player, the box's echo keys dropped), with each press
  // kept a moment so a game reading the controller in its fixed steps never misses one (and can buffer a jump)
  const presses = [{}, {}, {}, {}, {}];               // [who][button] = when (who 0: a key, the remote, the phone)
  G.pressAt = presses;
  G.input = new L3.Input({
    keys: Object.assign({}, BASEKEYS, o.keys || {}), top: () => G.menu ? G.menu.top() : 0,
    on(b, how, who) {
      G.synth.start();
      if (G.demo) return;                              // (the demo takes no controller: the games check is using it)
      if (how === "press") { const at = performance.now(); presses[0][b] = at; if (who > 0 && who < 5) presses[who][b] = at; }
      if (G.menu && G.menu.at && G.menu.button(b, how, who)) return;
      if (o.on) o.on(b, how, who);
    },
    joined: n => { if (o.joined) o.joined(n); }, left: n => { if (o.left) o.left(n); }
  });
  G.control = n => new Control(G, n || 0);
  G.label = b => G.input.label(b, Object.assign({ a: "ENTER", b: "ESC", start: "P", back: "ESC" }, o.keyNames || {}));

  // the loop: fixed steps of 1/60 s (snapped to the frame when it's a whole number of them: no judder at 60 or 30
  // a second), hit-stop, the drawing, then the governor
  let last = 0, acc = 0, fpsAt = 0, fpsLabel = null;
  function frame(now) {
    requestAnimationFrame(frame);
    if (!G.ready) return;
    G.input.tick(now);
    if (!G.gov.tick(now)) return;
    const t0 = performance.now();
    let dt = (now - last) / 1000; last = now; if (!(dt > 0)) dt = 0; if (dt > 0.1) dt = 0.1;
    G.frame++;
    if (!(o.paused && o.paused())) {
      if (G.stopT > 0) G.stopT -= dt;
      else {
        acc += dt;
        const k = Math.round(acc / G.DT);
        if (k >= 1 && Math.abs(acc - k * G.DT) < 0.0025) acc = k * G.DT;   // (a whole number of steps: take them all)
        let n = 0;
        while (acc >= G.DT - 1e-6 && n < 4) { o.update(G.DT); G.time += G.DT; G.steps++; acc -= G.DT; n++; }
        if (n === 4) acc = 0;
      }
    }
    if (G.trauma > 0) {
      G.trauma = Math.max(0, G.trauma - dt * 1.8);
      const t = G.trauma * G.trauma * 6, f = G.frame;
      G.ox = Math.round(t * Math.sin(f * 1.7 + 0.3) * Math.cos(f * 0.61)); G.oy = Math.round(t * Math.sin(f * 1.31 + 1.1) * Math.cos(f * 0.47 + 0.5));
    } else { G.ox = 0; G.oy = 0; }
    if (G.zoom !== G.zoomTo) { G.zoom += (G.zoomTo - G.zoom) * Math.min(1, dt * G.zoomK); if (Math.abs(G.zoom - G.zoomTo) < 0.002) G.zoom = G.zoomTo; }
    if (G.tilt || G.tiltV) { G.tiltV -= G.tilt * 90 * dt; G.tiltV *= Math.max(0, 1 - 9 * dt); G.tilt += G.tiltV * dt; if (Math.abs(G.tilt) < 0.0005 && Math.abs(G.tiltV) < 0.002) { G.tilt = 0; G.tiltV = 0; } }
    if (G.g) {
      if (G.zoom !== 1 || G.tilt) {                  // the world into its own picture, then through the camera's turn and lean
        if (!G.off) { G.off = mk(W, HH); G.offG = ctx(G.off); }
        o.draw(G.offG, G);
        const g = G.g; g.save(); g.fillStyle = "#000"; g.fillRect(0, 0, W, HH);
        g.translate(G.zx, G.zy); g.rotate(G.tilt); g.scale(G.zoom, G.zoom); g.translate(-G.zx, -G.zy);
        g.drawImage(G.off, 0, 0); g.restore();
      } else o.draw(G.g, G);
      if (o.hud) o.hud(G.g, G);
      if (G.menu && G.menu.at) G.menu.draw(G.g);
      if (G.fadeV) {                                   // the fade: to black, the change, back
        G.fadeK += G.fadeV * dt;
        if (G.fadeV > 0 && G.fadeK >= 1) { G.fadeK = 1; G.fadeV = -G.fadeV; const f = G.fadeFn; G.fadeFn = null; if (f) f(); G.gov.hold(800); }
        else if (G.fadeV < 0 && G.fadeK <= 0) { G.fadeK = 0; G.fadeV = 0; }
      }
      if (G.fadeK > 0) { G.g.globalAlpha = Math.min(1, G.fadeK); G.g.fillStyle = "#000"; G.g.fillRect(0, 0, W, HH); G.g.globalAlpha = 1; }
      if (G.showFps) {
        if (!fpsLabel) fpsLabel = new Label(160);
        if (now - fpsAt > 500) { fpsAt = now; fpsLabel.set(G.gov.fps + " FPS " + G.tier.name.toUpperCase() + " " + G.tier.fps + " " + G.gov.workMs.toFixed(2) + " MS", 0); }
        fpsLabel.draw(G.g, W - fpsLabel.w - 2, 2);
      }
    }
    if (G.slow > 1) { const until = performance.now() + (performance.now() - t0) * (G.slow - 1); while (performance.now() < until) { /* #slow: as a slower processor would */ } }
    G.gov.work(performance.now() - t0);
  }
  G.start = () => {
    G.fit(); addEventListener("resize", G.fit);
    G.probe = L3.probe();
    const go = () => {
      G.governor();
      G.options(null);
      if (o.ready) o.ready(G);
      G.ready = true; last = performance.now(); G.gov.hold(1500);
    };
    const box = load(BOX);
    if (box && box.key === G.probe.key && box.bench) { G.bench = box.bench; go(); }
    else L3.bench(null, r => { G.bench = r; if (!G.demo) keep(BOX, { key: G.probe.key, bench: r }); go(); });
    document.addEventListener("visibilitychange", () => { if (document.hidden && o.hidden) o.hidden(); });
    addEventListener("pointerdown", () => G.synth.start());
    requestAnimationFrame(frame);
    return G;
  };
  return G;
}

// one player's controller and (for player 1 and "anyone", 0) the keys: what a game reads in its fixed steps.
// x() and y(): the stick, the D-pad or the arrows, -1..1. take(b, ms): b was pressed in the last ms (120: a buffered
// jump) and not taken yet.
function Control(G, n) { this.G = G; this.n = n; this.taken = {}; }
Control.prototype = {
  pad() { return this.n ? this.G.input.player(this.n) : null; },
  held(b) { const p = this.pad(); return p ? p.held(b) || (this.n === 1 && this.G.input.key(b)) : this.G.input.held(b); },
  x() {
    const p = this.pad(), s = p ? p.stick() : this.G.input.stick();
    let x = Math.abs(s.x) > 0.25 ? s.x : 0;
    if (this.held("left")) x = -1; else if (this.held("right")) x = 1;
    return clamp(x, -1, 1);
  },
  y() {
    const p = this.pad(), s = p ? p.stick() : this.G.input.stick();
    let y = Math.abs(s.y) > 0.4 ? s.y : 0;
    if (this.held("up")) y = -1; else if (this.held("down")) y = 1;
    return clamp(y, -1, 1);
  },
  take(b, ms) {
    const t = this.G.pressAt[this.n > 0 && this.n < 5 ? this.n : 0][b];
    if (t == null || this.taken[b] === t || performance.now() - t > (ms || 120)) return false;
    this.taken[b] = t; return true;
  },
  rumble(s, w, ms) { this.G.rumble(s, w, ms, this.n); }
};

// ---------------------------------------------------------------- tile maps: drawn into chunks once, copied after
// TileMap(w, h, ts): t (a kind a tile), flags[kind] (SOLID, ONEWAY, HURT, and the game's own from 16 up), paint(g,
// tx, ty, kind, map, px, py) to draw a tile into a chunk at px py (it may look at its neighbours; up to a tile over
// its edges is kept). build() makes every chunk (at a level's start), draw(g, camX, camY) copies the ones in view
// (a changed tile's chunk is drawn again). move(body, dx, dy, drop) moves a box (x, y: the middle of its bottom
// edge; w, h) through the solid tiles, one-way tiles holding it from above unless it drops.
const SOLID = 1, ONEWAY = 2, HURT = 4;
const LEFT = 1, RIGHT = 2, UP = 4, DOWN = 8;
const CHUNKS = [], SILS = [];                          // (chunk canvases, kept from level to level)
function TileMap(w, h, ts) {
  this.w = w; this.h = h; this.ts = ts || 16; this.t = new Uint8Array(w * h); this.flags = new Uint8Array(256);
  this.CS = 16; this.cw = Math.ceil(w / this.CS); this.ch = Math.ceil(h / this.CS);
  this.chunks = new Array(this.cw * this.ch).fill(null); this.dirty = new Uint8Array(this.cw * this.ch).fill(1);
  this.paint = null; this.outside = 1; this.hitX = 0; this.hitY = 0;
}
TileMap.prototype = {
  at(x, y) { return x < 0 || y < 0 || x >= this.w || y >= this.h ? (y >= this.h ? 0 : this.outside) : this.t[y * this.w + x]; },
  flag(x, y) { return this.flags[this.at(x, y)]; },
  set(x, y, k) {
    if (x < 0 || y < 0 || x >= this.w || y >= this.h) return;
    this.t[y * this.w + x] = k;
    const done = this.done || (this.done = new Int32Array(4));
    let n = 0;
    for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {   // (its neighbours are drawn by it too)
      const cx = Math.floor((x + dx) / this.CS), cy = Math.floor((y + dy) / this.CS);
      if (cx < 0 || cy < 0 || cx >= this.cw || cy >= this.ch) continue;
      const i = cy * this.cw + cx; let seen = false; for (let q = 0; q < n; q++) if (done[q] === i) seen = true;
      if (seen) continue; done[n++] = i;
      if (this.chunks[i] && !this.dirty[i]) this.repaint(i, x, y); else this.dirty[i] = 1;
    }
  },
  // the tiles round (x, y) drawn again where they are in chunk i: a few tiles, not the chunk (no stall when a wall breaks)
  repaint(i, x, y) {
    const c = this.chunks[i], g = ctx(c); if (!g) return;
    const ts = this.ts, cx = i % this.cw, cy = (i / this.cw) | 0, x0 = cx * this.CS, y0 = cy * this.CS;
    const rx = (x - 1 - x0) * ts, ry = (y - 1 - y0) * ts;
    g.save(); g.beginPath(); g.rect(rx, ry, 3 * ts, 3 * ts); g.clip(); g.clearRect(rx, ry, 3 * ts, 3 * ts);
    if (this.paint) for (let ty = y - 2; ty <= y + 2; ty++) for (let tx = x - 2; tx <= x + 2; tx++) {
      if (tx < 0 || ty < 0 || tx >= this.w || ty >= this.h) continue;
      const k = this.t[ty * this.w + tx]; if (k) this.paint(g, tx, ty, k, this, (tx - x0) * ts, (ty - y0) * ts);
    }
    g.restore();
    if (this.sils) for (const col in this.sils) if (this.sils[col][i]) this.sils[col][i].stale = true;
  },
  // depth: the blocks' far faces, each chunk's shape in one dark colour, drawn smaller towards the middle of the view (k:
  // how far back, 0.03 to 0.08), before the tiles themselves, so a platform shows its side as the camera passes it
  drawDepth(g, camX, camY, vw, vh, k, col) {
    const S = this.CS * this.ts, mx = vw / 2, my = vh / 2, s = 1 - k, size = Math.ceil(S * s) + 1;
    if (!this.sils) this.sils = {};
    const sils = this.sils[col] || (this.sils[col] = []);   // (one set of shapes a colour: made once, kept)
    const cx0 = Math.max(0, Math.floor((camX + mx - mx / s) / S)), cy0 = Math.max(0, Math.floor((camY + my - my / s) / S));
    const cx1 = Math.min(this.cw - 1, Math.floor((camX + mx + (vw - mx) / s) / S)), cy1 = Math.min(this.ch - 1, Math.floor((camY + my + (vh - my) / s) / S));
    for (let cy = cy0; cy <= cy1; cy++) for (let cx = cx0; cx <= cx1; cx++) {
      const i = cy * this.cw + cx;
      if (this.dirty[i] || !this.chunks[i]) this.make(i);
      let sl = sils[i];
      if (!sl || sl.stale) {
        if (!sl) sl = sils[i] = SILS.pop() || mk(S, S);
        const sg = ctx(sl); if (!sg) continue;
        sg.globalCompositeOperation = "source-over"; sg.clearRect(0, 0, S, S); sg.drawImage(this.chunks[i], 0, 0);
        sg.globalCompositeOperation = "source-in"; sg.fillStyle = col; sg.fillRect(0, 0, S, S); sg.globalCompositeOperation = "source-over";
        sl.stale = false;
      }
      g.drawImage(sl, Math.round((cx * S - camX - mx) * s + mx), Math.round((cy * S - camY - my) * s + my), size, size);
    }
  },
  solidAt(px, py) { return (this.flag(Math.floor(px / this.ts), Math.floor(py / this.ts)) & SOLID) !== 0; },
  make(i) {
    let c = this.chunks[i];
    const S = this.CS * this.ts;
    if (!c) { c = this.chunks[i] = CHUNKS.pop() || mk(S, S); }
    const g = ctx(c); if (!g) return;
    g.clearRect(0, 0, S, S);
    const cx = i % this.cw, cy = (i / this.cw) | 0, x0 = cx * this.CS, y0 = cy * this.CS;
    if (this.paint) for (let y = y0 - 1; y <= y0 + this.CS; y++) for (let x = x0 - 1; x <= x0 + this.CS; x++) {
      if (x < 0 || y < 0 || x >= this.w || y >= this.h) continue;
      const k = this.t[y * this.w + x]; if (k) this.paint(g, x, y, k, this, (x - x0) * this.ts, (y - y0) * this.ts);
    }
    this.dirty[i] = 0;
  },
  build() { for (let i = 0; i < this.chunks.length; i++) this.make(i); },
  draw(g, camX, camY, vw, vh) {
    const S = this.CS * this.ts; vw = vw || 480; vh = vh || 270;
    const cx0 = Math.max(0, Math.floor(camX / S)), cy0 = Math.max(0, Math.floor(camY / S));
    const cx1 = Math.min(this.cw - 1, Math.floor((camX + vw - 1) / S)), cy1 = Math.min(this.ch - 1, Math.floor((camY + vh - 1) / S));
    for (let cy = cy0; cy <= cy1; cy++) for (let cx = cx0; cx <= cx1; cx++) {
      const i = cy * this.cw + cx;
      if (this.dirty[i] || !this.chunks[i]) this.make(i);
      if (this.chunks[i]) g.drawImage(this.chunks[i], cx * S - camX, cy * S - camY);
    }
  },
  free() {
    for (const c of this.chunks) if (c && CHUNKS.length < 48) CHUNKS.push(c);
    if (this.sils) for (const col in this.sils) for (const c of this.sils[col]) if (c && SILS.length < 64) SILS.push(c);
    this.chunks.fill(null); this.dirty.fill(1); this.sils = null;
  },
  // what's under a box, or touching it: the first tile with one of the flags, as its index (or -1)
  touch(b, mask, grow) {
    const ts = this.ts, e = grow || 0;
    const x0 = Math.floor((b.x - b.w / 2 - e) / ts), x1 = Math.floor((b.x + b.w / 2 + e - 0.01) / ts);
    const y0 = Math.floor((b.y - b.h - e) / ts), y1 = Math.floor((b.y + e - 0.01) / ts);
    for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) if (this.flag(x, y) & mask) { this.hitX = x; this.hitY = y; return y * this.w + x; }
    return -1;
  },
  ground(b, drop) {                                   // standing on something (solid, or a one-way tile unless dropping)?
    const ts = this.ts, y = Math.floor((b.y + 0.5) / ts);
    if (Math.abs(b.y - y * ts) > 0.5) return false;
    const x0 = Math.floor((b.x - b.w / 2) / ts), x1 = Math.floor((b.x + b.w / 2 - 0.01) / ts);
    for (let x = x0; x <= x1; x++) { const f = this.flag(x, y); if (f & SOLID || (f & ONEWAY && !drop)) return true; }
    return false;
  },
  move(b, dx, dy, drop) {
    const ts = this.ts, hw = b.w / 2;
    let hit = 0;
    // across, in steps no longer than half a tile (a dash can't pass through a wall)
    let left = dx;
    while (left !== 0) {
      const s = Math.abs(left) > ts / 2 ? Math.sign(left) * ts / 2 : left; left -= s;
      const nx = b.x + s, y0 = Math.floor((b.y - b.h) / ts), y1 = Math.floor((b.y - 0.01) / ts);
      if (s > 0) {
        const col = Math.floor((nx + hw - 0.01) / ts); let block = false;
        for (let y = y0; y <= y1; y++) if (this.flag(col, y) & SOLID) { block = true; this.hitX = col; this.hitY = y; break; }
        if (block) { b.x = col * ts - hw; hit |= RIGHT; left = 0; } else b.x = nx;
      } else {
        const col = Math.floor((nx - hw) / ts); let block = false;
        for (let y = y0; y <= y1; y++) if (this.flag(col, y) & SOLID) { block = true; this.hitX = col; this.hitY = y; break; }
        if (block) { b.x = (col + 1) * ts + hw; hit |= LEFT; left = 0; } else b.x = nx;
      }
    }
    // up and down
    left = dy;
    while (left !== 0) {
      const s = Math.abs(left) > ts / 2 ? Math.sign(left) * ts / 2 : left; left -= s;
      const ny = b.y + s, x0 = Math.floor((b.x - hw) / ts), x1 = Math.floor((b.x + hw - 0.01) / ts);
      if (s > 0) {
        const row = Math.floor((ny - 0.01) / ts), top = row * ts; let block = false;
        if (b.y <= top + 0.01 || row !== Math.floor((b.y - 0.01) / ts)) {
          for (let x = x0; x <= x1; x++) { const f = this.flag(x, row); if (f & SOLID || (f & ONEWAY && !drop && b.y <= top + 0.01)) { block = true; this.hitX = x; this.hitY = row; break; } }
        }
        if (block) { b.y = top; hit |= DOWN; left = 0; } else b.y = ny;
      } else {
        const row = Math.floor((ny - b.h) / ts); let block = false;
        for (let x = x0; x <= x1; x++) if (this.flag(x, row) & SOLID) { block = true; this.hitX = x; this.hitY = row; break; }
        if (block) { b.y = (row + 1) * ts + b.h; hit |= UP; left = 0; } else b.y = ny;
      }
    }
    return hit;
  }
};

// ---------------------------------------------------------------- sprites: pixel art from rows of characters
// art(rows, pal): each character a colour from pal (".", " " clear), a canvas. sheet(frames, pal, {ax, ay}) keeps
// each frame facing right and left, and as a flash (white, or o.flash), with an anchor (feet in the middle by
// default). put(g, sheet, frame, x, y, face, flash) draws one at whole pixels.
function art(rows, pal) {
  let w = 0; for (const r of rows) w = Math.max(w, r.length);
  const c = mk(w, rows.length), g = ctx(c); if (!g) return c;
  let last = null;
  for (let y = 0; y < rows.length; y++) for (let x = 0; x < rows[y].length; x++) {
    const ch = rows[y][x]; if (ch === "." || ch === " ") continue;
    const col = pal[ch]; if (!col) continue;
    if (col !== last) { g.fillStyle = col; last = col; }
    g.fillRect(x, y, 1, 1);
  }
  return c;
}
function flip(src) { const c = mk(src.width, src.height), g = ctx(c); if (g) { g.translate(src.width, 0); g.scale(-1, 1); g.drawImage(src, 0, 0); } return c; }
function silhouette(src, col) {
  const c = mk(src.width, src.height), g = ctx(c); if (!g) return c;
  g.drawImage(src, 0, 0); g.globalCompositeOperation = "source-in"; g.fillStyle = col || "#fff"; g.fillRect(0, 0, c.width, c.height); return c;
}
function outline(src, col) {                         // a 1-pixel edge round it (a sprite that must stand out)
  const c = mk(src.width + 2, src.height + 2), g = ctx(c); if (!g) return c;
  const s = silhouette(src, col || "#000");
  for (const [dx, dy] of [[0, 1], [2, 1], [1, 0], [1, 2]]) g.drawImage(s, dx, dy);
  g.drawImage(src, 1, 1); return c;
}
function sheet(frames, pal, o) {
  o = o || {};
  const r = frames.map(f => f.getContext ? f : art(f, pal));
  const s = { r, l: r.map(flip), fr: null, fl: null, w: r[0].width, h: r[0].height };
  s.fr = r.map(c => silhouette(c, o.flash || "#fff")); s.fl = s.fr.map(flip);
  s.ax = o.ax == null ? s.w >> 1 : o.ax; s.ay = o.ay == null ? s.h : o.ay;
  return s;
}
function put(g, s, f, x, y, face, flash) {
  f = f % s.r.length;
  const img = flash ? (face < 0 ? s.fl[f] : s.fr[f]) : (face < 0 ? s.l[f] : s.r[f]);
  g.drawImage(img, Math.round(x - (face < 0 ? s.w - s.ax : s.ax)), Math.round(y - s.ay));
}

// ---------------------------------------------------------------- backgrounds that scroll at their own pace
// Layer(w, h, paint(g, w, h), {k: how fast it moves with the camera across (0 far … 1 near), ky: and up and down, y})
// is drawn once into a strip w wide that repeats across; draw(g, camX, camY, vw) copies it into view.
function Layer(w, h, paint, o) {
  o = o || {};
  this.w = w; this.h = h; this.k = o.k == null ? 0.5 : o.k; this.ky = o.ky || 0; this.y = o.y || 0; this.c = mk(w, h);
  const g = ctx(this.c); if (g && paint) paint(g, w, h);
}
Layer.prototype.draw = function (g, camX, camY, vw) {
  vw = vw || 480;
  let x = -((camX * this.k) % this.w); if (x > 0) x -= this.w;
  x = Math.round(x); const y = Math.round(this.y - (camY || 0) * this.ky);
  for (; x < vw; x += this.w) g.drawImage(this.c, x, y);
};
// still water: the strip of the picture above y (h high) mirrored under it, faded, in slices that sway with t
function reflect(g, x, y, w, h, alpha, t) {
  const c = g.canvas, W = c.width, H = c.height;
  x = Math.max(0, Math.round(x)); w = Math.min(W - x, Math.round(w)); y = Math.round(y); h = Math.min(Math.round(h), y, H - y);
  if (w <= 0 || h <= 0) return;
  g.save(); g.globalAlpha = alpha;
  for (let r = 0; r < h; r += 4) {
    const sh = Math.min(4, h - r), dx = t == null ? 0 : Math.round(Math.sin(t * 2.2 + (y + r) * 0.45) * (1 + r / 12));
    g.drawImage(c, x, y - r - sh, w, sh, x + dx, y + r, w, sh);   // (each slice flipped as a whole: close enough, and cheap)
  }
  g.restore();
}
// a sky, top to bottom through the colours given (a picture, drawn once)
function gradient(w, h, stops) {
  const c = mk(w, h), g = ctx(c); if (!g) return c;
  const gr = g.createLinearGradient(0, 0, 0, h); stops.forEach((s, i) => gr.addColorStop(i / Math.max(1, stops.length - 1), s));
  g.fillStyle = gr; g.fillRect(0, 0, w, h); return c;
}

// ---------------------------------------------------------------- particles: a fixed pool, drawn from a sheet of dots
// dots(colours) makes the sheet once: each colour at four strengths and three sizes. Particles(max, dots): emit(x, y,
// n, {c: a colour's place or a list of them, v: speed, a: direction (radians), sp: spread, life, g: gravity, drag,
// s: size 1-3, up: added upward speed, bright: drawn over the dark}); step(dt); draw(g, camX, camY, bright).
// k (the share of each burst made) and cap (how many at once) follow the tier.
function dots(cols) {
  const c = mk(48, cols.length * 4), g = ctx(c);
  if (g) cols.forEach((col, i) => { g.fillStyle = col; [1, 0.72, 0.46, 0.22].forEach((a, k) => { g.globalAlpha = a; for (let s = 1; s <= 3; s++) g.fillRect(k * 12 + (s - 1) * 4, i * 4, s, s); }); g.globalAlpha = 1; });
  return { c, n: cols.length, cols };
}
function Particles(max, d) {
  this.max = max; this.cap = max; this.k = 1; this.dots = d; this.next = 0; this.alive = 0;
  const F = () => new Float32Array(max);
  this.x = F(); this.y = F(); this.vx = F(); this.vy = F(); this.life = F(); this.full = F(); this.gr = F(); this.drag = F();
  this.c = new Uint8Array(max); this.s = new Uint8Array(max); this.br = new Uint8Array(max);
}
Particles.prototype = {
  emit(x, y, n, o) {
    let m = n * this.k; m = Math.floor(m) + (Math.random() < m - Math.floor(m) ? 1 : 0);
    const cap = Math.min(this.cap, this.max), v = o.v == null ? 60 : o.v, a = o.a == null ? -Math.PI / 2 : o.a, sp = o.sp == null ? Math.PI * 2 : o.sp;
    for (let k = 0; k < m; k++) {
      if (this.next >= cap) this.next = 0;
      const i = this.next; this.next = (this.next + 1) % cap;
      const ang = a + (Math.random() - 0.5) * sp, spd = v * (0.45 + Math.random() * 0.55);
      this.x[i] = x + (o.r ? (Math.random() - 0.5) * o.r * 2 : 0); this.y[i] = y + (o.r ? (Math.random() - 0.5) * o.r : 0);
      this.vx[i] = Math.cos(ang) * spd; this.vy[i] = Math.sin(ang) * spd - (o.up || 0);
      const life = (o.life || 0.6) * (0.7 + Math.random() * 0.6); this.life[i] = life; this.full[i] = life;
      this.gr[i] = o.g == null ? 0 : o.g; this.drag[i] = o.drag || 0;
      const c = o.c == null ? 0 : typeof o.c === "number" ? o.c : o.c[(Math.random() * o.c.length) | 0];
      this.c[i] = c; this.s[i] = o.s || 1 + ((Math.random() * 2) | 0); this.br[i] = o.bright ? 1 : 0;
    }
  },
  step(dt) {
    let alive = 0;
    for (let i = 0; i < this.max; i++) {
      if (this.life[i] <= 0) continue;
      this.life[i] -= dt; if (this.life[i] <= 0) continue;
      alive++;
      this.vy[i] += this.gr[i] * dt;
      if (this.drag[i]) { const d = Math.max(0, 1 - this.drag[i] * dt); this.vx[i] *= d; this.vy[i] *= d; }
      this.x[i] += this.vx[i] * dt; this.y[i] += this.vy[i] * dt;
    }
    this.alive = alive;
  },
  clear() { this.life.fill(0); this.alive = 0; },
  draw(g, camX, camY, bright, vw, vh) {
    const D = this.dots.c, b = bright ? 1 : 0; vw = vw || 480; vh = vh || 270;
    for (let i = 0; i < this.max; i++) {
      if (this.life[i] <= 0 || this.br[i] !== b) continue;
      const x = Math.round(this.x[i] - camX), y = Math.round(this.y[i] - camY); if (x < -4 || y < -4 || x > vw || y > vh) continue;
      const f = this.life[i] / this.full[i], k = f > 0.6 ? 0 : f > 0.35 ? 1 : f > 0.15 ? 2 : 3, s = this.s[i];
      g.drawImage(D, k * 12 + (s - 1) * 4, this.c[i] * 4, s, s, x, y, s, s);
    }
  }
};

// ---------------------------------------------------------------- light: the dark, with holes cut for the lights
// Light(G): a small map of the dark (half the screen's size on the full tier, a quarter on light), filled each frame,
// a soft hole cut where each light is, then laid over the world; coloured glows are added on top of that. On the
// full tier the holes are in dithered steps and the map is drawn crisp (the pixel look); on light it's smoothed.
// begin(fill), cut(sx, sy, r, k) (screen pixels; k how strong), end(g); glows: glowOf(r, rgb, a) once, then
// glowBegin(g), glow(g, sx, sy, sprite, a) (as many as the tier allows a frame), glowEnd(g); pulse(x, y, r, life,
// glow) a burst of light in the world (pulses(camX, camY) cuts them, pulseGlows(g, camX, camY) adds their colour).
const BAYER = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5];
function holeOf(r, dither) {
  const s = r * 2, c = mk(s, s), g = ctx(c); if (!g) return c;
  const id = g.createImageData(s, s), u = new Uint32Array(id.data.buffer), r0 = r * 0.4;
  for (let y = 0; y < s; y++) for (let x = 0; x < s; x++) {
    const d = Math.sqrt((x + 0.5 - r) * (x + 0.5 - r) + (y + 0.5 - r) * (y + 0.5 - r));
    let a = d <= r0 ? 1 : d >= r ? 0 : 1 - (d - r0) / (r - r0); a = a * a * (3 - 2 * a);
    if (dither) { const q = a * 6, f = Math.floor(q); a = Math.min(6, f + ((q - f) * 16 > BAYER[(y & 3) * 4 + (x & 3)] + 0.5 ? 1 : 0)) / 6; }
    u[y * s + x] = ((Math.round(a * 255) << 24) | 0xffffff) >>> 0;
  }
  g.putImageData(id, 0, 0); return c;
}
function glowOf(r, rgb, maxA) {
  const s = r * 2, c = mk(s, s), g = ctx(c); if (!g) return c;
  const id = g.createImageData(s, s), u = new Uint32Array(id.data.buffer), base = (rgb[2] << 16 | rgb[1] << 8 | rgb[0]) >>> 0;
  for (let y = 0; y < s; y++) for (let x = 0; x < s; x++) {
    const d = Math.sqrt((x + 0.5 - r) * (x + 0.5 - r) + (y + 0.5 - r) * (y + 0.5 - r)) / r;
    let a = 1 - Math.min(1, d); a = a * a; const q = a * 5, f = Math.floor(q), lv = Math.min(5, f + ((q - f) * 16 > BAYER[(y & 3) * 4 + (x & 3)] + 0.5 ? 1 : 0));
    u[y * s + x] = ((Math.round(lv / 5 * maxA * 255) << 24) | base) >>> 0;
  }
  g.putImageData(id, 0, 0); return c;
}
function Light(G) {
  this.G = G; this.scale = 0; this.c = null; this.g = null; this.holes = []; this.fill = ""; this.used = 0; this.cutN = 0;
  this.P = []; for (let i = 0; i < 12; i++) this.P.push({ on: false, x: 0, y: 0, r: 0, t: 0, life: 1, glow: null });
  this.size(G.tier.light);
}
Light.prototype = {
  size(scale) {
    if (scale === this.scale && this.c) return;
    this.scale = scale; this.w = Math.ceil(this.G.w / scale); this.h = Math.ceil(this.G.h / scale);
    this.c = mk(this.w, this.h); this.g = ctx(this.c); this.holes = []; this.fill = ""; this.dither = scale <= 2;
    for (let r = 2; r <= 150 / scale; r += 2) this.hole(r);       // (made now, not mid-game)
  },
  hole(r) { r = Math.max(2, Math.min(76, Math.round(r / 2) * 2)); return this.holes[r] || (this.holes[r] = holeOf(r, this.dither)); },
  // fill: the dark's colour. A see-through fill lays over the last frame's map (the dark builds up where no light has
  // been, and a light that moves leaves a moment of glow behind); fresh: clear it first, so the dark is the fill's own
  begin(fill, fresh) {
    const g = this.g; if (!g) return;
    g.globalCompositeOperation = "source-over";
    if (fresh) g.clearRect(0, 0, this.w, this.h);
    if (fill !== this.fill) { g.fillStyle = fill; this.fill = fill; }
    g.fillRect(0, 0, this.w, this.h);
    g.globalCompositeOperation = "destination-out"; this.cutN = 0;
  },
  cut(sx, sy, r, k) {
    const g = this.g; if (!g) return;
    const s = this.scale, x = sx / s, y = sy / s, hr = r / s;
    if (x < -hr || y < -hr || x > this.w + hr || y > this.h + hr) return;
    const h = this.hole(hr);
    if (k != null && k < 1) g.globalAlpha = Math.max(0, k);
    g.drawImage(h, Math.round(x - h.width / 2), Math.round(y - h.height / 2));
    if (k != null && k < 1) g.globalAlpha = 1;
    this.cutN++;
  },
  end(g) {
    if (!this.g) return;
    this.g.globalCompositeOperation = "source-over";
    if (!this.dither) g.imageSmoothingEnabled = true;
    g.drawImage(this.c, 0, 0, this.w, this.h, 0, 0, this.w * this.scale, this.h * this.scale);
    g.imageSmoothingEnabled = false;
  },
  glowBegin(g) { g.globalCompositeOperation = "lighter"; this.used = 0; },
  glow(g, sx, sy, spr, a) {
    if (this.used >= this.G.tier.glows || !spr) return;
    const hw = spr.width >> 1, hh = spr.height >> 1;
    if (sx < -hw || sy < -hh || sx > this.G.w + hw || sy > this.G.h + hh) return;
    this.used++;
    if (a != null && a < 1) g.globalAlpha = Math.max(0, a);
    g.drawImage(spr, Math.round(sx - hw), Math.round(sy - hh));
    if (a != null && a < 1) g.globalAlpha = 1;
  },
  glowEnd(g) { g.globalCompositeOperation = "source-over"; g.globalAlpha = 1; },
  pulse(x, y, r, life, glow) {
    let q = null; for (const p of this.P) if (!p.on) { q = p; break; } if (!q) q = this.P[0];
    q.on = true; q.x = x; q.y = y; q.r = r; q.t = 0; q.life = life || 0.4; q.glow = glow || null;
  },
  step(dt) { for (const p of this.P) if (p.on && (p.t += dt) >= p.life) p.on = false; },
  pulses(camX, camY) { for (const p of this.P) if (p.on) this.cut(p.x - camX, p.y - camY, p.r * (0.4 + 0.6 * (1 - p.t / p.life)), 1); },
  pulseGlows(g, camX, camY) { for (const p of this.P) if (p.on && p.glow) this.glow(g, p.x - camX, p.y - camY, p.glow, 1 - p.t / p.life); },
  clear() { for (const p of this.P) p.on = false; }
};

// ---------------------------------------------------------------- the pixel font (5×7), the controller's buttons in it
const GLYPHS = {
  A: [14, 17, 17, 31, 17, 17, 17], B: [30, 17, 17, 30, 17, 17, 30], C: [14, 17, 16, 16, 16, 17, 14], D: [28, 18, 17, 17, 17, 18, 28],
  E: [31, 16, 16, 30, 16, 16, 31], F: [31, 16, 16, 30, 16, 16, 16], G: [14, 17, 16, 23, 17, 17, 15], H: [17, 17, 17, 31, 17, 17, 17],
  I: [14, 4, 4, 4, 4, 4, 14], J: [7, 2, 2, 2, 2, 18, 12], K: [17, 18, 20, 24, 20, 18, 17], L: [16, 16, 16, 16, 16, 16, 31],
  M: [17, 27, 21, 21, 17, 17, 17], N: [17, 17, 25, 21, 19, 17, 17], O: [14, 17, 17, 17, 17, 17, 14], P: [30, 17, 17, 30, 16, 16, 16],
  Q: [14, 17, 17, 17, 21, 18, 13], R: [30, 17, 17, 30, 20, 18, 17], S: [15, 16, 16, 14, 1, 1, 30], T: [31, 4, 4, 4, 4, 4, 4],
  U: [17, 17, 17, 17, 17, 17, 14], V: [17, 17, 17, 17, 17, 10, 4], W: [17, 17, 17, 21, 21, 21, 10], X: [17, 17, 10, 4, 10, 17, 17],
  Y: [17, 17, 10, 4, 4, 4, 4], Z: [31, 1, 2, 4, 8, 16, 31],
  "0": [14, 17, 19, 21, 25, 17, 14], "1": [4, 12, 4, 4, 4, 4, 14], "2": [14, 17, 1, 2, 4, 8, 31], "3": [31, 2, 4, 2, 1, 17, 14],
  "4": [2, 6, 10, 18, 31, 2, 2], "5": [31, 16, 30, 1, 1, 17, 14], "6": [6, 8, 16, 30, 17, 17, 14], "7": [31, 1, 2, 4, 8, 8, 8],
  "8": [14, 17, 17, 14, 17, 17, 14], "9": [14, 17, 17, 15, 1, 2, 12],
  ".": [0, 0, 0, 0, 0, 12, 12], ",": [0, 0, 0, 0, 12, 4, 8], ":": [0, 12, 12, 0, 12, 12, 0], ";": [0, 12, 12, 0, 12, 4, 8],
  "!": [4, 4, 4, 4, 4, 0, 4], "?": [14, 17, 1, 2, 4, 0, 4], "-": [0, 0, 0, 14, 0, 0, 0], "+": [0, 4, 4, 31, 4, 4, 0],
  "/": [1, 1, 2, 4, 8, 16, 16], "(": [2, 4, 8, 8, 8, 4, 2], ")": [8, 4, 2, 2, 2, 4, 8], "'": [4, 4, 8, 0, 0, 0, 0],
  '"': [10, 10, 0, 0, 0, 0, 0], "%": [25, 25, 2, 4, 8, 19, 19], "=": [0, 0, 31, 0, 31, 0, 0], "<": [2, 4, 8, 16, 8, 4, 2],
  ">": [8, 4, 2, 1, 2, 4, 8], "_": [0, 0, 0, 0, 0, 0, 31], "*": [0, 4, 21, 14, 21, 4, 0], "#": [10, 10, 31, 10, 31, 10, 10],
  "&": [12, 18, 20, 8, 21, 18, 13], "[": [14, 8, 8, 8, 8, 8, 14], "]": [14, 2, 2, 2, 2, 2, 14],
  "\x10": [0, 17, 10, 4, 10, 17, 0], "\x11": [0, 14, 17, 17, 17, 14, 0], "\x12": [0, 31, 17, 17, 17, 31, 0], "\x13": [0, 4, 4, 10, 10, 31, 0],   // ✕ ○ □ △
  "\x14": [2, 6, 14, 30, 14, 6, 2], "\x15": [8, 12, 14, 15, 14, 12, 8], "\x16": [0, 10, 31, 31, 14, 4, 0], "\x17": [4, 4, 31, 14, 10, 17, 0],   // ◀ ▶ ♥ ★
  "\x18": [0, 0, 0, 4, 0, 0, 0], "\x19": [4, 14, 31, 4, 4, 4, 0], "\x1a": [0, 4, 4, 4, 31, 14, 4],                                            // · ↑ ↓
  "\x1b": [0, 14, 14, 14, 14, 14, 0], "\x1c": [0, 14, 10, 10, 10, 14, 0]                                                                       // pips, full and empty
};
const SPECIAL = { 0x2715: 16, 0x25cb: 17, 0x25a1: 18, 0x25b3: 19, 0x25c0: 20, 0x25b6: 21, 0x2665: 22, 0x2605: 23, 0xb7: 24, 0x2191: 25, 0x2193: 26, 0xd7: 16 };
function Font() {
  this.GI = new Int16Array(256).fill(-1); this.rows = [];
  for (const k in GLYPHS) { this.GI[k.charCodeAt(0)] = this.rows.length; this.rows.push(GLYPHS[k]); }
  const n = this.rows.length; this.GX = new Uint8Array(n); this.GW = new Uint8Array(n);
  for (let i = 0; i < n; i++) {
    let lo = 5, hi = -1;
    for (let y = 0; y < 7; y++) for (let b = 0; b < 5; b++) if ((this.rows[i][y] >> (4 - b)) & 1) { lo = Math.min(lo, b); hi = Math.max(hi, b); }
    if (hi < 0) { this.GX[i] = 0; this.GW[i] = 3; } else { this.GX[i] = lo; this.GW[i] = hi - lo + 1; }
  }
  this.atlas = []; this.names = {};
  for (const c of ["#ece8f4", "#8c879c", "#ffd27a", "#e8463c", "#7ad8f0", "#8ed66a", "#ff9a3c", "#08060e"]) this.colour(c);
}
Font.prototype = {
  // a colour to write in: its place (the first eight are made at the start: white, grey, gold, red, ice, green, ember, ink)
  colour(css) {
    if (this.names[css] != null) return this.names[css];
    const n = this.rows.length, a = mk(n * 6, 7), g = ctx(a);
    if (g) { g.fillStyle = css; for (let i = 0; i < n; i++) for (let y = 0; y < 7; y++) for (let b = 0; b < 5; b++) if ((this.rows[i][y] >> (4 - b)) & 1) g.fillRect(i * 6 + b, y, 1, 1); }
    this.atlas.push(a); return (this.names[css] = this.atlas.length - 1);
  },
  code(s, i) { let c = s.charCodeAt(i); if (c > 255) c = SPECIAL[c] || 63; if (c >= 97 && c <= 122) c -= 32; return c; },
  text(g, s, x, y, col, sc) {
    sc = sc || 1; const at = this.atlas[col || 0];
    for (let i = 0; i < s.length; i++) {
      const c = this.code(s, i);
      if (c === 32) { x += 4 * sc; continue; }
      const k = this.GI[c]; if (k < 0) { x += 4 * sc; continue; }
      g.drawImage(at, k * 6 + this.GX[k], 0, this.GW[k], 7, x, y, this.GW[k] * sc, 7 * sc);
      x += (this.GW[k] + 1) * sc;
    }
    return x;
  },
  width(s, sc) {
    sc = sc || 1; let w = 0;
    for (let i = 0; i < s.length; i++) { const c = this.code(s, i), k = c === 32 ? -1 : this.GI[c]; w += (k < 0 ? 4 : this.GW[k] + 1) * sc; }
    return Math.max(0, w - sc);
  },
  shadow(g, s, x, y, col, sc) { sc = sc || 1; this.text(g, s, x + sc, y + sc, 7, sc); return this.text(g, s, x, y, col, sc); },
  center(g, s, cx, y, col, sc, shadow) { const x = Math.round(cx - this.width(s, sc) / 2); return shadow === false ? this.text(g, s, x, y, col, sc) : this.shadow(g, s, x, y, col, sc); },
  // words wrapped to a width: the lines
  wrap(s, maxW, sc) {
    const out = []; let line = "";
    for (const w of String(s).split(" ")) { const t = line ? line + " " + w : w; if (this.width(t, sc) > maxW && line) { out.push(line); line = w; } else line = t; }
    if (line) out.push(line); return out;
  }
};
const font = new Font();
// a line of text drawn once into its own small canvas, and copied after (the HUD's numbers: drawn again only when
// they change)
function Label(w, h, sc) { this.sc = sc || 1; this.c = mk(w, h || 9 * this.sc); this.g = ctx(this.c); this.s = null; this.w = 0; this.h = this.c.height; }
Label.prototype = {
  set(s, col, shadow) {
    s = String(s); const key = s + "|" + col + "|" + shadow; if (key === this.s || !this.g) return; this.s = key;
    this.g.clearRect(0, 0, this.c.width, this.c.height);
    if (shadow === false) font.text(this.g, s, 0, 0, col || 0, this.sc); else font.shadow(this.g, s, 0, 0, col || 0, this.sc);
    this.w = Math.min(this.c.width, font.width(s, this.sc) + this.sc);
  },
  draw(g, x, y) { if (this.w) g.drawImage(this.c, 0, 0, this.w, this.h, Math.round(x), Math.round(y), this.w, this.h); }
};
// a button as the player knows it (A, or ✕ on a PlayStation controller; the key's name with a keyboard), in a badge
function badge(g, G, b, x, y, col) {
  const s = G.label(b), w = font.width(s) + 5;
  g.fillStyle = "#2a2236"; g.fillRect(x + 1, y, w - 2, 9); g.fillRect(x, y + 1, w, 7);
  font.text(g, s, x + 3, y + 1, col == null ? 0 : col);
  return x + w + 2;
}

// ---------------------------------------------------------------- menus, in the engine's one look
// Menu(G, { top: the top screen's name (Back there is the box's: it leaves the game), screens: { name: { title, sub,
// items: [...] or (screen) → [...], back: "name" or function, hint, w } }, choose(item, screen), changed(k, v, item),
// accent }). An item: { t: "TEXT", act, sub (to its right), off (can't be chosen), k/vals/names (an option: ◀ ▶ change
// it, kept in values[k]) }. menu.show(name), hide(), at, top(), button(b, how), draw(g).
function Menu(G, o) {
  this.G = G; this.o = o; this.at = null; this.i = 0; this.topAt = 0; this.list = []; this.dirty = true;
  this.values = o.values || G.opts; this.c = mk(G.w, G.h); this.g = ctx(this.c); this.box = { x: 0, y: 0, w: 0, h: 0 }; this.t = 0;
  this.accent = o.accent || "#ff9a3c"; this.ai = font.colour(this.accent);
}
Menu.prototype = {
  show(name, i) {
    const S = this.o.screens[name]; if (!S) return;
    if (name === this.o.top && this.at !== name) this.topAt = performance.now();
    this.at = name; this.list = typeof S.items === "function" ? S.items(S) : S.items || [];
    this.i = i != null ? i : S.start != null ? (typeof S.start === "function" ? S.start() : S.start) : 0;
    this.skip(1); this.dirty = true;
  },
  refresh() { if (!this.at) return; const S = this.o.screens[this.at]; if (typeof S.items === "function") this.list = S.items(S); this.i = clamp(this.i, 0, Math.max(0, this.list.length - 1)); this.dirty = true; },
  hide() { this.at = null; this.dirty = true; },
  top() { return this.at === this.o.top ? this.topAt : 0; },
  skip(d) { const n = this.list.length; for (let k = 0; k < n && this.list[this.i] && this.list[this.i].gap; k++) this.i = (this.i + d + n) % n; },
  move(d) {
    const n = this.list.length; if (!n) return;
    const was = this.i; this.i = (this.i + d + n) % n; this.skip(d);
    if (this.i !== was) { this.dirty = true; this.sound("move"); }
  },
  sound(n) { if (this.o.sound) this.o.sound(n); else this.G.synth.play(n); },
  button(b, how) {                                   // true when the menu took it
    if (!this.at) return false;
    if (how === "release") return true;
    const S = this.o.screens[this.at], it = this.list[this.i];
    if (b === "up") this.move(-1);
    else if (b === "down") this.move(1);
    else if (b === "left" || b === "right") { if (it && it.k) this.change(it, b === "left" ? -1 : 1); else if (S.row) this.move(b === "left" ? -1 : 1); }
    else if (how !== "press") return true;
    else if (b === "a" || b === "start") {
      if (!it || it.gap) return true;
      if (it.k && !it.act) { this.change(it, 1, true); return true; }
      if (it.off) { this.sound("no"); return true; }
      this.sound("ok"); this.o.choose(it, this.at);
    } else if (b === "b" || b === "back") this.back();
    else if (S.on) S.on(b, it);
    return true;
  },
  back() {
    const S = this.o.screens[this.at]; if (!S || !S.back) return;
    this.sound("move");
    if (typeof S.back === "function") S.back(); else this.show(S.back);
  },
  change(it, d, wrap) {
    const v = this.values, k = it.vals.indexOf(v[it.k]); let n = k + d;
    if (wrap) n = (n + it.vals.length) % it.vals.length; else n = clamp(n, 0, it.vals.length - 1);
    if (it.vals[n] === v[it.k]) return;
    v[it.k] = it.vals[n]; this.sound("move"); this.dirty = true;
    if (this.o.changed) this.o.changed(it.k, v[it.k], it);
  },
  valueText(it) {
    const x = this.values[it.k];
    if (it.names) return it.names[x] != null ? it.names[x] : String(x);
    if (typeof x === "number" && it.vals.length > 5) { const top = it.vals[it.vals.length - 1]; return "\x1b".repeat(x) + "\x1c".repeat(top - x); }   // (pips)
    return String(x);
  },
  // the panel: drawn into its own canvas when something on it changes, copied after
  render() {
    const g = this.g, G = this.G, S = this.o.screens[this.at]; if (!g) return;
    g.clearRect(0, 0, G.w, G.h);
    const w = S.w || 236, lh = 12, items = this.list, extra = S.lines ? S.lines.length * 10 + 6 : 0;
    const title = S.title || "", sub = S.sub || "", hint = typeof S.hint === "function" ? S.hint() : S.hint;
    const subLines = sub ? font.wrap(sub, w - 24) : [];
    const h = 14 + (title ? 20 : 0) + subLines.length * 10 + (subLines.length ? 4 : 0) + extra + items.length * lh + 22;
    const x = (G.w - w) >> 1, y = S.y != null ? S.y : Math.max(6, (G.h - h) >> 1);
    this.box = { x, y, w, h };
    g.fillStyle = "rgba(12,8,18,0.93)"; g.fillRect(x + 2, y, w - 4, h); g.fillRect(x, y + 2, w, h - 4); g.fillRect(x + 1, y + 1, w - 2, h - 2);
    g.fillStyle = "#3a2c44"; g.fillRect(x + 2, y, w - 4, 1); g.fillRect(x + 2, y + h - 1, w - 4, 1); g.fillRect(x, y + 2, 1, h - 4); g.fillRect(x + w - 1, y + 2, 1, h - 4);
    g.fillStyle = this.accent; g.fillRect(x + 2, y, 10, 1); g.fillRect(x, y + 2, 1, 8); g.fillRect(x + w - 12, y + h - 1, 10, 1); g.fillRect(x + w - 1, y + h - 10, 1, 8);
    let cy = y + 8;
    if (title) { font.center(g, title, G.w / 2, cy, this.ai, 2); cy += 20; }
    for (const l of subLines) { font.center(g, l, G.w / 2, cy, 1, 1, false); cy += 10; }
    if (subLines.length) cy += 4;
    if (S.lines) { for (const l of S.lines) { font.text(g, l[0], x + 14, cy, 1); if (l[1] != null) font.text(g, String(l[1]), x + w - 14 - font.width(String(l[1])), cy, l[2] == null ? 0 : l[2]); cy += 10; } cy += 6; }
    this.itemsY = cy;
    items.forEach((it, k) => {
      const on = k === this.i && !it.gap, ty = cy + k * lh;
      if (it.gap) { if (it.t) font.text(g, it.t, x + 14, ty + 2, 1); return; }
      if (on) { g.fillStyle = "rgba(255,154,60,0.16)"; g.fillRect(x + 6, ty - 2, w - 12, lh - 1); g.fillStyle = this.accent; g.fillRect(x + 6, ty - 2, 2, lh - 1); }
      const col = it.off ? 1 : on ? 2 : 0;
      font.text(g, it.t, x + 14, ty, col);
      if (it.k) { const v = "◀ " + this.valueText(it) + " ▶"; font.text(g, v, x + w - 14 - font.width(v), ty, on ? 2 : 1); }
      else if (it.sub != null) { const s = String(it.sub); font.text(g, s, x + w - 14 - font.width(s), ty, it.subCol != null ? it.subCol : 1); }
    });
    // what the buttons do here
    let hx = x + 12; const hy = y + h - 14;
    const cur = items[this.i];
    if (cur && cur.k) { font.text(g, "◀ ▶", hx, hy + 1, 1); hx += font.width("◀ ▶") + 4; font.text(g, "CHANGE", hx, hy + 1, 1); hx += font.width("CHANGE") + 10; }
    else { hx = badge(g, G, "a", hx, hy, 2); font.text(g, "CHOOSE", hx, hy + 1, 1); hx += font.width("CHOOSE") + 10; }
    if (S.back) { hx = badge(g, G, "b", hx, hy, 2); font.text(g, "BACK", hx, hy + 1, 1); hx += font.width("BACK") + 10; }
    if (hint) font.text(g, hint, hx, hy + 1, 1);
    this.dirty = false; this.pad = G.input.pad();
  },
  draw(g) {
    if (!this.at) return;
    if (this.dirty || this.pad !== this.G.input.pad()) this.render();
    g.drawImage(this.c, 0, 0);
    // the marker: an ember that flickers beside the chosen item
    const it = this.list[this.i];
    if (it && !it.gap) { const f = (this.G.frame >> 3) & 1, ty = this.itemsY + this.i * 12; g.fillStyle = f ? "#ffd27a" : "#ff9a3c"; g.fillRect(this.box.x + 9, ty + 2, 2, 3); }
  }
};
// the options every game on the engine has, for a Menu screen's items: volumes, rumble, shake, effects
function optionItems(extra) {
  const ten = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
  return [
    { t: "MUSIC", k: "music", vals: ten }, { t: "SOUNDS", k: "sound", vals: ten },
    { t: "RUMBLE", k: "rumble", vals: [0, 1], names: { 0: "OFF", 1: "ON" } },
    { t: "SCREEN SHAKE", k: "shake", vals: [0, 1, 2], names: { 0: "OFF", 1: "GENTLE", 2: "FULL" } },
    { t: "LOOK", k: "fx", vals: ["auto", "rich", "full", "light"], names: { auto: "FOR THIS BOX", rich: "RICH", full: "FULL", light: "LIGHT" } },
    { t: "FRAMES", k: "pace", vals: ["auto", "60", "30"], names: { auto: "FOR THIS BOX", 60: "SMOOTHEST, 60", 30: "STEADY 30" } }
  ].concat(extra || []);
}

// ---------------------------------------------------------------- what's kept on the box
// Store(id, fresh): data (fresh() with what was saved laid over it, a level deep), save() (nothing in #demo), and
// wipe(). A game's own fields are its own; opts holds the engine's options.
function Store(id, fresh) {
  this.id = id; this.fresh = fresh; this.demo = /(^|[#&-])demo\b/.test(location.hash || "");
  let saved = null;
  if (!this.demo) { try { saved = JSON.parse(localStorage.getItem(id) || "null"); } catch (e) { saved = null; } }
  this.data = fresh();
  if (saved && typeof saved === "object") for (const k in saved) {
    const a = this.data[k], b = saved[k];
    this.data[k] = a && b && typeof a === "object" && typeof b === "object" && !Array.isArray(a) ? Object.assign(a, b) : b;
  }
}
Store.prototype = {
  save() { if (this.demo) return false; try { localStorage.setItem(this.id, JSON.stringify(this.data)); return true; } catch (e) { return false; } },
  wipe() { this.data = this.fresh(); this.save(); }
};

// a camera that follows: towards x y with some lag, a little ahead of where it's going, kept inside the world
function follow(cam, x, y, dt, o) {
  const k = 1 - Math.exp(-(o.k || 6) * dt), ky = 1 - Math.exp(-(o.ky || o.k || 6) * dt);
  cam.x += (x - cam.w / 2 - cam.x) * k; cam.y += (y - cam.h / 2 - cam.y) * ky;
  if (o.maxW) cam.x = clamp(cam.x, 0, Math.max(0, o.maxW - cam.w));
  if (o.maxH) cam.y = clamp(cam.y, 0, Math.max(0, o.maxH - cam.h));
}

window.Low2D = { game, plan, ladder, rungFor, LOOKS, TIERS, Governor, Control, TileMap, SOLID, ONEWAY, HURT, LEFT, RIGHT, UP, DOWN, art, flip, silhouette, outline,
  sheet, put, Layer, gradient, reflect, dots, Particles, Light, holeOf, glowOf, font, Font, Label, badge, Menu, optionItems, Store, follow, mk, ctx,
  U, version: 1 };
})();
