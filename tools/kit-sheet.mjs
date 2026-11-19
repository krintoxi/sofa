#!/usr/bin/env node
/* The kit, pictured: every thing Low3D's Kit builds (the maker's own list, games/maker/), each at the details it takes,
   under one light, on one sheet. For looking at the kit after a change to it, and before and after, side by side.

     node tools/kit-sheet.mjs                                   # this checkout, every thing, day light
     node tools/kit-sheet.mjs --things fir,birch,oak --light evening --row --out /tmp/kit
     node tools/kit-sheet.mjs --root before=../sofa-main --root after=. --things oak

   --root label=path   a checkout (or its deploy/sofa-box) to picture; several stand side by side.
   --things a,b        ids from the maker's list (all when left out); --details 0,1,2 (a thing is pictured at those it
                       takes; one without details once); --seed n; --row: five seeds side by side.
   --light             day, evening, overcast or night; --yaw: where the eye stands round it (radians).
   --lines n           the picture's height in lines (360: what a Pi 3 draws; 0: as sharp as the page).
   --size WxH          the page's size; --out dir: <thing>-d<detail>-<root>.png, sheet.html and sheet.png.

   It runs its own server and Chrome, and closes them. The GPU is this computer's: a picture is what the kit builds,
   never how fast a box draws it. Nothing here needs more than node and Chrome. */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import http from "node:http";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const argv = process.argv.slice(2);
if (argv.includes("--help") || argv.includes("-h")) { console.log(fs.readFileSync(fileURLToPath(import.meta.url), "utf8").split("*/")[0].replace(/^#!.*\n\/\* ?/, "")); process.exit(0); }
const all = n => { const out = []; for (let i = 0; i < argv.length; i++) if (argv[i] === "--" + n && argv[i + 1] != null) out.push(argv[++i]); return out; };
const one = (n, d) => { const a = all(n); return a.length ? a[a.length - 1] : d; };
const list = (n, d) => String(one(n, d)).split(",").map(s => s.trim()).filter(Boolean);
const OUT = path.resolve(one("out", path.join(os.tmpdir(), "kit-sheet")));
const [W, H] = one("size", "1280x720").split("x").map(Number);
const THINGS = one("things", "") ? list("things", "") : null, DETAILS = list("details", "0,1,2").map(Number), SEED = +one("seed", 1), ROW = argv.includes("--row");
const LIGHT = one("light", "day"), YAW = +one("yaw", 0.6), LINES = +one("lines", 360);
const boxDir = p => { const a = path.resolve(p); return fs.existsSync(path.join(a, "deploy", "sofa-box", "games")) ? path.join(a, "deploy", "sofa-box") : a; };
const ROOTS = (all("root").length ? all("root") : ["this=" + path.join(HERE, "..")]).map(s => { const i = s.indexOf("="); return i > 0 ? { label: s.slice(0, i), dir: boxDir(s.slice(i + 1)) } : { label: path.basename(path.resolve(s)), dir: boxDir(s) }; });
for (const r of ROOTS) if (!fs.existsSync(path.join(r.dir, "games", "maker", "index.html"))) { console.error("no games/maker under " + r.dir); process.exit(2); }
fs.mkdirSync(OUT, { recursive: true });

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
const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".css": "text/css" };
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
async function startChrome() {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), "kit-sheet-chrome-"));
  const flags = ["--remote-debugging-port=0", "--user-data-dir=" + profile, "--no-first-run", "--no-default-browser-check", "--disable-background-timer-throttling",
    "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows", "--mute-audio", "--hide-scrollbars", "--disable-extensions", "--disable-component-update",
    "--window-size=" + W + "," + H, "--headless=new", process.platform === "darwin" ? "--use-angle=metal" : "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"];
  const child = spawn(findChrome(), flags.concat(["about:blank"]), { stdio: ["ignore", "ignore", "pipe"] });
  let err = ""; child.stderr.on("data", d => { err += d; if (err.length > 20000) err = err.slice(-10000); });
  const file = path.join(profile, "DevToolsActivePort");
  for (let i = 0; i < 600; i++) { if (fs.existsSync(file)) { const port = +fs.readFileSync(file, "utf8").split("\n")[0]; if (port) return { child, port, profile }; } await sleep(100); }
  child.kill(); throw new Error("Chrome did not start:\n" + err.slice(-2000));
}
async function page(port, url) {
  const t = await (await fetch("http://127.0.0.1:" + port + "/json/new?" + encodeURIComponent(url), { method: "PUT" })).json();
  const c = await connect(t.webSocketDebuggerUrl);
  await c.send("Page.enable"); await c.send("Runtime.enable");
  await c.send("Emulation.setDeviceMetricsOverride", { width: W, height: H, deviceScaleFactor: 1, mobile: false });
  c.run = async js => { const r = await c.send("Runtime.evaluate", { expression: js, awaitPromise: true, returnByValue: true }); if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception ? r.exceptionDetails.exception.description : r.exceptionDetails.text); return r.result.value; };
  c.until = async (js, ms) => { for (let i = 0; i < (ms || 20000) / 100; i++) { if (await c.run(js).catch(() => false)) return; await sleep(100); } throw new Error("never true: " + js); };
  c.id = t.id; return c;
}

const chrome = await startChrome(), servers = [], rows = new Map(), cols = [];
try {
  for (const root of ROOTS) {
    const srv = await serve(root.dir); servers.push(srv);
    const c = await page(chrome.port, "http://127.0.0.1:" + srv.address().port + "/games/maker/");
    await c.until("window.Maker && window.Maker.kit && window.MakerKit && document.readyState === 'complete'");
    await c.run("Maker.show('kit')");
    const kit = await c.run("JSON.stringify(MakerKit.map(t => ({ id: t.id, name: t.name, details: t.details || null })))").then(JSON.parse);
    for (const t of kit) {
      if (THINGS && !THINGS.includes(t.id)) continue;
      for (const d of t.details ? DETAILS.filter(x => t.details.includes(x)) : [null]) {
        await c.run("Maker.kit.set(" + JSON.stringify({ thing: t.id, detail: d == null ? 1 : d, seed: SEED, row: ROW, light: LIGHT, yaw: YAW, pixels: LINES > 0 }) + ")");
        if (LINES > 0 && LINES !== 360) await c.run("(() => { const cv = document.getElementById('kgl'); cv.height = " + LINES + "; })()");
        await sleep(250);
        const count = await c.run("JSON.stringify(Maker.kit.count)").then(JSON.parse);
        const r = await c.run("(() => { const b = document.getElementById('kgl').getBoundingClientRect(); return JSON.stringify({ x: b.x, y: b.y, width: b.width, height: b.height }); })()").then(JSON.parse);
        const shot = await c.send("Page.captureScreenshot", { format: "png", clip: Object.assign({ scale: 1 }, r) });
        const file = t.id + (d == null ? "" : "-d" + d) + "-" + root.label + ".png";
        fs.writeFileSync(path.join(OUT, file), Buffer.from(shot.data, "base64"));
        const key = t.name + (d == null ? "" : ", detail " + d), col = root.label;
        if (!cols.includes(col)) cols.push(col);
        if (!rows.has(key)) rows.set(key, {});
        rows.get(key)[col] = { file, said: Math.round(count.tris) + " triangles" + (count.glow ? " + " + Math.round(count.glow) + " lit" : "") + ", " + count.h.toFixed(1) + " m tall" };
        console.log(file + "  " + rows.get(key)[col].said);
      }
    }
    c.close();
  }
  // the sheet: a row a thing and detail, a column a checkout
  const esc = s => String(s).replace(/[&<>"]/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[ch]);
  let html = "<!doctype html><meta charset=utf-8><title>The kit</title><style>body{margin:0;background:#050706;color:#e9ede8;font:13px ui-monospace,Menlo,monospace}table{border-collapse:collapse}td,th{padding:6px;vertical-align:top;text-align:left}th{color:#39ff88;font-weight:500}img{display:block;width:" + (cols.length > 1 ? 560 : 640) + "px}small{color:#8a968e}</style><table><tr><th></th>" + cols.map(c => "<th>" + esc(c) + "</th>").join("") + "</tr>";
  for (const [key, by] of rows) html += "<tr><th>" + esc(key) + "</th>" + cols.map(c => by[c] ? "<td><img src=\"" + esc(by[c].file) + "\"><small>" + esc(by[c].said) + "</small></td>" : "<td></td>").join("") + "</tr>";
  fs.writeFileSync(path.join(OUT, "sheet.html"), html + "</table>");
  const srv = await serve(OUT); servers.push(srv);
  const c = await page(chrome.port, "http://127.0.0.1:" + srv.address().port + "/sheet.html");
  await c.until("document.readyState === 'complete' && [...document.images].every(i => i.complete)");
  const size = await c.run("JSON.stringify({ w: document.documentElement.scrollWidth, h: document.documentElement.scrollHeight })").then(JSON.parse);
  await c.send("Emulation.setDeviceMetricsOverride", { width: size.w, height: Math.min(size.h, 16000), deviceScaleFactor: 1, mobile: false });
  const shot = await c.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
  fs.writeFileSync(path.join(OUT, "sheet.png"), Buffer.from(shot.data, "base64"));
  c.close();
  console.log(path.join(OUT, "sheet.png"));
} finally {
  for (const s of servers) s.close();
  chrome.child.kill();
  await sleep(300);
  try { fs.rmSync(chrome.profile, { recursive: true, force: true }); } catch (e) { /* Chrome may still be letting go of it */ }
}
