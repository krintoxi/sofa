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
    let zx = ex - tx, zy = ey - ty, zz = ez - tz, l = 1 / (Math.sqrt(zx * zx + zy * zy + zz * zz) || 1); zx *= l; zy *= l; zz *= l;
    let xx = uy * zz - uz * zy, xy = uz * zx - ux * zz, xz = ux * zy - uy * zx; l = 1 / (Math.sqrt(xx * xx + xy * xy + xz * xz) || 1); xx *= l; xy *= l; xz *= l;
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
      const l = 1 / (Math.sqrt(a * a + b * b + c * c) || 1); o[i * 4] = a * l; o[i * 4 + 1] = b * l; o[i * 4 + 2] = c * l; o[i * 4 + 3] = d * l;
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
  this.jit = 0; this.seed = 1; this.alpha = 255; this.glow = 0;   // (glow: what's built from now on is its own light, 0 to 127)
  this.s = new Float32Array(3);                      // (the next vertex's place, for v())
}
Mesh.prototype = {
  room(k) {
    if (this.n + k <= this.cap) return;
    while (this.n + k > this.cap) this.cap *= 2;
    const b = new ArrayBuffer(this.cap * 20); new Uint8Array(b).set(this.u8);
    this.buf = b; this.f = new Float32Array(b); this.i8 = new Int8Array(b); this.u8 = new Uint8Array(b); this.vw = null;
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
  // (e, the vertex's last spare byte, 0 to 127: in a world with its light baked in, how much it's its own light; among
  // see-through things (GL.fx), how much it's light added rather than paint laid over)
  put(x, y, z, nx, ny, nz, r, g, b, a, e) {
    const i = this.n++, f = i * 5, o = i * 20;
    this.f[f] = x; this.f[f + 1] = y; this.f[f + 2] = z;
    this.i8[o + 12] = Math.round(nx * 127); this.i8[o + 13] = Math.round(ny * 127); this.i8[o + 14] = Math.round(nz * 127); this.i8[o + 15] = e || 0;
    this.u8[o + 16] = r; this.u8[o + 17] = g; this.u8[o + 18] = b; this.u8[o + 19] = a;
  },
  // The same without garbage, for meshes built again every frame. A call that's handed numbers with fractions has
  // each of them made anew on the heap (V8 boxes them), unless it happens to be inlined: at 60 frames a second and a
  // thousand vertices that is megabytes a second for the collector, and its pauses are the stutters on a Pi 3. So:
  // the place into m.s (m.s[0] = x; m.s[1] = y; m.s[2] = z: stores into a typed array make nothing), then v() with
  // whole numbers only.
  v(r, g, b, a, e) {
    const i = this.n++, f = i * 5, o = i * 20, s = this.s;
    this.f[f] = s[0]; this.f[f + 1] = s[1]; this.f[f + 2] = s[2]; this.i8[o + 13] = 127; this.i8[o + 15] = e;
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
    const e = this.glow || 0;
    this.put(Ax, Ay, Az, nx, ny, nz, r, g, b, this.alpha, e); this.put(Bx, By, Bz, nx, ny, nz, r, g, b, this.alpha, e); this.put(Cx, Cy, Cz, nx, ny, nz, r, g, b, this.alpha, e);
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

// ---- the second way to draw a world, made for a Pi 3's GPU (VC4) and better on the rest. What costs a VC4 time is
// vertices worked on (twice each: once to sort them into tiles, once to draw), fragments with long shaders, draw calls
// (each a trip through the browser's GPU process) and, most of all, every pixel the browser lays over the canvas at
// the TV's full size. So: a still world's light is worked out once, as it's built, and kept in its colours
// (Mesh.light): its shader only moves and fogs. The sky is one painted picture on a dome. The water is one sheet with
// the world's picture, ripples and glints on it, see-through at a glancing angle so that what's drawn under it shows:
// the world drawn again upside down (mirror images, as old consoles did floors). Every see-through thing goes into one
// mesh (fx) and everything written on the screen into another (UI), each drawn with one call.
const STILL_VS = `
attribute vec3 aPos; attribute vec4 aNor; attribute vec4 aCol;
uniform mat4 uVP; uniform vec3 uEye; uniform vec2 uAir; uniform vec3 uFogCol; uniform vec3 uFogSun; uniform vec3 uSun; uniform vec3 uShine; uniform float uFlip;
varying vec3 vCol; varying vec4 vFog;
void main() {
  vec3 p = aPos;
  p.y = mix(p.y, -max(p.y, 0.0), uFlip);             // (its mirror image: what's above the water, under it)
  vec3 rel = p - uEye; float d = length(rel);
  float s = max(dot(rel, uSun) / d, 0.0);
  vFog = vec4(mix(uFogCol, uFogSun, s * s * s), clamp((d - uAir.x) * uAir.y, 0.0, 1.0));   // the air's colour that way, and how much of it
  vCol = aCol.rgb * mix(uShine, vec3(1.0), aNor.w);
  gl_Position = uVP * vec4(p, 1.0);
}`;
const STILL_FS = `
precision mediump float;
varying vec3 vCol; varying vec4 vFog;
void main() { gl_FragColor = vec4(mix(vCol, vFog.rgb, vFog.a), 1.0); }`;
// things that move (lit as they turn), with the same air as the still world and a mirror image of their own
const MOVE_VS = `
attribute vec3 aPos; attribute vec4 aNor; attribute vec4 aCol;
uniform mat4 uVP; uniform mat4 uM; uniform vec3 uSun; uniform vec3 uSunCol; uniform vec3 uAmb; uniform vec3 uGround;
uniform vec3 uEye; uniform vec2 uAir; uniform vec3 uFogCol; uniform vec3 uFogSun; uniform vec4 uTint; uniform float uFlip; uniform float uRim;
varying vec3 vCol; varying vec4 vFog;
void main() {
  vec4 w = uM * vec4(aPos, 1.0);
  vec3 n = normalize((uM * vec4(aNor.xyz, 0.0)).xyz);
  vec3 rel = w.xyz - uEye; float d = length(rel);
  float rim = 1.0 + dot(n, rel) / d; rim = clamp(rim, 0.0, 1.0); rim *= rim;   // its edge catches the sky's light
  vec3 c = aCol.rgb * uTint.rgb;
  vec3 lit = c * (mix(uGround, uAmb, 0.5 + 0.5 * n.y) + uSunCol * max(dot(n, uSun), 0.0)) + uAmb * (rim * uRim);
  vCol = mix(lit, c, max(uTint.a, aNor.w));
  w.y = mix(w.y, -w.y, uFlip);
  rel = w.xyz - uEye; d = length(rel);
  float s = max(dot(rel, uSun) / d, 0.0);
  vFog = vec4(mix(uFogCol, uFogSun, s * s * s), clamp((d - uAir.x) * uAir.y, 0.0, 1.0));
  gl_Position = uVP * w;
}`;
// the sky: a picture on a dome round the eye (its place on the picture in each vertex's colour: red across, green down)
const DOME_VS = `
attribute vec3 aPos; attribute vec4 aCol;
uniform mat4 uSkyVP; uniform float uFlip; uniform float uTurn;
varying vec2 vUV;
void main() {
  vec3 p = aPos; p.y = mix(p.y, -p.y, uFlip);
  vUV = vec2(aCol.x + uTurn, aCol.y);
  gl_Position = (uSkyVP * vec4(p, 1.0)).xyww;
}`;
const DOME_FS = `
precision mediump float;
uniform sampler2D uTex; uniform vec3 uShine; varying vec2 vUV;
void main() { gl_FragColor = vec4(texture2D(uTex, vUV).rgb * uShine, 1.0); }`;
// the water. Its colour from the world's picture (uTex: shallows, weed, shadows; its alpha: how near the shore), two
// layers of ripples that drift across each other (uDet: red and green), glints where they cross, most towards the sun's
// mirror image, foam that comes in to the shore in bands, and the air. Its alpha is how much of it hides what's under:
// little at a glancing angle (the sky and the mirror images show), more looking down.
// RICH (a Pi 4 and up): the ripples bend what's under and the glints are sharper.
const WATER_VS = `
attribute vec3 aPos;
uniform mat4 uVP; uniform vec3 uEye; uniform vec4 uMap; uniform vec4 uDrift; uniform vec2 uGrain;
varying vec2 vUV; varying vec3 vRel; varying vec4 vW;
void main() {
  vUV = (aPos.xz - uMap.xy) * uMap.zw;
  vRel = aPos - uEye;
  vW = vec4(aPos.xz * uGrain.x + uDrift.xy, aPos.zx * uGrain.y + uDrift.zw);
  gl_Position = uVP * vec4(aPos, 1.0);
}`;
const WATER_FS = `
#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif
uniform sampler2D uTex; uniform sampler2D uDet;
uniform vec3 uFogCol; uniform vec3 uFogSun; uniform vec2 uAir; uniform vec3 uSun; uniform vec3 uGlint; uniform vec3 uFoam; uniform vec4 uK; uniform float uTime; uniform vec3 uShine;
varying vec2 vUV; varying vec3 vRel; varying vec4 vW;
void main() {
  float d = length(vRel);
  vec3 v = vRel / d;
  vec3 r1 = texture2D(uDet, vW.xy).rgb; float r2 = texture2D(uDet, vW.zw).g;
  float n = (r1.r + r2) * (0.35 + 1.3 * r1.b);                         // the nets of light: either one's lines, coming and going with the swells
#ifdef RICH
  vec4 m = texture2D(uTex, vUV + (n - 0.3) * 0.0016);
#else
  vec4 m = texture2D(uTex, vUV);
#endif
  float s = max(v.x * uSun.x - v.y * uSun.y + v.z * uSun.z, 0.0);     // towards the sun's mirror image
  s *= s; s *= s; float s8 = s * s;
  float g = n * (uK.z + s8 * 1.1 + s * 0.2) + r1.r * r2 * 0.6;         // brightest in the sun's path, and where two lines cross
  float fo = clamp((fract(m.a * 2.5 - uTime * 0.35 + r1.b * 0.5) - 0.62) * 8.0, 0.0, 1.0) * m.a + clamp((m.a - 0.86) * 9.0, 0.0, 1.0);
  vec3 c = m.rgb * uShine * (0.82 + 0.36 * r1.b) + uGlint * g;
  c = mix(c, uFoam, min(fo * uK.w, 1.0));
  float fr = 1.0 + v.y; fr *= fr;                                      // 0 looking down, 1 along the water
  float f = clamp((d - uAir.x) * uAir.y, 0.0, 1.0);
  float sf = max(dot(v, uSun), 0.0);
  c = mix(c, mix(uFogCol, uFogSun, sf * sf * sf), f);
  float a = 1.0 - (uK.x + uK.y * fr) * (1.0 - f * 0.6);
  gl_FragColor = vec4(c, max(a, min(1.0, max(g * 0.8, fo * uK.w))));
}`;
// every see-through thing, in one mesh: each vertex's alpha is how much of it there is, its spare byte whether it's
// light added (flames, lamps, sparks, glowing wakes) or paint laid over (shadows, foam, rain); it thins with the air
const FX_VS = `
attribute vec3 aPos; attribute vec4 aNor; attribute vec4 aCol;
uniform mat4 uVP; uniform vec3 uEye; uniform vec2 uAir; uniform float uPoint;
varying vec4 vCol;
void main() {
  float a = aCol.a * (1.0 - clamp((length(aPos - uEye) - uAir.x) * uAir.y, 0.0, 1.0));
  vCol = vec4(aCol.rgb * a, a * (1.0 - aNor.w));
  gl_Position = uVP * vec4(aPos, 1.0);
  gl_PointSize = uPoint / max(gl_Position.w, 0.5);
}`;
const FX_FS = `
precision mediump float;
varying vec4 vCol;
void main() {
#ifdef DOTS
  vec2 d = gl_PointCoord - 0.5; gl_FragColor = vCol * clamp(1.0 - dot(d, d) * 4.0, 0.0, 1.0);
#else
  gl_FragColor = vCol;
#endif
}`;
// what's written on the screen: quads from one picture (letters, shapes), in the picture's own pixels
const UI_VS = `
attribute vec2 aXY; attribute vec2 aUV; attribute vec4 aCol;
uniform vec4 uView;
varying vec2 vUV; varying vec4 vCol;
void main() { vUV = aUV; vCol = aCol; gl_Position = vec4(aXY.x * uView.x + uView.z, aXY.y * uView.y + uView.w, 0.0, 1.0); }`;
const UI_FS = `
precision mediump float;
uniform sampler2D uTex; varying vec2 vUV; varying vec4 vCol;
void main() { float a = texture2D(uTex, vUV).a * vCol.a; gl_FragColor = vec4(vCol.rgb * a, a); }`;

function GL(canvas, opts) {
  opts = opts || {};
  const gl = canvas.getContext("webgl", { antialias: !!opts.antialias, alpha: false, depth: true, stencil: false, premultipliedAlpha: false,
    preserveDrawingBuffer: false, powerPreference: "high-performance" });
  if (!gl) throw new Error("no WebGL");
  this.gl = gl; this.canvas = canvas;
  this.vao = gl.getExtension("OES_vertex_array_object");
  this.derivatives = !!gl.getExtension("OES_standard_derivatives");
  const mk = (vs, fs, defs) => this.program(defs + vs, defs + fs);
  this.P = { lit: mk(LIT_VS, LIT_FS, ""), glow: mk(GLOW_VS, GLOW_FS, ""), sky: mk(SKY_VS, SKY_FS, "") };
  // the rest when first wanted (each takes a moment to make on a Pi 3): null when this GPU can't
  this.make = { sea: () => mk(SEA_VS, SEA_FS, ""), skySun: () => mk(SKY_VS, SKY_FS, "#define SUN\n"),
    seaWave: () => this.derivatives ? mk(SEA_VS, SEA_FS, "#define WAVES\n") : null,
    still: () => mk(STILL_VS, STILL_FS, ""), move: () => mk(MOVE_VS, STILL_FS, ""), dome: () => mk(DOME_VS, DOME_FS, ""),
    water: () => mk(WATER_VS, WATER_FS, ""), waterRich: () => mk(WATER_VS, WATER_FS, "#define RICH\n"),
    fx: () => mk(FX_VS, FX_FS, ""), fxDots: () => mk(FX_VS, FX_FS, "#define DOTS\n"), ui: () => mk(UI_VS, UI_FS, "") };
  this.flip = 0; this.skyVP = new Float32Array(16); this.tint = new Float32Array([1, 1, 1]);
  this.vp = new Float32Array(16); this.view = new Float32Array(16); this.proj = new Float32Array(16); this.m = new Float32Array(16);
  this.planes = new Float32Array(24); this.eye = new Float32Array(3);
  this.frame = 0; this.cur = null; this.curBuf = null; this.calls = 0; this.tris = 0;
  this.L = { sun: new Float32Array([0.4, 0.8, 0.3]), sunCol: new Float32Array([1, 0.95, 0.85]), amb: new Float32Array([0.42, 0.47, 0.55]),
    ground: new Float32Array([0.25, 0.22, 0.2]), fogCol: new Float32Array([0.7, 0.8, 0.9]), fog: new Float32Array([60, 200]),
    top: new Float32Array([0.25, 0.45, 0.8]), horizon: new Float32Array([0.7, 0.8, 0.9]), fogSun: new Float32Array([0.7, 0.8, 0.9]) };
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
  // the programs a game will use, made now, while it loads: the first use of one in the middle of a game is a pause
  // (a Pi 3 takes a good while over a shader)
  warm(names) { for (const n of names) this.prog(n); return this; },
  program(vs, fs) {
    const gl = this.gl;
    const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); return s; };
    const p = gl.createProgram(), v = sh(gl.VERTEX_SHADER, vs), f = sh(gl.FRAGMENT_SHADER, fs);
    gl.attachShader(p, v); gl.attachShader(p, f);
    gl.bindAttribLocation(p, 0, "aPos"); gl.bindAttribLocation(p, 0, "aXY"); gl.bindAttribLocation(p, 1, "aNor"); gl.bindAttribLocation(p, 1, "aUV"); gl.bindAttribLocation(p, 2, "aCol");
    gl.linkProgram(p);
    // (one question to the GPU, not three: each waits for its answer; the shaders' own complaints only when it failed)
    if (!gl.getProgramParameter(p, gl.LINK_STATUS) && !gl.isContextLost()) throw new Error(gl.getShaderInfoLog(v) || gl.getShaderInfoLog(f) || gl.getProgramInfoLog(p) || "link");
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
  update(h, mesh) {                                  // a dynamic mesh's verts, again (no new memory: a view of its bytes is kept for each 256 vertices it may hold)
    const gl = this.gl; gl.bindBuffer(gl.ARRAY_BUFFER, h.buf); this.curBuf = null;
    if (mesh.n) {
      const k = (mesh.n + 255) >> 8, vw = mesh.vw || (mesh.vw = []);
      gl.bufferSubData(gl.ARRAY_BUFFER, 0, vw[k] || (vw[k] = new Uint8Array(mesh.buf, 0, Math.min(mesh.cap, k << 8) * 20)));
    }
    h.n = mesh.n;
  },
  free(h) { if (!h) return; this.gl.deleteBuffer(h.buf); if (h.vao && this.vao) this.vao.deleteVertexArrayOES(h.vao); },
  attribs(buf) {
    const gl = this.gl;
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 20, 0);
    gl.enableVertexAttribArray(1); gl.vertexAttribPointer(1, 4, gl.BYTE, true, 20, 12);   // (the normal, and the vertex's spare byte)
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
  // a frame: the camera (eye, target), the field of view (radians, up and down), near and far; clears the screen, or only
  // rect: [x, y, w, h] of it from its top left, in pixels (one view of a split screen: begin() each view in turn)
  begin(ex, ey, ez, tx, ty, tz, fov, near, far, roll, rect) {
    const gl = this.gl, W = this.canvas.width, H = this.canvas.height;
    const x = rect ? rect[0] : 0, y = rect ? rect[1] : 0, w = rect ? rect[2] : W, h = rect ? rect[3] : H;
    gl.viewport(x, H - y - h, w, h); this.vh = h;
    if (rect) { gl.enable(gl.SCISSOR_TEST); gl.scissor(x, H - y - h, w, h); } else gl.disable(gl.SCISSOR_TEST);
    const L = this.L; gl.clearColor(L.fogCol[0], L.fogCol[1], L.fogCol[2], 1);
    gl.depthMask(true); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);   // (tiled GPUs, the Pi's: clearing is what's quick)
    const r = roll || 0;
    const th = Math.atan2(tx - ex, tz - ez);         // (roll: the camera's up leans to the screen's right)
    M4.look(this.view, ex, ey, ez, tx, ty, tz, -Math.sin(r) * Math.cos(th), Math.cos(r), Math.sin(r) * Math.sin(th));
    M4.persp(this.proj, fov, w / h, near, far);
    M4.mul(this.vp, this.proj, this.view);
    M4.planes(this.planes, this.vp);
    this.eye[0] = ex; this.eye[1] = ey; this.eye[2] = ez; this.fov = fov; this.aspect = w / h;
    const sv = this.skyVP, v = this.view;              // the sky's: the same view, turned but never moved
    for (let i = 0; i < 16; i++) sv[i] = v[i]; sv[12] = sv[13] = sv[14] = 0; M4.mul(sv, this.proj, sv);
    if (this.flip) { this.flip = 0; gl.frontFace(gl.CCW); }
    this.frame++; this.cur = null; this.curBuf = null; if (!rect || !rect[1]) { this.calls = 0; this.tris = 0; }
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
    if (u.uAir) gl.uniform2f(u.uAir, L.fog[0], 1 / Math.max(1, L.fog[1] - L.fog[0]));
    if (u.uFogSun) gl.uniform3fv(u.uFogSun, L.fogSun);
    if (u.uSkyVP) gl.uniformMatrix4fv(u.uSkyVP, false, this.skyVP);
    if (u.uFlip) gl.uniform1f(u.uFlip, this.flip);
    if (u.uShine) gl.uniform3fv(u.uShine, this.tint);
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
    gl.uniform1f(u.uPoint, points ? points * (this.vh || this.canvas.height) / 2 / Math.tan(this.fov / 2) : 1);
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
  // ---- the second way (see the shaders above)
  // a picture with choices: o {mip, repeat, nearest, alpha: a second canvas whose red becomes the picture's alpha (any
  // size: it's stretched to fit), data: [Uint8Array (r g b a), width, height] in place of a canvas}
  picture(canvas, o) {
    o = o || {};
    const gl = this.gl, t = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, t);
    if (o.data) gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, o.data[1], o.data[2], 0, gl.RGBA, gl.UNSIGNED_BYTE, o.data[0]);
    else if (o.alpha) {
      const w = canvas.width, h = canvas.height, px = canvas.getContext("2d").getImageData(0, 0, w, h).data;
      const c = document.createElement("canvas"); c.width = w; c.height = h;
      const g = c.getContext("2d", { willReadFrequently: true }); g.imageSmoothingEnabled = true; g.drawImage(o.alpha, 0, 0, w, h);
      const a = g.getImageData(0, 0, w, h).data;
      for (let i = 0; i < px.length; i += 4) px[i + 3] = a[i];
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array(px.buffer));
    } else gl.texImage2D(gl.TEXTURE_2D, 0, o.rgba ? gl.RGBA : gl.RGB, o.rgba ? gl.RGBA : gl.RGB, gl.UNSIGNED_BYTE, canvas);
    const wrap = o.repeat ? gl.REPEAT : gl.CLAMP_TO_EDGE;
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, o.repeat || o.round ? gl.REPEAT : gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, wrap);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, o.nearest ? gl.NEAREST : gl.LINEAR);
    if (o.mip) { gl.generateMipmap(gl.TEXTURE_2D); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_NEAREST); }
    else gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, o.nearest ? gl.NEAREST : gl.LINEAR);
    return t;
  },
  // from now on (until off, or the next begin): mirror images, under the water. Draw the dome, the still world and the
  // moving things again after it, then the water over them.
  mirror(on) {
    const gl = this.gl; this.flip = on ? 1 : 0; gl.frontFace(on ? gl.CW : gl.CCW);
    this.frame++;                                    // (every program hears of it at its next use)
  },
  // the whole frame brighter or tinted (lightning, a flash): r g b times the still world, the sky and the water
  shine(r, g, b) { const t = this.tint; if (t[0] !== r || t[1] !== g || t[2] !== b) { t[0] = r; t[1] = g; t[2] = b; this.frame++; } },
  // a still mesh with its light baked in (Mesh.light, Chunks.upload with a light): moved by nothing, only fogged
  still(h) {
    if (!h || !h.n) return;
    const gl = this.gl; this.use(this.prog("still"));
    this.bind(h); gl.drawArrays(gl.TRIANGLES, 0, h.n); this.calls++; this.tris += h.n / 3;
  },
  // a thing that moves: m its place, tint r g b, glow 0 lit … 1 its own colours, rim: how much its edges catch the sky
  moved(h, m, r, g, b, glow, rim) {
    if (!h || !h.n) return;
    const gl = this.gl, u = this.use(this.prog("move"));
    gl.uniformMatrix4fv(u.uM, false, m || IDENT);
    gl.uniform4f(u.uTint, r == null ? 1 : r, g == null ? 1 : g, b == null ? 1 : b, glow || 0);
    gl.uniform1f(u.uRim, rim || 0);
    this.bind(h); gl.drawArrays(gl.TRIANGLES, 0, h.n); this.calls++; this.tris += h.n / 3;
  },
  // the sky: a picture (Kit.sky paints one) on a dome round the eye, drawn first; turn: how far round it has drifted (0 to 1)
  dome(tex, turn) {
    const gl = this.gl, u = this.use(this.prog("dome"));
    if (!this.domeH) this.domeH = this.upload(Kit.dome());
    gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, tex); gl.uniform1i(u.uTex, 0);
    gl.uniform1f(u.uTurn, turn || 0);
    gl.disable(gl.DEPTH_TEST); gl.disable(gl.CULL_FACE); gl.depthMask(false);
    this.bind(this.domeH); gl.drawArrays(gl.TRIANGLES, 0, this.domeH.n); this.calls++; this.tris += this.domeH.n / 3;
    gl.enable(gl.DEPTH_TEST); gl.enable(gl.CULL_FACE); gl.depthMask(true);
  },
  // the water: h its sheet, tex the world's picture (x0 z0 its corner, size its side), det the ripples (Kit.ripples), t
  // the time; o {glint, foam: colours, see: how much shows through looking down, and more along the water (seeMore),
  // lines: how bright the ripples' lines are away from the sun, foamK, grain: [fine, broad] ripples a world unit,
  // drift: how fast they move, rich}
  water(h, tex, det, x0, z0, size, t, o) {
    if (!h || !h.n) return;
    o = o || {};
    const gl = this.gl, P = (o.rich && this.prog("waterRich")) || this.prog("water"), u = this.use(P), L = this.L;
    gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, det); gl.uniform1i(u.uDet, 1);
    gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, tex); gl.uniform1i(u.uTex, 0);
    gl.uniform4f(u.uMap, x0, z0, 1 / size, 1 / size);
    const g1 = o.grain ? o.grain[0] : 0.13, g2 = o.grain ? o.grain[1] : 0.061, dr = o.drift == null ? 1 : o.drift;
    gl.uniform2f(u.uGrain, g1, g2);
    gl.uniform4f(u.uDrift, (t * 0.06 * dr) % 1, (t * 0.021 * dr) % 1, (-t * 0.017 * dr) % 1, (t * 0.034 * dr) % 1);
    gl.uniform1f(u.uTime, t % 1000);
    const c3 = (loc, c, d) => { const v = c == null ? d : c; gl.uniform3f(loc, ((v >> 16) & 255) / 255, ((v >> 8) & 255) / 255, (v & 255) / 255); };
    c3(u.uGlint, o.glint, 0xffffff); c3(u.uFoam, o.foam, 0xffffff);
    gl.uniform4f(u.uK, this.seeUnder ? (o.see == null ? 0.1 : o.see) : 0, this.seeUnder ? (o.seeMore == null ? 0.62 : o.seeMore) : 0, o.lines == null ? 0.14 : o.lines, o.foamK == null ? 0.8 : o.foamK);
    if (this.seeUnder) { gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA); }
    this.bind(h); gl.drawArrays(gl.TRIANGLES, 0, h.n); this.calls++; this.tris += h.n / 3;
    if (this.seeUnder) gl.disable(gl.BLEND);
  },
  // every see-through thing at once: a dynamic mesh (handle h, sent again here), its vertices' alpha how much, their
  // spare byte 127 for light added, 0 for paint; from, n: only part of it; points: a size, drawn as round-ish dots
  fx(h, mesh, points, from, n) {
    if (!h) return;
    if (mesh) this.update(h, mesh);
    if (!h.n) return;
    const gl = this.gl, u = this.use(this.prog(points ? "fxDots" : "fx"));
    gl.uniform1f(u.uPoint, points ? points * (this.vh || this.canvas.height) / 2 / Math.tan(this.fov / 2) : 1);
    gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA); gl.depthMask(false);
    this.bind(h); gl.drawArrays(points ? gl.POINTS : gl.TRIANGLES, from || 0, n == null ? h.n : n); this.calls++;
    gl.disable(gl.BLEND); gl.depthMask(true);
  },
  // light and air: hex colors ("#rrggbb" or 0xrrggbb) and the sun's direction (towards it)
  light(o) {
    const L = this.L, set = (a, c) => { if (c == null) return; const v = typeof c === "string" ? parseInt(c.slice(1), 16) : c; a[0] = (v >> 16 & 255) / 255; a[1] = (v >> 8 & 255) / 255; a[2] = (v & 255) / 255; };
    set(L.sunCol, o.sunCol); set(L.amb, o.amb); set(L.ground, o.ground); set(L.fogCol, o.fog); set(L.top, o.top); set(L.horizon, o.horizon);
    if (o.fogSun != null) { set(L.fogSun, o.fogSun); this.ownFogSun = true; } else if (o.fog != null && !this.ownFogSun) set(L.fogSun, o.fog);   // (the air towards the sun: its own colour when given)
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
  // where the next frame goes: the whole picture (null), or [x, y, w, h] of it (one view of a split screen: view(), then
  // draw(), sprites and flush() for each view in turn)
  view(rect) { this.rect = rect || null; },
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
    const W = this.w, r = this.rect, ox = r ? r[0] : 0, oy = r ? r[1] : 0, w = r ? r[2] : W, h = r ? r[3] : this.h, u = this.u32, L = this.levels;
    const f = h / 2 / Math.tan(fov / 2), cp = Math.cos(pitch), sp = Math.sin(pitch);
    const fx = Math.sin(yaw), fz = Math.cos(yaw), rx = -Math.cos(yaw), rz = Math.sin(yaw);
    this.cam = { x: cx, y: cy, z: cz, fx, fz, rx, rz, f, cp, sp, hz: h / 2 - f * Math.tan(pitch), yaw, ox, oy, vw: w, vh: h };
    const sky = this.sky, fogC = sky.fog, fogPx = px(fogC[0], fogC[1], fogC[2]);
    const near = this.fogNear, far = this.fogFar;
    const horizon = Math.max(0, Math.min(h, Math.ceil(this.cam.hz)));
    for (let y = 0; y < horizon; y++) {              // the sky: a color a row
      const v = (h / 2 - y - 0.5) / f, dy = (v * cp - sp) / Math.hypot(1, v), t = Math.min(1, Math.max(0, dy / 0.55));
      const k = t * t * (3 - 2 * t), hz = Math.min(1, Math.max(0, (dy + 0.02) / 0.14));
      const r = (fogC[0] + ((sky.horizon[0] + (sky.top[0] - sky.horizon[0]) * k) - fogC[0]) * hz) | 0;
      const g = (fogC[1] + ((sky.horizon[1] + (sky.top[1] - sky.horizon[1]) * k) - fogC[1]) * hz) | 0;
      const b = (fogC[2] + ((sky.horizon[2] + (sky.top[2] - sky.horizon[2]) * k) - fogC[2]) * hz) | 0;
      u.fill(px(r, g, b), (oy + y) * W + ox, (oy + y) * W + ox + w);
    }
    if (sky.hills && horizon > 0) {                  // far hills, by the angle they're at
      const H = sky.hills, n = H.length, hc = sky.hill, hp = px(hc[0], hc[1], hc[2]);
      for (let x = 0; x < w; x++) {
        const a = yaw - Math.atan((x + 0.5 - w / 2) / f);
        let i = Math.floor(((a / TAU) % 1 + 1) % 1 * n);
        const e = H[i];                                // its height: an angle above the horizon
        const top = Math.max(0, Math.floor(h / 2 - f * Math.tan(pitch + e)));
        for (let y = top; y < horizon; y++) u[(oy + y) * W + ox + x] = hp;
      }
    }
    if (!L) { for (let y = horizon; y < h; y++) u.fill(fogPx, (oy + y) * W + ox, (oy + y) * W + ox + w); this.put(); return; }
    const x0 = this.x0, z0 = this.z0, out = this.outside, fr = fogC[0], fg = fogC[1], fb = fogC[2];
    for (let y = horizon; y < h; y++) {              // the ground: each row a line across the world
      const v = (h / 2 - y - 0.5) / f, den = sp - cp * v;
      if (den <= 1e-5) { u.fill(fogPx, (oy + y) * W + ox, (oy + y) * W + ox + w); continue; }
      const t = cy / den, D = t * (cp + sp * v), step = t / f;
      const fog = D <= near ? 0 : D >= far ? 256 : ((D - near) / (far - near) * 256) | 0;
      let i = (oy + y) * W + ox;
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
    this.put();
    this.qn = 0;
  },
  put() { const c = this.cam; if (this.rect) this.ctx.putImageData(this.img, 0, 0, c.ox, c.oy, c.vw, c.vh); else this.ctx.putImageData(this.img, 0, 0); },
  // where a point in the world falls on the screen: [x, y, scale (pixels a world unit), depth], or null behind
  project(x, y, z, o) {
    const c = this.cam, dx = x - c.x, dy = y - c.y, dz = z - c.z;
    const hd = dx * c.fx + dz * c.fz, lat = dx * c.rx + dz * c.rz;
    const d = hd * c.cp - dy * c.sp, up = hd * c.sp + dy * c.cp;
    if (d < 0.5) return null;
    o[0] = c.ox + c.vw / 2 + lat * c.f / d; o[1] = c.oy + c.vh / 2 - up * c.f / d; o[2] = c.f / d; o[3] = d;
    return o;
  },
  // a sprite to draw this frame (all drawn far to near by flush()): s from bake(), standing at x y z, size: world units a pixel of it
  sprite(s, x, y, z, scale, alpha) {
    const P = this._p || (this._p = new Float32Array(4));
    if (!this.project(x, y, z, P) || P[3] > this.fogFar) return;
    const k = P[2] * scale, w = s.c.width * k, hh = s.c.height * k, left = P[0] - s.ax * k;
    const c = this.cam; if (left + w < c.ox || left > c.ox + c.vw || w < 0.6 || P[1] - s.ay * k > c.oy + c.vh) return;
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
    const q = this.queue, n = this.qn, ctx = this.ctx, c = this.cam;
    if (this.rect && c) { ctx.save(); ctx.beginPath(); ctx.rect(c.ox, c.oy, c.vw, c.vh); ctx.clip(); }
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
    if (this.rect && c) ctx.restore();
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
// gl: h the height drawn (the width follows the screen; shown a whole number of times as big, crisp), far the draw
// distance, fps what to hold, look (0 light: a Pi 3's; 1 full: a Pi 4's and up), mirror (0 none, 1 the near world and
// what moves, 2 the sky too: what shows in the water), detail (more small things, nearer than far), wakes, and the
// first way's waves and sun. Every rung holds 60 but the lowest two: pixels are given up before frames, and when even
// the smallest picture runs late it's the frames at a good size (rung 1), then at the smallest. flat: the 2D renderer's.
const LADDER = {
  gl: [
    { h: 216, far: 420, fps: 30, look: 0, mirror: 0, waves: 0, sun: 0, detail: 0.4, wakes: 2 },
    { h: 360, far: 560, fps: 30, look: 0, mirror: 1, waves: 0, sun: 0, detail: 0.6, wakes: 3 },
    { h: 216, far: 420, fps: 60, look: 0, mirror: 0, waves: 0, sun: 0, detail: 0.4, wakes: 2 },
    { h: 270, far: 480, fps: 60, look: 0, mirror: 1, waves: 0, sun: 0, detail: 0.5, wakes: 3 },
    { h: 360, far: 560, fps: 60, look: 0, mirror: 2, waves: 0, sun: 1, detail: 0.6, wakes: 4 },
    { h: 540, far: 640, fps: 60, look: 0, mirror: 2, waves: 0, sun: 1, detail: 0.75, wakes: 4 },
    { h: 540, far: 760, fps: 60, look: 1, mirror: 2, waves: 1, sun: 1, detail: 0.9, wakes: 4 },
    { h: 720, far: 900, fps: 60, look: 1, mirror: 2, waves: 1, sun: 1, detail: 1, wakes: 4 },
    { h: 1080, far: 1100, fps: 60, look: 1, mirror: 2, waves: 1, sun: 1, detail: 1, wakes: 4 }
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
  // A Pi keeps to its own kind's rungs whatever the test says (the test can't see what the browser spends putting the
  // page together at the TV's size, which is most of a Pi 3's frame): the light look for a Pi 3, the full one from a
  // Pi 4. The test can only say "less". The governor finds the rest while the game plays.
  const pi = p.family === "pi3" || p.family === "pi4" || p.family === "pi5";
  if (p.family === "pi3") { rung = 4; top = 5; why = "a Pi 3's GPU"; }
  else if (p.family === "pi4") { rung = 6; top = 7; why = "a Pi 4's GPU"; }
  else if (p.family === "pi5") { rung = 7; top = glTop; why = "a Pi 5's GPU"; }
  else if (p.software) { rung = 3; top = 5; why = "fast software WebGL"; }
  else { rung = 6; top = glTop; why = p.family === "mobile" ? "a mobile GPU" : "a desktop GPU"; }
  if (b.draws != null) {                             // the test says more than the name
    const d = b.draws, f = b.fill;
    if (d < 8 || f < 0.5) { rung = Math.min(rung, 2); why += ", slow in the test"; }
    else if (d < 24 || f < 1.5) { rung = Math.min(rung, 3); why += ", modest in the test"; }
    else if (!pi && d >= 512 && f >= 16) { rung = Math.max(rung, 8); top = glTop; why += ", strong in the test"; }
    else if (!pi && d >= 256 && f >= 8) { rung = Math.max(rung, 7); top = glTop; why += ", good in the test"; }
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
  gl.disable(gl.SCISSOR_TEST);                       // (a split screen's last view may have left it on)
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
  this.workMs = 0;                                   // the game's work a frame drawn, smoothed (ms)
  this.ran = { frames: 0, late: 0, worst: 0, secs: 0, work: 0, low: 1e9 };   // how it ran since it started (or since ran was read): for a report
}
Governor.prototype = {
  get cur() { return this.ladder[this.rung]; },
  tick(now) {
    const iv = 1000 / this.ladder[this.rung].fps;
    if (this.last && now - this.last < iv - 4) return false;
    const gap = this.last ? now - this.last : iv;
    this.last = now;
    this.frames++;
    if (now - this.fpsAt >= 1000) { this.fps = Math.round(this.frames * 1000 / (now - this.fpsAt)); this.frames = 0; if (this.fpsAt && now >= this.wait && this.fps < this.ran.low) this.ran.low = this.fps; this.fpsAt = now; }
    if (document.hidden || gap > 400) { this.reset(now); return true; }   // (back from elsewhere: not the game's doing)
    if (now >= this.wait) { const R = this.ran; R.frames++; R.secs += gap / 1000; if (gap > 25) R.late++; if (gap > R.worst) R.worst = gap; }
    if (now < this.wait) return true;
    if (!this.win) this.win = now;
    this.n++; if (gap > iv * 1.5) this.late++;
    if (now - this.win >= 2000) this.judge(now, iv);
    return true;
  },
  work(ms) { this.workSum += ms; this.workMs += (ms - this.workMs) * 0.05; if (ms > this.ran.work) this.ran.work = ms; },
  miss(k) { if (performance.now() >= this.wait) this.late += k; },   // frames drawn late elsewhere (a Ray game's helpers, still busy)
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
// Its light worked out now and kept in its colours, for a still world drawn with GL.still (nothing to work out a frame
// but where each vertex is): L {sun: towards it, sunCol, amb, ground} as GL.light takes them; o {shade(x, y, z) → how
// much of the sun reaches there (0 in shadow … 1), sky(x, y, z, ny) → how much of the sky's light (1: all of it; less
// in a hollow or at the foot of something)}. Vertices that are their own light (glow, or alpha 254) are left as they are.
Mesh.prototype.light = function (L, o) {
  o = o || {};
  const f = this.f, i8 = this.i8, u8 = this.u8, sun = L.sun, sl = Math.hypot(sun[0], sun[1], sun[2]) || 1, sx = sun[0] / sl, sy = sun[1] / sl, sz = sun[2] / sl;
  const sc = hexRGB(L.sunCol), am = hexRGB(L.amb), gr = hexRGB(L.ground);
  for (let i = this.lit || 0; i < this.n; i++) {
    const q = i * 20;
    if (u8[q + 19] === 254) { i8[q + 15] = 127; u8[q + 19] = 255; continue; }
    if (i8[q + 15] > 0) continue;
    const nx = i8[q + 12] / 127, ny = i8[q + 13] / 127, nz = i8[q + 14] / 127, x = f[i * 5], y = f[i * 5 + 1], z = f[i * 5 + 2];
    let d = nx * sx + ny * sy + nz * sz; if (d < 0) d = 0;
    if (d > 0 && o.shade) d *= o.shade(x + nx * 0.6, y + ny * 0.6 + 0.2, z + nz * 0.6);
    const k = 0.5 + 0.5 * ny, a = o.sky ? o.sky(x, y, z, ny) : 1;
    const r = u8[q + 16] * (((gr[0] + (am[0] - gr[0]) * k) * a + sc[0] * d) / 255), g = u8[q + 17] * (((gr[1] + (am[1] - gr[1]) * k) * a + sc[1] * d) / 255), b = u8[q + 18] * (((gr[2] + (am[2] - gr[2]) * k) * a + sc[2] * d) / 255);
    u8[q + 16] = r > 255 ? 255 : r; u8[q + 17] = g > 255 ? 255 : g; u8[q + 18] = b > 255 ? 255 : b;
  }
  this.lit = this.n;                                 // (what's built after this is lit by the next call)
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
  // the sky's dome (GL.dome): rings from straight up down to just under the horizon; each vertex's colour says where
  // on the sky's picture it is (red: round, green: down). More of the picture is given to the sky near the horizon.
  dome() {
    const m = new Mesh(24 * 8 * 6), N = 24, R = 100, V = [0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875, 1], pt = [];
    for (let k = 0; k < V.length; k++) {
      const e = Math.PI / 2 * (1 - V[k]) * (1 - V[k]), ring = [];
      for (let i = 0; i <= N; i++) { const a = i / N * TAU; ring.push([Math.sin(a) * Math.cos(e) * R, Math.sin(e) * R, Math.cos(a) * Math.cos(e) * R, Math.round(i / N * 255), Math.round(V[k] * 255)]); }
      pt.push(ring);
    }
    const put = p => m.put(p[0], p[1], p[2], 0, -1, 0, p[3], p[4], 0, 255);
    for (let k = 0; k + 1 < pt.length; k++) for (let i = 0; i < N; i++) {
      const a = pt[k][i], b = pt[k][i + 1], c = pt[k + 1][i + 1], d = pt[k + 1][i];
      put(a); put(d); put(c); put(a); put(c); put(b);
    }
    return m;
  },
  // where a height in the sky (radians up from the horizon) falls on the sky's picture, 0 its top … 1 the horizon
  skyV(e) { return 1 - Math.sqrt(Math.max(0, e) / (Math.PI / 2)); },
  // a sky painted once, for the dome: o {w, h (512 × 256), top, mid, horizon, haze (colours, top to bottom), sun: {az,
  // el (radians), size (radians across), col, glow (colour of the light round it), halo: how wide that is, bars: a low
  // sun cut by dark bars}, clouds: {n, col, lit (their sunward side), lo, hi (radians), len}, stars (how many), ridges:
  // [{h (radians), col, rough, seed}] far mountains, nearest last, seed}
  sky(o) {
    const W = o.w || 512, H = o.h || 256, c = document.createElement("canvas"); c.width = W; c.height = H;
    const g = c.getContext("2d"), rnd = U.rand(o.seed || 7), V = Kit.skyV, hex = U.hex;
    const gr = g.createLinearGradient(0, 0, 0, H);
    gr.addColorStop(0, hex(o.top)); gr.addColorStop(V(0.55), hex(U.mix(o.top, o.mid == null ? o.horizon : o.mid, 0.55)));
    gr.addColorStop(V(0.2), hex(o.mid == null ? U.mix(o.top, o.horizon, 0.7) : o.mid)); gr.addColorStop(V(0.045), hex(o.horizon)); gr.addColorStop(1, hex(o.haze == null ? o.horizon : o.haze));
    g.fillStyle = gr; g.fillRect(0, 0, W, H);
    for (let i = 0; i < (o.stars || 0); i++) {         // stars: more of them high up
      const e = 0.12 + rnd() * rnd() * 1.3, b = 0.35 + rnd() * 0.65;
      g.fillStyle = "rgba(" + (215 + rnd() * 40 | 0) + "," + (225 + rnd() * 30 | 0) + ",255," + b.toFixed(2) + ")"; g.fillRect(rnd() * W | 0, V(e) * H | 0, rnd() < 0.12 ? 2 : 1, 1);
    }
    const S = o.sun;
    const oval = (az, el, r, fill) => {                // a round thing in the sky, as the picture has to hold it; twice where it crosses the picture's edge
      const x = ((az / TAU) % 1 + 1) % 1 * W, y0 = V(el + r) * H, y1 = V(el - r) * H, rx = r / TAU * W / Math.max(0.3, Math.cos(el)), ry = (y1 - y0) / 2;
      for (const dx of [0, -W, W]) { if (x + dx + rx < 0 || x + dx - rx > W) continue; fill(x + dx, (y0 + y1) / 2, rx, Math.max(0.5, ry)); }
    };
    if (S) {
      const halo = (r, col, a) => oval(S.az, S.el, r, (x, y, rx, ry) => {
        g.save(); g.translate(x, y); g.scale(1, ry / rx);
        const rg = g.createRadialGradient(0, 0, 0, 0, 0, rx); rg.addColorStop(0, col + a); rg.addColorStop(0.35, col + "55"); rg.addColorStop(1, col + "00");
        g.fillStyle = rg; g.fillRect(-rx, -rx, rx * 2, rx * 2); g.restore();
      });
      halo((S.halo || 0.9), hex(S.glow == null ? S.col : S.glow), "aa");
      halo((S.size || 0.1) * 2.2, hex(S.col), "ff");
    }
    const C = o.clouds;
    if (C) for (let i = 0; i < C.n; i++) {             // clouds: long thin ones low down, each a few soft ovals, their sunward ends lit
      const el = (C.lo || 0.03) + rnd() * rnd() * ((C.hi || 0.7) - (C.lo || 0.03)), az = rnd() * TAU, len = (C.len || 0.5) * (0.4 + rnd()) * (1.4 - el), th = 0.012 + rnd() * 0.03 + el * 0.05;
      const near = S ? Math.max(0, Math.cos(az - S.az)) : 0, col = U.mix(C.col, C.lit == null ? C.col : C.lit, near * near * (0.5 + rnd() * 0.5));
      for (let k = 0; k < 5; k++) {
        const a2 = az + (k - 2) * len * 0.22 + (rnd() - 0.5) * len * 0.2, e2 = el + (rnd() - 0.5) * th, r = len * (0.2 + rnd() * 0.25);
        const x = ((a2 / TAU) % 1 + 1) % 1 * W, y = V(e2) * H, rx = r / TAU * W, ry = Math.max(1, (V(e2 - th) - V(e2 + th)) * H * (0.5 + rnd() * 0.5));
        for (const dx of [0, -W, W]) {
          if (x + dx + rx < 0 || x + dx - rx > W) continue;
          g.save(); g.translate(x + dx, y); g.scale(1, ry / rx);
          const rg = g.createRadialGradient(0, 0, 0, 0, 0, rx); rg.addColorStop(0, hex(col) + (C.a || "d0")); rg.addColorStop(0.6, hex(col) + "70"); rg.addColorStop(1, hex(col) + "00");
          g.fillStyle = rg; g.fillRect(-rx, -rx, rx * 2, rx * 2); g.restore();
        }
      }
    }
    if (S) {                                           // the sun (or moon) itself, over its light and the clouds behind it: row by row, so it's round on the dome
      const r = (S.size || 0.1) / 2, c0 = hexRGB(S.col), c1 = hexRGB(S.low == null ? S.col : S.low), x0 = ((S.az / TAU) % 1 + 1) % 1 * W;
      const bars = S.bars ? hex(S.bars === true ? o.horizon : S.bars) : null;
      for (let y = Math.floor(V(S.el + r) * H); y < H; y++) {
        const e = Math.PI / 2 * (1 - (y + 0.5) / H) * (1 - (y + 0.5) / H), de = e - S.el; if (Math.abs(de) >= r) { if (de < 0) break; continue; }
        const hw = Math.sqrt(r * r - de * de) / Math.max(0.3, Math.cos(e)) / TAU * W, t = (r - de) / (2 * r);   // t: 0 its top … 1 its foot
        const bar = bars && t > 0.4 && ((t - 0.4) * 9.5) % 1 < 0.2 + (t - 0.4) * 0.5;
        g.fillStyle = bar ? bars : "rgb(" + (c0[0] + (c1[0] - c0[0]) * t | 0) + "," + (c0[1] + (c1[1] - c0[1]) * t | 0) + "," + (c0[2] + (c1[2] - c0[2]) * t | 0) + ")";
        for (const dx of [0, -W, W]) if (x0 + dx + hw > 0 && x0 + dx - hw < W) g.fillRect(x0 + dx - hw, y, hw * 2, 1);
      }
    }
    for (const r of o.ridges || []) {                  // far mountains: a line of heights round the horizon, the same at both edges
      const rr = U.rand(r.seed || 3), P = 64, a1 = [], a2 = [], a3 = [];
      for (let i = 0; i < P; i++) { a1.push(rr()); a2.push(rr()); a3.push(rr()); }
      const at = (arr, t, n) => { const x = ((t % 1) + 1) % 1 * n, i = x | 0, fz = x - i, sm = fz * fz * (3 - 2 * fz); return arr[i % n] + (arr[(i + 1) % n] - arr[i % n]) * sm; };
      g.fillStyle = hex(r.col); g.beginPath(); g.moveTo(0, H);
      for (let x = 0; x <= W; x += 2) {
        const t = x / W, hgt = r.h * (0.25 + 0.75 * (at(a1, t, 7) * 0.55 + at(a2, t, 19) * 0.3 + at(a3, t, 53) * 0.15 * (r.rough == null ? 1 : r.rough)));
        g.lineTo(x, V(hgt) * H);
      }
      g.lineTo(W, H); g.closePath(); g.fill();
    }
    if (o.haze != null) { const hz = g.createLinearGradient(0, V(0.05) * H, 0, H); hz.addColorStop(0, hex(o.haze) + "00"); hz.addColorStop(1, hex(o.haze) + (o.hazeA || "e0")); g.fillStyle = hz; g.fillRect(0, V(0.05) * H, W, H); }
    // a little grain, so the long fades show no bands: a small tile of light and dark specks laid over all of it (the
    // browser's own fill: a loop over half a million pixels here is a tenth of a second on a Pi 3)
    const t = document.createElement("canvas"); t.width = t.height = 64;
    const tg = t.getContext("2d"), td = tg.createImageData(64, 64), tp = td.data;
    for (let i = 0; i < tp.length; i += 4) { const v = rnd() < 0.5 ? 0 : 255; tp[i] = tp[i + 1] = tp[i + 2] = v; tp[i + 3] = rnd() * 9; }
    tg.putImageData(td, 0, 0); g.fillStyle = g.createPattern(t, "repeat"); g.fillRect(0, 0, W, H);
    return c;
  },
  // ripples for the water (GL.water's det): n × n and the same at every edge. Red and green: two nets of thin bright
  // lines (the edges between cells scattered over the picture: light on a ruffled surface, as cartoons draw it), drawn
  // over each other and drifting apart; blue: broad soft swells. Returns what GL.picture takes: {data: [bytes, n, n]…}
  ripples(n, seed) {
    n = n || 128; const rnd = U.rand(seed || 5), px = new Uint8Array(n * n * 4);
    const cells = (C) => { const p = new Float32Array(C * C * 2); for (let i = 0; i < p.length; i++) p[i] = rnd(); return { C, p }; };
    const net = (K, u, v, thin) => {                  // 1 on the line between the two nearest points, falling off either side
      const C = K.C, x = u * C, y = v * C, ci = Math.floor(x), cj = Math.floor(y); let f1 = 9, f2 = 9;
      for (let dj = -1; dj <= 1; dj++) for (let di = -1; di <= 1; di++) {
        const i = ((ci + di) % C + C) % C, j = ((cj + dj) % C + C) % C, q = (j * C + i) * 2;
        const d = Math.hypot(ci + di + K.p[q] - x, cj + dj + K.p[q + 1] - y);
        if (d < f1) { f2 = f1; f1 = d; } else if (d < f2) f2 = d;
      }
      const e = 1 - (f2 - f1) / thin; return e <= 0 ? 0 : e * e;
    };
    const A = cells(7), B = cells(5), S1 = new Float32Array(16).map(() => rnd()), S2 = new Float32Array(64).map(() => rnd());
    const soft = (a, k, x, y) => {
      const fx = x * k, fy = y * k, i = fx | 0, j = fy | 0, tx = fx - i, ty = fy - j, sx = tx * tx * (3 - 2 * tx), sy = ty * ty * (3 - 2 * ty), i1 = (i + 1) % k, j1 = (j + 1) % k;
      const p = a[j * k + i], q = a[j * k + i1], r = a[j1 * k + i], t = a[j1 * k + i1];
      return p + (q - p) * sx + (r - p) * sy + (p - q - r + t) * sx * sy;
    };
    for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
      const u = x / n, v = y / n, o = (y * n + x) * 4;
      px[o] = Math.min(255, net(A, u, v, 0.2) * 255) | 0; px[o + 1] = Math.min(255, net(B, v, u, 0.16) * 255) | 0;
      px[o + 2] = (soft(S1, 4, u, v) * 0.65 + soft(S2, 8, u, v) * 0.35) * 255 | 0; px[o + 3] = 255;
    }
    return { data: [px, n, n], repeat: true, mip: true };
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
    let tx = this.tx[i] + (this.tx[j] - this.tx[i]) * t, tz = this.tz[i] + (this.tz[j] - this.tz[i]) * t; const l = Math.sqrt(tx * tx + tz * tz) || 1;
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
  // bake: {light, shade, sky} (Mesh.light's): the world's light worked out now and kept in its colours, its glowing
  // things put in with the rest (one mesh a chunk, and its small things), drawn with GL.still
  upload(g3, bake) {
    this.free(); this.g3 = g3; this.baked = !!bake;
    for (const c of this.cells) {
      if (!c) continue;
      if (bake) {
        c.base.light(bake.light, bake); c.detail.light(bake.light, bake);
        if (c.glow.n) { for (let i = 0; i < c.glow.n; i++) c.glow.i8[i * 20 + 15] = 127; c.base = Mesh.join([c.base, c.glow]); c.base.lit = c.base.n; c.glow = new Mesh(8); }
      }
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
    for (let i = 0; i < this.list.length; i++) { const c = this.list[i]; c.d = Math.sqrt((c.x - ex) * (c.x - ex) + (c.z - ez) * (c.z - ez)) - c.r; if (c.d < far && g3.sees(c.x, c.y, c.z, c.r)) o[k++] = c; }
    for (let i = 1; i < k; i++) { const e = o[i]; let j = i - 1; while (j >= 0 && o[j].d > e.d) { o[j + 1] = o[j]; j--; } o[j + 1] = e; }
    for (let i = 0; i < k; i++) {
      const c = o[i];
      if (this.baked) { g3.still(c.base); if (c.detail && c.d < far * (detailK == null ? 1 : detailK)) g3.still(c.detail); continue; }
      g3.lit(c.base, null, 1, 1, 1, 0);
      if (c.detail && c.d < far * (detailK == null ? 1 : detailK)) g3.lit(c.detail, null, 1, 1, 1, 0);
      if (c.glow) g3.lit(c.glow, null, 1, 1, 1, 1);
    }
    return k;
  },
  free() { if (this.g3) for (const c of this.list) { this.g3.free(c.base); this.g3.free(c.detail); this.g3.free(c.glow); } this.list.length = 0; this.order.length = 0; }
};

// ---------------------------------------------------------------- land: ground with height over a square world (coasts,
// islands, hills, a gorge's walls), a height at each corner of an n × n grid. The GPU draws it as chunks of flat-lit
// triangles where it's near or above the water; the 2D renderer has it painted into the ground's picture, shaded by
// its slopes, with its banks stood up where it leaves the water (banks()); anything can ask its height (to float, or to
// bump into the shore).
function Land(size, n, base) {
  this.size = size; this.n = n; this.N = n + 1; this.cell = size / n; this.half = size / 2; this.jit = 0.04;
  this.h = new Float32Array(this.N * this.N).fill(base == null ? -4 : base);
}
Land.prototype = {
  fill(fn) {                                         // fn(x, z, now) → the height at each corner
    const N = this.N, c = this.cell, h = this.h;
    for (let j = 0; j < N; j++) for (let i = 0; i < N; i++) { const k = j * N + i; h[k] = fn(-this.half + i * c, -this.half + j * c, h[k]); }
    return this;
  },
  at(x, z) {                                         // the height at x z, smoothly between the corners (past the edge: the edge's)
    const n = this.n, N = this.N, h = this.h;
    let fx = (x + this.half) / this.cell, fz = (z + this.half) / this.cell;
    fx = fx < 0 ? 0 : fx > n ? n : fx; fz = fz < 0 ? 0 : fz > n ? n : fz;
    let i = fx | 0, j = fz | 0; if (i >= n) i = n - 1; if (j >= n) j = n - 1;
    const tx = fx - i, tz = fz - j, k = j * N + i, a = h[k], b = h[k + 1], c = h[k + N], d = h[k + N + 1];
    return a + (b - a) * tx + (c - a) * tz + (a - b - c + d) * tx * tz;
  },
  slope(x, z, out) {                                 // which way it rises at x z: out = [rise a unit along x, along z]
    const e = this.cell * 0.5;
    out[0] = (this.at(x + e, z) - this.at(x - e, z)) / (2 * e); out[1] = (this.at(x, z + e) - this.at(x, z - e)) / (2 * e);
    return out;
  },
  // each cell's two triangles (split along the diagonal that follows the ground): corners, and a colour from
  // col(height, steepness: 0 flat … 1 a wall, x, z); fn(ax, ay, az, bx, by, bz, cx, cy, cz, col, nx, ny, nz) for every
  // cell with a corner above water - under (the shore carries on under the sea)
  each(col, water, under, fn) {
    const N = this.N, h = this.h, c = this.cell, lo = (water || 0) - (under == null ? 2 : under);
    const tri = (ax, ay, az, bx, by, bz, cx, cy, cz) => {
      const ux = bx - ax, uy = by - ay, uz = bz - az, vx = cx - ax, vy = cy - ay, vz = cz - az;
      let nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx; const l = Math.hypot(nx, ny, nz) || 1;
      nx /= l; ny /= l; nz /= l; if (ny < 0) { nx = -nx; ny = -ny; nz = -nz; }
      fn(ax, ay, az, bx, by, bz, cx, cy, cz, col((ay + by + cy) / 3, 1 - ny, (ax + bx + cx) / 3, (az + bz + cz) / 3), nx, ny, nz);
    };
    for (let j = 0; j < this.n; j++) for (let i = 0; i < this.n; i++) {
      const k = j * N + i, a = h[k], b = h[k + 1], d = h[k + N], e = h[k + N + 1];
      if (a < lo && b < lo && d < lo && e < lo) continue;
      const x0 = -this.half + i * c, z0 = -this.half + j * c, x1 = x0 + c, z1 = z0 + c;
      if (Math.abs(a - e) <= Math.abs(b - d)) { tri(x0, a, z0, x1, b, z0, x1, e, z1); tri(x0, a, z0, x1, e, z1, x0, d, z1); }
      else { tri(x0, a, z0, x1, b, z0, x0, d, z1); tri(x1, b, z0, x1, e, z1, x0, d, z1); }
    }
  },
  // The cells of high ground with no drop near them: a plateau behind its cliffs, the top of a tableland. From low down
  // (on the water, on a road below) nothing of them shows but a far rise now and then, yet they can be most of a land's
  // triangles. o {above: only ground higher than this (6), drop: how much lower anything within `near` cells may be (4,
  // 3)}. Returns a mark for each cell (n × n).
  inner(o) {
    o = o || {}; const n = this.n, N = this.N, h = this.h, above = o.above == null ? 6 : o.above, drop = o.drop == null ? 4 : o.drop, R = o.near || 3;
    const v = new Uint8Array(N * N);
    for (let j = 0; j < N; j++) for (let i = 0; i < N; i++) {
      const hh = h[j * N + i]; if (hh < above) continue;
      let ok = 1;
      for (let dj = -R; dj <= R && ok; dj++) for (let di = -R; di <= R; di++) { const x = i + di, z = j + dj; if (x < 0 || z < 0 || x > n || z > n) continue; if (h[z * N + x] < hh - drop) { ok = 0; break; } }
      v[j * N + i] = ok;
    }
    const out = new Uint8Array(n * n);
    for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) out[j * n + i] = v[j * N + i] & v[j * N + i + 1] & v[(j + 1) * N + i] & v[(j + 1) * N + i + 1];
    return out;
  },
  // its triangles into chunks (Chunks: one mesh a chunk, layer "base" unless said), faceted like everything else.
  // o {coarse: a mark for each cell (inner()): where a whole square of 8, 6, 4 or 3 cells a side is marked, the square
  // is two big triangles with a skirt round them (to hide where they don't quite meet the finer ground) in place of
  // 128, 72, 32 or 18;
  // under: how far below the water a cell's highest corner may be and still be built (2; less where the water hides
  // what's under it anyway, or shows it: a bed of shallows built as triangles is most of a map's)}
  mesh(chunks, col, water, layer, o) {
    const mark = o && o.coarse, n = this.n, N = this.N, h = this.h, c = this.cell, done = mark ? new Uint8Array(n * n) : null;
    const tri = (ax, ay, az, bx, by, bz, cx, cy, cz, k) => {
      const m = chunks.mesh((ax + bx + cx) / 3, (az + bz + cz) / 3, layer), jit = m.jit;
      m.at(0, 0, 0); m.jit = this.jit;
      m.tri(ax, ay, az, bx, by, bz, cx, cy, cz, k, (ax + bx + cx) / 3, Math.min(ay, by, cy) - 10, (az + bz + cz) / 3);
      m.jit = jit;
    };
    if (mark) {
      // the biggest squares of marked cells, wherever they fall (8, 6, 4, then 3 cells a side); a side shared whole with
      // a square of the same size needs no skirt (the two meet along one straight edge)
      const blk = new Int32Array(n * n).fill(-1), list = [];
      for (const B of [8, 6, 4, 3]) for (let j = 0; j + B <= n; j++) for (let i = 0; i + B <= n; i++) {
        let all = 1; for (let dj = 0; dj < B && all; dj++) for (let di = 0; di < B; di++) if (!mark[(j + dj) * n + i + di] || done[(j + dj) * n + i + di]) { all = 0; break; }
        if (!all) continue;
        for (let dj = 0; dj < B; dj++) for (let di = 0; di < B; di++) { done[(j + dj) * n + i + di] = 1; blk[(j + dj) * n + i + di] = list.length; }
        list.push([i, j, B]);
      }
      const same = (i, j, B, ci, cj, along) => { if (ci < 0 || cj < 0 || ci >= n || cj >= n) return false; const q = blk[cj * n + ci]; if (q < 0) return false; const L = list[q]; return L[2] === B && (along ? L[0] === i : L[1] === j); };
      for (const [i, j, B] of list) {
        const x0 = -this.half + i * c, z0 = -this.half + j * c, x1 = x0 + B * c, z1 = z0 + B * c;
        const a = h[j * N + i], b = h[j * N + i + B], d = h[(j + B) * N + i], e = h[(j + B) * N + i + B], k = col((a + b + d + e) / 4, 0, (x0 + x1) / 2, (z0 + z1) / 2), sk = B * 0.8;
        tri(x0, a, z0, x1, b, z0, x1, e, z1, k); tri(x0, a, z0, x1, e, z1, x0, d, z1, k);
        if (!same(i, j, B, i, j - 1, true)) { tri(x0, a, z0, x0, a - sk, z0, x1, b - sk, z0, k); tri(x0, a, z0, x1, b - sk, z0, x1, b, z0, k); }
        if (!same(i, j, B, i + B, j, false)) { tri(x1, b, z0, x1, b - sk, z0, x1, e - sk, z1, k); tri(x1, b, z0, x1, e - sk, z1, x1, e, z1, k); }
        if (!same(i, j, B, i, j + B, true)) { tri(x1, e, z1, x1, e - sk, z1, x0, d - sk, z1, k); tri(x1, e, z1, x0, d - sk, z1, x0, d, z1, k); }
        if (!same(i, j, B, i - 1, j, false)) { tri(x0, d, z1, x0, d - sk, z1, x0, a - sk, z0, k); tri(x0, d, z1, x0, a - sk, z0, x0, a, z0, k); }
      }
    }
    const under = o && o.under != null ? o.under : 2, lo = (water || 0) - under;
    this.each(col, water, under, (ax, ay, az, bx, by, bz, cx, cy, cz, k) => {
      if (o && o.under != null && ay < lo && by < lo && cy < lo) return;   // (a cell's other half, wholly under the water)
      if (done) { const i = Math.min(n - 1, Math.floor(((ax + bx + cx) / 3 + this.half) / c)), j = Math.min(n - 1, Math.floor(((az + bz + cz) / 3 + this.half) / c)); if (done[j * n + i]) return; }
      tri(ax, ay, az, bx, by, bz, cx, cy, cz, k);
    });
    return this;
  },
  // painted into a picture of the world from above (g: its 2D context, k: its pixels a world unit, its 0 0 at the world's
  // corner): ground above the water in its colours, lit on its slopes by sun (towards it: [x, y, z]); under the water
  // a wash of shallow ("#rrggbb" or 0xrrggbb) that fades out by `depth` down. noGround: the shallows alone (where the
  // GPU draws the ground itself)
  paint(g, k, col, sun, water, shallow, depth, noGround) {
    const W = g.canvas.width, H = g.canvas.height, img = g.getImageData(0, 0, W, H), d8 = img.data, w = water || 0, dp = depth || 4;
    const sl = Math.hypot(sun[0], sun[1], sun[2]), s0 = sun[0] / sl, s1 = sun[1] / sl, s2 = sun[2] / sl, sh = hexRGB(shallow);
    // the ground: each triangle filled (a pixel's centre inside it), lit as the GPU would light it
    if (!noGround) this.each(col, w, 0, (ax, ay, az, bx, by, bz, cx, cy, cz, c, nx, ny, nz) => {
      if (ay < w && by < w && cy < w) return;
      const L = 0.62 + 0.5 * Math.max(0, nx * s0 + ny * s1 + nz * s2), r = Math.min(255, ((c >> 16) & 255) * L) | 0, gg = Math.min(255, ((c >> 8) & 255) * L) | 0, b = Math.min(255, (c & 255) * L) | 0;
      const X0 = Math.max(0, Math.floor((Math.min(ax, bx, cx) + this.half) * k)), X1 = Math.min(W - 1, Math.ceil((Math.max(ax, bx, cx) + this.half) * k));
      const Z0 = Math.max(0, Math.floor((Math.min(az, bz, cz) + this.half) * k)), Z1 = Math.min(H - 1, Math.ceil((Math.max(az, bz, cz) + this.half) * k));
      const den = (bz - cz) * (ax - cx) + (cx - bx) * (az - cz) || 1;
      for (let pz = Z0; pz <= Z1; pz++) for (let px_ = X0; px_ <= X1; px_++) {
        const x = (px_ + 0.5) / k - this.half, z = (pz + 0.5) / k - this.half;
        const l1 = ((bz - cz) * (x - cx) + (cx - bx) * (z - cz)) / den, l2 = ((cz - az) * (x - cx) + (ax - cx) * (z - cz)) / den, l3 = 1 - l1 - l2;
        if (l1 < -1e-6 || l2 < -1e-6 || l3 < -1e-6) continue;
        const o = (pz * W + px_) * 4;
        if (l1 * ay + l2 * by + l3 * cy < w) continue;   // (this pixel's under the water: the wash, below)
        d8[o] = r; d8[o + 1] = gg; d8[o + 2] = b;
      }
    });
    // the shallows: pixel by pixel from the height under each, in the cells that have some (not open water, nor dry land)
    const N = this.N, h = this.h, cp = this.cell * k;
    for (let j = 0; j < this.n; j++) for (let i = 0; i < this.n; i++) {
      const q = j * N + i, a0 = h[q], b0 = h[q + 1], c0 = h[q + N], d0 = h[q + N + 1];
      if (Math.max(a0, b0, c0, d0) < w - dp || Math.min(a0, b0, c0, d0) >= w) continue;
      const X0 = Math.max(0, Math.floor(i * cp)), X1 = Math.min(W, Math.ceil((i + 1) * cp)), Z0 = Math.max(0, Math.floor(j * cp)), Z1 = Math.min(H, Math.ceil((j + 1) * cp));
      for (let pz = Z0; pz < Z1; pz++) for (let px_ = X0; px_ < X1; px_++) {
        const hh = this.at((px_ + 0.5) / k - this.half, (pz + 0.5) / k - this.half);
        if (hh >= w || hh < w - dp) continue;
        const a = (1 - (w - hh) / dp) * 0.8, o = (pz * W + px_) * 4;
        d8[o] += (sh[0] - d8[o]) * a; d8[o + 1] += (sh[1] - d8[o + 1]) * a; d8[o + 2] += (sh[2] - d8[o + 2]) * a;
      }
    }
    g.putImageData(img, 0, 0);
  },
  // where it leaves the water, stood up for the 2D renderer: a list of banks, each from two points on the waterline up to
  // the ground a cell inland ({ax, az, bx, bz, ah, bh, x2..: the tops, nx nz: facing out, col}), found on the grid
  banks(col, water) {
    const N = this.N, h = this.h, c = this.cell, w = water || 0, out = [], P = [];
    const cut = (x0, z0, h0, x1, z1, h1) => { const t = (w - h0) / (h1 - h0); P.push(x0 + (x1 - x0) * t, z0 + (z1 - z0) * t); };
    for (let j = 0; j < this.n; j++) for (let i = 0; i < this.n; i++) {
      const k = j * N + i, a = h[k], b = h[k + 1], d = h[k + N], e = h[k + N + 1];
      const up = (a >= w) + (b >= w) + (d >= w) + (e >= w); if (up === 0 || up === 4) continue;
      const x0 = -this.half + i * c, z0 = -this.half + j * c, x1 = x0 + c, z1 = z0 + c;
      P.length = 0;                                    // where the waterline crosses the cell's sides (marching squares)
      if ((a >= w) !== (b >= w)) cut(x0, z0, a, x1, z0, b);
      if ((b >= w) !== (e >= w)) cut(x1, z0, b, x1, z1, e);
      if ((e >= w) !== (d >= w)) cut(x1, z1, e, x0, z1, d);
      if ((d >= w) !== (a >= w)) cut(x0, z1, d, x0, z0, a);
      for (let q = 0; q + 3 < P.length; q += 4) {
        const ax = P[q], az = P[q + 1], bx = P[q + 2], bz = P[q + 3], mx = (ax + bx) / 2, mz = (az + bz) / 2;
        let nx = -(bz - az), nz = bx - ax; const l = Math.hypot(nx, nz) || 1; nx /= l; nz /= l;
        if (this.at(mx + nx * c * 0.5, mz + nz * c * 0.5) > this.at(mx - nx * c * 0.5, mz - nz * c * 0.5)) { nx = -nx; nz = -nz; }   // (facing the water)
        const ix = -nx * c, iz = -nz * c, ah = Math.max(0.4, this.at(ax + ix, az + iz)), bh = Math.max(0.4, this.at(bx + ix, bz + iz));
        out.push({ ax, az, bx, bz, ah, bh, tx: ix, tz: iz, x: mx, z: mz, nx, nz, col: col((ah + bh) / 2, Math.min(1, Math.max(ah, bh) / c / 1.5), mx, mz) });
      }
    }
    return out;
  }
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
  ribbon(m, y, col, w0, dw, alpha, add) {            // (add: 127 when it's light, for GL.fx)
    const p = this.p, r = (col >> 16) & 255, g = (col >> 8) & 255, b = col & 255, e = add || 0, S = m.s; S[1] = y;
    for (let i = 0; i + 1 < this.n; i++) {
      const ax = p[i * 3], az = p[i * 3 + 1], bx = p[i * 3 + 3], bz = p[i * 3 + 4];
      let dx = bx - ax, dz = bz - az; const l = Math.sqrt(dx * dx + dz * dz) || 1; dx /= l; dz /= l;
      const wa = w0 + i * dw, wb = w0 + (i + 1) * dw;
      const aa = U.clamp((1 - i / this.max) * p[i * 3 + 2] * alpha, 0, 255) | 0, ab = U.clamp((1 - (i + 1) / this.max) * p[i * 3 + 5] * alpha, 0, 255) | 0;
      if (m.n + 6 > m.cap) return;
      S[0] = ax - dz * wa; S[2] = az + dx * wa; m.v(r, g, b, aa, e); S[0] = bx - dz * wb; S[2] = bz + dx * wb; m.v(r, g, b, ab, e); S[0] = bx + dz * wb; S[2] = bz - dx * wb; m.v(r, g, b, ab, e);
      S[0] = ax - dz * wa; S[2] = az + dx * wa; m.v(r, g, b, aa, e); S[0] = bx + dz * wb; S[2] = bz - dx * wb; m.v(r, g, b, ab, e); S[0] = ax + dz * wa; S[2] = az - dx * wa; m.v(r, g, b, aa, e);
    }
  },
  // a wake on water, into a mesh for GL.fx: two arms that spread (bright at their outer edge, fading inwards) and the
  // churned water between them just behind; w0 + i·dw each arm's distance out, alpha from strength, add: 127 for light
  wake(m, y, col, w0, dw, alpha, add) {
    const p = this.p, r = (col >> 16) & 255, g = (col >> 8) & 255, b = col & 255, e = add || 0, N = this.max, S = m.s; S[1] = y;
    for (let i = 0; i + 1 < this.n; i++) {
      if (m.n + 18 > m.cap) return;
      const ax = p[i * 3], az = p[i * 3 + 1], bx = p[i * 3 + 3], bz = p[i * 3 + 4];
      let dx = bx - ax, dz = bz - az; const l = Math.sqrt(dx * dx + dz * dz) || 1; dx /= l; dz /= l;
      const wa = w0 + i * dw, wb = w0 + (i + 1) * dw, ia = wa * 0.45, ib = wb * 0.45, fa = 1 - i / N, fb = 1 - (i + 1) / N;
      const aa = U.clamp(fa * fa * p[i * 3 + 2] * alpha, 0, 255) | 0, ab = U.clamp(fb * fb * p[i * 3 + 5] * alpha, 0, 255) | 0, ca = i < 7 ? aa * (1 - i / 7) * 0.55 | 0 : 0, cb = i < 6 ? ab * (1 - (i + 1) / 7) * 0.55 | 0 : 0;
      for (let sd = -1; sd <= 1; sd += 2) {              // each arm: its outer edge, and in to nothing
        const ox = -dz * sd, oz = dx * sd;
        S[0] = ax + ox * wa; S[2] = az + oz * wa; m.v(r, g, b, aa, e); S[0] = bx + ox * wb; S[2] = bz + oz * wb; m.v(r, g, b, ab, e); S[0] = bx + ox * ib; S[2] = bz + oz * ib; m.v(r, g, b, 0, e);
        S[0] = ax + ox * wa; S[2] = az + oz * wa; m.v(r, g, b, aa, e); S[0] = bx + ox * ib; S[2] = bz + oz * ib; m.v(r, g, b, 0, e); S[0] = ax + ox * ia; S[2] = az + oz * ia; m.v(r, g, b, 0, e);
      }
      if (ca) {                                          // the churn down the middle
        const cw = 0.35 + i * 0.04;
        S[0] = ax - dz * cw; S[2] = az + dx * cw; m.v(r, g, b, ca, e); S[0] = bx - dz * cw; S[2] = bz + dx * cw; m.v(r, g, b, cb, e); S[0] = bx + dz * cw; S[2] = bz - dx * cw; m.v(r, g, b, cb, e);
        S[0] = ax - dz * cw; S[2] = az + dx * cw; m.v(r, g, b, ca, e); S[0] = bx + dz * cw; S[2] = bz - dx * cw; m.v(r, g, b, cb, e); S[0] = ax + dz * cw; S[2] = az - dx * cw; m.v(r, g, b, ca, e);
      }
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
    const S = m.s;
    for (let i = 0; i < this.max; i++) if (this.life[i] > 0 && m.n < m.cap) { S[0] = this.x[i]; S[1] = this.y[i]; S[2] = this.z[i]; m.v(r, g, b, U.clamp(this.life[i] * 320, 0, 255) | 0, 0); }
  },
  sprites(flat, sprite, scale) { for (let i = 0; i < this.max; i++) if (this.life[i] > 0) flat.sprite(sprite, this.x[i], this.y[i], this.z[i], scale, Math.min(1, this.life[i] * 1.6)); }
};

// ---------------------------------------------------------------- what's written on the picture: a game's numbers, bars and
// maps, drawn in the game's own canvas. On a Pi 3 anything the page lays over the canvas (text, a bar, a see-through
// panel) is put together again by the browser at the TV's full size every frame, and that costs more than the game's
// whole picture; this costs one draw call. Letters are the 5×7 pixel font (Low2D's), in whole pixels, so they stay
// crisp at any size. Build a list (begin … end) when what's shown changes; the engine draws the list every frame, in
// either renderer.
const GLYPHS = {
  A: [14, 17, 17, 31, 17, 17, 17], B: [30, 17, 17, 30, 17, 17, 30], C: [14, 17, 16, 16, 16, 17, 14], D: [28, 18, 17, 17, 17, 18, 28],
  E: [31, 16, 16, 30, 16, 16, 31], F: [31, 16, 16, 30, 16, 16, 16], G: [14, 17, 16, 23, 17, 17, 15], H: [17, 17, 17, 31, 17, 17, 17],
  I: [14, 4, 4, 4, 4, 4, 14], J: [7, 2, 2, 2, 2, 18, 12], K: [17, 18, 20, 24, 20, 18, 17], L: [16, 16, 16, 16, 16, 16, 31],
  M: [17, 27, 21, 21, 17, 17, 17], N: [17, 17, 25, 21, 19, 17, 17], O: [14, 17, 17, 17, 17, 17, 14], P: [30, 17, 17, 30, 16, 16, 16],
  Q: [14, 17, 17, 17, 21, 18, 13], R: [30, 17, 17, 30, 20, 18, 17], S: [15, 16, 16, 14, 1, 1, 30], T: [31, 4, 4, 4, 4, 4, 4],
  U: [17, 17, 17, 17, 17, 17, 14], V: [17, 17, 17, 17, 17, 10, 4], W: [17, 17, 17, 21, 21, 21, 10], X: [17, 17, 10, 4, 10, 17, 17],
  Y: [17, 17, 10, 4, 4, 4, 4], Z: [31, 1, 2, 4, 8, 16, 31],
  "0": [14, 17, 19, 21, 25, 17, 14], "1": [4, 12, 4, 4, 4, 4, 14], "2": [14, 17, 1, 2, 4, 8, 31], "3": [31, 2, 4, 2, 1, 17, 14],
  "4": [2, 6, 10, 18, 31, 2, 2], "5": [31, 16, 30, 1, 1, 17, 14], "6": [6, 8, 16, 30, 17, 17, 14], "7": [31, 1, 2, 4, 8, 8, 8],
  "8": [14, 17, 17, 14, 17, 17, 14], "9": [14, 17, 17, 15, 1, 2, 12],
  ".": [0, 0, 0, 0, 0, 12, 12], ",": [0, 0, 0, 0, 12, 4, 8], ":": [0, 12, 12, 0, 12, 12, 0], ";": [0, 12, 12, 0, 12, 4, 8],
  "!": [4, 4, 4, 4, 4, 0, 4], "?": [14, 17, 1, 2, 4, 0, 4], "-": [0, 0, 0, 14, 0, 0, 0], "+": [0, 4, 4, 31, 4, 4, 0],
  "/": [1, 1, 2, 4, 8, 16, 16], "(": [2, 4, 8, 8, 8, 4, 2], ")": [8, 4, 2, 2, 2, 4, 8], "'": [4, 4, 8, 0, 0, 0, 0],
  '"': [10, 10, 0, 0, 0, 0, 0], "%": [25, 25, 2, 4, 8, 19, 19], "=": [0, 0, 31, 0, 31, 0, 0], "<": [2, 4, 8, 16, 8, 4, 2],
  ">": [8, 4, 2, 1, 2, 4, 8], "_": [0, 0, 0, 0, 0, 0, 31], "*": [0, 4, 21, 14, 21, 4, 0], "#": [10, 10, 31, 10, 31, 10, 10],
  "&": [12, 18, 20, 8, 21, 18, 13], "[": [14, 8, 8, 8, 8, 8, 14], "]": [14, 2, 2, 2, 2, 2, 14],
  "\x10": [0, 17, 10, 4, 10, 17, 0], "\x11": [0, 14, 17, 17, 17, 14, 0], "\x12": [0, 31, 17, 17, 17, 31, 0], "\x13": [0, 4, 4, 10, 10, 31, 0],   // ✕ ○ □ △
  "\x14": [2, 6, 14, 30, 14, 6, 2], "\x15": [8, 12, 14, 15, 14, 12, 8], "\x16": [0, 10, 31, 31, 14, 4, 0], "\x17": [4, 4, 31, 14, 10, 17, 0],   // ◀ ▶ ♥ ★
  "\x18": [0, 0, 0, 4, 0, 0, 0], "\x19": [4, 14, 31, 4, 4, 4, 0], "\x1a": [0, 4, 4, 4, 31, 14, 4],                                            // · ↑ ↓
  "\x1b": [0, 14, 14, 14, 14, 14, 0], "\x1c": [0, 14, 10, 10, 10, 14, 0]                                                                       // pips, full and empty
};
const SPECIAL = { 0x2715: 16, 0x25cb: 17, 0x25a1: 18, 0x25b3: 19, 0x25c0: 20, 0x25b6: 21, 0x2665: 22, 0x2605: 23, 0xb7: 24, 0x2191: 25, 0x2193: 26, 0xd7: 16 };
function Letters() {
  this.GI = new Int16Array(256).fill(-1); this.rows = [];
  for (const k in GLYPHS) { this.GI[k.charCodeAt(0)] = this.rows.length; this.rows.push(GLYPHS[k]); }
  const n = this.rows.length; this.GX = new Uint8Array(n); this.GW = new Uint8Array(n);
  for (let i = 0; i < n; i++) {
    let lo = 5, hi = -1;
    for (let y = 0; y < 7; y++) for (let b = 0; b < 5; b++) if ((this.rows[i][y] >> (4 - b)) & 1) { lo = Math.min(lo, b); hi = Math.max(hi, b); }
    if (hi < 0) { this.GX[i] = 0; this.GW[i] = 3; } else { this.GX[i] = lo; this.GW[i] = hi - lo + 1; }
  }
}
Letters.prototype = {
  code(s, i) { let c = s.charCodeAt(i); if (c > 255) c = SPECIAL[c] || 63; if (c >= 97 && c <= 122) c -= 32; return c; },
  width(s, k) {
    k = k || 1; let w = 0;
    for (let i = 0; i < s.length; i++) { const c = this.code(s, i), g = c === 32 ? -1 : this.GI[c]; w += (g < 0 ? 4 : this.GW[g] + 1) * k; }
    return Math.max(0, w - k);
  }
};
let LETTERS = null;
const UI_COLS = 42, UI_W = 256, UI_H = 64;         // the picture the letters and shapes are cut from: 6 × 8 cells, then shapes
function UI() {
  if (!LETTERS) LETTERS = new Letters();
  this.L = LETTERS; this.cap = 512; this.q = new Float32Array(this.cap * 16); this.n = 0; this.w = 320; this.h = 180;
  this.mesh = null; this.handle = null; this.tex = null; this.dirty = false; this.g3 = null; this.tints = new Map(); this.atlas = null;
}
UI.prototype = {
  sheet() {                                          // the letters and a few shapes, white: made once
    if (this.atlas) return this.atlas;
    const c = document.createElement("canvas"); c.width = UI_W; c.height = UI_H;
    const g = c.getContext("2d"), L = this.L; g.fillStyle = "#fff";
    for (let i = 0; i < L.rows.length; i++) for (let y = 0; y < 7; y++) for (let b = 0; b < 5; b++) if ((L.rows[i][y] >> (4 - b)) & 1) g.fillRect((i % UI_COLS) * 6 + b, ((i / UI_COLS) | 0) * 8 + y, 1, 1);
    g.fillRect(0, 40, 8, 8);                           // a block (bars, lines)
    g.beginPath(); g.arc(20, 48, 7.5, 0, TAU); g.fill();   // a disc, 16 across at 12 40
    g.beginPath(); g.moveTo(32, 55); g.lineTo(40, 41); g.lineTo(48, 55); g.lineTo(40, 51); g.closePath(); g.fill();   // an arrowhead, 16 across at 32 40
    return (this.atlas = c);
  },
  begin(w, h) { this.n = 0; this.base = 0; this.w = w; this.h = h; return this; },
  // what's in the list so far stays (a map's lines, a panel): rewind() goes back to here, to build the rest again
  hold() { this.base = this.n; return this; },
  rewind() { this.n = this.base || 0; return this; },
  room() { if (this.n < this.cap) return; this.cap *= 2; const q = new Float32Array(this.cap * 16); q.set(this.q); this.q = q; },
  // any four corners (clockwise from the top left), cut from the sheet at u v (in its pixels), a colour and how solid
  quad(x0, y0, x1, y1, x2, y2, x3, y3, u0, v0, u1, v1, col, a) {
    this.room(); const q = this.q, o = this.n++ * 16;
    q[o] = x0; q[o + 1] = y0; q[o + 2] = x1; q[o + 3] = y1; q[o + 4] = x2; q[o + 5] = y2; q[o + 6] = x3; q[o + 7] = y3;
    q[o + 8] = u0; q[o + 9] = v0; q[o + 10] = u1; q[o + 11] = v1; q[o + 12] = col; q[o + 13] = a == null ? 1 : a; q[o + 14] = 0; q[o + 15] = 0;
  },
  rect(x, y, w, h, col, a) { this.quad(x, y, x + w, y, x + w, y + h, x, y + h, 2, 42, 6, 46, col, a); },
  frame(x, y, w, h, t, col, a) { this.rect(x, y, w, t, col, a); this.rect(x, y + h - t, w, t, col, a); this.rect(x, y + t, t, h - t * 2, col, a); this.rect(x + w - t, y + t, t, h - t * 2, col, a); },
  line(x0, y0, x1, y1, t, col, a) {                  // t thick
    let dx = x1 - x0, dy = y1 - y0; const l = Math.sqrt(dx * dx + dy * dy) || 1; dx = dx / l * t / 2; dy = dy / l * t / 2;
    this.quad(x0 - dy, y0 + dx, x1 - dy, y1 + dx, x1 + dy, y1 - dx, x0 + dy, y0 - dx, 2, 42, 6, 46, col, a);
  },
  disc(x, y, r, col, a) { this.quad(x - r, y - r, x + r, y - r, x + r, y + r, x - r, y + r, 12, 40, 28, 56, col, a); },
  arrow(x, y, r, turn, col, a) {                     // an arrowhead pointing up, turned clockwise by turn
    const c = Math.cos(turn), s = Math.sin(turn), P = (px, py, k) => k ? x + (px * c - py * s) * r : y + (px * s + py * c) * r;
    this.quad(P(-1, -1, 1), P(-1, -1, 0), P(1, -1, 1), P(1, -1, 0), P(1, 1, 1), P(1, 1, 0), P(-1, 1, 1), P(-1, 1, 0), 32, 40, 48, 56, col, a);
  },
  width(s, k) { return this.L.width(String(s), k); },
  // a line of text, its top left at x y, each of the font's pixels k of the picture's (a whole number); align: 0 from
  // x, 0.5 centred on it, 1 ending at it; shade: a dark copy behind (a colour)
  text(s, x, y, k, col, a, align, shade) {
    s = String(s); k = Math.max(1, Math.round(k || 1)); const L = this.L;
    x = Math.round(align ? x - L.width(s, k) * align : x); y = Math.round(y);
    if (shade != null) this.text(s, x + Math.max(1, k >> 1), y + Math.max(1, k >> 1), k, shade, a);
    const al = a == null ? 1 : a;
    for (let i = 0; i < s.length; i++) {
      const c = L.code(s, i);
      if (c === 32) { x += 4 * k; continue; }
      const gi = L.GI[c]; if (gi < 0) { x += 4 * k; continue; }
      const u = (gi % UI_COLS) * 6 + L.GX[gi], v = ((gi / UI_COLS) | 0) * 8, w = L.GW[gi];
      this.room(); const q = this.q, o = this.n++ * 16;   // (written here, not through quad(): a call would make each number anew)
      q[o] = x; q[o + 1] = y; q[o + 2] = x + w * k; q[o + 3] = y; q[o + 4] = x + w * k; q[o + 5] = y + 7 * k; q[o + 6] = x; q[o + 7] = y + 7 * k;
      q[o + 8] = u; q[o + 9] = v; q[o + 10] = u + w; q[o + 11] = v + 7; q[o + 12] = col; q[o + 13] = al; q[o + 14] = 0; q[o + 15] = 0;
      x += (w + 1) * k;
    }
    return x;
  },
  end() { this.dirty = true; },
  // drawn: with WebGL one call (the list is sent again only when it changed), else through a 2D context
  show(g3, ctx) {
    if (!this.n) return;
    if (g3) {
      const gl = g3.gl;
      if (this.g3 !== g3) { this.g3 = g3; this.tex = g3.picture(this.sheet(), { rgba: true, nearest: true }); this.buf = gl.createBuffer(); this.dirty = true; this.sent = 0; }
      const u = g3.use(g3.prog("ui"));
      if (g3.vao) g3.vao.bindVertexArrayOES(null);
      gl.bindBuffer(gl.ARRAY_BUFFER, this.buf); g3.curBuf = null;
      if (this.dirty) {
        const need = this.n * 6 * 20;
        if (!this.vb || this.vb.byteLength < need) { this.vb = new ArrayBuffer(this.cap * 6 * 20); this.vf = new Float32Array(this.vb); this.vu = new Uint8Array(this.vb); this.sent = 0; }
        const f = this.vf, b8 = this.vu, q = this.q, ORD = UI.ORD;
        for (let i = 0; i < this.n; i++) {
          const o = i * 16, col = q[o + 12], a = Math.max(0, Math.min(255, q[o + 13] * 255)) | 0, r = (col >> 16) & 255, gg = (col >> 8) & 255, bb = col & 255;
          for (let k = 0; k < 6; k++) {
            const c = ORD[k], vi = (i * 6 + k) * 5, bi = (i * 6 + k) * 20;
            f[vi] = q[o + c * 2]; f[vi + 1] = q[o + c * 2 + 1];
            f[vi + 2] = (c === 0 || c === 3 ? q[o + 8] : q[o + 10]) / UI_W; f[vi + 3] = (c < 2 ? q[o + 9] : q[o + 11]) / UI_H;
            b8[bi + 16] = r; b8[bi + 17] = gg; b8[bi + 18] = bb; b8[bi + 19] = a;
          }
        }
        if (this.sent < need) { gl.bufferData(gl.ARRAY_BUFFER, this.vb.byteLength, gl.DYNAMIC_DRAW); this.sent = this.vb.byteLength; }
        gl.bufferSubData(gl.ARRAY_BUFFER, 0, this.view && this.view.buffer === this.vb && this.view.length === need ? this.view : (this.view = new Uint8Array(this.vb, 0, need)));
        this.dirty = false;
      }
      gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 20, 0);
      gl.enableVertexAttribArray(1); gl.vertexAttribPointer(1, 2, gl.FLOAT, false, 20, 8);
      gl.enableVertexAttribArray(2); gl.vertexAttribPointer(2, 4, gl.UNSIGNED_BYTE, true, 20, 16);
      gl.viewport(0, 0, g3.canvas.width, g3.canvas.height); gl.disable(gl.SCISSOR_TEST);
      gl.uniform4f(u.uView, 2 / this.w, -2 / this.h, -1, 1);
      gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, this.tex); gl.uniform1i(u.uTex, 0);
      gl.disable(gl.DEPTH_TEST); gl.disable(gl.CULL_FACE); gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
      gl.drawArrays(gl.TRIANGLES, 0, this.n * 6); g3.calls++;
      gl.disable(gl.BLEND); gl.enable(gl.DEPTH_TEST); gl.enable(gl.CULL_FACE);
      return;
    }
    if (!ctx) return;
    const q = this.q, sx = ctx.canvas.width / this.w, sy = ctx.canvas.height / this.h;
    ctx.save(); ctx.setTransform(sx, 0, 0, sy, 0, 0); ctx.imageSmoothingEnabled = false;
    for (let i = 0; i < this.n; i++) {
      const o = i * 16, col = q[o + 12], a = q[o + 13];
      ctx.globalAlpha = Math.max(0, Math.min(1, a));
      const flat = q[o + 1] === q[o + 3] && q[o] === q[o + 6] && q[o + 2] === q[o + 4];
      if (q[o + 9] >= 40 && q[o + 8] < 8) {              // a block: a rectangle, or any four corners
        ctx.fillStyle = U.hex(col);
        if (flat) ctx.fillRect(q[o], q[o + 1], q[o + 2] - q[o], q[o + 5] - q[o + 1]);
        else { ctx.beginPath(); ctx.moveTo(q[o], q[o + 1]); ctx.lineTo(q[o + 2], q[o + 3]); ctx.lineTo(q[o + 4], q[o + 5]); ctx.lineTo(q[o + 6], q[o + 7]); ctx.closePath(); ctx.fill(); }
      } else if (flat) ctx.drawImage(this.tinted(col), q[o + 8], q[o + 9], q[o + 10] - q[o + 8], q[o + 11] - q[o + 9], q[o], q[o + 1], q[o + 2] - q[o], q[o + 5] - q[o + 1]);
      else {                                           // a turned shape (an arrow): the sheet's piece, turned with it
        const w = Math.hypot(q[o + 2] - q[o], q[o + 3] - q[o + 1]), h = Math.hypot(q[o + 6] - q[o], q[o + 7] - q[o + 1]);
        ctx.save(); ctx.translate(q[o], q[o + 1]); ctx.rotate(Math.atan2(q[o + 3] - q[o + 1], q[o + 2] - q[o]));
        ctx.drawImage(this.tinted(col), q[o + 8], q[o + 9], q[o + 10] - q[o + 8], q[o + 11] - q[o + 9], 0, 0, w, h); ctx.restore();
      }
    }
    ctx.restore();
  },
  tinted(col) {                                      // (2D) the sheet in a colour, kept
    let c = this.tints.get(col);
    if (!c) {
      if (this.tints.size > 24) this.tints.clear();
      c = document.createElement("canvas"); c.width = UI_W; c.height = UI_H;
      const g = c.getContext("2d"); g.drawImage(this.sheet(), 0, 0); g.globalCompositeOperation = "source-in"; g.fillStyle = U.hex(col); g.fillRect(0, 0, UI_W, UI_H);
      this.tints.set(col, c);
    }
    return c;
  }
};
UI.ORD = [0, 1, 2, 0, 2, 3];

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
  const dx = cam.tx - cam.x, dz = cam.tz - cam.z, hd = Math.sqrt(dx * dx + dz * dz) || 1;
  return { yaw: Math.atan2(dx, dz), pitch: Math.atan2(cam.y - cam.ty, hd) };
}

// ---------------------------------------------------------------- input: the controller first (pad.js), the keyboard too
// The box turns a controller's buttons into keys as well (arrows, Enter, Back…, for its menus): while a controller is
// there, such a key waits a moment and is dropped when the controller itself was just pressed (so nothing happens
// twice); a remote's or the phone's keys still come through. Back (B, or a remote's Back) on the game's top screen is
// left to the box: it leaves the game. o: { keys: {key: action}, on(action, how, who), top() → ms since the top screen
// showed, or 0, joined(n), left(n) }. who: the player whose controller it was (1, 2, …: pad.js numbers them as they
// come), or 0 for a key (the keyboard, a remote, the phone). joined(n) and left(n): a controller became player n, or
// player n's went away. input.player(n) reads player n's controller alone; the rest of Input is everyone's at once.
const ECHO = /^(Arrow|Enter$|NumpadEnter$|Escape$|Backspace$|BrowserBack$|GoBack$|Media|\/$)/;
const BACKS = /^(Escape|Backspace|BrowserBack|GoBack)$/;
const NOPAD = { n: 0, on() {}, held: () => false, button: () => false, stick: () => ({ x: 0, y: 0 }), stick2: () => ({ x: 0, y: 0 }), trigger: () => 0,
  rumble() {}, active: () => false, connected: () => false, kind: () => null, label: b => b };   // (no pad.js: nobody)
function Input(o) {
  this.o = o; this.k = {}; this.q = []; this.lastPad = -1e9;
  const pad = window.SofaPad;
  if (pad) pad.on((b, how, p) => { if (b === "connected") { if (o.connected) o.connected(); return; } this.lastPad = performance.now(); o.on(b, how, p && p.n || 1); });
  if (pad && pad.players) { pad.on("joined", p => { if (o.joined) o.joined(p.n); }); pad.on("left", p => { if (o.left) o.left(p.n); }); }
  addEventListener("keydown", e => {
    const back = BACKS.test(e.key) || e.code === "BrowserBack", top = o.top ? o.top() : 0;
    if (back && top && performance.now() - top > 500) return;      // the box's: out of the game
    const act = o.keys[e.key] || o.keys[e.code];
    if (act || back) e.preventDefault();
    if (!act) return;
    if (pad && pad.connected() && ECHO.test(e.key)) { if (!e.repeat) this.q.push({ act, t: performance.now(), down: true }); return; }
    this.k[act] = true; o.on(act, e.repeat ? "repeat" : "press", 0);
  });
  addEventListener("keyup", e => {
    const act = o.keys[e.key] || o.keys[e.code]; if (!act) return;
    if (pad && pad.connected() && ECHO.test(e.key)) { this.q.push({ act, t: performance.now(), down: false }); return; }
    this.k[act] = false; o.on(act, "release", 0);
  });
  addEventListener("blur", () => { for (const a in this.k) this.k[a] = false; });
}
Input.prototype = {
  tick(now) {
    while (this.q.length && now - this.q[0].t > 60) {
      const e = this.q.shift();
      if (this.lastPad > e.t - 300 || (window.SofaPad && window.SofaPad.active())) continue;   // the controller's own echo
      this.k[e.act] = e.down; this.o.on(e.act, e.down ? "press" : "release", 0);
    }
  },
  // player n's own controller (pad.js's player: held, button, stick, stick2, trigger, rumble, label, kind, active,
  // connected), the same object for good; players(): the numbers of those who have joined so far
  player(n) { const pad = window.SofaPad; return pad && pad.player ? pad.player(n) : NOPAD; },
  players() { const pad = window.SofaPad; return pad && pad.players ? pad.players().map(p => p.n) : []; },
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
function Synth() { this.ac = null; this.fx = Object.assign({}, FX); this.seq = null; this.vol = { music: 0.6, sound: 0.8 }; this.cur = null; this.routes = []; }
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
    g.connect(dest || this.cur || this.sfxBus); o.start(t); o.stop(t + dur + 0.05);
    return g;
  },
  noise(t, dur, vol, freq, q, dest) {
    if (!this.ac) return;
    const ac = this.ac, s = ac.createBufferSource(), f = ac.createBiquadFilter(), g = ac.createGain();
    s.buffer = this.noiseBuf; f.type = "bandpass"; f.frequency.value = freq; f.Q.value = q || 1;
    g.gain.setValueAtTime(vol, t); g.gain.exponentialRampToValueAtTime(0.0008, t + dur);
    s.connect(f); f.connect(g); g.connect(dest || this.cur || this.sfxBus); s.start(t, Math.random() * 0.5); s.stop(t + dur + 0.05);
  },
  define(name, fn) { this.fx[name] = fn; },
  // an effect; pan (-1 left .. 1 right) and gain (0..1) place it: a sound from where it happens. Nothing's made for it:
  // 9 pans × 5 loudnesses, each a gain and a panner made the first time it's wanted.
  play(name, pan, gain) {
    if (!this.ac || !this.fx[name]) return;
    if (pan == null && gain == null) { this.fx[name](this, this.ac.currentTime + 0.01); return; }
    const gi = Math.round(U.clamp(gain == null ? 1 : gain, 0, 1) * 5); if (!gi) return;      // (too far off to hear)
    this.cur = this.route(U.clamp(pan || 0, -1, 1), gi);
    try { this.fx[name](this, this.ac.currentTime + 0.01); } finally { this.cur = null; }
  },
  route(pan, gi) {
    const pi = Math.round((pan + 1) * 4), key = pi * 8 + gi;
    let r = this.routes[key];
    if (!r) {
      const ac = this.ac; r = ac.createGain(); r.gain.value = Math.pow(gi / 5, 1.4);
      if (ac.createStereoPanner) { const p = ac.createStereoPanner(); p.pan.value = pi / 4 - 1; r.connect(p); p.connect(this.sfxBus); } else r.connect(this.sfxBus);
      this.routes[key] = r;
    }
    return r;
  },
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
//   rung(E, r), update(dt) (60 times a second), draw(now, dt) (each frame drawn), paused(), missed() (frames drawn late
//   elsewhere, as a Ray's helpers say) and helperWork() (their time a frame, ms) })
// a height for the picture that goes into the screen's a whole number of times, the nearest to the one wanted: [height,
// how many times] (1080 wanting 360: 360, 3; wanting 540 on a 720 screen: 720, 1)
// How many fixed steps a frame takes: [steps, what's carried].
// A frame whose own length is a whole number of steps, to within 1.5%, takes exactly that many and carries nothing: a
// screen that is 60 Hz or nearly (59.94 on a TV, 59.79 on a 1366 × 768 panel, 60.02, 60.32) runs on its own beat, one
// step a frame, at most 1.5% off real time, which nobody sees. (Carrying the difference instead is right to the
// second, and takes two steps in one frame, or none, every few seconds: a skip you do see.)
// Any other frame's time is carried, never dropped: what it is short of a whole number of steps, or over it, goes to
// the next (acc, in seconds; it may run a little under nought), so a game runs at real time on a 50, 72, 75 or 144 Hz
// screen. There a frame that comes within a quarter of a step of a whole number takes that many, so a clock that
// wobbles gives no frame with none and then one with two.
// most: the most one frame may take; a longer pause isn't caught up on.
const STEPS = [0, 0];
function wholeSteps(acc, dt, DT, most) {
  const f = dt / DT, w = Math.round(f);
  if (w >= 1 && w < most && Math.abs(f - w) < 0.015 * w) { STEPS[0] = w; STEPS[1] = acc; return STEPS; }   // on the screen's own beat
  acc += dt;
  const s = acc / DT, r = Math.round(s);
  let n = Math.abs(s - r) < 0.25 ? r : Math.floor(s);
  if (n < 0) n = 0;
  if (n >= most) { n = most; acc = 0; } else acc -= n * DT;
  STEPS[0] = n; STEPS[1] = acc; return STEPS;
}
// A ladder as one line (each rung's size and rate). A rung kept for a box is a number on the ladder as it was then, and
// means nothing on another: what's kept carries this, and is used only on the ladder it was kept on.
function ladderSig(lad) { let s = ""; for (let i = 0; i < lad.length; i++) s += (i ? " " : "") + lad[i].h + "@" + lad[i].fps; return s; }
function wholeSize(dev, want) { const div = Math.max(1, Math.round(dev / Math.max(1, want))); return [Math.round(dev / div), div]; }
const GLOPTS = p => ({ antialias: p.family === "desktop" || p.family === "pi5" });   // (smoothed edges where there's room: never a Pi 3 or 4)
// kind: "ray" for a game drawn a pixel at a time (Ray): the CPU test alone picks its rung (LADDER.ray), E.screen is
// its picture (E.screen.u32), shown through WebGL where the GPU is real (picture() "plain": never), resized(E) when
// the picture's size changes.
// In the address: #fps shows the rate and the rung, #flat or #gl picks the renderer, #rung=N holds a rung, #test is for checks.
function game(o) {
  const H = location.hash || "";
  const E = {
    o, mode: "flat", g3: null, flat: null, gov: null, rung: null, probe: null, bench: null, plan: null, ready: false, broken: false,
    test: /test/.test(H), showFps: /fps/.test(H), force: /flat|2d/.test(H) ? "flat" : /\bgl\b|3d/.test(H) ? "gl" : null,
    forceRung: /rung=(\d+)/.test(H) ? +H.match(/rung=(\d+)/)[1] : null, aspect: o.aspect || 16 / 9, vw: 960, vh: 540, DT: 1 / 60,
    // for checks: #slow=N makes every frame's work take N times as long (a slower processor, as a Pi's is), #threads=N
    // holds the helpers that draw a Ray game's picture (0: the page draws it all)
    slow: /slow=(\d+)/.test(H) ? Math.max(1, +H.match(/slow=(\d+)/)[1]) : 1, threads: /threads=(\d+)/.test(H) ? +H.match(/threads=(\d+)/)[1] : null
  };
  // #demo: the game plays by itself (an attract mode that saves nothing and takes no controller), for the games
  // check (probe/), which reads window.SofaStats: whether it's ready and playing itself, the rung, the frame rate drawn
  E.demo = /demo/.test(H);
  E.ui = new UI(); E.alpha = 0; E.div = 1;
  window.SofaStats = {
    get ready() { return E.ready; },
    get tier() { return E.ready && E.gov ? (E.mode === "gl" ? "3D" : E.mode === "ray" ? "ray" : "2D") + " rung " + E.gov.rung + " of " + (E.gov.ladder.length - 1) : null; },
    get fps() { return E.gov ? E.gov.fps : 0; },
    get workMs() { return E.gov ? Math.round(E.gov.workMs * 100) / 100 : 0; },
    demo: false                                      // (the game sets it while its #demo plays)
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
  // the picture's size. 3D: the screen's own height divided by a whole number (the nearest to the rung's height), so
  // every pixel of it is shown as a square of the screen's, crisp; when it's the screen's own size, smooth
  const SZ = [0, 0];
  E.size = () => {
    const dev = Math.round(E.vh * (devicePixelRatio || 1));
    let h = E.mode === "ray" ? E.rung.h : Math.min(E.rung.h, dev);
    if (E.mode !== "ray" && o.crisp !== false) { const s = wholeSize(dev, h); h = s[0]; E.div = s[1]; }
    SZ[0] = Math.round(h * E.aspect); SZ[1] = h; return SZ;
  };
  E.resize = () => {
    if (!E.rung) return;
    const [w, h] = E.size();
    if (E.mode === "ray") {
      // its canvas: the screen's height divided by a whole number, the nearest to what the box shows (plan.show) that
      // holds the picture
      const dev = Math.round(E.vh * (devicePixelRatio || 1));
      let div = Math.max(1, Math.round(dev / Math.max(h, E.plan.show || 360))); while (div > 1 && Math.round(dev / div) < h) div--;
      const ch = Math.max(h, Math.round(dev / div)); E.div = div;
      if (E.screen && E.screen.size(w, h, Math.round(ch * E.aspect), ch) && o.resized) o.resized(E);
    }
    else if (E.mode === "gl" && E.g3) {
      if (o.gl.width !== w || o.gl.height !== h) { o.gl.width = w; o.gl.height = h; }
      if (o.crisp !== false) o.gl.style.imageRendering = E.div > 1 && !(o.smooth && o.smooth()) ? "pixelated" : "auto";
    }
    else if (E.flat) { E.flat.size(w, h); if (o.crisp !== false) o.flat.style.imageRendering = E.div > 1 && !(o.smooth && o.smooth()) ? "pixelated" : "auto"; }
    if (o.resized && E.mode !== "ray") o.resized(E);
  };
  E.lad = LADDER.flat; E.ladder = () => E.gov ? E.gov.ladder : E.lad;   // (the ladder in use: a ray game's may be the player's own)
  E.glows = () => !(o.tune && o.tune().glow === 0);      // (a ray game's glow: the player may turn it off)
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
      if (want === "gl" && !E.g3) { try { E.g3 = new GL(o.gl, GLOPTS(E.probe)); } catch (e) { E.g3 = null; } }
      E.mode = want === "gl" && E.g3 ? "gl" : "flat";
      if (E.mode === "flat" && !E.flat) E.flat = new Flat(o.flat);
      o.gl.classList.toggle("hidden", E.mode !== "gl"); o.flat.classList.toggle("hidden", E.mode !== "flat");
    }
    // tune() (a ray game's): what the player holds: { lines (the picture's height), fps (30 or 60), glow (0: never) }, 0
    // or left out for what the box finds by itself. A size or a rate held makes a ladder of its own (heldRay).
    const T = o.kind === "ray" && o.tune ? o.tune() : null, own = T && E.forceRung == null ? heldRay(T.lines || 0, T.fps || 0) : null;
    E.held = !!own;
    const lad = own || LADDER[E.mode], p = o.picture ? o.picture() : "auto";
    let start = E.mode === E.plan.mode ? E.plan.rung : E.mode === "gl" ? 1 : 2, top = E.mode === E.plan.mode ? E.plan.top : lad.length - 1;
    // (where this game's governor settled on this box: a rung kept on another ladder, an older version's, is not this one's)
    if (tune && tune.key === E.probe.key && tune.mode === E.mode && tune.lad === ladderSig(LADDER[E.mode]) && tune.rung != null && p === "auto" && !own) { start = tune.rung; top = Math.min(top, tune.top); }
    if (own) {                                       // the size it would have started on (or the one held), at the best rate held
      const want = T.lines || LADDER.ray[U.clamp(start, 0, LADDER.ray.length - 1)].h, most = T.lines || LADDER.ray[U.clamp(top, 0, LADDER.ray.length - 1)].h;
      start = top = 0;
      for (let i = 0; i < own.length; i++) { if (own[i].h <= want) start = i; if (own[i].h <= most) top = i; }
    }
    if (p === "light") { start = Math.min(start, E.mode === "ray" ? 2 : 1); top = Math.min(top, E.mode === "ray" ? 4 : 2); }
    if (p === "rich") { start = Math.max(start, E.mode === "ray" ? 6 : 4); top = lad.length - 1; }
    if (E.forceRung != null) start = top = E.forceRung;
    start = U.clamp(start, 0, lad.length - 1); top = U.clamp(Math.max(top, start), 0, lad.length - 1);
    E.lad = lad;
    E.gov = new Governor(lad, start, top, (r, why) => { E.rung = lad[r]; E.resize(); if (o.rung) o.rung(E, E.rung); E.remember(); });
    if (E.forceRung != null) E.gov.lock = true;
    E.rung = lad[start]; E.resize();
    if (!first && o.prepare) o.prepare(E);
    if (o.rung) o.rung(E, E.rung);
  };
  E.remember = () => { if ((o.picture ? o.picture() : "auto") === "auto" && E.forceRung == null && !E.held) E.keep({ key: E.probe.key, bench: E.bench, mode: E.mode, rung: E.gov.rung, top: E.gov.top, lad: ladderSig(LADDER[E.mode]) }); };
  E.setPicture = () => { E.keep({ key: E.probe.key, bench: E.bench }); E.renderer(false); };
  E.test3d = (done, step) => {                       // the ~2 s test (software GL is left out: the 2D sea is quicker there)
    let g = null;
    if (E.probe.webgl1 && !E.probe.software && E.force !== "flat" && o.kind !== "ray") { try { g = E.g3 || new GL(o.gl, GLOPTS(E.probe)); E.g3 = g; } catch (e) { g = null; } }
    o.gl.classList.toggle("hidden", !g);
    if (o.loading) o.loading.el.classList.add("see");
    bench(g, r => { E.bench = r; o.gl.classList.add("hidden"); if (o.loading) o.loading.el.classList.remove("see"); done(r); }, step);
  };
  const planOf = () => {
    const b = E.slow > 1 && E.bench ? Object.assign({}, E.bench, { cpu: E.bench.cpu * E.slow }) : E.bench;
    if (o.kind !== "ray") return plan(E.probe, b);
    const pl = planRay(E.probe, b); if (E.threads != null) pl.helpers = E.threads;
    return pl;
  };
  E.retest = (done) => E.test3d(() => { E.plan = planOf(); E.keep({ key: E.probe.key, bench: E.bench }); E.renderer(false); if (done) done(); });
  E.rows = () => {                                   // "This box": what it is, what was chosen, what it's doing now
    const [w, h] = E.size(), R = E.rung, G3 = E.g3;
    const now = E.mode === "ray"
      ? ["Now", "drawn by the processor, rung " + E.gov.rung + " (top " + E.gov.top + (E.held ? ", held in the options" : "") + "): " + w + "×" + h + ", " + R.fps + " fps wanted, " + E.gov.fps + " drawn" +
        (E.screen ? ", shown on " + E.screen.cw + "×" + E.screen.ch + (E.screen.gl ? " through WebGL" + (R.glow && E.glows() ? " with glow" : "") : " in 2D") : "")]
      : null;
    return rows(E.probe, E.bench, E.plan).concat([
      now || ["Now", (E.mode === "gl" ? "3D" : "2D") + ", rung " + E.gov.rung + " (top " + E.gov.top + "): " + w + "×" + h + ", " + R.fps + " fps wanted, " + E.gov.fps + " drawn" +
        (E.mode === "gl" ? ", draw distance " + R.far + " m" + (R.waves && G3 && G3.can("waves") ? ", waves" : "") : "")],
      ["Changes", E.gov.log.length ? E.gov.log.slice(-4).join(" · ") : "none yet"],
      ["Screen", E.probe.screen + " · page " + innerWidth + "×" + innerHeight + " at " + (devicePixelRatio || 1) + "×"],
      ["In one line", line(E.probe, E.bench, E.plan)]
    ]);
  };
  // How it ran, in one line. On the box a page's console errors are kept for "Send a report" (nothing else of a game
  // reaches one), so a game that's left there says how it ran: the only measure there is of a real Pi.
  E.ran = () => {
    const R = E.gov.ran, [w, h] = E.size();
    return (o.id || "game") + " ran: " + (E.mode === "gl" ? "3D" : E.mode === "ray" ? "ray" : "2D") + " rung " + E.gov.rung + " (top " + E.gov.top + ") " + w + "x" + h + ", " +
      (R.secs ? Math.round(R.frames / R.secs) : 0) + " fps over " + Math.round(R.secs) + " s (wanted " + E.rung.fps + ", lowest second " + (R.low > 1e8 ? "-" : R.low) + "), " + R.late + " of " + R.frames + " frames late, worst " + Math.round(R.worst) +
      " ms, work " + E.gov.workMs.toFixed(1) + " ms (most " + R.work.toFixed(0) + ")" + (E.mode === "gl" && E.g3 ? ", " + E.g3.calls + " draws " + Math.round(E.g3.tris) + " tris" : "") +
      (E.gov.log.length ? "; " + E.gov.log.slice(-5).join(", ") : "") + "; " + (E.probe.renderer || "no WebGL").slice(0, 60);
  };
  // said when the game is left, and when the game calls tell() (at the end of a race or a level: a page that's closed
  // may not get its last word out): once in five minutes at most, and what's counted starts again
  let toldAt = -1e9;
  E.tell = (last) => {
    if (!E.ready || !E.gov || E.demo || E.gov.ran.secs < 20 || !/^\/box\//.test(location.pathname)) return;
    if (!last && performance.now() - toldAt < 300000) return;
    toldAt = performance.now(); console.error(E.ran());
    E.gov.ran = { frames: 0, late: 0, worst: 0, secs: 0, work: 0, low: 1e9 };
  };
  addEventListener("pagehide", () => E.tell(true));
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
    // (the steps this frame takes: see wholeSteps. One a frame on a screen that's 60 Hz or nearly; real time on the rest.)
    if (!(o.paused && o.paused())) { const S = wholeSteps(acc, dt, E.DT, 6); acc = S[1]; for (let n = S[0]; n > 0; n--) o.update(E.DT); }
    E.alpha = acc > 0 ? acc / E.DT : 0;                 // (how far into the next step: for a game that draws between steps)
    // (a draw that returns false drew nothing: the last picture stays, and the governor isn't asked to judge frames
    // with no work in them: it would climb to the top rung under a menu and find it too much when play goes on)
    let drew = true;
    if (E.mode === "gl") { try { drew = o.draw(now, dt) !== false; if (drew && E.ui.n) E.ui.show(E.g3); } catch (e) { E.lost(e); } }
    else if ((drew = o.draw(now, dt) !== false)) {
      if (E.mode === "ray") { if (E.screen) { E.screen.present(E.glows() ? E.rung.glow : 0, E.vig); if (E.ui.n) E.screen.show(E.ui); } }
      else if (E.ui.n && E.flat) E.ui.show(null, E.flat.ctx);
    }
    if (!drew) E.gov.hold(400);
    if (E.slow > 1) { const until = performance.now() + (performance.now() - t0) * (E.slow - 1); while (performance.now() < until) { /* #slow: as a slower processor would */ } }
    if (o.missed) { const k = o.missed(); if (k) E.gov.miss(k); }
    E.gov.work(Math.max(performance.now() - t0, o.helperWork ? o.helperWork() : 0));
    E.workNow = performance.now() - t0;
    if (E.showFps && o.fps && now - fpsAt > 500) {
      fpsAt = now; const [w, h] = E.size();
      o.fps.textContent = E.gov.fps + " fps · " + (E.mode === "gl" ? "3D" : E.mode === "ray" ? "ray" : "2D") + " rung " + E.gov.rung + " · " + w + "×" + h +
        (E.mode === "gl" ? " · " + E.g3.calls + " draws " + Math.round(E.g3.tris) + " tris" : "") + "\nwork " + E.workNow.toFixed(1) + " ms";
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
function begin(E, cam, near, far, rect) {               // (rect: one view of a split screen, [x, y, w, h] in pixels)
  if (E.mode === "gl") { E.g3.begin(cam.x, cam.y, cam.z, cam.tx, cam.ty, cam.tz, cam.fov, near || 0.6, far || 2600, cam.roll, rect); return; }
  const v = viewOf(cam); E.flat.view(rect); E.flat.draw(cam.x, cam.y, cam.z, v.yaw, v.pitch, cam.fov);
}

// ================================================================ Ray: a software renderer for worlds on a grid
// Rooms and corridors with floors and ceilings at any height (steps, ledges, pits, sky), doors and lifts (a cell's
// ceiling or floor that moves), textures and sprites, drawn a pixel at a time into one picture: the same on every
// box, GPU or not (a Pi 3 draws it at 320×180). Light is Doom-like: each cell its own level, fading with distance,
// and a palette of 16 ramps of 16 shades with colormaps, so shading a pixel is a single look-up. A cell's light can
// have a colour (lava orange, ice blue: a colormap of its own), walls and floors keep the marks left on them (a copy
// of their texture with the mark in it), and some cells are walls you see through (grates, railings, bars, windows).
// Where the processor has cores to spare, helpers (web workers) each draw a strip of the picture at the same time.

// ---------------------------------------------------------------- the palette: index = ramp·16 + shade; 0 is see-through
function Palette(ramps, glow) {
  this.rgb = new Uint8Array(768); this.full = new Uint8Array(256); this.cube = new Int16Array(32768).fill(-1); this.ver = 0; this.tintRGB = [[1, 1, 1]];
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
  // coloured light: each tint ([r, g, b], 1 = as it is) gets a colormap of its own, after plain light (tint 0). A cell's
  // tint (RayMap.tint, or .dtint for a frame) picks it. Call maps() after.
  tints(list) { this.tintRGB = [[1, 1, 1]].concat(list || []); },
  // 32 light levels × 256 colours for each tint, packed for the picture (cmap[tint · 8192 + light · 256 + colour]); dark
  // fades towards fog (a colour) as much as haze says. Glowing colours stay as they are in every light and tint.
  maps(fog, haze) {
    const fr = (fog >> 16) & 255, fg = (fog >> 8) & 255, fb = fog & 255, T = this.tintRGB, n = T.length * 8192;
    const cm = this.cmap && this.cmap.length === n ? this.cmap : (this.cmap = new Uint32Array(n));
    for (let t = 0; t < T.length; t++) {
      const kr = T[t][0], kg = T[t][1], kb = T[t][2], base = t * 8192;
      for (let L = 0; L < 32; L++) {
        const b = Math.pow(L / 31, 1.15), h = (1 - b) * haze;
        for (let i = 0; i < 256; i++) {
          let r = this.rgb[i * 3], g = this.rgb[i * 3 + 1], bl = this.rgb[i * 3 + 2];
          if (!this.full[i]) { r = r * b * kr + fr * h; g = g * b * kg + fg * h; bl = bl * b * kb + fb * h; }
          cm[base + L * 256 + i] = LE ? (0xff000000 | (Math.min(255, bl) << 16) | (Math.min(255, g) << 8) | Math.min(255, r)) >>> 0 : 0;
        }
      }
    }
    this.fogPx = LE ? (0xff000000 | (fb * haze) << 16 | (fg * haze) << 8 | (fr * haze)) >>> 0 : 0;
    this.ver++;
    return cm;
  },
  // a sprite's colours swapped: every shade of each ramp in `from` drawn as the same shade of its ramp in `to`
  // ({px: 256 indices}, for Ray.sprite's last argument): one set of sprites in many team colours
  remap(from, to) { const px = new Uint8Array(256); for (let i = 0; i < 256; i++) { const k = from.indexOf(i >> 4); px[i] = k >= 0 ? (to[k] << 4) | (i & 15) : i; } return { px }; },
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
  // a see-through texture (a grate, bars, a railing, a window): 0 where you see past it
  mask(fn, size) {
    size = size || 64; const px = new Uint8Array(size * size);
    for (let u = 0; u < size; u++) for (let v = 0; v < size; v++) px[u * size + v] = fn(u, v) || 0;
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
// Per cell: solid, wtex (a wall's texture), floor and ceiling heights with their textures (ftex, ctex; ctex 255: sky),
// stex (a step's face), utex (a ceiling's lip, a door), light (0..31) and dyn (light added for a frame), tint (the
// light's colour, a Palette tint) and dtint (a tint for a frame), mask (a wall you see through: a texture made with
// Tex.mask, in a cell nothing walks through), seen (an automap); wdec and fdec: the marks on a wall's four faces and
// on a floor (Marks keeps them).
function RayMap(w, h) {
  const n = w * h;
  this.w = w; this.h = h;
  this.solid = new Uint8Array(n); this.wtex = new Uint8Array(n); this.stex = new Uint8Array(n); this.utex = new Uint8Array(n);
  this.ftex = new Uint8Array(n); this.ctex = new Uint8Array(n);
  this.floor = new Float32Array(n); this.ceil = new Float32Array(n).fill(1);
  this.light = new Uint8Array(n).fill(24); this.dyn = new Uint8Array(n); this.seen = new Uint8Array(n);
  this.tint = new Uint8Array(n); this.dtint = new Uint8Array(n); this.mask = new Uint8Array(n);
  this.wdec = new Uint16Array(n * 4); this.fdec = new Uint16Array(n);
  this.flowD = new Int16Array(n); this.q = new Int32Array(n);
  this.hitI = -1; this.hitFace = -1;
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
      if (this.solid[i] || (this.mask[i] && z < this.floor[i] + 1) || this.floor[i] > z + step || this.ceil[i] - Math.max(this.floor[i], z) < room) return false;
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
  // a straight line from one point to another (z the heights): the share of the way it gets before something stops it
  // (1: clear). What stopped it: hitI (a cell, or -1) and hitFace (0 its west face, 1 east, 2 north, 3 south). Walls you
  // see through let it pass.
  trace(x0, y0, z0, x1, y1, z1) {
    const dx = x1 - x0, dy = y1 - y0;
    let mx = Math.floor(x0), my = Math.floor(y0);
    const ex = Math.floor(x1), ey = Math.floor(y1), sx = dx < 0 ? -1 : 1, sy = dy < 0 ? -1 : 1;
    const tdx = dx === 0 ? 1e30 : Math.abs(1 / dx), tdy = dy === 0 ? 1e30 : Math.abs(1 / dy);
    let tx = dx === 0 ? 1e30 : (dx < 0 ? x0 - mx : mx + 1 - x0) * tdx, ty = dy === 0 ? 1e30 : (dy < 0 ? y0 - my : my + 1 - y0) * tdy;
    this.hitI = -1; this.hitFace = -1;
    for (let k = 0; k < 200; k++) {
      if (mx === ex && my === ey) return 1;
      let t, face;
      if (tx < ty) { t = tx; tx += tdx; mx += sx; face = sx > 0 ? 0 : 1; } else { t = ty; ty += tdy; my += sy; face = sy > 0 ? 2 : 3; }
      if (t >= 1) return 1;
      if (!this.inside(mx, my)) { this.hitFace = face; return t; }
      const i = my * this.w + mx, z = z0 + (z1 - z0) * t;
      if (this.solid[i] || z < this.floor[i] || z > this.ceil[i]) { this.hitI = i; this.hitFace = face; return t; }
    }
    return 1;
  },
  see(x0, y0, z0, x1, y1, z1) { return this.trace(x0, y0, z0, x1, y1, z1) >= 0.999; },
  // how many steps from every cell to x y, for things that walk (step: the highest step up; room: headroom; through:
  // cells they get past whatever (doors they open); avoid: cells they'd rather not cross (fire), crossed only when
  // there's no other way); -1: no way
  flow(x, y, step, room, through, avoid) {
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
        if (d[j] >= 0 || this.solid[j] || this.mask[j] || (this.ceil[j] - this.floor[j] < room && !(through && through[j]))) continue;
        if (fz > this.floor[j] + step || this.floor[j] > fz + step) continue;      // (both ways: they walk to you)
        if (avoid && avoid[j]) { d[j] = d[i] + 24; q[tail++] = j; continue; }   // (the long way round, unless there's none)
        d[j] = d[i] + 1; q[tail++] = j;
      }
    }
    return d;
  }
};

// ---------------------------------------------------------------- the drawing itself
// RAYCORE makes the code that draws: the same on the page and in the helpers (its source starts them), so it uses
// nothing from outside itself. A Core draws columns x0..x1 of a picture w×h into buf (x1 - x0 wide).
function RAYCORE() {
  "use strict";
  function Core() {
    this.w = 0; this.h = 0; this.x0 = 0; this.x1 = 0; this.sw = 0; this.buf = null; this.depth = null; this.rowInv = null;
    this.tex = []; this.sky = null; this.dtex = [null]; this.cm = null; this.full = null; this.fogPx = 0;
    this.dim = 2.4; this.minL = 0; this.maxD = 40; this.queue = []; this.qn = 0; this.track = null; this.map = null; this.cam = null;
    this.mD = new Float32Array(6); this.mI = new Int32Array(6); this.mU = new Int32Array(6); this.mS = new Int32Array(6); this.mT = new Int32Array(6); this.mB = new Int32Array(6);
    this.far = 1;                                    // how soon a texture goes over to its smaller selves (0: never)
  }
  Core.prototype = {
    // A texture's smaller selves. Far off, many of a texture's texels fall in one pixel of the picture, and which of
    // them is drawn changes with every step you take: floors and ceilings crawl, and a small picture is mostly far
    // off. Each smaller self is the texture in blocks of 2, 4, 8 and 16 texels of one colour: the palette's nearest to
    // the block's own (as fully lit), from the ramps the block has; a block that's a quarter light or more stays a
    // light. They're kept at the texture's own size, so the drawing is the same and costs the same. Made the first
    // time a texture is seen far off (here and in each helper).
    smaller(t) {
      const px = t.px, CM = this.cm, full = this.full, m = [px];
      if (px.length !== 4096 || !CM) return [px, px, px, px, px];
      const has = new Uint8Array(16);
      for (let L = 1; L <= 4; L++) {
        const b = 1 << L, out = new Uint8Array(4096);
        for (let u = 0; u < 64; u += b) for (let v = 0; v < 64; v += b) {
          let r = 0, g = 0, bl = 0, n = 0, lr = 0, lg = 0, lb = 0, ln = 0; has.fill(0);
          for (let du = 0; du < b; du++) for (let dv = 0; dv < b; dv++) {
            const idx = px[(u + du) * 64 + v + dv]; if (!idx) continue;
            const c = CM[7936 | idx];
            if (full[idx]) { lr += c & 255; lg += (c >> 8) & 255; lb += (c >> 16) & 255; ln++; has[idx >> 4] |= 2; }
            else { r += c & 255; g += (c >> 8) & 255; bl += (c >> 16) & 255; n++; has[idx >> 4] |= 1; }
          }
          let best = 0;
          if (n + ln) {
            const lit = ln * 4 >= b * b || !n, k = lit ? ln : n, bit = lit ? 2 : 1, tr = (lit ? lr : r) / k, tg = (lit ? lg : g) / k, tb = (lit ? lb : bl) / k;
            let bd = 1e9;
            for (let ramp = 0; ramp < 16; ramp++) {
              if (!(has[ramp] & bit)) continue;
              for (let sh = ramp ? 0 : 1; sh < 16; sh++) {
                const idx = ramp * 16 + sh; if (!!full[idx] !== lit) continue;
                const c = CM[7936 | idx], dr = (c & 255) - tr, dg = ((c >> 8) & 255) - tg, db = ((c >> 16) & 255) - tb, d = dr * dr + dg * dg + db * db;
                if (d < bd) { bd = d; best = idx; }
              }
            }
          }
          for (let du = 0; du < b; du++) for (let dv = 0; dv < b; dv++) out[(u + du) * 64 + v + dv] = best;
        }
        m.push(out);
      }
      return (t.m = m);
    },
    // the texture to draw with where one pixel of the picture is st of its texels
    lod(t, st) { return st < 2 ? t.px : (t.m || this.smaller(t))[st >= 16 ? 4 : st >= 8 ? 3 : st >= 4 ? 2 : 1]; },
    size(w, h, x0, x1, buf) {
      this.w = w; this.h = h; this.x0 = x0; this.x1 = x1; this.sw = x1 - x0;
      this.buf = buf || new Uint32Array(this.sw * h); this.depth = new Float32Array(this.sw * h); this.rowInv = new Float32Array(h);
    },
    // where the camera is, without drawing (what sprite() and project() need)
    view(m, cam) {
      const t = Math.tan(cam.fov / 2);
      this.map = m; this.cam = cam; this.f = (this.w / 2) / t; this.hz = this.h / 2 + cam.pitch * this.h; this.dirX = Math.cos(cam.a); this.dirY = Math.sin(cam.a); this.qn = 0;
    },
    // the world from a camera {x, y, z (eye height), a (facing), pitch (looking up: a share of the height), fov (across)}
    render(m, cam) {
      this.view(m, cam);
      const w = this.w, h = this.h, x0 = this.x0, x1 = this.x1, sw = this.sw, buf = this.buf, dep = this.depth, CM = this.cm, tex = this.tex, sky = this.sky, dtex = this.dtex, W = m.w, H = m.h;
      const solid = m.solid, wtex = m.wtex, stex = m.stex, utex = m.utex, ftex = m.ftex, ctex = m.ctex, flo = m.floor, cei = m.ceil, lig = m.light, dyn = m.dyn, seen = m.seen;
      const tint = m.tint, dtint = m.dtint, wdec = m.wdec, fdec = m.fdec, mask = m.mask, track = this.track;
      const dirX = this.dirX, dirY = this.dirY, t = Math.tan(cam.fov / 2), plX = -dirY * t, plY = dirX * t;
      const f = this.f, hz = this.hz, px = cam.x, py = cam.y, ez = cam.z, dim = this.dim, rowInv = this.rowInv;
      const fogPx = this.fogPx, maxD = this.maxD || 40, mL = this.minL, MK = 64 / f * this.far, MF = MK * 1.5;   // (texels a pixel, a cell away: on a wall, on a floor)
      for (let y = 0; y < h; y++) { const d = y + 0.5 - hz; rowInv[y] = Math.abs(d) < 1e-3 ? 1e3 : 1 / d; }
      const R = (b) => b < 0 ? 0 : b > h ? h : Math.ceil(b - 0.5);
      // a wall's column at d1, from zTop down to zBot (made once a frame: it reads the column's state below)
      let xo = 0, d1 = 0, top = 0, bot = h, u = 0, Lw = 0, vs = 0, cb = 0;
      const wall = (T, zTop, zBot) => {
        const yA = Math.max(R(hz - (zTop - ez) * f / d1), top), yB = Math.min(R(hz - (zBot - ez) * f / d1), bot);
        if (yA >= yB) return;
        let s = (Lw - d1 * dim) | 0; s = s < mL ? mL : s > 31 ? 31 : s; s = cb | (s << 8);
        let v = (-(ez + (hz - (yA + 0.5)) * d1 / f)) * 64 + 65536;
        const step = vs, uu = u;
        for (let y = yA, o = yA * sw + xo; y < yB; y++, v += step, o += sw) { buf[o] = CM[s | T[uu | ((v | 0) & 63)]]; dep[o] = d1; }
      };
      const mD = this.mD, mI = this.mI, mU = this.mU, mS = this.mS, mT = this.mT, mB = this.mB, MM = mD.length;
      const skyW = sky ? sky.w : 1, skyH = sky ? sky.h : 1, skyK = sky ? skyH / (h * 0.62) : 0, TAU = Math.PI * 2;
      for (let x = x0; x < x1; x++) {
        xo = x - x0;
        const camX = 2 * (x + 0.5) / w - 1, rdx = dirX + plX * camX, rdy = dirY + plY * camX;
        let mx = Math.floor(px), my = Math.floor(py);
        const ddx = rdx === 0 ? 1e30 : Math.abs(1 / rdx), ddy = rdy === 0 ? 1e30 : Math.abs(1 / rdy), stX = rdx < 0 ? -1 : 1, stY = rdy < 0 ? -1 : 1;
        let sdx = rdx < 0 ? (px - mx) * ddx : (mx + 1 - px) * ddx, sdy = rdy < 0 ? (py - my) * ddy : (my + 1 - py) * ddy;
        let ci = my * W + mx, d0 = 0, mn = 0; top = 0; bot = h;
        let skyU = -1;
        for (let guard = 0; guard < 128 && top < bot; guard++) {
          let side;
          if (sdx < sdy) { d1 = sdx; sdx += ddx; mx += stX; side = 0; } else { d1 = sdy; sdy += ddy; my += stY; side = 1; }
          if (d1 > maxD) d1 = maxD;
          const cF = flo[ci], cC = cei[ci], Lc = lig[ci] + dyn[ci];
          cb = (dtint[ci] || tint[ci]) << 13;
          if (!seen[ci]) { seen[ci] = 1; if (track) track.push(ci); }
          // this cell's floor, d0 to d1 (its marks, if it has them)
          if (ez > cF) {
            const yA = Math.max(R(hz - (cF - ez) * f / d1), top), yB = Math.min(d0 > 0 ? R(hz - (cF - ez) * f / d0) : h, bot), k = (ez - cF) * f, fd = fdec[ci], T = fd ? dtex[fd].px : this.lod(tex[ftex[ci]], (d0 + d1) * 0.5 * MF);
            for (let y = yA, o = yA * sw + xo; y < yB; y++, o += sw) {
              const d = k * rowInv[y];
              let s = (Lc - d * dim) | 0; s = s < mL ? mL : s > 31 ? 31 : s;
              buf[o] = CM[cb | (s << 8) | T[((((px + rdx * d) * 64) & 63) << 6) | (((py + rdy * d) * 64) & 63)]]; dep[o] = d;
            }
            if (yA < yB && yB > 0) bot = Math.min(bot, yA);
          }
          // its ceiling (or the sky)
          if (ez < cC) {
            const yA = Math.max(d0 > 0 ? R(hz - (cC - ez) * f / d0) : 0, top), yB = Math.min(R(hz - (cC - ez) * f / d1), bot);
            if (ctex[ci] === 255 && sky) {
              if (skyU < 0) { let a = (cam.a + Math.atan(camX * t)) / TAU; a -= Math.floor(a); skyU = ((a * skyW) | 0) * skyH; }
              const S = sky.px;
              for (let y = yA, o = yA * sw + xo; y < yB; y++, o += sw) { let v = (skyH - 1 + (y + 0.5 - hz) * skyK) | 0; v = v < 0 ? 0 : v >= skyH ? skyH - 1 : v; buf[o] = CM[7936 | S[skyU + v]]; dep[o] = 1e9; }
            } else {
              const k = (ez - cC) * f, T = this.lod(tex[ctex[ci]], (d0 + d1) * 0.5 * MF);
              for (let y = yA, o = yA * sw + xo; y < yB; y++, o += sw) {
                const d = k * rowInv[y];
                let s = (Lc - d * dim) | 0; s = s < mL ? mL : s > 31 ? 31 : s;
                buf[o] = CM[cb | (s << 8) | T[((((px + rdx * d) * 64) & 63) << 6) | (((py + rdy * d) * 64) & 63)]]; dep[o] = d;
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
          if (solid[ni]) {
            const dc = wdec[ni * 4 + (side === 0 ? (stX > 0 ? 0 : 1) : (stY > 0 ? 2 : 3))];
            wall(dc ? dtex[dc].px : this.lod(tex[wtex[ni]], d1 * MK), cC, cF);
            if (!seen[ni]) { seen[ni] = 1; if (track) track.push(ni); }
            top = bot; break;
          }
          if (mask[ni] && mn < MM) {                   // a wall you see through: drawn over the rest of this column, after
            let s = (Lw - d1 * dim) | 0; s = s < mL ? mL : s > 31 ? 31 : s;
            mD[mn] = d1; mI[mn] = ni; mU[mn] = u; mS[mn] = cb | (s << 8); mT[mn] = top; mB[mn] = bot; mn++;
          }
          const nF = flo[ni], nC = cei[ni];
          if (nF > cF) { wall(this.lod(tex[stex[ni]], d1 * MK), nF, cF); bot = Math.min(bot, R(hz - (nF - ez) * f / d1)); }
          else bot = Math.min(bot, R(hz - (cF - ez) * f / d1));
          if (nC < cC) { wall(this.lod(tex[utex[ni]], d1 * MK), cC, nC); top = Math.max(top, R(hz - (nC - ez) * f / d1)); }
          else top = Math.max(top, R(hz - (cC - ez) * f / d1));
          ci = ni; d0 = d1;
        }
        for (let y = top, o = top * sw + xo; y < bot; y++, o += sw) { buf[o] = fogPx; dep[o] = 1e9; }   // (nothing there: far fog)
        // the walls you see through, the far ones first: one texture tall, standing on their cell's floor
        for (let k = mn - 1; k >= 0; k--) {
          const d = mD[k], ni = mI[k], T = tex[mask[ni]].px, uu = mU[k], s = mS[k], fz = flo[ni];
          const yA = Math.max(R(hz - (Math.min(cei[ni], fz + 1) - ez) * f / d), mT[k]), yB = Math.min(R(hz - (fz - ez) * f / d), mB[k]);
          if (yA >= yB) continue;
          const step = 64 * d / f; let v = (fz + 1 - ez - (hz - (yA + 0.5)) * d / f) * 64;
          for (let y = yA, o = yA * sw + xo; y < yB; y++, v += step, o += sw) { const idx = T[uu | ((v | 0) & 63)]; if (idx) { buf[o] = CM[s | idx]; dep[o] = d; } }
        }
      }
    },
    // the light's colour where a thing stands (its cell's tint), as a colormap offset
    tintAt(x, y) { const m = this.map; if (!m || x < 0 || y < 0 || x >= m.w || y >= m.h) return 0; const i = (y | 0) * m.w + (x | 0); return (m.dtint[i] || m.tint[i]) << 13; },
    // a sprite standing at x y (its foot at height z), light 0..31 (full: drawn as it is), flip: mirrored, scale, rm: its
    // colours swapped (256 indices: one set of sprites in many team colours)
    sprite(s, x, y, z, light, full, flip, scale, rm) {
      const c = this.cam, dx = x - c.x, dy = y - c.y, d = dx * this.dirX + dy * this.dirY;
      if (d < 0.15 || d > (this.maxD || 40)) return;
      if (this.qn >= this.queue.length) this.queue.push({});
      const q = this.queue[this.qn++];
      q.s = s; q.d = d; q.lat = dx * -this.dirY + dy * this.dirX; q.z = z; q.light = light; q.full = full; q.flip = flip; q.k = scale || 1; q.dot = 0;
      q.cb = full ? 0 : this.tintAt(x, y); q.x = x; q.y = y; q.rm = rm || null;
    },
    dot(x, y, z, idx, size, full) {                  // a speck (spark, blood, smoke): a small square, world size
      const c = this.cam, dx = x - c.x, dy = y - c.y, d = dx * this.dirX + dy * this.dirY;
      if (d < 0.3 || d > 24) return;                 // (none right at the eye: they'd fill the screen)
      if (this.qn >= this.queue.length) this.queue.push({});
      const q = this.queue[this.qn++];
      q.s = null; q.d = d; q.lat = dx * -this.dirY + dy * this.dirX; q.z = z; q.idx = idx; q.size = size; q.full = full; q.dot = 1; q.light = 24;
      q.cb = full ? 0 : this.tintAt(x, y); q.x = x; q.y = y;
    },
    // a list of specks at once, each {x, y, z} (and its own idx, size, full where they're not given here): the same as
    // dot() for each, without a number handed over for each (which is a number made on the heap, for every speck)
    dots(list, idx, size, full) {
      const c = this.cam, own = idx == null, m = this.map, W = m ? m.w : 0, H = m ? m.h : 0;
      for (let i = 0; i < list.length; i++) {
        const p = list[i], dx = p.x - c.x, dy = p.y - c.y, d = dx * this.dirX + dy * this.dirY;
        if (d < 0.3 || d > 24) continue;
        if (this.qn >= this.queue.length) this.queue.push({});
        const q = this.queue[this.qn++], f = own ? p.full : full, cx = p.x | 0, cy = p.y | 0;
        q.s = null; q.d = d; q.lat = dx * -this.dirY + dy * this.dirX; q.z = p.z; q.idx = own ? p.idx : idx; q.size = own ? p.size : size; q.full = f; q.dot = 1; q.light = 24;
        q.cb = f || p.x < 0 || p.y < 0 || cx >= W || cy >= H ? 0 : (m.dtint[cy * W + cx] || m.tint[cy * W + cx]) << 13;   // (its cell's tint, as tintAt says: worked out here, with no number handed over)
        q.x = p.x; q.y = p.y;
      }
    },
    flush() {                                         // the sprites, far to near, behind what's nearer
      const Q = this.queue, n = this.qn, w = this.w, h = this.h, x0 = this.x0, x1 = this.x1, sw = this.sw, buf = this.buf, dep = this.depth, CM = this.cm;
      const f = this.f, hz = this.hz, ez = this.cam.z, dim = this.dim, full = this.full, mL = this.minL, dotMax = Math.max(2, Math.round(h / 45));
      for (let i = 1; i < n; i++) { const e = Q[i]; let j = i - 1; while (j >= 0 && Q[j].d < e.d) { Q[j + 1] = Q[j]; j--; } Q[j + 1] = e; }
      for (let i = 0; i < n; i++) {
        const q = Q[i], d = q.d, sx = w / 2 + q.lat * f / d;
        if (q.dot) {
          const sz = Math.min(dotMax, Math.max(1, q.size * f / d) | 0), cy = hz - (q.z - ez) * f / d, X0 = (sx - sz / 2) | 0, Y0 = (cy - sz / 2) | 0;
          let s = (24 - d * dim) | 0; s = q.full ? 31 : s < 0 ? 0 : s > 31 ? 31 : s;
          const col = CM[q.cb | (s << 8) | q.idx];
          for (let y = Math.max(0, Y0); y < Math.min(h, Y0 + sz); y++) for (let x = Math.max(x0, X0); x < Math.min(x1, X0 + sz); x++) { const o = y * sw + x - x0; if (dep[o] > d) buf[o] = col; }
          continue;
        }
        const s = q.s; if (!s) continue;
        const k = f / d / s.ppu * q.k, swd = s.w * k, sh = s.h * k;
        const left = sx - s.ax * k, topY = hz - (q.z - ez) * f / d - s.ay * k;
        const X0 = Math.max(x0, Math.ceil(left - 0.5)), X1 = Math.min(x1, Math.ceil(left + swd - 0.5)), Y0 = Math.max(0, Math.ceil(topY - 0.5)), Y1 = Math.min(h, Math.ceil(topY + sh - 0.5));
        if (X0 >= X1 || Y0 >= Y1) continue;
        let L = (q.light - d * dim) | 0; L = L < mL ? mL : L > 31 ? 31 : L; const Ls = q.cb | (L << 8);
        const P = s.px, H = s.h, inv = 1 / k, rm = q.rm ? q.rm.px || q.rm : null;
        for (let x = X0; x < X1; x++) {
          let uu = ((x + 0.5 - left) * inv) | 0; if (uu >= s.w) uu = s.w - 1; if (q.flip) uu = s.w - 1 - uu;
          const col = uu * H;
          let v = (Y0 + 0.5 - topY) * inv;
          for (let y = Y0, o = Y0 * sw + x - x0; y < Y1; y++, v += inv, o += sw) {
            if (dep[o] <= d) continue;
            let idx = P[col + (v | 0)]; if (!idx) continue; if (rm) idx = rm[idx];
            buf[o] = CM[(q.full || full[idx] ? 7936 : Ls) | idx];
          }
        }
      }
      this.qn = 0;
    }
  };
  return Core;
}
const RayCore = RAYCORE();

// a helper's side: it keeps its own copy of the textures, the sprites and the map (sent once, then what changed), and
// draws its strip of each frame it's sent, handing the picture back
function RAYHELPER(Core) {
  const core = new Core(), store = [];
  let m = null; const seenNew = []; core.track = seenNew;
  onmessage = (e) => {
    const d = e.data;
    // (a texture's smaller selves are made as it arrives, while a level loads, not the first time it's seen far off)
    if (d.k === "pal") { core.cm = d.cm; core.full = d.full; core.fogPx = d.fogPx; for (const t of store) if (t && !t.m && t.px && t.px.length === 4096) core.smaller(t); return; }
    if (d.k === "tex") { store[d.id] = d.t; if (core.cm && d.t.px && d.t.px.length === 4096) core.smaller(d.t); return; }
    if (d.k === "map") { m = d.m; core.dtex = [null]; return; }
    if (d.k === "dtex") { core.dtex[d.slot] = { px: d.px }; return; }
    if (d.k !== "frame" || !m) return;
    const t0 = performance.now(), c = d.ch;
    for (let k = 0; k < c.i.length; k++) { const i = c.i[k]; m.floor[i] = c.floor[k]; m.ceil[i] = c.ceil[k]; m.light[i] = c.light[k]; m.dyn[i] = c.dyn[k]; m.tint[i] = c.tint[k]; m.dtint[i] = c.dtint[k]; }
    for (let k = 0; k < d.wd.length; k += 2) m.wdec[d.wd[k]] = d.wd[k + 1];
    for (let k = 0; k < d.fd.length; k += 2) m.fdec[d.fd[k]] = d.fd[k + 1];
    core.tex.length = d.tex.length; for (let k = 0; k < d.tex.length; k++) core.tex[k] = store[d.tex[k]];
    core.sky = d.sky >= 0 ? store[d.sky] : null; core.dim = d.dim; core.minL = d.minL; core.maxD = d.maxD; core.far = d.far;
    const need = (d.x1 - d.x0) * d.h;
    if (core.w !== d.w || core.h !== d.h || core.x0 !== d.x0 || core.x1 !== d.x1) core.size(d.w, d.h, d.x0, d.x1, null);
    core.buf = d.buf && d.buf.byteLength === need * 4 ? new Uint32Array(d.buf) : new Uint32Array(need);
    seenNew.length = 0;
    core.render(m, d.cam);
    const q = d.q;
    for (let k = 0; k < d.qn; k++) {
      const o = k * 9;
      if (q[o] < 0) core.dot(q[o + 1], q[o + 2], q[o + 3], q[o + 4], q[o + 5], q[o + 6]);
      else core.sprite(store[q[o]], q[o + 1], q[o + 2], q[o + 3], q[o + 4], q[o + 5], q[o + 6], q[o + 7], q[o + 8] ? store[q[o + 8]] : null);
    }
    core.flush();
    const ms = performance.now() - t0;
    if (d.slow > 1) { const until = performance.now() + ms * (d.slow - 1); while (performance.now() < until) { /* a slower processor, for checks */ } }
    postMessage({ k: "strip", id: d.id, x0: d.x0, buf: core.buf.buffer, seen: seenNew.length ? Int32Array.from(seenNew) : null, ms: performance.now() - t0 }, [core.buf.buffer]);
  };
}

// ---------------------------------------------------------------- the helpers, from the page's side
// n web workers, each drawing a strip of every frame. Two frames can be on their way at once, so the helpers never wait
// on the page; the newest finished world is what the page shows (the game's blits, a weapon in hand, go on top of it
// each frame): a frame or two behind, so the page's own work and the drawing overlap.
// (A strip's memory is handed to its helper and back each frame. Drawing into memory shared with the page instead, where
// a page may have it, was tried and measured: the page's collector came round no less often, so it isn't here.)
let helperURL = null;
const NONE32 = new Int32Array(0), NOLIST = [];
const NOCELLS = { i: NONE32, floor: new Float32Array(0), ceil: new Float32Array(0), light: new Uint8Array(0), dyn: new Uint8Array(0), tint: new Uint8Array(0), dtint: new Uint8Array(0) };
function Helpers(n, onFail) {
  if (!helperURL) helperURL = URL.createObjectURL(new Blob(["\"use strict\";\nconst Core = (" + RAYCORE.toString() + ")();\n(" + RAYHELPER.toString() + ")(Core);\n"], { type: "text/javascript" }));
  this.n = n; this.list = []; this.id = 0; this.done = 0; this.frames = new Map(); this.world = null; this.w = 0; this.h = 0; this.palVer = -1; this.map = null; this.shadow = null;
  this.ids = new WeakMap(); this.nextId = 1; this.ms = 0; this.fresh = 0; this.dead = false; this.onFail = onFail; this.depth = 2; this.qs = [];
  for (let i = 0; i < n; i++) {
    const wk = new Worker(helperURL);
    wk.onmessage = e => this.back(i, e.data);
    wk.onerror = () => this.fail();
    this.list.push({ wk, free: [], ms: 0 });
  }
}
Helpers.prototype = {
  get busy() { return this.frames.size; },
  fail() { if (this.dead) return; this.dead = true; this.stop(); if (this.onFail) this.onFail(); },
  stop() { for (const h of this.list) { try { h.wk.terminate(); } catch (e) { /* gone */ } } this.list = []; },
  post(msg, transfer) { for (const h of this.list) h.wk.postMessage(msg, transfer || []); },
  idOf(t) {                                          // a texture's or sprite's number: sent to the helpers the first time
    if (!t || typeof t !== "object") return 0;
    let id = this.ids.get(t);
    if (!id) { id = this.nextId++; this.ids.set(t, id); this.post({ k: "tex", id, t: { w: t.w, h: t.h, px: t.px || t, ax: t.ax, ay: t.ay, ppu: t.ppu } }); }
    return id;
  },
  prime(list) { for (const t of list) this.idOf(t); },   // send these now (a level's sprites), not when first drawn
  // one frame: send what changed, the camera and the sprites; false when two are already on their way
  send(ray, m, cam, core, slow) {
    if (this.frames.size >= this.depth || this.dead || !this.list.length) return false;
    const pal = ray.pal, n = m.w * m.h;
    if (pal.ver !== this.palVer) { this.palVer = pal.ver; this.post({ k: "pal", cm: pal.cmap, full: pal.full, fogPx: pal.fogPx }); }
    if (m !== this.map) {
      this.map = m; const keep = ["solid", "wtex", "stex", "utex", "ftex", "ctex", "floor", "ceil", "light", "dyn", "seen", "tint", "dtint", "mask", "wdec", "fdec"], copy = { w: m.w, h: m.h };
      for (const k of keep) copy[k] = m[k].slice();
      this.post({ k: "map", m: copy });
      this.shadow = { floor: m.floor.slice(), ceil: m.ceil.slice(), light: m.light.slice(), dyn: m.dyn.slice(), tint: m.tint.slice(), dtint: m.dtint.slice(), wdec: m.wdec.slice(), fdec: m.fdec.slice() };
      this.markVer = []; this.moved = -1;
    }
    const mk = ray.marks;
    if (mk && mk.map === m) for (let s = 1; s < mk.tex.length; s++) if ((this.markVer[s] || 0) !== mk.ver[s]) { this.markVer[s] = mk.ver[s]; this.post({ k: "dtex", slot: s, px: mk.tex[s].px.slice() }); }
    // the cells that changed (doors, lifts, lights)
    // (Nothing here is made anew each frame where it can be helped: a message's arrays are copied as it's sent, so the
    // same ones go again; most frames no cell has changed and no mark has moved.)
    const S = this.shadow;
    if (!this.chI || this.chI.length < n) this.chI = new Int32Array(n);
    const ch = this.chI; let k = 0;
    for (let i = 0; i < n; i++) {
      if (m.floor[i] !== S.floor[i] || m.ceil[i] !== S.ceil[i] || m.light[i] !== S.light[i] || m.dyn[i] !== S.dyn[i] || m.tint[i] !== S.tint[i] || m.dtint[i] !== S.dtint[i]) {
        ch[k++] = i; S.floor[i] = m.floor[i]; S.ceil[i] = m.ceil[i]; S.light[i] = m.light[i]; S.dyn[i] = m.dyn[i]; S.tint[i] = m.tint[i]; S.dtint[i] = m.dtint[i];
      }
    }
    let C = NOCELLS;
    if (k) {
      C = { i: ch.slice(0, k), floor: new Float32Array(k), ceil: new Float32Array(k), light: new Uint8Array(k), dyn: new Uint8Array(k), tint: new Uint8Array(k), dtint: new Uint8Array(k) };
      for (let j = 0; j < k; j++) { const i = ch[j]; C.floor[j] = m.floor[i]; C.ceil[j] = m.ceil[i]; C.light[j] = m.light[i]; C.dyn[j] = m.dyn[i]; C.tint[j] = m.tint[i]; C.dtint[j] = m.dtint[i]; }
    }
    let wd = NONE32, fd = NONE32; const sw = S.wdec, sf = S.fdec;      // (the marks moved onto faces and floors since the last frame)
    if (mk && mk.map === m && this.moved !== mk.moved) {
      this.moved = mk.moved; const a = [], b = [];
      for (let i = 0; i < m.wdec.length; i++) if (m.wdec[i] !== sw[i]) { sw[i] = m.wdec[i]; a.push(i, sw[i]); }
      for (let i = 0; i < n; i++) if (m.fdec[i] !== sf[i]) { sf[i] = m.fdec[i]; b.push(i, sf[i]); }
      if (a.length) wd = new Int32Array(a); if (b.length) fd = new Int32Array(b);
    }
    if (!this.texIds || this.texIds.length !== ray.tex.length) this.texIds = new Int32Array(ray.tex.length);
    const tex = this.texIds; for (let j = 0; j < ray.tex.length; j++) tex[j] = ray.tex[j] ? this.idOf(ray.tex[j]) : 0;
    const sky = ray.sky ? this.idOf(ray.sky) : -1;
    // the sprites and specks, as numbers (in a list kept for each size of list: 16, 32, 64… of them)
    const qn = core.qn; let cap = 16, slot = 0; while (cap < qn) { cap *= 2; slot++; }
    const q = this.qs[slot] || (this.qs[slot] = new Float64Array(cap * 9));
    for (let j = 0; j < qn; j++) {
      const e = core.queue[j], o = j * 9;
      if (e.dot) { q[o] = -1; q[o + 1] = e.x; q[o + 2] = e.y; q[o + 3] = e.z; q[o + 4] = e.idx; q[o + 5] = e.size; q[o + 6] = e.full ? 1 : 0; }
      else { q[o] = this.idOf(e.s); q[o + 1] = e.x; q[o + 2] = e.y; q[o + 3] = e.z; q[o + 4] = e.light; q[o + 5] = e.full ? 1 : 0; q[o + 6] = e.flip ? 1 : 0; q[o + 7] = e.k; q[o + 8] = e.rm ? this.idOf(e.rm) : 0; }
    }
    core.qn = 0;
    const w = ray.w, h = ray.h, cv = { x: cam.x, y: cam.y, z: cam.z, a: cam.a, pitch: cam.pitch, fov: cam.fov }, id = ++this.id, L = this.list.length;
    this.frames.set(id, { left: L, w, h, strips: [], ms: 0 });
    for (let j = 0; j < L; j++) {
      const hp = this.list[j], x0 = Math.round(w * j / L), x1 = Math.round(w * (j + 1) / L), need = (x1 - x0) * h * 4;
      let buf = null; while (hp.free.length) { const b0 = hp.free.pop(); if (b0.byteLength === need) { buf = b0; break; } }
      hp.wk.postMessage({ k: "frame", id, x0, x1, w, h, buf, cam: cv, ch: C, wd, fd, tex, sky, dim: ray.dim, minL: ray.minL, maxD: ray.maxD, far: ray.far, q, qn, slow: slow || 1 }, buf ? [buf] : NOLIST);
    }
    return true;
  },
  back(i, d) {                                       // a strip, drawn
    const hp = this.list[i]; if (!hp) return;
    hp.ms = d.ms;
    if (this.map && d.seen) for (let k = 0; k < d.seen.length; k++) this.map.seen[d.seen[k]] = 1;
    const f = this.frames.get(d.id);
    if (!f) { hp.free.push(d.buf); return; }
    f.strips.push({ i, x0: d.x0, buf: d.buf });
    if (hp.ms > f.ms) f.ms = hp.ms;
    if (--f.left > 0) return;
    // all of them: the picture, put together (unless it's a size the screen no longer is)
    this.frames.delete(d.id);
    const w = f.w, h = f.h;
    if (w === this.w && h === this.h && d.id > this.done) {
      if (!this.world || this.world.length !== w * h) this.world = new Uint32Array(w * h);
      const world = this.world, strips = f.strips;      // (a pixel at a time: a view of each row would be 540 new things a frame)
      for (let j = 0; j < strips.length; j++) {
        const src = new Uint32Array(strips[j].buf), sw = (src.length / h) | 0, x0 = strips[j].x0;
        for (let y = 0, o = 0; y < h; y++) { const d = y * w + x0; for (let x = 0; x < sw; x++) world[d + x] = src[o++]; }
      }
      this.done = d.id; this.fresh++;
    }
    for (let j = 0; j < f.strips.length; j++) { const s = f.strips[j]; this.list[s.i].free.push(s.buf); }
    const ms = f.ms;
    this.ms = this.ms ? this.ms + (ms - this.ms) * 0.15 : ms;           // (smoothed: one slow strip isn't a slow box)
  },
  size(w, h) { this.w = w; this.h = h; this.world = null; this.ms = 0; for (const hp of this.list) hp.free.length = 0; }
};

// ---------------------------------------------------------------- marks that stay (rivet holes, scorch, blood, oil)
// stamped into a copy of the wall's face or the floor's texture, so drawing them costs nothing; a pool of copies (max),
// the oldest given back when it's full. A stamp: {r: its radius in texels (64 a cell), kind: "hole" (dark, a rim),
// "scorch" (darker, fading out), "splat" (a colour: ramp), "stain" (a colour, faint), "frost" (a white star, ramp at its edges)}
function Marks(ray, m, max) {
  this.ray = ray; this.map = m; this.max = Math.max(4, max || 96); this.tex = [null]; this.key = [0]; this.order = []; this.byKey = new Map();
  this.ver = [0]; this.moved = 0; this.seed = 1;     // (ver: each copy's changes, moved: copies put on or taken off faces; for the helpers)
  ray.marks = this;
}
Marks.prototype = {
  // the slot for a wall face (key i·4 + face + 1) or a floor (key -(i + 1)), copied from its texture the first time
  slot(key, base) {
    let s = this.byKey.get(key);
    if (s) return s;
    if (this.tex.length <= this.max) { s = this.tex.length; this.tex.push({ px: new Uint8Array(4096) }); this.key.push(0); this.ver.push(0); }
    else { s = this.order.shift(); this.unhook(this.key[s]); }
    this.tex[s].px.set(base.px.length === 4096 ? base.px : new Uint8Array(4096).fill(1));
    this.key[s] = key; this.byKey.set(key, s); this.order.push(s); this.hook(key, s);
    return s;
  },
  hook(key, s) { const m = this.map; if (key > 0) m.wdec[key - 1] = s; else m.fdec[-key - 1] = s; this.moved++; },
  unhook(key) { if (!key) return; this.byKey.delete(key); this.hook(key, 0); },
  rnd() { this.seed = (this.seed * 16807) % 2147483647; return this.seed / 2147483647; },
  // one stamp into a texture's pixels, centred on texel (u, v); col: true when the texture's columns run up a wall
  stamp(px, u, v, st, wrapV) {
    const r = st.r, full = this.ray.pal.full, R2 = r * r, ramp = st.ramp == null ? 12 : st.ramp;
    for (let du = -Math.ceil(r); du <= r; du++) for (let dv = -Math.ceil(r); dv <= r; dv++) {
      const d2 = du * du + dv * dv; if (d2 > R2) continue;
      let uu = u + du, vv = v + dv; if (uu < 0 || uu > 63) continue;
      if (vv < 0 || vv > 63) { if (!wrapV) continue; vv &= 63; }
      const o = uu * 64 + vv, idx = px[o], k = Math.sqrt(d2) / Math.max(1, r), sh = idx & 15, rp = idx >> 4;
      if (full[idx] && st.kind !== "scorch") continue;
      if (st.kind === "hole") px[o] = k < 0.55 ? rp * 16 + 1 : k < 0.85 ? rp * 16 + Math.max(1, sh - 4) : rp * 16 + Math.min(15, sh + 2);
      else if (st.kind === "scorch") { if (this.rnd() < 1.15 - k) px[o] = (full[idx] ? 12 : rp) * 16 + Math.max(1, Math.round(sh * (0.25 + k * 0.7))); }
      else if (st.kind === "splat") { if (this.rnd() < (1 - k * k) * 0.95) px[o] = ramp * 16 + Math.max(1, Math.min(15, 4 + ((this.rnd() * 5) | 0) - (k > 0.7 ? 2 : 0))); }
      else if (st.kind === "stain") { if (this.rnd() < (1 - k) * 0.7) px[o] = ramp * 16 + Math.max(1, Math.min(sh, 3 + ((this.rnd() * 3) | 0))); }
      else if (st.kind === "frost") { const a = Math.atan2(dv, du) * 3, star = 0.55 + 0.45 * Math.abs(Math.cos(a)); if (this.rnd() < (1 - k / star) * 1.2) px[o] = (this.rnd() < 0.35 ? ramp : 0) * 16 + 11 + ((this.rnd() * 5) | 0); }
    }
  },
  // a mark on the face of wall cell i (face as RayMap.trace says), where the line hit it at x y z
  wall(i, face, x, y, z, st) {
    const m = this.map; if (i < 0 || face < 0 || !m.solid[i]) return;
    const base = this.ray.tex[m.wtex[i]]; if (!base) return;
    let a = face < 2 ? y : x; a -= Math.floor(a); if (face === 0 || face === 3) a = 1 - a;
    const s = this.slot(i * 4 + face + 1, base), u = Math.min(63, (a * 64) | 0), v = ((Math.floor(-z * 64) % 64) + 64) % 64;
    this.stamp(this.tex[s].px, u, v, st, true); this.touch(s);
  },
  // a mark on the floor, centred at x y: into every cell it reaches
  floor(x, y, st) {
    const m = this.map, rc = st.r / 64;
    for (let cy = Math.floor(y - rc); cy <= Math.floor(y + rc); cy++) for (let cx = Math.floor(x - rc); cx <= Math.floor(x + rc); cx++) {
      if (cx < 0 || cy < 0 || cx >= m.w || cy >= m.h) continue;
      const i = cy * m.w + cx; if (m.solid[i] || m.mask[i]) continue;
      const base = this.ray.tex[m.ftex[i]]; if (!base) continue;
      const s = this.slot(-(i + 1), base);
      this.stamp(this.tex[s].px, Math.round((x - cx) * 64), Math.round((y - cy) * 64), st, false); this.touch(s);
    }
  },
  touch(s) { this.ver[s]++; }
};

// ---------------------------------------------------------------- the renderer, from the game's side
const NOMARKS = [null];
function Ray(pal) {
  this.pal = pal; this.tex = []; this.sky = null; this.dim = 2.4; this.minL = 0; this.maxD = 40; this.w = 0; this.h = 0;   // (minL: the darkest a lit thing gets)
  this.far = 1;                                      // (how soon textures go over to their smaller selves: see RayCore.smaller; 0: never)
  this.core = new RayCore(); this.helpers = null; this.marks = null; this.slow = 1; this.drew = 0; this.missed = 0;
}
Ray.prototype = {
  size(w, h, buf) {
    this.w = w; this.h = h; this.buf = buf;
    this.core.size(w, h, 0, w, buf); this.depth = this.core.depth; this.rowInv = this.core.rowInv;
    if (this.helpers) this.helpers.size(w, h);
  },
  // helpers: n web workers each drawing a strip of the picture (0: all on the page). Where they can't start, the page draws.
  threads(n) {
    if (this.helpers) { this.helpers.stop(); this.helpers = null; }
    if (!n || typeof Worker === "undefined" || typeof Blob === "undefined") return 0;
    try { this.helpers = new Helpers(n, () => { this.helpers = null; }); this.helpers.size(this.w, this.h); } catch (e) { this.helpers = null; }
    return this.helpers ? n : 0;
  },
  get threaded() { return !!(this.helpers && !this.helpers.dead); },
  takeMissed() { const k = this.missed; this.missed = 0; return k; },   // frames the helpers couldn't take (for the governor)
  prime(list) { if (this.threaded) this.helpers.prime(list); },        // textures and sprites to the helpers now, not when first drawn
  get helperMs() { return this.threaded ? this.helpers.ms : 0; },
  sync() {
    const c = this.core, p = this.pal;
    c.tex = this.tex; c.sky = this.sky; c.dim = this.dim; c.minL = this.minL; c.maxD = this.maxD; c.cm = p.cmap; c.full = p.full; c.fogPx = p.fogPx; c.far = this.far;
    c.dtex = this.marks && this.marks.map === this.m ? this.marks.tex : NOMARKS;
  },
  // the world from a camera {x, y, z (eye height), a (facing), pitch (looking up: a share of the height), fov (across)}
  render(m, cam) {
    this.m = m; this.sync();
    if (this.threaded) { this.core.view(m, cam); this.cam = cam; return; }
    this.core.render(m, cam); this.cam = cam;
  },
  sprite(s, x, y, z, light, full, flip, scale, rm) { this.core.sprite(s, x, y, z, light, full, flip, scale, rm); },
  dot(x, y, z, idx, size, full) { this.core.dot(x, y, z, idx, size, full); },
  dots(list, idx, size, full) { this.core.dots(list, idx, size, full); },   // (a list of {x, y, z} specks at once: see RayCore.dots)
  // the sprites; with helpers, this frame goes to them and the newest one they've finished is put in the picture
  flush() {
    if (this.threaded) {
      const H = this.helpers;
      if (!H.send(this, this.m, this.core.cam, this.core, this.slow)) { this.missed++; this.core.qn = 0; }
      if (H.world && H.world.length === this.buf.length) this.buf.set(H.world);
      this.drew = H.fresh;
      return;
    }
    this.core.flush(); this.drew++;
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
  // this picture into a bigger one (a split screen's view): its top left at x y of dst, dw wide
  paste(dst, dw, x, y) { const w = this.w, b = this.buf; for (let r = 0; r < this.h; r++) dst.set(b.subarray(r * w, r * w + w), (y + r) * dw + x); },
  // where a world point is on the screen: [x, y, distance], or null behind
  project(x, y, z, out) {
    const c = this.core, cam = c.cam, dx = x - cam.x, dy = y - cam.y, d = dx * c.dirX + dy * c.dirY;
    if (d < 0.1) return null;
    out[0] = this.w / 2 + (dx * -c.dirY + dy * c.dirX) * c.f / d; out[1] = c.hz - (z - cam.z) * c.f / d; out[2] = d;
    return out;
  }
};
// how many helpers a box gets: none on one or two cores; on four (every Pi), two, leaving the page and the browser theirs
function helpersFor(p) { const c = (p && p.cores) || navigator.hardwareConcurrency || 1; return c >= 4 ? Math.min(3, c - 2) : 0; }

// ---------------------------------------------------------------- the screen: a picture made a pixel at a time, shown
// scaled up; through WebGL where the GPU is real (smooth or crisp scaling, a soft glow round bright things, a little
// vignette: on a Pi 4 or 5), else straight onto a 2D canvas
const POST_VS = `attribute vec2 aXY; varying vec2 vUV; void main() { vUV = vec2(aXY.x * 0.5 + 0.5, 0.5 - aXY.y * 0.5); gl_Position = vec4(aXY, 0.0, 1.0); }`;
// Each pixel of the picture is a crisp block at any size, a whole number of times as big or not: inside a block the
// picture's own pixel, and at its edges one pixel of the canvas going over to the next (uSharp: how many times as big,
// and how much of a block is its inside; 1 and 0: smooth all through). One look at the picture a pixel; GLOW: four more.
const POST_FS = `
#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif
uniform sampler2D uT; uniform vec4 uSize; uniform vec4 uSharp; uniform float uVig; varying vec2 vUV;
#ifdef GLOW
uniform float uGlow;
#endif
void main() {
  vec2 p = vUV * uSize.xy, d = fract(p) - 0.5;
  vec2 uv = (floor(p) + (d - clamp(d, -uSharp.zw, uSharp.zw)) * uSharp.xy + 0.5) * uSize.zw;
  vec3 c = texture2D(uT, uv).rgb;
#ifdef GLOW
  vec3 b = texture2D(uT, uv + vec2(uSize.z * 1.5, 0.0)).rgb + texture2D(uT, uv - vec2(uSize.z * 1.5, 0.0)).rgb
         + texture2D(uT, uv + vec2(0.0, uSize.w * 1.5)).rgb + texture2D(uT, uv - vec2(0.0, uSize.w * 1.5)).rgb;
  c += max(b * 0.25 - 0.6, 0.0) * uGlow * 1.8;
#endif
  vec2 q = vUV - 0.5; c *= 1.0 - uVig * dot(q, q) * 1.6;
  gl_FragColor = vec4(c, 1.0);
}`;
// The picture is w × h; the canvas it's shown on is cw × ch, a size of its own: the screen's divided by a whole number
// (so the browser shows it crisp for nothing), and big enough for what's written over the picture (UI) to be read. A
// small picture costs the processor less; the canvas costs the GPU one look at the picture a pixel.
function Screen(c2d, cgl, useGL) {
  this.c2d = c2d; this.cgl = cgl; this.gl = null; this.w = 0; this.h = 0; this.cw = 0; this.ch = 0; this.crisp = true; this.P = {}; this.cur = null; this.mine = false;
  if (useGL) {
    try {
      const gl = cgl.getContext("webgl", { antialias: false, alpha: false, depth: false, preserveDrawingBuffer: false });
      if (!gl) throw new Error("no WebGL");
      this.gl = gl;
      if (!this.prog("plain")) throw new Error("no shader");
      this.quad = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, this.quad); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
      this.tex = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, this.tex);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      // what a UI needs of a renderer, to draw its list here (see UI.show)
      const S = this;
      this.g3 = { gl, canvas: cgl, vao: null, calls: 0, curBuf: null, prog: () => S.prog("ui"), use(P) { if (S.cur !== P) { gl.useProgram(P.p); S.cur = P; } return P.u; },
        picture(c) {
          const t = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, t); gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, c);
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
          return t;
        } };
    } catch (e) { this.gl = null; }
  }
  cgl.classList.toggle("hidden", !this.gl); c2d.classList.toggle("hidden", !!this.gl);
  if (!this.gl) { this.ctx = c2d.getContext("2d", { alpha: false }); this.tmp = document.createElement("canvas"); this.tctx = this.tmp.getContext("2d", { alpha: false }); }
}
Screen.prototype = {
  prog(name) {                                       // a program, made the first time it's wanted (null: this GPU can't)
    if (!(name in this.P)) {
      try { this.P[name] = name === "ui" ? GL.prototype.program.call(this, UI_VS, UI_FS) : GL.prototype.program.call(this, POST_VS, (name === "glow" ? "#define GLOW\n" : "") + POST_FS); }
      catch (e) { this.P[name] = null; }
    }
    return this.P[name];
  },
  // the picture's size (what the game draws into: u32, one number a pixel) and the canvas's (left out: the picture's)
  size(w, h, cw, ch) {
    cw = cw || w; ch = ch || h;
    if (w === this.w && h === this.h && cw === this.cw && ch === this.ch) return false;
    const pic = w !== this.w || h !== this.h;
    this.w = w; this.h = h; this.cw = cw; this.ch = ch;
    if (pic) { this.img = new ImageData(w, h); this.u8 = new Uint8Array(this.img.data.buffer); this.u32 = new Uint32Array(this.img.data.buffer); }
    if (this.gl) {
      const gl = this.gl; this.cgl.width = cw; this.cgl.height = ch; this.mine = false;
      if (pic) { gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, this.tex); gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, null); }
    } else { this.c2d.width = cw; this.c2d.height = ch; this.tmp.width = w; this.tmp.height = h; }
    return pic;
  },
  filter() { /* (crisp or smooth is this.crisp, read each time the picture is shown) */ },
  present(glow, vig) {
    if (this.gl) {
      const gl = this.gl, P = (glow && this.prog("glow")) || this.prog("plain"), u = P.u, w = this.w, h = this.h;
      if (this.cur !== P) { gl.useProgram(P.p); this.cur = P; P.set = false; }
      if (!this.mine) {                               // (a UI was drawn here since: put back what it changed)
        gl.bindBuffer(gl.ARRAY_BUFFER, this.quad); gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 8, 0);
        gl.disableVertexAttribArray(1); gl.disableVertexAttribArray(2);
        gl.disable(gl.BLEND); gl.disable(gl.DEPTH_TEST); gl.disable(gl.CULL_FACE); gl.viewport(0, 0, this.cw, this.ch);
        gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, this.tex); this.mine = true;
      }
      gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, this.u8);
      const sx = this.crisp ? Math.max(1, this.cw / w) : 1, sy = this.crisp ? Math.max(1, this.ch / h) : 1;
      if (!P.set || P.w !== w || P.h !== h || P.sx !== sx || P.sy !== sy) {
        P.set = true; P.w = w; P.h = h; P.sx = sx; P.sy = sy;
        gl.uniform4f(u.uSize, w, h, 1 / w, 1 / h); gl.uniform4f(u.uSharp, sx, sy, 0.5 - 0.5 / sx, 0.5 - 0.5 / sy);
      }
      if (u.uGlow) gl.uniform1f(u.uGlow, glow || 0);
      gl.uniform1f(u.uVig, vig == null ? 0.35 : vig);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    } else if (this.cw === this.w && this.ch === this.h) this.ctx.putImageData(this.img, 0, 0);
    else { this.tctx.putImageData(this.img, 0, 0); this.ctx.imageSmoothingEnabled = !this.crisp; this.ctx.drawImage(this.tmp, 0, 0, this.cw, this.ch); }
  },
  // what's written over the picture (a UI's list, in the canvas's own pixels), after present()
  show(ui) { if (this.gl) { this.mine = false; ui.show(this.g3); } else ui.show(null, this.ctx); }
};
// the rungs for a software-drawn game: the picture's height (16:9), frames a second, the WebGL glow (where there's a
// GPU). Every rung holds 60 but the lowest two: pixels are given up before frames, in small steps (the picture needn't
// go into the screen a whole number of times: see Screen), and when the smallest runs late, the frames.
LADDER.ray = [
  { h: 108, fps: 30, glow: 0 }, { h: 135, fps: 30, glow: 0 },
  { h: 108, fps: 60, glow: 0 }, { h: 120, fps: 60, glow: 0 }, { h: 135, fps: 60, glow: 0 }, { h: 150, fps: 60, glow: 0 }, { h: 180, fps: 60, glow: 0 },
  { h: 216, fps: 60, glow: 1 }, { h: 270, fps: 60, glow: 1 }, { h: 360, fps: 60, glow: 1 }
];
// a ladder for a game whose player holds the picture's size (lines), its frame rate (fps), or both (0: not held): the
// size at 30 and at 60, or every size at the rate held; null when nothing is held
function heldRay(lines, fps) {
  if (!lines && !fps) return null;
  const sizes = [], lad = [];
  if (lines) sizes.push(lines); else for (const r of LADDER.ray) if (sizes.indexOf(r.h) < 0) sizes.push(r.h);
  sizes.sort((a, b) => a - b);
  for (const f of fps ? [fps] : [30, 60]) for (const h of sizes) lad.push({ h, fps: f, glow: h >= 216 ? 1 : 0 });
  return lad;
}
// where a software-drawn game starts: from the script test (the CPU does the drawing). show: the canvas's height (the
// picture is shown on it, with what's written over it): 360 lines on a Pi 3, which is all its GPU is asked for
function planRay(p, b) {
  const cpu = b && b.cpu != null ? b.cpu : 100, top = LADDER.ray.length - 1, help = helpersFor(p), eff = help >= 2 ? cpu / 1.7 : cpu;
  let rung = eff < 12 ? 9 : eff < 30 ? 8 : eff < 60 ? 7 : eff < 110 ? 6 : eff < 180 ? 4 : 2, cap = top;   // (helpers: the picture drawn on other cores too)
  if (p.family === "pi3") { rung = Math.min(rung, 4); cap = 6; }
  const fx = p.webgl1 && !p.software;
  return { mode: "ray", rung, top: Math.min(cap, rung + 2), fx, helpers: help, show: !fx || p.family === "pi3" ? 360 : p.family === "pi4" ? 540 : 1080,
    why: "the processor draws it (script " + cpu + " ms" + (help ? ", " + help + " helpers on other cores" : "") + ")" + (fx ? "; the GPU adds the glow" : "") };
}

window.Low3D = { probe, family, NAMES, bench, plan, rows, line, LADDER, Governor, GL, Mesh, Flat, bake, M4, px, hexRGB,
  U, Kit, Path, Chunks, Land, Trail, Particles, camera, chase, orbit, viewOf, begin, Input, Menu, Synth, game,
  Palette, Tex, RayMap, Ray, Marks, Screen, planRay, heldRay, helpersFor, wholeSteps, ladderSig, UI, Letters, GLYPHS, SPECIAL, wholeSize, version: 4 };
})();
