# Low3D: the Sofa Box game engine

`low3d.js` is the engine the box's own page games are built on. Tidewing (`tidewing/`) is the first game on it.
It's one file: offline, no libraries, no build step. A game is one page that loads `../pad.js` and then
`../low3d.js`, and adds its own content and rules.

The engine grows with each game. When a game needs something another game could use, the general part goes
here and the game keeps only what is its own.

## What it promises every game

- **Smooth on a Raspberry Pi 3 (1 GB), better on a Pi 4 or 5.** At its first start on a box, the engine looks at
  the browser's GPU (`probe()`), runs a ~2 s test (`bench()`) and picks 3D or 2D and a quality rung (`plan()`).
  The result is kept per box and browser. While the game plays, the `Governor` keeps the frame rate steady:
  a rung down when frames run late, straight to a 30 fps rung when the game's own work fills the frame, a rung up
  when there's been room for a while (never back to one that ran late).
- **A 2D fallback.** With no WebGL, or a software one (SwiftShader, llvmpipe), the same world is drawn by `Flat`:
  a mode-7 ground from a picture of the world seen from above, a sky with far hills, and sprites `bake()`d once
  from the game's own meshes. It plays the same; it just looks flatter.
- **The controller first.** `Input` reads pad.js (buttons by their place: A/✕ at the bottom) and the keyboard. The
  box also turns controller presses into keys; `Input` drops those echoes, so nothing happens twice. A remote's or
  the phone's keys still come through. Back on the game's top screen is left to the box (it leaves the game);
  Home is always the box's.
- **Cheap to draw.** WebGL 1, drawn at a small size and scaled up by the browser. Flat-shaded meshes are built in
  code, with one draw call each. A world's still things are merged into chunks. Nothing new is made while a game
  plays: matrices, particles, trails and dynamic meshes are made once and reused.

## The rungs (`LADDER`)

| | rung 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|---|
| **3D** height drawn | 144 | 180 | 180 | 216 | 270 | 360 | 450 | 540 | 720 |
| draw distance (m) | 150 | 170 | 190 | 220 | 260 | 320 | 380 | 440 | 500 |
| frames a second | 30 | 30 | 60 | 60 | 60 | 60 | 60 | 60 | 60 |
| extras | | | | sun glow | + waves | | | | |
| **2D** height drawn | 112 | 135 | 160 | 160 | 200 | 240 | | | |

Where it starts: a Pi 3's GPU (VC4) on 3D rung 1 (up to 3); a Pi 4's (V3D 4.x) on 3; a Pi 5's (V3D 7.x) on 4;
a desktop GPU from the test. Software or no WebGL means 2D, its rung picked from the test's script time. A game
reads `E.rung` (`h`, `far`, `fps`, `waves`, `sun`, `detail`, `wakes`) and decides what each one means for it.

## A new game, from the start

```html
<div id="view">
  <canvas id="gl" class="world hidden"></canvas><canvas id="flat" class="world hidden"></canvas>
  <div id="title" class="screen hidden"><div class="menu"><div class="item" data-do="play">Play</div></div></div>
  <div id="loading"><div class="bar"><i id="loadbar"></i></div><p id="loadtext"></p></div>
  <div id="fps" class="hidden"></div>
</div>
<script src="../pad.js"></script>
<script src="../low3d.js"></script>
<script>
const L3 = Low3D, cam = L3.camera(), synth = new L3.Synth();
const input = new L3.Input({ keys: { Enter: "a", Escape: "back", ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right" },
  on: (b, how) => { if (how === "press" || how === "repeat") menu.button(b, how); }, top: () => menu.top() });
const menu = new L3.Menu({ top: "title", screens: { title: {} }, sound: n => synth.play(n),
  choose: (el, act) => { if (act === "play") { menu.hide(); /* start */ } } });
const E = L3.game({ id: "my-game", view: view, gl: gl, flat: flat, fps: fps, input,
  loading: { el: loading, bar: loadbar, text: loadtext },
  ready() { menu.show("title"); synth.start(); },
  prepare(E) {          // build what this mode needs: meshes on the GPU (E.g3), or sprites baked for E.flat
  },
  update(dt) {          // the game's rules, 60 times a second
  },
  draw(now) {           // each frame drawn
    L3.begin(E, cam);   // GL: then g3.lit(…), g3.sea(…), g3.sky(…), g3.glow(…); 2D: flat.sprite(…), then flat.flush()
  } });
E.start();
</script>
```

Copy Tidewing's `<style>` for the view, menus, HUD and loading screen. In the address, `#fps` shows the frame rate
and rung, `#flat` or `#gl` forces a renderer, `#rung=N` holds a rung, and `#test` is for a game's own checks.

## The parts

**Hardware.** `probe()` returns what the browser gives: WebGL 1 and 2, the unmasked GPU name, `family` (pi3, pi4,
pi5, software, mobile, desktop or none), cores, memory and a `key` for saved tuning. `bench(gl, done, step)` is
the ~2 s test. `plan(probe, bench)` returns `{mode, rung, top, why}`. `rows()` and `line()` turn all that into text
for a "This box" screen. `Governor(ladder, rung, top, onChange)` keeps the frame rate steady.

**3D (`GL`).**
- `upload(mesh, dynamic)` puts a mesh on the GPU; `update(handle, mesh)` sends a dynamic one again.
- `begin(eye…, target…, fov, near, far, roll)` starts a frame, `sees(x, y, z, r)` culls against the view.
- `lit(handle, matrix, r, g, b, glow)` draws a mesh, lit by the sun and fogged.
- `glow(handle, matrix, r, g, b, a, "add" or "mix", pointSize)` draws see-through things: lights, shadows, trails,
  and round particles when given a point size.
- `sea(handle, texture, x0, z0, size, time, waves)` draws a water or ground plane with a picture on it; with
  waves, the facets rise and fall and catch the light (Pi 4 and up).
- `sky(sun)` draws only where nothing else was drawn. `light({sun, sunCol, amb, ground, fog, top, horizon, near,
  far})` sets the lighting, and `texture(canvas, mip)` makes a texture.
- `can("waves")` and `can("sun")` say what this GPU can do (each program is made the first time it's used).

**2D (`Flat`).** `size(w, h)`; `ground(canvas, x0, z0, size, outside)` (mip levels made, so far ground doesn't
shimmer); `air({top, horizon, fog, hill, hills, near, far})`; `draw(camera…)`; `project(x, y, z, out)`;
`sprite(s, x, y, z, scale, alpha)` and `poly(12 numbers, color)` queue things, and `flush()` draws them far to near.
`bake(mesh, {yaw, pitch, roll, ppu, light, glow})` draws a mesh once into a sprite, lit the same way as 3D.

**Building things.**
- `Mesh`: `at(x, y, z, yaw, sx, sy, sz, pitch, roll)` sets where the next part goes.
- Parts: `tri`, `quad`, `both` (seen from both sides), `box`, `stack` (rings up an axis: cylinders, cones, rocks,
  hulls), `ico` and `disc`. A face is lit flat and faces away from the "outside" point you give.
- `Mesh.join(list)` merges meshes; each vertex is 20 bytes.
- `Kit` has ready-made pieces: `palm`, `pine`, `rock`, `columns`, `hut`, `lighthouse`, `buoy`, `shadow`,
  `hills` and `skyline` (far hills for 3D and 2D), and `blob` (a soft 2D spot).
- `Chunks(size, cell)` holds a world's still things: `mesh(x, z, "base" | "detail" | "glow")` to build into,
  `upload(g3)`, then `draw(g3, x, z, far, detail)` each frame (culled, nearest first).

**Moving things.**
- `Path(points, {closed, step})` is a smooth line to race, ride or patrol along. It has `at(s)`, `side(s, off)`,
  `near(x, z, hint)`, `delta(a, b)`, `curve` (how sharply it bends ahead) and `knots` (where the points fall).
- `Trail` makes wakes, light trails and tyre marks: `step(dt, x, z, strength)`, then `ribbon(mesh, …)` for 3D or
  `spots(flat, …)` for 2D.
- `Particles(n)` is a fixed pool: `emit`, `step`, `points(mesh)` for 3D, `sprites(flat)` for 2D.
- Cameras: `camera()`; `chase(cam, thing, dt, dist, height, ahead)`; `orbit(cam, x, z, radius, height, angle)`;
  `begin(E, cam)` draws a frame from a camera in whichever renderer the box has.

**The rest.**
- `game({...})` sets up the screen (16:9, as big as fits, `--u` a hundredth of its height for CSS), the tuning,
  the loop (fixed 60 steps a second, drawing as the governor says), `#fps`, and the switch to 2D if the GPU goes
  away. It returns `E`, with `mode`, `g3`, `flat`, `rung`, `gov`, `rows()`, `retest()` and `setPicture()`.
- `Input` and `Menu`: screens of `.item` elements. A screen can be a list, a `grid` of columns, a `row`, or
  `options` (◀ ▶ to change values).
- `Synth`: `play(name)` plays effects, and `define(name, fn)` adds your own. `song({seed, root, tempo, calm})`
  writes a tune from a seed and plays it. `drone("saw" | "noise")` is a sound that goes on (an engine, the wind),
  changed with `set(pitch, brightness, volume)`.
- `U` has small tools: `clamp`, `lerp`, `wrap`, `rand(seed)`, colors (`hex`, `shade`, `mix`), `time` and `ord`.

## Checking a game

- In a browser: `python3 deploy/sofa-box/sofa-box-agent.py` with `SOFA_BOX_CONF=<tmp> SOFA_BOX_ICONS=0
  SOFA_BOX_UINPUT=0`, then `http://127.0.0.1:8091/box/games/<id>/#fps`.
- On a box: the graphics check at `http://127.0.0.1:8091/box/games/probe/` (in the box's browser) shows the GPU,
  the test, the rung a game would pick, and a scene drawn that way with its live frame rate. Tidewing's "This box"
  screen shows the same, plus what the governor has done.
- `tests/test_box_games.py` (`TheEngine`) checks that games stay offline and on the controller, that every page's
  script parses, and that each kind of box gets the right drawing.

## Next, as games need it

Height-field ground (hills you drive over), simple collision shapes, two players on one screen, and parts that
move together (characters, doors). Each one comes with the game that first needs it.
