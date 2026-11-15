/* Sofa Box games: the controllers, read straight from the browser (the Gamepad API) every frame, the same on every
   controller (the browser's "standard" layout: A / ✕ at the bottom). For the box's own games, which are made for a
   controller first: keys and a mouse are for when there's nothing else.

   The box also turns every controller's buttons into key presses (for its menus), so while a controller is in use a
   game ignores those keys (SofaPad.active()): it would get every press twice. Back and Home stay the box's (Home,
   button 16, is never read: held a second, it leaves the game).

   One player: these follow the controller used last, so any controller works the menus.
     SofaPad.on((button, how, player) => ...)   button: a b x y lb rb lt rt select start up down left right;
                                         how: "press", "release", or "repeat" (a direction held: menus and grids);
                                         player: whose controller it was (player.n is their number)
     SofaPad.held("left")               held now? (a direction: the D-pad or the left stick)
     SofaPad.button("left")             the button itself held now (the D-pad only, not the stick)
     SofaPad.stick()                    the left stick, {x, y} from -1 to 1 (a little play in the middle)
     SofaPad.stick2()                   the right stick, the same way (for looking round)
     SofaPad.trigger("rt")              how far a trigger (lt or rt) is pulled, 0 to 1
     SofaPad.rumble(strong, weak, ms)   shake the controller (0 to 1 each), where the controller and browser can
     SofaPad.active()                   a controller (any of them) in use just now
     SofaPad.label("a")                 "A", or "✕" on a PlayStation controller

   Several players: each controller is a player, numbered in the order they come (as each one connects; when several
   turn up at once, as at a page's first press, the one pressed first). A player has all of the calls above for its
   own controller (on, held, button, stick, stick2, trigger, rumble, active, connected, kind, label), and n, its number.
     SofaPad.players()                  the players so far, by number
     SofaPad.player(n)                  player n (1, 2, …): the same object for good, reading nothing while no
                                         controller is theirs (so a game can hold on to it before they join)
     SofaPad.on("joined", p => ...)     a controller became player p.n: someone new, or back after theirs went away
     SofaPad.on("left", p => ...)       player p.n's controller went away (switched off, flat, out of range); theirs
                                         is the first place a controller coming back takes, the same kind first

   Touch (phones and tablets): SofaPad.touch is a controller drawn on the game's own picture, read as one more player
   (a standard gamepad: the same button names, the stick, the triggers), so a game's rules don't change for it. It
   shows when a touch screen is used (a coarse pointer, or a first touch) and hides when a controller or a key is;
   on the box and on computers it never shows and costs one call a frame. Nothing of it is laid over the picture:
   the engine that owns the canvas draws it (Low3D's E.ui, Low2D's hud), or the game with draw2d().
     SofaPad.touch.layout({...})        the game's controls, as data: { stick: "stick" (a floating left stick) | "dpad"
                                         | "none", look: true (drag on the right: the right stick), buttons: [["a",
                                         "JUMP"], ["x", "HIT"], …] (the first the big one, bottom right), pause: "start"
                                         | false, tilt: "x" | "xy" | false, sets: { name: {...} } }; use(name) picks a set
     SofaPad.touch.frame(covered)       each frame, before drawing: true when the controls are drawn now (covered: a
                                         menu is over the picture, which is worked by tapping instead)
     SofaPad.touch.draw(paint, w, h)    draws them through paint.disc / ring / text into a picture w × h over the
                                         element given to attach(el) (the engines do this); draw2d(ctx, w, h, text)
                                         for a plain 2D canvas
     SofaPad.touch.onTap(fn)            fn({kind: "tap" | "swipe", x, y, dx, dy, target}) for a touch that missed the
                                         controls (page pixels); return true when it was taken
     SofaPad.touch.tilt(on)             tilting the device moves the left stick (asks first where the browser does,
                                         so call it from a tap); wanted(), can() (a touch screen with a tilt sensor)
     SofaPad.touch.on                   shown now; SofaPad.real(): a controller (not the touch one) is connected */
(function () {
  if (window.SofaPad) return;
  const BTN = { a: 0, b: 1, x: 2, y: 3, lb: 4, rb: 5, lt: 6, rt: 7, select: 8, start: 9, up: 12, down: 13, left: 14, right: 15 };
  const NAMES = Object.keys(BTN), DIRS = ["up", "down", "left", "right"], FIRST = 380, AGAIN = 120, IN_USE = 2500;
  const handlers = [], named = { joined: [], left: [] }, slots = [];   // slots[n - 1] is player n
  let current = null, usedAt = -1e9;                // the player whose controller was used last; when any one was

  function kind(id) {
    if (/^Sofa touch/.test(id)) return "touch";
    if (/xbox|microsoft|x-box|xinput|045e/i.test(id)) return "xbox";
    if (/dualsense|dualshock|playstation|054c|wireless controller/i.test(id)) return "playstation";
    if (/nintendo|pro controller|057e/i.test(id)) return "nintendo";
    return "other";
  }
  function label(k, b) {
    const ps = k === "playstation";
    if (k === "touch") return ({ a: "A", b: "B", x: "X", y: "Y", lb: "LB", rb: "RB", lt: "LT", rt: "RT", start: "II", select: "SEL" })[b] || b;   // (as drawn on it)
    return ({ a: ps ? "✕" : "A", b: ps ? "○" : "B", x: ps ? "□" : "X", y: ps ? "△" : "Y", start: ps ? "Options" : "Menu" })[b] || b;
  }
  const dz = (v, d) => Math.abs(v) < d ? 0 : (v - Math.sign(v) * d) / (1 - d);
  function call(list, a, b, c) { for (const h of list) { try { h(a, b, c); } catch (e) { /* one game's slip doesn't stop the pad */ } } }

  function Player(n) {
    this.n = n; this.pad = null; this.index = -1; this.id = ""; this.seen = false;   // seen: it has had a controller
    this.prev = {}; this.now = {}; this.next = {}; this.handlers = []; this.usedAt = -1e9; this.pickedAt = -1e9; this.out = false;
  }
  Player.prototype = {
    on(h) { this.handlers.push(h); },
    held(b) { return !!this.prev[b]; },
    button(b) { const p = this.pad, k = p && p.buttons[BTN[b]]; return !!(k && k.pressed); },
    stick() { const p = this.pad; return p ? { x: dz(p.axes[0] || 0, 0.15), y: dz(p.axes[1] || 0, 0.15) } : { x: 0, y: 0 }; },
    stick2() { const p = this.pad; return p ? { x: dz(p.axes[2] || 0, 0.12), y: dz(p.axes[3] || 0, 0.12) } : { x: 0, y: 0 }; },
    trigger(b) { const k = this.pad && this.pad.buttons[BTN[b]]; return k ? Math.max(k.value || 0, k.pressed ? 1 : 0) : 0; },
    rumble(strong, weak, ms) {
      const act = this.pad && this.pad.vibrationActuator;
      if (!act || !act.playEffect) return;
      try { act.playEffect("dual-rumble", { duration: ms || 120, strongMagnitude: Math.min(1, strong || 0), weakMagnitude: Math.min(1, weak || 0) }).catch(() => {}); } catch (e) { /* this one doesn't shake */ }
    },
    active() { return performance.now() - this.usedAt < IN_USE; },
    connected() { return !!this.pad; },
    kind() { return this.pad ? kind(this.pad.id) : null; },
    label(b) { return label(this.kind(), b); }
  };
  const nobody = new Player(0);                      // (no controller at all: reads nothing)

  function slot(n) { while (slots.length < n) slots.push(new Player(slots.length + 1)); return slots[n - 1]; }
  const standard = p => !!(p.pad && p.pad.mapping === "standard");
  const pressed = g => NAMES.some(b => g.buttons[BTN[b]] && g.buttons[BTN[b]].pressed) || g.axes.some(v => Math.abs(v) > 0.5);
  // (the touch controller is no source of the box's echo keys, so its use isn't counted for them; a real one picked
  // up hides it)
  function use(p, t) { p.usedAt = t; if (p.pad !== TP && t > usedAt) usedAt = t; }
  function pick(p, t) { p.pickedAt = t; current = p; if (p.pad !== TP && T.on) T.away(); }
  function choose() {                                // the controller used last; none pressed yet: a standard one first
    let best = null;
    for (const p of slots) if (p.pad && (!best || p.pickedAt > best.pickedAt || (p.pickedAt === best.pickedAt && standard(p) && !standard(best)))) best = p;
    current = best;
  }
  function emit(p, b, how) { call(handlers, b, how, p); call(p.handlers, b, how, p); }

  // a controller turned up: the first place free (a player whose controller went away, the same kind of controller
  // first), or a new number
  function join(g, t) {
    let p = null;
    for (const q of slots) if (!q.pad && q.seen && q.id === g.id) { p = q; break; }
    if (!p) for (const q of slots) if (!q.pad) { p = q; break; }
    if (!p) p = slot(slots.length + 1);
    Object.assign(p, { pad: g, index: g.index, id: g.id, seen: true, prev: {}, now: {}, next: {}, out: false, pickedAt: -1e9 });
    use(p, t);
    call(named.joined, p);
  }
  function leave(p) {
    const was = p.prev;
    p.pad = null; p.index = -1; p.prev = {}; p.now = {};
    for (const b of NAMES) if (was[b]) emit(p, b, "release");
    call(named.left, p);
  }

  function read() {
    requestAnimationFrame(read);
    let list = null;
    try { list = navigator.getGamepads ? navigator.getGamepads() : null; } catch (e) { list = null; }
    list = list || [];
    const t = performance.now();
    let changed = false;
    for (const p of slots) if (p.pad) {              // gone (or another controller in its place)
      const g = p.pad === TP ? (TP.connected ? TP : null) : list[p.index];
      if (!g || !g.connected || g.id !== p.id) { leave(p); changed = true; }
    }
    const fresh = [];
    for (let i = 0; i < list.length; i++) { const g = list[i]; if (g && g.connected && !slots.some(p => p.pad && p.pad !== TP && p.index === g.index)) fresh.push(g); }
    if (TP.connected && !slots.some(p => p.pad === TP)) fresh.push(TP);
    if (fresh.length) {                              // several at once: the one pressed first, then standard ones
      fresh.sort((a, b) => (pressed(b) - pressed(a)) || ((b.mapping === "standard") - (a.mapping === "standard")) || a.index - b.index);
      for (const g of fresh) join(g, t);
      changed = true;
    }
    if (changed) choose();
    for (const p of slots) {
      if (!p.pad) continue;
      const g = p.pad === TP ? TP : list[p.index], now = p.now;
      p.pad = g;
      for (const b of NAMES) now[b] = !!(g.buttons[BTN[b]] && g.buttons[BTN[b]].pressed);
      const ax = g.axes[0] || 0, ay = g.axes[1] || 0;
      now.left = now.left || ax < -0.5; now.right = now.right || ax > 0.5;
      now.up = now.up || ay < -0.5; now.down = now.down || ay > 0.5;
      // in use: a stick off the middle, or a direction held (the box repeats its arrow keys while one is); picked up:
      // a stick pushed out from the middle (not one resting a little off it, as a worn one does, lying on the sofa)
      const far = Math.max(Math.abs(ax), Math.abs(ay), Math.abs(g.axes[2] || 0), Math.abs(g.axes[3] || 0));
      if (far > 0.25 || now.up || now.down || now.left || now.right) use(p, t);
      if (far > 0.4 && !p.out) { p.out = true; pick(p, t); }
      else if (far < 0.2) p.out = false;
      const was = p.prev;
      for (const b of NAMES) {
        if (now[b] && !was[b]) { use(p, t); pick(p, t); p.next[b] = t + FIRST; emit(p, b, "press"); }
        else if (!now[b] && was[b]) emit(p, b, "release");
        else if (now[b] && DIRS.includes(b) && t >= p.next[b]) { p.next[b] = t + AGAIN; emit(p, b, "repeat"); }
      }
      p.prev = now; p.now = was;                     // (the two kept and swapped: nothing made new each frame)
    }
  }

  // ---------------------------------------------------------------- touch: a controller drawn on the picture
  // A standard gamepad of our own (TP), its buttons and sticks set by fingers on the screen, read by the loop above
  // as one more player: every game hears it under the names it already reads. Drawn by whatever owns the canvas.
  const DEMO = /(^|[#&-])demo\b/.test(location.hash || ""), TAU = Math.PI * 2;
  const TB = []; for (let i = 0; i < 17; i++) TB.push({ pressed: false, touched: false, value: 0 });
  const TC = new Uint8Array(17);                     // how many fingers hold each button
  const TP = { id: "Sofa touch (STANDARD GAMEPAD)", index: -2, connected: false, mapping: "standard", timestamp: 0, buttons: TB, axes: [0, 0, 0, 0],
    vibrationActuator: { type: "dual-rumble", reset: () => Promise.resolve("complete"),
      playEffect(type, o) { buzz(o && o.duration, Math.max((o && o.strongMagnitude) || 0, (o && o.weakMagnitude) || 0)); return Promise.resolve("complete"); } } };
  // vibration for rumble, where the browser has it (not iPhone Safari): a buzz as long as the rumble, a weak one none
  function buzz(ms, k) { if (k < 0.15 || !navigator.vibrate) return; try { navigator.vibrate(Math.max(15, Math.min(400, Math.round((ms || 120) * (0.4 + 0.6 * Math.min(1, k)))))); } catch (e) { /* none here */ } }
  const media = q => { try { return matchMedia(q).matches; } catch (e) { return false; } };
  const BONE = 0xefe6d2, INK = 0x0b0d10;
  const DIRB = { up: 12, down: 13, left: 14, right: 15 };
  const store = k => { try { return localStorage.getItem(k); } catch (e) { return null; } };
  const keep = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* not kept */ } };
  const TILTKEY = "sofa:tilt:" + location.pathname;

  const T = {
    on: false, seen: false, L: null, sets: null, el: null, covered: false, drawnAt: -1e9, placedAt: -1e9, taps: [],
    pad: TP, ver: 0, coarse: false, setL: {},        // the gamepad itself (a game that reads controllers on its own); ver: changes with every touch
    box: { l: 0, t: 0, w: 1, h: 1 }, ctl: [], stick: null, look: null, s: 1, p2d: null,
    // the game's controls, as data (see the top of this file); a set: one of layout.sets
    layout(L) {
      if (!L) return T;
      T.sets = L.sets || null; T.setL = {}; T.L = norm(L); T.base = T.L; T.coarse = media("(pointer: coarse)"); place();
      if (tiltWant == null) { tiltWant = store(TILTKEY) === "1"; if (tiltWant && !DEMO && T.L.tilt) startTilt(); }   // (a game's own: kept for it)
      if (!DEMO && T.coarse) T.show();
      return T;
    },
    // a set of the layout's (null: the layout itself); cheap to call every frame (each set is made once)
    use(name) {
      let L = T.base;
      if (name && T.sets && T.sets[name]) L = T.setL[name] || (T.setL[name] = norm(Object.assign({}, T.base.src, T.sets[name])));
      if (L !== T.L) { T.release(); T.L = L; place(); }
      return T;
    },
    attach(el) { if (el !== T.el) { T.el = el; place(); } return T; },
    can() { return !!(T.L && T.L.tilt && window.DeviceOrientationEvent && (T.seen || T.coarse)); },
    show() {
      if (T.on || DEMO || !T.L) return;
      T.on = true; T.seen = true; TP.connected = true; T.ver++; dress(); place(); hint();
    },
    // a controller or a key was used: the drawing goes (the touch player stays, holding nothing)
    away() { if (!T.on) return; T.on = false; T.ver++; T.release(); hint(); },
    release() { ptrs.clear(); T.stick = T.look = null; for (let i = 0; i < 17; i++) { TC[i] = 0; TB[i].pressed = false; TB[i].value = 0; } TP.axes[0] = TP.axes[1] = TP.axes[2] = TP.axes[3] = 0; T.dpadAt = -1; tiltAxes(); },
    // each frame, before the picture's writing: whether the controls are drawn now (covered: a menu is over it)
    frame(covered) {
      if (!T.on || !T.L) return false;
      T.covered = !!covered;
      if (T.covered || T.L.none) return false;
      const now = performance.now();
      if (now - T.placedAt > 1000) place();           // (the game may have moved its picture: looked at once a second)
      T.drawnAt = now; return true;
    },
    live() { return T.on && !T.covered && performance.now() - T.drawnAt < 300; },
    onTap(fn) { if (typeof fn === "function") T.taps.push(fn); },
    wanted() { return !!tiltWant; },
    tilting() { return tiltOn; },
    tilt(on) {
      tiltWant = !!on; keep(TILTKEY, tiltWant ? "1" : "0");
      if (!tiltWant) { stopTilt(); return Promise.resolve(false); }
      const D = window.DeviceOrientationEvent;
      if (!D) { tiltWant = false; keep(TILTKEY, "0"); return Promise.resolve(false); }
      if (typeof D.requestPermission === "function") {   // (iPhone, iPad: asked on a tap, once)
        let ask; try { ask = D.requestPermission(); } catch (e) { ask = Promise.reject(e); }
        return Promise.resolve(ask).then(r => { if (r === "granted") { startTilt(); return true; } tiltWant = false; keep(TILTKEY, "0"); return false; },
          () => { tiltWant = false; keep(TILTKEY, "0"); return false; });
      }
      startTilt(); return Promise.resolve(true);
    },
    level() { tiltN = null; },
    // a button pressed a moment, as if by a finger (a menu's own button: WYRD's Salvage)
    press(name) { const i = NUM[name]; if (i == null) return; setBtn(i, true); setTimeout(() => setBtn(i, false), 120); },
    vibrate(ms) { buzz(ms, 1); },
    // draws the controls into a picture w × h that covers the attached element, through paint.disc(x, y, r, colour,
    // alpha), paint.ring(…) and paint.text(s, x, y (its middle), px (its height), colour, alpha); colours are numbers
    draw(P, w, h) {
      if (!T.L || T.L.none) return;
      // (page pixels to the picture's: (x - bl) * kx; written out, so a frame makes nothing new)
      const b = T.box, bl = b.l, bt = b.t, kx = w / b.w, ky = h / b.h, k = (kx + ky) / 2, s = T.s;
      const st = T.stick;
      if (T.L.stick === "stick") {
        const r = T.R.stick, ox = st ? st.ox : T.R.sx, oy = st ? st.oy : T.R.sy;
        P.disc((ox - bl) * kx, (oy - bt) * ky, r * k, INK, st ? 0.3 : 0.16); P.ring((ox - bl) * kx, (oy - bt) * ky, r * k, BONE, st ? 0.55 : 0.28);
        P.disc((ox + (st ? st.dx : 0) - bl) * kx, (oy + (st ? st.dy : 0) - bt) * ky, r * 0.44 * k, BONE, st ? 0.62 : 0.3);
      } else if (T.L.stick === "dpad") {
        const d = T.R.dpad;
        for (let i = 0; i < 4; i++) {
          const on = TB[DIRB[DIRN[i]]].pressed, x = (T.R.sx + DX[i] * d * 0.62 - bl) * kx, y = (T.R.sy + DY[i] * d * 0.62 - bt) * ky, r = d * 0.36 * k;
          P.disc(x, y, r, on ? BONE : INK, on ? 0.45 : 0.3); P.ring(x, y, r, BONE, 0.5); P.text(ARROW[i], x, y, Math.max(7, 9 * s * k), BONE, 0.9);
        }
      }
      if (T.look) { const L = T.look; P.ring((L.ox - bl) * kx, (L.oy - bt) * ky, T.R.stick * k, BONE, 0.25); P.disc((L.ox + L.dx - bl) * kx, (L.oy + L.dy - bt) * ky, T.R.stick * 0.4 * k, BONE, 0.35); }
      for (let i = 0; i < T.ctl.length; i++) {
        const c = T.ctl[i], on = TB[c.i].pressed, x = (c.x - bl) * kx, y = (c.y - bt) * ky, r = c.r * k;
        P.disc(x, y, r, on ? BONE : INK, on ? 0.42 : 0.3); P.ring(x, y, r, c.col, on ? 0.9 : 0.55);
        if (c.pause) { const bw = Math.max(1, r * 0.2), bh = r * 0.5; P.bar(x - bw * 1.6, y - bh, bw, bh * 2, BONE, 0.9); P.bar(x + bw * 0.6, y - bh, bw, bh * 2, BONE, 0.9); continue; }
        // the letter (what the game's hints say), and under it in the button, small, what it does in this game
        P.text(c.label, x, c.word ? y - r * 0.16 : y, (c.big ? 22 : c.small ? 10 : 17) * s * k, on ? INK : BONE, 0.95);
        if (c.word) P.text(c.word, x, y + r * 0.55, 9 * s * k, on ? INK : BONE, 0.85);
      }
      if (P.end) P.end();
    },
    // for a plain 2D canvas (a game of its own): text(s, x, y (its middle), px, css) to write in the game's own letters
    draw2d(g, w, h, text) {
      if (!g) return;
      let P = T.p2d;                                 // (made once for a canvas and its letters, used every frame)
      if (!P || P.g !== g || P.write !== text) T.p2d = P = {
        g, write: text,
        disc(x, y, r, c, a) { g.globalAlpha = a; g.fillStyle = css(c); g.beginPath(); g.arc(x, y, r, 0, TAU); g.fill(); },
        ring(x, y, r, c, a) { g.globalAlpha = a; g.strokeStyle = css(c); g.lineWidth = Math.max(1, r * 0.09); g.beginPath(); g.arc(x, y, r, 0, TAU); g.stroke(); },
        bar(x, y, bw, bh, c, a) { g.globalAlpha = a; g.fillStyle = css(c); g.fillRect(x, y, bw, bh); },
        text(s, x, y, px, c, a) {
          g.globalAlpha = a;
          if (text) text(s, x, y, px, css(c));
          else { g.fillStyle = css(c); g.font = "700 " + Math.round(px * 1.25) + "px system-ui, sans-serif"; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText(s, x, y); }
        }
      };
      g.save(); T.draw(P, w, h); g.restore();
    }
  };
  const CSS = {};
  function css(c) { return CSS[c] || (CSS[c] = "#" + (0x1000000 + c).toString(16).slice(1)); }
  const DIRN = ["up", "right", "down", "left"], DX = [0, 1, 0, -1], DY = [-1, 0, 1, 0], ARROW = ["↑", "▶", "↓", "◀"];
  const NUM = { a: 0, b: 1, x: 2, y: 3, lb: 4, rb: 5, lt: 6, rt: 7, select: 8, start: 9 };
  function norm(L) {                                 // the layout as it's used: buttons by number, the stick's kind
    const src = L.src || L, out = { src, stick: src.stick == null ? "stick" : src.stick, look: !!src.look, tilt: src.tilt === false ? null : src.tilt || "xy",
      pause: src.pause === false ? null : src.pause || "start", none: !!src.none, buttons: [], top: [], app: src.app !== false, color: src.color != null ? src.color : null };
    const list = (from, to) => { for (const b of from || []) {
      const name = Array.isArray(b) ? b[0] : b.b, word = Array.isArray(b) ? b[1] : b.t;
      if (NUM[name] != null) to.push({ i: NUM[name], name, word: word ? String(word).toUpperCase() : "" });
    } };
    list(src.buttons, out.buttons); list(src.top, out.top);   // (top: small ones beside the pause button, for what is seldom pressed)
    return out;
  }

  // where everything goes: in page pixels, inside the attached element and the screen's safe area, sized for thumbs
  let probeEl = null;
  function safe() {
    if (!probeEl) {
      probeEl = document.createElement("div");
      probeEl.style.cssText = "position:fixed;left:0;top:0;width:0;height:0;visibility:hidden;pointer-events:none;" +
        "padding:env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left)";
      (document.body || document.documentElement).appendChild(probeEl);
    }
    const c = getComputedStyle(probeEl), n = v => parseFloat(v) || 0;
    return { t: n(c.paddingTop), r: n(c.paddingRight), b: n(c.paddingBottom), l: n(c.paddingLeft) };
  }
  function place() {
    if (!T.on || !T.L) return;
    T.placedAt = performance.now();
    const el = T.el, vw = innerWidth, vh = innerHeight;
    const r = el ? el.getBoundingClientRect() : { left: 0, top: 0, width: vw, height: vh };
    T.box = { l: r.left, t: r.top, w: Math.max(1, r.width), h: Math.max(1, r.height) };
    const sf = safe(), L0 = Math.max(r.left, sf.l), R0 = Math.min(r.left + r.width, vw - sf.r), T0 = Math.max(r.top, sf.t), B0 = Math.min(r.top + r.height, vh - sf.b);
    const w = Math.max(1, R0 - L0), h = Math.max(1, B0 - T0), s = Math.max(0.62, Math.min(1.45, Math.min(w, h) / 360)), m = 14 * s;
    T.s = s; T.area = { l: L0, t: T0, r: R0, b: B0 };
    const L = T.L, stick = 52 * s, dpad = 58 * s;
    T.R = { stick, dpad, sx: L0 + m + (L.stick === "dpad" ? dpad : stick), sy: B0 - m - (L.stick === "dpad" ? dpad : stick) };
    const big = 34 * s, small = 26 * s, col = L.color != null ? L.color : BONE, ctl = [];
    const px = R0 - m - big, py = B0 - m - big - 6 * s;   // (room for the word under it)
    // the first button big in the corner, up to four round it (far enough out that they don't touch), three more on a
    // ring outside those
    const n = L.buttons.length, ANG = [[], [205], [185, 265], [180, 225, 270], [180, 210, 240, 270]], gap = 2 * small + 10 * s;
    const inner = Math.max(big + small + 10 * s, n > 2 ? gap / (2 * Math.sin(Math.PI / 4 / Math.max(1, Math.min(4, n - 1) - 1))) : 0);
    L.buttons.forEach((b, k) => {
      let x = px, y = py, rr = big;
      if (k > 0) {
        const ring = k <= 4 ? 0 : 1, list = ring ? null : ANG[Math.min(4, n - 1)], j = k - 1;
        const a = (ring ? 198 + (j - 4) * 27 : list[j]) * Math.PI / 180, d = ring ? inner + gap : inner;
        x = px + Math.cos(a) * d; y = py + Math.sin(a) * d; rr = small;
      }
      ctl.push({ i: b.i, label: label("touch", b.name), word: b.word, x, y, r: rr, big: k === 0, col: k === 0 ? col : BONE });
    });
    // (the seldom pressed: small, beside the pause button, clear of the corners where games keep their maps)
    L.top.forEach((b, k) => ctl.push({ i: b.i, label: label("touch", b.name), word: b.word, x: (L0 + R0) / 2 + (k + 1) * 46 * s, y: T0 + m * 0.5 + 18 * s, r: 18 * s, col: BONE, small: true }));
    if (L.pause) ctl.push({ i: NUM[L.pause], pause: true, x: (L0 + R0) / 2, y: T0 + m * 0.5 + 16 * s, r: 16 * s, col: BONE });
    T.ctl = ctl;
    hint();
  }

  // the page, for touch: no scrolling, zooming or callouts; the home screen's manifest and icons (each game's folder
  // has app.webmanifest and icon-192.png / icon-512.png); the hint to turn a phone held upright
  let dressed = false, hintEl = null;
  function dress() {
    if (dressed) return; dressed = true;
    const d = document, st = d.createElement("style");
    st.textContent = "html.sofa-touch,html.sofa-touch body{touch-action:none;overscroll-behavior:none;-webkit-user-select:none;user-select:none;" +
      "-webkit-touch-callout:none;-webkit-tap-highlight-color:transparent}" +
      ".sofa-turn{position:fixed;left:0;right:0;text-align:center;font:600 14px/1.35 system-ui,sans-serif;color:rgba(239,230,210,.8);pointer-events:none;z-index:9;margin:0}" +
      ".sofa-tbar{position:absolute;z-index:3;top:calc(var(--u,6px)*2.4);left:calc(var(--u,6px)*2.4);display:flex;gap:calc(var(--u,6px)*1.6)}" +
      ".sofa-tbtn{padding:calc(var(--u,6px)*1) calc(var(--u,6px)*2.4);font-size:calc(var(--u,6px)*2.9);font-weight:800;text-transform:uppercase;" +
      "background:rgba(11,13,16,.85);color:#efe6d2;border:2px solid rgba(239,230,210,.5)}";
    (d.head || d.documentElement).appendChild(st);
    d.documentElement.classList.add("sofa-touch");
    d.addEventListener("touchmove", e => { if (T.on) e.preventDefault(); }, { passive: false });   // (no pull-to-refresh, no rubber band)
    d.addEventListener("gesturestart", e => e.preventDefault());   // (Safari's pinch)
    d.addEventListener("contextmenu", e => { if (T.on) e.preventDefault(); });
    if (T.L && T.L.app) {                            // add to the home screen: the game's own name, icon and full screen
      const head = d.head || d.documentElement, add = (tag, a) => { const e = d.createElement(tag); for (const k in a) e.setAttribute(k, a[k]); head.appendChild(e); };
      if (!d.querySelector('link[rel="manifest"]')) add("link", { rel: "manifest", href: "app.webmanifest" });
      if (!d.querySelector('link[rel="apple-touch-icon"]')) add("link", { rel: "apple-touch-icon", href: "icon-192.png" });
      add("meta", { name: "apple-mobile-web-app-capable", content: "yes" }); add("meta", { name: "mobile-web-app-capable", content: "yes" });
      add("meta", { name: "apple-mobile-web-app-status-bar-style", content: "black-translucent" }); add("meta", { name: "apple-mobile-web-app-title", content: d.title || "Sofa" });
    }
  }
  function hint() {                                  // a 16:9 picture on a phone held upright: a line under it
    const want = T.on && T.L && !T.L.none && innerHeight > innerWidth * 1.1 && T.box.w > T.box.h * 1.2;
    if (!want) { if (hintEl) hintEl.style.display = "none"; return; }
    if (!hintEl) { hintEl = document.createElement("p"); hintEl.className = "sofa-turn"; hintEl.textContent = "↻ Turn your phone on its side for a bigger picture"; document.body.appendChild(hintEl); }
    hintEl.style.display = "block"; hintEl.style.top = Math.round(T.box.t + T.box.h + 14) + "px";
  }

  // fingers: each one a role from where it came down (a button, the pause button, the stick, the D-pad, looking, or a
  // tap or swipe for the game and its menus)
  const ptrs = new Map();
  function setBtn(i, down) {
    TC[i] = Math.max(0, TC[i] + (down ? 1 : -1));
    const on = TC[i] > 0; TB[i].pressed = on; TB[i].touched = on; TB[i].value = on ? 1 : 0; TP.timestamp = performance.now(); T.ver++;
  }
  function hitBtn(x, y) {
    let best = null, bd = 1e9;
    for (const c of T.ctl) { const dx = x - c.x, dy = y - c.y, d = dx * dx + dy * dy, r = c.r * 1.3; if (d < r * r && d < bd) { bd = d; best = c; } }
    return best;
  }
  function stickTo(st, x, y, r) {
    let dx = x - st.x0, dy = y - st.y0; const l = Math.sqrt(dx * dx + dy * dy);
    if (l > r) { dx = dx / l * r; dy = dy / l * r; }
    st.dx = dx; st.dy = dy; return st;
  }
  function dpadTo(x, y) {
    const dx = x - T.R.sx, dy = y - T.R.sy, l = Math.sqrt(dx * dx + dy * dy);
    let want = -1;
    if (l > T.R.dpad * 0.18) want = Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? 1 : 3) : (dy > 0 ? 2 : 0);   // four ways: menus and grids
    if (want === T.dpadAt) return;
    if (T.dpadAt >= 0) setBtn(DIRB[DIRN[T.dpadAt]], false);
    T.dpadAt = want; if (want >= 0) setBtn(DIRB[DIRN[want]], true);
  }
  T.dpadAt = -1;
  function down(e) {
    if (e.pointerType === "mouse" || DEMO || !T.L) return;
    if (!T.on) T.show();
    const x = e.clientX, y = e.clientY, live = T.live(), A = T.area || { l: 0, r: innerWidth };
    let role = null;
    if (live) {
      const c = hitBtn(x, y);
      if (c) { role = { kind: "btn", c }; setBtn(c.i, true); }
      else if (T.L.stick === "dpad" && Math.hypot(x - T.R.sx, y - T.R.sy) < T.R.dpad * 1.25) { role = { kind: "dpad" }; if (T.dpadAt >= 0) setBtn(DIRB[DIRN[T.dpadAt]], false); T.dpadAt = -1; dpadTo(x, y); }
      else if (T.L.stick === "stick" && x < (A.l + A.r) / 2 && !T.stick) {
        // a floating stick: it starts where the thumb lands (kept inside the picture, so it's drawn whole)
        const r = T.R.stick, ar = T.area;
        const ox = Math.max(ar.l + r, Math.min(ar.r - r, x)), oy = Math.max(ar.t + r, Math.min(ar.b - r, y));
        role = T.stick = { kind: "stick", x0: x, y0: y, ox, oy, dx: 0, dy: 0, t0: performance.now(), far: 0, target: e.target };
      } else if (T.L.look && x >= (A.l + A.r) / 2 && !T.look) role = T.look = { kind: "look", x0: x, y0: y, ox: x, oy: y, dx: 0, dy: 0, t0: performance.now(), far: 0, target: e.target };
    }
    if (!role) role = { kind: "tap", x0: x, y0: y, t0: performance.now(), target: e.target, far: 0 };
    ptrs.set(e.pointerId, role);
    axes();
  }
  function move(e) {
    const role = ptrs.get(e.pointerId); if (!role) return;
    const x = e.clientX, y = e.clientY;
    if (role.kind === "stick" || role.kind === "look") { stickTo(role, x, y, T.R.stick); role.far = Math.max(role.far, Math.sqrt(role.dx * role.dx + role.dy * role.dy)); }
    else if (role.kind === "dpad") dpadTo(x, y);
    else if (role.kind === "btn") {                  // a thumb rolled onto the next button
      const c = hitBtn(x, y);
      if (c && c !== role.c && !c.pause && !role.c.pause) { setBtn(role.c.i, false); setBtn(c.i, true); role.c = c; }
    } else { const dx = x - role.x0, dy = y - role.y0; role.far = Math.max(role.far, Math.sqrt(dx * dx + dy * dy)); }
    axes();
  }
  function up(e) {
    const role = ptrs.get(e.pointerId); if (!role) return;
    ptrs.delete(e.pointerId);
    const ms = performance.now() - (role.t0 || 0);
    if (role.kind === "btn") setBtn(role.c.i, false);
    else if (role.kind === "stick" || role.kind === "look") {
      if (role.kind === "stick") T.stick = null; else T.look = null;
      // (a short touch that didn't move, where the stick lives: a tap after all, for a menu or the game drawn there)
      if (e.type === "pointerup" && role.far < 12 && ms < 350) offer("tap", e.clientX, e.clientY, 0, 0, role.target);
    }
    else if (role.kind === "dpad") { if (T.dpadAt >= 0) setBtn(DIRB[DIRN[T.dpadAt]], false); T.dpadAt = -1; }
    else if (e.type === "pointerup") {
      const dx = e.clientX - role.x0, dy = e.clientY - role.y0, d = Math.sqrt(dx * dx + dy * dy);
      const kind = role.far < 16 && d < 16 && ms < 600 ? "tap" : d > 28 && ms < 700 ? "swipe" : null;
      if (kind) offer(kind, e.clientX, e.clientY, dx, dy, role.target);
    }
    axes();
    if (e.type === "pointerup" && e.pointerType !== "mouse") gesture();
  }
  function offer(kind, x, y, dx, dy, target) {      // a tap or a swipe, to whoever takes it first
    const t = { kind, x, y, dx, dy, target };
    for (const fn of T.taps) { let took = false; try { took = fn(t); } catch (err) { /* one slip doesn't stop the rest */ } if (took) break; }
  }
  // things a browser allows only from a tap: the full screen (once: leaving it is the player's choice), and asking
  // for tilt where a game remembered it on
  let fsTried = false;
  function gesture() {
    const d = document, el = d.documentElement;
    if (!fsTried && T.on) {
      fsTried = true;
      const standalone = media("(display-mode: standalone)") || media("(display-mode: fullscreen)") || navigator.standalone;
      const f = el.requestFullscreen || el.webkitRequestFullscreen;
      if (!standalone && f && !d.fullscreenElement && !d.webkitFullscreenElement && window.self === window.top) { try { const r = f.call(el, { navigationUI: "hide" }); if (r && r.catch) r.catch(() => {}); } catch (err) { /* not here */ } }
    }
    if (tiltWant && !tiltGot && !tiltAsked && window.DeviceOrientationEvent && typeof DeviceOrientationEvent.requestPermission === "function") { tiltAsked = true; T.tilt(true); }
  }
  // the left stick: a finger on it, or else the tilt
  function axes() {
    const st = T.stick, lk = T.look, r = T.R ? T.R.stick : 1;
    if (st) { TP.axes[0] = st.dx / r; TP.axes[1] = st.dy / r; } else tiltAxes();
    TP.axes[2] = lk ? lk.dx / r : 0; TP.axes[3] = lk ? lk.dy / r : 0;
    TP.timestamp = performance.now(); T.ver++;
  }

  // tilt: which way is down, from the device's angles, turned into the screen's own (held either way up), against
  // where it was held when tilt came on (forward and back; left and right is against level)
  let tiltWant = null, tiltOn = false, tiltGot = false, tiltAsked = false, tiltN = null, tx = 0, ty = 0;
  const GAIN = 2.6;
  function orient(e) {
    if (e.beta == null || e.gamma == null) return;
    tiltGot = true;
    const b = e.beta * Math.PI / 180, g = e.gamma * Math.PI / 180, cb = Math.cos(b);
    const dx = Math.sin(g) * cb, dy = -Math.sin(b);  // (down, in the device's own x and y: x right, y up)
    const o = screen.orientation && screen.orientation.angle != null ? screen.orientation.angle : window.orientation || 0, a = o * Math.PI / 180;
    const sx = dx * Math.cos(a) - dy * Math.sin(a), sy = dx * Math.sin(a) + dy * Math.cos(a);
    if (tiltN == null) tiltN = sy;
    tx += (sx * GAIN - tx) * 0.35; ty += (-(sy - tiltN) * GAIN - ty) * 0.35;
    if (!T.stick) tiltAxes();
  }
  function tiltAxes() {
    if (T.stick) return;
    if (!tiltOn || !T.L || !T.L.tilt) { TP.axes[0] = 0; TP.axes[1] = 0; return; }
    TP.axes[0] = Math.max(-1, Math.min(1, tx)); TP.axes[1] = T.L.tilt === "xy" ? Math.max(-1, Math.min(1, ty)) : 0;
    TP.timestamp = performance.now();
  }
  function startTilt() { if (tiltOn) return; tiltOn = true; tiltN = null; tx = ty = 0; addEventListener("deviceorientation", orient); }
  function stopTilt() { if (!tiltOn) return; tiltOn = false; removeEventListener("deviceorientation", orient); tx = ty = 0; tiltAxes(); }

  addEventListener("pointerdown", down);
  addEventListener("pointermove", move);
  addEventListener("pointerup", up);
  addEventListener("pointercancel", up);
  addEventListener("keydown", e => { if (!e.repeat) T.away(); }, true);
  addEventListener("blur", () => T.release());
  addEventListener("resize", () => { setTimeout(place, 0); tiltN = null; });   // (after the game has fitted its picture)
  addEventListener("orientationchange", () => { setTimeout(place, 200); tiltN = null; });

  const cur = () => current || nobody;
  window.SofaPad = {
    on(h, fn) { if (typeof h === "function") handlers.push(h); else if (named[h] && typeof fn === "function") named[h].push(fn); },
    held(b) { return cur().held(b); },
    button(b) { return cur().button(b); },
    stick() { return cur().stick(); },
    stick2() { return cur().stick2(); },
    trigger(b) { return cur().trigger(b); },
    rumble(strong, weak, ms) { cur().rumble(strong, weak, ms); },
    active() { return performance.now() - usedAt < IN_USE; },
    connected() { return slots.some(p => p.pad && (p.pad !== TP || T.on)); },
    real() { return slots.some(p => p.pad && p.pad !== TP); },        // a controller of its own (the box's echo keys)
    kind() { return cur().kind(); },
    label(b) { return label(cur().kind(), b); },
    // the box's key presses for a controller's buttons, while one is in use: ignore them (the game has the pad itself)
    echo(e) { return performance.now() - usedAt < IN_USE && /^(Arrow|Enter$| $)/.test(e.key); },
    players() { return slots.filter(p => p.seen); },
    player(n) { n = Math.floor(n); return n >= 1 && n <= 16 ? slot(n) : nobody; },
    touch: T
  };
  addEventListener("gamepadconnected", () => { usedAt = performance.now(); call(handlers, "connected", "press"); });
  requestAnimationFrame(read);
})();
