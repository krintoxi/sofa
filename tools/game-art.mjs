#!/usr/bin/env node
/* Each page game's pictures for Home and the Games page, taken from the game itself: the game is opened in a Chrome of
   this tool's own, brought to a moment worth showing (tools/game-art.json: playing itself, or stood somewhere), and
   photographed. Nothing from outside: what's in a picture is what the game drew.

     node tools/game-art.mjs                       # every game: home/art/games/<id>.jpg (1280 x 720), small/<id>.jpg (640 x 360), icon/<id>.jpg (256 x 256)
     node tools/game-art.mjs --games wyrd,tidewing
     node tools/game-art.mjs --try 4,9,15,22 --out /tmp/art     # look for a moment: a picture at each of those seconds, and sheet.png
     node tools/game-art.mjs --recipes /tmp/mine.json --out /tmp/art   # other recipes, tried somewhere else first
     node tools/game-art.mjs --faces               # only the small faces again, cut from the pictures as they are (no game is run)
     node tools/game-art.mjs --check               # say which games have no recipe or no picture, change nothing (exit 1 if any)

   A game's recipe (tools/game-art.json):
     hash     what the page is opened with ("demo": it plays itself and keeps nothing)
     ready    true once the game can be driven (a game that needs standing somewhere)
     run      run once it is ready (stand here, face there, put the menus away)
     secs     how long to let it play before the picture
     quiet    run just before the picture (a banner cleared, the writing over the game hidden)
     zoom     the picture is a part of a larger one (1.25: the page drawn at 1600 x 900, 1280 x 720 of it kept), which
              leaves the game's own writing at the edges out of it; at: [x, y] is where in the page the picture's
              middle is, each from 0 to 1 (left out: the middle)
     icon     [x, y, size]: the game's face for a small tile, a square of the picture (its middle and its side, in the
              picture's own 1280 x 720), kept as icon/<id>.jpg at 256 x 256 (left out: the middle 720)
     gpu      "off" for a game pictured in its 2D way (left out: this computer's GPU)

   Needs node and Chrome, as the benches do. */
import http from "node:http";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BOX = path.join(HERE, "..", "deploy", "sofa-box"), ART = path.join(BOX, "home", "art", "games");
const args = process.argv.slice(2);
const opt = (name, dflt) => { const i = args.indexOf("--" + name); return i < 0 ? dflt : args[i + 1] && !args[i + 1].startsWith("--") ? args[i + 1] : true; };
if (opt("help", false)) { console.log(fs.readFileSync(fileURLToPath(import.meta.url), "utf8").split("*/")[0].replace(/^#!.*\n\/\* ?/, "")); process.exit(0); }
const W = 1280, H = 720, QUALITY = +opt("quality", 80);
const RECIPES = JSON.parse(fs.readFileSync(opt("recipes", "") ? path.resolve(String(opt("recipes", ""))) : path.join(HERE, "game-art.json"), "utf8"));
const LIST = JSON.parse(fs.readFileSync(path.join(BOX, "games", "games.json"), "utf8")).games.map(g => g.id);
const GAMES = opt("games", "") ? String(opt("games", "")).split(",") : LIST;
const TRY = opt("try", "") ? String(opt("try", "")).split(",").map(Number) : null;
const OUT = opt("out", "") ? path.resolve(String(opt("out", ""))) : null;

if (opt("check", false)) {
  const bad = [];
  for (const id of LIST) {
    if (!RECIPES[id]) bad.push(id + ": no recipe in tools/game-art.json");
    for (const f of [path.join(ART, id + ".jpg"), path.join(ART, "small", id + ".jpg"), path.join(ART, "icon", id + ".jpg")]) if (!fs.existsSync(f)) bad.push(id + ": no " + path.relative(BOX, f));
  }
  for (const id of Object.keys(RECIPES)) if (id !== "about" && !LIST.includes(id)) bad.push(id + ": a recipe for a game that isn't in games.json");
  console.log(bad.length ? bad.join("\n") : "Every game has its recipe and its pictures.");
  process.exit(bad.length ? 1 : 0);
}

const sleep = ms => new Promise(r => setTimeout(r, ms));
function connect(ws) {
  return new Promise((ok, bad) => {
    const s = new WebSocket(ws); let id = 0; const wait = new Map();
    s.onopen = () => ok({ send(method, params) { return new Promise((r, j) => { const i = ++id; wait.set(i, { r, j }); s.send(JSON.stringify({ id: i, method, params: params || {} })); }); }, close() { s.close(); } });
    s.onerror = e => bad(new Error("DevTools: " + (e.message || "no connection")));
    s.onmessage = m => { const d = JSON.parse(m.data); if (d.id && wait.has(d.id)) { const w = wait.get(d.id); wait.delete(d.id); d.error ? w.j(new Error(JSON.stringify(d.error))) : w.r(d.result); } };
  });
}
function findChrome() {
  const env = process.env.CHROME; if (env && fs.existsSync(env)) return env;
  for (const f of ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Chromium.app/Contents/MacOS/Chromium"]) if (fs.existsSync(f)) return f;
  for (const dir of (process.env.PATH || "").split(path.delimiter)) for (const n of ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]) { const f = path.join(dir, n); if (fs.existsSync(f)) return f; }
  throw new Error("no Chrome found: set CHROME to its program");
}
const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg" };
function serve(root) {
  return new Promise(ok => {
    const srv = http.createServer((req, res) => {
      let p = decodeURIComponent(req.url.split(/[?#]/)[0]); if (p.endsWith("/")) p += "index.html";
      const full = path.join(root, path.normalize(p));
      if (!full.startsWith(root)) { res.writeHead(403); return res.end(); }
      fs.readFile(full, (err, data) => {
        if (err) { res.writeHead(404, { "Content-Type": "application/json" }); return res.end("{}"); }
        res.writeHead(200, { "Content-Type": TYPES[path.extname(full)] || "application/octet-stream", "Cache-Control": "no-store" }); res.end(data);
      });
    });
    srv.listen(0, "127.0.0.1", () => ok(srv));
  });
}
async function startChrome(gpu) {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), "game-art-chrome-"));
  const flags = ["--remote-debugging-port=0", "--user-data-dir=" + profile, "--no-first-run", "--no-default-browser-check", "--disable-background-timer-throttling",
    "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows", "--mute-audio", "--hide-scrollbars", "--disable-extensions",
    "--disable-component-update", "--window-size=" + W + "," + H, "--headless=new"];
  if (gpu === "off") flags.push("--disable-gpu");
  else flags.push(process.platform === "darwin" ? "--use-angle=metal" : "--use-gl=angle", "--enable-gpu", "--ignore-gpu-blocklist");
  const child = spawn(findChrome(), flags.concat(["about:blank"]), { stdio: "ignore" });
  const file = path.join(profile, "DevToolsActivePort");
  for (let i = 0; i < 600; i++) { if (fs.existsSync(file)) { const port = +fs.readFileSync(file, "utf8").split("\n")[0]; if (port) return { child, port, profile }; } await sleep(100); }
  child.kill(); throw new Error("Chrome did not start");
}
const evalJS = async (c, expression) => { const r = await c.send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true }); if (r.exceptionDetails) throw new Error((r.exceptionDetails.exception && r.exceptionDetails.exception.description) || r.exceptionDetails.text); return r.result.value; };

// one game: its page, its moment, the pictures
async function picture(chrome, origin, id, r) {
  const zoom = r.zoom || 1, vw = Math.round(W * zoom), vh = Math.round(H * zoom);
  const tab = await (await fetch(`http://127.0.0.1:${chrome.port}/json/new?about:blank`, { method: "PUT" })).json();
  const c = await connect(tab.webSocketDebuggerUrl);
  const made = [];
  try {
    await c.send("Page.enable"); await c.send("Runtime.enable");
    await c.send("Emulation.setDeviceMetricsOverride", { width: vw, height: vh, deviceScaleFactor: 1, mobile: false });
    await c.send("Storage.clearDataForOrigin", { origin, storageTypes: "all" });
    await c.send("Page.navigate", { url: `${origin}/games/${id}/index.html?art=${Date.now()}#${r.hash == null ? "demo" : r.hash}` });
    if (r.ready) {
      const until = Date.now() + 60000;
      for (;;) { const v = await evalJS(c, `(() => { try { return !!(${r.ready}); } catch (e) { return false; } })()`).catch(() => false); if (v) break; if (Date.now() > until) throw new Error(id + ": never ready"); await sleep(150); }
      await sleep(400);
    } else await sleep(1200);
    if (r.run) await evalJS(c, `(() => { ${r.run} })()`);
    const still = () => evalJS(c, "window.requestAnimationFrame = () => 0; 1");      // (the same moment in every picture of it)
    const at = r.at || [0.5, 0.5], cx = Math.min(vw - W, Math.max(0, Math.round(at[0] * vw - W / 2))), cy = Math.min(vh - H, Math.max(0, Math.round(at[1] * vh - H / 2)));
    const whole = { x: cx, y: cy, width: W, height: H };
    const snap = async (file, scale) => {
      const clip = whole;
      if (r.quiet) { await evalJS(c, `(() => { ${r.quiet} })()`).catch(() => null); await sleep(120); }
      const shot = await c.send("Page.captureScreenshot", { format: "jpeg", quality: QUALITY, clip: Object.assign({ scale }, clip) });
      fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, Buffer.from(shot.data, "base64")); made.push(file);
    };
    if (TRY) {
      let at = 0;
      for (const t of TRY) { await sleep(Math.max(0, t - at) * 1000); at = t; await snap(path.join(OUT, `${id}-${String(t).padStart(2, "0")}.jpg`), 0.5); }
    } else {
      await sleep((r.secs == null ? 6 : r.secs) * 1000);
      const dir = OUT || ART;
      await still();
      await snap(path.join(dir, id + ".jpg"), 1);
      await snap(path.join(dir, "small", id + ".jpg"), 0.5);
      await face(c, origin, id, r, dir);
    }
  } finally { try { c.close(); await fetch(`http://127.0.0.1:${chrome.port}/json/close/${tab.id}`); } catch (e) { /* gone already */ } }
  return made;
}
// a game's face: a square of its picture, as the picture was kept (so the faces can be chosen again without the games)
async function face(c, origin, id, r, dir) {
  const big = path.join(dir, id + ".jpg"), ic = r.icon || [W / 2, H / 2, H], side = Math.min(H, ic[2]);
  const x = Math.min(W - side, Math.max(0, ic[0] - side / 2)), y = Math.min(H - side, Math.max(0, ic[1] - side / 2));
  await c.send("Emulation.setDeviceMetricsOverride", { width: W, height: H, deviceScaleFactor: 1, mobile: false });
  await c.send("Page.navigate", { url: "data:text/html," + encodeURIComponent(`<body style="margin:0;background:#000"><img style="display:block" src="data:image/jpeg;base64,${fs.readFileSync(big).toString("base64")}">`) });
  for (let i = 0; i < 50 && !(await evalJS(c, "!!document.images[0] && document.images[0].complete && document.images[0].naturalWidth > 0").catch(() => false)); i++) await sleep(100);
  const shot = await c.send("Page.captureScreenshot", { format: "jpeg", quality: QUALITY, clip: { x, y, width: side, height: side, scale: 256 / side } });
  const file = path.join(dir, "icon", id + ".jpg");
  fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, Buffer.from(shot.data, "base64"));
}
async function sheet(chrome, files) {
  const html = `<!doctype html><meta charset="utf-8"><style>body{margin:0;background:#0b0d10;color:#efe6d2;font:700 12px ui-monospace,Menlo,monospace;display:grid;grid-template-columns:repeat(${TRY.length},320px);gap:4px}
figure{margin:0;position:relative}img{display:block;width:320px;height:180px}figcaption{position:absolute;left:4px;top:2px;text-shadow:0 0 3px #000}</style>
${files.map(f => `<figure><img src="${path.basename(f)}"><figcaption>${path.basename(f, ".jpg")}</figcaption></figure>`).join("")}`;
  fs.writeFileSync(path.join(OUT, "sheet.html"), html);
  const srv = await serve(OUT), tab = await (await fetch(`http://127.0.0.1:${chrome.port}/json/new?about:blank`, { method: "PUT" })).json();
  const c = await connect(tab.webSocketDebuggerUrl);
  await c.send("Page.enable");
  await c.send("Emulation.setDeviceMetricsOverride", { width: TRY.length * 324, height: Math.ceil(files.length / TRY.length) * 184, deviceScaleFactor: 1, mobile: false });
  await c.send("Page.navigate", { url: `http://127.0.0.1:${srv.address().port}/sheet.html` }); await sleep(1500);
  const shot = await c.send("Page.captureScreenshot", { format: "jpeg", quality: 80 });
  fs.writeFileSync(path.join(OUT, "sheet.jpg"), Buffer.from(shot.data, "base64")); c.close(); srv.close();
}

if (opt("faces", false)) {                             // only the faces again, from the pictures as they are
  const chrome = await startChrome("off"), tab = await (await fetch(`http://127.0.0.1:${chrome.port}/json/new?about:blank`, { method: "PUT" })).json();
  const c = await connect(tab.webSocketDebuggerUrl);
  try { await c.send("Page.enable"); await c.send("Runtime.enable"); for (const id of GAMES) { await face(c, "", id, RECIPES[id] || {}, OUT || ART); console.log(id + ": its face"); } }
  finally { c.close(); chrome.child.kill(); await sleep(300); try { fs.rmSync(chrome.profile, { recursive: true, force: true }); } catch (e) { /* in use a moment longer */ } }
  process.exit(0);
}
if (TRY && !OUT) { console.error("--try needs --out: a folder for the pictures"); process.exit(2); }
const srv = await serve(BOX), origin = "http://127.0.0.1:" + srv.address().port, chromes = {}, all = [];
let failed = 0;
try {
  for (const id of GAMES) {
    const r = RECIPES[id] || {};
    const gpu = r.gpu === "off" ? "off" : "on";
    chromes[gpu] = chromes[gpu] || await startChrome(gpu);
    try { const made = await picture(chromes[gpu], origin, id, r); all.push(...made); console.log(id + ": " + made.map(f => path.relative(process.cwd(), f)).join(", ")); }
    catch (e) { failed++; console.error(id + ": " + e.message); }
  }
  if (TRY && all.length) await sheet(Object.values(chromes)[0], all);
} finally {
  srv.close();
  for (const ch of Object.values(chromes)) { ch.child.kill(); await sleep(300); try { fs.rmSync(ch.profile, { recursive: true, force: true }); } catch (e) { /* in use a moment longer */ } }
}
process.exit(failed ? 1 : 0);
