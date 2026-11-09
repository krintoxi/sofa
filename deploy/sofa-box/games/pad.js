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
                                         is the first place a controller coming back takes, the same kind first */
(function () {
  if (window.SofaPad) return;
  const BTN = { a: 0, b: 1, x: 2, y: 3, lb: 4, rb: 5, lt: 6, rt: 7, select: 8, start: 9, up: 12, down: 13, left: 14, right: 15 };
  const NAMES = Object.keys(BTN), DIRS = ["up", "down", "left", "right"], FIRST = 380, AGAIN = 120, IN_USE = 2500;
  const handlers = [], named = { joined: [], left: [] }, slots = [];   // slots[n - 1] is player n
  let current = null, usedAt = -1e9;                // the player whose controller was used last; when any one was

  function kind(id) {
    if (/xbox|microsoft|x-box|xinput|045e/i.test(id)) return "xbox";
    if (/dualsense|dualshock|playstation|054c|wireless controller/i.test(id)) return "playstation";
    if (/nintendo|pro controller|057e/i.test(id)) return "nintendo";
    return "other";
  }
  function label(k, b) {
    const ps = k === "playstation";
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
  function use(p, t) { p.usedAt = t; if (t > usedAt) usedAt = t; }
  function pick(p, t) { p.pickedAt = t; current = p; }
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
      const g = list[p.index];
      if (!g || !g.connected || g.id !== p.id) { leave(p); changed = true; }
    }
    const fresh = [];
    for (let i = 0; i < list.length; i++) { const g = list[i]; if (g && g.connected && !slots.some(p => p.pad && p.index === g.index)) fresh.push(g); }
    if (fresh.length) {                              // several at once: the one pressed first, then standard ones
      fresh.sort((a, b) => (pressed(b) - pressed(a)) || ((b.mapping === "standard") - (a.mapping === "standard")) || a.index - b.index);
      for (const g of fresh) join(g, t);
      changed = true;
    }
    if (changed) choose();
    for (const p of slots) {
      if (!p.pad) continue;
      const g = list[p.index], now = p.now;
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
    connected() { return slots.some(p => p.pad); },
    kind() { return cur().kind(); },
    label(b) { return label(cur().kind(), b); },
    // the box's key presses for a controller's buttons, while one is in use: ignore them (the game has the pad itself)
    echo(e) { return performance.now() - usedAt < IN_USE && /^(Arrow|Enter$| $)/.test(e.key); },
    players() { return slots.filter(p => p.seen); },
    player(n) { n = Math.floor(n); return n >= 1 && n <= 16 ? slot(n) : nobody; }
  };
  addEventListener("gamepadconnected", () => { usedAt = performance.now(); call(handlers, "connected", "press"); });
  requestAnimationFrame(read);
})();
