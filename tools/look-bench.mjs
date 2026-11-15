#!/usr/bin/env node
/* What a game looks like, pictured the same way every time: fixed places, at chosen rungs, with the GPU and without,
   before and after a change, laid out on one sheet.

     node tools/look-bench.mjs --game wyrd                                  # this checkout: rungs 8 and 4, the GPU on
     node tools/look-bench.mjs --game wyrd --root before=../sofa-main --root after=. --rungs 8,4 --gpu on,off --out /tmp/look
     node tools/look-bench.mjs --game wyrd --places square,briar --clip square:6 --out /tmp/look

   --root label=path   a checkout (or its deploy/sofa-box) to picture; give several to set them side by side ("this"
                       checkout when none is given). --rungs: the rungs to picture (each a column). --gpu on,off: on is
                       this computer's GPU; off is Chrome with no GPU at all, so the game draws its 2D way, as a box
                       with no real GPU would. --places: ids from tools/look-places.json (all when left out).
   --size WxH          the page's size (1920x1080: the box's screen). --run "js": run after each place is reached (to try
                       a setting on every picture). --stats "js": what to say under each picture, in place of the
                       game's own (a timing, say). --clip id:seconds: also record that place moving, for each root at
                       its first rung (clip-<id>-<root>.webm, made in the page from its own canvas).
   --out dir           where the pictures go: <place>-<root>-r<rung>-<gpu>.png, and sheet.png (a row a place, a column
                       for each root, rung and GPU) with sheet.html beside it.

   The places are the game's own, in tools/look-places.json: what makes the game ready to drive, a prelude (a player,
   the screen quiet), what to say under each picture (stats: the draws and triangles of the last frame, say) and, for
   each place, where to stand and how long to wait for what streams in. Each picture is a
   fresh page with the site's storage cleared first, so nothing carries from one to the next. It runs its own servers
   and Chrome (two, for --gpu on,off), and closes them at the end.

   What it cannot do: be a Pi. The GPU is this computer's, so a picture is what the rung draws, never how fast a box
   draws it (that's games-bench.mjs). Nothing here needs more than node and Chrome. */
import http from "node:http";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const all = name => { const out = []; for (let i = 0; i < args.length; i++) if (args[i] === "--" + name && args[i + 1] && !args[i + 1].startsWith("--")) out.push(args[i + 1]); return out; };
const opt = (name, dflt) => { const a = all(name); return a.length ? a[a.length - 1] : args.includes("--" + name) ? true : dflt; };
if (opt("help", false)) { console.log(fs.readFileSync(fileURLToPath(import.meta.url), "utf8").split("*/")[0].replace(/^#!.*\n\/\* ?/, "")); process.exit(0); }

const GAME = String(opt("game", "wyrd")), RUNGS = String(opt("rungs", "8,4")).split(",").filter(Boolean).map(Number);
const GPUS = String(opt("gpu", "on")).split(",").filter(Boolean), HEADED = args.includes("--headed");
const [W, H] = String(opt("size", "1920x1080")).split("x").map(Number), RUN = opt("run", ""), STATS = opt("stats", "");
const OUT = path.resolve(String(opt("out", path.join(os.tmpdir(), "look-bench-" + Date.now()))));
const CLIP = opt("clip", "") ? String(opt("clip", "")).split(":") : null;
const PLACES_FILE = JSON.parse(fs.readFileSync(path.join(HERE, "look-places.json"), "utf8"));
const SPEC = PLACES_FILE[GAME];
if (!SPEC) { console.error("no places for " + GAME + " in tools/look-places.json"); process.exit(2); }
const ONLY = opt("places", "") ? String(opt("places", "")).split(",") : null;
const PLACES = SPEC.places.filter(p => !ONLY || ONLY.includes(p.id));
const boxDir = p => { const a = path.resolve(p); return fs.existsSync(path.join(a, "deploy", "sofa-box", "games")) ? path.join(a, "deploy", "sofa-box") : a; };
const ROOTS = (all("root").length ? all("root") : ["this=" + path.join(HERE, "..")]).map(s => { const i = s.indexOf("="); return i > 0 ? { label: s.slice(0, i), dir: boxDir(s.slice(i + 1)) } : { label: path.basename(path.resolve(s)), dir: boxDir(s) }; });
for (const r of ROOTS) if (!fs.existsSync(path.join(r.dir, "games", GAME, "index.html"))) { console.error("no games/" + GAME + " under " + r.dir); process.exit(2); }
fs.mkdirSync(OUT, { recursive: true });

// ---------------------------------------------------------------- DevTools, a server, Chrome
const sleep = ms => new Promise(r => setTimeout(r, ms));
function connect(ws) {
  return new Promise((ok, bad) => {
    const s = new WebSocket(ws); let id = 0; const wait = new Map(), on = [];
    s.onopen = () => ok({ send(method, params) { return new Promise((r, j) => { const i = ++id; wait.set(i, { r, j }); s.send(JSON.stringify({ id: i, method, params: params || {} })); }); },
      on(cb) { on.push(cb); }, close() { s.close(); } });
    s.onerror = e => bad(new Error("DevTools: " + (e.message || "no connection")));
    s.onmessage = m => { const d = JSON.parse(m.data); if (d.id && wait.has(d.id)) { const w = wait.get(d.id); wait.delete(d.id); d.error ? w.j(new Error(JSON.stringify(d.error))) : w.r(d.result); } else for (const cb of on.slice()) cb(d); };
  });
}
function findChrome() {
  const env = process.env.CHROME; if (env && fs.existsSync(env)) return env;
  for (const f of ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Chromium.app/Contents/MacOS/Chromium"]) if (fs.existsSync(f)) return f;
  for (const dir of (process.env.PATH || "").split(path.delimiter)) for (const n of ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]) { const f = path.join(dir, n); if (fs.existsSync(f)) return f; }
  throw new Error("no Chrome found: set CHROME to its program");
}
const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".css": "text/css", ".webm": "video/webm" };
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
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), "look-bench-chrome-"));
  const flags = ["--remote-debugging-port=0", "--user-data-dir=" + profile, "--no-first-run", "--no-default-browser-check", "--disable-background-timer-throttling",
    "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows", "--mute-audio", "--hide-scrollbars", "--disable-extensions",
    "--disable-component-update", "--window-size=" + W + "," + H];
  if (!HEADED) flags.push("--headless=new");
  if (gpu === "on") flags.push(process.platform === "darwin" ? "--use-angle=metal" : "--use-gl=angle", "--enable-gpu", "--ignore-gpu-blocklist");
  else flags.push("--disable-gpu");
  const child = spawn(findChrome(), flags.concat(["about:blank"]), { stdio: ["ignore", "ignore", "pipe"] });
  let err = ""; child.stderr.on("data", d => { err += d; if (err.length > 20000) err = err.slice(-10000); });
  const file = path.join(profile, "DevToolsActivePort");
  for (let i = 0; i < 600; i++) { if (fs.existsSync(file)) { const port = +fs.readFileSync(file, "utf8").split("\n")[0]; if (port) return { child, port, profile }; } await sleep(100); }
  child.kill(); throw new Error("Chrome did not start:\n" + err.slice(-2000));
}
async function openTab(port, w, h) {
  const tab = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: "PUT" })).json();
  const c = await connect(tab.webSocketDebuggerUrl); c.tab = tab.id; c.errors = [];
  c.on(d => {
    if (d.method === "Runtime.exceptionThrown") c.errors.push(String((d.params.exceptionDetails.exception && d.params.exceptionDetails.exception.description) || d.params.exceptionDetails.text).split("\n")[0].slice(0, 200));
    if (d.method === "Runtime.consoleAPICalled" && d.params.type === "error") c.errors.push("console: " + d.params.args.map(a => a.value || a.description).join(" ").slice(0, 200));
  });
  await c.send("Page.enable"); await c.send("Runtime.enable");
  await c.send("Emulation.setDeviceMetricsOverride", { width: w, height: h, deviceScaleFactor: 1, mobile: false });
  return c;
}
const closeTab = async (port, c) => { try { c.close(); await fetch(`http://127.0.0.1:${port}/json/close/${c.tab}`); } catch (e) { /* gone already */ } };
const evalJS = async (c, expression) => { const r = await c.send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true }); if (r.exceptionDetails) throw new Error((r.exceptionDetails.exception && r.exceptionDetails.exception.description) || r.exceptionDetails.text); return r.result.value; };
async function waitFor(c, expression, ms, what) {
  const until = Date.now() + ms;
  for (;;) { let v = false; try { v = await evalJS(c, `(() => { try { return !!(${expression}); } catch (e) { return false; } })()`); } catch (e) { v = false; } if (v) return; if (Date.now() > until) throw new Error("timed out waiting for " + what); await sleep(150); }
}

// ---------------------------------------------------------------- one picture (and the clip)
let pageNo = 0;
async function picture(chrome, origin, root, place, rung, gpu, clipSecs) {
  const c = await openTab(chrome.port, W, H);
  try {
    await c.send("Storage.clearDataForOrigin", { origin, storageTypes: "all" });
    const hash = [SPEC.hash, gpu === "on" ? "gl" : "", rung != null && gpu === "on" ? "rung=" + rung : ""].filter(Boolean).join("&");
    await c.send("Page.navigate", { url: `${origin}/games/${GAME}/index.html?look=${++pageNo}#${hash}` });
    await waitFor(c, SPEC.ready, 60000, "the game to be ready").catch(e => { throw new Error(e.message + (c.errors.length ? " (the page said: " + c.errors[0] + ")" : "")); });
    await sleep(500);
    await evalJS(c, `(() => { ${SPEC.prelude} })()`);
    await sleep(300);
    await evalJS(c, `(() => { ${place.run} })()`);
    if (RUN) await evalJS(c, `(() => { ${RUN} })()`);
    await sleep(place.settle || 2500);
    const shot = await c.send("Page.captureScreenshot", { format: "png" });
    const file = path.join(OUT, `${place.id}-${root.label}-r${rung}-${gpu}.png`);
    fs.writeFileSync(file, Buffer.from(shot.data, "base64"));
    let clip = null;
    if (clipSecs) {
      const b64 = await evalJS(c, `new Promise((ok, bad) => {
        const cv = [...document.querySelectorAll("canvas")].filter(x => x.offsetWidth > 0).sort((a, b) => b.width * b.height - a.width * a.height)[0];
        if (!cv || !cv.captureStream || !window.MediaRecorder) return bad(new Error("no canvas to record"));
        const rec = new MediaRecorder(cv.captureStream(30), { mimeType: "video/webm", videoBitsPerSecond: 8e6 }), parts = [];
        rec.ondataavailable = e => parts.push(e.data);
        rec.onstop = () => { const fr = new FileReader(); fr.onload = () => ok(String(fr.result).split(",")[1]); fr.readAsDataURL(new Blob(parts, { type: "video/webm" })); };
        rec.start(); setTimeout(() => rec.stop(), ${Math.round(clipSecs * 1000)});
      })`);
      clip = path.join(OUT, `clip-${place.id}-${root.label}.webm`);
      fs.writeFileSync(clip, Buffer.from(b64, "base64"));
    }
    const tier = await evalJS(c, "window.SofaStats ? SofaStats.tier : null").catch(() => null);
    const st = STATS || SPEC.stats, stats = st ? await evalJS(c, `(() => { try { return String(${st}); } catch (e) { return "stats: " + e.message; } })()`).catch(() => "") : "";
    return { file, clip, errors: c.errors.slice(), tier: [tier, stats].filter(Boolean).join(" · ") };
  } finally { await closeTab(chrome.port, c); }
}

// ---------------------------------------------------------------- the sheet: a row a place, a column for each root, rung and GPU
async function sheet(chrome, cols, rows) {
  const cell = 640, ch = Math.round(cell * H / W);
  const esc = s => String(s).replace(/[&<>"]/g, m => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[m]);
  const html = `<!doctype html><meta charset="utf-8"><title>${esc(GAME)}: look bench</title><style>
body{margin:0;background:#0b0d10;color:#efe6d2;font:700 15px/1.3 ui-monospace,Menlo,monospace}
table{border-collapse:separate;border-spacing:6px;padding:8px}th{padding:6px 8px;text-align:left;letter-spacing:.06em;text-transform:uppercase;font-size:14px}
th.col{border-bottom:4px solid #39ff88}th.row{width:150px;border-left:6px solid #ff2e88;vertical-align:middle}
img{display:block;width:${cell}px;height:${ch}px;outline:1px solid #242830}td small{display:block;padding:3px 2px 0;font-weight:600;opacity:.75;font-size:12px}
</style><table><tr><th></th>${cols.map(c => `<th class="col">${esc(c.label)}</th>`).join("")}</tr>
${rows.map(r => `<tr><th class="row">${esc(r.place.name)}</th>${r.cells.map(x => `<td>${x ? `<img src="${esc(path.basename(x.file))}"><small>${esc(x.tier || "")}${x.errors.length ? " · " + x.errors.length + " error(s)" : ""}</small>` : ""}</td>`).join("")}</tr>`).join("\n")}
</table>`;
  fs.writeFileSync(path.join(OUT, "sheet.html"), html);
  const srv = await serve(OUT), origin = "http://127.0.0.1:" + srv.address().port;
  const c = await openTab(chrome.port, cols.length * (cell + 6) + 190, 400);
  try {
    await c.send("Page.navigate", { url: origin + "/sheet.html" });
    await waitFor(c, "document.readyState === 'complete' && [...document.images].every(i => i.complete)", 30000, "the sheet");
    const size = await evalJS(c, "[document.documentElement.scrollWidth, document.documentElement.scrollHeight]");
    await c.send("Emulation.setDeviceMetricsOverride", { width: size[0], height: size[1], deviceScaleFactor: 1, mobile: false });
    await sleep(300);
    const shot = await c.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
    fs.writeFileSync(path.join(OUT, "sheet.png"), Buffer.from(shot.data, "base64"));
  } finally { await closeTab(chrome.port, c); srv.close(); }
}

// ---------------------------------------------------------------- run
const chromes = {}, servers = [];
async function main() {
  const cols = [];
  for (const gpu of GPUS) for (const root of ROOTS) for (const rung of gpu === "on" ? RUNGS : [null]) cols.push({ gpu, root, rung, label: `${root.label} · ${gpu === "on" ? "rung " + rung : "no GPU (2D)"}` });
  for (const gpu of GPUS) chromes[gpu] = await startChrome(gpu);
  for (const root of ROOTS) { const srv = await serve(root.dir); servers.push(srv); root.origin = "http://127.0.0.1:" + srv.address().port; }
  const rows = PLACES.map(place => ({ place, cells: [] }));
  console.log(`look bench: ${GAME}, ${PLACES.length} places × ${cols.length} columns → ${OUT}`);
  for (const row of rows) for (const col of cols) {
    const wantClip = CLIP && CLIP[0] === row.place.id && cols.find(k => k.root === col.root) === col ? +(CLIP[1] || 6) : 0;
    try {
      const r = await picture(chromes[col.gpu], col.root.origin, col.root, row.place, col.rung, col.gpu, wantClip);
      row.cells.push(r);
      console.log(`  ${row.place.id.padEnd(10)} ${col.label.padEnd(28)} ${r.tier || ""}${r.errors.length ? "  errors: " + r.errors.slice(0, 2).join(" | ") : ""}${r.clip ? "  clip: " + path.basename(r.clip) : ""}`);
    } catch (e) { row.cells.push(null); console.log(`  ${row.place.id.padEnd(10)} ${col.label.padEnd(28)} FAILED: ${e.message.split("\n")[0]}`); }
  }
  await sheet(chromes[GPUS[0]], cols, rows);
  console.log("sheet: " + path.join(OUT, "sheet.png"));
}
const done = code => { for (const k in chromes) { try { chromes[k].child.kill(); fs.rmSync(chromes[k].profile, { recursive: true, force: true }); } catch (e) { /* gone */ } } for (const s of servers) s.close(); process.exit(code); };
main().then(() => done(0), e => { console.error(e.stack || e.message); done(1); });
