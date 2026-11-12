// Sofa Box icons, Phosphor, Sticker and Pixel. Drawn once, on a computer, and baked to pictures (build.py); the box only
// shows pictures, so none of the glow, grain or halftone costs a Pi 3 anything.
const INK = "#0E0E12", BONE = "#EDE6D6", GREEN = "#3DF07A", PINK = "#FF2E88";
const DPINK = "#B3175E", DGREEN = "#13854B", DIM = "#3A3A46";
const { ICONS } = require("./drawn.js");
const NAMES = { sofa: "Sofa", live: "Live TV", browser: "Browser", store: "Store", games: "Games", files: "Files", settings: "Settings", "edge-music": "Edge Music",
  "lj-showroom": "The LJ Collection", "lj-manager": "LJ Collection Manager", "lj-fragrances": "LJ Fragrances", edgeventure: "EdgeVenture",
  "gold-toilet": "Glossy Gold Toilet" };
const IDS = Object.keys(NAMES);

// ---------- A. Phosphor: the line drawings lit like a green screen, glow and scan lines baked in
function phosphor(id, size) {
  const body = ICONS[id][1].replaceAll(BONE, GREEN).replace(/<rect x="29" y="12"[^>]*\/>/, "");   // (the sofa's cursor block: a bump here)
  const u = `${id}-${size}`;
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="${size}" height="${size}">
  <defs><radialGradient id="crt-${u}" cx="50%" cy="45%" r="70%"><stop offset="0" stop-color="#0c2214"/><stop offset=".7" stop-color="#06100a"/><stop offset="1" stop-color="#020403"/></radialGradient>
  <filter id="glow-${u}" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="1.6" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  <pattern id="sl-${u}" width="64" height="2" patternUnits="userSpaceOnUse"><rect width="64" height="1" fill="#000" opacity=".35"/></pattern>
  <clipPath id="c-${u}"><rect x="1" y="1" width="62" height="62" rx="14"/></clipPath></defs>
  <g clip-path="url(#c-${u})"><rect width="64" height="64" fill="url(#crt-${u})"/>
  <g filter="url(#glow-${u})" transform="translate(32 32) scale(.9) translate(-32 -32)">${body}</g>
  <rect width="64" height="64" fill="url(#sl-${u})"/></g>
  <rect x="1" y="1" width="62" height="62" rx="14" fill="none" stroke="${GREEN}" stroke-opacity=".28"/></svg>`;
}

// ---------- B. Sticker: die-cut street stickers, flat colour, a bone cut edge, a hard shadow, halftone, a tilt
const S = {
  sofa: { tilt: -5, parts: [
    ["rect", { x: 14, y: 17, width: 36, height: 19, rx: 5 }, PINK, "ht-p"],
    ["rect", { x: 7, y: 27, width: 11, height: 18, rx: 4 }, DPINK],
    ["rect", { x: 46, y: 27, width: 11, height: 18, rx: 4 }, DPINK],
    ["rect", { x: 15, y: 32, width: 34, height: 10, rx: 3 }, GREEN],
    ["rect", { x: 9, y: 42, width: 46, height: 6, rx: 2 }, DPINK],
    ["rect", { x: 13, y: 48, width: 4, height: 5, rx: 1 }, BONE],
    ["rect", { x: 47, y: 48, width: 4, height: 5, rx: 1 }, BONE]] },
  live: { tilt: 4, parts: [
    ["path", { d: "M24 8l8 9 8-9" }, "none"],
    ["rect", { x: 8, y: 17, width: 48, height: 34, rx: 7 }, GREEN, "ht-g"],
    ["rect", { x: 13, y: 22, width: 29, height: 24, rx: 4 }, PINK],
    ["rect", { x: 17, y: 27, width: 10, height: 3, rx: 1.5 }, BONE],
    ["circle", { cx: 49, cy: 28, r: 3.2 }, BONE],
    ["circle", { cx: 49, cy: 39, r: 3.2 }, INK],
    ["rect", { x: 14, y: 51, width: 6, height: 4, rx: 1 }, DGREEN],
    ["rect", { x: 44, y: 51, width: 6, height: 4, rx: 1 }, DGREEN]] },
  browser: { tilt: -3, parts: [
    ["rect", { x: 7, y: 11, width: 50, height: 42, rx: 6 }, BONE],
    ["path", { d: "M7 17a6 6 0 0 1 6-6h38a6 6 0 0 1 6 6v4H7z" }, PINK],
    ["circle", { cx: 13, cy: 16, r: 1.8 }, BONE], ["circle", { cx: 19, cy: 16, r: 1.8 }, GREEN],
    ["circle", { cx: 18, cy: 31, r: 2.6 }, PINK], ["circle", { cx: 18, cy: 42, r: 2.6 }, PINK],
    ["path", { d: "M27 47l7-20h5l-7 20z" }, GREEN], ["path", { d: "M37 47l7-20h5l-7 20z" }, GREEN]] },
  store: { tilt: 5, parts: [
    ["path", { d: "M22 21v-3a10 10 0 0 1 20 0v3" }, "none"],
    ["path", { d: "M12 21h40l4 32H8z" }, PINK, "ht-p"],
    ["path", { d: "M28 28h8v11h6L32 50 22 39h6z" }, GREEN]] },
  games: { tilt: -6, parts: [
    ["path", { d: "M20 20h24a12 12 0 0 1 12 12v6a8 8 0 0 1-14.4 4.8L38.5 39h-13l-3.1 3.8A8 8 0 0 1 8 38v-6a12 12 0 0 1 12-12z" }, GREEN, "ht-g"],
    ["path", { d: "M18 25h5v4h4v5h-4v4h-5v-4h-4v-5h4z" }, BONE],
    ["circle", { cx: 42, cy: 28, r: 3.2 }, PINK], ["circle", { cx: 48, cy: 34, r: 3.2 }, PINK]] },
  files: { tilt: 3, parts: [
    ["path", { d: "M8 18a4 4 0 0 1 4-4h12l5 5h23a4 4 0 0 1 4 4v24a4 4 0 0 1-4 4H12a4 4 0 0 1-4-4z" }, DPINK],
    ["rect", { x: 14, y: 20, width: 36, height: 16, rx: 2 }, BONE],
    ["path", { d: "M8 27h48v20a4 4 0 0 1-4 4H12a4 4 0 0 1-4-4z" }, PINK, "ht-p"],
    ["rect", { x: 18, y: 35, width: 28, height: 8, rx: 2 }, GREEN]] },
  settings: { tilt: -4, parts: [
    ["rect", { x: 9, y: 9, width: 46, height: 46, rx: 8 }, "#24242C"],
    ["rect", { x: 19, y: 15, width: 2.5, height: 34, rx: 1 }, DIM], ["rect", { x: 31, y: 15, width: 2.5, height: 34, rx: 1 }, DIM],
    ["rect", { x: 43, y: 15, width: 2.5, height: 34, rx: 1 }, DIM],
    ["rect", { x: 14, y: 34, width: 12, height: 7, rx: 2 }, PINK], ["rect", { x: 26, y: 19, width: 12, height: 7, rx: 2 }, GREEN],
    ["rect", { x: 38, y: 28, width: 12, height: 7, rx: 2 }, BONE]] },
  "edge-music": { tilt: 6, parts: [
    ["rect", { x: 6, y: 15, width: 52, height: 34, rx: 5 }, PINK, "ht-p"],
    ["rect", { x: 11, y: 19, width: 42, height: 12, rx: 2 }, BONE],
    ["rect", { x: 15, y: 23, width: 24, height: 3, rx: 1.5 }, GREEN],
    ["rect", { x: 18, y: 33, width: 28, height: 10, rx: 5 }, INK],
    ["circle", { cx: 24, cy: 38, r: 3.2 }, BONE], ["circle", { cx: 40, cy: 38, r: 3.2 }, BONE],
    ["path", { d: "M16 49l3-5h26l3 5z" }, DPINK]] },
  "lj-showroom": { tilt: -4, parts: [
    ["path", { d: "M21 16h22l10 12-21 25-21-25z" }, PINK, "ht-p"],
    ["path", { d: "M22 28h20l-10 25z" }, DPINK],
    ["path", { d: "M11 28h42" }, "none"],
    ["path", { d: "M24 18h9l-3 8h-9z" }, BONE]] },
  "lj-manager": { tilt: 4, parts: [
    ["rect", { x: 13, y: 12, width: 38, height: 44, rx: 5 }, DPINK],
    ["rect", { x: 18, y: 18, width: 28, height: 33, rx: 2 }, BONE],
    ["rect", { x: 24, y: 8, width: 16, height: 8, rx: 2.5 }, GREEN],
    ["path", { d: "M22 27l3 3 5-6" }, "none"], ["path", { d: "M22 39l3 3 5-6" }, "none"],
    ["rect", { x: 33, y: 26, width: 9, height: 3, rx: 1.5 }, PINK], ["rect", { x: 33, y: 38, width: 9, height: 3, rx: 1.5 }, PINK]] },
  "lj-fragrances": { tilt: -5, parts: [
    ["rect", { x: 26, y: 13, width: 12, height: 11, rx: 2 }, BONE],
    ["rect", { x: 29, y: 22, width: 6, height: 5 }, DIM],
    ["rect", { x: 15, y: 26, width: 34, height: 29, rx: 8 }, PINK, "ht-p"],
    ["rect", { x: 22, y: 35, width: 20, height: 11, rx: 2 }, BONE],
    ["rect", { x: 26, y: 39, width: 12, height: 3, rx: 1.5 }, GREEN],
    ["circle", { cx: 46, cy: 14, r: 2.4 }, GREEN], ["circle", { cx: 52, cy: 19, r: 2 }, GREEN], ["circle", { cx: 52, cy: 10, r: 1.8 }, GREEN]] },
  edgeventure: { tilt: 3, parts: [
    ["circle", { cx: 32, cy: 32, r: 25 }, "#24242C"],
    ["path", { d: "M12 46L29 17l9 15 5-8 10 22z" }, BONE],
    ["path", { d: "M28 18h3l-5 28h-3z" }, PINK],
    ["rect", { x: 39, y: 49, width: 12, height: 4, rx: 1 }, GREEN]] },
  "gold-toilet": { tilt: -4, parts: [
    ["rect", { x: 34, y: 11, width: 17, height: 20, rx: 3 }, BONE],
    ["rect", { x: 38, y: 15, width: 7, height: 3, rx: 1.5 }, DIM],
    ["path", { d: "M12 33h40c-1.5 8-6 12-12 13v6H27v-6c-8-1.5-13-6-15-13z" }, BONE],
    ["rect", { x: 10, y: 29, width: 44, height: 7, rx: 3.5 }, PINK, "ht-p"],
    ["path", { d: "M19 14v10M14 19h10" }, "none"]] },
};
const el = (tag, a, extra) => `<${tag} ${Object.entries(a).map(([k, v]) => `${k}="${v}"`).join(" ")} ${extra}/>`;
function sticker(id, size) {
  const { tilt, parts } = S[id], u = `${id}-${size}`;
  const cut = parts.map(([t, a, fill]) => el(t, a, `fill="${fill === "none" ? "none" : BONE}" stroke="${BONE}" stroke-width="${fill === "none" ? 9 : 7}" stroke-linejoin="round" stroke-linecap="round"`)).join("");
  const shadow = parts.map(([t, a, fill]) => el(t, a, `fill="${fill === "none" ? "none" : "#000"}" stroke="#000" stroke-width="${fill === "none" ? 9 : 7}" stroke-linejoin="round" stroke-linecap="round"`)).join("");
  const art = parts.map(([t, a, fill, ht]) => el(t, a, fill === "none" ? `fill="none" stroke="${INK}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"`
    : `fill="${fill}" stroke="${INK}" stroke-width="1.6" stroke-linejoin="round"`) + (ht ? el(t, a, `fill="url(#${ht}-${u})"`) : "")).join("");
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="${size}" height="${size}">
  <defs><pattern id="ht-p-${u}" width="3" height="3" patternUnits="userSpaceOnUse" patternTransform="rotate(30)"><circle cx="1.5" cy="1.5" r=".7" fill="${DPINK}"/></pattern>
  <pattern id="ht-g-${u}" width="3" height="3" patternUnits="userSpaceOnUse" patternTransform="rotate(30)"><circle cx="1.5" cy="1.5" r=".7" fill="${DGREEN}"/></pattern></defs>
  <g transform="translate(32 32) scale(.86) rotate(${tilt}) translate(-32 -32)">
  <g transform="translate(2.2 3)" opacity=".55">${shadow}</g>${cut}${art}</g></svg>`;
}

// ---------- C. Pixel: 16 x 16, four colours and their shades, drawn square and shown crisp
const P = { b: BONE, p: PINK, P: DPINK, g: GREEN, G: DGREEN, d: DIM };
const X = {
  sofa: ["................", "................", "................", "...bbbbbbbbbb...", "...pppppppppp...", "...pppppppppp...",
         ".bbppppppppppbb.", ".PPppppppppppPP.", ".PPggggggggggPP.", ".PPggggggggggPP.", ".PPGGGGGGGGGGPP.", ".PPPPPPPPPPPPPP.",
         "..d..........d..", "................", "................", "................"],
  live: ["................", ".....b....b.....", "......b..b......", ".......bb.......", ".gggggggggggggg.", ".gPPPPPPPPPgggg.",
         ".gPpPPPPPPPgbgg.", ".gPPPPPPPPPgggg.", ".gPPbbbbbPPgpgg.", ".gPPPPPPPPPgggg.", ".gPPPPPPPPPgggg.", ".gggggggggggggg.",
         "..G..........G..", "................", "................", "................"],
  browser: ["................", "................", ".bbbbbbbbbbbbbb.", ".bpdgbbbbbbbbbb.", ".bbbbbbbbbbbbbb.", ".b............b.",
            ".b.......g..g.b.", ".b.p....g..g..b.", ".b.....g..g...b.", ".b.p..g..g....b.", ".b............b.", ".bbbbbbbbbbbbbb.",
            "................", "................", "................", "................"],
  store: ["................", "................", "................", "..PPPPPPPPPPPP..", "..pppppppppppp..", "...gggggggggg...",
          "...ggggbbgggg...", "...ggggbbgggg...", "...ggggbbgggg...", "...gbbbbbbbbg...", "...ggbbbbbbgg...", "...gggbbbbggg...",
          "...ggggbbgggg...", "...GGGGGGGGGG...", "................", "................"],
  games: ["................", "................", "................", "................", "................", "...gggg..gggg...",
          "..gggggggggggg..", ".gggbgggggggpgg.", ".ggbbbggggpgpgg.", ".gggbgggggggpgg.", ".gggggggggggggg.", ".gggg......gggg.",
          ".GGG........GGG.", "................", "................", "................"],
  files: ["................", "................", "................", "..PPPP..........", ".PPPPPPPPPPPPPP.", ".PPbbbbbbbbbbPP.",
          ".pppppppppppppp.", ".pppppppppppppp.", ".pppbbbbbbbbppp.", ".pppbggggggbppp.", ".pppbbbbbbbbppp.", ".pppppppppppppp.",
          ".PPPPPPPPPPPPPP.", "................", "................", "................"],
  settings: ["................", "................", "...d....d...d...", "...d....d...d...", "...d...ggg..d...", "...d...ggg..d...",
             "...d....d...d...", "...d....d...d...", "..ppp...d...d...", "..ppp...d...d...", "...d....d..bbb..", "...d....d..bbb..",
             "...d....d...d...", "...d....d...d...", "................", "................"],
  "edge-music": ["................", "................", "................", ".pppppppppppppp.", ".pbbbbbbbbbbbbp.", ".pbggggggggggbp.",
                 ".pbbbbbbbbbbbbp.", ".pPPPPPPPPPPPPp.", ".pPbbPPPPPPbbPp.", ".pPbbPPPPPPbbPp.", ".pPPPPPPPPPPPPp.", ".ppppPPPPPPpppp.",
                 ".pppppppppppppp.", "................", "................", "................"],
  "lj-showroom": ["................", ".............b..", "............bbb.", "....bbpppppp.b..", "...bbppppppPP...", "..pppppppppPPP..",
                  ".PPPPPPPPPPPPPP.", "..ppppPPPPpppp..", "...pppPPPPppp...", "....ppPPPPpp....", ".....pPPPPp.....", "......PPPP......",
                  ".......PP.......", "................", "................", "................"],
  "lj-manager": ["................", "......gggg......", "...ddggggggdd...", "...dbbbbbbbbd...", "...dbgbppppbd...", "...dbbbbbbbbd...",
                 "...dbgbpppbbd...", "...dbbbbbbbbd...", "...dbgbppppbd...", "...dbbbbbbbbd...", "...dbbPPPPbbd...", "...dbbbbbbbbd...",
                 "...dddddddddd...", "................", "................", "................"],
  "lj-fragrances": ["................", "............g.g.", "......bbbb..g...", "......bbbb...g.g", "......bbbb......", ".......dd.......",
                    "...pppppppppp...", "..pbppppppppPp..", "..pbppppppppPp..", "..pbpbbbbbbpPp..", "..pppbggggbpPp..", "..pppbbbbbbpPp..",
                    "..ppppppppppPp..", "...PPPPPPPPPP...", "................", "................"],
  edgeventure: ["................", "................", "................", "......b.........", ".....bpb........", ".....bpbb.......",
                "....bpbbbb......", "....bpbbbbb.b...", "...bbpbbbbbbbb..", "...bpbbbbbbbbbb.", "..bbpbbbbbbbbbb.", ".bbpbbbbbbbbbbb.",
                "................", "..........gggg..", "................", "................"],
  "gold-toilet": ["................", "................", ".........bbbbb..", ".g.......bddbb..", "ggg......bbbbb..", ".g.......bbbbb..",
                  ".........bbbbb..", ".ppppppppppppp..", ".pGGGGGGGGGGGp..", "..bbbbbbbbbbb...", "...bbbbbbbbb....", ".....bbbbbb.....",
                  ".....dddddd.....", "................", "................", "................"],
};
function pixel(id, size) {
  const rows = X[id];
  rows.forEach((r, i) => { if (r.length !== 16) throw new Error(id + " row " + i + " is " + r.length); });
  if (rows.length !== 16) throw new Error(id + " rows " + rows.length);
  let px = "", x0 = 16, x1 = -1, y0 = 16, y1 = -1;
  rows.forEach((r, y) => [...r].forEach((c, x) => {
    if (!P[c]) return;
    px += `<rect x="${x}" y="${y}" width="1.02" height="1.02" fill="${P[c]}"/>`;
    x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y);
  }));
  const dx = Math.round((15 - x1 - x0) / 2), dy = Math.round((15 - y1 - y0) / 2);   // (centred on what's drawn, in whole pixels)
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="${size}" height="${size}" shape-rendering="crispEdges">
  <rect x=".5" y=".5" width="63" height="63" rx="10" fill="#111116" stroke="${BONE}" stroke-opacity=".12"/>
  <g transform="translate(8 8) scale(3) translate(${dx} ${dy})">${px}</g></svg>`;
}
module.exports = { IDS, NAMES, phosphor, sticker, pixel, INK, BONE, GREEN, PINK };
