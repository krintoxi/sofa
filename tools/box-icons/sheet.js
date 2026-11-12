// Every icon style on one page, one square per icon, on nothing (build.py photographs each square). Each style's row
// ends with its housing for other companies' apps: the picture behind their logo and the one on it (frames.js).
//   node sheet.js --list   the styles and apps, as JSON
//   node sheet.js 192      the page, at 192 pixels an icon
const { glossy } = require("./glossy.js");
const { tile } = require("./drawn.js");
const { IDS, phosphor, sticker, pixel } = require("./styles.js");
const { frame } = require("./frames.js");
const FRAMES = ["frame-under", "frame-over"];
const STYLES = { glossy, drawn: tile, sticker, phosphor, pixel };
if (process.argv[2] === "--list") {
  process.stdout.write(JSON.stringify({ styles: Object.keys(STYLES), ids: IDS, frames: FRAMES }));
} else {
  const n = +process.argv[2] || 192;
  const cells = Object.entries(STYLES).map(([style, draw]) => IDS.map(id => `<div>${draw(id, n)}</div>`).join("")
    + FRAMES.map(f => `<div>${frame(style, f.slice(6), n)}</div>`).join("")).join("");
  process.stdout.write(`<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;background:transparent}
    main{display:grid;grid-template-columns:repeat(${IDS.length + FRAMES.length},${n}px);grid-auto-rows:${n}px}main div{width:${n}px;height:${n}px}
    svg{display:block}</style></head><body><main>${cells}</main></body></html>`);
}
