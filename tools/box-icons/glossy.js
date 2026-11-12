// Sofa Box icons, Glossy: real-looking objects with shine and depth, in the spirit of an old Mac's desktop. 512 x 512.
// Drawn once here and baked to pictures (build.py): the box only shows pictures, so no gloss or shadow costs a Pi 3 anything.
const PINK = ["#FFB3D6", "#FF6FB1", "#FF2E88", "#C40F63", "#7E0940"];
const GREEN = ["#B9FFD4", "#6BFF9E", "#3DF07A", "#15A855", "#0A5A2E"];

function kit(p) {
  const defs = [];
  const stops = s => s.map(([o, c, a]) => `<stop offset="${o}" stop-color="${c}"${a != null ? ` stop-opacity="${a}"` : ""}/>`).join("");
  return {
    lin(n, x1, y1, x2, y2, s) { defs.push(`<linearGradient id="${p}${n}" gradientUnits="userSpaceOnUse" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}">${stops(s)}</linearGradient>`); return `url(#${p}${n})`; },
    rad(n, cx, cy, r, s, fx, fy) { defs.push(`<radialGradient id="${p}${n}" gradientUnits="userSpaceOnUse" cx="${cx}" cy="${cy}" r="${r}"${fx != null ? ` fx="${fx}" fy="${fy}"` : ""}>${stops(s)}</radialGradient>`); return `url(#${p}${n})`; },
    blur(n, sd) { defs.push(`<filter id="${p}${n}" x="-40%" y="-40%" width="180%" height="180%"><feGaussianBlur stdDeviation="${sd}"/></filter>`); return `url(#${p}${n})`; },
    clip(n, inner) { defs.push(`<clipPath id="${p}${n}">${inner}</clipPath>`); return `url(#${p}${n})`; },
    pat(n, inner, w, h) { defs.push(`<pattern id="${p}${n}" width="${w}" height="${h}" patternUnits="userSpaceOnUse">${inner}</pattern>`); return `url(#${p}${n})`; },
    defs: () => `<defs>${defs.join("")}</defs>`
  };
}
const metal = (g, n, x1, y1, x2, y2) => g.lin(n, x1, y1, x2, y2, [[0, "#FFFFFF"], [.22, "#D9D9E0"], [.48, "#8C8C99"], [.62, "#C9C9D2"], [.85, "#6A6A76"], [1, "#2E2E36"]]);
const shadow = (g, cx, cy, rx, ry, op) => `<ellipse cx="${cx}" cy="${cy}" rx="${rx}" ry="${ry}" fill="#000" opacity="${op || .55}" filter="${g.blur("sh", 16)}"/>`;
const sparkle = (x, y, s, c) => `<path d="M${x} ${y - s}C${x + s * .12} ${y - s * .12} ${x + s * .12} ${y - s * .12} ${x + s} ${y}C${x + s * .12} ${y + s * .12} ${x + s * .12} ${y + s * .12} ${x} ${y + s}C${x - s * .12} ${y + s * .12} ${x - s * .12} ${y + s * .12} ${x - s} ${y}C${x - s * .12} ${y - s * .12} ${x - s * .12} ${y - s * .12} ${x} ${y - s}z" fill="${c || "#fff"}"/>`;
function gear(cx, cy, ro, ri, teeth, rot) {
  const pts = [], step = Math.PI * 2 / teeth, a0 = (rot || 0) * Math.PI / 180;
  for (let i = 0; i < teeth; i++) {
    const a = a0 + i * step, w = step * .22;
    for (const [r, t] of [[ri, a - step * .5 + w * .2], [ro, a - w], [ro, a + w], [ri, a + step * .5 - w * .2]])
      pts.push((cx + Math.cos(t) * r).toFixed(1) + " " + (cy + Math.sin(t) * r).toFixed(1));
  }
  return "M" + pts.join("L") + "Z";
}

const GLOSSY = {
  sofa(g) {
    const back = g.lin("bk", 0, 140, 0, 310, [[0, "#FF9CCB"], [.35, PINK[2]], [1, PINK[4]]]);
    const armL = g.lin("al", 50, 0, 146, 0, [[0, "#5E062F"], [.5, PINK[3]], [.85, PINK[1]], [1, "#FF9CCB"]]);
    const armR = g.lin("ar", 366, 0, 462, 0, [[0, "#FF9CCB"], [.15, PINK[1]], [.5, PINK[3]], [1, "#5E062F"]]);
    const seat = g.lin("st", 0, 282, 0, 362, [[0, "#FFC2DF"], [.25, PINK[1]], [.7, PINK[2]], [1, PINK[3]]]);
    const base = g.lin("bs", 0, 350, 0, 410, [[0, PINK[3]], [1, "#46041F"]]);
    const leg = metal(g, "lg", 0, 396, 0, 444);
    const pillow = g.rad("pl", 168, 230, 90, [[0, GREEN[0]], [.45, GREEN[2]], [1, GREEN[4]]], 150, 210);
    const gloss = g.lin("gl", 0, 142, 0, 226, [[0, "#fff", .6], [1, "#fff", 0]]);
    const btn = g.rad("bt", 0, 0, 10, [[0, "#3A021A"], [1, PINK[4], .2]]);
    return `${shadow(g, 256, 446, 214, 22)}
      <rect x="114" y="396" width="18" height="46" rx="6" fill="${leg}"/><rect x="380" y="396" width="18" height="46" rx="6" fill="${leg}"/>
      <rect x="100" y="140" width="312" height="176" rx="58" fill="${back}"/>
      <path d="M204 168v118M308 168v118" stroke="#6E0937" stroke-width="5" stroke-linecap="round" opacity=".45"/>
      ${[[152, 206], [256, 206], [360, 206], [204, 254], [308, 254]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="8" fill="#5A0630" opacity=".75"/><circle cx="${x - 2}" cy="${y - 3}" r="3.4" fill="#FFC7E1" opacity=".75"/>`).join("")}
      <rect x="112" y="146" width="288" height="78" rx="40" fill="${gloss}"/>
      <rect x="78" y="340" width="356" height="70" rx="26" fill="${base}"/>
      <rect x="112" y="282" width="288" height="82" rx="32" fill="${seat}"/>
      <path d="M256 292v64" stroke="${PINK[4]}" stroke-width="5" opacity=".45"/>
      <rect x="128" y="289" width="256" height="20" rx="10" fill="#fff" opacity=".35"/>
      <g transform="rotate(-14 168 246)"><rect x="124" y="198" width="96" height="92" rx="30" fill="${pillow}"/>
        <rect x="134" y="205" width="74" height="24" rx="12" fill="#fff" opacity=".5"/><path d="M134 246q38 10 76 0" stroke="${GREEN[4]}" stroke-width="3" fill="none" opacity=".4"/></g>
      <rect x="50" y="232" width="96" height="176" rx="46" fill="${armL}"/>
      <rect x="366" y="232" width="96" height="176" rx="46" fill="${armR}"/>
      <ellipse cx="100" cy="250" rx="32" ry="12" fill="#fff" opacity=".42"/><ellipse cx="412" cy="250" rx="32" ry="12" fill="#fff" opacity=".42"/>`;
  },

  live(g) {
    const cab = g.lin("cb", 0, 130, 0, 420, [[0, "#5A5A68"], [.08, "#34343E"], [.55, "#1A1A22"], [1, "#08080C"]]);
    const bezel = g.lin("bz", 0, 160, 0, 392, [[0, "#050507"], [1, "#22222A"]]);
    const sky = g.lin("sk", 0, 172, 0, 300, [[0, "#14061F"], [.55, "#4A0D45"], [1, PINK[2]]]);
    const sun = g.lin("sn", 0, 226, 0, 330, [[0, "#FFE9F3"], [.45, PINK[1]], [1, PINK[3]]]);
    const floor = g.lin("fl", 0, 300, 0, 380, [[0, "#14061F"], [1, "#050507"]]);
    const knob = g.rad("kn", 396, 206, 34, [[0, "#FFFFFF"], [.35, "#C9C9D2"], [.8, "#5C5C68"], [1, "#25252C"]], 390, 198);
    const glass = g.lin("gs", 96, 172, 300, 330, [[0, "#fff", .32], [.45, "#fff", .06], [1, "#fff", 0]]);
    const scr = g.clip("sc", `<rect x="98" y="174" width="240" height="202" rx="34"/>`);
    const ant = metal(g, "an", 160, 40, 350, 140);
    const lines = [0, 1, 2, 3, 4, 5].map(i => `<rect x="80" y="${276 + i * 9}" width="300" height="${3 + i * .6}" fill="#4A0D45"/>`).join("");
    const grid = [-200, -120, -50, 0, 50, 120, 200].map(d => `<path d="M218 306L${218 + d * 1.6} 380" stroke="${GREEN[2]}" stroke-width="2" opacity=".75"/>`).join("") +
      [312, 324, 342, 366].map(y => `<path d="M90 ${y}H346" stroke="${GREEN[2]}" stroke-width="2" opacity=".7"/>`).join("");
    return `${shadow(g, 256, 438, 200, 18)}
      <path d="M256 138L172 52M256 138L342 46" stroke="${ant}" stroke-width="9" stroke-linecap="round"/>
      <circle cx="172" cy="52" r="13" fill="${PINK[2]}"/><circle cx="168" cy="48" r="5" fill="#fff" opacity=".7"/>
      <circle cx="342" cy="46" r="13" fill="${GREEN[2]}"/><circle cx="338" cy="42" r="5" fill="#fff" opacity=".7"/>
      <rect x="236" y="124" width="40" height="22" rx="8" fill="#1A1A22"/>
      <rect x="128" y="404" width="30" height="26" rx="6" fill="#121218"/><rect x="354" y="404" width="30" height="26" rx="6" fill="#121218"/>
      <rect x="56" y="132" width="400" height="284" rx="48" fill="${cab}"/>
      <rect x="62" y="138" width="388" height="26" rx="13" fill="#fff" opacity=".12"/>
      <rect x="82" y="158" width="272" height="234" rx="44" fill="${bezel}"/>
      <g clip-path="${scr}"><rect x="90" y="170" width="260" height="140" fill="${sky}"/>
        <circle cx="218" cy="300" r="74" fill="${sun}"/>${lines}
        <rect x="90" y="304" width="260" height="80" fill="${floor}"/>${grid}
        <rect x="90" y="170" width="260" height="210" fill="${g.pat("scn", `<rect width="4" height="2" fill="#000" opacity=".28"/>`, 4, 4)}"/>
        <path d="M98 174h240v80C280 230 180 220 98 260z" fill="${glass}"/></g>
      <circle cx="318" cy="196" r="8" fill="${PINK[2]}"/><circle cx="318" cy="196" r="14" fill="${PINK[2]}" opacity=".35" filter="${g.blur("lv", 4)}"/>
      <circle cx="402" cy="210" r="28" fill="${knob}"/><path d="M402 188v18" stroke="#1A1A22" stroke-width="5" stroke-linecap="round"/>
      <circle cx="402" cy="282" r="22" fill="${knob}"/><path d="M396 268l6 12" stroke="#1A1A22" stroke-width="4" stroke-linecap="round"/>
      ${[0, 1, 2, 3, 4, 5].map(i => `<rect x="378" y="${320 + i * 11}" width="48" height="5" rx="2.5" fill="#050507"/><rect x="378" y="${325 + i * 11}" width="48" height="1.5" fill="#fff" opacity=".12"/>`).join("")}`;
  },

  browser(g) {
    const globe = g.rad("gb", 256, 236, 172, [[0, GREEN[0]], [.32, GREEN[2]], [.72, GREEN[3]], [1, "#05331A"]], 200, 168);
    const clip = g.clip("gc", `<circle cx="256" cy="236" r="168"/>`);
    const ring = g.lin("rg", 40, 236, 470, 236, [[0, PINK[3]], [.35, PINK[1]], [.5, "#FFD1E6"], [.7, PINK[2]], [1, PINK[4]]]);
    const stand = metal(g, "sd", 0, 400, 0, 470);
    const hi = g.lin("hi", 0, 78, 0, 178, [[0, "#fff", .85], [.55, "#fff", .25], [1, "#fff", 0]]);
    const lat = [-120, -60, 0, 60, 120].map(d => { const w = Math.sqrt(168 * 168 - d * d); return `<ellipse cx="256" cy="${236 + d}" rx="${w.toFixed(1)}" ry="${(w * .16).toFixed(1)}" fill="none" stroke="#EDE6D6" stroke-width="3" opacity=".35"/>`; }).join("");
    const lon = [.32, .68, 1].map(k => `<ellipse cx="256" cy="236" rx="${(168 * k).toFixed(1)}" ry="168" fill="none" stroke="#EDE6D6" stroke-width="3" opacity=".3"/>`).join("") + `<path d="M256 68v336" stroke="#EDE6D6" stroke-width="3" opacity=".3"/>`;
    return `${shadow(g, 256, 466, 150, 18)}
      <ellipse cx="256" cy="452" rx="112" ry="22" fill="${stand}"/><ellipse cx="256" cy="446" rx="100" ry="15" fill="#fff" opacity=".35"/>
      <rect x="246" y="404" width="20" height="44" fill="${stand}"/>
      <g transform="rotate(-18 256 236)"><ellipse cx="256" cy="236" rx="222" ry="62" fill="none" stroke="${ring}" stroke-width="20" opacity=".55"/></g>
      <circle cx="256" cy="236" r="168" fill="${globe}"/>
      <g clip-path="${clip}">${lat}${lon}
        <path d="M176 150c30-20 70-14 84 10s-10 46-36 40-60-24-48-50z" fill="${GREEN[4]}" opacity=".45"/>
        <path d="M290 260c34-6 70 12 70 40s-30 44-54 36-40-70-16-76z" fill="${GREEN[4]}" opacity=".45"/></g>
      <g clip-path="${clip}"><ellipse cx="214" cy="128" rx="104" ry="50" transform="rotate(-16 214 128)" fill="${hi}"/>
        <path d="M120 360A168 168 0 0 0 392 340" fill="none" stroke="${GREEN[0]}" stroke-width="10" opacity=".35"/></g>
      <g transform="rotate(-18 256 236)"><path d="M34 236A222 62 0 0 0 478 236" fill="none" stroke="${ring}" stroke-width="20" stroke-linecap="round"/>
        <path d="M60 252A200 50 0 0 0 452 252" fill="none" stroke="#fff" stroke-width="4" opacity=".45"/></g>
      <g transform="translate(330 290) scale(4.2)" filter="${g.blur("cs", .35)}"><path d="M0 0v26l7-6 5 11 5-2-5-11h9z" fill="#000" opacity=".35" transform="translate(1.5 2)"/></g>
      <g transform="translate(330 290) scale(4.2)"><path d="M0 0v26l7-6 5 11 5-2-5-11h9z" fill="#fff" stroke="#0E0E12" stroke-width="1.6" stroke-linejoin="round"/></g>`;
  },

  store(g) {
    const front = g.lin("fr", 0, 170, 0, 450, [[0, "#FF8CC3"], [.3, PINK[2]], [1, PINK[4]]]);
    const side = g.lin("sd", 370, 0, 430, 0, [[0, PINK[3]], [1, "#4A0420"]]);
    const inside = g.lin("in", 0, 168, 0, 204, [[0, "#2A0213"], [1, "#5A0630"]]);
    const rope = g.lin("rp", 0, 60, 0, 200, [[0, "#FFFFFF"], [.5, "#EDE6D6"], [1, "#9C958A"]]);
    const em = g.rad("em", 234, 312, 74, [[0, GREEN[0]], [.4, GREEN[2]], [1, GREEN[4]]], 216, 286);
    const gloss = g.lin("gl", 96, 0, 200, 0, [[0, "#fff", .45], [1, "#fff", 0]]);
    return `${shadow(g, 262, 452, 190, 20)}
      <path d="M176 188C176 70 300 70 300 188" fill="none" stroke="#7E7768" stroke-width="16" stroke-linecap="round"/>
      <path d="M372 172L428 204L420 432L366 448Z" fill="${side}"/>
      <path d="M96 172H372L428 204H152Z" fill="${inside}"/>
      <path d="M96 172H372L366 448H104Z" fill="${front}"/>
      <path d="M96 172H190L184 448H104Z" fill="${gloss}"/>
      <path d="M96 172H372" stroke="#fff" stroke-width="5" opacity=".5"/>
      <path d="M150 188C150 64 264 64 264 188" fill="none" stroke="${rope}" stroke-width="16" stroke-linecap="round"/>
      <path d="M156 176C160 86 254 86 258 176" fill="none" stroke="#fff" stroke-width="4" opacity=".6"/>
      <circle cx="150" cy="190" r="10" fill="#4A0420"/><circle cx="264" cy="190" r="10" fill="#4A0420"/>
      <circle cx="234" cy="312" r="72" fill="${em}"/><circle cx="234" cy="312" r="72" fill="none" stroke="#fff" stroke-width="4" opacity=".35"/>
      <path d="M220 262h28v50h26l-40 46-40-46h26z" fill="#fff"/><path d="M220 262h28v50h26l-40 46-40-46h26z" fill="none" stroke="${GREEN[4]}" stroke-width="3" opacity=".5"/>
      <ellipse cx="220" cy="270" rx="44" ry="18" fill="#fff" opacity=".3"/>`;
  },

  games(g) {
    const BODY = "M20 23h24a10 10 0 0 1 10 10v5a7 7 0 0 1-12.6 4.2L38.5 38h-13l-2.9 4.2A7 7 0 0 1 10 38v-5a10 10 0 0 1 10-10z";
    const top = g.lin("tp", 0, 22, 0, 46, [[0, "#6A6A78"], [.22, "#2C2C35"], [.75, "#121217"], [1, "#050507"]]);
    const hi = g.lin("hi", 0, 22, 0, 31, [[0, "#fff", .55], [1, "#fff", 0]]);
    const rim = g.lin("rm", 0, 36, 0, 47, [[0, PINK[2], 0], [1, PINK[2], .55]]);
    const pad = metal(g, "pd", 0, 24, 0, 38);
    const bclip = g.clip("bc", `<path d="${BODY}"/>`);
    const b = (cx, cy, c, n) => `<circle cx="${cx}" cy="${cy + .5}" r="2.9" fill="#000" opacity=".6"/><circle cx="${cx}" cy="${cy}" r="2.9" fill="${g.rad("b" + n, cx, cy, 2.9, [[0, c[0]], [.5, c[2]], [1, c[4]]], cx - .9, cy - 1.1)}"/><ellipse cx="${cx - .6}" cy="${cy - 1.3}" rx="1.4" ry=".8" fill="#fff" opacity=".75"/>`;
    const stick = (cx, cy, n) => `<circle cx="${cx}" cy="${cy}" r="4.4" fill="#050507"/><circle cx="${cx}" cy="${cy - .4}" r="3.4" fill="${g.rad("s" + n, cx, cy, 3.4, [[0, "#55555F"], [.7, "#1A1A20"], [1, "#0A0A0D"]], cx - 1, cy - 1.4)}"/><circle cx="${cx}" cy="${cy - .4}" r="2.2" fill="none" stroke="#000" stroke-width=".5" opacity=".6"/><ellipse cx="${cx - .8}" cy="${cy - 1.7}" rx="1.5" ry=".7" fill="#fff" opacity=".35"/>`;
    return `${shadow(g, 256, 430, 214, 22)}
      <g transform="translate(-19 -36) scale(8.6)">
        <path d="${BODY}" transform="translate(0 3)" fill="#050507"/>
        <path d="${BODY}" transform="translate(0 3)" fill="${rim}"/>
        <path d="${BODY}" fill="${top}"/>
        <g clip-path="${bclip}"><rect x="8" y="22" width="48" height="8.5" fill="${hi}"/><path d="M8 44q24-5 48 0v6H8z" fill="${PINK[3]}" opacity=".25"/></g>
        <path d="M18 25h5v4h4v5h-4v4h-5v-4h-4v-5h4z" transform="translate(.3 .6)" fill="#000" opacity=".7"/>
        <path d="M18 25h5v4h4v5h-4v4h-5v-4h-4v-5h4z" fill="${pad}"/>
        <path d="M18.6 25.6h3.8v3.4" fill="none" stroke="#fff" stroke-width=".5" opacity=".7"/>
        ${b(42, 27.6, PINK, 1)}${b(47.2, 32.2, GREEN, 2)}${b(36.8, 32.2, ["#fff", "#fff", "#EDE6D6", "#C9C2B4", "#8C8478"], 3)}${b(42, 36.8, PINK, 4)}
        ${stick(26.5, 39, 1)}${stick(37.5, 39, 2)}
        <rect x="29.6" y="31.4" width="4.8" height="1.6" rx=".8" fill="#3A3A44"/>
        <circle cx="32" cy="27.4" r="1.2" fill="${GREEN[2]}"/><circle cx="32" cy="27.4" r="2.6" fill="${GREEN[2]}" opacity=".45" filter="${g.blur("led", .8)}"/></g>`;
  },

  files(g) {
    const back = g.lin("bk", 0, 110, 0, 420, [[0, "#FAF7F0"], [1, "#B9B2A4"]]);
    const front = g.lin("fr", 0, 196, 0, 430, [[0, "#FFFFFF"], [.12, "#F2EEE4"], [1, "#B5AE9F"]]);
    const usb = g.lin("us", 300, 0, 380, 0, [[0, PINK[1]], [.5, PINK[2]], [1, PINK[4]]]);
    const conn = metal(g, "cn", 0, 120, 0, 170);
    const sheet = (x, y, r) => `<g transform="rotate(${r} ${x + 90} ${y + 120})"><rect x="${x}" y="${y}" width="200" height="220" rx="8" fill="#fff"/>${[0, 1, 2, 3, 4].map(i => `<rect x="${x + 22}" y="${y + 26 + i * 22}" width="${150 - (i % 2) * 40}" height="6" rx="3" fill="#C9C2B4"/>`).join("")}</g>`;
    return `${shadow(g, 256, 438, 210, 22)}
      <path d="M58 132a22 22 0 0 1 22-22h104l30 32h218a22 22 0 0 1 22 22v236a22 22 0 0 1-22 22H80a22 22 0 0 1-22-22z" fill="${back}"/>
      ${sheet(110, 126, -6)}${sheet(160, 120, 4)}
      <g transform="rotate(24 340 200)"><rect x="318" y="118" width="44" height="40" rx="4" fill="${conn}"/><rect x="326" y="128" width="10" height="8" fill="#2E2E36"/><rect x="344" y="128" width="10" height="8" fill="#2E2E36"/>
        <rect x="306" y="154" width="68" height="140" rx="16" fill="${usb}"/><rect x="314" y="162" width="20" height="120" rx="10" fill="#fff" opacity=".35"/></g>
      <path d="M48 214a20 20 0 0 1 20-20h376a20 20 0 0 1 20 20l-14 192a24 24 0 0 1-24 22H86a24 24 0 0 1-24-22z" fill="${front}"/>
      <path d="M68 200h376" stroke="#fff" stroke-width="6" stroke-linecap="round" opacity=".9"/>
      <path d="M200 316q22-26 44 0t44 0" fill="none" stroke="${GREEN[3]}" stroke-width="16" stroke-linecap="round"/>
      <path d="M320 344l30-72" stroke="${PINK[2]}" stroke-width="16" stroke-linecap="round"/>
      <path d="M200 312q22-26 44 0t44 0" fill="none" stroke="${GREEN[1]}" stroke-width="6" stroke-linecap="round" opacity=".7"/>`;
  },

  settings(g) {
    const steel = metal(g, "st", 80, 90, 400, 420);
    const face = g.rad("fc", 214, 236, 112, [[0, "#C9C9D2"], [.75, "#8C8C99"], [.92, "#5C5C68"], [1, "#3A3A44"]], 190, 196);
    const face2 = g.rad("f2", 364, 356, 62, [[0, "#C9C9D2"], [.75, "#8C8C99"], [.92, "#5C5C68"], [1, "#3A3A44"]], 350, 336);
    const brush = (cx, cy, r) => [...Array(Math.floor(r / 5)).keys()].map(i => `<circle cx="${cx}" cy="${cy}" r="${r - i * 5}" fill="none" stroke="#fff" stroke-width="1" opacity=".1"/>`).join("");
    const holes = (cx, cy, rr, r, k, rot) => [...Array(k).keys()].map(i => { const a = (rot + i * 360 / k) * Math.PI / 180, x = cx + Math.cos(a) * rr, y = cy + Math.sin(a) * rr;
      return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${r}" fill="#18181D"/><path d="M${(x - r * .8).toFixed(1)} ${(y + r * .5).toFixed(1)}A${r} ${r} 0 0 0 ${(x + r * .8).toFixed(1)} ${(y + r * .5).toFixed(1)}" fill="none" stroke="#fff" stroke-width="2" opacity=".35"/>`; }).join("");
    const hex = (cx, cy, r) => "M" + [0, 1, 2, 3, 4, 5].map(i => { const a = (i * 60 + 30) * Math.PI / 180; return (cx + Math.cos(a) * r).toFixed(1) + " " + (cy + Math.sin(a) * r).toFixed(1); }).join("L") + "Z";
    const nut = (cx, cy, r, c, n) => `<path d="${hex(cx, cy + r * .12, r)}" fill="#000" opacity=".5"/>
      <path d="${hex(cx, cy, r)}" fill="${g.lin("n" + n, cx - r, cy - r, cx + r, cy + r, [[0, c[0]], [.35, c[1]], [.7, c[3]], [1, c[4]]])}"/>
      <path d="${hex(cx, cy, r * .78)}" fill="none" stroke="#fff" stroke-width="${r * .05}" opacity=".35"/>
      <circle cx="${cx}" cy="${cy}" r="${r * .42}" fill="${g.rad("bo" + n, cx, cy, r * .42, [[0, "#F2F2F6"], [.7, "#8C8C99"], [1, "#3A3A44"]], cx - r * .15, cy - r * .18)}"/>`;
    return `${shadow(g, 270, 448, 200, 20)}
      <path d="${gear(214, 236, 160, 128, 12, 8)}" transform="translate(7 9)" fill="#121216"/>
      <path d="${gear(214, 236, 160, 128, 12, 8)}" fill="${steel}"/>
      <circle cx="214" cy="236" r="114" fill="${face}"/>${brush(214, 236, 112)}${holes(214, 236, 76, 20, 5, -90)}
      <path d="${gear(364, 356, 92, 74, 9, 4)}" transform="translate(6 8)" fill="#121216"/>
      <path d="${gear(364, 356, 92, 74, 9, 4)}" fill="${steel}"/>
      <circle cx="364" cy="356" r="64" fill="${face2}"/>${brush(364, 356, 62)}${holes(364, 356, 42, 11, 4, -45)}
      ${nut(214, 236, 40, PINK, 1)}${nut(364, 356, 22, GREEN, 2)}
      <path d="${gear(214, 236, 160, 128, 12, 8)}" fill="none" stroke="#fff" stroke-width="3" opacity=".35"/>
      <path d="M90 170A140 140 0 0 1 250 92" fill="none" stroke="#fff" stroke-width="10" stroke-linecap="round" opacity=".35"/>`;
  },

  "edge-music"(g) {
    const disc = g.rad("dc", 256, 250, 210, [[0, "#2E2E36"], [.7, "#141418"], [1, "#050507"]]);
    const sheen = g.lin("sh2", 120, 80, 400, 420, [[0, "#fff", 0], [.42, "#fff", .32], [.5, "#fff", 0], [.58, "#fff", .22], [1, "#fff", 0]]);
    const label = g.rad("lb", 246, 236, 80, [[0, PINK[0]], [.4, PINK[1]], [1, PINK[3]]], 230, 218);
    const note = g.lin("nt", 0, 250, 0, 470, [[0, GREEN[0]], [.4, GREEN[2]], [1, GREEN[4]]]);
    const dclip = g.clip("dk", `<ellipse cx="256" cy="250" rx="206" ry="176"/>`);
    const grooves = [...Array(14).keys()].map(i => `<ellipse cx="256" cy="250" rx="${200 - i * 9}" ry="${170 - i * 7.6}" fill="none" stroke="#3A3A44" stroke-width="1.6" opacity=".7"/>`).join("");
    const eq = [[-34, 30], [-17, 46], [0, 22], [17, 52], [34, 34]].map(([dx, h]) => `<rect x="${244 + dx}" y="${262 - h}" width="10" height="${h}" rx="4" fill="${GREEN[2]}"/>`).join("");
    return `${shadow(g, 256, 440, 210, 22)}
      <ellipse cx="256" cy="266" rx="206" ry="176" fill="#050507"/>
      <ellipse cx="256" cy="250" rx="206" ry="176" fill="${disc}"/>
      <g clip-path="${dclip}">${grooves}<rect x="40" y="70" width="440" height="360" fill="${sheen}"/></g>
      <ellipse cx="256" cy="250" rx="84" ry="72" fill="${label}"/>${eq}
      <ellipse cx="256" cy="250" rx="10" ry="8" fill="#050507"/><ellipse cx="256" cy="250" rx="16" ry="13" fill="none" stroke="#C9C9D2" stroke-width="3"/>
      <ellipse cx="226" cy="204" rx="40" ry="16" fill="#fff" opacity=".35"/>
      <path d="M372 266v140" stroke="${note}" stroke-width="16" stroke-linecap="round"/>
      <path d="M372 266q50 14 58 66" fill="none" stroke="${note}" stroke-width="16" stroke-linecap="round"/>
      <ellipse cx="344" cy="410" rx="36" ry="28" transform="rotate(-24 344 410)" fill="${note}"/>
      <ellipse cx="334" cy="400" rx="14" ry="7" transform="rotate(-24 334 400)" fill="#fff" opacity=".55"/>`;
  },

  "lj-showroom"(g) {
    const girdle = [120, 188, 256, 324, 392];
    const fac = (pts, c, n) => `<path d="M${pts.join("L")}Z" fill="${c}"/>`;
    const L = (n, a, b) => g.lin(n, 0, 140, 0, 430, [[0, a], [1, b]]);
    const pav = [];
    for (let i = 0; i < 4; i++) pav.push(fac([`${girdle[i]} 212`, `${girdle[i + 1]} 212`, "256 430"], L("p" + i, i % 2 ? PINK[1] : PINK[3], i % 2 ? PINK[3] : PINK[4])));
    const crown = [
      fac(["176 146", "336 146", "324 212", "188 212"], L("c0", "#FFE3F0", PINK[1])),
      fac(["176 146", "188 212", "120 212"], L("c1", PINK[1], PINK[2])),
      fac(["336 146", "392 212", "324 212"], L("c2", PINK[2], PINK[3])),
      fac(["176 146", "256 146", "220 182"], L("c3", "#fff", PINK[0]))];
    return `${shadow(g, 256, 452, 110, 14, .45)}
      <path d="M176 146H336L392 212L256 430L120 212Z" fill="${PINK[4]}" transform="translate(4 8)" opacity=".6"/>
      ${pav.join("")}${crown.join("")}
      <path d="M120 212H392" stroke="#fff" stroke-width="4" opacity=".6"/>
      <path d="M176 146H336L392 212L256 430L120 212Z" fill="none" stroke="#fff" stroke-width="3" opacity=".45"/>
      <path d="M188 212L256 430L324 212" fill="none" stroke="#fff" stroke-width="2" opacity=".35"/>
      ${sparkle(372, 120, 30)}${sparkle(130, 300, 20)}${sparkle(410, 300, 14, GREEN[1])}`;
  },

  "lj-manager"(g) {
    const board = g.lin("bd", 0, 80, 0, 460, [[0, "#3A3A44"], [1, "#0E0E12"]]);
    const paper = g.lin("pp", 0, 130, 0, 430, [[0, "#FFFFFF"], [1, "#E4DED2"]]);
    const clip = metal(g, "cl", 0, 70, 0, 150);
    const gem = g.lin("gm", 0, 150, 0, 250, [[0, "#FFE3F0"], [.4, PINK[1]], [1, PINK[4]]]);
    const tick = (y) => `<path d="M154 ${y}l12 12 22-26" fill="none" stroke="${GREEN[3]}" stroke-width="9" stroke-linecap="round" stroke-linejoin="round"/>`;
    return `${shadow(g, 256, 456, 170, 18)}
      <rect x="110" y="88" width="292" height="364" rx="28" fill="${board}"/><rect x="116" y="94" width="280" height="30" rx="15" fill="#fff" opacity=".12"/>
      <rect x="136" y="138" width="240" height="294" rx="12" fill="${paper}"/>
      ${tick(236)}${tick(286)}${tick(336)}
      ${[236, 286, 336, 380].map((y, i) => `<rect x="${i < 3 ? 204 : 160}" y="${y - 2}" width="${i < 3 ? 140 : 180}" height="10" rx="5" fill="#C9C2B4"/>`).join("")}
      <path d="M206 72h100a14 14 0 0 1 14 14v34a12 12 0 0 1-12 12H204a12 12 0 0 1-12-12V86a14 14 0 0 1 14-14z" fill="${clip}"/>
      <circle cx="256" cy="98" r="10" fill="${PINK[2]}"/><circle cx="253" cy="95" r="4" fill="#fff" opacity=".7"/>
      <g transform="translate(300 160)"><path d="M10 0h44l14 18-36 42L-4 18z" fill="${gem}"/><path d="M-4 18h72" stroke="#fff" stroke-width="2" opacity=".6"/><path d="M10 0l12 18 10 42 10-42 12-18" fill="none" stroke="#fff" stroke-width="1.5" opacity=".45"/></g>`;
  },

  "lj-fragrances"(g) {
    const glass = g.lin("gl", 150, 0, 362, 0, [[0, "#fff", .55], [.2, "#fff", .14], [.7, "#fff", .06], [1, "#fff", .35]]);
    const liquid = g.lin("lq", 0, 240, 0, 420, [[0, PINK[1]], [.6, PINK[2]], [1, PINK[4]]]);
    const cap = g.lin("cp", 200, 0, 312, 0, [[0, "#2E2E36"], [.2, "#9A9AA6"], [.38, "#FFFFFF"], [.55, "#B5B5C0"], [1, "#2E2E36"]]);
    const mist = g.blur("ms", 10);
    return `${shadow(g, 256, 446, 150, 18)}
      <path d="M312 118L440 60L452 170Z" fill="${PINK[0]}" opacity=".35" filter="${mist}"/>
      ${[[338, 116, 5], [356, 104, 6], [362, 128, 4.5], [384, 96, 7], [392, 124, 5], [380, 148, 4], [414, 84, 6], [420, 116, 7], [412, 146, 5], [440, 102, 4.5], [444, 134, 6], [434, 70, 3.5]].map(([x, y, r], i) => `<circle cx="${x}" cy="${y}" r="${r}" fill="${i % 3 ? "#fff" : PINK[0]}" opacity="${(.9 - i * .05).toFixed(2)}"/>`).join("")}
      <rect x="226" y="176" width="60" height="28" rx="6" fill="#6A6A76"/>
      <rect x="204" y="96" width="104" height="86" rx="16" fill="${cap}"/><rect x="300" y="112" width="16" height="12" rx="4" fill="#3A3A44"/><ellipse cx="256" cy="98" rx="52" ry="10" fill="#fff" opacity=".55"/>
      <rect x="146" y="198" width="220" height="238" rx="40" fill="#fff" opacity=".1"/>
      <rect x="162" y="240" width="188" height="182" rx="28" fill="${liquid}"/>
      <ellipse cx="256" cy="242" rx="92" ry="9" fill="${PINK[0]}" opacity=".8"/>
      <rect x="146" y="198" width="220" height="238" rx="40" fill="${glass}"/>
      <rect x="146" y="198" width="220" height="238" rx="40" fill="none" stroke="#fff" stroke-width="6" opacity=".55"/>
      <rect x="164" y="214" width="22" height="196" rx="11" fill="#fff" opacity=".55"/>
      <rect x="206" y="304" width="100" height="62" rx="10" fill="#EDE6D6" opacity=".92"/>
      <rect x="222" y="322" width="68" height="8" rx="4" fill="${PINK[3]}"/><rect x="232" y="340" width="48" height="6" rx="3" fill="${GREEN[3]}"/>`;
  },

  edgeventure(g) {
    const disc = g.rad("dc", 256, 236, 210, [[0, "#3A3A44"], [.7, "#16161B"], [1, "#050507"]], 210, 170);
    const rim = metal(g, "rm", 0, 40, 0, 470);
    const peak = g.lin("pk", 0, 140, 0, 360, [[0, "#FFFFFF"], [.3, "#D9D9E0"], [.7, "#8C8C99"], [1, "#4A4A56"]]);
    const slash = g.lin("sl", 0, 150, 0, 360, [[0, PINK[0]], [.4, PINK[2]], [1, PINK[4]]]);
    const hi = g.lin("hi", 0, 60, 0, 230, [[0, "#fff", .32], [1, "#fff", 0]]);
    return `${shadow(g, 256, 456, 180, 18)}
      <circle cx="256" cy="246" r="200" fill="${rim}"/><circle cx="256" cy="246" r="184" fill="${disc}"/>
      <path d="M116 356L234 150L292 252L326 202L404 356Z" transform="translate(6 10)" fill="#050507" opacity=".8"/>
      <path d="M116 356L234 150L292 252L326 202L404 356Z" fill="${peak}"/>
      <path d="M234 150L292 252L326 202L404 356H330Z" fill="#000" opacity=".22"/>
      <path d="M234 150L246 150L210 356H192Z" fill="${slash}"/>
      <rect x="330" y="376" width="64" height="18" rx="4" fill="${GREEN[2]}"/><rect x="326" y="372" width="72" height="26" rx="6" fill="${GREEN[2]}" opacity=".35" filter="${g.blur("cr", 5)}"/>
      <ellipse cx="236" cy="150" rx="150" ry="80" fill="${hi}"/>`;
  },

  "gold-toilet"(g) {
    const pc = g.lin("pc", 0, 90, 0, 460, [[0, "#FFFFFF"], [.5, "#E6E2DA"], [1, "#A9A396"]]);
    const side = g.lin("sd", 60, 0, 420, 0, [[0, "#B5AFA2"], [.3, "#FFFFFF"], [.7, "#E6E2DA"], [1, "#9C958A"]]);
    const seat = g.lin("se", 0, 230, 0, 320, [[0, "#FF9CCB"], [.5, PINK[2]], [1, PINK[4]]]);
    const hole = g.rad("ho", 240, 272, 120, [[0, "#3A7C9A"], [.6, "#17384A"], [1, "#0A1820"]]);
    const chrome = metal(g, "cr", 0, 120, 0, 150);
    return `${shadow(g, 250, 452, 190, 20)}
      <rect x="150" y="70" width="190" height="200" rx="24" fill="${pc}"/><rect x="140" y="62" width="210" height="34" rx="14" fill="${side}"/>
      <rect x="150" y="66" width="190" height="14" rx="7" fill="#fff" opacity=".8"/>
      <rect x="290" y="112" width="40" height="14" rx="7" fill="${chrome}"/><circle cx="296" cy="119" r="10" fill="${chrome}"/>
      <path d="M190 446h120l-8-40H198z" fill="${side}"/>
      <path d="M66 278c0 90 70 140 146 140h40c80 0 168-40 168-140z" fill="${side}"/>
      <ellipse cx="242" cy="276" rx="178" ry="56" fill="${seat}"/>
      <ellipse cx="242" cy="272" rx="134" ry="36" fill="${hole}"/>
      <ellipse cx="190" cy="258" rx="54" ry="10" fill="#fff" opacity=".35"/>
      <ellipse cx="160" cy="250" rx="60" ry="10" fill="#fff" opacity=".45" transform="rotate(-6 160 250)"/>
      ${sparkle(410, 110, 28)}${sparkle(392, 176, 14, GREEN[1])}${sparkle(96, 170, 18)}`;
  }
};

function glossy(id, size) {
  const g = kit("g" + id.replace(/[^a-z]/g, "") + "_");
  const body = GLOSSY[id](g);
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="${size || 512}" height="${size || 512}">${g.defs()}${body}</svg>`;
}
module.exports = { glossy, GLOSSY };
