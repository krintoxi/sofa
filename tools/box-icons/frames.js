// Sofa Box icons: a housing in each style for other companies' apps. Their own logos are never redrawn: the box puts
// each app's own icon (fetched from its site) in the screen of the housing, between two pictures made here.
//   under: what is behind the logo (the tile, its edge, its shadow), drawn as the icon's background
//   over:  what lies on it (gloss, scan lines, an outline), drawn on top
// SCREEN gives where the logo sits, as a share of the icon's square, and how round its corners are (home.css reads the
// same numbers). 512 x 512, like glossy.js.
const INK = "#0E0E12", BONE = "#EDE6D6", GREEN = "#3DF07A", PINK = "#FF2E88";
const SCREEN = { glossy: [0.12, 0.22], drawn: [0.2, 0.16], sticker: [0.15, 0.18], phosphor: [0.19, 0.12], pixel: [0.22, 0] };
const box = (style) => { const [pad, rad] = SCREEN[style], x = 512 * pad, w = 512 - 2 * x; return { x, w, r: w * rad / 2 * 2 }; };
// (CSS's border-radius: 22% of the screen's side; the same here)
const rr = (x, y, w, h, r) => `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${r}"/>`;

const FRAMES = {
  glossy() {
    const { x, w } = box("glossy"), r = w * SCREEN.glossy[1];
    return {
      under: `<defs><filter id="b" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="14"/></filter>
          <linearGradient id="rim" x1="0" y1="${x}" x2="0" y2="${x + w}" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#fff" stop-opacity=".55"/><stop offset=".5" stop-color="#8C8C99" stop-opacity=".5"/><stop offset="1" stop-color="#000" stop-opacity=".6"/></linearGradient></defs>
        <rect x="${x + 10}" y="${x + 34}" width="${w - 20}" height="${w - 14}" rx="${r}" fill="#000" opacity=".6" filter="url(#b)"/>
        <rect x="${x - 6}" y="${x - 6}" width="${w + 12}" height="${w + 12}" rx="${r + 6}" fill="url(#rim)"/>
        <rect x="${x}" y="${x}" width="${w}" height="${w}" rx="${r}" fill="#fff"/>`,
      over: `<defs><clipPath id="c">${rr(x, x, w, w, r)}</clipPath>
          <linearGradient id="g" x1="0" y1="${x}" x2="0" y2="${x + w * .5}" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#fff" stop-opacity=".62"/><stop offset="1" stop-color="#fff" stop-opacity=".1"/></linearGradient>
          <linearGradient id="d" x1="0" y1="${x + w * .6}" x2="0" y2="${x + w}" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".22"/></linearGradient></defs>
        <g clip-path="url(#c)"><rect x="${x}" y="${x}" width="${w}" height="${w}" fill="url(#d)"/>
          <path d="M${x - 10} ${x - 10}H${x + w + 10}V${x + w * .44}C${x + w * .7} ${x + w * .36} ${x + w * .3} ${x + w * .36} ${x - 10} ${x + w * .5}Z" fill="url(#g)"/></g>
        <rect x="${x + 2}" y="${x + 2}" width="${w - 4}" height="${w - 4}" rx="${r - 2}" fill="none" stroke="#fff" stroke-opacity=".45" stroke-width="3"/>
        <ellipse cx="${x + w * .24}" cy="${x + w * .12}" rx="${w * .1}" ry="${w * .035}" fill="#fff" opacity=".7"/>`
    };
  },
  drawn() {
    const { x, w } = box("drawn"), r = w * SCREEN.drawn[1], s = 8;
    return {
      under: `<defs><pattern id="sl" width="512" height="24" patternUnits="userSpaceOnUse"><rect width="512" height="${s}" fill="${BONE}" opacity=".04"/></pattern></defs>
        <rect x="4" y="4" width="504" height="504" rx="112" fill="${INK}" stroke="${BONE}" stroke-opacity=".14" stroke-width="8"/>
        <rect x="4" y="4" width="504" height="504" rx="112" fill="url(#sl)"/>
        <rect x="${x}" y="${x}" width="${w}" height="${w}" rx="${r}" fill="#fff"/>`,
      over: `<rect x="${x - 10}" y="${x - 10}" width="${w + 20}" height="${w + 20}" rx="${r + 10}" fill="none" stroke="${BONE}" stroke-width="22"/>
        <rect x="${x + w - 64}" y="${x + w + 34}" width="72" height="24" fill="${GREEN}"/><circle cx="${x + 12}" cy="${x + w + 46}" r="12" fill="${PINK}"/>`
    };
  },
  sticker() {
    const { x, w } = box("sticker"), r = w * SCREEN.sticker[1], e = 26;
    return {
      under: `<defs><pattern id="ht" width="20" height="20" patternUnits="userSpaceOnUse" patternTransform="rotate(30)"><circle cx="10" cy="10" r="4.6" fill="#B3175E"/></pattern>
          <clipPath id="c"><path d="M${x + w * .5} ${512}H${512}V${x + w * .5}Z"/></clipPath></defs>
        <rect x="${x - e + 18}" y="${x - e + 24}" width="${w + 2 * e}" height="${w + 2 * e}" rx="${r + e}" fill="#000" opacity=".55"/>
        <rect x="${x - e}" y="${x - e}" width="${w + 2 * e}" height="${w + 2 * e}" rx="${r + e}" fill="${BONE}"/>
        <g clip-path="url(#c)"><rect x="${x - e}" y="${x - e}" width="${w + 2 * e}" height="${w + 2 * e}" rx="${r + e}" fill="url(#ht)" opacity=".7"/></g>
        <rect x="${x}" y="${x}" width="${w}" height="${w}" rx="${r}" fill="#fff"/>`,
      over: `<rect x="${x}" y="${x}" width="${w}" height="${w}" rx="${r}" fill="none" stroke="${INK}" stroke-width="12"/>
        <path d="M${x - e + 10} ${x + w * .3}A${r + e} ${r + e} 0 0 1 ${x + w * .3} ${x - e + 10}" fill="none" stroke="#fff" stroke-width="10" stroke-linecap="round" opacity=".8"/>`
    };
  },
  phosphor() {
    const { x, w } = box("phosphor"), r = w * SCREEN.phosphor[1];
    return {
      under: `<defs><radialGradient id="crt" cx="50%" cy="45%" r="70%"><stop offset="0" stop-color="#0c2214"/><stop offset=".7" stop-color="#06100a"/><stop offset="1" stop-color="#020403"/></radialGradient>
          <filter id="gl" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="16"/></filter></defs>
        <rect x="8" y="8" width="496" height="496" rx="112" fill="url(#crt)" stroke="${GREEN}" stroke-opacity=".28" stroke-width="8"/>
        <rect x="${x - 8}" y="${x - 8}" width="${w + 16}" height="${w + 16}" rx="${r + 8}" fill="${GREEN}" opacity=".55" filter="url(#gl)"/>
        <rect x="${x}" y="${x}" width="${w}" height="${w}" rx="${r}" fill="#fff"/>`,
      over: `<defs><pattern id="sl" width="512" height="10" patternUnits="userSpaceOnUse"><rect width="512" height="4" fill="#000" opacity=".3"/></pattern>
          <clipPath id="c">${rr(x, x, w, w, r)}</clipPath>
          <linearGradient id="gz" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".3"/><stop offset=".45" stop-color="#fff" stop-opacity="0"/></linearGradient></defs>
        <g clip-path="url(#c)"><rect x="${x}" y="${x}" width="${w}" height="${w}" fill="url(#sl)"/><rect x="${x}" y="${x}" width="${w}" height="${w}" fill="url(#gz)"/></g>
        <rect x="${x}" y="${x}" width="${w}" height="${w}" rx="${r}" fill="none" stroke="${GREEN}" stroke-width="7" opacity=".85"/>`
    };
  },
  pixel() {
    const { x, w } = box("pixel"), p = 16;                         // (a pixel of the 32-pixel grid: 16 here)
    const steps = [[0, 0], [1, 0], [0, 1]];                         // each corner of the screen cut in two steps
    const corner = (cx, cy, sx, sy) => steps.map(([i, j]) => `<rect x="${sx > 0 ? cx + i * p : cx - (i + 1) * p}" y="${sy > 0 ? cy + j * p : cy - (j + 1) * p}" width="${p}" height="${p}" fill="#111116"/>`).join("");
    const ring = [];
    for (let i = x - p; i < x + w + p; i += p) ring.push([i, x - p], [i, x + w]);
    for (let j = x; j < x + w; j += p) ring.push([x - p, j], [x + w, j]);
    return {
      under: `<rect x="4" y="4" width="504" height="504" rx="80" fill="#111116" stroke="${BONE}" stroke-opacity=".12" stroke-width="8"/>
        <rect x="${x}" y="${x}" width="${w}" height="${w}" fill="#fff"/>`,
      over: `<g shape-rendering="crispEdges">${corner(x, x, 1, 1)}${corner(x + w, x, -1, 1)}${corner(x, x + w, 1, -1)}${corner(x + w, x + w, -1, -1)}
        ${ring.map(([i, j], n) => ((i === x - p || i === x + w) && (j === x - p || j === x + w)) ? "" : `<rect x="${i}" y="${j}" width="${p}" height="${p}" fill="${(Math.round((i + j) / p) % 2) ? BONE : "#C9C2B4"}"/>`).join("")}
        <rect x="${x + w - 2 * p}" y="${x + w + 2 * p}" width="${3 * p}" height="${p}" fill="${GREEN}"/><rect x="${x}" y="${x + w + 2 * p}" width="${p}" height="${p}" fill="${PINK}"/></g>`
    };
  }
};

function frame(style, part, size) {
  const own = `f-${style}-${part}-`;              // (many pictures share one page when they're baked: ids of their own)
  const body = FRAMES[style]()[part].replace(/id="([\w-]+)"/g, `id="${own}$1"`).replace(/url\(#([\w-]+)\)/g, `url(#${own}$1)`);
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="${size}" height="${size}">${body}</svg>`;
}
module.exports = { FRAMES, SCREEN, frame };
