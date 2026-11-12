// Sofa Box icons, Drawn (2026-11): an ink tile, bone lines, a mark or two in phosphor green and hot pink. 64 x 64,
// plain paths. The first set; Phosphor draws the same lines lit like a green screen.
const INK = "#0E0E12", BONE = "#EDE6D6", GREEN = "#3DF07A", PINK = "#FF2E88";
const L = `fill="none" stroke="${BONE}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"`;
const G = c => `fill="none" stroke="${c}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"`;
const ICONS = {
  sofa: ["Sofa", `<path ${L} d="M17 31v-6a4 4 0 0 1 4-4h22a4 4 0 0 1 4 4v6"/><path ${L} d="M12 36a4 4 0 0 1 8 0v3h24v-3a4 4 0 0 1 8 0v9H12z"/><path ${L} d="M17 45v4M47 45v4"/><path ${G(PINK)} d="M24 39h16"/><rect x="29" y="12" width="7" height="4" fill="${GREEN}"/>`],
  live: ["Live TV", `<rect x="11" y="21" width="42" height="29" rx="6" ${L}/><path ${L} d="M24 12l8 8 8-8"/><path ${G(GREEN)} d="M17 30h22M17 36h18M17 42h24" opacity=".85"/><circle cx="45" cy="29" r="3.2" fill="${PINK}"/>`],
  browser: ["Browser", `<rect x="9" y="13" width="46" height="38" rx="5" ${L}/><path ${L} d="M9 21h46"/><circle cx="15" cy="17" r="1.4" fill="${BONE}"/><circle cx="20" cy="17" r="1.4" fill="${BONE}"/><circle cx="20" cy="31" r="2" fill="${GREEN}"/><circle cx="20" cy="40" r="2" fill="${GREEN}"/><path ${G(GREEN)} d="M30 44l6-16M38 44l6-16"/>`],
  store: ["Store", `<path ${L} d="M32 11l19 9.5v21L32 51 13 41.5v-21z"/><path ${L} d="M13 20.5L32 30l19-9.5M32 30v21"/><path ${G(PINK)} d="M22 31v10M18 37l4 4 4-4"/>`],
  games: ["Games", `<path ${L} d="M20 23h24a10 10 0 0 1 10 10v5a7 7 0 0 1-12.6 4.2L38.5 38h-13l-2.9 4.2A7 7 0 0 1 10 38v-5a10 10 0 0 1 10-10z"/><path ${G(GREEN)} d="M21 28v8M17 32h8"/><circle cx="41" cy="30" r="2.4" fill="${PINK}"/><circle cx="46" cy="35" r="2.4" fill="${PINK}"/>`],
  files: ["Files", `<path ${L} d="M10 20a4 4 0 0 1 4-4h11l4 5h21a4 4 0 0 1 4 4v20a4 4 0 0 1-4 4H14a4 4 0 0 1-4-4z"/><path ${G(GREEN)} d="M19 36q3.5-4 7 0t7 0"/><path ${G(PINK)} d="M38 42l6-14"/>`],
  settings: ["Settings", `<path ${L} d="M20 14v36M32 14v36M44 14v36"/><rect x="15" y="34" width="10" height="6" rx="2" fill="${INK}" stroke="${GREEN}" stroke-width="3"/><rect x="27" y="20" width="10" height="6" rx="2" fill="${INK}" stroke="${PINK}" stroke-width="3"/><rect x="39" y="28" width="10" height="6" rx="2" fill="${INK}" stroke="${BONE}" stroke-width="3"/>`],
  "edge-music": ["Edge Music", `<path ${G(GREEN)} d="M14 44V34M22 44V24M30 44V30M38 44V18M46 44V28"/><path ${G(PINK)} d="M12 50h40" /><path ${G(PINK)} d="M36 13h4M44 23h4M20 19h4"/>`],
  "lj-showroom": ["The LJ Collection", `<path ${L} d="M21 17h22l9 11-20 23-20-23z"/><path ${L} d="M12 28h40M27 17l-4 11 9 23 9-23-4-11"/><path d="M23 28h18l-9 23z" fill="${PINK}" opacity=".9"/>`],
  "lj-manager": ["LJ Collection Manager", `<rect x="14" y="12" width="36" height="42" rx="5" ${L}/><path ${L} d="M24 12v-1h16v1"/><path ${G(PINK)} d="M21 26l3-4h8l3 4-7 8z"/><path ${G(GREEN)} d="M39 25h5M39 31h5M21 42h23M21 48h15"/>`],
  "lj-fragrances": ["LJ Fragrances", `<rect x="19" y="27" width="26" height="25" rx="6" ${L}/><rect x="27" y="19" width="10" height="8" rx="1.5" ${L}/><path ${L} d="M25 19h14"/><circle cx="46" cy="14" r="1.7" fill="${PINK}"/><circle cx="51" cy="18" r="1.7" fill="${PINK}"/><circle cx="50" cy="11" r="1.7" fill="${PINK}"/><path ${G(GREEN)} d="M25 41h14"/>`],
  edgeventure: ["EdgeVenture", `<path ${L} d="M11 47L29 17l9 15 5-8 10 23z"/><path ${G(PINK)} d="M29 17l-5 30"/><rect x="40" y="50" width="11" height="3.5" fill="${GREEN}"/>`],
  "gold-toilet": ["Glossy Gold Toilet", `<rect x="36" y="13" width="14" height="17" rx="3" ${L}/><path ${L} d="M13 31h37a2 2 0 0 1 0 4c-1.5 8-6 12-12 13v5H27v-5c-8-1.5-13-7-14-17z"/><path ${G(PINK)} d="M19 18v8M15 22h8"/><path ${G(GREEN)} d="M20 38q8 4 22 0"/>`],
};
function tile(id, size) {
  const [, body] = ICONS[id];
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="${size}" height="${size}">
    <defs><pattern id="sl-${id}-${size}" width="64" height="3" patternUnits="userSpaceOnUse"><rect width="64" height="1" fill="${BONE}" opacity=".04"/></pattern></defs>
    <rect x=".5" y=".5" width="63" height="63" rx="14" fill="${INK}" stroke="${BONE}" stroke-opacity=".14"/>
    <rect x=".5" y=".5" width="63" height="63" rx="14" fill="url(#sl-${id}-${size})"/>${body}</svg>`;
}
module.exports = { ICONS, tile, INK, BONE, GREEN, PINK };
