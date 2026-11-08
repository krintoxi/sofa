/* Sofa Box games: the controller, read straight from the browser (the Gamepad API) every frame, the same on every
   controller (the browser's "standard" layout: A / ✕ at the bottom). For the box's own games, which are made for a
   controller first: keys and a mouse are for when there's nothing else.

   The box also turns a controller's buttons into key presses (for its menus), so while a controller is in use a
   game ignores those keys (SofaPad.active()): it would get every press twice. Back and Home stay the box's.

     SofaPad.on((button, how) => ...)   button: a b x y lb rb lt rt select start up down left right;
                                         how: "press", "release", or "repeat" (a direction held: menus and grids)
     SofaPad.held("left")               held now? (a direction: the D-pad or the left stick)
     SofaPad.button("left")             the button itself held now (the D-pad only, not the stick)
     SofaPad.stick()                    the left stick, {x, y} from -1 to 1 (a little play in the middle)
     SofaPad.stick2()                   the right stick, the same way (for looking round)
     SofaPad.trigger("rt")              how far a trigger (lt or rt) is pulled, 0 to 1
     SofaPad.rumble(strong, weak, ms)   shake the controller (0 to 1 each), where the controller and browser can
     SofaPad.active()                   a controller in use just now
     SofaPad.label("a")                 "A", or "✕" on a PlayStation controller */
(function () {
  if (window.SofaPad) return;
  const BTN = { a: 0, b: 1, x: 2, y: 3, lb: 4, rb: 5, lt: 6, rt: 7, select: 8, start: 9, up: 12, down: 13, left: 14, right: 15 };
  const DIRS = ["up", "down", "left", "right"], FIRST = 380, AGAIN = 120;
  const handlers = [], next = {};
  let prev = {}, pad = null, usedAt = -1e9;

  function kind(id) {
    if (/xbox|microsoft|x-box|xinput|045e/i.test(id)) return "xbox";
    if (/dualsense|dualshock|playstation|054c|wireless controller/i.test(id)) return "playstation";
    if (/nintendo|pro controller|057e/i.test(id)) return "nintendo";
    return "other";
  }
  function emit(b, how) { for (const h of handlers) { try { h(b, how); } catch (e) { /* one game's slip doesn't stop the pad */ } } }

  function read() {
    const pads = navigator.getGamepads ? Array.from(navigator.getGamepads()).filter(p => p && p.connected) : [];
    pad = pads.find(p => p.mapping === "standard") || pads[0] || null;
    const now = {}, t = performance.now();
    if (pad) {
      for (const b in BTN) now[b] = !!(pad.buttons[BTN[b]] && pad.buttons[BTN[b]].pressed);
      const ax = pad.axes[0] || 0, ay = pad.axes[1] || 0;
      now.left = now.left || ax < -0.5; now.right = now.right || ax > 0.5;
      now.up = now.up || ay < -0.5; now.down = now.down || ay > 0.5;
      if (Math.abs(ax) > 0.25 || Math.abs(ay) > 0.25 || Math.abs(pad.axes[2] || 0) > 0.25 || Math.abs(pad.axes[3] || 0) > 0.25) usedAt = t;
    }
    for (const b in BTN) {
      if (now[b] && !prev[b]) { usedAt = t; next[b] = t + FIRST; emit(b, "press"); }
      else if (!now[b] && prev[b]) emit(b, "release");
      else if (now[b] && DIRS.includes(b) && t >= next[b]) { next[b] = t + AGAIN; emit(b, "repeat"); }
    }
    prev = now;
    requestAnimationFrame(read);
  }

  window.SofaPad = {
    on(h) { handlers.push(h); },
    held(b) { return !!prev[b]; },
    button(b) { return !!(pad && pad.buttons[BTN[b]] && pad.buttons[BTN[b]].pressed); },
    stick() {
      if (!pad) return { x: 0, y: 0 };
      const dz = v => Math.abs(v) < 0.15 ? 0 : (v - Math.sign(v) * 0.15) / 0.85;
      return { x: dz(pad.axes[0] || 0), y: dz(pad.axes[1] || 0) };
    },
    stick2() {
      if (!pad) return { x: 0, y: 0 };
      const dz = v => Math.abs(v) < 0.12 ? 0 : (v - Math.sign(v) * 0.12) / 0.88;
      return { x: dz(pad.axes[2] || 0), y: dz(pad.axes[3] || 0) };
    },
    trigger(b) {
      const k = BTN[b], btn = pad && pad.buttons[k];
      return btn ? Math.max(btn.value || 0, btn.pressed ? 1 : 0) : 0;
    },
    rumble(strong, weak, ms) {
      const act = pad && pad.vibrationActuator;
      if (!act || !act.playEffect) return;
      try { act.playEffect("dual-rumble", { duration: ms || 120, strongMagnitude: Math.min(1, strong || 0), weakMagnitude: Math.min(1, weak || 0) }).catch(() => {}); } catch (e) { /* this one doesn't shake */ }
    },
    active() { return performance.now() - usedAt < 2500; },
    connected() { return !!pad; },
    kind() { return pad ? kind(pad.id) : null; },
    label(b) {
      const ps = this.kind() === "playstation";
      return ({ a: ps ? "✕" : "A", b: ps ? "○" : "B", x: ps ? "□" : "X", y: ps ? "△" : "Y", start: ps ? "Options" : "Menu" })[b] || b;
    },
    // the box's key presses for a controller's buttons, while one is in use: ignore them (the game has the pad itself)
    echo(e) { return this.active() && /^(Arrow|Enter$| $)/.test(e.key); }
  };
  addEventListener("gamepadconnected", () => { usedAt = performance.now(); emit("connected", "press"); });
  requestAnimationFrame(read);
})();
