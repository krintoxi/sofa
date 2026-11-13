# Low3D: the Sofa Box game engine

`low3d.js` is the engine the box's own page games are built on. It has two ways to draw, for two kinds of game:

- **3D** (`GL`, with a 2D fallback, `Flat`), for open worlds. Tidewing (`tidewing/`), a racer over the sea, is
  drawn this way: light baked into the world's colours, a painted sky, mirror images in the water, everything
  written on the screen drawn in the canvas (see [What costs a Pi 3 time](#what-costs-a-pi-3-time)). WYRD
  (`wyrd/`), an action-RPG seen from above, is drawn this way too: floors of land with height in chunks, and bodies
  baked a pose at a time (see [Bodies, a pose at a time](#bodies-a-pose-at-a-time)).
- **Drawn by the processor** (`Ray`), for worlds on a grid: rooms, corridors, doors and floors at any height. It
  looks the same on every box, GPU or not, and the GPU only adds a glow. Ironmaw (`ironmaw/`), an old-style
  shooter, is drawn this way.

It's one file: offline, no libraries, no build step. A game is one page that loads `../pad.js` and then
`../low3d.js`, and adds its own content and rules.

For games in pixels (side-on or from above: platformers, brawlers, tactics, racers seen from the sky) there's a
second file on top of it, **Low2D** (`low2d.js`): see [Low2D: the 2D engine](#low2d-the-2d-engine). Cinder Knight
(`cinder-knight/`), Neon Brawler (`neon-brawler/`), Micro Drifters (`micro-drifters/`), Shadow Heist (`shadow-heist/`), Rune Tactics (`rune-tactics/`), Void Drifter (`void-drifter/`) and Cosmic Cascade (`cosmic-cascade/`) are built on it, and the
box's other small page games move onto it as each is made better.

The engine grows with each game. When a game needs something another game could use, the general part goes
here and the game keeps only what is its own. The maker (`maker/`) is the first page of a game maker on these engines: see
[The maker](#the-maker).

## What it promises every game

- **60 frames a second on a Raspberry Pi 3 (1 GB), a fuller look on a Pi 4 or 5.** At its first start on a box, the
  engine looks at the browser's GPU (`probe()`), runs a ~2 s test (`bench()`) and picks 3D or 2D and a quality rung
  (`plan()`). The result is kept per box and browser. While the game plays, the `Governor` keeps the frame rate
  steady: a rung down when frames run late (a smaller picture: pixels are given up before frames), straight to a
  30 fps rung when the game's own work fills the frame, a rung up when there's been room for a while (never back to
  one that ran late). A Pi keeps to its own kind's rungs whatever the test says: the light look for a Pi 3, the
  full one from a Pi 4.
- **A 2D fallback.** With no WebGL, or a software one (SwiftShader, llvmpipe), the same world is drawn by `Flat`:
  a mode-7 ground from a picture of the world seen from above, a sky with far hills, and sprites `bake()`d once
  from the game's own meshes. It plays the same; it just looks flatter.
- **The controller first.** `Input` reads pad.js (buttons by their place: A/✕ at the bottom) and the keyboard. The
  box also turns controller presses into keys; `Input` drops those echoes, so nothing happens twice. A remote's or
  the phone's keys still come through. Back on the game's top screen is left to the box (it leaves the game);
  Home is always the box's. Every controller is a player of its own, for games with more than one (see Several
  players).
- **Cheap to draw.** WebGL 1 and nothing more (a Pi 3 has no WebGL 2), drawn at the screen's size divided by a whole
  number and shown crisp: every pixel of the picture a square of the screen's. Flat-shaded meshes are built in code;
  a world's still things are merged into chunks with their light baked in. Nothing new is made while a game plays:
  matrices, particles, trails and dynamic meshes are made once and reused, and the frame's own code makes no
  garbage (see [No garbage](#no-garbage)).

## Which way to draw

- Use 3D for big open spaces, for things seen from far off, and for a sea, sky and hills. It's sharp where there's
  a GPU, and the 2D sea where there isn't.
- Use `Ray` for indoor places on a grid, where it's all walls, steps and doors (shooters, dungeon crawlers, mazes,
  tower defence on a grid). A Pi 3 draws it at 320×180 whether or not Chromium gives it the GPU, and every pixel is
  under the game's control.

## What costs a Pi 3 time

A Pi 3's GPU (VC4: OpenGL ES 2.0, so WebGL 1; it sorts triangles into tiles, then draws tile by tile) is not what
makes a page game slow there. Measured with `tools/games-bench.mjs` (below), Tidewing as Sofa Box OS 1.1.60 gave it
to a Pi 3 filled 1.1 screens of a 320×180 picture a frame: 4 megapixels a second at 60, where the browser itself has
to put 124 a second on a 1080p TV just to show the canvas. What cost the time, in the order it mattered:

1. **Anything the page lays over the canvas.** The race's numbers were page elements over the canvas: a layer the
   size of the screen (and the little map), laid over the game by the browser at the TV's full size every frame:
   2.1 megapixels a frame, where the game's own picture was 0.06 (the box's own reports say "drawing" is 82 to 95%
   of a slow moment on this Pi; a menu over the title was another such layer). Now everything written on a
   game is drawn in its canvas (`UI`, one draw call), a menu's blocks are each a small layer of their own with no
   panel behind them, the picture is dimmed behind a menu in the canvas (a 360-line quad, not a 1080-line one), and
   a menu that covers the picture stops the game drawing at all (`draw()` returns false; the governor doesn't judge
   those frames, or it would climb the ladder under a menu and find the top too much when play goes on).
2. **A 30 fps rung.** The Pi 3's rungs were 30 fps by design. Every rung but the lowest two now holds 60; what's
   given up first is pixels (360 lines, 270, 216), then frames at a good picture.
3. **Garbage.** 0.5 to 1.2 MB of script memory a second in a race (1.9 with two players), so the collector stopped
   the game 30 to 67 times a minute (2 to 6 ms each on a fast Mac; several times that on a Pi 3: the stutters). Now
   0.14 to 0.32 MB a second and 7 to 22 times a minute. See [No garbage](#no-garbage).
4. **The first use of a shader in the middle of a game** (a spray of dots, a weather effect): a pause while it's
   made. `GL.warm([...])` makes a game's programs while it loads; a program is asked one question about how it
   went, not three (each waits for the GPU's answer).
5. **Vertices.** A VC4 works on each vertex twice (to sort it into tiles, then to draw it). A still world's light is
   worked out once as it's built and kept in its colours (`Mesh.light`), so its shader only moves and fogs; high
   ground behind its cliffs is big triangles (`Land.inner`, `Land.mesh`'s `coarse`), and nothing is built under
   the water (`under`).

Before and after, Tidewing's Stormwall race (rain, a swell, cliffs: its heaviest water), 1.1.60 as it gave a Pi 3
(rung 1) against this engine as it gives one (rung 4). Measured on a Mac (Apple A18 Pro, Chrome 157 headless, its
own GPU) standing in for a Pi 3; none of it is a Pi's, and the GPU's own time isn't in it at all:

| | 1.1.60 | now |
|---|---|---|
| picture | 320×180, smoothed up | 640×360, each pixel 3 × 3 of the TV's |
| frames a second | 30 (by design) | 60 |
| between frames, ms: median / 95th / 99th / worst | 33.3 / 33.4 / 33.5 / 33.5 | 16.7 / 16.7 / 16.8 / 33.3 |
| the game's work a frame at ×20, ms: median / 95th / 99th | 6.1 / 16.2 / 24.2 | 4 / 8 / 14 |
| page layers over the picture, megapixels a frame | 2.14 | 0 |
| garbage, KB a second · collector pauses a minute | 1238 · 45 | 315 · 22 |
| draw calls · triangles a frame | 25 · 3.7k | 25 · 11.5k |
| fragments a frame, in screens of its own picture (megapixels a second at 60) | 1.17 (4) | 2.62 (36) |

The last two rows went up on purpose: the whole map is drawn, with its mirror image, at four times the pixels. The
browser's own job of showing the canvas on a 1080p TV is 124 megapixels a second at 60, so the bet is that 36 more
at a third of the lines costs a VC4 less than the 2.1-megapixel layer that's gone. Only the box can say (below).

What the picture is made of now, cheapest first: the sky is one painted picture on a dome (`Kit.sky`, `GL.dome`);
the water is one sheet with the world's picture on it, two nets of light drifting across each other, foam that
comes in to the shore, and it's see-through at a glancing angle, so that what's drawn under it shows: the sky and
the near world drawn again upside down (`GL.mirror`), mirror images as old consoles did their floors, with no second
picture to draw into. Every see-through thing (shadows, wakes, flames, sparks, rain) goes into one mesh drawn with
one call (`GL.fx`).

## The rungs (`LADDER`)

| | rung 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|---|
| **3D** lines drawn | 216 | 360 | 216 | 270 | 360 | 540 | 540 | 720 | 1080 |
| frames a second | 30 | 30 | 60 | 60 | 60 | 60 | 60 | 60 | 60 |
| look | light | light | light | light | light | light | full | full | full |
| mirror images | | near | | near | + sky | + sky | + sky | + sky | + sky |
| draw distance (m) | 420 | 560 | 420 | 480 | 560 | 640 | 760 | 900 | 1100 |
| **2D** height drawn | 112 | 135 | 160 | 160 | 200 | 240 | | | |


| | rung 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
|---|---|---|---|---|---|---|---|---|---|---|
| **Ray** lines drawn | 108 | 135 | 108 | 120 | 135 | 150 | 180 | 216 | 270 | 360 |
| frames a second | 30 | 30 | 60 | 60 | 60 | 60 | 60 | 60 | 60 | 60 |
| glow (WebGL) | | | | | | | | yes | yes | yes |

The 3D picture's height is the screen's own divided by a whole number, the nearest to the rung's (`wholeSize`):
on a 1080p TV 360 lines is a third, each pixel shown as 3 × 3 of the screen's, crisp; on a 720p TV it's a half.
Where it starts: a Pi 3's GPU (VC4) on 3D rung 4 (up to 5); a Pi 4's (V3D 4.x) on 6 (up to 7); a Pi 5's (V3D 7.x)
on 7; a desktop GPU on 6 and up, from the test. For a Pi the test can only say "less" (it can't see what the browser
spends putting the page together, which is most of a Pi 3's frame); the governor finds the rest while the game
plays, and goes down through the pixels (3, 2) before the frames (1: 360 lines at 30, then 0). Software or no WebGL
means 2D, its rung picked from the test's script time.
A `Ray` game starts from the script time alone (`planRay`): the processor does its drawing. Its ladder gives up
pixels before frames too, in small steps (its picture needn't go into the screen a whole number of times: see "A game
drawn by the processor"). A Pi 3 starts on rung 4 (240×135 at 60) and is held to rung 6 at most (320×180). A game
reads `E.rung` (`h`, `far`, `fps`, `look`, `mirror`, `detail`, `wakes`) and decides what each one means for it.

**Even frames.** A frame that stays on the screen the same time as the last looks smooth; one that stays one refresh
and then two looks worse than a steady 30. So the governor draws a rung's frames the same number of the screen's
refreshes apart, every one: the fewest refreshes that cover the rung's interval less a little slack (4 ms, or 45% of
a refresh on a fast screen), held once chosen, with the refresh learned from every one (`gov.ref`, seeded from the
test's `b.hz`). On a 60 Hz screen that's one refresh at 60 a second and two at 30; on a 120 Hz screen two, three
and four. Counted refreshes per frame drawn, a minute at each rate with the refresh times off by up to 0.3 ms:

| screen | 60 a second | 40 | 30 |
|---|---|---|---|
| 50 Hz | every refresh | (no 40 rung) | every 2 |
| 59.94, 60 Hz | every refresh | (no 40 rung) | every 2 |
| 75 Hz | every refresh | (no 40 rung) | every 3 |
| 120 Hz | every 2 | every 3 | every 4 |
| 144 Hz | every 2 | (no 40 rung) | every 5 |
| 240 Hz | every 4 | every 6 | every 8 |

(1.1.70 drew when the interval less a fixed 4 ms had passed: the same counts up to 120 Hz, but 144 Hz at 40 and every
rate at 240 Hz went three refreshes, four, three.)

**A rung at 40, only where it's even.** 40 a second is three refreshes of a 120 Hz screen (or six of 240), even;
on a 60 Hz screen it can't be. `withForty(lad, hz)` puts a rung at 40 (the best 30's picture, at 40) between a
ladder's 30s and 60s when the screen is a multiple of 40 (`fortyOn`: 80, 120, 160, 240 Hz), and the game's start is
the same picture as without it. A governor too busy for 60 goes to it first, then to 30. A ladder with a rate held
gets none. On every other screen the ladder is the very one it was, so what a box kept for its rungs stays good; on
a 40-capable screen the ladder's line (`ladderSig`) changes, and what was kept there is dropped once.

The game's own line for the report (`ran()`) counts a frame late when it came a refresh or more after its time: a
steady 30 isn't late (it counted every frame of a 30 as late before, anything over 25 ms).

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
  },                    // (and E.g3.warm([...]): the programs it will use, made now)
  update(dt) {          // the game's rules, 60 times a second
  },
  draw(now) {           // each frame drawn (return false: nothing drawn, the last picture stays)
    L3.begin(E, cam);   // GL: g3.dome(sky); g3.mirror(true) … the world again … g3.mirror(false); g3.water(…);
  } });                 //     chunks.draw(…); g3.moved(…); g3.fx(…). 2D: flat.sprite(…), then flat.flush()
E.start();
</script>
```

Copy Tidewing's `<style>` for the view, menus and loading screen (what's written on the game itself goes through
`E.ui`, in the canvas). In the address, `#fps` shows the frame rate
and rung, `#flat` or `#gl` forces a renderer, `#rung=N` holds a rung, and `#test` is for a game's own checks. For
checks: `#slow=N` makes each frame's work take N times as long (a slower processor), and `#threads=N` holds a Ray
game's helpers (0: the page draws it all). Chrome's own CPU slowdown isn't a fair stand-in for a Pi: slowed "10×" it
stretches a short frame's work about 3×, and it doesn't slow web workers at all.

## A game drawn by the processor

`L3.game({ kind: "ray", ... })`: the engine sizes `E.screen` (a picture, `E.screen.u32`) to the rung and calls
`resized(E)`. The game hands that buffer to a `Ray`, draws into it in `draw()`, and the engine shows it each frame.
That's WebGL with a glow on a real GPU, or a 2D canvas otherwise.

**The picture and the canvas are two sizes.** The picture (`E.screen.w` × `h`: the rung's) is what the processor
draws; the canvas (`E.screen.cw` × `ch`) is what it's shown on, and it's the screen's height divided by a whole
number, the nearest to `E.plan.show`: 360 lines on a Pi 3 (and wherever there's no GPU), 540 on a Pi 4, the screen's
own up to 1080 elsewhere. So the browser shows the canvas crisp for nothing, the GPU is asked for one look at the
picture for each of the canvas's pixels (a Pi 3: 0.23 megapixels a frame; the glow is a second shader, used only on
the rungs that have it), and the picture can be any size: the shader shows each of its pixels as a crisp block with
edges one canvas pixel soft, a whole number of times as big or not (`E.screen.crisp = false`: smooth all through).

**What's written on the game is written on the canvas**, not on the picture and not by the page: `E.ui` (see "What's
written on the picture"), built in the canvas's pixels (`E.ui.begin(E.screen.cw, E.screen.ch)`), drawn by the engine
after the picture. So a 240×135 picture has numbers as sharp as a 640×360 one's, and nothing of the page lies over
the game. A flash of colour over the view, frost at its edges, a menu's darkening are see-through blocks in the same
list. `draw()` that returns `false` draws and shows nothing: under a menu, draw the picture once, darkened, and leave it.

**What the player holds.** `tune()` (a game option) returns `{ lines, fps, glow }`: the picture's height, 30 or 60,
and 0 for no glow; 0 or left out is "as the box finds". A size or a rate held makes a ladder of the player's own
(`heldRay`): the size at 30 and at 60 (the governor may still give up the frames), or every size at the rate held.
After changing it, `E.setPicture()`. `E.held` says a ladder is the player's; nothing is remembered from it.

**Far off, a texture goes over to its smaller selves** (`ray.far`, 1; 0: never). Many of a texture's texels fall in
one pixel of a small picture, and which one is drawn changes with every step: floors and ceilings crawl. A texture's
smaller selves are itself in blocks of 2, 4, 8 and 16 texels of one colour (the palette's nearest to the block's own;
a block that's a quarter light or more stays a light), kept at the texture's own size, so the drawing is the same and
costs the same. They're picked once for each cell's floor, ceiling and wall, never for each pixel, and made the first
time a texture is seen far off. Marked faces and see-through walls are drawn as they are.

Ironmaw as a Pi 3 gets it, before and after this (the harness, an Apple A18 Pro standing in: **not a Pi's numbers**;
10 s a scene, garbage after 25 s of play; the collector's pauses are the page's own thread's):

| | 1.1.60 | now |
|---|---|---|
| picture | 320×180, on a 640×360 canvas | 240×135, on a 640×360 canvas |
| frames a second | 30 (by design) | 60 |
| between frames, ms: median / 95th / 99th / worst | 33.3 / 33.4 / 33.5 / 33.5 | 16.7 / 16.7 / 16.8 / 16.8 |
| the game's work a frame at ×20, ms: median / 95th / 99th (a level) | 4.1 / 12.1 / 14.2 | 2.1 / 4.1 / 4.1 |
| the same, the arena with 7 bots | 4.1 / 6.2 / 10 | 2.1 / 4.1 / 6.1 |
| page layers over the picture, megapixels a frame | 2.07 | 0 |
| looks at the picture for each pixel of the canvas | 5 | 1 |
| made on the script's heap, KB a second (a frame): a level · the arena | 1095 (37) · 2064 (69) | 274 (5) · 952 (16) |
| the page's collector, pauses a minute: a level · the arena | 37 · 82 | 22 · 67 |

The governor's ladder is what a Pi will really run on: a fight that fills the page's own frame (the rules for
thirty creatures awake at once) still drops it to 30 a second, as it should. Of five runs of the snow level, three
held 60 with nothing late; two had late frames (11 of 579, 18 of 522).

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
- `sky(sun)` draws only where nothing else was drawn. `light({sun, sunCol, amb, ground, fog, fogSun, top, horizon,
  near, far})` sets the lighting (`fogSun`: the air's colour towards the sun), and `texture(canvas, mip)` makes a
  texture.
- `can("waves")` and `can("sun")` say what this GPU can do (each program is made the first time it's used).

**3D, the second way** (made for a Pi 3; Tidewing's). A frame, in order:
- `dome(tex, turn)`: the sky, a picture from `Kit.sky` on a dome round the eye (`picture(canvas, {round: true})`).
- `mirror(true)`, then the dome, the near chunks and what moves again, then `mirror(false)`: their mirror images,
  under the water (a rung's `mirror`: 0 none, 1 the world and what moves, 2 the sky too).
- `water(sheet, tex, ripples, x0, z0, size, time, {glint, foam, see, seeMore, lines, foamK, grain, drift, rich})`:
  `tex` the world's picture from above, its alpha how near the shore (`picture(canvas, {alpha: canvas, mip: true})`),
  `ripples` from `picture(null, Kit.ripples(128))`. With `g3.seeUnder` set it's see-through at a glancing angle.
- `still(handle)`: a mesh with its light baked in (`Mesh.light`), or `chunks.draw(…)` for a world of them.
- `moved(handle, matrix, r, g, b, glow, rim)`: a thing that turns, lit as it turns, its edges catching the sky.
- `fx(handle, mesh, points)`: every see-through thing at once, premultiplied: each vertex's alpha is how much of it,
  its spare byte 127 for light added (flames, lamps) or 0 for paint laid over (shadows, foam, rain).
- `shine(r, g, b)` brightens the whole frame (lightning); `warm(names)` makes programs while the game loads.
- `bloom({from, to, pure, power, size, wide})`: what's bright in the picture drawn so far, spread as light over it
  (lamps, fires, what's lit by itself). The picture is copied, what's bright in it (by its strongest colour, so a pure
  pink glows as a white would; with `pure`, only colours that pure, so skin and pale stone in the sun don't) kept at a
  quarter of the size, blurred across and down, and added back: four draw calls, three
  small pictures and a copy of the canvas. It's for a GPU with room to spare: a game calls it on its upper rungs only
  (WYRD: the full look from 720 lines up), after its see-through things and before what's written on the picture, which
  the engine draws after `draw()` and so stays crisp. On a Pi 3's rungs it's never called and costs nothing.
- `hold(k)`: from now on what's lit is held under `k` of full brightness, and what's a light of its own is left as
  it is. Ask for it with `bloom` (its `from` at `k` or above) and only the lights glow: never skin, pale stone or
  leaves in full sun. `hold(0)`: not held (as it is when nobody asks).

**2D (`Flat`).** `size(w, h)`; `ground(canvas, x0, z0, size, outside)` (mip levels made, so far ground doesn't
shimmer); `air({top, horizon, fog, hill, hills, near, far})`; `draw(camera…)`; `project(x, y, z, out)`;
`sprite(s, x, y, z, scale, alpha)` and `poly(12 numbers, color)` queue things, and `flush()` draws them far to near.
`view(rect)` before `draw` puts the next frame in a part of the picture (a split screen's view; `null`: all of it).
`bake(mesh, {yaw, pitch, roll, ppu, light, glow})` draws a mesh once into a sprite, lit the same way as 3D.

**Building things.**
- `Mesh`: `at(x, y, z, yaw, sx, sy, sz, pitch, roll)` sets where the next part goes.
- Parts: `tri`, `quad`, `both` (seen from both sides), `box`, `stack` (rings up an axis: cylinders, cones, rocks,
  hulls), `ico` and `disc`. A face is lit flat and faces away from the "outside" point you give.
- `mesh.light(L, {shade(x, y, z), sky(x, y, z, ny)})` works its light out now and keeps it in its colours (the sun
  where `shade` says it reaches: shadows; the sky's share from `sky`: darker at the foot of things). What's built
  with `mesh.glow = 127` (or alpha 254) is its own light and stays. `mesh.s[0…2]` then `mesh.v(r, g, b, a, e)`
  writes a vertex without garbage, for meshes built again every frame.
- `Mesh.join(list)` merges meshes; each vertex is 20 bytes. `mesh.turn(yaw, pitch, roll, pivot…)` turns all
  that's built about a point. Build a body's parts separately, turn them, and join them: legs that walk, a body
  that leans, falls or lies down.
- Faces made with `m.alpha = 254` glow. `bake()` draws them unlit, and `Palette.sprite` keeps them full-bright
  (eyes, fire, screens).
- `Kit` has ready-made pieces: `palm`, `pine`, `rock`, `columns`, `hut`, `lighthouse`, `buoy`, `shadow`,
  `hills` and `skyline` (far hills for 3D and 2D), and `blob` (a soft 2D spot); `sky({top, mid, horizon, haze, sun,
  clouds, stars, ridges})` paints a sky for the dome (a big low sun cut by bars, clouds lit on their sunward side,
  far ridges, stars), `dome()` is its mesh, and `ripples(n)` the water's nets of light.
- `Chunks(size, cell)` holds a world's still things: `mesh(x, z, "base" | "detail" | "glow")` to build into,
  `upload(g3)`, then `draw(g3, x, z, far, detail)` each frame (culled, nearest first). `upload(g3, {light, shade,
  sky})` bakes the world's light in and puts each chunk's glowing things in with the rest: one draw call a chunk.
- `Land(size, n, base)` is ground with height: an n × n grid over the world, `fill((x, z) => height)`, then `at(x,
  z)` anywhere (to float on it, or bump into the shore) and `slope(x, z, out)`. `mesh(chunks, colour(h, steep),
  water, layer, {coarse: land.inner({above, drop}), under})` builds its triangles into chunks where it's near or
  above the water (with `coarse`, high ground with no drop near it as squares of two big triangles; `under`: how far
  below the water still counts); for the 2D renderer, `paint(ctx, k,
  colour, sun, water, shallow, depth)` paints it into the ground's picture (shaded by its slopes, shallows round it)
  and `banks(colour, water)` gives the quads that stand its edge up from the water. Tidewing's cliffs, gorge and
  volcano are made this way.

<a id="a-world-too-big-to-hold"></a>**A world too big to hold at once (`Stream`, `Mesh.stamp`, `Land.part`).** `Chunks` builds
a whole world as a game loads; `Stream` makes a world's still things a chunk at a time as the eye comes near and gives
them back as it leaves, so the memory used is the neighbourhood's, never the world's. WYRD's open world (780 m across,
676 chunks of 30 m) holds 25 of them: about 2 MB on the GPU in its thickest forest, where the whole would be 55.

```js
const stream = new L3.Stream({ cell: 30, near: 2,          // chunks 30 m a side; two each way from the eye's: a 5 × 5 block
  has: (ix, iz) => inTheWorld(ix, iz),                      // (none are made outside it)
  open(c) { c.data = whatStandsIn(c); },                    // a chunk comes into being: the game's own things for it
  close(c) { forget(c.data); },                             // …and goes
  build(c, base, glow, step) {                              // its meshes, a part a call (a step a frame): true when done
    if (step === 0) { land.part(base, land.cellOf(c.x0), land.cellOf(c.z0), land.cellOf(c.x1), land.cellOf(c.z1), colour); return false; }
    for (const t of c.data.trees) base.stamp(TREE, t.x, t.y, t.z, t.yaw, t.size, t.size, t.shade);
    return true; },
  light: { sun, sunCol, amb, ground }, shade, verts: 900 }); // Mesh.light's; verts: how many vertices are lit a frame
stream.fill(g3, x, z);          // everything near, now (as a world is entered, behind its fade)
stream.update(g3, x, z);        // every step of the game: one step of whatever is being made, and what's far behind given back
stream.draw(g3, x, z, far);     // what's in view, nearest first: one call a chunk
stream.remake(x, z);            // the chunk there is built again (a tree felled): its old mesh is drawn until the new one is ready
```

- A chunk is **one mesh with its light baked in**, built in the two meshes the stream keeps for all of them (`base`, and
  `glow` for what lights itself), so making one allocates nothing but the GPU's copy. Its making is spread over frames:
  the game's `build` a step a call, then its light some vertices a frame, then the upload. No frame carries a whole chunk.
- **`Mesh.stamp(src, x, y, z, yaw, size, sizeY, shade)`** is the engine's instancing: a thing built once about its own
  middle is copied into a mesh wherever one stands, turned and sized, with no vertex worked out twice. What's stamped
  into a chunk is drawn with the chunk's one call. (A Pi 3's GPU has no instanced drawing, and where there is one a
  draw call for each kind of thing would still cost more than a chunk's one.) `Mesh.reset()` empties a mesh and keeps
  its memory; `Mesh.add(src, glowing)` appends another's vertices as they are.
- **`Land.part(mesh, i0, j0, i1, j1, colour)`** builds one part of a land's ground into a mesh (`cellOf(x)` is the cell a
  place is in). The heights of a big world are cheap to keep whole (a number every 2.5 m of WYRD's is 0.4 MB); it's the
  triangles that are made a chunk at a time.
- `unload()` gives the GPU's side back and keeps the chunks open (the picture is being made anew: another renderer, a
  lost context); `free()` closes them all. With nothing to draw into (`Flat`, or a check that only steps the game) give
  it a stand-in `{ upload: () => null, free() {} }` and a `build` that returns true: the chunks still open and close.
- Walking 400 m across a world in the tests (`TheBigWorld`): never more than 36 chunks held, one step of making a frame,
  the ground under the walker always there, every chunk opened closed again.

**Models made elsewhere.** `tools/low3d-models.py` (Python alone: no Blender) turns models in glTF, in flat colours,
into data for a page: each model's colours, its box, and its vertices and triangles as bytes, with fewer triangles where
asked (edges collapsed where that changes the shape least: quadric error, the edges between colours and open edges
held). WYRD's props, weapons and creatures come in this way; the page puts them into meshes with `Mesh.tri`, so they
light, bake and join like anything built in code.

<a id="bodies-a-pose-at-a-time"></a>**Bodies, a pose at a time (`Rig`).** Low3D has no skinning: a body is parts on a
skeleton, each pose's joints worked out once and every part built where its joint puts it, the whole pose baked into one
mesh. A walk is four meshes, a swing three; the frame picks the mesh for the moment and draws it with `moved()`: one
draw call a body, with no work a frame but its matrix. WYRD's people, the risen dead and the powers are made this way.

```js
const rig = new L3.Rig();                 // Rig.HUMAN: hips, chest, head, each arm in three, each leg in three (15)
const POSES = { walk0: { y: -0.03, chest: [0.12, 0, 0.12], legR: [0.55, 0, 0], armL: [0.55, 0.1, 0] /* … */ } };
function build(m, look, pose) {           // one pose's body into m, standing on y = 0 and facing +z
  rig.pose(POSES[pose], 1, look.bulk);    // each joint: [swing forward, roll out, turn]; y lowers the hips, lean tips the body
  rig.at(m, "chest"); m.box(0, 0, 0, 0.36, 0.5, 0.22, look.cloth);              // a part where its joint is
  rig.attach(m, "handR", 0, -0.09, 0, 0, Math.PI / 2, 0, 1); /* the sword */    // a thing held: placed in the hand's frame
  m.at(0, 0, 0);
}
```

- `new Rig(joints)`: `[name, parent, x, y, z, kind]` each, the parent's number (-1 for the root). A joint of kind
  `"spine"` stands up from its parent and leans forward as it swings; `"arm"` and `"leg"` are set out from the middle by a
  broad body (`bulk`, and its square root for legs); the rest hang down and rise as they swing forward. A name ending in
  R is the right side, its roll and turn mirrored, so a pose reads the same on both sides.
- `pose(P, size, bulk)` works the joints out; `at(m, j)` builds what comes next in `m` where joint `j` is (its name or
  number); `attach(m, j, x, y, z, yaw, pitch, roll, size)` places a thing in that joint's frame; `where(j, out)` is the
  joint's place (for a hit, a spark from a hand, the maker's marker).
- `mirror(P)` is the same pose the other way round (WYRD's `walk2` is `walk0` mirrored), and `Rig.clips(poses)` groups
  poses by name: `walk0` … `walk3` is the clip `walk`.

The maths is WYRD's, moved into the engine unchanged: its 25 poses of 21 looks, at two sizes, bake to the same bytes as
they did before (1,050 meshes compared).

<a id="the-maker"></a>**The maker** (`maker/`, not on Home). The first page of our game maker, for a computer with a
mouse: from a checkout, `python3 -m http.server -d deploy/sofa-box/games 8770` and then
`http://127.0.0.1:8770/maker/`; on a box, `http://127.0.0.1:8091/box/games/maker/` in its own browser (the box serves
its pages to itself only, so a computer on its network can't open it there yet). It reads a game's own page and what's
marked there for it, draws the game's bodies as the game bakes them, and turns their poses joint by joint (mirror,
revert, clips played at a rate, all the bodies in a line-up, the picture a Pi 3 draws, the draw calls and triangles
against a Pi 3's frame). What's changed is copied out as the game writes it, a pose or the whole block; nothing is
written back to the page yet. A game marks the parts the maker reads, in this order, each using only `L3` and the
blocks before it:

```js
/* maker: models */ const MODELS = { … }; /* maker: end */          // models packed by tools/low3d-models.py
/* maker: poses */ const POSES = { … }; /* maker: end */            // each pose on a line of its own: name: { … },
/* maker: bodies rig=RIG build=buildBody looks=FOLK,STYLES */
const RIG = new L3.Rig(); …  function buildBody(mesh, look, pose, size) { … }
/* maker: end */
```

`rig`, `build` and `looks` name what's in the bodies block: the rig, the function that builds one pose of a body, and
the tables of looks to show (each look a body's colours and parts, as `build` takes them). The page is
`maker/index.html#<game>` (`#wyrd` first).

**Moving things.**
- `Path(points, {closed, step})` is a smooth line to race, ride or patrol along. It has `at(s)`, `side(s, off)`,
  `near(x, z, hint)`, `delta(a, b)`, `curve` (how sharply it bends ahead) and `knots` (where the points fall).
- `Trail` makes wakes, light trails and tyre marks: `step(dt, x, z, strength)`, then `ribbon(mesh, …)` or
  `wake(mesh, …)` (two arms that spread, the churn between them) for 3D, or `spots(flat, …)` for 2D.
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
- `Ray` also: `dots(list, idx, size, full)` (a list of `{x, y, z}` specks at once: no number is handed over for each),
  `far` (how soon textures go over to their smaller selves).
- `Screen(canvas2d, canvasGL, useGL)` shows the picture: `size(w, h, cw, ch)`, `present(glow, vig)`, `show(ui)`;
  `planRay(probe, bench)` picks a `Ray` game's starting rung, its canvas (`show`) and its helpers; `heldRay(lines,
  fps)` is the ladder for a size or a rate held.

**The controller (`pad.js`).** Beyond the buttons and the left stick: `SofaPad.stick2()` (the right stick),
`SofaPad.trigger("rt")` (how far a trigger is pulled), `SofaPad.button("left")` (the D-pad itself, not the stick),
and `SofaPad.rumble(strong, weak, ms)`. These follow whichever controller was used last; each player's own are
`SofaPad.player(n)`'s (Several players, below).

**What's written on the picture (`UI`, as `E.ui`).** A list of quads in the picture's own pixels, drawn after the
game's `draw()` with one call (through the 2D context where there's no WebGL): `begin(w, h)`, then `rect`, `frame`,
`line`, `disc`, `arrow`, `quad` and `text(s, x, y, k, colour, alpha, align, shade)` (the 5×7 pixel font Low2D
writes with, each of its pixels `k` of the picture's, a whole number: crisp at any size), `end()`. `hold()` keeps
what's in the list so far (a map's lines, a panel) and `rewind()` goes back to there, so only what changes is built
again; build it when it changes (ten times a second is plenty), not every frame.

**A moment worth marking (`Confetti`, `Banners`).** Both write into `E.ui`, so they are part of the picture's one
call for what's written on it, and a frame of either makes no garbage.
- `new Confetti(n)`: n pieces of paper at most, in the picture's own pixels. `burst(x, y, count, power, colours, size,
  spread)` throws them up from a point in a fan, `rain(w, count, colours, size)` lets them fall from above the picture;
  `step(dt, gravity)` (it returns how many are still in the air), then `draw(ui)`. A piece turns as it falls and
  tumbles, its other side a darker shade.
- `new Banners({gap, on})`: lines that come in one after another, stack down from the top, stay and go. `push({title,
  text, col, hold})`, `step(dt)`, `draw(ui, w, h, k, top)`, `busy`; `on(i, banner)` as each lands (its sound). Big and
  dark-backed on purpose: it has to read from a sofa. WYRD's level-75 moment is these two, a fanfare, and lights in its
  one mesh of see-through things: no draw call more than a quiet frame.
- `new Emblem(parts, hot)`: one flat mark (a skill's, a clan's) kept as three- and four-cornered pieces on a square
  from -1 to 1, so the same shape goes on a body's cloth (`onto(mesh, place, col, hi, ox, oy, oz)`), on the HUD
  (`draw(ui, x, y, r, col, a)`) and in a menu (`svg(col)`), sharp at any size. A banner takes one (`emblem`), and so
  does a slot of `Slots` (`show()` → `emblem`).

**The rest.**
- `game({...})` sets up the screen (16:9, as big as fits, `--u` a hundredth of its height for CSS), the tuning,
  the loop (fixed 60 steps a second, `wholeSteps`: a frame whose own length is a whole number of steps to within 1.5% takes exactly that many, so a screen that's 60 Hz or nearly (59.94, 59.79, 60.32) runs on its own beat with the same steps every frame (what frames off the beat left carried, it lets go of a twentieth of a step at a time, so a clock that wobbles doesn't build it up into a skip); any other frame's time is carried, never dropped, so a 50, 72, 75 or 144 Hz screen runs at real time, and there a frame that comes within a quarter of a step of a whole number of steps after the last takes exactly that
  many, never none and then two; `E.alpha` says how far into the next step a frame is), `#fps`, and the switch to
  2D if the GPU goes away. It returns `E`, with `mode`, `g3`, `flat`, `ui`, `rung`, `gov`, `rows()`, `retest()`,
  `setPicture()`, `ran()`: how it ran, in one line, and `tell()`: says it to the console (on the box only, once in
  five minutes at most; the engine also says it when the game is left), which is what "Send a report" keeps of a
  page. Call `tell()` at the end of a race or a level.
- `Input` and `Menu`: screens of `.item` elements. A screen can be a list, a `grid` of columns, a `row`, or
  `options` (◀ ▶ to change values).
- `Slots({grid, worn, size, act, items, places, wearing, show})`: what's carried and what's worn, as the elements of a
  `Menu` screen: a grid of slots (each an `.item`, so the arrows, A and B, a remote's keys and a tap all work it as they
  work any menu), and the places a thing is worn beside it. The game says what a slot shows (`show(item)` → title, kind,
  colour, a mark) and its menu's `choose()` what choosing one does; `render()` after anything changes. WYRD's bag.
- `Synth`: `play(name)` plays effects, `play(name, pan, gain)` from a place (left -1 to right 1, and how loud), and
  `define(name, fn)` adds your own. `song({seed, root, tempo, calm})`
  writes a tune from a seed and plays it. `drone("saw" | "noise")` is a sound that goes on (an engine, the wind),
  changed with `set(pitch, brightness, volume)`.
- `U` has small tools: `clamp`, `lerp`, `wrap`, `rand(seed)`, colors (`hex`, `shade`, `mix`), `time` and `ord`.

## No garbage

Script memory made while a game plays has to be cleared, and the collector stops the game to do it: a millisecond or
two on a desktop, a dropped frame or several on a Pi 3. `tools/games-bench.mjs --alloc` names the functions that
make it. What it found in Chrome 157 (V8), each measured in a loop of its own on this Mac:

- `Math.hypot(a, b)` makes about 31 bytes a call; `Math.sqrt(a * a + b * b)` makes none.
- `for (const x of list)` in a hot function made about 10 bytes a call, and a closure (`list.forEach(…)`,
  `list.reduce(…)`, an arrow function made inside the frame) is an object each time: Tidewing's `stepRacer` went from
  209 KB a second to 13 with loops by number and no closures.
- An array or object literal (`[w, h]`, `{x, y}`) is an allocation: return into something made once.
- A regular expression written in a loop (`/[quy]/.test(c)`) is a new one each time round: compare the letters.
- A message to a worker copies its typed arrays as it's sent, so the same ones can go again next frame; a `subarray`
  is a new thing each time (540 a frame, copying a picture's strips row by row): copy a pixel at a time.
- A call into a big function (one V8 won't inline) with fractional numbers as arguments makes each number anew on
  the heap: a mesh built again every frame through `put(x, y, z, …)` was 2.4 MB a second. Write the place into a
  typed array (`m.s`) and call with whole numbers only (`m.v(r, g, b, a, e)`): stores into typed arrays make nothing.
- Fields that hold fractions, typed arrays, `Math.sin`, `exp`, `atan2`, `sqrt`, `max`, `min`: none.
- For its first 20 to 30 seconds a game makes several times more (V8 is still compiling its hot code, and what
  isn't compiled yet makes every number anew): the harness waits 25 s before it measures.

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
  or the key's name), `options(o)`, `rows()`, `ran()` (how it ran, in one line) and `tell()` (says that line for the
  box's report: the engine does it every five minutes of play and when the game is left, so a game needn't).
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

Every game on Low2D says how it ran, as the 3D games do: `cinder-knight ran: 2D light rung 2 of 4 480x270, 60 fps
over 212 s (wanted 60, lowest second 57), 3 of 12720 frames late, worst 41 ms, work 4.2 ms (most 19); …`. On the box
a page's console errors are what "Send a report" keeps of a page, and that line is the only measure there is of a
real Pi: every five minutes of play and when the game is left, never off the box, never the demo. Gloamwell, which
has an engine of its own, says the same (`gloamwell ran: FX 1 480x270, …`).

All of them as a stand-in Pi 3 (`tools/games-bench.mjs`, an Apple A18 Pro: **not a Pi's numbers**; each game playing
itself for 10 s, its work made 20 times as long). None lays anything of the page over its picture.

| | frames a second | late frames | work a frame at ×20, ms: median / 95th | its picture filled a frame, in screens (calls) |
|---|---|---|---|---|
| Cinder Knight | 60 | 0 of 602 | 4.1 / 8.1 | 5.26 (49) |
| Cosmic Cascade | 59 | 1 of 591 | 2.2 / 6.2 | 3.45 (111) |
| Micro Drifters | 60 | 1 of 601 | 2.2 / 6.2 | 2.03 (29) |
| Neon Brawler | 59.3 | 2 of 595 | 4.1 / 6.2 | 3.9 (158) |
| Rune Tactics | 60 | 0 of 600 | 4 / 8 | 1.59 (107) |
| Shadow Heist | 58.1 | 3 of 581 | 4.1 / 10 | 3.38 (67) |
| Void Drifter | 59.9 | 0 of 600 | 0.1 / 2.2 | 4 (4) |
| Neon Dodge (no engine) | 59.9 | 0 of 602 | 0.3 / 0.8 | 2.22 (229) |
| Sky Hop (no engine) | 60 | 0 of 601 | 0.2 / 0.6 | 1.56 (127) |
| Gloamwell (its own) | 4 to 20 | nearly all | 38 to 80 / 132 to 1245 | 2.26 (124) |

Gloamwell's row is not like the others, and it doesn't mean Gloamwell is slow. `#slow` in Low2D and Low3D waits out
the script's time; Gloamwell's own `#slow` first makes the browser finish drawing the frame (it reads a pixel back)
and waits that out 20 times over too. Drawing isn't the script's work, a Mac doesn't draw as a Pi does, and the
figure swings from run to run. Without `#slow` its script is 0.5 ms a frame here (1 ms at the 95th), and it fills
fewer screens of its picture than five of the games above it. What the stand-in can't price for any of them is the
drawing itself (the last column): that is for the Pi's own line to say.

`#fps` shows the frame rate, the look, the pace and the work a frame; `#tier=light|full|rich` and `#pace=60|30` hold
them; `#slow=N`, `#demo` and `#test` work as in Low3D. Cinder Knight on this Mac's headless Chrome (A18 Pro, no GPU):
0.27 ms of script a frame on the full look, 0.6 ms on rich; on the light look with `#slow=20` (each frame's work 20
times as long) 60 frames a second and none late. Micro Drifters, racing by itself: 0.16 ms on the light look,
0.25 ms on full and rich; with `#slow=20` it holds 60 on the light look, 3.6 ms of work a frame on a day track,
5.6 ms in the night's storm (lamps and headlights in the light map) and 8.2 ms in the blizzard. A track is painted
as it loads (about 0.1 s here; longer on a Pi 3, not yet timed on one, behind the fade).
Shadow Heist: about 0.45 ms of work a frame here; with `#slow=20` a heist holds the light look at 60 (5.6 ms a
frame). Its light map is worked out a tile at a time when a lamp, a door or smoke changes it, and scaled up once
then, so a frame only copies it (scaling it each frame cost more than the rest of the drawing).
Rune Tactics: 0.15 ms a frame on the light look, 0.27 ms on full; with `#slow=20` it holds the light look at 60
(4.1 ms a frame). Its field is drawn once and again only when the ground changes (forest burnt, water frozen).
Void Drifter: 0.1 to 0.5 ms a frame here; with `#slow=20` it holds the light look at 60 (4 ms a frame, 5.3 ms in
the Dreadnought's fight). Its ships are drawn at 32 angles once, from their outlines, a pixel at a time.
Cosmic Cascade: about 0.35 ms a frame; with `#slow=20` it holds the light look at 60 (4.4 ms a frame). Its board's
rules are one block of plain functions (`resolve`, `drop`) that the puzzle boards were found with: a search, run
once outside the game, kept the boards that have a way to clear them, and the game's checks replay each one.

## Checking a game

- **`node tools/games-bench.mjs`** (from the repository; node and Chrome, nothing else) opens each scene of each
  game in a Chrome of its own, WebGL 1 only, at the box's screen size (1920×1080, pages at ×2), three times: timed
  as the stand-in box (the game's work made 20 times as long with `#slow=20`, about a Pi 3 B+ against a fast
  desktop core: frames a second, the time between frames at the median, 95th and 99th percentile and the worst,
  the work a frame, draw calls, triangles, vertices, uploads, 2D pixels filled); at the computer's own speed with
  nothing counted (garbage a second, the collector's pauses, the layers lying over the game's picture and their
  pixels; `--alloc` and `--profile` name the functions); and with every fragment shader's output swapped for a
  counter (fragments shaded a frame, opaque and see-through). `--games`, `--scenes`, `--secs`, `--hash rung=4`,
  `--shots DIR`, `--json FILE`, `--root OTHER/deploy/sofa-box` (another checkout: before and after), `--box
  pi3|pi4|pc`. It cannot be a Pi: the GPU is the computer's own, so GPU time isn't measured, only what costs a VC4
  time. Every number it prints is that computer's.
- **On a real box** the measure is the games check (below), and what a game says when it's left: both now go to the
  console as errors, which is what the box keeps of a page for "Send a report" (lines starting `Graphics check:`,
  `Games check:` and `<game> ran:`).
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

In Low3D's second way: a full look that earns the name (the water bending what's under it is all `rich` adds so
far; a second picture for the mirror images, ripples on them, detail textures on the land), and draws between
steps (`E.alpha`) for screens that aren't 60 Hz. In `Ray`: sloped floors; and its picture kept a column at a time
(a wall's column is then written in order, and a helper's strip comes back as one copy: putting the strips into the
picture a pixel at a time is the most the page itself spends on a frame now). In Low2D: a 3D backdrop drawn by `GL` behind the pixels on the rich look (a tower that
turns as you climb), split screens for couch play, slopes. Each one comes with the game that first needs it.
In the maker: changes written back into the game's page, the kit of meshes built in code, and the same scene shown as a
Pi 3, a Pi 4, a desktop and a box with no GPU draw it, side by side.
