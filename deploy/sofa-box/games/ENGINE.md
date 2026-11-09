# Low3D: the Sofa Box game engine

`low3d.js` is the engine the box's own page games are built on. It has two ways to draw, for two kinds of game:

- **3D** (`GL`, with a 2D fallback, `Flat`), for open worlds. Tidewing (`tidewing/`), a racer over the sea, is
  drawn this way.
- **Drawn by the processor** (`Ray`), for worlds on a grid: rooms, corridors, doors and floors at any height. It
  looks the same on every box, GPU or not, and the GPU only adds a glow. Ironmaw (`ironmaw/`), an old-style
  shooter, is drawn this way.

It's one file: offline, no libraries, no build step. A game is one page that loads `../pad.js` and then
`../low3d.js`, and adds its own content and rules.

For games in pixels (side-on or from above: platformers, brawlers, tactics, racers seen from the sky) there's a
second file on top of it, **Low2D** (`low2d.js`): see [Low2D: the 2D engine](#low2d-the-2d-engine). Cinder Knight
(`cinder-knight/`), Neon Brawler (`neon-brawler/`) and Micro Drifters (`micro-drifters/`) are built on it, and the
box's other small page games move onto it as each is made better.

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
  Home is always the box's. Every controller is a player of its own, for games with more than one (see Several
  players).
- **Cheap to draw.** WebGL 1, drawn at a small size and scaled up by the browser. Flat-shaded meshes are built in
  code, with one draw call each. A world's still things are merged into chunks. Nothing new is made while a game
  plays: matrices, particles, trails and dynamic meshes are made once and reused.

## Which way to draw

- Use 3D for big open spaces, for things seen from far off, and for a sea, sky and hills. It's sharp where there's
  a GPU, and the 2D sea where there isn't.
- Use `Ray` for indoor places on a grid, where it's all walls, steps and doors (shooters, dungeon crawlers, mazes,
  tower defence on a grid). A Pi 3 draws it at 320×180 whether or not Chromium gives it the GPU, and every pixel is
  under the game's control.

## The rungs (`LADDER`)

| | rung 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|---|
| **3D** height drawn | 144 | 180 | 180 | 216 | 270 | 360 | 450 | 540 | 720 |
| draw distance (m) | 150 | 170 | 190 | 220 | 260 | 320 | 380 | 440 | 500 |
| frames a second | 30 | 30 | 60 | 60 | 60 | 60 | 60 | 60 | 60 |
| extras | | | | sun glow | + waves | | | | |
| **2D** height drawn | 112 | 135 | 160 | 160 | 200 | 240 | | | |

| **Ray** height drawn | 120 | 144 | 180 | 180 | 216 | 270 | 360 | | |
| frames a second | 30 | 30 | 30 | 60 | 60 | 60 | 60 | | |
| glow (WebGL) | | | | | yes | yes | yes | | |

Where it starts: a Pi 3's GPU (VC4) on 3D rung 1 (up to 3); a Pi 4's (V3D 4.x) on 3; a Pi 5's (V3D 7.x) on 4;
a desktop GPU from the test. Software or no WebGL means 2D, its rung picked from the test's script time.
A `Ray` game starts from the script time alone (`planRay`): the processor does its drawing. A Pi 3 is held to
rung 3 at most (320×180). A game
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
and rung, `#flat` or `#gl` forces a renderer, `#rung=N` holds a rung, and `#test` is for a game's own checks. For
checks: `#slow=N` makes each frame's work take N times as long (a slower processor), and `#threads=N` holds a Ray
game's helpers (0: the page draws it all). Chrome's own CPU slowdown isn't a fair stand-in for a Pi: slowed "10×" it
stretches a short frame's work about 3×, and it doesn't slow web workers at all.

## A game drawn by the processor

`L3.game({ kind: "ray", ... })`: the engine sizes `E.screen` (a picture, `E.screen.u32`) to the rung and calls
`resized(E)`. The game hands that buffer to a `Ray`, draws into it in `draw()`, and the engine shows it each frame.
That's WebGL with a glow on a real GPU, or a 2D canvas otherwise (picture "plain": always the canvas).

```js
const pal = new L3.Palette(RAMPS, [14, 15]);     // 16 colour ramps of 16 shades; ramps 14 and 15 glow (never darken)
const ray = new L3.Ray(pal); ray.tex = [L3.Tex.make((u, v) => …), …]; ray.sky = …;
const m = new L3.RayMap(w, h);                   // per cell: solid, wtex (wall), floor/ceil heights, ftex/ctex, light,
                                                  // stex (a step's face), utex (a ceiling's lip, a door); ctex 255: sky
function resized(E) { ray.size(E.screen.w, E.screen.h, E.screen.u32); }
function draw() {
  ray.render(m, { x, y, z: eyeHeight, a: facing, pitch, fov });
  ray.sprite(pal.sprite(L3.bake(mesh, {...})), x, y, z, light);   // things in the world, behind what's nearer
  ray.flush(); ray.blit(gunSprite, w / 2, h, scale, light);       // a weapon in hand
}
```

A door is a cell whose ceiling comes down to its floor, and a lift is a cell whose floor moves. Set `m.ceil[i]` or
`m.floor[i]` each frame and the renderer, the walking (`m.move`, `m.open`), the sight lines (`m.see`, `m.trace`) and
the way-finding (`m.flow`, which can be told which doors walkers may open) all follow. `m.dyn` adds light for a
frame (muzzle flashes, explosions), and `m.seen` marks what's been seen (an automap).

Light can have a colour. `pal.tints([[r, g, b], …])` (then `pal.maps(…)`) gives each tint a colormap of its own, and
a cell's `m.tint[i]` picks one (lava's warm light, ice's cold one, a lamp's); `m.dtint[i]` does it for a frame (an
alarm, a muzzle flash). It costs nothing a pixel: the colormap is picked once a cell. Glowing colours stay as they are.

Walls and floors keep the marks left on them: `new L3.Marks(ray, m, max)`, then `marks.wall(i, face, x, y, z, stamp)`
where a line hit a wall (`m.trace` says which cell and face: `m.hitI`, `m.hitFace`), or `marks.floor(x, y, stamp)`. A
stamp is `{r, kind}`: a rivet hole, scorch, a splat or stain of a colour, frost. Each mark goes into a copy of that
face's or floor's texture, so drawing it costs nothing; the oldest copy is given back when `max` are used.

Some walls you see through: `m.mask[i]` is a texture made with `Tex.mask` (0 where you see past it: bars, a railing,
a window, a fence). It's drawn one cell tall from the floor, over what's behind it; nothing walks through it, but
sight lines and shots pass.

Where the processor has cores to spare (four on every Pi), `ray.threads(n)` has n helpers (web workers) each draw a
strip of the picture at the same time, a frame or two behind the page so the page's work and the drawing overlap
(`planRay` says how many: `E.plan.helpers`). The game's code doesn't change: `render`, `sprite`, `flush` and `blit` work
the same. `ray.prime(list)` sends a level's textures and sprites ahead; give the engine `missed: () =>
ray.takeMissed()` and `helperWork: () => ray.helperMs` so the governor counts the helpers' frames.

A split screen is one `Ray` a view, each with a picture of its own (`r.size(w, h, new Uint32Array(w * h))`), drawn as
usual and put into the screen's with `r.paste(E.screen.u32, E.screen.w, x, y)`; where there are cores to spare each
view can have a helper of its own (`r.threads(1)`). One set of sprites serves every crew: `pal.remap(from, to)` swaps
each ramp in `from` for the one in `to`, shade for shade, and goes as `ray.sprite`'s last argument. Things that walk
can be told what to keep out of: `m.flow(x, y, step, room, through, avoid)` goes round the cells set in `avoid` (fire)
and crosses them only when there's no other way.

## The parts

**Hardware.** `probe()` returns what the browser gives: WebGL 1 and 2, the unmasked GPU name, `family` (pi3, pi4,
pi5, software, mobile, desktop or none), cores, memory and a `key` for saved tuning. `bench(gl, done, step)` is
the ~2 s test. `plan(probe, bench)` returns `{mode, rung, top, why}`. `rows()` and `line()` turn all that into text
for a "This box" screen. `Governor(ladder, rung, top, onChange)` keeps the frame rate steady.

**3D (`GL`).**
- `upload(mesh, dynamic)` puts a mesh on the GPU; `update(handle, mesh)` sends a dynamic one again.
- `begin(eye…, target…, fov, near, far, roll, rect)` starts a frame (rect: `[x, y, w, h]`, one view of a split
  screen), `sees(x, y, z, r)` culls against the view.
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
`view(rect)` before `draw` puts the next frame in a part of the picture (a split screen's view; `null`: all of it).
`bake(mesh, {yaw, pitch, roll, ppu, light, glow})` draws a mesh once into a sprite, lit the same way as 3D.

**Building things.**
- `Mesh`: `at(x, y, z, yaw, sx, sy, sz, pitch, roll)` sets where the next part goes.
- Parts: `tri`, `quad`, `both` (seen from both sides), `box`, `stack` (rings up an axis: cylinders, cones, rocks,
  hulls), `ico` and `disc`. A face is lit flat and faces away from the "outside" point you give.
- `Mesh.join(list)` merges meshes; each vertex is 20 bytes. `mesh.turn(yaw, pitch, roll, pivot…)` turns all
  that's built about a point. Build a body's parts separately, turn them, and join them: legs that walk, a body
  that leans, falls or lies down.
- Faces made with `m.alpha = 254` glow. `bake()` draws them unlit, and `Palette.sprite` keeps them full-bright
  (eyes, fire, screens).
- `Kit` has ready-made pieces: `palm`, `pine`, `rock`, `columns`, `hut`, `lighthouse`, `buoy`, `shadow`,
  `hills` and `skyline` (far hills for 3D and 2D), and `blob` (a soft 2D spot).
- `Chunks(size, cell)` holds a world's still things: `mesh(x, z, "base" | "detail" | "glow")` to build into,
  `upload(g3)`, then `draw(g3, x, z, far, detail)` each frame (culled, nearest first).
- `Land(size, n, base)` is ground with height: an n × n grid over the world, `fill((x, z) => height)`, then `at(x,
  z)` anywhere (to float on it, or bump into the shore) and `slope(x, z, out)`. `mesh(chunks, colour(h, steep),
  water)` builds its triangles into chunks where it's near or above the water; for the 2D renderer, `paint(ctx, k,
  colour, sun, water, shallow, depth)` paints it into the ground's picture (shaded by its slopes, shallows round it)
  and `banks(colour, water)` gives the quads that stand its edge up from the water. Tidewing's cliffs, gorge and
  volcano are made this way.

**Moving things.**
- `Path(points, {closed, step})` is a smooth line to race, ride or patrol along. It has `at(s)`, `side(s, off)`,
  `near(x, z, hint)`, `delta(a, b)`, `curve` (how sharply it bends ahead) and `knots` (where the points fall).
- `Trail` makes wakes, light trails and tyre marks: `step(dt, x, z, strength)`, then `ribbon(mesh, …)` for 3D or
  `spots(flat, …)` for 2D.
- `Particles(n)` is a fixed pool: `emit`, `step`, `points(mesh)` for 3D, `sprites(flat)` for 2D.
- Cameras: `camera()`; `chase(cam, thing, dt, dist, height, ahead)`; `orbit(cam, x, z, radius, height, angle)`;
  `begin(E, cam, near, far, rect)` draws a frame from a camera in whichever renderer the box has. Two players:
  a camera each and a rect each (the screen's top half and bottom half), and the game draws its world twice.

**Drawn by the processor.**
- `Palette(ramps, glowRamps)` has `cmap` (32 light levels × 256), `maps(fog, haze)` for darkness or a coloured
  haze, `near(r, g, b)`, `sprite(canvasOrBake)` (a sprite as indices), and `color(i)`.
- `Tex.make(fn)` makes 64×64 textures (`fn(u, v)` → an index), with `Tex.noise(seed)`, `Tex.fbm` and
  `Tex.shade(ramp, k)` to help.
- `Palette.tints(list)`: coloured light (see above); `Palette.remap(from, to)`: a sprite in other colours.
- `RayMap`: `open`, `move`, `floorAt`, `trace` (and what it hit: `hitI`, `hitFace`), `see`, `flow` (round what to
  `avoid`); per cell `tint`, `dtint`, `mask`, and the marks' `wdec`, `fdec`.
- `Ray`: `render`, `sprite`, `dot` (a speck; none right at the eye), `flush`, `blit`, `project`, `paste` (a view into
  a split screen), and `dim` (light lost with distance), `minL` (the darkest it gets) and `maxD` (how far it looks);
  `threads(n)`, `prime(list)`, `takeMissed()`, `helperMs`.
- `Marks(ray, map, max)`: `wall(i, face, x, y, z, stamp)`, `floor(x, y, stamp)`.
- `Screen(canvas2d, canvasGL, useGL)` shows the picture (`size`, `present`); `planRay(probe, bench)` picks a
  `Ray` game's starting rung.

**The controller (`pad.js`).** Beyond the buttons and the left stick: `SofaPad.stick2()` (the right stick),
`SofaPad.trigger("rt")` (how far a trigger is pulled), `SofaPad.button("left")` (the D-pad itself, not the stick),
and `SofaPad.rumble(strong, weak, ms)`. These follow whichever controller was used last; each player's own are
`SofaPad.player(n)`'s (Several players, below).

**The rest.**
- `game({...})` sets up the screen (16:9, as big as fits, `--u` a hundredth of its height for CSS), the tuning,
  the loop (fixed 60 steps a second, drawing as the governor says), `#fps`, and the switch to 2D if the GPU goes
  away. It returns `E`, with `mode`, `g3`, `flat`, `rung`, `gov`, `rows()`, `retest()` and `setPicture()`.
- `Input` and `Menu`: screens of `.item` elements. A screen can be a list, a `grid` of columns, a `row`, or
  `options` (◀ ▶ to change values).
- `Synth`: `play(name)` plays effects, `play(name, pan, gain)` from a place (left -1 to right 1, and how loud), and
  `define(name, fn)` adds your own. `song({seed, root, tempo, calm})`
  writes a tune from a seed and plays it. `drone("saw" | "noise")` is a sound that goes on (an engine, the wind),
  changed with `set(pitch, brightness, volume)`.
- `U` has small tools: `clamp`, `lerp`, `wrap`, `rand(seed)`, colors (`hex`, `shade`, `mix`), `time` and `ord`.

## Several players

Every controller is a player, numbered in the order they come: as each one connects, and when several turn up at
once (a browser shows a page every controller at its first press) the one pressed first is player 1. Someone can
join at any time. A player whose controller goes away (switched off, flat) keeps the number, and the first
controller to come back takes the first place free, the same kind of controller first. The one-player calls
(`SofaPad.held`, `input.held`, `input.stick`…) follow whichever controller was used last, so a one-player game
works with any of them.

```js
const input = new L3.Input({ keys: KEYS, top: () => menu.top(),
  on: (b, how, who) => { },      // who: the player whose controller it was (1, 2, …), or 0 for a key (keyboard, remote, phone)
  joined: n => addPlayer(n),      // a controller became player n (someone new, or back)
  left: n => holdPlace(n) });     // player n's controller went away
const p2 = input.player(2);       // the same object for good: it reads nothing until someone is player 2
p2.held("left"); p2.stick(); p2.stick2(); p2.trigger("rt"); p2.button("up"); p2.rumble(0.6, 0.3, 120);
p2.label("a"); p2.kind(); p2.connected(); p2.active();
input.players();                  // the numbers of those who have joined so far
```

Without Low3D it's pad.js alone: `SofaPad.players()`, `SofaPad.player(n)` (with `n` and the same calls, `on(h)`
among them, for that controller's own presses), `SofaPad.on("joined", p => …)` and `SofaPad.on("left", p => …)`;
`SofaPad.on((b, how, p) => …)` hears every controller and says whose it was. The box turns every controller's
presses into keys; while any of them is in use (a direction held included), those keys are dropped as before.

## Playing by itself, and the games check

A game opened with `#demo` at the end of its address plays by itself: an attract mode that takes no controller and
keeps nothing (no saves, records or settings), and says so with `window.SofaStats.demo = true`. The games check
uses it to measure each game playing. In a Low3D game the engine sets `E.demo` and makes `window.SofaStats` (its
`ready`, `tier`: the mode and rung, `fps`: frames drawn a second, and `workMs`: its work a frame drawn); the game
sets `demo`. A game of its own sets `window.SofaStats = { demo: true }`, with `tier`, `fps` and `workMs` if it has
them. Tidewing rides behind a rival, Cosmic Cascade drops its own gems, Micro Drifters' car drives itself and
Shadow Heist's thief wanders the level.

The games check is in the graphics check ("Games check", or `probe/#games`; `&run` starts it, `&secs=N` measures N
seconds a game, `&only=id+id` checks those alone). It opens each game in `games.json`'s `games` in turn, in a frame
of its page with `#demo`, lets it settle, and times 15 s from the game's own window: frames a second, late frames
(more than 25 ms apart), the slowest, the game's work each frame (its requestAnimationFrame callbacks), memory
(the box's free memory from the agent, and the page's script memory where the browser gives it exactly: Chromium
can round it and refresh it only every 20 minutes, and the check notices), and what `SofaStats` says. The frame can't take the keys and the game sees no
controller, so B stops the check and nothing starts or saves. On a Pi 3 it is the measure of each game.

## Low2D: the 2D engine

`low2d.js` is loaded after `../pad.js` and `../low3d.js`, and builds on Low3D: its probe and processor test, its
`Input` (the controller first, every controller a player, the box's echo keys dropped), its `Synth`, its `Governor`,
`#demo` and `window.SofaStats`, and `#slow=N`. What it adds is the 2D part, the same for every game on it, so they
all have the same menus, pause, options and saves, the same controller handling, and the same tuning to the box.

### What it promises every game

- **A pixel picture**, 480×270, drawn crisp. On a 1080p TV it's 4 times as big exactly (on 4K, 8); where a whole
  number doesn't fill enough of the screen (a 720p TV: 2.67) it's as big as fits, still without smoothing.
- **A fixed-step loop**: the game's rules run 60 steps a second whatever is drawn. A frame that comes a whole
  number of steps after the last takes exactly that many (no judder at 60 or at 30). `G.stop(ms)` holds the world
  still for a moment (hit-stop) while the picture goes on; `G.shake(k)` shakes it (Options: off, gentle, full).
- **Three looks and two paces, held steady.** A game reads `G.tier` and decides what each means for it:
  - *light*: the light map at a quarter of the screen's size, smoothed; a few coloured glows; fewer particles; two
    background layers;
  - *full*: the light map at half the size in dithered steps (the pixel look); every glow; three layers; depth (a
    block's far face receding into the screen); a layer in front of the camera; reflections in still water;
  - *rich*: as full, with the light at the screen's own size, smooth, and more particles, glows and weather.

  Each is drawn at 60 frames a second or a **steady 30** (a frame on every other refresh, never one late). A steady
  30 is better than an uneven 60, so on its own a box goes rich 60, full 60, light 60, then full at a steady 30 (twice
  the time a frame is room for the full look), then light at 30, and **never below 30**.
- **The box picks.** A Pi 3 (its GPU, or any 1 GB ARM board) starts light at 60 and goes no higher at 60; a slow
  processor (the test, as `#slow` makes it) starts light and may climb to full; a fast one with a real GPU (a
  desktop, a Pi 5) starts rich; the rest start full and may climb. The box's test runs once for every game on the
  engine (kept as `sofa:box`); each game keeps where its own governor settled.
- **The governor steps down before a stutter shows**: it judges each 2 s by the 90th percentile of the frame's own
  work, and goes a rung down when that passes 70% of the frame, or when more than 6% of frames came late. After three
  calm windows (none late, under 35%) it goes a rung up, but never back to a rung that failed twice.
- **Options in every game**: music and sounds, rumble, screen shake, **Look** (for this box, rich, full, light)
  and **Frames** (for this box, smoothest at 60, steady 30). The same choices work in the box's browser, in Sofa, or
  on a website: "for this box" is the auto-detect.

### A new game, from the start

```html
<canvas id="c"></canvas>
<script src="../pad.js"></script><script src="../low3d.js"></script><script src="../low2d.js"></script>
<script>
const L2 = Low2D;
const G = L2.game({ id: "my-game", canvas: document.getElementById("c"),
  keys: { " ": "a", x: "x" }, keyNames: { a: "SPACE" },          // keys beyond Enter, Escape and the arrows
  on(b, how, who) { },                    // presses the menus didn't take (who: the player, 0 for a key)
  ready(G) { menu.show("title"); },       // after the box's tuning
  tier(G, t) { light.size(t.light); },    // the look or the pace changed
  update(dt) { },                         // 60 times a second
  draw(g) { },                            // the world: through the camera's zoom and tilt
  hud(g) { } });                          // over it, never zoomed
const pad = G.control();                  // what a fixed step reads: pad.x(), pad.held("a"), pad.take("a", 120)
const menu = new L2.Menu(G, { top: "title", screens: { title: { items: [{ t: "PLAY", act: "play" }] },
  options: { title: "OPTIONS", back: "title", items: L2.optionItems() } }, choose(it) { } });
G.menu = menu;
G.start();
</script>
```

Cinder Knight keeps its rules (the knight's moves, the stages and what's in them) in a script of their own before
the game's, so the tests can play every stage in node with the game's own physics.

### The parts

- `game(o)` → `G`: `g` (the canvas's 2D context), `tier`, `gov`, `control(n)`, `input` (Low3D's), `synth`,
  `shake(k)`, `stop(ms)`, `fade(fn)`, `zoomOn(z, x, y)` and `tiltBy(a)` (the camera's moments: a boss walks in, a
  hard blow; off with screen shake), `rumble(s, w, ms, who)`, `label(b)` (a button as the player knows it: A or ✕,
  or the key's name), `options(o)`, `rows()`.
- `Control`: one player's controller and, for player 1 and "anyone", the keys: `x()`, `y()`, `held(b)`, and
  `take(b, ms)`: a press kept a moment, so a fixed step never misses one (and a jump pressed just before landing
  still jumps).
- `TileMap(w, h, ts)`: tiles drawn once into 256-pixel chunks and copied after. `paint(g, x, y, kind, map, px, py)`
  draws a tile (it can look at its neighbours); `flags[kind]` says `SOLID`, `ONEWAY` (a ledge you jump up through)
  or `HURT`. A changed tile (a wall broken, a ledge crumbling) is drawn again where it is, not its whole chunk.
  `move(body, dx, dy, drop)` moves a box through it (never through a wall, however fast); `touch`, `ground`,
  `solidAt`. `drawDepth(g, camX, camY, vw, vh, k, colour)` draws the blocks' far faces, each chunk's shape smaller
  towards the middle of the view, so a platform shows its side as the camera passes.
- `art(rows, palette)`, `sheet(frames, palette, {ax, ay})` (each frame facing both ways, with a flash copy),
  `put(g, sheet, frame, x, y, face, flash)`; `flip`, `silhouette`, `outline`.
- `Layer(w, h, paint, {k, ky, y})`: a strip drawn once that scrolls at its own pace (0 far … 1 the world; over 1, a
  layer in front of the camera). `gradient(w, h, colours)` for a sky.
- `Particles(max, dots(colours))`: a fixed pool drawn from a sheet of dots (each colour at four strengths and three
  sizes); `k` and `cap` follow the look. `emit(x, y, n, {c, v, a, sp, life, g, drag, s, up, bright})`.
- `Light(G)`: the dark with a hole cut for each light (`begin(fill, fresh)`, `cut(x, y, r, k)`, `end(g)`; a see-through
  fill lays over the last frame's dark, so it builds up where no light has been: `fresh` clears it first, so the dark is
  the fill's own), coloured glows
  added on top (`glowOf(r, rgb, a)` once, then `glowBegin`, `glow`, `glowEnd`: as many as the look allows), and
  bursts of light (`pulse(x, y, r, life, glow)`).
- `reflect(g, x, y, w, h, alpha, t)`: still water, mirroring what's over it in slices that sway.
- `font` (5×7, with ✕ ○ □ △ ◀ ▶ ♥ ★ in it): `text`, `shadow`, `center`, `width`, `wrap`, `colour(css)`;
  `Label(w)`: a line drawn once and copied after; `badge(g, G, b, x, y)`: a button in a little box.
- `Menu(G, {top, screens, choose, changed})`: title, pause, options and the rest in one look, worked with the
  controller (◀ ▶ change an option) and the keys; Back on the top screen is the box's (it leaves the game).
  `optionItems(extra)` are the engine's options.
- `Store(id, fresh)`: what's kept on the box (`data`, `save()`), never written in `#demo`.

### Checking a 2D game

`#fps` shows the frame rate, the look, the pace and the work a frame; `#tier=light|full|rich` and `#pace=60|30` hold
them; `#slow=N`, `#demo` and `#test` work as in Low3D. Cinder Knight on this Mac's headless Chrome (A18 Pro, no GPU):
0.27 ms of script a frame on the full look, 0.6 ms on rich; on the light look with `#slow=20` (each frame's work 20
times as long) 60 frames a second and none late. Micro Drifters, racing by itself: 0.16 ms on the light look,
0.25 ms on full and rich; with `#slow=20` it holds 60 on the light look, 3.6 ms of work a frame on a day track,
5.6 ms in the night's storm (lamps and headlights in the light map) and 8.2 ms in the blizzard. A track is painted
as it loads (about 0.1 s here; longer on a Pi 3, not yet timed on one, behind the fade).

## Checking a game

- In a browser: `python3 deploy/sofa-box/sofa-box-agent.py` with `SOFA_BOX_CONF=<tmp> SOFA_BOX_ICONS=0
  SOFA_BOX_UINPUT=0`, then `http://127.0.0.1:8091/box/games/<id>/#fps`.
- On a box: the graphics check at `http://127.0.0.1:8091/box/games/probe/` (in the box's browser) shows the GPU,
  the test, the rung a game would pick, and a scene drawn that way with its live frame rate. Tidewing's "This box"
  screen shows the same, plus what the governor has done. Its Games check plays every game in turn and shows a
  table of how each one ran.
- `tests/test_box_games.py` (`TheEngine`) checks that games stay offline and on the controller, that every page's
  script parses, and that each kind of box gets the right drawing. `TheEngine2D` checks Low2D's looks and paces,
  its governor, loop, tiles, particles and saves in node; `TheCinderKnight` plays every one of Cinder Knight's stages
  with the moves you'd have by then.

## Next, as games need it

In `Ray`: sloped floors. In Low2D: a 3D backdrop drawn by `GL` behind the pixels on the rich look (a tower that
turns as you climb), split screens for couch play, slopes. Each one comes with the game that first needs it.
