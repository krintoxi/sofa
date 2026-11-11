#!/usr/bin/env node
/* Frame times for Sofa Box's page games (deploy/sofa-box/games), measured the same way every time.

     node tools/games-bench.mjs                              # Tidewing and Ironmaw, as a Raspberry Pi 3 would be given them
     node tools/games-bench.mjs --games tidewing --secs 15 --shots /tmp/shots --json /tmp/tidewing.json
     node tools/games-bench.mjs --box pc --games cinder-knight
     node tools/games-bench.mjs --root ../sofa-main/deploy/sofa-box     # another checkout: before and after

   It serves the games from this checkout, starts a Chrome of its own (headless, its own profile, closed at the end),
   opens each scene of each game through DevTools and measures, per scene:

     (Three passes a scene: timed as the stand-in box; then at this computer's own speed with nothing counted, for
     memory, layers and profiles; then, with WebGL, with every fragment counted.)
     frames     frames drawn a second; the time between frames drawn (median, 95th, 99th percentile, worst); frames more
                than 25 ms apart ("late")
     work       the page's own work each frame drawn: everything its requestAnimationFrame callbacks did (ms)
     draws      WebGL draw calls, triangles and vertices a frame; bytes of vertex data and pixels of texture sent a
                frame; 2D canvas pixels filled a frame (drawImage, fillRect, putImageData: what lands on the canvas, no transform reckoned)
     fill       WebGL fragments shaded a frame, opaque and see-through, in screens of the game's own picture (a second
                run of the scene with every fragment shader's output swapped for a counter, added up and read back)
     memory     script memory made a second (what the garbage collector will have to clear) and its pauses (the page's
                own thread's; its workers' are counted apart: each has a collector of its own), once the
                game has run a while (--warm N seconds, 25: until then the script engine itself makes garbage, still
                compiling the game's code; Tidewing's rate falls for some 25 s on a fast Mac before it settles)
     layers     the page's composited layers: how many draw, and their pixels (what the browser puts together each frame
                at the screen's size: on a Pi 3 the largest cost there is)

   The box it stands in for (--box):
     pi3   the screen of the owner's box (1920x1080, pages at x2), WebGL 1 only, the GPU named as a Pi 3's
           (VC4 V3D 2.1) with the short list of extensions Mesa's vc4 has, 4 cores, and the game's own work made 20
           times as long (the engines' #slow=20: about a Pi 3 B+ against this Mac's fast cores for tight JavaScript).
     pi4   the same screen, the GPU named as a Pi 4's (V3D 4.2), work 8 times as long.
     pc    this computer as it is.
   --cpu N adds Chrome's own CPU throttling (Emulation.setCPUThrottlingRate), which slows the page's main thread only
   and is not linear for short frames; --slow N sets the engines' #slow.

   --alloc adds where the script memory is made (the functions that make the most, and the sum, from Chrome's sampling
   heap profiler: things on the script's own heap. The memory line's figure is the browser's own count, which seems to take
   in buffers on their way to and from a worker: a game that hands a picture to helpers 30 times a second on a 60 Hz
   screen showed that picture's size every frame there, in every scene, where the sampler found a sixth of it); --profile adds where the page's time goes (the functions with the most time of their own).

   What it cannot do: be a Pi. The GPU here is this computer's (or SwiftShader with --gpu swiftshader), so GPU time is
   not measured at all: what's counted instead is what costs a VC4 time (draw calls, vertices, fragments, uploads,
   layers). Every number it prints is from this computer; the box's own are from its games check (probe/#games). */
import http from "node:http";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const opt = (name, dflt) => { const i = args.indexOf("--" + name); return i < 0 ? dflt : args[i + 1] && !args[i + 1].startsWith("--") ? args[i + 1] : true; };
if (opt("help", false)) { console.log(fs.readFileSync(fileURLToPath(import.meta.url), "utf8").split("*/")[0].replace(/^#!.*\n\/\* ?/, "")); process.exit(0); }
const ROOT = path.resolve(opt("root", path.join(HERE, "..", "deploy", "sofa-box")));
const BOX = String(opt("box", "pi3")), SECS = +opt("secs", 10), CPU = +opt("cpu", 1);
const SLOW = +opt("slow", BOX === "pi3" ? 20 : BOX === "pi4" ? 8 : 1);
const GPU = String(opt("gpu", process.platform === "darwin" ? "metal" : "default"));
const GAMES = String(opt("games", "tidewing,ironmaw")).split(",").filter(Boolean);
const ONLY = opt("scenes", "") ? String(opt("scenes", "")).split(",") : null;
const SHOTS = opt("shots", ""), JSON_OUT = opt("json", ""), FILL = !args.includes("--no-fill"), HASH = String(opt("hash", ""));
const WARM = +opt("warm", 25);
const HEADED = args.includes("--headed"), VERBOSE = args.includes("--verbose"), ALLOC = args.includes("--alloc"), PROFILE = args.includes("--profile");

// ---------------------------------------------------------------- the scenes: how to get each game into its heavy moments
// hash: what's added to the address; enter: run once the game is ready; until: wait for this to be true; settle: then
// this long (ms) before measuring. A game with no entry here is measured playing itself (#demo).
const tw = (ci, two) => ({ hash: "test", settle: 2500,
  enter: `TW.two = ${!!two}; TW.startRace(${ci}); for (const p of TW.players) { p.racer.ai = true; p.racer.pace = 1; } if (TW.go) TW.go();`,
  until: `TW.state === "race" && TW.raceT > 1` });
const im = lv => ({ hash: "demo&test", settle: 4000, enter: `IM.startLevel(${lv}, false);`, until: `IM.state === "play"` });
const SCENES = {
  tidewing: [
    { name: "title (round the course)", hash: "test", settle: 2500 },
    Object.assign({ name: "race: Wren Shallows" }, tw(0)),
    Object.assign({ name: "race: Fogbound Skerries" }, tw(4)),
    Object.assign({ name: "race: Stormwall (rain, swell, cliffs)" }, tw(6)),
    Object.assign({ name: "race: Ember Atoll (volcano, ash)" }, tw(10)),
    Object.assign({ name: "two players: Stormwall" }, tw(6, true))
  ],
  ironmaw: [
    { name: "it plays itself (#demo)", hash: "demo", settle: 6000 },
    Object.assign({ name: "level 3: Cooling Towers (outdoors)" }, im(2)),
    Object.assign({ name: "level 6: Glacier Mine (snow)" }, im(5)),
    { name: "arena: Crucible, 7 bots", hash: "test", settle: 4000, until: `IM.state === "play"`,
      enter: `Object.assign(IM.save().opts, { mode: 0, map: 0, bots: 7 }); if (IM.save().arena) Object.assign(IM.save().arena, { mode: 0, map: 0, bots: 7 }); IM.startArena();` }
  ]
};
const sceneList = g => (SCENES[g] || [{ name: "it plays itself (#demo)", hash: "demo", settle: 5000 }]).filter(s => !ONLY || ONLY.some(o => s.name.toLowerCase().includes(o.toLowerCase())));

// ---------------------------------------------------------------- the box it stands in for
const BOXES = {
  pi3: { renderer: "ANGLE (Broadcom, VC4 V3D 2.1, OpenGL ES 2.0 Mesa 26.2.6-1~bpo13+0~rpt1)", vendor: "Google Inc. (Broadcom)", webgl2: false, maxTex: 2048, cores: 4, memory: 1,
    ext: ["OES_vertex_array_object", "OES_standard_derivatives", "OES_element_index_uint", "WEBGL_lose_context", "WEBGL_debug_renderer_info"],
    ua: "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36" },
  pi4: { renderer: "ANGLE (Broadcom, V3D 4.2.14.0, OpenGL ES 3.1 Mesa 26.2.6-1~bpo13+0~rpt1)", vendor: "Google Inc. (Broadcom)", webgl2: true, maxTex: 4096, cores: 4, memory: 4, ext: null,
    ua: "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36" },
  pc: null
};
if (!(BOX in BOXES)) { console.error("--box: pi3, pi4 or pc"); process.exit(2); }

// ---------------------------------------------------------------- what's put into every page before its own scripts
// (counters on requestAnimationFrame, WebGL and the 2D canvas; the stand-in box; in "fill" mode, the fragment counter)
function hook(BOXJSON, MODE) {
  const BOX = BOXJSON, K = 8;
  const B = window.__bench = { mode: MODE, on: false, fill: [], gl: null };
  let c = null;
  const fresh = () => ({ work: 0, draws: 0, tris: 0, verts: 0, points: 0, buf: 0, tex: 0, uni: 0, prog: 0, px2d: 0, off2d: 0, calls2d: 0, clears: 0, draws0: 0 });
  c = fresh();
  if (BOX) {
    try { Object.defineProperty(Navigator.prototype, "hardwareConcurrency", { get: () => BOX.cores, configurable: true }); } catch (e) { /* as it is */ }
    try { Object.defineProperty(Navigator.prototype, "deviceMemory", { get: () => BOX.memory, configurable: true }); } catch (e) { /* as it is */ }
  }
  // ---- requestAnimationFrame: one record a tick (a tick: every callback the browser ran for one frame). Nothing is
  // made a frame here (the records go into one array made at the start, each of the page's callbacks keeps one wrapper):
  // the page's own garbage is what's measured.
  const raf = window.requestAnimationFrame.bind(window), caf = window.cancelAnimationFrame.bind(window);
  const REC = 16, MAXT = 30000, T = new Float64Array(REC * MAXT); let nT = 0;
  Object.defineProperty(B, "ticks", { get() { const out = []; for (let i = 0; i < nT; i++) out.push(Array.from(T.subarray(i * REC, i * REC + REC))); return out; } });
  B.start = function () { nT = 0; this.fill.length = 0; this.on = true; this.t0 = performance.now(); }; B.stop = function () { this.on = false; this.t1 = performance.now(); };
  let tickAt = -1, endId = 0, inTick = false;
  const mem = () => (performance.memory ? performance.memory.usedJSHeapSize : 0);
  function endTick() {                                  // after the page's last callback of the frame (asked for after each of them, so it runs last)
    inTick = false;
    if (B.on && tickAt >= 0 && nT < MAXT) { const o = nT++ * REC; T[o] = tickAt; T[o + 1] = c.work; T[o + 2] = c.draws; T[o + 3] = c.tris; T[o + 4] = c.verts; T[o + 5] = c.buf; T[o + 6] = c.tex; T[o + 7] = c.px2d; T[o + 8] = c.off2d; T[o + 9] = mem(); T[o + 10] = c.points; T[o + 11] = c.uni; T[o + 12] = c.calls2d; T[o + 13] = c.clears; T[o + 14] = c.prog; }
    if (B.mode === "fill" && B.on && B.gl && c.draws) sample();
    c.work = c.draws = c.tris = c.verts = c.points = c.buf = c.tex = c.uni = c.prog = c.px2d = c.off2d = c.calls2d = c.clears = c.draws0 = 0;
  }
  const wrappers = new WeakMap();
  window.requestAnimationFrame = function (cb) {
    let w = wrappers.get(cb);
    if (!w) { w = function (ts) { if (!inTick) { inTick = true; endId = 0; } tickAt = ts; const t0 = performance.now(); try { cb(ts); } finally { c.work += performance.now() - t0; } }; wrappers.set(cb, w); }   // (endId: now the next frame's)
    const id = raf(w);
    if (endId) caf(endId); endId = raf(endTick);
    return id;
  };
  // ---- the 2D canvas: pixels filled (the picture's own, and canvases kept off screen)
  const C2 = window.CanvasRenderingContext2D && CanvasRenderingContext2D.prototype;
  if (C2 && B.mode === "time") {                        // (the counting itself makes a little garbage: only in the pass that times)
    // (what lands on the canvas: a picture of the whole map drawn at an offset fills one screen, not six. A transform
    // isn't taken into account.)
    const area = (ctx, x, y, w, h) => {
      const cv = ctx.canvas, cw = cv ? cv.width : 0, ch = cv ? cv.height : 0;
      const x0 = Math.max(0, Math.min(x, x + w)), x1 = Math.min(cw, Math.max(x, x + w)), y0 = Math.max(0, Math.min(y, y + h)), y1 = Math.min(ch, Math.max(y, y + h));
      const a = x1 > x0 && y1 > y0 ? (x1 - x0) * (y1 - y0) : 0;
      if (cv && cv.isConnected) c.px2d += a; else c.off2d += a; c.calls2d++;
    };
    const wrap = (name, fn) => { const o = C2[name]; C2[name] = function () { fn(this, arguments); return o.apply(this, arguments); }; };
    wrap("drawImage", (ctx, a) => { const s = a[0] || {}; if (a.length >= 9) area(ctx, a[5], a[6], a[7], a[8]); else if (a.length >= 5) area(ctx, a[1], a[2], a[3], a[4]); else area(ctx, a[1], a[2], s.width || s.videoWidth || 0, s.height || s.videoHeight || 0); });
    wrap("fillRect", (ctx, a) => area(ctx, a[0], a[1], a[2], a[3]));
    wrap("clearRect", (ctx, a) => area(ctx, a[0], a[1], a[2], a[3]));
    wrap("putImageData", (ctx, a) => { const d = a[0] || {}; if (a.length >= 7) area(ctx, a[1] + a[3], a[2] + a[4], a[5], a[6]); else area(ctx, a[1], a[2], d.width || 0, d.height || 0); });
    for (const n of ["fill", "stroke", "fillText", "strokeRect"]) wrap(n, () => { c.calls2d++; });
  }
  // ---- WebGL: draw calls, triangles, vertices, uploads; the stand-in box's GPU; the fragment counter
  const getContext = HTMLCanvasElement.prototype.getContext, seen = new WeakSet();
  HTMLCanvasElement.prototype.getContext = function (type, attrs) {
    if (BOX && !BOX.webgl2 && /^webgl2$/i.test(type)) return null;
    if (B.mode === "fill" && /webgl/i.test(type)) attrs = Object.assign({}, attrs, { alpha: true, premultipliedAlpha: false });
    const gl = getContext.call(this, type, attrs);
    if (gl && /webgl/i.test(type) && !seen.has(gl)) { seen.add(gl); if (B.mode !== "mem" || BOX) patch(gl, this); }
    return gl;
  };
  function patch(gl, canvas) {
    const o = {}; for (const n of ["drawArrays", "drawElements", "bufferData", "bufferSubData", "texImage2D", "texSubImage2D", "getParameter", "getExtension", "getSupportedExtensions",
      "shaderSource", "createShader", "useProgram", "enable", "disable", "blendFunc", "blendFuncSeparate", "clear", "clearColor", "getUniformLocation", "uniform4f", "readPixels", "bindFramebuffer"]) o[n] = gl[n].bind(gl);
    const TRI = gl.TRIANGLES, STRIP = gl.TRIANGLE_STRIP, FAN = gl.TRIANGLE_FAN, PTS = gl.POINTS, BLEND = gl.BLEND;
    let blend = false, prog = null, fbo = null; const bf = [gl.ONE, gl.ZERO, gl.ONE, gl.ZERO], cc = new Float32Array(4);
    const ovr = new Map(), kinds = new WeakMap();
    const count = (mode, n) => { c.draws++; c.verts += n; if (mode === TRI) c.tris += n / 3; else if (mode === STRIP || mode === FAN) c.tris += Math.max(0, n - 2); else if (mode === PTS) c.points += n; };
    const fillOn = () => {                              // every fragment adds K to red (opaque) or green (see-through)
      if (!c.clears && !c.draws0 && !fbo) { c.draws0 = 1; o.clearColor(0, 0, 0, 0); o.clear(gl.COLOR_BUFFER_BIT); o.clearColor(cc[0], cc[1], cc[2], cc[3]); }   // (a page that never clears: counted from nothing all the same)
      let loc = ovr.get(prog); if (loc === undefined) { loc = prog ? o.getUniformLocation(prog, "uBenchOvr") : null; ovr.set(prog, loc); }
      if (loc) o.uniform4f(loc, blend ? 0 : K / 255, blend ? K / 255 : 0, 0, 0);
      o.enable(BLEND); o.blendFunc(gl.ONE, gl.ONE);
    };
    const fillOff = () => { if (!blend) o.disable(BLEND); o.blendFuncSeparate(bf[0], bf[1], bf[2], bf[3]); };
    const FILLS = B.mode === "fill";                    // (nothing is made a call here: the page's own garbage is what's measured)
    if (B.mode !== "mem") {
    gl.drawArrays = function (mode, first, n) { count(mode, n); if (FILLS) fillOn(); o.drawArrays(mode, first, n); if (FILLS) fillOff(); };
    gl.drawElements = function (mode, n, type, off) { count(mode, n); if (FILLS) fillOn(); o.drawElements(mode, n, type, off); if (FILLS) fillOff(); };
    }
    if (B.mode === "time") {
    const bytes = d => (d == null ? 0 : typeof d === "number" ? d : d.byteLength || 0);
    gl.bufferData = function (t, d, u) { c.buf += bytes(d); return o.bufferData(t, d, u); };
    gl.bufferSubData = function (t, off, d) { c.buf += bytes(d); return o.bufferSubData(t, off, d); };
    const texPx = a => { const s = a[a.length - 1]; if (a.length >= 9 || (a.length === 9)) return (a[3] | 0) * (a[4] | 0); return s && (s.width || s.videoWidth) ? (s.width || s.videoWidth) * (s.height || s.videoHeight) : 0; };
    gl.texImage2D = function () { c.tex += texPx(arguments); return o.texImage2D.apply(null, arguments); };
    gl.texSubImage2D = function () { const a = arguments; c.tex += a.length >= 9 ? (a[4] | 0) * (a[5] | 0) : texPx(a); return o.texSubImage2D.apply(null, a); };
    for (const n in gl) if (/^uniform(?!4f$)/.test(n) && typeof gl[n] === "function") { const f = gl[n].bind(gl); gl[n] = function () { c.uni++; return f.apply(null, arguments); }; }
    gl.uniform4f = function () { c.uni++; return o.uniform4f.apply(null, arguments); };
    }
    gl.useProgram = function (p) { c.prog++; prog = p; return o.useProgram(p); };
    gl.enable = function (cap) { if (cap === BLEND) blend = true; return o.enable(cap); };
    gl.disable = function (cap) { if (cap === BLEND) blend = false; return o.disable(cap); };
    gl.blendFunc = function (s, d) { bf[0] = bf[2] = s; bf[1] = bf[3] = d; return o.blendFunc(s, d); };
    gl.blendFuncSeparate = function (s, d, sa, da) { bf[0] = s; bf[1] = d; bf[2] = sa; bf[3] = da; return o.blendFuncSeparate(s, d, sa, da); };
    gl.bindFramebuffer = function (t, f) { fbo = f; return o.bindFramebuffer(t, f); };
    gl.clearColor = function (r, g, b, a) { cc[0] = r; cc[1] = g; cc[2] = b; cc[3] = a; return o.clearColor(r, g, b, a); };
    gl.clear = function (mask) { c.clears++; if (B.mode === "fill") { o.clearColor(0, 0, 0, 0); o.clear(mask); return o.clearColor(cc[0], cc[1], cc[2], cc[3]); } return o.clear(mask); };
    if (B.mode === "fill") {
      gl.createShader = function (type) { const s = o.createShader(type); if (s) kinds.set(s, type); return s; };
      gl.shaderSource = function (s, src) {
        if (kinds.get(s) === gl.FRAGMENT_SHADER && /\bvoid\s+main\s*\(/.test(src)) src = src.replace(/\bvoid\s+main\s*\(\s*(void)?\s*\)/, "void benchMain()") + "\nuniform mediump vec4 uBenchOvr;\nvoid main() { benchMain(); gl_FragColor = uBenchOvr; }\n";
        return o.shaderSource(s, src);
      };
    }
    if (BOX) {
      const dbg = o.getExtension("WEBGL_debug_renderer_info");
      gl.getParameter = function (p) {
        if (dbg && p === dbg.UNMASKED_RENDERER_WEBGL) return BOX.renderer;
        if (dbg && p === dbg.UNMASKED_VENDOR_WEBGL) return BOX.vendor;
        if (p === gl.MAX_TEXTURE_SIZE) return Math.min(BOX.maxTex, o.getParameter(p));
        return o.getParameter(p);
      };
      if (BOX.ext) {
        gl.getExtension = function (n) { return BOX.ext.indexOf(n) >= 0 ? o.getExtension(n) : null; };
        gl.getSupportedExtensions = function () { return (o.getSupportedExtensions() || []).filter(n => BOX.ext.indexOf(n) >= 0); };
      }
    }
    if (canvas.isConnected || !B.gl) { B.gl = gl; B.read = o.readPixels; B.fbo = () => fbo; B.canvas = canvas; }
  }
  let px = null, every = 0;
  function sample() {                                   // (fill mode) add up the counters in the picture just drawn
    if (++every % 6 || B.fbo()) return;
    const gl = B.gl, w = gl.drawingBufferWidth, h = gl.drawingBufferHeight;
    if (!px || px.length !== w * h * 4) px = new Uint8Array(w * h * 4);
    B.read(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, px);
    let r = 0, g = 0, top = 0;
    for (let i = 0; i < px.length; i += 4) { r += px[i]; g += px[i + 1]; if (px[i] + px[i + 1] > top) top = px[i] + px[i + 1]; }
    B.fill.push([r / K / (w * h), g / K / (w * h), top / K, w, h]);
  }
}

// ---------------------------------------------------------------- DevTools
function connect(ws) {
  return new Promise((ok, bad) => {
    const s = new WebSocket(ws); let id = 0; const wait = new Map(), on = [];
    s.onopen = () => ok({
      send(method, params) { return new Promise((r, j) => { const i = ++id; wait.set(i, { r, j }); s.send(JSON.stringify({ id: i, method, params: params || {} })); }); },
      on(cb) { on.push(cb); }, off(cb) { const i = on.indexOf(cb); if (i >= 0) on.splice(i, 1); }, close() { s.close(); }
    });
    s.onerror = e => bad(new Error("DevTools: " + (e.message || "no connection")));
    s.onmessage = m => { const d = JSON.parse(m.data); if (d.id && wait.has(d.id)) { const w = wait.get(d.id); wait.delete(d.id); d.error ? w.j(new Error(method(d) + JSON.stringify(d.error))) : w.r(d.result); } else for (const cb of on.slice()) cb(d); };
  });
}
const method = () => "";
const sleep = ms => new Promise(r => setTimeout(r, ms));
const q = (sorted, p) => (sorted.length ? sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * p))] : 0);
const r1 = v => Math.round(v * 10) / 10, r2 = v => Math.round(v * 100) / 100;

function findChrome() {
  const env = process.env.CHROME; if (env && fs.existsSync(env)) return env;
  const fixed = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Chromium.app/Contents/MacOS/Chromium"];
  for (const f of fixed) if (fs.existsSync(f)) return f;
  for (const dir of (process.env.PATH || "").split(path.delimiter)) for (const n of ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]) { const f = path.join(dir, n); if (fs.existsSync(f)) return f; }
  throw new Error("no Chrome found: set CHROME to its program");
}
const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".css": "text/css", ".woff2": "font/woff2" };
function serve() {
  return new Promise(ok => {
    const srv = http.createServer((req, res) => {
      let p = decodeURIComponent(req.url.split(/[?#]/)[0]); if (p.endsWith("/")) p += "index.html";
      const full = path.join(ROOT, path.normalize(p));
      if (!full.startsWith(ROOT)) { res.writeHead(403); return res.end(); }
      fs.readFile(full, (err, data) => {
        if (err) { res.writeHead(404, { "Content-Type": "application/json" }); return res.end("{}"); }
        res.writeHead(200, { "Content-Type": TYPES[path.extname(full)] || "application/octet-stream", "Cache-Control": "no-store" }); res.end(data);
      });
    });
    srv.listen(0, "127.0.0.1", () => ok(srv));
  });
}
async function startChrome(profile) {
  const flags = ["--remote-debugging-port=0", "--user-data-dir=" + profile, "--no-first-run", "--no-default-browser-check", "--disable-background-timer-throttling",
    "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows", "--autoplay-policy=no-user-gesture-required", "--mute-audio", "--enable-precise-memory-info",
    "--window-size=960,540", "--hide-scrollbars", "--disable-extensions", "--disable-component-update", "--disable-features=Translate,MediaRouter,OptimizationHints"];
  if (!HEADED) flags.push("--headless=new");
  if (GPU === "metal") flags.push("--use-angle=metal", "--enable-gpu", "--ignore-gpu-blocklist");
  else if (GPU === "swiftshader") flags.push("--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist");
  else if (GPU === "off") flags.push("--disable-gpu");
  const child = spawn(findChrome(), flags.concat(["about:blank"]), { stdio: ["ignore", "ignore", "pipe"] });
  let err = ""; child.stderr.on("data", d => { err += d; if (err.length > 20000) err = err.slice(-10000); });
  const file = path.join(profile, "DevToolsActivePort");
  for (let i = 0; i < 150; i++) { if (fs.existsSync(file)) { const port = +fs.readFileSync(file, "utf8").split("\n")[0]; if (port) return { child, port, err: () => err }; } await sleep(100); }
  child.kill(); throw new Error("Chrome did not start:\n" + err.slice(-2000));
}

// ---------------------------------------------------------------- one scene, measured
async function openTab(port, origin, mode) {
  const tab = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: "PUT" })).json();
  const c = await connect(tab.webSocketDebuggerUrl); c.tab = tab.id; c.errors = [];
  c.on(d => {
    if (d.method === "Runtime.exceptionThrown") c.errors.push(String((d.params.exceptionDetails.exception && d.params.exceptionDetails.exception.description) || d.params.exceptionDetails.text).slice(0, 240));
    if (d.method === "Runtime.consoleAPICalled" && (d.params.type === "error" || d.params.type === "assert")) c.errors.push("console: " + d.params.args.map(a => a.value || a.description).join(" ").slice(0, 240));
  });
  await c.send("Page.enable"); await c.send("Runtime.enable");
  if (BOX !== "pc") { await c.send("Emulation.setDeviceMetricsOverride", { width: 960, height: 540, deviceScaleFactor: 2, mobile: false }); await c.send("Emulation.setUserAgentOverride", { userAgent: BOXES[BOX].ua, platform: "Linux aarch64" }); }
  else await c.send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 720, deviceScaleFactor: 1, mobile: false });
  await c.send("Page.addScriptToEvaluateOnNewDocument", { source: `(${hook.toString()})(${JSON.stringify(BOXES[BOX])}, ${JSON.stringify(mode)});` });
  await c.send("Storage.clearDataForOrigin", { origin, storageTypes: "all" });
  return c;
}
const evalJS = async (c, expression) => { const r = await c.send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true }); if (r.exceptionDetails) throw new Error((r.exceptionDetails.exception && r.exceptionDetails.exception.description) || r.exceptionDetails.text); return r.result.value; };
async function waitFor(c, expression, ms, what) {
  const until = Date.now() + ms;
  for (;;) { let v = false; try { v = await evalJS(c, `(() => { try { return !!(${expression}); } catch (e) { return false; } })()`); } catch (e) { v = false; } if (v) return true; if (Date.now() > until) throw new Error("timed out waiting for " + what); await sleep(150); }
}
async function enter(c, origin, game, scene, slow) {
  const hash = [scene.hash, HASH, slow > 1 ? "slow=" + slow : ""].filter(Boolean).join("&");
  await c.send("Page.navigate", { url: `${origin}/games/${game}/#${hash}` });
  await waitFor(c, "document.readyState === 'complete' && (!window.SofaStats || SofaStats.ready !== false)", 45000, "the game to be ready");
  await sleep(600);
  if (scene.enter) await evalJS(c, scene.enter);
  if (scene.until) await waitFor(c, scene.until, 30000, "the scene (" + scene.until + ")");
  await sleep(scene.settle || 2000);
}
async function traceGC(c, run) {                         // the garbage collector's pauses while run() goes on
  // (the page's own thread is told from its workers' by the threads' names: a worker has a collector of its own, and
  // its pauses stop that worker, not the page)
  const ev = [], names = new Map(), take = d => {
    if (d.method !== "Tracing.dataCollected") return;
    for (const e of d.params.value) {
      if (e.ph === "M" && e.name === "thread_name") names.set(e.pid + ":" + e.tid, (e.args && e.args.name) || "");
      else if (/GC|Scaveng|MarkCompact/i.test(e.name || "")) ev.push(e);
    }
  };
  c.on(take);
  let traced = true;
  try { await c.send("Tracing.start", { transferMode: "ReportEvents", traceConfig: { recordMode: "recordAsMuchAsPossible", includedCategories: ["v8", "devtools.timeline", "disabled-by-default-v8.gc"], excludedCategories: ["*"] } }); } catch (e) { traced = false; }
  await run();
  if (traced) { const done = new Promise(r => { const f = d => { if (d.method === "Tracing.tracingComplete") { c.off(f); r(); } }; c.on(f); }); await c.send("Tracing.end"); await Promise.race([done, sleep(20000)]); }
  c.off(take);
  // top-level pauses: MinorGC / MajorGC as complete events (X), or begin and end pairs (B, E)
  const out = [], open = new Map();
  for (const e of ev.sort((a, b) => a.ts - b.ts)) {
    if (!/^(MinorGC|MajorGC)$/.test(e.name)) continue;
    const worker = /worker/i.test(names.get(e.pid + ":" + e.tid) || "");
    if (e.ph === "X") out.push({ name: e.name, ms: (e.dur || 0) / 1000, worker });
    else if (e.ph === "B") open.set(e.tid + e.name, e.ts);
    else if (e.ph === "E" && open.has(e.tid + e.name)) { out.push({ name: e.name, ms: (e.ts - open.get(e.tid + e.name)) / 1000, worker }); open.delete(e.tid + e.name); }
  }
  return traced ? out : null;
}
async function measure(port, origin, game, scene) {
  // the first pass: frame times and the page's work as the stand-in box (#slow), and what it draws
  const c = await openTab(port, origin, "time");
  const res = { game, scene: name(scene) };
  try {
    await enter(c, origin, game, scene, SLOW);
    if (CPU > 1) await c.send("Emulation.setCPUThrottlingRate", { rate: CPU });
    await evalJS(c, "window.__bench.start()"); await sleep(SECS * 1000); await evalJS(c, "window.__bench.stop()");
    if (CPU > 1) await c.send("Emulation.setCPUThrottlingRate", { rate: 1 });
    const v = await evalJS(c, `(() => { const B = window.__bench, S = window.SofaStats || {}, cv = (B.canvas && B.canvas.isConnected ? B.canvas : null) || document.querySelector("canvas:not(.hidden)") || document.querySelector("canvas") || B.canvas;   /* (the game's own, on the page: not a canvas made aside to ask the GPU what it is) */
      return { ticks: B.ticks, secs: (B.t1 - B.t0) / 1000, tier: S.tier || null, canvas: cv ? [cv.width, cv.height] : null, gl: !!(B.gl && B.ticks.some(t => t[2] > 0)),
        fpsText: (document.getElementById("fps") || {}).textContent || "" }; })()`);
    const drawn = v.ticks.filter(t => t[2] > 0 || t[7] > 0 || t[12] > 0);   // (a tick that drew something: WebGL draws, or 2D pixels or calls)
    const gaps = []; for (let i = 1; i < drawn.length; i++) gaps.push(drawn[i][0] - drawn[i - 1][0]);
    const gs = gaps.slice().sort((a, b) => a - b), ws = drawn.map(t => t[1]).sort((a, b) => a - b);
    const avg = k => (drawn.length ? drawn.reduce((a, t) => a + t[k], 0) / drawn.length : 0), max = k => drawn.reduce((a, t) => Math.max(a, t[k]), 0);
    const px = v.canvas ? v.canvas[0] * v.canvas[1] : 1;
    Object.assign(res, {
      tier: v.tier, picture: v.canvas ? v.canvas.join("x") : "", renderer: v.gl ? "WebGL" : "2D canvas", fps: r1(drawn.length / v.secs), refresh: r1(v.ticks.length / v.secs),
      gap_ms: { p50: r1(q(gs, 0.5)), p95: r1(q(gs, 0.95)), p99: r1(q(gs, 0.99)), worst: r1(gs[gs.length - 1] || 0) }, late: gaps.filter(g => g > 25).length, frames: drawn.length,
      work_ms: { p50: r2(q(ws, 0.5)), p95: r2(q(ws, 0.95)), p99: r2(q(ws, 0.99)), worst: r2(ws[ws.length - 1] || 0) },
      draws: { avg: r1(avg(2)), max: max(2) }, tris: Math.round(avg(3)), verts: { avg: Math.round(avg(4)), max: max(4) }, points: Math.round(avg(10)), uniforms: Math.round(avg(11)), programs: r1(avg(14)),
      upload: { vertex_bytes: Math.round(avg(5)), texture_px: Math.round(avg(6)) },
      canvas2d: { screens: r2(avg(7) / px), px: Math.round(avg(7)), offscreen_px: Math.round(avg(8)), calls: Math.round(avg(12)) },
      engine: v.fpsText.replace(/\n/g, " | "), errors: [...new Set(c.errors)].slice(0, 5)
    });
    if (SHOTS) { fs.mkdirSync(SHOTS, { recursive: true }); const s = await c.send("Page.captureScreenshot", { format: "png" }); res.shot = path.join(SHOTS, slug(game + "-" + name(scene)) + ".png"); fs.writeFileSync(res.shot, Buffer.from(s.data, "base64")); }
  } catch (e) { res.error = String(e.message || e); res.errors = [...new Set(c.errors)].slice(0, 5); }
  await fetch(`http://127.0.0.1:${port}/json/close/${c.tab}`).catch(() => {}); c.close();
  if (res.error || !FILL) return res;
  // the second pass, at this computer's own speed and with nothing counted (#slow's waiting and the counters make
  // garbage of their own): script memory made, the collector's pauses, the page's layers, where the time and the
  // memory go; then, with WebGL, a third: every fragment counted
  const f = await openTab(port, origin, "mem");
  try {
    await enter(f, origin, game, scene, 1);
    await sleep(WARM * 1000);                            // (the script engine makes garbage of its own until it has the game's hot code compiled)
    let layers = null;
    const onLayer = d => { if (d.method === "LayerTree.layerTreeDidChange" && d.params.layers) layers = d.params.layers; };
    f.on(onLayer); try { await f.send("LayerTree.enable"); } catch (e) { /* older Chromes */ }
    await sleep(300);
    const secs2 = Math.min(SECS, 8);
    if (PROFILE) { await f.send("Profiler.enable"); await f.send("Profiler.setSamplingInterval", { interval: 200 }); await f.send("Profiler.start"); }
    if (ALLOC) { await f.send("HeapProfiler.enable"); await f.send("HeapProfiler.startSampling", { samplingInterval: 256, includeObjectsCollectedByMajorGC: true, includeObjectsCollectedByMinorGC: true }); }
    const gcs = await traceGC(f, async () => { await evalJS(f, "window.__bench.start()"); await sleep(secs2 * 1000); await evalJS(f, "window.__bench.stop()"); });
    if (PROFILE) {
      const pr = (await f.send("Profiler.stop")).profile, self = new Map(), dt = pr.timeDeltas || [], idOf = new Map(pr.nodes.map(n => [n.id, n]));
      (pr.samples || []).forEach((id, i) => { const n = idOf.get(id), fr = n.callFrame, k = (fr.functionName || "(anonymous)") + " " + fr.url.split("/").slice(-2).join("/") + ":" + (fr.lineNumber + 1); self.set(k, (self.get(k) || 0) + (dt[i] || 0)); });
      res.profile = [...self.entries()].filter(e => !/^\((idle|program|garbage collector)\)/.test(e[0])).sort((a, b) => b[1] - a[1]).slice(0, 14).map(e => ({ fn: e[0], ms_per_s: r2(e[1] / 1000 / secs2) }));
    }
    if (ALLOC) {
      const hp = (await f.send("HeapProfiler.stopSampling")).profile, sites = new Map();
      const walk = n => { const fr = n.callFrame, k = (fr.functionName || "(anonymous)") + " " + fr.url.split("/").slice(-2).join("/") + ":" + (fr.lineNumber + 1); if (n.selfSize) sites.set(k, (sites.get(k) || 0) + n.selfSize); (n.children || []).forEach(walk); };
      walk(hp.head);
      res.alloc = [...sites.entries()].sort((a, b) => b[1] - a[1]).slice(0, 12).map(e => ({ fn: e[0], kb_s: Math.round(e[1] / 1024 / secs2) }));
      res.alloc_kb_s = Math.round([...sites.values()].reduce((a, b) => a + b, 0) / 1024 / secs2);   // all of it: what the script made on its heap
    }
    f.off(onLayer); try { await f.send("LayerTree.disable"); } catch (e) { /* none */ }
    const v = await evalJS(f, "({ heap: window.__bench.ticks.map(t => t[9]), secs: (window.__bench.t1 - window.__bench.t0) / 1000, dpr: devicePixelRatio, vw: innerWidth, vh: innerHeight })");
    let made = 0; for (let i = 1; i < v.heap.length; i++) { const d = v.heap[i] - v.heap[i - 1]; if (d > 0) made += d; }
    res.heap_kb_s = Math.round(made / 1024 / v.secs);
    const sum = list => ({ count: list.length, per_min: Math.round(list.length * 60 / v.secs), total_ms: r1(list.reduce((a, g) => a + g.ms, 0)), worst_ms: r1(list.reduce((a, g) => Math.max(a, g.ms), 0)), major: list.filter(g => g.name === "MajorGC").length });
    res.gc = gcs ? sum(gcs.filter(g => !g.worker)) : null;            // the page's own thread
    res.gc_workers = gcs && gcs.some(g => g.worker) ? sum(gcs.filter(g => g.worker)) : null;   // its workers' (Low3D's helpers): each stops a helper, not the page
    if (layers) {
      // what lies over the game's picture: every layer that draws but the page's own ground and the first that fills the
      // screen (the canvas: the browser leaves out what an opaque layer hides)
      const draws = layers.filter(l => l.drawsContent && l.width * l.height > 0), full = l => l.width >= v.vw && l.height >= v.vh;
      const over = draws.filter(l => !full(l)).concat(draws.filter(full).slice(2));
      res.layers = { drawing: draws.length, over: over.length, over_mpx: r2(over.reduce((a, l) => a + l.width * l.height, 0) * v.dpr * v.dpr / 1e6),
        mpx: r2(draws.reduce((a, l) => a + l.width * l.height, 0) * v.dpr * v.dpr / 1e6), list: over.map(l => Math.round(l.width * v.dpr) + "x" + Math.round(l.height * v.dpr)).join(" ") };
    }
  } catch (e) { res.mem_error = String(e.message || e); }
  await fetch(`http://127.0.0.1:${port}/json/close/${f.tab}`).catch(() => {}); f.close();
  if (res.renderer !== "WebGL") return res;
  const g = await openTab(port, origin, "fill");
  try {
    await enter(g, origin, game, scene, 1);
    await evalJS(g, "window.__bench.start()"); await sleep(3000); await evalJS(g, "window.__bench.stop()");
    const s = await evalJS(g, "window.__bench.fill");
    if (!s.length) res.fill = { error: "nothing read back" + (g.errors.length ? ": " + g.errors[0] : "") };
    else {
      const a = k => s.reduce((x, y) => x + y[k], 0) / s.length, m = k => s.reduce((x, y) => Math.max(x, y[k]), 0);
      res.fill = { opaque: r2(a(0)), blended: r2(a(1)), total: r2(a(0) + a(1)), worst: r2(s.reduce((x, y) => Math.max(x, y[0] + y[1]), 0)), deepest: m(2), samples: s.length,
        mpx_s_at_60: r1((a(0) + a(1)) * s[0][3] * s[0][4] * 60 / 1e6) };
    }
  } catch (e) { res.fill = { error: String(e.message || e) }; }
  await fetch(`http://127.0.0.1:${port}/json/close/${g.tab}`).catch(() => {}); g.close();
  return res;
}
const name = s => s.name, slug = s => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

// ---------------------------------------------------------------- the run
const pad = (s, n) => { s = String(s); return s.length >= n ? s : s + " ".repeat(n - s.length); };
function show(r) {
  if (r.error) { console.log(`  ${pad(r.scene, 40)} FAILED: ${r.error}${r.errors && r.errors.length ? "\n      " + r.errors.join("\n      ") : ""}`); return; }
  console.log(`  ${r.scene}  [${r.tier || r.renderer}, ${r.picture}]`);
  console.log(`      frames  ${pad(r.fps + " fps", 9)} between frames ${r.gap_ms.p50} / ${r.gap_ms.p95} / ${r.gap_ms.p99} / ${r.gap_ms.worst} ms (median / 95th / 99th / worst), ${r.late} of ${r.frames} late`);
  console.log(`      work    ${r.work_ms.p50} / ${r.work_ms.p95} / ${r.work_ms.p99} / ${r.work_ms.worst} ms a frame`);
  if (r.renderer === "WebGL") console.log(`      draws   ${r.draws.avg} a frame (most ${r.draws.max}), ${r.tris} triangles, ${r.verts.avg} vertices (most ${r.verts.max}), ${r.points} points, ${r.uniforms} uniform calls; sent ${r.upload.vertex_bytes} B of vertices, ${r.upload.texture_px} px of texture a frame`);
  if (r.canvas2d.px || r.canvas2d.offscreen_px) console.log(`      2D      ${r.canvas2d.screens} screens filled a frame (${r.canvas2d.px} px in ${r.canvas2d.calls} calls; ${r.canvas2d.offscreen_px} px more off screen)`);
  if (r.fill && !r.fill.error) console.log(`      fill    ${r.fill.total} screens of fragments a frame (${r.fill.opaque} opaque + ${r.fill.blended} see-through; worst frame ${r.fill.worst}, deepest pixel ${r.fill.deepest}): ${r.fill.mpx_s_at_60} Mpx/s at 60 fps`);
  if (r.fill && r.fill.error) console.log(`      fill    not measured: ${r.fill.error}`);
  if (r.heap_kb_s != null) console.log(`      memory  ${r.heap_kb_s} KB/s of script memory made${r.gc ? `; the collector stopped it ${r.gc.per_min} times a minute, worst ${r.gc.worst_ms} ms${r.gc.major ? " (" + r.gc.major + " full)" : ""}` : ""}${r.gc_workers ? `; its helpers' own ${r.gc_workers.per_min} times a minute, worst ${r.gc_workers.worst_ms} ms` : ""}`);
  if (r.layers) console.log(`      layers  ${r.layers.over} over the game's picture, ${r.layers.over_mpx} Mpx of them to lay over it each frame${r.layers.list ? " (" + r.layers.list + ")" : ""}`);
  if (r.mem_error) console.log("      memory  not measured: " + r.mem_error);
  if (r.profile) console.log("      time    (ms a second of its own, at this computer's speed) " + r.profile.map(p => p.fn + " " + p.ms_per_s).join("; "));
  if (r.alloc) console.log("      made by (KB a second) " + (r.alloc_kb_s != null ? r.alloc_kb_s + " in all: " : "") + r.alloc.map(p => p.fn + " " + p.kb_s).join("; "));
  if (r.errors && r.errors.length) console.log("      errors  " + r.errors.join(" | "));
}
(async () => {
  const srv = await serve(), origin = "http://127.0.0.1:" + srv.address().port;
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), "sofa-games-bench-"));
  let chrome = null; const all = [];
  const stop = () => { try { if (chrome) chrome.child.kill(); } catch (e) { /* gone */ } try { srv.close(); } catch (e) { /* closed */ } try { fs.rmSync(profile, { recursive: true, force: true }); } catch (e) { /* later */ } };
  process.on("SIGINT", () => { stop(); process.exit(130); });
  try {
    chrome = await startChrome(profile);
    const ver = await (await fetch(`http://127.0.0.1:${chrome.port}/json/version`)).json();
    const where = `${os.cpus()[0].model.trim()}, ${ver.Browser}${HEADED ? "" : " headless"}, GPU ${GPU}`;
    console.log(`Sofa Box games bench: ${ROOT}`);
    console.log(`Measured on: ${where}. Standing in for: ${BOX}${SLOW > 1 ? ", the game's work x" + SLOW + " (#slow)" : ""}${CPU > 1 ? ", Chrome CPU throttle x" + CPU : ""}. ${SECS} s a scene. Not a Pi's numbers.`);
    for (const g of GAMES) {
      console.log("\n" + g);
      for (const s of sceneList(g)) { const r = await measure(chrome.port, origin, g, s); all.push(r); show(r); if (VERBOSE && r.engine) console.log("      engine  " + r.engine); }
    }
    if (JSON_OUT) fs.writeFileSync(JSON_OUT, JSON.stringify({ root: ROOT, where, box: BOX, slow: SLOW, cpu: CPU, secs: SECS, at: new Date().toISOString(), scenes: all }, null, 1));
  } catch (e) { console.error(String(e.stack || e)); process.exitCode = 1; }
  stop();
  setTimeout(() => process.exit(process.exitCode || 0), 300);
})();
