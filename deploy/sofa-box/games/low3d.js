/* Low3D: the Sofa Box game engine, for the box's own page games. One file, offline, no libraries, loaded like pad.js
   (<script src="../pad.js"></script><script src="../low3d.js"></script>); each game is one page on top of it.
   Made to stay smooth on a Raspberry Pi 3 (1 GB) and to look better on a Pi 4 or 5: it finds out what the browser has,
   tests it once (~2 s), starts on a quality rung to match and keeps the frame rate steady by stepping rungs while the
   game plays. 3D is WebGL 1 at a small size the browser scales up, flat-shaded meshes made in code, one draw call each,
   nothing made new while a game plays. With no WebGL, or a software one, the same world is drawn in 2D: a mode-7
   ground, the sky, and sprites baked once from the same meshes. See ENGINE.md beside it for how to make a game.

   Hardware:  probe(), bench(), plan(), LADDER, Governor, rows() and line() (what was found, to show)
   Drawing:   GL (lit and glowing meshes, a sea, a sky), Flat (the 2D renderer), Mesh (building meshes), bake() (mesh to
              sprite), Kit (trees, rocks, buildings, buoys, shadows, far hills), Chunks (a world's still things), M4
   Moving:    Path (smooth lines to race or ride along), Trail (wakes, light trails), Particles, camera(), chase(), orbit()
   The rest:  game() (the screen, tuning, the loop), begin() (a frame in either renderer), Input (controller first, the
              box's echo keys handled), Menu (screens worked with a controller), Synth (effects, a music sequencer,
              drones), U (small tools) */
(function () {
"use strict";
if (window.Low3D) return;
const TAU = Math.PI * 2;

// ---------------------------------------------------------------- what the browser gives
const NAMES = { pi3: "Raspberry Pi 3 class (VideoCore IV)", pi4: "Raspberry Pi 4 class (VideoCore VI)", pi5: "Raspberry Pi 5 class (VideoCore VII)",
  software: "software (no GPU)", none: "no WebGL", mobile: "a mobile GPU", desktop: "a desktop GPU" };
function family(r) {
  r = String(r || "").toLowerCase();
  if (!r.trim()) return "none";
  if (/swiftshader|llvmpipe|softpipe|lavapipe|software|basic render/.test(r)) return "software";
  if (/\bvc4\b|videocore iv|v3d 2\./.test(r)) return "pi3";
  if (/v3d 4\.|videocore vi\b/.test(r)) return "pi4";
  if (/v3d [7-9]\.|videocore vii/.test(r)) return "pi5";
  if (/mali|adreno|powervr|vivante|lima|panfrost|etnaviv|tegra/.test(r)) return "mobile";
  return "desktop";
}
function drop(g) { try { const l = g && g.getExtension("WEBGL_lose_context"); if (l) l.loseContext(); } catch (e) { /* gone already */ } }
function probe() {
  const ua = navigator.userAgent || "";
  const p = { webgl1: false, webgl2: false, renderer: "", vendor: "", masked: "", version: "", glsl: "", maxTex: 0, derivatives: false,
    vao: false, highp: false, caveat: false, software: false, family: "none", cores: navigator.hardwareConcurrency || 0,
    memory: navigator.deviceMemory || 0, ua, chrome: (ua.match(/Chrom(?:e|ium)\/(\d+)/) || [])[1] || "",
    arch: !/linux|android|cros/i.test(ua) ? "" : /aarch64|arm64/i.test(ua) ? "arm64" : /armv\d|\barm\b/i.test(ua) ? "arm" : /x86_64|x64/i.test(ua) ? "x86-64" : "",
    dpr: devicePixelRatio || 1, screen: screen.width + "×" + screen.height, view: innerWidth + "×" + innerHeight };
  try { const g2 = document.createElement("canvas").getContext("webgl2"); p.webgl2 = !!g2; drop(g2); } catch (e) { /* none */ }
  let gl = null;
  try {
    gl = document.createElement("canvas").getContext("webgl", { failIfMajorPerformanceCaveat: true });
    if (!gl) {                                       // only with a "major performance caveat": Chromium's software WebGL
      const c = document.createElement("canvas");
      gl = c.getContext("webgl") || c.getContext("experimental-webgl");
      p.caveat = !!gl;
    }
  } catch (e) { gl = null; }
  if (gl) {
    p.webgl1 = true;
    const dbg = gl.getExtension("WEBGL_debug_renderer_info");
    p.masked = String(gl.getParameter(gl.RENDERER) || "");
    p.renderer = String((dbg && gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL)) || p.masked);
    p.vendor = String((dbg && gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL)) || gl.getParameter(gl.VENDOR) || "");
    p.version = String(gl.getParameter(gl.VERSION) || ""); p.glsl = String(gl.getParameter(gl.SHADING_LANGUAGE_VERSION) || "");
    p.maxTex = gl.getParameter(gl.MAX_TEXTURE_SIZE) || 0;
    p.derivatives = !!gl.getExtension("OES_standard_derivatives");
    p.vao = !!gl.getExtension("OES_vertex_array_object");
    const hp = gl.getShaderPrecisionFormat(gl.FRAGMENT_SHADER, gl.HIGH_FLOAT);
    p.highp = !!(hp && hp.precision > 0);
    drop(gl);
  }
  p.family = p.webgl1 ? family(p.renderer + " " + p.vendor) : "none";
  p.software = p.family === "software" || p.caveat;
  if (p.software) p.family = "software";
  p.name = NAMES[p.family];
  p.key = [p.family, p.renderer, p.chrome, p.cores, p.memory].join("|");   // what a saved tuning belongs to
  return p;
}

// ---------------------------------------------------------------- matrices (column-major, in place)
const M4 = {
  ident(o) { o.fill(0); o[0] = o[5] = o[10] = o[15] = 1; return o; },
  persp(o, fovy, aspect, near, far) {
    const f = 1 / Math.tan(fovy / 2), nf = 1 / (near - far);
    o.fill(0); o[0] = f / aspect; o[5] = f; o[10] = (far + near) * nf; o[11] = -1; o[14] = 2 * far * near * nf; return o;
  },
  look(o, ex, ey, ez, tx, ty, tz, ux, uy, uz) {
    let zx = ex - tx, zy = ey - ty, zz = ez - tz, l = 1 / (Math.hypot(zx, zy, zz) || 1); zx *= l; zy *= l; zz *= l;
    let xx = uy * zz - uz * zy, xy = uz * zx - ux * zz, xz = ux * zy - uy * zx; l = 1 / (Math.hypot(xx, xy, xz) || 1); xx *= l; xy *= l; xz *= l;
    const yx = zy * xz - zz * xy, yy = zz * xx - zx * xz, yz = zx * xy - zy * xx;
    o[0] = xx; o[1] = yx; o[2] = zx; o[3] = 0; o[4] = xy; o[5] = yy; o[6] = zy; o[7] = 0; o[8] = xz; o[9] = yz; o[10] = zz; o[11] = 0;
    o[12] = -(xx * ex + xy * ey + xz * ez); o[13] = -(yx * ex + yy * ey + yz * ez); o[14] = -(zx * ex + zy * ey + zz * ez); o[15] = 1; return o;
  },
  mul(o, a, b) {                                     // o = a × b (o may be a or b)
    let a0, a1, a2, a3;
    for (let i = 0; i < 4; i++) {
      const b0 = b[i * 4], b1 = b[i * 4 + 1], b2 = b[i * 4 + 2], b3 = b[i * 4 + 3];
      a0 = a[0] * b0 + a[4] * b1 + a[8] * b2 + a[12] * b3; a1 = a[1] * b0 + a[5] * b1 + a[9] * b2 + a[13] * b3;
      a2 = a[2] * b0 + a[6] * b1 + a[10] * b2 + a[14] * b3; a3 = a[3] * b0 + a[7] * b1 + a[11] * b2 + a[15] * b3;
      o[i * 4] = a0; o[i * 4 + 1] = a1; o[i * 4 + 2] = a2; o[i * 4 + 3] = a3;
    }
    return o;
  },
  // turned by yaw (about y: 0 faces +z), then pitch (nose down), then roll; sized s; at x y z
  model(o, x, y, z, yaw, pitch, roll, s) {
    const cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch), cr = Math.cos(roll), sr = Math.sin(roll);
    o[0] = (cy * cr + sy * sp * sr) * s; o[1] = cp * sr * s; o[2] = (-sy * cr + cy * sp * sr) * s; o[3] = 0;
    o[4] = (-cy * sr + sy * sp * cr) * s; o[5] = cp * cr * s; o[6] = (sy * sr + cy * sp * cr) * s; o[7] = 0;
    o[8] = sy * cp * s; o[9] = -sp * s; o[10] = cy * cp * s; o[11] = 0;
    o[12] = x; o[13] = y; o[14] = z; o[15] = 1; return o;
  },
  planes(o, m) {                                     // the view's six planes (for culling), each a b c d, unit length
    for (let i = 0; i < 6; i++) {
      const r = i >> 1, s = i & 1 ? -1 : 1;
      let a = m[3] + s * m[r], b = m[7] + s * m[4 + r], c = m[11] + s * m[8 + r], d = m[15] + s * m[12 + r];
      const l = 1 / (Math.hypot(a, b, c) || 1); o[i * 4] = a * l; o[i * 4 + 1] = b * l; o[i * 4 + 2] = c * l; o[i * 4 + 3] = d * l;
    }
    return o;
  },
  sees(p, x, y, z, r) {                              // a sphere in the view?
    for (let i = 0; i < 24; i += 4) if (p[i] * x + p[i + 1] * y + p[i + 2] * z + p[i + 3] < -r) return false;
    return true;
  }
};

// ---------------------------------------------------------------- meshes, made in code
// Each vertex: position (3 floats), normal (3 bytes), color (4 bytes, the last see-through): 20 bytes.
function Mesh(cap) {
  this.cap = cap || 1024; this.n = 0;
  this.buf = new ArrayBuffer(this.cap * 20); this.f = new Float32Array(this.buf); this.i8 = new Int8Array(this.buf); this.u8 = new Uint8Array(this.buf);
  this.t = [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0];   // where the next part goes: a 3×3 (turn and size) and a move
  this.jit = 0; this.seed = 1; this.alpha = 255;
}
Mesh.prototype = {
  room(k) {
    if (this.n + k <= this.cap) return;
    while (this.n + k > this.cap) this.cap *= 2;
    const b = new ArrayBuffer(this.cap * 20); new Uint8Array(b).set(this.u8);
    this.buf = b; this.f = new Float32Array(b); this.i8 = new Int8Array(b); this.u8 = new Uint8Array(b);
  },
  // parts from now on: sized (sx sy sz), turned (yaw about y, then pitch about x: π/2 lays what's built up y along +z,
  // then roll about z), moved to x y z
  at(x, y, z, yaw, sx, sy, sz, pitch, roll) {
    yaw = yaw || 0; sx = sx == null ? 1 : sx; sy = sy == null ? sx : sy; sz = sz == null ? sx : sz;
    const cy = Math.cos(yaw), sy_ = Math.sin(yaw), cp = Math.cos(pitch || 0), sp = Math.sin(pitch || 0), cr = Math.cos(roll || 0), sr = Math.sin(roll || 0), t = this.t;
    t[0] = (cy * cr + sy_ * sp * sr) * sx; t[1] = cp * sr * sx; t[2] = (-sy_ * cr + cy * sp * sr) * sx;
    t[3] = (-cy * sr + sy_ * sp * cr) * sy; t[4] = cp * cr * sy; t[5] = (sy_ * sr + cy * sp * cr) * sy;
    t[6] = sy_ * cp * sz; t[7] = -sp * sz; t[8] = cy * cp * sz;
    t[9] = x || 0; t[10] = y || 0; t[11] = z || 0; return this;
  },
  rnd() { let a = this.seed = (this.seed + 0x6D2B79F5) | 0; a = Math.imul(a ^ (a >>> 15), 1 | a); a = (a + Math.imul(a ^ (a >>> 7), 61 | a)) ^ a; return ((a ^ (a >>> 14)) >>> 0) / 4294967296; },
  put(x, y, z, nx, ny, nz, r, g, b, a) {
    const i = this.n++, f = i * 5, o = i * 20;
    this.f[f] = x; this.f[f + 1] = y; this.f[f + 2] = z;
    this.i8[o + 12] = Math.round(nx * 127); this.i8[o + 13] = Math.round(ny * 127); this.i8[o + 14] = Math.round(nz * 127);
    this.u8[o + 16] = r; this.u8[o + 17] = g; this.u8[o + 18] = b; this.u8[o + 19] = a;
  },
  // a triangle (its corners in the part's own space), lit flat; with an "outside" point it faces away from that point
  tri(ax, ay, az, bx, by, bz, cx, cy, cz, col, ox, oy, oz) {
    const t = this.t;
    const Ax = t[0] * ax + t[3] * ay + t[6] * az + t[9], Ay = t[1] * ax + t[4] * ay + t[7] * az + t[10], Az = t[2] * ax + t[5] * ay + t[8] * az + t[11];
    let Bx = t[0] * bx + t[3] * by + t[6] * bz + t[9], By = t[1] * bx + t[4] * by + t[7] * bz + t[10], Bz = t[2] * bx + t[5] * by + t[8] * bz + t[11];
    let Cx = t[0] * cx + t[3] * cy + t[6] * cz + t[9], Cy = t[1] * cx + t[4] * cy + t[7] * cz + t[10], Cz = t[2] * cx + t[5] * cy + t[8] * cz + t[11];
    let ux = Bx - Ax, uy = By - Ay, uz = Bz - Az, vx = Cx - Ax, vy = Cy - Ay, vz = Cz - Az;
    let nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
    const l = Math.hypot(nx, ny, nz); if (l < 1e-9) return this;
    nx /= l; ny /= l; nz /= l;
    if (ox != null) {
      const Ox = t[0] * ox + t[3] * oy + t[6] * oz + t[9], Oy = t[1] * ox + t[4] * oy + t[7] * oz + t[10], Oz = t[2] * ox + t[5] * oy + t[8] * oz + t[11];
      if (nx * ((Ax + Bx + Cx) / 3 - Ox) + ny * ((Ay + By + Cy) / 3 - Oy) + nz * ((Az + Bz + Cz) / 3 - Oz) < 0) {
        nx = -nx; ny = -ny; nz = -nz;
        let q = Bx; Bx = Cx; Cx = q; q = By; By = Cy; Cy = q; q = Bz; Bz = Cz; Cz = q;
      }
    }
    let r = (col >> 16) & 255, g = (col >> 8) & 255, b = col & 255;
    if (this.jit) { const k = 1 + (this.rnd() * 2 - 1) * this.jit; r = Math.min(255, r * k) | 0; g = Math.min(255, g * k) | 0; b = Math.min(255, b * k) | 0; }
    this.room(3);
    this.put(Ax, Ay, Az, nx, ny, nz, r, g, b, this.alpha); this.put(Bx, By, Bz, nx, ny, nz, r, g, b, this.alpha); this.put(Cx, Cy, Cz, nx, ny, nz, r, g, b, this.alpha);
    return this;
  },
  quad(ax, ay, az, bx, by, bz, cx, cy, cz, dx, dy, dz, col, ox, oy, oz) {
    this.tri(ax, ay, az, bx, by, bz, cx, cy, cz, col, ox, oy, oz);
    return this.tri(ax, ay, az, cx, cy, cz, dx, dy, dz, col, ox, oy, oz);
  },
  both(ax, ay, az, bx, by, bz, cx, cy, cz, col) {     // seen from both sides (a flag, a blade of weed)
    this.tri(ax, ay, az, bx, by, bz, cx, cy, cz, col);
    return this.tri(ax, ay, az, cx, cy, cz, bx, by, bz, col);
  },
  box(x, y, z, w, h, d, col, top) {
    const x0 = x - w / 2, x1 = x + w / 2, y0 = y, y1 = y + h, z0 = z - d / 2, z1 = z + d / 2, cy = y + h / 2;
    this.quad(x0, y0, z1, x1, y0, z1, x1, y1, z1, x0, y1, z1, col, x, cy, z); this.quad(x1, y0, z0, x0, y0, z0, x0, y1, z0, x1, y1, z0, col, x, cy, z);
    this.quad(x1, y0, z1, x1, y0, z0, x1, y1, z0, x1, y1, z1, col, x, cy, z); this.quad(x0, y0, z0, x0, y0, z1, x0, y1, z1, x0, y1, z0, col, x, cy, z);
    this.quad(x0, y1, z1, x1, y1, z1, x1, y1, z0, x0, y1, z0, top == null ? col : top, x, cy, z);
    return this.quad(x0, y0, z0, x1, y0, z0, x1, y0, z1, x0, y0, z1, col, x, cy, z);
  },
  // rings of points up a stack: rings [[radius, y], ...], n sides, each band its own color; a cap on top (when it narrows to a
  // point it's a cone); jit: how uneven each point is (a rock), from the mesh's seed
  stack(rings, n, cols, capCol, jit, rot) {
    rot = rot || 0; jit = jit || 0;
    const pts = [];
    for (let k = 0; k < rings.length; k++) {
      const ring = [];
      for (let i = 0; i < n; i++) {
        const a = rot + i / n * TAU, r = rings[k][0] * (1 + (jit ? (this.rnd() * 2 - 1) * jit : 0)), y = rings[k][1] + (jit && k ? (this.rnd() * 2 - 1) * jit * rings[k][0] * 0.4 : 0);
        ring.push([Math.cos(a) * r, y, Math.sin(a) * r]);
      }
      pts.push(ring);
    }
    for (let k = 0; k + 1 < pts.length; k++) {
      const A = pts[k], B = pts[k + 1], my = (rings[k][1] + rings[k + 1][1]) / 2, col = Array.isArray(cols) ? cols[Math.min(k, cols.length - 1)] : cols;
      for (let i = 0; i < n; i++) {
        const j = (i + 1) % n;
        if (rings[k + 1][0] === 0) this.tri(A[i][0], A[i][1], A[i][2], A[j][0], A[j][1], A[j][2], B[i][0], B[i][1], B[i][2], col, 0, my, 0);
        else this.quad(A[i][0], A[i][1], A[i][2], A[j][0], A[j][1], A[j][2], B[j][0], B[j][1], B[j][2], B[i][0], B[i][1], B[i][2], col, 0, my, 0);
      }
    }
    const T = pts[pts.length - 1], tr = rings[rings.length - 1];
    if (capCol != null && tr[0] > 0) {
      let cx = 0, cy = 0, cz = 0;
      for (const p of T) { cx += p[0]; cy += p[1]; cz += p[2]; }
      cx /= n; cy /= n; cz /= n;
      for (let i = 0; i < n; i++) { const j = (i + 1) % n; this.tri(T[i][0], T[i][1], T[i][2], T[j][0], T[j][1], T[j][2], cx, cy, cz, capCol, cx, cy - 1, cz); }
    }
    return this;
  },
  ico(r, col) {                                      // a small gem (an octahedron)
    const P = [[r, 0, 0], [-r, 0, 0], [0, r * 1.3, 0], [0, -r * 1.3, 0], [0, 0, r], [0, 0, -r]];
    const F = [[0, 2, 4], [4, 2, 1], [1, 2, 5], [5, 2, 0], [4, 3, 0], [1, 3, 4], [5, 3, 1], [0, 3, 5]];
    for (const f of F) this.tri(P[f[0]][0], P[f[0]][1], P[f[0]][2], P[f[1]][0], P[f[1]][1], P[f[1]][2], P[f[2]][0], P[f[2]][1], P[f[2]][2], col, 0, 0, 0);
    return this;
  },
  disc(r, n, y, col) {                               // flat, facing up
    for (let i = 0; i < n; i++) {
      const a = i / n * TAU, b = (i + 1) / n * TAU;
      this.tri(0, y, 0, Math.cos(a) * r, y, Math.sin(a) * r, Math.cos(b) * r, y, Math.sin(b) * r, col, 0, y - 1, 0);
    }
    return this;
  },
  // the triangles as plain arrays (for baking sprites): [ax, ay, az, bx, by, bz, cx, cy, cz, nx, ny, nz, r, g, b, a] each
  tris() {
    const out = [];
    for (let i = 0; i + 2 < this.n; i += 3) {
      const t = [];
      for (let k = 0; k < 3; k++) t.push(this.f[(i + k) * 5], this.f[(i + k) * 5 + 1], this.f[(i + k) * 5 + 2]);
      const o = i * 20;
      t.push(this.i8[o + 12] / 127, this.i8[o + 13] / 127, this.i8[o + 14] / 127, this.u8[o + 16], this.u8[o + 17], this.u8[o + 18], this.u8[o + 19]);
      out.push(t);
    }
    return out;
  },
  bounds() {                                         // a sphere round it: x y z r
    if (!this.n) return [0, 0, 0, 0];
    let x0 = Infinity, y0 = Infinity, z0 = Infinity, x1 = -Infinity, y1 = -Infinity, z1 = -Infinity;
    for (let i = 0; i < this.n; i++) {
      const x = this.f[i * 5], y = this.f[i * 5 + 1], z = this.f[i * 5 + 2];
      if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; if (z < z0) z0 = z; if (z > z1) z1 = z;
    }
    const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2, cz = (z0 + z1) / 2;
    let r = 0;
    for (let i = 0; i < this.n; i++) r = Math.max(r, Math.hypot(this.f[i * 5] - cx, this.f[i * 5 + 1] - cy, this.f[i * 5 + 2] - cz));
    return [cx, cy, cz, r];
  }
};

// ---------------------------------------------------------------- the WebGL 1 renderer
const LIT_VS = `
attribute vec3 aPos; attribute vec3 aNor; attribute vec4 aCol;
uniform mat4 uVP; uniform mat4 uM; uniform vec3 uSun; uniform vec3 uSunCol; uniform vec3 uAmb; uniform vec3 uGround;
uniform vec3 uEye; uniform vec2 uFog; uniform vec4 uTint;
varying vec3 vCol; varying float vFog;
void main() {
  vec4 w = uM * vec4(aPos, 1.0);
  vec3 n = normalize((uM * vec4(aNor, 0.0)).xyz);
  float d = max(dot(n, uSun), 0.0);
  vec3 c = aCol.rgb * uTint.rgb;
  vCol = mix(c * (mix(uGround, uAmb, 0.5 + 0.5 * n.y) + uSunCol * d), c, uTint.a);
  vFog = clamp((length(w.xyz - uEye) - uFog.x) / (uFog.y - uFog.x), 0.0, 1.0);
  gl_Position = uVP * w;
}`;
const LIT_FS = `
precision mediump float;
uniform vec3 uFogCol; varying vec3 vCol; varying float vFog;
void main() { gl_FragColor = vec4(mix(vCol, uFogCol, vFog), 1.0); }`;
const GLOW_VS = `
attribute vec3 aPos; attribute vec4 aCol;
uniform mat4 uVP; uniform mat4 uM; uniform vec3 uEye; uniform vec2 uFog; uniform vec4 uTint; uniform float uPoint;
varying vec4 vCol;
void main() {
  vec4 w = uM * vec4(aPos, 1.0);
  float f = clamp((length(w.xyz - uEye) - uFog.x) / (uFog.y - uFog.x), 0.0, 1.0);
  vCol = vec4(aCol.rgb * uTint.rgb, aCol.a * uTint.a * (1.0 - f));
  gl_Position = uVP * w;
  gl_PointSize = uPoint / max(gl_Position.w, 0.5);
}`;
const GLOW_FS = `
precision mediump float;
uniform float uRound; varying vec4 vCol;
void main() {
  float a = vCol.a;
  if (uRound > 0.5) { vec2 d = gl_PointCoord - 0.5; float r = dot(d, d) * 4.0; if (r > 1.0) discard; a *= 1.0 - r * r; }
  gl_FragColor = vec4(vCol.rgb, a);
}`;
// the sea: the course's own picture laid on the water (shallows, weed, pads drawn in it), lit by the sun; with WAVES, the
// water rises and falls and each facet catches the light (flat, from the screen's derivatives)
const SEA_VS = `
attribute vec3 aPos;
uniform mat4 uVP; uniform vec3 uEye; uniform vec4 uMap; uniform float uTime; uniform float uWave;
varying vec2 vUV; varying vec3 vRel;
void main() {
  vec3 p = aPos;
#ifdef WAVES
  vec2 e = (p.xz - uMap.xy) * uMap.zw;             // (calm at the picture's edge, where the flat sea carries on)
  float edge = clamp(min(min(e.x, 1.0 - e.x), min(e.y, 1.0 - e.y)) * 12.0, 0.0, 1.0);
  p.y += (sin(p.x * 0.09 + uTime * 1.1) * 0.55 + sin(p.z * 0.071 - uTime * 0.9) * 0.45 + sin((p.x - p.z) * 0.043 + uTime * 0.6) * 0.5) * uWave * edge;
#endif
  vUV = (p.xz - uMap.xy) * uMap.zw;
  vRel = p - uEye;
  gl_Position = uVP * vec4(p, 1.0);
}`;
const SEA_FS = `
#ifdef WAVES
#extension GL_OES_standard_derivatives : enable
#endif
#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif
uniform sampler2D uTex; uniform vec3 uFogCol; uniform vec2 uFog; uniform vec3 uSun; uniform vec3 uSunCol; uniform vec3 uAmb; uniform vec3 uSkyCol;
varying vec2 vUV; varying vec3 vRel;
void main() {
  vec3 c = texture2D(uTex, vUV).rgb;
  float dist = length(vRel);
#ifdef WAVES
  vec3 n = normalize(cross(dFdx(vRel), dFdy(vRel)));
  if (n.y < 0.0) n = -n;
  vec3 v = -vRel / dist;
  float fr = pow(1.0 - max(dot(n, v), 0.0), 3.0);
  float sp = pow(max(dot(reflect(-uSun, n), v), 0.0), 120.0);
  c = mix(c * mix(vec3(1.0), uAmb + uSunCol * max(dot(n, uSun), 0.0), 0.5), uSkyCol, fr * 0.45) + uSunCol * sp * 0.45;
#else
  c = c * mix(vec3(1.0), uAmb + uSunCol * max(uSun.y, 0.0), 0.35);   // (the sea's picture is painted as it should look: lit gently)
#endif
  gl_FragColor = vec4(mix(c, uFogCol, clamp((dist - uFog.x) / (uFog.y - uFog.x), 0.0, 1.0)), 1.0);
}`;
const SKY_VS = `
attribute vec2 aXY;
uniform vec3 uF; uniform vec3 uR; uniform vec3 uU;
varying vec3 vDir;
void main() { vDir = uF + uR * aXY.x + uU * aXY.y; gl_Position = vec4(aXY, 1.0, 1.0); }`;
const SKY_FS = `
precision mediump float;
uniform vec3 uTop; uniform vec3 uHorizon; uniform vec3 uSun; uniform vec3 uSunCol; uniform vec3 uFogCol;
varying vec3 vDir;
void main() {
  vec3 d = normalize(vDir);
  vec3 c = mix(uHorizon, uTop, smoothstep(0.0, 0.55, d.y));
  c = mix(uFogCol, c, smoothstep(-0.02, 0.12, d.y));
#ifdef SUN
  float s = max(dot(d, uSun), 0.0);
  c += uSunCol * (pow(s, 600.0) * 1.2 + pow(s, 12.0) * 0.22);
#endif
  gl_FragColor = vec4(c, 1.0);
}`;

function GL(canvas, opts) {
  opts = opts || {};
  const gl = canvas.getContext("webgl", { antialias: false, alpha: false, depth: true, stencil: false, premultipliedAlpha: false,
    preserveDrawingBuffer: false, powerPreference: "high-performance" });
  if (!gl) throw new Error("no WebGL");
  this.gl = gl; this.canvas = canvas;
  this.vao = gl.getExtension("OES_vertex_array_object");
  this.derivatives = !!gl.getExtension("OES_standard_derivatives");
  const mk = (vs, fs, defs) => this.program(defs + vs, defs + fs);
  this.P = { lit: mk(LIT_VS, LIT_FS, ""), glow: mk(GLOW_VS, GLOW_FS, ""), sky: mk(SKY_VS, SKY_FS, "") };
  // the rest when first wanted (each takes a moment to make on a Pi 3): null when this GPU can't
  this.make = { sea: () => mk(SEA_VS, SEA_FS, ""), skySun: () => mk(SKY_VS, SKY_FS, "#define SUN\n"),
    seaWave: () => this.derivatives ? mk(SEA_VS, SEA_FS, "#define WAVES\n") : null };
  this.vp = new Float32Array(16); this.view = new Float32Array(16); this.proj = new Float32Array(16); this.m = new Float32Array(16);
  this.planes = new Float32Array(24); this.eye = new Float32Array(3);
  this.frame = 0; this.cur = null; this.curBuf = null; this.calls = 0; this.tris = 0;
  this.L = { sun: new Float32Array([0.4, 0.8, 0.3]), sunCol: new Float32Array([1, 0.95, 0.85]), amb: new Float32Array([0.42, 0.47, 0.55]),
    ground: new Float32Array([0.25, 0.22, 0.2]), fogCol: new Float32Array([0.7, 0.8, 0.9]), fog: new Float32Array([60, 200]),
    top: new Float32Array([0.25, 0.45, 0.8]), horizon: new Float32Array([0.7, 0.8, 0.9]) };
  const q = new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]);
  this.quad = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, this.quad); gl.bufferData(gl.ARRAY_BUFFER, q, gl.STATIC_DRAW);
  gl.enable(gl.DEPTH_TEST); gl.depthFunc(gl.LEQUAL); gl.enable(gl.CULL_FACE); gl.cullFace(gl.BACK);
  gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
}
GL.prototype = {
  prog(name) {                                       // a program, made the first time it's asked for
    if (!(name in this.P)) { try { this.P[name] = this.make[name](); } catch (e) { this.P[name] = null; } }
    return this.P[name];
  },
  can(what) { return what === "waves" ? !!this.prog("seaWave") : what === "sun" ? !!this.prog("skySun") : false; },
  program(vs, fs) {
    const gl = this.gl;
    const sh = (type, src) => {
      const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS) && !gl.isContextLost()) throw new Error(gl.getShaderInfoLog(s) || "shader");
      return s;
    };
    const p = gl.createProgram();
    gl.attachShader(p, sh(gl.VERTEX_SHADER, vs)); gl.attachShader(p, sh(gl.FRAGMENT_SHADER, fs));
    gl.bindAttribLocation(p, 0, "aPos"); gl.bindAttribLocation(p, 0, "aXY"); gl.bindAttribLocation(p, 1, "aNor"); gl.bindAttribLocation(p, 2, "aCol");
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS) && !gl.isContextLost()) throw new Error(gl.getProgramInfoLog(p) || "link");
    const u = {}, n = gl.getProgramParameter(p, gl.ACTIVE_UNIFORMS);
    for (let i = 0; i < n; i++) { const a = gl.getActiveUniform(p, i); u[a.name] = gl.getUniformLocation(p, a.name); }
    const xy = gl.getAttribLocation(p, "aXY");
    return { p, u, frame: -1, xy };
  },
  // a mesh on the GPU, with a sphere round it for culling; dynamic: room for verts, sent again each frame with update()
  upload(mesh, dynamic) {
    const gl = this.gl, buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    if (dynamic) gl.bufferData(gl.ARRAY_BUFFER, mesh.cap * 20, gl.DYNAMIC_DRAW);
    else gl.bufferData(gl.ARRAY_BUFFER, new Uint8Array(mesh.buf, 0, mesh.n * 20), gl.STATIC_DRAW);
    this.curBuf = null;
    const b = mesh.bounds(), h = { buf, n: mesh.n, x: b[0], y: b[1], z: b[2], r: b[3], vao: null };
    if (this.vao) { h.vao = this.vao.createVertexArrayOES(); this.vao.bindVertexArrayOES(h.vao); this.attribs(buf); this.vao.bindVertexArrayOES(null); }
    return h;
  },
  update(h, mesh) {                                  // a dynamic mesh's verts, again (no new memory)
    const gl = this.gl; gl.bindBuffer(gl.ARRAY_BUFFER, h.buf); this.curBuf = null;
    if (mesh.n) gl.bufferSubData(gl.ARRAY_BUFFER, 0, new Uint8Array(mesh.buf, 0, mesh.n * 20));
    h.n = mesh.n;
  },
  free(h) { if (!h) return; this.gl.deleteBuffer(h.buf); if (h.vao && this.vao) this.vao.deleteVertexArrayOES(h.vao); },
  attribs(buf) {
    const gl = this.gl;
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 20, 0);
    gl.enableVertexAttribArray(1); gl.vertexAttribPointer(1, 3, gl.BYTE, true, 20, 12);
    gl.enableVertexAttribArray(2); gl.vertexAttribPointer(2, 4, gl.UNSIGNED_BYTE, true, 20, 16);
  },
  bind(h) {
    if (this.curBuf === h) return;
    if (h.vao) this.vao.bindVertexArrayOES(h.vao);
    else { if (this.vao) this.vao.bindVertexArrayOES(null); this.attribs(h.buf); }
    this.curBuf = h;
  },
  texture(canvasOrImage, mip) {                      // a picture (a power of two on each side when mip)
    const gl = this.gl, t = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, t);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB, gl.UNSIGNED_BYTE, canvasOrImage);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    if (mip) { gl.generateMipmap(gl.TEXTURE_2D); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_NEAREST); }
    else gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    return t;
  },
  // a frame: the camera (eye, target), the field of view (radians, up and down), near and far; clears the screen
  begin(ex, ey, ez, tx, ty, tz, fov, near, far, roll) {
    const gl = this.gl, w = this.canvas.width, h = this.canvas.height;
    gl.viewport(0, 0, w, h);
    const L = this.L; gl.clearColor(L.fogCol[0], L.fogCol[1], L.fogCol[2], 1);
    gl.depthMask(true); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);   // (tiled GPUs, the Pi's: clearing is what's quick)
    const r = roll || 0;
    const th = Math.atan2(tx - ex, tz - ez);         // (roll: the camera's up leans to the screen's right)
    M4.look(this.view, ex, ey, ez, tx, ty, tz, -Math.sin(r) * Math.cos(th), Math.cos(r), Math.sin(r) * Math.sin(th));
    M4.persp(this.proj, fov, w / h, near, far);
    M4.mul(this.vp, this.proj, this.view);
    M4.planes(this.planes, this.vp);
    this.eye[0] = ex; this.eye[1] = ey; this.eye[2] = ez; this.fov = fov; this.aspect = w / h;
    this.frame++; this.cur = null; this.curBuf = null; this.calls = 0; this.tris = 0;
  },
  sees(x, y, z, r) { return M4.sees(this.planes, x, y, z, r); },
  use(P) {
    const gl = this.gl;
    if (this.cur !== P) { gl.useProgram(P.p); this.cur = P; }
    if (P.frame === this.frame) return P.u;
    P.frame = this.frame;
    const u = P.u, L = this.L;
    if (u.uVP) gl.uniformMatrix4fv(u.uVP, false, this.vp);
    if (u.uEye) gl.uniform3fv(u.uEye, this.eye);
    if (u.uFog) gl.uniform2fv(u.uFog, L.fog);
    if (u.uFogCol) gl.uniform3fv(u.uFogCol, L.fogCol);
    if (u.uSun) gl.uniform3fv(u.uSun, L.sun);
    if (u.uSunCol) gl.uniform3fv(u.uSunCol, L.sunCol);
    if (u.uAmb) gl.uniform3fv(u.uAmb, L.amb);
    if (u.uGround) gl.uniform3fv(u.uGround, L.ground);
    if (u.uSkyCol) gl.uniform3fv(u.uSkyCol, L.horizon);
    if (u.uTop) gl.uniform3fv(u.uTop, L.top);
    if (u.uHorizon) gl.uniform3fv(u.uHorizon, L.horizon);
    return u;
  },
  // a mesh, lit: m its place (a matrix, or null where it was made), tint r g b, glow: 0 lit by the sun … 1 its own colors
  lit(h, m, r, g, b, glow) {
    if (!h || !h.n) return;
    const gl = this.gl, u = this.use(this.P.lit);
    gl.uniformMatrix4fv(u.uM, false, m || IDENT);
    gl.uniform4f(u.uTint, r == null ? 1 : r, g == null ? 1 : g, b == null ? 1 : b, glow || 0);
    this.bind(h); gl.drawArrays(gl.TRIANGLES, 0, h.n); this.calls++; this.tris += h.n / 3;
  },
  // see-through: blend "add" (light: lanterns, sparks) or "mix" (shadows, wakes); points: a size, as particles
  glow(h, m, r, g, b, a, blend, points) {
    if (!h || !h.n) return;
    const gl = this.gl, u = this.use(this.P.glow);
    gl.enable(gl.BLEND); gl.depthMask(false);
    if (blend === "add") gl.blendFunc(gl.SRC_ALPHA, gl.ONE); else gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    gl.uniformMatrix4fv(u.uM, false, m || IDENT);
    gl.uniform4f(u.uTint, r, g, b, a);
    gl.uniform1f(u.uPoint, points ? points * this.canvas.height / 2 / Math.tan(this.fov / 2) : 1);
    gl.uniform1f(u.uRound, points ? 1 : 0);
    this.bind(h);
    gl.drawArrays(points ? gl.POINTS : gl.TRIANGLES, 0, h.n); this.calls++;
    gl.disable(gl.BLEND); gl.depthMask(true);
  },
  // the sea, the course's picture on it: x0 z0 where the picture starts, size how far it reaches (it carries on past it)
  sea(h, tex, x0, z0, size, t, wave) {
    if (!h || !h.n) return;
    const gl = this.gl, P = (wave > 0 && this.prog("seaWave")) || this.prog("sea"), u = this.use(P);
    gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, tex); gl.uniform1i(u.uTex, 0);
    gl.uniform4f(u.uMap, x0, z0, 1 / size, 1 / size);
    if (u.uTime) gl.uniform1f(u.uTime, t);
    if (u.uWave) gl.uniform1f(u.uWave, wave || 0);
    this.bind(h); gl.drawArrays(gl.TRIANGLES, 0, h.n); this.calls++; this.tris += h.n / 3;
  },
  // the sky, last: only where nothing else was drawn (sun: its glow, which costs a little more)
  sky(sun) {
    const gl = this.gl, P = (sun && this.prog("skySun")) || this.P.sky, u = this.use(P), v = this.view;
    const ty = Math.tan(this.fov / 2), tx = ty * this.aspect;
    gl.uniform3f(u.uF, -v[2], -v[6], -v[10]);
    gl.uniform3f(u.uR, v[0] * tx, v[4] * tx, v[8] * tx);
    gl.uniform3f(u.uU, v[1] * ty, v[5] * ty, v[9] * ty);
    if (this.vao) this.vao.bindVertexArrayOES(null);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.quad); this.curBuf = null;
    gl.disableVertexAttribArray(1); gl.disableVertexAttribArray(2);
    gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 8, 0);
    gl.depthMask(false); gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4); gl.depthMask(true); this.calls++;
  },
  // light and air: hex colors ("#rrggbb" or 0xrrggbb) and the sun's direction (towards it)
  light(o) {
    const L = this.L, set = (a, c) => { if (c == null) return; const v = typeof c === "string" ? parseInt(c.slice(1), 16) : c; a[0] = (v >> 16 & 255) / 255; a[1] = (v >> 8 & 255) / 255; a[2] = (v & 255) / 255; };
    set(L.sunCol, o.sunCol); set(L.amb, o.amb); set(L.ground, o.ground); set(L.fogCol, o.fog); set(L.top, o.top); set(L.horizon, o.horizon);
    if (o.sun) { const l = Math.hypot(o.sun[0], o.sun[1], o.sun[2]); L.sun[0] = o.sun[0] / l; L.sun[1] = o.sun[1] / l; L.sun[2] = o.sun[2] / l; }
    if (o.near != null) L.fog[0] = o.near;
    if (o.far != null) L.fog[1] = o.far;
    this.frame++;                                    // (sent again on next use)
  }
};
const IDENT = M4.ident(new Float32Array(16));

// ---------------------------------------------------------------- the 2D renderer: mode-7 ground, sky, sprites
const LE = new Uint8Array(new Uint32Array([1]).buffer)[0] === 1;
function px(r, g, b) { return LE ? (0xff000000 | (b << 16) | (g << 8) | r) >>> 0 : ((r << 24) | (g << 16) | (b << 8) | 0xff) >>> 0; }
function hexRGB(c) { const v = typeof c === "string" ? parseInt(c.slice(1), 16) : c; return [(v >> 16) & 255, (v >> 8) & 255, v & 255]; }
function Flat(canvas) {
  this.canvas = canvas;
  this.ctx = canvas.getContext("2d", { alpha: false });
  this.levels = null; this.queue = []; this.qn = 0;
  this.sky = { top: [60, 110, 200], horizon: [180, 205, 230], fog: [180, 205, 230], hill: [120, 140, 160], hills: null };
  this.fogNear = 60; this.fogFar = 200; this.outside = px(20, 60, 100);
}
Flat.prototype = {
  size(w, h) {
    if (this.w === w && this.h === h) return;
    this.canvas.width = this.w = w; this.canvas.height = this.h = h;
    this.img = this.ctx.createImageData(w, h); this.u32 = new Uint32Array(this.img.data.buffer);
    this.ctx.imageSmoothingEnabled = false;
  },
  // the ground: a picture (canvas) of the world from above, x0 z0 its corner, size its side in world units (a power of
  // two in pixels); smaller copies are made for far away (no shimmer)
  ground(canvas, x0, z0, size, outside) {
    const levels = [];
    let c = canvas;
    while (c.width >= 16) {
      const d = c.getContext("2d").getImageData(0, 0, c.width, c.height);
      levels.push({ u: new Uint32Array(d.data.buffer.slice(0)), n: c.width, shift: Math.round(Math.log2(c.width)), k: c.width / size });
      if (c.width <= 64) break;
      const s = document.createElement("canvas"); s.width = s.height = c.width >> 1;
      const g = s.getContext("2d"); g.imageSmoothingEnabled = true; g.drawImage(c, 0, 0, s.width, s.height); c = s;
    }
    this.levels = levels; this.x0 = x0; this.z0 = z0; this.gsize = size;
    if (outside != null) { const o = hexRGB(outside); this.outside = px(o[0], o[1], o[2]); }
  },
  air(o) {                                           // the sky's colors, fog, far hills ([heights by angle], color)
    if (o.top) this.sky.top = hexRGB(o.top);
    if (o.horizon) this.sky.horizon = hexRGB(o.horizon);
    if (o.fog) this.sky.fog = hexRGB(o.fog);
    if (o.hill) this.sky.hill = hexRGB(o.hill);
    if (o.hills) this.sky.hills = o.hills;
    if (o.near != null) this.fogNear = o.near;
    if (o.far != null) this.fogFar = o.far;
  },
  // draws the sky and the ground for a camera at x y(height) z, turned yaw (0 faces +z), pitched down by pitch, with a
  // field of view fov (radians, up and down)
  draw(cx, cy, cz, yaw, pitch, fov) {
    const w = this.w, h = this.h, u = this.u32, L = this.levels;
    const f = h / 2 / Math.tan(fov / 2), cp = Math.cos(pitch), sp = Math.sin(pitch);
    const fx = Math.sin(yaw), fz = Math.cos(yaw), rx = -Math.cos(yaw), rz = Math.sin(yaw);
    this.cam = { x: cx, y: cy, z: cz, fx, fz, rx, rz, f, cp, sp, hz: h / 2 - f * Math.tan(pitch), yaw };
    const sky = this.sky, fogC = sky.fog, fogPx = px(fogC[0], fogC[1], fogC[2]);
    const near = this.fogNear, far = this.fogFar;
    const horizon = Math.max(0, Math.min(h, Math.ceil(this.cam.hz)));
    for (let y = 0; y < horizon; y++) {              // the sky: a color a row
      const v = (h / 2 - y - 0.5) / f, dy = (v * cp - sp) / Math.hypot(1, v), t = Math.min(1, Math.max(0, dy / 0.55));
      const k = t * t * (3 - 2 * t), hz = Math.min(1, Math.max(0, (dy + 0.02) / 0.14));
      const r = (fogC[0] + ((sky.horizon[0] + (sky.top[0] - sky.horizon[0]) * k) - fogC[0]) * hz) | 0;
      const g = (fogC[1] + ((sky.horizon[1] + (sky.top[1] - sky.horizon[1]) * k) - fogC[1]) * hz) | 0;
      const b = (fogC[2] + ((sky.horizon[2] + (sky.top[2] - sky.horizon[2]) * k) - fogC[2]) * hz) | 0;
      u.fill(px(r, g, b), y * w, y * w + w);
    }
    if (sky.hills && horizon > 0) {                  // far hills, by the angle they're at
      const H = sky.hills, n = H.length, hc = sky.hill, hp = px(hc[0], hc[1], hc[2]);
      for (let x = 0; x < w; x++) {
        const a = yaw - Math.atan((x + 0.5 - w / 2) / f);
        let i = Math.floor(((a / TAU) % 1 + 1) % 1 * n);
        const e = H[i];                                // its height: an angle above the horizon
        const top = Math.max(0, Math.floor(h / 2 - f * Math.tan(pitch + e)));
        for (let y = top; y < horizon; y++) u[y * w + x] = hp;
      }
    }
    if (!L) { u.fill(fogPx, horizon * w); this.ctx.putImageData(this.img, 0, 0); return; }
    const x0 = this.x0, z0 = this.z0, out = this.outside, fr = fogC[0], fg = fogC[1], fb = fogC[2];
    for (let y = horizon; y < h; y++) {              // the ground: each row a line across the world
      const v = (h / 2 - y - 0.5) / f, den = sp - cp * v;
      if (den <= 1e-5) { u.fill(fogPx, y * w, y * w + w); continue; }
      const t = cy / den, D = t * (cp + sp * v), step = t / f;
      const fog = D <= near ? 0 : D >= far ? 256 : ((D - near) / (far - near) * 256) | 0;
      let i = y * w;
      if (fog >= 256) { u.fill(fogPx, i, i + w); continue; }
      let lv = 0; const tpp = step * L[0].k;
      while (lv + 1 < L.length && tpp > (2 << lv)) lv++;
      const Lv = L[lv], tex = Lv.u, n = Lv.n, sh = Lv.shift, k = Lv.k;
      let wx = (cx + fx * D + rx * step * (0.5 - w / 2) - x0) * k, wz = (cz + fz * D + rz * step * (0.5 - w / 2) - z0) * k;
      const sx = rx * step * k, sz = rz * step * k, end = i + w;
      if (fog === 0) {
        for (; i < end; i++, wx += sx, wz += sz) {
          const tx = wx | 0, tz = wz | 0;
          u[i] = (tx >>> 0) < n && (tz >>> 0) < n ? tex[(tz << sh) + tx] : out;
        }
      } else {
        const g1 = 256 - fog, ar = fr * fog, ag = fg * fog, ab = fb * fog;
        for (; i < end; i++, wx += sx, wz += sz) {
          const tx = wx | 0, tz = wz | 0, c = (tx >>> 0) < n && (tz >>> 0) < n ? tex[(tz << sh) + tx] : out;
          u[i] = LE ? (0xff000000 | ((((c >> 16 & 255) * g1 + ab) >> 8) << 16) | ((((c >> 8 & 255) * g1 + ag) >> 8) << 8) | (((c & 255) * g1 + ar) >> 8)) >>> 0
                    : c;
        }
      }
    }
    this.ctx.putImageData(this.img, 0, 0);
    this.qn = 0;
  },
  // where a point in the world falls on the screen: [x, y, scale (pixels a world unit), depth], or null behind
  project(x, y, z, o) {
    const c = this.cam, dx = x - c.x, dy = y - c.y, dz = z - c.z;
    const hd = dx * c.fx + dz * c.fz, lat = dx * c.rx + dz * c.rz;
    const d = hd * c.cp - dy * c.sp, up = hd * c.sp + dy * c.cp;
    if (d < 0.5) return null;
    o[0] = this.w / 2 + lat * c.f / d; o[1] = this.h / 2 - up * c.f / d; o[2] = c.f / d; o[3] = d;
    return o;
  },
  // a sprite to draw this frame (all drawn far to near by flush()): s from bake(), standing at x y z, size: world units a pixel of it
  sprite(s, x, y, z, scale, alpha) {
    const P = this._p || (this._p = new Float32Array(4));
    if (!this.project(x, y, z, P) || P[3] > this.fogFar) return;
    const k = P[2] * scale, w = s.c.width * k, hh = s.c.height * k, left = P[0] - s.ax * k;
    if (left + w < 0 || left > this.w || w < 0.6 || P[1] - s.ay * k > this.h) return;
    if (this.qn >= this.queue.length) this.queue.push({ s: null, x: 0, y: 0, k: 0, d: 0, a: 1, poly: null, col: "" });
    const q = this.queue[this.qn++];
    q.s = s; q.x = left; q.y = P[1] - s.ay * k; q.w = w; q.h = hh; q.d = P[3]; q.poly = null;
    const fog = P[3] <= this.fogNear ? 0 : Math.min(1, (P[3] - this.fogNear) / (this.fogFar - this.fogNear));
    q.a = (alpha == null ? 1 : alpha) * (1 - fog * fog);
  },
  // a flat four-cornered shape between world points (a banner): corners as 12 numbers
  poly(pts, col, alpha) {
    const P = this._p || (this._p = new Float32Array(4));
    if (this.qn >= this.queue.length) this.queue.push({ s: null, x: 0, y: 0, k: 0, d: 0, a: 1, poly: null, col: "" });
    const q = this.queue[this.qn];
    if (!q.poly) q.poly = new Float32Array(8);
    let d = 0;
    for (let i = 0; i < 4; i++) { if (!this.project(pts[i * 3], pts[i * 3 + 1], pts[i * 3 + 2], P)) return; q.poly[i * 2] = P[0]; q.poly[i * 2 + 1] = P[1]; d += P[3] / 4; }
    if (d > this.fogFar) return;
    this.qn++; q.s = null; q.d = d; q.col = col;
    const fog = d <= this.fogNear ? 0 : Math.min(1, (d - this.fogNear) / (this.fogFar - this.fogNear));
    q.a = (alpha == null ? 1 : alpha) * (1 - fog * fog);
  },
  flush() {
    const q = this.queue, n = this.qn, ctx = this.ctx;
    for (let i = 1; i < n; i++) {                    // far to near (an insertion sort: nearly sorted from frame to frame)
      const e = q[i]; let j = i - 1;
      while (j >= 0 && q[j].d < e.d) { q[j + 1] = q[j]; j--; }
      q[j + 1] = e;
    }
    for (let i = 0; i < n; i++) {
      const e = q[i];
      ctx.globalAlpha = e.a;
      if (e.s) ctx.drawImage(e.s.c, e.x, e.y, e.w, e.h);
      else if (e.poly) {
        const p = e.poly; ctx.fillStyle = e.col; ctx.beginPath();
        ctx.moveTo(p[0], p[1]); ctx.lineTo(p[2], p[3]); ctx.lineTo(p[4], p[5]); ctx.lineTo(p[6], p[7]); ctx.closePath(); ctx.fill();
      }
    }
    ctx.globalAlpha = 1;
    this.qn = 0;
  }
};

// a mesh drawn once into a small canvas, lit the same way as the 3D renderer: seen from yaw (0: from behind, looking
// along +z), a little from above (pitch), ppu pixels a world unit; light {sun, sunCol, amb, ground} as numbers 0..1, the sun
// as seen by the viewer (x right, y up, z away), so every sprite of a turning thing is lit alike
function bake(mesh, o) {
  o = o || {};
  const yaw = o.yaw || 0, pitch = o.pitch == null ? 0.2 : o.pitch, roll = o.roll || 0, ppu = o.ppu || 8;
  const L = o.light || { sun: [-0.45, 0.8, -0.4], sunCol: [1, 0.95, 0.85], amb: [0.42, 0.47, 0.55], ground: [0.25, 0.22, 0.2] };
  const sl = Math.hypot(L.sun[0], L.sun[1], L.sun[2]), sun = [L.sun[0] / sl, L.sun[1] / sl, L.sun[2] / sl];
  const cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch), cr = Math.cos(roll), sr = Math.sin(roll);
  // the object turned by -yaw (the viewer goes round it), its roll; then seen from slightly above
  const view = (x, y, z, out) => {
    let X = x * cr - y * sr, Y = x * sr + y * cr, Z = z;     // roll about z (its own nose)
    const x1 = X * cy - Z * sy, z1 = X * sy + Z * cy; X = x1; Z = z1;
    const y2 = Y * cp + Z * sp, z2 = Z * cp - Y * sp;      // (seen from above: the top is nearer)
    out[0] = -X; out[1] = y2; out[2] = z2; return out;   // (x flipped: +x is on the viewer's left)
  };
  const tris = mesh.tris(), P = [];
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  const a = [0, 0, 0];
  for (const t of tris) {
    const q = [];
    for (let k = 0; k < 3; k++) { view(t[k * 3], t[k * 3 + 1], t[k * 3 + 2], a); q.push(a[0], a[1], a[2]); x0 = Math.min(x0, a[0]); x1 = Math.max(x1, a[0]); y0 = Math.min(y0, a[1]); y1 = Math.max(y1, a[1]); }
    // the face's normal, turned the same way: does it face the viewer (towards -z)?
    let nx = t[9], ny = t[10], nz = t[11];
    const X = nx * cr - ny * sr, Y = nx * sr + ny * cr, Z = nz, xx = X * cy - Z * sy, zz = X * sy + Z * cy;
    const vx = -xx, vy = Y * cp + zz * sp, vz = zz * cp - Y * sp, emis = t[15] === 254;
    if (vz > 0.02 && (t[15] === 255 || emis)) continue;   // (turned away)
    const d = Math.max(0, vx * sun[0] + vy * sun[1] + vz * sun[2]), hemi = 0.5 + 0.5 * vy;
    const lr = L.ground[0] + (L.amb[0] - L.ground[0]) * hemi + L.sunCol[0] * d, lg = L.ground[1] + (L.amb[1] - L.ground[1]) * hemi + L.sunCol[1] * d,
      lb = L.ground[2] + (L.amb[2] - L.ground[2]) * hemi + L.sunCol[2] * d;
    const glow = o.glow || 0;
    // (a face made with alpha 254 glows: drawn in its own colour, unlit, so Palette.sprite keeps it full-bright)
    const r = emis ? t[12] : Math.min(255, t[12] * (lr + (1 - lr) * glow)) | 0, g = emis ? t[13] : Math.min(255, t[13] * (lg + (1 - lg) * glow)) | 0, b = emis ? t[14] : Math.min(255, t[14] * (lb + (1 - lb) * glow)) | 0;
    P.push({ q, d: (q[2] + q[5] + q[8]) / 3, col: "rgb(" + r + "," + g + "," + b + ")", a: emis ? 1 : t[15] / 255 });
  }
  P.sort((p, q) => q.d - p.d);
  const W = Math.max(1, Math.ceil((x1 - x0) * ppu) + 2), H = Math.max(1, Math.ceil((y1 - y0) * ppu) + 2);
  const c = document.createElement("canvas"); c.width = W; c.height = H;
  const g = c.getContext("2d"); g.lineJoin = "round"; g.lineWidth = 0.6;
  for (const p of P) {
    const q = p.q; g.globalAlpha = p.a; g.fillStyle = g.strokeStyle = p.col; g.beginPath();
    g.moveTo((q[0] - x0) * ppu + 1, (y1 - q[1]) * ppu + 1); g.lineTo((q[3] - x0) * ppu + 1, (y1 - q[4]) * ppu + 1); g.lineTo((q[6] - x0) * ppu + 1, (y1 - q[7]) * ppu + 1);
    g.closePath(); g.fill(); if (p.a === 1) g.stroke();
  }
  return { c, ax: (0 - x0) * ppu + 1, ay: (y1 - 0) * ppu + 1, ppu };
}

// ---------------------------------------------------------------- the quality rungs, and keeping the frame rate steady
// gl: h the height drawn (the width follows the screen), far the draw distance, waves (the sea moves), sun (its glow in the
// sky), detail (more small things, nearer than far), fps what to hold. flat: the same for the 2D renderer.
const LADDER = {
  gl: [
    { h: 144, far: 150, fps: 30, waves: 0, sun: 0, detail: 0.35, wakes: 1 },
    { h: 180, far: 170, fps: 30, waves: 0, sun: 0, detail: 0.5, wakes: 2 },
    { h: 180, far: 190, fps: 60, waves: 0, sun: 0, detail: 0.55, wakes: 2 },
    { h: 216, far: 220, fps: 60, waves: 0, sun: 1, detail: 0.65, wakes: 4 },
    { h: 270, far: 260, fps: 60, waves: 1, sun: 1, detail: 0.75, wakes: 4 },
    { h: 360, far: 320, fps: 60, waves: 1, sun: 1, detail: 0.9, wakes: 4 },
    { h: 450, far: 380, fps: 60, waves: 1, sun: 1, detail: 1, wakes: 4 },
    { h: 540, far: 440, fps: 60, waves: 1, sun: 1, detail: 1, wakes: 4 },
    { h: 720, far: 500, fps: 60, waves: 1, sun: 1, detail: 1, wakes: 4 }
  ],
  flat: [
    { h: 112, far: 150, fps: 30, detail: 0.4 },
    { h: 135, far: 170, fps: 30, detail: 0.5 },
    { h: 160, far: 190, fps: 30, detail: 0.6 },
    { h: 160, far: 200, fps: 60, detail: 0.7 },
    { h: 200, far: 240, fps: 60, detail: 0.85 },
    { h: 240, far: 280, fps: 60, detail: 1 }
  ]
};

// where to start, from what the browser is and the test: {mode, rung, top (the highest it may climb to), why}
function plan(p, b) {
  b = b || {};
  const flatTop = LADDER.flat.length - 1, glTop = LADDER.gl.length - 1;
  const flatStart = () => b.cpu == null ? 1 : b.cpu < 20 ? 4 : b.cpu < 45 ? 3 : b.cpu < 90 ? 2 : b.cpu < 160 ? 1 : 0;
  const strong = (b.draws || 0) >= 128 && (b.fill || 0) >= 8;
  if (!p.webgl1) return { mode: "flat", rung: flatStart(), top: flatTop, why: "no WebGL in this browser" };
  if (p.software && !strong) return { mode: "flat", rung: flatStart(), top: flatTop, why: "WebGL here is software (" + (p.renderer || "no GPU") + ")" };
  let rung, top, why;
  if (p.family === "pi3") { rung = 1; top = 3; why = "a Pi 3's GPU"; }
  else if (p.family === "pi4") { rung = 3; top = 5; why = "a Pi 4's GPU"; }
  else if (p.family === "pi5") { rung = 4; top = 6; why = "a Pi 5's GPU"; }
  else if (p.software) { rung = 2; top = 4; why = "fast software WebGL"; }
  else { rung = 4; top = glTop; why = p.family === "mobile" ? "a mobile GPU" : "a desktop GPU"; }
  if (b.draws != null) {                             // the test says more than the name
    const d = b.draws, f = b.fill;
    if (d < 8 || f < 0.5) { rung = 0; why += ", slow in the test"; }
    else if (d < 24 || f < 1.5) { rung = Math.min(rung, 1); why += ", modest in the test"; }
    else if (d >= 512 && f >= 16) { rung = Math.max(rung, 6); top = glTop; why += ", strong in the test"; }
    else if (d >= 256 && f >= 8) { rung = Math.max(rung, 5); top = Math.max(top, 6); why += ", good in the test"; }
    else if (d >= 96 && f >= 3) { rung = Math.max(rung, 3); top = Math.max(top, 4); }
  }
  return { mode: "gl", rung: Math.min(rung, top), top, why };
}

// a ~2 s test. First the screen's own rate (frames with nothing in them). With a renderer: draw calls of a small rock
// (196 triangles) a frame that hold 60 fps, doubling; then screens of see-through fill (at 640×360) a frame that hold
// 60 fps. Always: the time for a fixed bit of JavaScript (cpu, ms). done({cpu, draws, fill, hz, ms})
function bench(g3, done, onStep) {
  const r = { cpu: 0, draws: null, fill: null, hz: 60, ms: 0 }, t0 = performance.now();
  { // the processor: a fixed loop of float maths and array work
    const a = new Float32Array(4096); let s = 0;
    const s0 = performance.now();
    for (let k = 0; k < 600; k++) for (let i = 0; i < 4096; i++) { a[i] = a[i] * 0.999 + Math.sqrt(i + k) * 0.001; s += a[i]; }
    r.cpu = Math.round((performance.now() - s0) * 10) / 10; r.sum = s;
  }
  if (!g3) { r.ms = Math.round(performance.now() - t0); return setTimeout(() => done(r), 0); }
  const gl = g3.gl, cv = g3.canvas, ow = cv.width, oh = cv.height;
  const rock = new Mesh(); rock.seed = 7; rock.jit = 0.06;
  rock.stack([[1, 0], [0.9, 0.6], [0.55, 1.1], [0.2, 1.4]], 14, [0x8a8076, 0x9a9086, 0xaaa096], 0xb8b0a6, 0.12);
  const R = g3.upload(rock), M = new Float32Array(16);
  const sheet = new Mesh(); sheet.alpha = 26;            // (in the screen's own space: it covers all of it)
  sheet.quad(-1, -1, 0, 1, -1, 0, 1, 1, 0, -1, 1, 0, 0xffffff, 0, 0, -1);
  const S = g3.upload(sheet);
  g3.light({ fog: 0x9ab0c8, near: 400, far: 900, top: 0x5080c0, horizon: 0x9ab0c8 });
  let phase = -1, load = 0, last = 0, deltas = [], ok = 0;
  const STEP = 8;
  function scene() {
    g3.begin(0, 6, -22, 0, 0, 0, 1.0, 1, 200);
    if (phase === 0) for (let i = 0; i < load; i++) {
      const a = i * 2.399, d = 3 + Math.sqrt(i) * 1.6;
      M4.model(M, Math.cos(a) * d, 0, Math.sin(a) * d, i, 0, 0, 1); g3.lit(R, M, 1, 1, 1, 0);
    }
    if (phase === 1) { M4.ident(g3.vp); for (let i = 0; i < load; i++) g3.glow(S, IDENT, 1, 1, 1, 1, "mix"); }
    else g3.sky(false);
  }
  function next(holds) {
    if (onStep) onStep(phase, load, holds);
    const spent = performance.now() - t0;
    if (phase === -1) { phase = 0; load = 8; return; }
    if (holds) ok = load;
    if (holds && load < (phase === 0 ? 1024 : 64) && spent < (phase === 0 ? 1300 : 2400)) { load *= 2; return; }
    if (phase === 0) { r.draws = ok; phase = 1; load = 1; ok = 0; cv.width = 640; cv.height = 360; return; }
    r.fill = ok || 0.25; phase = 2;
  }
  function tick(now) {
    if (last) {
      const d = now - last; deltas.push(d);
      if (d > 150 && phase >= 0) { deltas = []; next(false); }   // (far too slow: no need to wait for more)
    }
    last = now;
    if (deltas.length >= STEP) {                       // a step: did it hold 60 fps?
      const s = deltas.slice(2).sort((a, b) => a - b), med = s[s.length >> 1];
      deltas = [];
      if (phase === -1) r.hz = Math.max(24, Math.min(240, Math.round(1000 / med)));
      next(med < Math.max(18.5, 1150 / r.hz));
    }
    if (phase === 2) return finish();
    scene(); requestAnimationFrame(tick);
  }
  function finish() {
    g3.free(R); g3.free(S); cv.width = ow; cv.height = oh;
    r.ms = Math.round(performance.now() - t0); done(r);
  }
  cv.width = 320; cv.height = 180;
  requestAnimationFrame(tick);
}

// keeps the frame rate steady. tick(now) on every animation frame says whether to draw this one (30 fps: every other one);
// after drawing, work(ms) says how long the game took. Late frames (half a frame or more) for a tenth of two seconds: a
// rung down; none at all for six seconds, with time to spare: a rung up (but never back to one that ran late).
function Governor(ladder, rung, top, change) {
  this.ladder = ladder; this.rung = rung; this.top = top == null ? ladder.length - 1 : top; this.change = change || null;
  this.last = 0; this.win = 0; this.n = 0; this.late = 0; this.workSum = 0; this.calm = 0; this.quiet = 0; this.wait = 0;
  this.fps = 0; this.shown = 0; this.frames = 0; this.fpsAt = 0; this.lock = false; this.log = [];
}
Governor.prototype = {
  get cur() { return this.ladder[this.rung]; },
  tick(now) {
    const iv = 1000 / this.ladder[this.rung].fps;
    if (this.last && now - this.last < iv - 4) return false;
    const gap = this.last ? now - this.last : iv;
    this.last = now;
    this.frames++;
    if (now - this.fpsAt >= 1000) { this.fps = Math.round(this.frames * 1000 / (now - this.fpsAt)); this.frames = 0; this.fpsAt = now; }
    if (document.hidden || gap > 400) { this.reset(now); return true; }   // (back from elsewhere: not the game's doing)
    if (now < this.wait) return true;
    if (!this.win) this.win = now;
    this.n++; if (gap > iv * 1.5) this.late++;
    if (now - this.win >= 2000) this.judge(now, iv);
    return true;
  },
  work(ms) { this.workSum += ms; },
  reset(now) { this.win = 0; this.n = 0; this.late = 0; this.workSum = 0; this.wait = now + 800; },
  hold(ms) { this.wait = performance.now() + (ms || 1500); this.win = 0; this.n = 0; this.late = 0; this.workSum = 0; },
  judge(now, iv) {
    const lateK = this.n ? this.late / this.n : 0, work = this.n ? this.workSum / this.n : 0;
    this.win = now; this.n = 0; this.late = 0; this.workSum = 0;
    if (this.lock) return;
    if (lateK > 0.1 && this.rung > 0) {
      if (this.quiet) this.top = Math.min(this.top, this.rung - 1);   // it ran late just after going up: not again
      let to = this.rung - 1, why = "late " + Math.round(lateK * 100) + "%";
      if (work > iv * 0.8) {                         // the game's own work fills the frame: a smaller picture won't help,
        const fps = this.ladder[this.rung].fps;      // fewer frames will (the best rung below at a lower rate)
        for (let r = this.rung - 1; r >= 0; r--) if (this.ladder[r].fps < fps) { to = r; why += ", busy " + work.toFixed(0) + " ms"; break; }
      }
      this.set(to, why, now);
      this.calm = 0; this.quiet = 0;
    } else if (lateK === 0 && work < iv * 0.5) {
      this.calm++;
      if (this.quiet) this.quiet--;
      if (this.calm >= 3 && this.rung < this.top) { this.set(this.rung + 1, "room to spare", now); this.calm = 0; this.quiet = 2; }
    } else { this.calm = 0; if (this.quiet) this.quiet--; }
  },
  set(r, why, now) {
    r = Math.max(0, Math.min(this.ladder.length - 1, r));
    if (r === this.rung) return;
    now = now == null ? performance.now() : now;
    this.log.push(Math.round(now / 100) / 10 + "s " + this.rung + "→" + r + " (" + why + ")");
    if (this.log.length > 12) this.log.shift();
    this.rung = r; this.wait = now + 1200;
    if (this.change) this.change(r, why);
  }
};

// what was found, as rows to show ([label, value]) and as one line to read out or photograph
function rows(p, b, pl) {
  b = b || {};
  return [
    ["GPU", p.renderer || "–"], ["Made by", p.vendor || "–"], ["What it is", p.name + (p.caveat ? " (the browser calls it slow)" : "")],
    ["WebGL", (p.webgl1 ? "1 yes" : "1 no") + " · " + (p.webgl2 ? "2 yes" : "2 no") + (p.webgl1 ? " · max texture " + p.maxTex + (p.derivatives ? " · derivatives" : "") + (p.highp ? " · highp" : "") : "")],
    ["Processor", (p.cores || "?") + " cores · " + (p.memory ? p.memory + " GB (as the browser rounds it)" : "memory not said") + (p.arch ? " · " + p.arch : "") + (p.chrome ? " · Chromium " + p.chrome : "")],
    ["Test", b.ms ? (b.draws != null ? b.draws + " draws and " + b.fill + " screens of fill at 60 fps · " : p.webgl1 && !p.software ? "" : "no GPU to test · ") + "script " + b.cpu + " ms · screen " + b.hz + " Hz · " + (b.ms / 1000).toFixed(1) + " s" : "not run yet"],
    ["Chose", pl ? (pl.mode === "gl" ? "3D" : pl.mode === "ray" ? "drawn by the processor" : "2D") + ", rung " + pl.rung + " of " + (LADDER[pl.mode].length - 1) + " (up to " + pl.top + "): " + pl.why : "–"]
  ];
}
function line(p, b, pl) {
  b = b || {};
  return [p.renderer || "no WebGL", "WebGL1 " + (p.webgl1 ? "yes" : "no") + " WebGL2 " + (p.webgl2 ? "yes" : "no") + (p.software ? " software" : ""),
    (p.cores || "?") + " cores " + (p.memory || "?") + " GB", "draws " + (b.draws == null ? "–" : b.draws) + " fill " + (b.fill == null ? "–" : b.fill),
    "cpu " + b.cpu + " ms " + b.hz + " Hz", pl ? (pl.mode === "gl" ? "3D" : pl.mode === "ray" ? "ray" : "2D") + " rung " + pl.rung + "/" + pl.top : ""].join(" | ");
}

// ================================================================ the engine's other parts: what every game here needs
// (a game is one page: its own content and rules on top of these; each part is used by Tidewing, the first one)

// ---------------------------------------------------------------- small tools
const U = {
  TAU, clamp: (v, a, b) => v < a ? a : v > b ? b : v, lerp: (a, b, t) => a + (b - a) * t,
  wrap(a) { a = (a + Math.PI) % TAU; if (a < 0) a += TAU; return a - Math.PI; },   // an angle in -π..π
  rand(a) {                                          // a seeded random (the same world from the same seed)
    return function () { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
  },
  hex: c => "#" + (c >>> 0).toString(16).padStart(6, "0"),
  rgb01: c => [((c >> 16) & 255) / 255, ((c >> 8) & 255) / 255, (c & 255) / 255],
  shade: (c, k) => (Math.min(255, ((c >> 16) & 255) * k) << 16) | (Math.min(255, ((c >> 8) & 255) * k) << 8) | Math.min(255, (c & 255) * k),
  mix: (a, b, t) => (Math.round(((a >> 16) & 255) + ((((b >> 16) & 255) - ((a >> 16) & 255)) * t)) << 16) |
    (Math.round(((a >> 8) & 255) + ((((b >> 8) & 255) - ((a >> 8) & 255)) * t)) << 8) | Math.round((a & 255) + (((b & 255) - (a & 255)) * t)),
  esc: s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]),
  time: t => !isFinite(t) || t >= 1e8 ? "–" : Math.floor(t / 60) + ":" + (t % 60).toFixed(1).padStart(4, "0"),
  ord: n => n + (n % 100 >= 11 && n % 100 <= 13 ? "th" : n % 10 === 1 ? "st" : n % 10 === 2 ? "nd" : n % 10 === 3 ? "rd" : "th")
};
// turns everything built so far about a pivot (ox oy oz): yaw, then pitch (nose down), then roll; normals too. With
// meshes for parts joined after, that's a body that leans, falls or lies down (parts that move together)
Mesh.prototype.turn = function (yaw, pitch, roll, ox, oy, oz) {
  ox = ox || 0; oy = oy || 0; oz = oz || 0;
  const M = M4.model(new Float32Array(16), 0, 0, 0, yaw || 0, pitch || 0, roll || 0, 1), f = this.f, i8 = this.i8;
  for (let i = 0; i < this.n; i++) {
    const x = f[i * 5] - ox, y = f[i * 5 + 1] - oy, z = f[i * 5 + 2] - oz, o = i * 20;
    f[i * 5] = M[0] * x + M[4] * y + M[8] * z + ox; f[i * 5 + 1] = M[1] * x + M[5] * y + M[9] * z + oy; f[i * 5 + 2] = M[2] * x + M[6] * y + M[10] * z + oz;
    const nx = i8[o + 12], ny = i8[o + 13], nz = i8[o + 14];
    i8[o + 12] = Math.round(M[0] * nx + M[4] * ny + M[8] * nz); i8[o + 13] = Math.round(M[1] * nx + M[5] * ny + M[9] * nz); i8[o + 14] = Math.round(M[2] * nx + M[6] * ny + M[10] * nz);
  }
  return this;
};
Mesh.join = function (list) {                      // several meshes as one
  const out = new Mesh(list.reduce((a, m) => a + m.n, 0) + 3);
  for (const m of list) { out.room(m.n); out.u8.set(new Uint8Array(m.buf, 0, m.n * 20), out.n * 20); out.n += m.n; }
  return out;
};

// ---------------------------------------------------------------- a kit of low-poly things, put into a mesh where it's
// placed (m.at() first, or the x y z given): trees, rocks, buildings, buoys, a soft round shadow
const Kit = {
  palm(m, x, y, z, s, trunk, leaf) {
    m.at(x, y, z, m.rnd() * TAU, s);
    m.stack([[0.35, 0], [0.25, 5]], 5, trunk, null);
    for (let k = 0; k < 6; k++) { const b = k / 6 * TAU; m.both(0, 5, 0, Math.cos(b) * 3.2, 4.0, Math.sin(b) * 3.2, Math.cos(b + 0.4) * 2.4, 4.6, Math.sin(b + 0.4) * 2.4, leaf); }
  },
  pine(m, x, y, z, s, trunk, leaf) {
    m.at(x, y, z, m.rnd() * TAU, s);
    m.stack([[0.3, 0], [0.25, 1.5]], 5, trunk, null);
    m.stack([[2.2, 1.4], [0, 4.6]], 7, leaf); m.stack([[1.6, 3.4], [0, 6.4]], 7, shadeK(leaf, 1.1));
  },
  // a rock or crag: radius r, height h, colors low to high (3), its top; uneven by the mesh's seed
  rock(m, x, z, r, h, cols, top, rough) {
    m.at(x, 0, z, m.rnd() * TAU);
    m.stack([[r, -1], [r * 0.9, h * 0.35], [r * 0.6, h * 0.75], [r * 0.25, h]], 7, cols, top, rough == null ? 0.18 : rough);
  },
  columns(m, x, z, r, h, cols, top, rnd) {           // basalt: hexagonal columns of different heights
    const n = 5 + ((rnd() * 5) | 0);
    for (let i = 0; i < n; i++) {
      const a = rnd() * TAU, d = rnd() * r * 0.7, cr = r * (0.22 + rnd() * 0.18), ch = h * (0.35 + rnd() * 0.65);
      m.at(x + Math.cos(a) * d, 0, z + Math.sin(a) * d, rnd());
      m.stack([[cr, -1], [cr, ch]], 6, cols[i % cols.length], top);
    }
  },
  hut(m, x, y, z, yaw, wall, roof, lamps, light) {
    m.at(x, y, z, yaw); m.box(0, 0, 0, 5, 3, 4, wall);
    m.quad(-2.8, 3, 2.2, 2.8, 3, 2.2, 2.8, 5, 0, -2.8, 5, 0, roof, 0, 0, 0); m.quad(2.8, 3, -2.2, -2.8, 3, -2.2, -2.8, 5, 0, 2.8, 5, 0, roof, 0, 0, 0);
    m.tri(2.5, 3, 2.0, 2.5, 3, -2.0, 2.5, 5, 0, shadeK(wall, 0.85), 0, 3, 0); m.tri(-2.5, 3, 2.0, -2.5, 3, -2.0, -2.5, 5, 0, shadeK(wall, 0.85), 0, 3, 0);
    if (lamps) { lamps.at(x, y, z, yaw); lamps.box(0.8, 1.2, 2.02, 1, 0.9, 0.05, light || 0xffd890); }
  },
  lighthouse(m, x, y, z, lamps) {
    m.at(x, y, z); m.stack([[2.6, 0], [2.2, 6], [1.9, 12], [1.7, 16]], 8, [0xf2efe8, 0xd84a3e, 0xf2efe8], 0x3a3a44);
    m.at(x, y + 16, z); m.stack([[1.5, 0], [1.5, 1.6]], 8, 0xffe9a8, null); m.stack([[1.9, 1.6], [0, 3.2]], 8, 0x3a3a44);
    if (lamps) { lamps.at(x, y + 16, z); lamps.stack([[1.2, 0.1], [1.2, 1.5]], 8, 0xfff0b0, 0xfff0b0); }
  },
  buoy(m, x, z, a, b, lamps, light) {                // a striped float with a pole (a lamp on top at night)
    m.at(x, 0, z);
    m.stack([[0.95, -0.6], [0.95, 0.5], [0.85, 1.2], [0.6, 1.9], [0.2, 2.6]], 8, [a, b, a, b], null);
    m.box(0, 2.4, 0, 0.22, 4.4, 0.22, 0x4a4f58);
    if (lamps && light) { lamps.at(x, 0, z); lamps.box(0, 6.7, 0, 0.6, 0.6, 0.6, light); }
  },
  shadow(sx, sz) {                                   // a flat oval to draw dark and see-through under something
    const m = new Mesh(64); m.at(0, 0, 0, 0, sx || 1, 1, sz || sx || 1); m.disc(1, 12, 0.05, 0x000000); return m;
  },
  hills(list, color) {                               // far hills or mountains round the world: [{a (angle), d, r, h, seed}]
    const m = new Mesh(4096);
    for (const hl of list) {
      m.seed = hl.seed; m.jit = 0.08;
      m.at(Math.sin(hl.a) * hl.d, 0, Math.cos(hl.a) * hl.d, hl.a);
      m.stack([[hl.r, -2], [hl.r * 0.6, hl.h * 0.6], [hl.r * 0.2, hl.h]], 7, [color, shadeK(color, 1.08)], shadeK(color, 1.15), 0.25);
    }
    return m;
  },
  // the same hills as the 2D sky draws them: a height (an angle above the horizon) for each of n directions
  skyline(list, n) {
    const out = new Float32Array(n || 720);
    for (const hl of list) {
      const half = Math.atan(hl.r / hl.d), e = Math.atan(hl.h / hl.d);
      for (let i = 0; i < out.length; i++) {
        const d = Math.abs(U.wrap(i / out.length * TAU - hl.a)) / half;
        if (d < 1) out[i] = Math.max(out[i], e * (1 - d * d) * (0.85 + 0.15 * Math.sin(i * 0.7 + hl.seed)));
      }
    }
    return out;
  },
  blob(w, h, col) {                                  // a soft round spot (a 2D sprite): shadows, foam, glows
    const c = document.createElement("canvas"); c.width = w; c.height = h;
    const g = c.getContext("2d"), gr = g.createRadialGradient(w / 2, w / 2, 0, w / 2, w / 2, w / 2);
    gr.addColorStop(0, col); gr.addColorStop(1, "rgba(0,0,0,0)");
    g.setTransform(1, 0, 0, h / w, 0, 0); g.fillStyle = gr; g.fillRect(0, 0, w, w);
    return { c, ax: w / 2, ay: h / 2, ppu: 1 };
  }
};
function shadeK(c, k) { return U.shade(c, k); }

// ---------------------------------------------------------------- a path: a closed (or open) smooth line through points,
// sampled every step; where things race, patrol, ride or fly along
function Path(pts, o) {
  o = o || {}; const step = o.step || 2, closed = o.closed !== false, n = pts.length;
  const xs = [], zs = [];
  const last = closed ? n : n - 1;
  this.knots = [];                                   // the sample each point falls on
  for (let i = 0; i < last; i++) {
    this.knots.push(xs.length);
    const p0 = pts[closed ? (i - 1 + n) % n : Math.max(0, i - 1)], p1 = pts[i], p2 = pts[closed ? (i + 1) % n : i + 1], p3 = pts[closed ? (i + 2) % n : Math.min(n - 1, i + 2)];
    const k = Math.max(4, Math.ceil(Math.hypot(p2[0] - p1[0], p2[1] - p1[1]) / step));
    for (let j = 0; j < k; j++) {
      const t = j / k, t2 = t * t, t3 = t2 * t;
      const f = (a, b, c, d) => 0.5 * (2 * b + (-a + c) * t + (2 * a - 5 * b + 4 * c - d) * t2 + (-a + 3 * b - 3 * c + d) * t3);
      xs.push(f(p0[0], p1[0], p2[0], p3[0])); zs.push(f(p0[1], p1[1], p2[1], p3[1]));
    }
  }
  if (!closed) { this.knots.push(xs.length); xs.push(pts[n - 1][0]); zs.push(pts[n - 1][1]); }
  const N = xs.length;
  this.closed = closed; this.n = N; this.x = new Float32Array(xs); this.z = new Float32Array(zs);
  this.s = new Float32Array(N + 1); this.tx = new Float32Array(N); this.tz = new Float32Array(N); this.curve = new Float32Array(N);
  for (let i = 0; i < N; i++) { const j = closed ? (i + 1) % N : Math.min(N - 1, i + 1); this.s[i + 1] = this.s[i] + Math.hypot(xs[j] - xs[i], zs[j] - zs[i]); }
  this.len = this.s[closed ? N : N - 1];
  for (let i = 0; i < N; i++) {
    const a = closed ? (i - 1 + N) % N : Math.max(0, i - 1), b = closed ? (i + 1) % N : Math.min(N - 1, i + 1);
    const dx = xs[b] - xs[a], dz = zs[b] - zs[a], l = Math.hypot(dx, dz) || 1; this.tx[i] = dx / l; this.tz[i] = dz / l;
  }
  for (let i = 0; i < N; i++) {                      // how sharply it bends just ahead (things on it slow for it)
    let c = 0;
    for (let k = 1; k <= 12; k++) { const a = (i + k - 1) % N, b = (i + k) % N; c += Math.abs(U.wrap(Math.atan2(this.tx[b], this.tz[b]) - Math.atan2(this.tx[a], this.tz[a]))); }
    this.curve[i] = c;
  }
}
Path.prototype = {
  at(s, out) {                                       // at a distance s along it: out = [x, z, tx, tz, sample]
    const L = this.len; s = this.closed ? ((s % L) + L) % L : U.clamp(s, 0, L);
    let lo = 0, hi = this.n;
    while (lo + 1 < hi) { const m = (lo + hi) >> 1; if (this.s[m] <= s) lo = m; else hi = m; }
    const i = lo, j = (i + 1) % this.n, t = (s - this.s[i]) / ((this.s[i + 1] - this.s[i]) || 1);
    out[0] = this.x[i] + (this.x[j] - this.x[i]) * t; out[1] = this.z[i] + (this.z[j] - this.z[i]) * t;
    let tx = this.tx[i] + (this.tx[j] - this.tx[i]) * t, tz = this.tz[i] + (this.tz[j] - this.tz[i]) * t; const l = Math.hypot(tx, tz) || 1;
    out[2] = tx / l; out[3] = tz / l; out[4] = i;
    return out;
  },
  side(s, off, out) { this.at(s, out); const x = out[0] - out[3] * off, z = out[1] + out[2] * off; out[0] = x; out[1] = z; return out; },   // off: to the left
  near(x, z, hint, win) {                            // the nearest sample (near hint when given: quicker, and stays on its part)
    let best = 1e18, bi = 0;
    if (hint == null) { for (let i = 0; i < this.n; i++) { const d = (this.x[i] - x) ** 2 + (this.z[i] - z) ** 2; if (d < best) { best = d; bi = i; } } }
    else for (let k = -(win || 40); k <= (win || 40); k++) {
      const i = this.closed ? (hint + k + this.n) % this.n : U.clamp(hint + k, 0, this.n - 1), d = (this.x[i] - x) ** 2 + (this.z[i] - z) ** 2;
      if (d < best) { best = d; bi = i; }
    }
    this.dist = Math.sqrt(best);
    return bi;
  },
  delta(from, to) {                                  // how far along from one sample to another (the short way round)
    let d = this.s[to] - this.s[from];
    if (this.closed) { if (d > this.len / 2) d -= this.len; else if (d < -this.len / 2) d += this.len; }
    return d;
  },
  bounds(pad) { let x0 = 1e9, z0 = 1e9, x1 = -1e9, z1 = -1e9; for (let i = 0; i < this.n; i++) { x0 = Math.min(x0, this.x[i]); x1 = Math.max(x1, this.x[i]); z0 = Math.min(z0, this.z[i]); z1 = Math.max(z1, this.z[i]); } pad = pad || 0; return [x0 - pad, z0 - pad, x1 + pad, z1 + pad]; }
};

// ---------------------------------------------------------------- a world's still things, in square chunks: one mesh a
// chunk for each layer ("base", "detail": small things, drawn nearer; "glow": lit by themselves), culled and drawn
// nearest first
function Chunks(size, cell) {
  this.size = size; this.cell = cell || 128; this.nc = Math.ceil(size / this.cell); this.half = size / 2;
  this.cells = new Array(this.nc * this.nc); this.list = []; this.order = []; this.g3 = null;
}
Chunks.prototype = {
  mesh(x, z, layer) {                                // the mesh to build into for something at x z
    const nc = this.nc, ix = U.clamp(Math.floor((x + this.half) / this.cell), 0, nc - 1), iz = U.clamp(Math.floor((z + this.half) / this.cell), 0, nc - 1);
    const c = this.cells[iz * nc + ix] || (this.cells[iz * nc + ix] = { base: new Mesh(512), detail: new Mesh(256), glow: new Mesh(64) });
    return c[layer || "base"];
  },
  each(fn) { for (const c of this.cells) if (c) fn(c); },
  upload(g3) {
    this.free(); this.g3 = g3;
    for (const c of this.cells) {
      if (!c) continue;
      const h = { base: c.base.n ? g3.upload(c.base) : null, detail: c.detail.n ? g3.upload(c.detail) : null, glow: c.glow.n ? g3.upload(c.glow) : null, d: 0 };
      const b = h.base || h.detail || h.glow; if (!b) continue;
      h.x = b.x; h.y = b.y; h.z = b.z; h.r = Math.max(b.r, (h.detail || b).r, (h.glow || b).r) + 4;
      this.list.push(h);
    }
    return this;
  },
  // the chunks in view and within far, nearest first (an insertion sort: the order hardly changes frame to frame)
  draw(g3, ex, ez, far, detailK) {
    const o = this.order; let k = 0;
    for (let i = 0; i < this.list.length; i++) { const c = this.list[i]; c.d = Math.hypot(c.x - ex, c.z - ez) - c.r; if (c.d < far && g3.sees(c.x, c.y, c.z, c.r)) o[k++] = c; }
    for (let i = 1; i < k; i++) { const e = o[i]; let j = i - 1; while (j >= 0 && o[j].d > e.d) { o[j + 1] = o[j]; j--; } o[j + 1] = e; }
    for (let i = 0; i < k; i++) {
      const c = o[i];
      g3.lit(c.base, null, 1, 1, 1, 0);
      if (c.detail && c.d < far * (detailK == null ? 1 : detailK)) g3.lit(c.detail, null, 1, 1, 1, 0);
      if (c.glow) g3.lit(c.glow, null, 1, 1, 1, 1);
    }
    return k;
  },
  free() { if (this.g3) for (const c of this.list) { this.g3.free(c.base); this.g3.free(c.detail); this.g3.free(c.glow); } this.list.length = 0; this.order.length = 0; }
};

// ---------------------------------------------------------------- trails behind moving things (wakes, light trails, tyre
// marks): a point every so often; drawn as a ribbon (3D) or spots (2D)
function Trail(n, every) { this.max = n || 22; this.every = every || 0.06; this.p = new Float32Array(this.max * 3); this.n = 0; this.t = 0; }
Trail.prototype = {
  step(dt, x, z, strength) {
    this.t -= dt; if (this.t > 0) return;
    this.t = this.every; const p = this.p, n = Math.min(this.n + 1, this.max);
    for (let k = n - 1; k > 0; k--) { p[k * 3] = p[k * 3 - 3]; p[k * 3 + 1] = p[k * 3 - 2]; p[k * 3 + 2] = p[k * 3 - 1]; }
    p[0] = x; p[1] = z; p[2] = strength; this.n = n;
  },
  clear() { this.n = 0; },
  // into a mesh (a dynamic one, drawn with glow()): flat on the ground at y, widening w0 + i·dw, alpha from strength
  ribbon(m, y, col, w0, dw, alpha) {
    const p = this.p, r = (col >> 16) & 255, g = (col >> 8) & 255, b = col & 255;
    for (let i = 0; i + 1 < this.n; i++) {
      const ax = p[i * 3], az = p[i * 3 + 1], bx = p[i * 3 + 3], bz = p[i * 3 + 4];
      let dx = bx - ax, dz = bz - az; const l = Math.hypot(dx, dz) || 1; dx /= l; dz /= l;
      const wa = w0 + i * dw, wb = w0 + (i + 1) * dw;
      const aa = U.clamp((1 - i / this.max) * p[i * 3 + 2] * alpha, 0, 255) | 0, ab = U.clamp((1 - (i + 1) / this.max) * p[i * 3 + 5] * alpha, 0, 255) | 0;
      const ax1 = ax - dz * wa, az1 = az + dx * wa, ax2 = ax + dz * wa, az2 = az - dx * wa, bx1 = bx - dz * wb, bz1 = bz + dx * wb, bx2 = bx + dz * wb, bz2 = bz - dx * wb;
      if (m.n + 6 > m.cap) return;
      m.put(ax1, y, az1, 0, 1, 0, r, g, b, aa); m.put(bx1, y, bz1, 0, 1, 0, r, g, b, ab); m.put(bx2, y, bz2, 0, 1, 0, r, g, b, ab);
      m.put(ax1, y, az1, 0, 1, 0, r, g, b, aa); m.put(bx2, y, bz2, 0, 1, 0, r, g, b, ab); m.put(ax2, y, az2, 0, 1, 0, r, g, b, aa);
    }
  },
  spots(flat, sprite, y, s0, ds, alpha, stride) {    // in 2D: soft spots along it
    for (let k = 1; k < this.n; k += stride || 2) {
      const a = (1 - k / this.max) * this.p[k * 3 + 2] * alpha; if (a < 0.05) continue;
      flat.sprite(sprite, this.p[k * 3], y, this.p[k * 3 + 1], s0 + k * ds, Math.min(1, a));
    }
  }
};

// ---------------------------------------------------------------- particles: a fixed pool (spray, sparks, dust, smoke)
function Particles(n) {
  this.max = n || 64; const F = () => new Float32Array(this.max);
  this.x = F(); this.y = F(); this.z = F(); this.vx = F(); this.vy = F(); this.vz = F(); this.life = F(); this.next = 0;
}
Particles.prototype = {
  emit(x, y, z, count, power, up) {
    for (let k = 0; k < count; k++) {
      const i = this.next++ % this.max, a = Math.random() * TAU, p = (0.4 + Math.random()) * power;
      this.x[i] = x; this.y[i] = y; this.z[i] = z; this.vx[i] = Math.cos(a) * p; this.vz[i] = Math.sin(a) * p;
      this.vy[i] = (up == null ? 2 : up) + Math.random() * 3 * power / 6; this.life[i] = 0.5 + Math.random() * 0.4;
    }
  },
  step(dt, gravity, floor) {
    for (let i = 0; i < this.max; i++) if (this.life[i] > 0) {
      this.life[i] -= dt; this.vy[i] -= (gravity == null ? 14 : gravity) * dt;
      this.x[i] += this.vx[i] * dt; this.y[i] += this.vy[i] * dt; this.z[i] += this.vz[i] * dt;
      if (this.y[i] < (floor || 0)) this.life[i] = 0;
    }
  },
  clear() { this.life.fill(0); },
  points(m, col) {                                   // into a dynamic mesh, drawn with glow(…, points)
    m.n = 0; const r = (col >> 16) & 255, g = (col >> 8) & 255, b = col & 255;
    for (let i = 0; i < this.max; i++) if (this.life[i] > 0) m.put(this.x[i], this.y[i], this.z[i], 0, 1, 0, r, g, b, U.clamp(this.life[i] * 320, 0, 255) | 0);
  },
  sprites(flat, sprite, scale) { for (let i = 0; i < this.max; i++) if (this.life[i] > 0) flat.sprite(sprite, this.x[i], this.y[i], this.z[i], scale, Math.min(1, this.life[i] * 1.6)); }
};

// ---------------------------------------------------------------- cameras: a camera is {x y z, tx ty tz (looked at), yaw,
// fov (up and down, radians), roll}; both renderers draw from it
function camera() { return { x: 0, y: 8, z: -20, tx: 0, ty: 0, tz: 0, yaw: 0, fov: 0.78, roll: 0 }; }
// behind something that has x z yaw (and yr, its turning speed): dist behind, height up, looking ahead; snap: no lag
function chase(cam, t, dt, dist, height, ahead, snap) {
  const want = t.yaw + U.clamp((t.yr || 0) * 0.18, -0.3, 0.3);
  cam.yaw += U.wrap(want - cam.yaw) * (snap ? 1 : 1 - Math.exp(-5.5 * dt));
  const fx = Math.sin(cam.yaw), fz = Math.cos(cam.yaw), k = snap ? 1 : 1 - Math.exp(-14 * dt);
  cam.x += (t.x - fx * dist - cam.x) * k; cam.z += (t.z - fz * dist - cam.z) * k; cam.y = height + (t.y || 0) * 0.5;
  cam.tx = t.x + fx * ahead; cam.tz = t.z + fz * ahead; cam.ty = 1.2 + (t.y || 0) * 0.5;
}
function orbit(cam, cx, cz, radius, height, angle, tx, tz) {
  cam.x = cx + Math.sin(angle) * radius; cam.z = cz + Math.cos(angle) * radius; cam.y = height;
  cam.tx = tx == null ? cx : tx; cam.tz = tz == null ? cz : tz; cam.ty = 0; cam.roll = 0;
  cam.yaw = Math.atan2(cam.tx - cam.x, cam.tz - cam.z);
}
// draw a frame of either renderer from a camera (GL: begin() with the same view the 2D one gets)
function viewOf(cam) {
  const dx = cam.tx - cam.x, dz = cam.tz - cam.z, hd = Math.hypot(dx, dz) || 1;
  return { yaw: Math.atan2(dx, dz), pitch: Math.atan2(cam.y - cam.ty, hd) };
}

// ---------------------------------------------------------------- input: the controller first (pad.js), the keyboard too
// The box turns a controller's buttons into keys as well (arrows, Enter, Back…, for its menus): while a controller is
// there, such a key waits a moment and is dropped when the controller itself was just pressed (so nothing happens
// twice); a remote's or the phone's keys still come through. Back (B, or a remote's Back) on the game's top screen is
// left to the box: it leaves the game. o: { keys: {key: action}, on(action, how), top() → ms since the top screen showed, or 0 }
const ECHO = /^(Arrow|Enter$|NumpadEnter$|Escape$|Backspace$|BrowserBack$|GoBack$|Media|\/$)/;
const BACKS = /^(Escape|Backspace|BrowserBack|GoBack)$/;
function Input(o) {
  this.o = o; this.k = {}; this.q = []; this.lastPad = -1e9;
  const pad = window.SofaPad;
  if (pad) pad.on((b, how) => { if (b === "connected") { if (o.connected) o.connected(); return; } this.lastPad = performance.now(); o.on(b, how); });
  addEventListener("keydown", e => {
    const back = BACKS.test(e.key) || e.code === "BrowserBack", top = o.top ? o.top() : 0;
    if (back && top && performance.now() - top > 500) return;      // the box's: out of the game
    const act = o.keys[e.key] || o.keys[e.code];
    if (act || back) e.preventDefault();
    if (!act) return;
    if (pad && pad.connected() && ECHO.test(e.key)) { if (!e.repeat) this.q.push({ act, t: performance.now(), down: true }); return; }
    this.k[act] = true; o.on(act, e.repeat ? "repeat" : "press");
  });
  addEventListener("keyup", e => {
    const act = o.keys[e.key] || o.keys[e.code]; if (!act) return;
    if (pad && pad.connected() && ECHO.test(e.key)) { this.q.push({ act, t: performance.now(), down: false }); return; }
    this.k[act] = false; o.on(act, "release");
  });
  addEventListener("blur", () => { for (const a in this.k) this.k[a] = false; });
}
Input.prototype = {
  tick(now) {
    while (this.q.length && now - this.q[0].t > 60) {
      const e = this.q.shift();
      if (this.lastPad > e.t - 300 || (window.SofaPad && window.SofaPad.active())) continue;   // the controller's own echo
      this.k[e.act] = e.down; this.o.on(e.act, e.down ? "press" : "release");
    }
  },
  held(a) { return (window.SofaPad && window.SofaPad.held(a)) || !!this.k[a]; },
  key(a) { return !!this.k[a]; },
  stick() { return window.SofaPad ? window.SofaPad.stick() : { x: 0, y: 0 }; },
  pad() { return !!(window.SofaPad && window.SofaPad.connected()); },
  // a button's name as the player knows it: the controller's (A, or ✕ on a PlayStation one), or the key's
  label(a, keyNames) { return this.pad() ? window.SofaPad.label(a) : (keyNames || {})[a] || a; },
  kbd(a, keyNames) { return "<kbd>" + U.esc(this.label(a, keyNames)) + "</kbd>"; }
};

// ---------------------------------------------------------------- menus: screens of .item elements, worked with the
// arrows, A to choose and B for back. o: { screens: { name: { grid: columns, row: true (left and right), back:
// "screen" or function, enter(el), options: [{k, name, vals, names}] with values (an object) and changed(k, v) } },
// top: the top screen's name, choose(el, act, screen), sound(name) }
function Menu(o) {
  this.o = o; this.at = null; this.i = 0; this.topAt = 0;
}
Menu.prototype = {
  el(name) { return (this.o.screens[name] || {}).el || document.getElementById(name); },
  items() { return this.at ? Array.from(this.el(this.at).querySelectorAll(".item")) : []; },
  show(name, keep) {
    for (const n in this.o.screens) { const e = this.el(n); if (e) e.classList.toggle("hidden", n !== name); }
    if (name === this.o.top && this.at !== name) this.topAt = performance.now();
    this.at = name; if (!keep) this.i = 0;
    const S = this.o.screens[name];
    if (S.enter) { const i = S.enter(this.el(name)); if (typeof i === "number" && !keep) this.i = i; }
    if (S.options) this.renderOptions();
    this.focus(this.i);
  },
  hide() { for (const n in this.o.screens) { const e = this.el(n); if (e) e.classList.add("hidden"); } this.at = null; },
  top() { return this.at === this.o.top ? this.topAt : 0; },
  focus(i) {
    const it = this.items(); if (!it.length) return;
    this.i = U.clamp(i, 0, it.length - 1);
    it.forEach((e, k) => e.classList.toggle("on", k === this.i));
  },
  move(d) { const before = this.i; this.focus(this.i + d); if (this.i !== before && this.o.sound) this.o.sound("move"); },
  button(b, how) {                                  // true when the menu took it
    if (!this.at) return false;
    const S = this.o.screens[this.at], cols = S.grid || 1, it = this.items();
    if (b === "up") { if (!S.row) this.move(-cols); }
    else if (b === "down") { if (!S.row) this.move(cols); }
    else if (b === "left" || b === "right") {
      const d = b === "left" ? -1 : 1;
      if (S.options) this.change(this.i, d); else if (S.grid || S.row) this.move(d);
    } else if (how !== "press") return true;
    else if (b === "a" || b === "start") {
      const el = it[this.i]; if (!el) return true;
      if (S.options && !el.dataset.do) this.change(this.i, 1);
      else { if (this.o.sound) this.o.sound("ok"); this.o.choose(el, el.dataset.do, this.at); }
    } else if (b === "b" || b === "back") this.back();
    return true;
  },
  back() {
    const S = this.o.screens[this.at]; if (!S || !S.back) return;
    if (this.o.sound) this.o.sound("move");
    if (typeof S.back === "function") S.back(); else this.show(S.back);
  },
  renderOptions() {
    const S = this.o.screens[this.at], v = S.values;
    const list = S.list || this.el(this.at).querySelector(".menu");
    list.innerHTML = S.options.map(o => {
      const x = v[o.k], name = o.names ? o.names[x] : typeof x === "number" && o.vals.length > 5 ? "▮".repeat(x) + "▯".repeat(o.vals[o.vals.length - 1] - x) : x;
      return `<div class="item row"><span>${U.esc(o.name)}</span><b>◀ ${U.esc(name)} ▶</b></div>`;
    }).join("") + (S.extra || "");
    this.focus(this.i);
  },
  change(i, d) {
    const S = this.o.screens[this.at], o = S.options[i]; if (!o) return;
    const k = o.vals.indexOf(S.values[o.k]), v = o.vals[U.clamp(k + d, 0, o.vals.length - 1)];
    if (v === S.values[o.k]) return;
    S.values[o.k] = v; if (this.o.sound) this.o.sound("move");
    if (S.changed) S.changed(o.k, v);
    this.renderOptions();
  }
};

// ---------------------------------------------------------------- sound, made as it plays (WebAudio): notes and noise,
// named effects (define your own), a music sequencer that writes a tune from a seed, and drones (engines, wind)
function Synth() { this.ac = null; this.fx = Object.assign({}, FX); this.seq = null; this.vol = { music: 0.6, sound: 0.8 }; }
const FX = {
  move: (s, t) => s.note(t, 880, 0.05, "sine", 0.06),
  ok: (s, t) => { s.note(t, 660, 0.1, "sine", 0.1); s.note(t + 0.05, 990, 0.14, "sine", 0.1); },
  no: (s, t) => { s.note(t, 330, 0.3, "square", 0.08, null, 0.01, 1200); s.note(t + 0.12, 262, 0.4, "square", 0.08, null, 0.01, 1200); },
  beep: (s, t) => s.note(t, 660, 0.18, "square", 0.08, null, 0.005, 2000),
  go: (s, t) => s.note(t, 1320, 0.45, "square", 0.09, null, 0.005, 2600),
  chime: (s, t) => { s.note(t, 988, 0.25, "sine", 0.18); s.note(t + 0.07, 1319, 0.35, "sine", 0.16); },
  pickup: (s, t) => s.note(t, 1760 + Math.random() * 200, 0.18, "sine", 0.12),
  fanfare: (s, t) => [784, 988, 1175, 1568].forEach((f, i) => s.note(t + i * 0.08, f, 0.4, "triangle", 0.16)),
  win: (s, t) => [523, 659, 784, 1047, 1319].forEach((f, i) => s.note(t + i * 0.11, f, 0.6, "triangle", 0.15)),
  whoosh: (s, t) => s.noise(t, 0.6, 0.3, 700, 0.7),
  bump: (s, t) => { s.noise(t, 0.25, 0.5, 220, 1.2); s.note(t, 70, 0.25, "sine", 0.4); },
  splash: (s, t) => s.noise(t, 0.35, 0.25, 900, 0.6),
  hit: (s, t) => { s.noise(t, 0.12, 0.4, 1800, 1); s.note(t, 180, 0.12, "square", 0.12, null, 0.002, 900); },
  jump: (s, t) => s.note(t, 300, 0.2, "square", 0.08, null, 0.005, 2400)
};
Synth.prototype = {
  start() {
    if (this.ac) { if (this.ac.state === "suspended") this.ac.resume(); return; }
    const AC = window.AudioContext || window.webkitAudioContext; if (!AC) return;
    try { this.ac = new AC(); } catch (e) { return; }
    const ac = this.ac;
    this.master = ac.createGain(); this.master.gain.value = 0.8; this.master.connect(ac.destination);
    this.musicBus = ac.createGain(); this.musicBus.connect(this.master); this.sfxBus = ac.createGain(); this.sfxBus.connect(this.master);
    this.echo = ac.createDelay(1); this.echo.delayTime.value = 0.33; const fb = ac.createGain(); fb.gain.value = 0.28; const wet = ac.createGain(); wet.gain.value = 0.3;
    this.echo.connect(fb); fb.connect(this.echo); this.echo.connect(wet); wet.connect(this.musicBus);
    this.noiseBuf = ac.createBuffer(1, ac.sampleRate, ac.sampleRate); const d = this.noiseBuf.getChannelData(0); for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
    this.volume(this.vol.music, this.vol.sound);
  },
  volume(music, sound) {                             // 0..1 each
    this.vol.music = music; this.vol.sound = sound;
    if (!this.ac) return;
    this.musicBus.gain.value = Math.pow(music, 1.5) * 0.55; this.sfxBus.gain.value = Math.pow(sound, 1.5) * 0.9;
  },
  note(t, freq, dur, type, vol, dest, attack, cutoff) {
    if (!this.ac) return null;
    const ac = this.ac, o = ac.createOscillator(), g = ac.createGain();
    o.type = type; o.frequency.value = freq;
    g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(vol, t + (attack || 0.008)); g.gain.exponentialRampToValueAtTime(0.0008, t + dur);
    if (cutoff) { const f = ac.createBiquadFilter(); f.type = "lowpass"; f.frequency.value = cutoff; o.connect(f); f.connect(g); } else o.connect(g);
    g.connect(dest || this.sfxBus); o.start(t); o.stop(t + dur + 0.05);
    return g;
  },
  noise(t, dur, vol, freq, q, dest) {
    if (!this.ac) return;
    const ac = this.ac, s = ac.createBufferSource(), f = ac.createBiquadFilter(), g = ac.createGain();
    s.buffer = this.noiseBuf; f.type = "bandpass"; f.frequency.value = freq; f.Q.value = q || 1;
    g.gain.setValueAtTime(vol, t); g.gain.exponentialRampToValueAtTime(0.0008, t + dur);
    s.connect(f); f.connect(g); g.connect(dest || this.sfxBus); s.start(t, Math.random() * 0.5); s.stop(t + dur + 0.05);
  },
  define(name, fn) { this.fx[name] = fn; },
  play(name) { if (this.ac && this.fx[name]) this.fx[name](this, this.ac.currentTime + 0.01); },
  // a tune written from a seed and played on: { seed, root (MIDI note), tempo, calm (no drums, slower), prog (chords
  // as semitones over the root, a bar each), lead: a melody from the seed after the first bars }
  song(o) {
    this.stopSong(); if (!this.ac) return;
    const ac = this.ac, mb = this.musicBus, s = this, rnd = U.rand((o.seed || 1) * 101 + (o.calm ? 7 : 0));
    const root = o.root || 50, beat = 60 / (o.calm ? Math.min(o.tempo || 100, 84) : (o.tempo || 100));
    const PROGS = [[0, 9, 5, 7], [0, 5, 9, 7], [9, 5, 0, 7], [0, 7, 9, 5], [2, 7, 0, 5]];
    const prog = o.prog || PROGS[(o.seed || 0) % PROGS.length], scale = [0, 2, 4, 7, 9], mtof = m => 440 * Math.pow(2, (m - 69) / 12);
    const lead = []; let li = 2;
    for (let i = 0; i < 16; i++) { li = U.clamp(li + ((rnd() * 5) | 0) - 2, 0, 9); lead.push(rnd() < 0.28 ? -1 : li); }
    let step = 0, next = ac.currentTime + 0.1;
    this.seq = setInterval(() => {
      while (next < ac.currentTime + 0.25) {
        const bar = (step >> 3) & 3, s8 = step & 7, ch = prog[bar], t = next;
        const third = ch === 9 || ch === 2 || ch === 4 ? 3 : 4, tones = [ch, ch + third, ch + 7, ch + 12];
        if (s8 === 0 || s8 === 4 || (!o.calm && s8 === 6)) s.note(t, mtof(root - 12 + ch), beat * (s8 === 6 ? 0.9 : 1.8), "triangle", 0.32, mb, 0.01);
        if (!o.calm || s8 % 2 === 0) { const n = s.note(t, mtof(root + 12 + tones[(step + bar) % 4]), beat * 0.9, "square", 0.05, mb, 0.004, 1600); if (n) n.connect(s.echo); }
        if (s8 === 0) for (const k of [0, third, 7]) s.note(t, mtof(root + ch + k), beat * 7.5, "sawtooth", 0.022, mb, beat * 1.5, 900);
        if (!o.calm && o.lead !== false && step >= 32) { const L = lead[step % 16]; if (L >= 0 && s8 % 2 === 0) s.note(t, mtof(root + 24 + scale[L % 5] + (L >= 5 ? 12 : 0)), beat * 0.85, "triangle", 0.09, mb, 0.01); }
        if (!o.calm && o.drums !== false) {
          if (s8 === 0 || s8 === 4) { const k = ac.createOscillator(), g = ac.createGain(); k.frequency.setValueAtTime(110, t); k.frequency.exponentialRampToValueAtTime(40, t + 0.18);
            g.gain.setValueAtTime(0.5, t); g.gain.exponentialRampToValueAtTime(0.001, t + 0.22); k.connect(g); g.connect(mb); k.start(t); k.stop(t + 0.25); }
          if (s8 % 2 === 1) s.noise(t, 0.05, 0.08, 8000, 0.8, mb);
        }
        step++; next += beat / 2;
      }
    }, 60);
  },
  stopSong() { if (this.seq) { clearInterval(this.seq); this.seq = null; } },
  // a sound that goes on (an engine, the wind): kind "saw" (two detuned saws through a lowpass) or "noise" (filtered);
  // set(pitch Hz, brightness Hz, volume) as it changes (values only: nothing new made while it plays); stop()
  drone(kind) {
    if (!this.ac) return null;
    const ac = this.ac, f = ac.createBiquadFilter(), g = ac.createGain(), src = [];
    g.gain.value = 0; f.connect(g); g.connect(this.sfxBus);
    if (kind === "noise") { const s = ac.createBufferSource(); s.buffer = this.noiseBuf; s.loop = true; f.type = "bandpass"; f.Q.value = 0.6; s.connect(f); s.start(); src.push(s); }
    else { f.type = "lowpass"; for (const dt of [0, 9]) { const o = ac.createOscillator(); o.type = "sawtooth"; o.detune.value = dt; o.connect(f); o.start(); src.push(o); } }
    return {
      set(pitch, bright, vol) {
        const t = ac.currentTime;
        if (kind !== "noise") for (const o of src) o.frequency.setTargetAtTime(pitch, t, 0.06);
        f.frequency.setTargetAtTime(bright, t, 0.08); g.gain.setTargetAtTime(vol, t, 0.08);
      },
      stop() { g.gain.setTargetAtTime(0, ac.currentTime, 0.05); setTimeout(() => { for (const s of src) { try { s.stop(); } catch (e) { /* stopped */ } } }, 300); }
    };
  }
};

// ---------------------------------------------------------------- a game: its screen, tuned to the box, and its loop
// Low3D.game({ id, view, gl, flat, fps, loading: {el, bar, text}, aspect, picture() → "auto" | "light" | "rich" | "flat",
//   input, ready(E), prepare(E) (build what the mode needs: after a level loads, and when the mode changes),
//   rung(E, r), update(dt) (60 times a second), draw(now, dt) (each frame drawn), paused() })
// kind: "ray" for a game drawn a pixel at a time (Ray): the CPU test alone picks its rung (LADDER.ray), E.screen is
// its picture (E.screen.u32), shown through WebGL where the GPU is real (picture() "plain": never), resized(E) when
// the picture's size changes.
// In the address: #fps shows the rate and the rung, #flat or #gl picks the renderer, #rung=N holds a rung, #test is for checks.
function game(o) {
  const H = location.hash || "";
  const E = {
    o, mode: "flat", g3: null, flat: null, gov: null, rung: null, probe: null, bench: null, plan: null, ready: false, broken: false,
    test: /test/.test(H), showFps: /fps/.test(H), force: /flat|2d/.test(H) ? "flat" : /\bgl\b|3d/.test(H) ? "gl" : null,
    forceRung: /rung=(\d+)/.test(H) ? +H.match(/rung=(\d+)/)[1] : null, aspect: o.aspect || 16 / 9, vw: 960, vh: 540, DT: 1 / 60
  };
  const KEY = (o.id || "game") + ":tune";
  let tune = null;
  try { tune = JSON.parse(localStorage.getItem(KEY) || "null"); } catch (e) { tune = null; }
  E.keep = (t) => { tune = t; try { localStorage.setItem(KEY, JSON.stringify(t)); } catch (e) { /* the game still runs */ } };
  E.fit = () => {                                     // the game's box: the screen's shape, as big as fits
    const a = E.aspect, s = Math.min(innerWidth / a, innerHeight), w = Math.round(s * a), h = Math.round(s);
    Object.assign(o.view.style, { width: w + "px", height: h + "px", left: ((innerWidth - w) >> 1) + "px", top: ((innerHeight - h) >> 1) + "px" });
    o.view.style.setProperty("--u", (h / 100) + "px"); E.vw = w; E.vh = h;
    E.resize();
  };
  E.size = () => { const h = E.mode === "ray" ? E.rung.h : Math.min(E.rung.h, Math.round(E.vh * (devicePixelRatio || 1))); return [Math.round(h * E.aspect), h]; };
  E.resize = () => {
    if (!E.rung) return;
    const [w, h] = E.size();
    if (E.mode === "ray") { if (E.screen && E.screen.size(w, h, Math.min(E.rung.out || 1, (E.vh * (devicePixelRatio || 1)) / h)) && o.resized) o.resized(E); }
    else if (E.mode === "gl" && E.g3) { if (o.gl.width !== w || o.gl.height !== h) { o.gl.width = w; o.gl.height = h; } }
    else if (E.flat) E.flat.size(w, h);
  };
  E.ladder = () => LADDER[E.mode];
  E.choice = () => {
    const p = o.picture ? o.picture() : "auto";
    if (E.broken) return "flat";
    if (E.force) return E.force;
    if (p === "flat") return "flat";
    if (p === "light" || p === "rich") return E.probe.webgl1 && !E.probe.software ? "gl" : E.plan.mode;
    return E.plan.mode;
  };
  E.renderer = (first) => {                          // the renderer, the rung to start on and the governor
    if (o.kind === "ray") {
      const p = o.picture ? o.picture() : "auto", fx = E.plan.fx && p !== "plain" && !E.broken;
      if (!E.screen || E.screen.fx !== fx) { E.screen = new Screen(o.flat, o.gl, fx); E.screen.fx = fx; E.screen.w = 0; }
      E.mode = "ray";
    }
    const want = o.kind === "ray" ? "ray" : E.choice();
    if (want !== "ray") {
      if (want === "gl" && !E.g3) { try { E.g3 = new GL(o.gl); } catch (e) { E.g3 = null; } }
      E.mode = want === "gl" && E.g3 ? "gl" : "flat";
      if (E.mode === "flat" && !E.flat) E.flat = new Flat(o.flat);
      o.gl.classList.toggle("hidden", E.mode !== "gl"); o.flat.classList.toggle("hidden", E.mode !== "flat");
    }
    const lad = LADDER[E.mode], p = o.picture ? o.picture() : "auto";
    let start = E.mode === E.plan.mode ? E.plan.rung : E.mode === "gl" ? 1 : 2, top = E.mode === E.plan.mode ? E.plan.top : lad.length - 1;
    if (tune && tune.key === E.probe.key && tune.mode === E.mode && tune.rung != null && p === "auto") { start = tune.rung; top = Math.min(top, tune.top); }
    if (p === "light") { start = Math.min(start, E.mode === "ray" ? 2 : 1); top = Math.min(top, E.mode === "ray" ? 3 : 2); }
    if (p === "rich") { start = Math.max(start, 4); top = lad.length - 1; }
    if (E.forceRung != null) start = top = E.forceRung;
    start = U.clamp(start, 0, lad.length - 1); top = U.clamp(Math.max(top, start), 0, lad.length - 1);
    E.gov = new Governor(lad, start, top, (r, why) => { E.rung = lad[r]; E.resize(); if (o.rung) o.rung(E, E.rung); E.remember(); });
    if (E.forceRung != null) E.gov.lock = true;
    E.rung = lad[start]; E.resize();
    if (!first && o.prepare) o.prepare(E);
    if (o.rung) o.rung(E, E.rung);
  };
  E.remember = () => { if ((o.picture ? o.picture() : "auto") === "auto" && E.forceRung == null) E.keep({ key: E.probe.key, bench: E.bench, mode: E.mode, rung: E.gov.rung, top: E.gov.top }); };
  E.setPicture = () => { E.keep({ key: E.probe.key, bench: E.bench }); E.renderer(false); };
  E.test3d = (done, step) => {                       // the ~2 s test (software GL is left out: the 2D sea is quicker there)
    let g = null;
    if (E.probe.webgl1 && !E.probe.software && E.force !== "flat" && o.kind !== "ray") { try { g = E.g3 || new GL(o.gl); E.g3 = g; } catch (e) { g = null; } }
    o.gl.classList.toggle("hidden", !g);
    if (o.loading) o.loading.el.classList.add("see");
    bench(g, r => { E.bench = r; o.gl.classList.add("hidden"); if (o.loading) o.loading.el.classList.remove("see"); done(r); }, step);
  };
  const planOf = () => o.kind === "ray" ? planRay(E.probe, E.bench) : plan(E.probe, E.bench);
  E.retest = (done) => E.test3d(() => { E.plan = planOf(); E.keep({ key: E.probe.key, bench: E.bench }); E.renderer(false); if (done) done(); });
  E.rows = () => {                                   // "This box": what it is, what was chosen, what it's doing now
    const [w, h] = E.size(), R = E.rung, G3 = E.g3;
    const now = E.mode === "ray"
      ? ["Now", "drawn by the processor, rung " + E.gov.rung + " (top " + E.gov.top + "): " + w + "×" + h + ", " + R.fps + " fps wanted, " + E.gov.fps + " drawn" + (E.screen && E.screen.gl ? ", shown through WebGL" + (R.glow ? " with glow" : "") : ", shown in 2D")]
      : null;
    return rows(E.probe, E.bench, E.plan).concat([
      now || ["Now", (E.mode === "gl" ? "3D" : "2D") + ", rung " + E.gov.rung + " (top " + E.gov.top + "): " + w + "×" + h + ", " + R.fps + " fps wanted, " + E.gov.fps + " drawn" +
        (E.mode === "gl" ? ", draw distance " + R.far + " m" + (R.waves && G3 && G3.can("waves") ? ", waves" : "") : "")],
      ["Changes", E.gov.log.length ? E.gov.log.slice(-4).join(" · ") : "none yet"],
      ["Screen", E.probe.screen + " · page " + innerWidth + "×" + innerHeight + " at " + (devicePixelRatio || 1) + "×"],
      ["In one line", line(E.probe, E.bench, E.plan)]
    ]);
  };
  E.lost = (err) => {                                // the GPU went away: carry on in 2D
    console.warn("WebGL failed; drawing in 2D", err);
    if (o.kind === "ray") { E.broken = true; E.plan = Object.assign({}, E.plan, { fx: false }); E.renderer(false); return; }
    E.g3 = null; E.broken = true; E.plan = Object.assign({}, E.plan, { mode: "flat", rung: 2, top: LADDER.flat.length - 1, why: "WebGL stopped" });
    E.renderer(false);
  };
  o.gl.addEventListener("webglcontextlost", e => { e.preventDefault(); if (E.mode === "gl" || (E.screen && E.screen.gl)) E.lost(new Error("context lost")); });
  // the loop: input, then (when the governor says this frame is drawn) the fixed steps, then the drawing
  let last = 0, acc = 0, fpsAt = 0;
  function frame(now) {
    requestAnimationFrame(frame);
    if (!E.ready) return;
    if (o.input) o.input.tick(now);
    if (!E.gov.tick(now)) return;
    const t0 = performance.now();
    let dt = (now - last) / 1000; last = now; if (dt > 0.25) dt = 0.25;
    if (!(o.paused && o.paused())) { acc += dt; let n = 0; while (acc >= E.DT && n < 6) { o.update(E.DT); acc -= E.DT; n++; } if (n === 6) acc = 0; }
    if (E.mode === "gl") { try { o.draw(now, dt); } catch (e) { E.lost(e); } } else o.draw(now, dt);
    if (E.mode === "ray" && E.screen) E.screen.present(E.rung.glow, E.vig);
    E.gov.work(performance.now() - t0);
    if (E.showFps && o.fps && now - fpsAt > 500) {
      fpsAt = now; const [w, h] = E.size();
      o.fps.textContent = E.gov.fps + " fps · " + (E.mode === "gl" ? "3D" : E.mode === "ray" ? "ray" : "2D") + " rung " + E.gov.rung + " · " + w + "×" + h +
        (E.mode === "gl" ? " · " + E.g3.calls + " draws " + Math.round(E.g3.tris) + " tris" : "") + "\nwork " + (performance.now() - t0).toFixed(1) + " ms";
    }
  }
  E.start = () => {                                  // what this box is, the test (once per box and browser), then ready
    E.fit(); addEventListener("resize", E.fit);
    E.probe = probe();
    const go = () => {
      E.plan = planOf();
      E.renderer(true);
      if (o.loading && o.loading.text) o.loading.text.textContent = "Getting ready…";
      setTimeout(() => {
        if (o.ready) o.ready(E);
        if (o.prepare) o.prepare(E);
        if (!tune || tune.key !== E.probe.key || !tune.bench) E.remember();
        if (o.loading) o.loading.el.classList.add("hidden");
        if (E.showFps && o.fps) o.fps.classList.remove("hidden");
        E.ready = true; last = performance.now(); E.gov.hold(1500);
      }, 30);
    };
    if (tune && tune.key === E.probe.key && tune.bench) { E.bench = tune.bench; go(); }
    else {
      if (o.loading && o.loading.text) o.loading.text.textContent = "Tuning to this box…";
      setTimeout(() => E.test3d(go, (phase, load) => { if (o.loading && o.loading.bar) o.loading.bar.style.width = Math.min(95, 20 + (phase + 1) * 30 + Math.log2(load + 1) * 3) + "%"; }), 50);
    }
    requestAnimationFrame(frame);
    return E;
  };
  return E;
}

// one frame of a world from a camera in either renderer: GL begin() (the caller draws its things after), or the 2D
// ground and sky (the caller adds sprites, then flat.flush())
function begin(E, cam, near, far) {
  if (E.mode === "gl") { E.g3.begin(cam.x, cam.y, cam.z, cam.tx, cam.ty, cam.tz, cam.fov, near || 0.6, far || 2600, cam.roll); return; }
  const v = viewOf(cam); E.flat.draw(cam.x, cam.y, cam.z, v.yaw, v.pitch, cam.fov);
}

// ================================================================ Ray: a software renderer for worlds on a grid
// Rooms and corridors with floors and ceilings at any height (steps, ledges, pits, sky), doors and lifts (a cell's
// ceiling or floor that moves), textures and sprites, drawn a pixel at a time into one picture: the same on every
// box, GPU or not (a Pi 3 draws it at 320×180). Light is Doom-like: each cell its own level, fading with distance,
// and a palette of 16 ramps of 16 shades with colormaps, so shading a pixel is a single look-up.

// ---------------------------------------------------------------- the palette: index = ramp·16 + shade; 0 is see-through
function Palette(ramps, glow) {
  this.rgb = new Uint8Array(768); this.full = new Uint8Array(256); this.cube = new Int16Array(32768).fill(-1);
  for (let r = 0; r < 16; r++) {
    const base = ramps[r] || [128, 128, 128];
    for (let s = 0; s < 16; s++) {
      const k = 0.08 + (s / 15) * 1.22, i = r * 16 + s;
      for (let c = 0; c < 3; c++) { let v = base[c] * Math.min(k, 1); if (k > 1) v += (255 - v) * (k - 1) * 0.85; this.rgb[i * 3 + c] = Math.max(0, Math.min(255, Math.round(v))); }
      if (glow && glow.indexOf(r) >= 0) this.full[i] = 1;
    }
  }
  this.maps(0x000000, 0);
}

Palette.prototype = {
  color(i) { return (this.rgb[i * 3] << 16) | (this.rgb[i * 3 + 1] << 8) | this.rgb[i * 3 + 2]; },   // an index as 0xrrggbb
  near(r, g, b) {                                    // the nearest colour's index (never 0, the see-through one)
    const key = ((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3);
    let v = this.cube[key];
    if (v >= 0) return v;
    let best = 1e9; v = 1;
    for (let i = 1; i < 256; i++) {
      if (this.full[i]) continue;                      // (glowing colours only where they're meant: Tex, emissive faces)
      const dr = this.rgb[i * 3] - r, dg = this.rgb[i * 3 + 1] - g, db = this.rgb[i * 3 + 2] - b, d = dr * dr * 3 + dg * dg * 4 + db * db * 2;
      if (d < best) { best = d; v = i; }
    }
    return (this.cube[key] = v);
  },
  // 32 light levels × 256 colours, packed for the picture; dark fades towards fog (a colour) as much as haze says
  maps(fog, haze) {
    const fr = (fog >> 16) & 255, fg = (fog >> 8) & 255, fb = fog & 255, cm = this.cmap || (this.cmap = new Uint32Array(32 * 256));
    for (let L = 0; L < 32; L++) {
      const b = Math.pow(L / 31, 1.15), h = (1 - b) * haze;
      for (let i = 0; i < 256; i++) {
        let r = this.rgb[i * 3], g = this.rgb[i * 3 + 1], bl = this.rgb[i * 3 + 2];
        if (!this.full[i]) { r = r * b + fr * h; g = g * b + fg * h; bl = bl * b + fb * h; }
        cm[L * 256 + i] = LE ? (0xff000000 | (Math.min(255, bl) << 16) | (Math.min(255, g) << 8) | Math.min(255, r)) >>> 0 : 0;
      }
    }
    this.fogPx = LE ? (0xff000000 | (fb * haze) << 16 | (fg * haze) << 8 | (fr * haze)) >>> 0 : 0;
    return cm;
  },
  // a picture (a canvas, or bake()'s sprite) as palette indices, columns first: what Ray draws
  sprite(src) {
    const c = src.c || src, w = c.width, h = c.height, d = c.getContext("2d").getImageData(0, 0, w, h).data, px = new Uint8Array(w * h);
    if (!this.glowAt) { this.glowAt = new Map(); for (let i = 1; i < 256; i++) if (this.full[i]) this.glowAt.set((this.rgb[i * 3] << 16) | (this.rgb[i * 3 + 1] << 8) | this.rgb[i * 3 + 2], i); }
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      const o = (y * w + x) * 4;
      if (d[o + 3] > 110) { const g = this.glowAt.get((d[o] << 16) | (d[o + 1] << 8) | d[o + 2]); px[x * h + y] = g || this.near(d[o], d[o + 1], d[o + 2]); }
    }
    return { w, h, px, ax: src.ax != null ? src.ax : w / 2, ay: src.ay != null ? src.ay : h, ppu: src.ppu || 32 };
  }
};

// ---------------------------------------------------------------- textures, made in code: 64×64 palette indices, columns first
const Tex = {
  make(fn, size) {                                    // fn(u, v) → a palette index, u and v from 0 to size-1
    size = size || 64; const px = new Uint8Array(size * size);
    for (let u = 0; u < size; u++) for (let v = 0; v < size; v++) px[u * size + v] = fn(u, v) || 1;
    return { w: size, h: size, px };
  },
  // smooth noise that wraps every period (seamless tiles), 0..1
  noise(seed) {
    const r = U.rand(seed), g = new Float32Array(256 * 256); for (let i = 0; i < g.length; i++) g[i] = r();
    const at = (x, y, p) => g[((y % p + p) % p) * 256 + ((x % p + p) % p)];
    return function (x, y, p) {
      p = p || 8; const xi = Math.floor(x), yi = Math.floor(y), fx = x - xi, fy = y - yi, sx = fx * fx * (3 - 2 * fx), sy = fy * fy * (3 - 2 * fy);
      const a = at(xi, yi, p), b = at(xi + 1, yi, p), c = at(xi, yi + 1, p), d = at(xi + 1, yi + 1, p);
      return a + (b - a) * sx + (c - a) * sy + (a - b - c + d) * sx * sy;
    };
  },
  fbm(n, x, y, p, oct) { let s = 0, a = 0.5, t = 0; for (let o = 0; o < (oct || 3); o++) { s += n(x, y, p) * a; t += a; x *= 2; y *= 2; p *= 2; a *= 0.5; } return s / t; },
  shade(ramp, k) { return ramp * 16 + Math.max(1, Math.min(15, Math.round(k * 15))); }   // a ramp's shade from 0..1
};

// ---------------------------------------------------------------- a world on a grid
function RayMap(w, h) {
  const n = w * h;
  this.w = w; this.h = h;
  this.solid = new Uint8Array(n); this.wtex = new Uint8Array(n); this.stex = new Uint8Array(n); this.utex = new Uint8Array(n);   // (stex: a step's face; utex: a ceiling's lip, a door)
  this.ftex = new Uint8Array(n); this.ctex = new Uint8Array(n);
  this.floor = new Float32Array(n); this.ceil = new Float32Array(n).fill(1);
  this.light = new Uint8Array(n).fill(24); this.dyn = new Uint8Array(n); this.seen = new Uint8Array(n);
  this.flowD = new Int16Array(n); this.q = new Int32Array(n);
}
RayMap.SKY = 255;
RayMap.prototype = {
  at(x, y) { return (y | 0) * this.w + (x | 0); },
  inside(x, y) { return x >= 0 && y >= 0 && x < this.w && y < this.h; },
  // can a body (radius r, standing at height z, stepping up to step, needing room) be at x y?
  open(x, y, r, z, step, room) {
    const x0 = Math.floor(x - r), x1 = Math.floor(x + r), y0 = Math.floor(y - r), y1 = Math.floor(y + r);
    for (let cy = y0; cy <= y1; cy++) for (let cx = x0; cx <= x1; cx++) {
      if (cx < 0 || cy < 0 || cx >= this.w || cy >= this.h) return false;
      const i = cy * this.w + cx;
      if (this.solid[i] || this.floor[i] > z + step || this.ceil[i] - Math.max(this.floor[i], z) < room) return false;
    }
    return true;
  },
  floorAt(x, y, r) {                                 // the highest floor under a body
    const x0 = Math.floor(x - r), x1 = Math.floor(x + r), y0 = Math.floor(y - r), y1 = Math.floor(y + r);
    let f = -1e9;
    for (let cy = y0; cy <= y1; cy++) for (let cx = x0; cx <= x1; cx++) { const i = cy * this.w + cx; if (!this.solid[i] && this.floor[i] > f) f = this.floor[i]; }
    return f;
  },
  // moves a body {x, y, z} by dx dy, sliding along walls; true when it moved all the way
  move(b, dx, dy, r, step, room) {
    let ok = true;
    if (this.open(b.x + dx, b.y, r, b.z, step, room)) b.x += dx; else ok = false;
    if (this.open(b.x, b.y + dy, r, b.z, step, room)) b.y += dy; else ok = false;
    return ok;
  },
  // a straight line from one point to another (z the heights): the share of the way it gets before something stops it (1: clear)
  trace(x0, y0, z0, x1, y1, z1) {
    const dx = x1 - x0, dy = y1 - y0, len = Math.hypot(dx, dy) || 1e-6;
    let mx = Math.floor(x0), my = Math.floor(y0);
    const ex = Math.floor(x1), ey = Math.floor(y1), sx = dx < 0 ? -1 : 1, sy = dy < 0 ? -1 : 1;
    const tdx = dx === 0 ? 1e30 : Math.abs(1 / dx), tdy = dy === 0 ? 1e30 : Math.abs(1 / dy);
    let tx = dx === 0 ? 1e30 : (dx < 0 ? x0 - mx : mx + 1 - x0) * tdx, ty = dy === 0 ? 1e30 : (dy < 0 ? y0 - my : my + 1 - y0) * tdy;
    for (let k = 0; k < 200; k++) {
      if (mx === ex && my === ey) return 1;
      let t;
      if (tx < ty) { t = tx; tx += tdx; mx += sx; } else { t = ty; ty += tdy; my += sy; }
      if (t >= 1) return 1;
      if (!this.inside(mx, my)) return t;
      const i = my * this.w + mx, z = z0 + (z1 - z0) * t;
      if (this.solid[i] || z < this.floor[i] || z > this.ceil[i]) return t;
    }
    return 1;
  },
  see(x0, y0, z0, x1, y1, z1) { return this.trace(x0, y0, z0, x1, y1, z1) >= 0.999; },
  // how many steps from every cell to x y, for things that walk (step: the highest step up; room: headroom; through:
  // cells they get past whatever (doors they open)); -1: no way
  flow(x, y, step, room, through) {
    const d = this.flowD, q = this.q, w = this.w, n = this.w * this.h;
    d.fill(-1); let head = 0, tail = 0;
    const s = this.at(x, y); if (s < 0 || s >= n) return d;
    d[s] = 0; q[tail++] = s;
    while (head < tail) {
      const i = q[head++], cx = i % w, cy = (i / w) | 0, fz = this.floor[i];
      for (let k = 0; k < 4; k++) {
        const nx = cx + (k === 0 ? 1 : k === 1 ? -1 : 0), ny = cy + (k === 2 ? 1 : k === 3 ? -1 : 0);
        if (nx < 0 || ny < 0 || nx >= w || ny >= this.h) continue;
        const j = ny * w + nx;
        if (d[j] >= 0 || this.solid[j] || (this.ceil[j] - this.floor[j] < room && !(through && through[j]))) continue;
        if (fz > this.floor[j] + step || this.floor[j] > fz + step) continue;      // (both ways: they walk to you)
        d[j] = d[i] + 1; q[tail++] = j;
      }
    }
    return d;
  }
};

// ---------------------------------------------------------------- the renderer
function Ray(pal) {
  this.pal = pal; this.tex = []; this.sky = null; this.dim = 2.4; this.minL = 0; this.queue = []; this.qn = 0; this.w = 0;   // (minL: the darkest a lit thing gets)
}
Ray.prototype = {
  size(w, h, buf) {
    this.w = w; this.h = h; this.buf = buf;
    this.depth = new Float32Array(w * h); this.rowInv = new Float32Array(h);
  },
  // the world from a camera {x, y, z (eye height), a (facing), pitch (looking up: a share of the height), fov (across)}
  render(m, cam) {
    const w = this.w, h = this.h, buf = this.buf, dep = this.depth, cm = this.pal.cmap, tex = this.tex, sky = this.sky, W = m.w, H = m.h;
    const solid = m.solid, wtex = m.wtex, stex = m.stex, utex = m.utex, ftex = m.ftex, ctex = m.ctex, flo = m.floor, cei = m.ceil, lig = m.light, dyn = m.dyn, seen = m.seen;
    const dirX = Math.cos(cam.a), dirY = Math.sin(cam.a), t = Math.tan(cam.fov / 2), plX = -dirY * t, plY = dirX * t;
    const f = (w / 2) / t, hz = h / 2 + cam.pitch * h, px = cam.x, py = cam.y, ez = cam.z, dim = this.dim, rowInv = this.rowInv;
    const fogPx = this.pal.fogPx, maxD = this.maxD || 40, mL = this.minL;
    this.cam = cam; this.f = f; this.hz = hz; this.dirX = dirX; this.dirY = dirY;
    for (let y = 0; y < h; y++) { const d = y + 0.5 - hz; rowInv[y] = Math.abs(d) < 1e-3 ? 1e3 : 1 / d; }
    const R = (b) => b < 0 ? 0 : b > h ? h : Math.ceil(b - 0.5);
    // a wall's column at d1, from zTop down to zBot (made once a frame: it reads the column's state below)
    let x = 0, d1 = 0, top = 0, bot = h, u = 0, Lw = 0, vs = 0;
    const wall = (T, zTop, zBot) => {
      const yA = Math.max(R(hz - (zTop - ez) * f / d1), top), yB = Math.min(R(hz - (zBot - ez) * f / d1), bot);
      if (yA >= yB) return;
      let s = (Lw - d1 * dim) | 0; s = s < mL ? mL : s > 31 ? 31 : s; s <<= 8;
      let v = (-(ez + (hz - (yA + 0.5)) * d1 / f)) * 64 + 65536;
      const step = vs, uu = u, xx = x;
      for (let y = yA; y < yB; y++, v += step) { const o = y * w + xx; buf[o] = cm[s | T[uu | ((v | 0) & 63)]]; dep[o] = d1; }
    };
    const skyW = sky ? sky.w : 1, skyH = sky ? sky.h : 1, skyK = sky ? skyH / (h * 0.62) : 0;
    for (x = 0; x < w; x++) {
      const camX = 2 * (x + 0.5) / w - 1, rdx = dirX + plX * camX, rdy = dirY + plY * camX;
      let mx = Math.floor(px), my = Math.floor(py);
      const ddx = rdx === 0 ? 1e30 : Math.abs(1 / rdx), ddy = rdy === 0 ? 1e30 : Math.abs(1 / rdy), stX = rdx < 0 ? -1 : 1, stY = rdy < 0 ? -1 : 1;
      let sdx = rdx < 0 ? (px - mx) * ddx : (mx + 1 - px) * ddx, sdy = rdy < 0 ? (py - my) * ddy : (my + 1 - py) * ddy;
      let ci = my * W + mx, d0 = 0; top = 0; bot = h;
      let skyU = -1;
      for (let guard = 0; guard < 128 && top < bot; guard++) {
        let side;
        if (sdx < sdy) { d1 = sdx; sdx += ddx; mx += stX; side = 0; } else { d1 = sdy; sdy += ddy; my += stY; side = 1; }
        if (d1 > maxD) d1 = maxD;
        const cF = flo[ci], cC = cei[ci], Lc = lig[ci] + dyn[ci];
        seen[ci] = 1;
        // this cell's floor, d0 to d1
        if (ez > cF) {
          const yA = Math.max(R(hz - (cF - ez) * f / d1), top), yB = Math.min(d0 > 0 ? R(hz - (cF - ez) * f / d0) : h, bot), k = (ez - cF) * f, T = tex[ftex[ci]].px;
          for (let y = yA; y < yB; y++) {
            const d = k * rowInv[y], o = y * w + x;
            let s = (Lc - d * dim) | 0; s = s < mL ? mL : s > 31 ? 31 : s;
            buf[o] = cm[(s << 8) | T[((((px + rdx * d) * 64) & 63) << 6) | (((py + rdy * d) * 64) & 63)]]; dep[o] = d;
          }
          if (yA < yB && yB > 0) bot = Math.min(bot, yA);
        }
        // its ceiling (or the sky)
        if (ez < cC) {
          const yA = Math.max(d0 > 0 ? R(hz - (cC - ez) * f / d0) : 0, top), yB = Math.min(R(hz - (cC - ez) * f / d1), bot);
          if (ctex[ci] === 255 && sky) {
            if (skyU < 0) { let a = (cam.a + Math.atan(camX * t)) / TAU; a -= Math.floor(a); skyU = ((a * skyW) | 0) * skyH; }
            const S = sky.px;
            for (let y = yA; y < yB; y++) { let v = (skyH - 1 + (y + 0.5 - hz) * skyK) | 0; v = v < 0 ? 0 : v >= skyH ? skyH - 1 : v; const o = y * w + x; buf[o] = cm[(31 << 8) | S[skyU + v]]; dep[o] = 1e9; }
          } else {
            const k = (ez - cC) * f, T = tex[ctex[ci]].px;
            for (let y = yA; y < yB; y++) {
              const d = k * rowInv[y], o = y * w + x;
              let s = (Lc - d * dim) | 0; s = s < mL ? mL : s > 31 ? 31 : s;
              buf[o] = cm[(s << 8) | T[((((px + rdx * d) * 64) & 63) << 6) | (((py + rdy * d) * 64) & 63)]]; dep[o] = d;
            }
          }
          if (yA < yB) top = Math.max(top, yB);
        }
        if (d1 >= maxD || mx < 0 || my < 0 || mx >= W || my >= H) break;
        const ni = my * W + mx;
        // where the ray meets the next cell's edge, across the wall's face
        let wx = side === 0 ? py + d1 * rdy : px + d1 * rdx; wx -= Math.floor(wx);
        if ((side === 0 && rdx > 0) || (side === 1 && rdy < 0)) wx = 1 - wx;
        u = ((wx * 64) | 0) << 6; Lw = Lc - (side ? 2 : 0); vs = 64 * d1 / f;
        if (solid[ni]) { wall(tex[wtex[ni]].px, cC, cF); seen[ni] = 1; top = bot; break; }
        const nF = flo[ni], nC = cei[ni];
        if (nF > cF) { wall(tex[stex[ni]].px, nF, cF); bot = Math.min(bot, R(hz - (nF - ez) * f / d1)); }
        else bot = Math.min(bot, R(hz - (cF - ez) * f / d1));
        if (nC < cC) { wall(tex[utex[ni]].px, cC, nC); top = Math.max(top, R(hz - (nC - ez) * f / d1)); }
        else top = Math.max(top, R(hz - (cC - ez) * f / d1));
        ci = ni; d0 = d1;
      }
      for (let y = top; y < bot; y++) { const o = y * w + x; buf[o] = fogPx; dep[o] = 1e9; }   // (nothing there: far fog)
    }
    this.qn = 0;
  },
  // a sprite standing at x y (its foot at height z), light 0..31 (full: drawn as it is), flip: mirrored
  sprite(s, x, y, z, light, full, flip, scale) {
    const c = this.cam, dx = x - c.x, dy = y - c.y, d = dx * this.dirX + dy * this.dirY;
    if (d < 0.15 || d > (this.maxD || 40)) return;
    if (this.qn >= this.queue.length) this.queue.push({});
    const q = this.queue[this.qn++];
    q.s = s; q.d = d; q.lat = dx * -this.dirY + dy * this.dirX; q.z = z; q.light = light; q.full = full; q.flip = flip; q.k = scale || 1; q.dot = 0;
  },
  dot(x, y, z, idx, size, full) {                    // a speck (spark, blood, smoke): a small square, world size
    const c = this.cam, dx = x - c.x, dy = y - c.y, d = dx * this.dirX + dy * this.dirY;
    if (d < 0.15 || d > 24) return;
    if (this.qn >= this.queue.length) this.queue.push({});
    const q = this.queue[this.qn++];
    q.s = null; q.d = d; q.lat = dx * -this.dirY + dy * this.dirX; q.z = z; q.idx = idx; q.size = size; q.full = full; q.dot = 1; q.light = 24;
  },
  flush() {                                           // the sprites, far to near, behind what's nearer
    const Q = this.queue, n = this.qn, w = this.w, h = this.h, buf = this.buf, dep = this.depth, cm = this.pal.cmap, f = this.f, hz = this.hz, ez = this.cam.z, dim = this.dim, full = this.pal.full;
    for (let i = 1; i < n; i++) { const e = Q[i]; let j = i - 1; while (j >= 0 && Q[j].d < e.d) { Q[j + 1] = Q[j]; j--; } Q[j + 1] = e; }
    for (let i = 0; i < n; i++) {
      const q = Q[i], d = q.d, sx = w / 2 + q.lat * f / d;
      if (q.dot) {
        const sz = Math.max(1, q.size * f / d) | 0, cy = hz - (q.z - ez) * f / d, x0 = (sx - sz / 2) | 0, y0 = (cy - sz / 2) | 0;
        let s = (24 - d * dim) | 0; s = q.full ? 31 : s < 0 ? 0 : s > 31 ? 31 : s;
        const col = cm[(s << 8) | q.idx];
        for (let y = Math.max(0, y0); y < Math.min(h, y0 + sz); y++) for (let x = Math.max(0, x0); x < Math.min(w, x0 + sz); x++) { const o = y * w + x; if (dep[o] > d) buf[o] = col; }
        continue;
      }
      const s = q.s; if (!s) continue;
      const k = f / d / s.ppu * q.k, sw = s.w * k, sh = s.h * k;
      const left = sx - s.ax * k, topY = hz - (q.z - ez) * f / d - s.ay * k;
      const x0 = Math.max(0, Math.ceil(left - 0.5)), x1 = Math.min(w, Math.ceil(left + sw - 0.5)), y0 = Math.max(0, Math.ceil(topY - 0.5)), y1 = Math.min(h, Math.ceil(topY + sh - 0.5));
      if (x0 >= x1 || y0 >= y1) continue;
      let L = (q.light - d * dim) | 0; L = L < this.minL ? this.minL : L > 31 ? 31 : L; const Ls = L << 8;
      const P = s.px, H = s.h, inv = 1 / k;
      for (let x = x0; x < x1; x++) {
        let u = ((x + 0.5 - left) * inv) | 0; if (u >= s.w) u = s.w - 1; if (q.flip) u = s.w - 1 - u;
        const col = u * H;
        let v = (y0 + 0.5 - topY) * inv;
        for (let y = y0; y < y1; y++, v += inv) {
          const o = y * w + x; if (dep[o] <= d) continue;
          const idx = P[col + (v | 0)]; if (!idx) continue;
          buf[o] = cm[(q.full || full[idx] ? 31 << 8 : Ls) | idx];
        }
      }
    }
    this.qn = 0;
  },
  // a sprite on the screen itself (a weapon in hand): its bottom middle at sx sy, scale screen pixels a sprite pixel
  blit(s, sx, sy, scale, light) {
    const w = this.w, h = this.h, buf = this.buf, cm = this.pal.cmap, full = this.pal.full, P = s.px, H = s.h;
    const left = sx - s.w * scale / 2, topY = sy - s.h * scale, inv = 1 / scale, Ls = Math.max(0, Math.min(31, light | 0)) << 8;
    const x0 = Math.max(0, Math.ceil(left - 0.5)), x1 = Math.min(w, Math.ceil(left + s.w * scale - 0.5)), y0 = Math.max(0, Math.ceil(topY - 0.5)), y1 = Math.min(h, Math.ceil(topY + s.h * scale - 0.5));
    for (let x = x0; x < x1; x++) {
      const col = Math.min(s.w - 1, ((x + 0.5 - left) * inv) | 0) * H;
      let v = (y0 + 0.5 - topY) * inv;
      for (let y = y0; y < y1; y++, v += inv) { const idx = P[col + Math.min(H - 1, v | 0)]; if (idx) buf[y * w + x] = cm[(full[idx] ? 31 << 8 : Ls) | idx]; }
    }
  },
  // where a world point is on the screen: [x, y, distance], or null behind
  project(x, y, z, out) {
    const c = this.cam, dx = x - c.x, dy = y - c.y, d = dx * this.dirX + dy * this.dirY;
    if (d < 0.1) return null;
    out[0] = this.w / 2 + (dx * -this.dirY + dy * this.dirX) * this.f / d; out[1] = this.hz - (z - c.z) * this.f / d; out[2] = d;
    return out;
  }
};

// ---------------------------------------------------------------- the screen: a picture made a pixel at a time, shown
// scaled up; through WebGL where the GPU is real (smooth or crisp scaling, a soft glow round bright things, a little
// vignette: on a Pi 4 or 5), else straight onto a 2D canvas
const POST_VS = `attribute vec2 aXY; varying vec2 vUV; void main() { vUV = vec2(aXY.x * 0.5 + 0.5, 0.5 - aXY.y * 0.5); gl_Position = vec4(aXY, 0.0, 1.0); }`;
const POST_FS = `
precision mediump float;
uniform sampler2D uT; uniform vec2 uTexel; uniform float uGlow; uniform float uVig; varying vec2 vUV;
void main() {
  vec3 c = texture2D(uT, vUV).rgb;
  if (uGlow > 0.0) {
    vec3 b = texture2D(uT, vUV + vec2(uTexel.x * 1.5, 0.0)).rgb + texture2D(uT, vUV - vec2(uTexel.x * 1.5, 0.0)).rgb
           + texture2D(uT, vUV + vec2(0.0, uTexel.y * 1.5)).rgb + texture2D(uT, vUV - vec2(0.0, uTexel.y * 1.5)).rgb;
    c += max(b * 0.25 - 0.6, 0.0) * uGlow * 1.8;
  }
  vec2 d = vUV - 0.5; c *= 1.0 - uVig * dot(d, d) * 1.6;
  gl_FragColor = vec4(c, 1.0);
}`;
function Screen(c2d, cgl, useGL) {
  this.c2d = c2d; this.cgl = cgl; this.gl = null; this.w = 0; this.h = 0; this.crisp = true;
  if (useGL) {
    try {
      const gl = cgl.getContext("webgl", { antialias: false, alpha: false, depth: false, preserveDrawingBuffer: false });
      if (!gl) throw new Error("no WebGL");
      const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s)); return s; };
      const p = gl.createProgram(); gl.attachShader(p, sh(gl.VERTEX_SHADER, POST_VS)); gl.attachShader(p, sh(gl.FRAGMENT_SHADER, POST_FS));
      gl.bindAttribLocation(p, 0, "aXY"); gl.linkProgram(p); if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error("link");
      gl.useProgram(p);
      const b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
      gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 8, 0);
      this.tex = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, this.tex);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      this.u = { texel: gl.getUniformLocation(p, "uTexel"), glow: gl.getUniformLocation(p, "uGlow"), vig: gl.getUniformLocation(p, "uVig") };
      this.gl = gl;
    } catch (e) { this.gl = null; }
  }
  cgl.classList.toggle("hidden", !this.gl); c2d.classList.toggle("hidden", !!this.gl);
  if (!this.gl) this.ctx = c2d.getContext("2d", { alpha: false });
}
Screen.prototype = {
  // the picture's size (what the game draws into: u32, one number a pixel); out: how much bigger WebGL shows it
  size(w, h, out) {
    if (w === this.w && h === this.h && (out || 1) === this.out) return false;
    this.w = w; this.h = h; this.out = out || 1;
    this.img = new ImageData(w, h); this.u8 = new Uint8Array(this.img.data.buffer); this.u32 = new Uint32Array(this.img.data.buffer);
    if (this.gl) {
      const gl = this.gl; this.cgl.width = Math.round(w * this.out); this.cgl.height = Math.round(h * this.out);
      gl.viewport(0, 0, this.cgl.width, this.cgl.height);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
      gl.uniform2f(this.u.texel, 1 / w, 1 / h); this.filter();
    } else { this.c2d.width = w; this.c2d.height = h; }
    return true;
  },
  filter() { if (!this.gl) return; const gl = this.gl, F = this.crisp ? gl.NEAREST : gl.LINEAR; gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, F); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, F); },
  present(glow, vig) {
    if (this.gl) {
      const gl = this.gl;
      gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, this.w, this.h, gl.RGBA, gl.UNSIGNED_BYTE, this.u8);
      gl.uniform1f(this.u.glow, glow || 0); gl.uniform1f(this.u.vig, vig == null ? 0.35 : vig);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    } else this.ctx.putImageData(this.img, 0, 0);
  }
};
// the rungs for a software-drawn game: the size drawn (16:9), frames a second, the WebGL glow (where there's a GPU)
LADDER.ray = [
  { h: 120, fps: 30, glow: 0, out: 2 }, { h: 144, fps: 30, glow: 0, out: 2 }, { h: 180, fps: 30, glow: 0, out: 2 },
  { h: 180, fps: 60, glow: 0, out: 2 }, { h: 216, fps: 60, glow: 1, out: 2 }, { h: 270, fps: 60, glow: 1, out: 2 }, { h: 360, fps: 60, glow: 1, out: 2 }
];
// where a software-drawn game starts: from the script test (the CPU does the drawing)
function planRay(p, b) {
  const cpu = b && b.cpu != null ? b.cpu : 100, top = LADDER.ray.length - 1;
  let rung = cpu < 12 ? 6 : cpu < 30 ? 5 : cpu < 60 ? 4 : cpu < 110 ? 3 : cpu < 180 ? 2 : 1;
  if (p.family === "pi3") rung = Math.min(rung, 3);
  const fx = p.webgl1 && !p.software;
  return { mode: "ray", rung, top: Math.min(top, rung + 2), fx, why: "the processor draws it (script " + cpu + " ms)" + (fx ? "; the GPU adds the glow" : "") };
}

window.Low3D = { probe, family, NAMES, bench, plan, rows, line, LADDER, Governor, GL, Mesh, Flat, bake, M4, px, hexRGB,
  U, Kit, Path, Chunks, Trail, Particles, camera, chase, orbit, viewOf, begin, Input, Menu, Synth, game,
  Palette, Tex, RayMap, Ray, Screen, planRay, version: 2 };
})();
