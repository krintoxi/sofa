#!/usr/bin/env python3
"""Models made elsewhere (glTF, in flat colours) as data for a Low3D page: no Blender, nothing but Python.

    python3 tools/low3d-models.py ART_DIR LIST.json OUT.js

ART_DIR is where the models are. LIST.json says which to take, and as what:
    {"spider": {"src": "chars/cc0/wyrd_spider.gltf", "tris": 420, "origin": "ground"}, ...}
  tris    the most triangles to keep (fewer are made by collapsing the edges that change the shape least:
          Garland and Heckbert's quadric error, with the edges between colours and open edges held)
  origin  "ground": centred on x and z, standing on y = 0 (props, creatures); "keep": as made (weapons: the grip)

OUT.js holds one line a model: name, colours (r, g, b, glow 0..127), the box it fits in, and its vertices and
triangles packed as bytes (base64): positions as 0..255 across the box, then each triangle's three corners
(uint16) and its colour's number. Only the standard library is used.
"""
import base64, heapq, json, math, os, struct, sys


# ---------------------------------------------------------------- reading glTF (separate .bin, as the scripts write it)
COMP = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def accessor(g, bins, i):
    a = g["accessors"][i]
    bv = g["bufferViews"][a["bufferView"]]
    fmt, size = COMP[a["componentType"]]
    n, k = a["count"], NCOMP[a["type"]]
    stride = bv.get("byteStride") or size * k
    data = bins[bv["buffer"]]
    off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    out = []
    for j in range(n):
        vals = struct.unpack_from("<" + fmt * k, data, off + j * stride)
        out.append(vals if k > 1 else vals[0])
    return out


def mat_mul(a, b):
    return [sum(a[r + 4 * k] * b[k + 4 * c] for k in range(4)) for c in range(4) for r in range(4)]


def trs(node):
    if "matrix" in node:
        return list(node["matrix"])
    t = node.get("translation", [0, 0, 0]); r = node.get("rotation", [0, 0, 0, 1]); s = node.get("scale", [1, 1, 1])
    x, y, z, w = r
    R = [1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w), 0,
         2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w), 0,
         2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y), 0,
         0, 0, 0, 1]
    S = [s[0], 0, 0, 0, 0, s[1], 0, 0, 0, 0, s[2], 0, 0, 0, 0, 1]
    T = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, t[0], t[1], t[2], 1]
    return mat_mul(T, mat_mul(R, S))


def colour_of(g, mi):
    """A material's colour (sRGB bytes) and whether it lights itself."""
    if mi is None:
        return (200, 200, 200, 0)
    m = g["materials"][mi]
    f = m.get("pbrMetallicRoughness", {}).get("baseColorFactor", [0.8, 0.8, 0.8, 1])
    to8 = lambda v: max(0, min(255, round((v ** (1 / 2.2)) * 255)))     # (glTF's factors are linear)
    e = m.get("emissiveFactor", [0, 0, 0])
    glow = 0
    if max(e) > 0.05:                                                   # a lit material shows its light's colour
        k = max(e)
        f = [min(1.0, e[0] / k), min(1.0, e[1] / k), min(1.0, e[2] / k)]
        glow = 127
    return (to8(f[0]), to8(f[1]), to8(f[2]), glow)


def load(path):
    g = json.load(open(path))
    base = os.path.dirname(path)
    bins = [open(os.path.join(base, b["uri"]), "rb").read() for b in g["buffers"]]
    verts, faces, cols = [], [], []
    colix = {}

    def walk(ni, parent):
        node = g["nodes"][ni]
        M = mat_mul(parent, trs(node))
        if "mesh" in node:
            for p in g["meshes"][node["mesh"]]["primitives"]:
                if p.get("mode", 4) != 4:
                    continue
                pos = accessor(g, bins, p["attributes"]["POSITION"])
                idx = accessor(g, bins, p["indices"]) if "indices" in p else list(range(len(pos)))
                c = colour_of(g, p.get("material"))
                if c not in colix:
                    colix[c] = len(cols); cols.append(c)
                ci = colix[c]
                o = len(verts)
                for (x, y, z) in pos:
                    verts.append([M[0] * x + M[4] * y + M[8] * z + M[12], M[1] * x + M[5] * y + M[9] * z + M[13], M[2] * x + M[6] * y + M[10] * z + M[14]])
                det = (M[0] * (M[5] * M[10] - M[9] * M[6]) - M[4] * (M[1] * M[10] - M[9] * M[2]) + M[8] * (M[1] * M[6] - M[5] * M[2]))
                for t in range(0, len(idx) - 2, 3):
                    a, b, cc = idx[t] + o, idx[t + 1] + o, idx[t + 2] + o
                    faces.append([a, cc, b, ci] if det < 0 else [a, b, cc, ci])
        for ch in node.get("children", []):
            walk(ch, M)

    I = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    for ni in g["scenes"][g.get("scene", 0)]["nodes"]:
        walk(ni, I)
    return verts, faces, cols


# ---------------------------------------------------------------- one vertex where several share a place
def weld(verts, faces, eps=1e-5):
    key, out, remap = {}, [], []
    for v in verts:
        k = (round(v[0] / eps), round(v[1] / eps), round(v[2] / eps))
        if k not in key:
            key[k] = len(out); out.append(list(v))
        remap.append(key[k])
    nf = []
    for a, b, c, ci in faces:
        a, b, c = remap[a], remap[b], remap[c]
        if a != b and b != c and a != c:
            nf.append([a, b, c, ci])
    return out, nf


# ---------------------------------------------------------------- fewer triangles: quadric error edge collapse
def sub(a, b): return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
def cross(a, b): return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
def dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def norm(a):
    l = math.sqrt(dot(a, a))
    return [a[0] / l, a[1] / l, a[2] / l] if l > 1e-12 else None


def plane_q(n, p, w=1.0):
    a, b, c = n; d = -dot(n, p)
    return [w * x for x in (a * a, a * b, a * c, a * d, b * b, b * c, b * d, c * c, c * d, d * d)]


def q_add(q, r):
    for i in range(10):
        q[i] += r[i]


def q_err(q, v):
    x, y, z = v
    return (q[0] * x * x + 2 * q[1] * x * y + 2 * q[2] * x * z + 2 * q[3] * x + q[4] * y * y + 2 * q[5] * y * z
            + 2 * q[6] * y + q[7] * z * z + 2 * q[8] * z + q[9])


def simplify(verts, faces, target):
    if len(faces) <= target:
        return verts, faces
    V = [list(v) for v in verts]
    F = [list(f) for f in faces]
    alive = [True] * len(F)
    vf = [set() for _ in V]
    for i, f in enumerate(F):
        for k in range(3):
            vf[f[k]].add(i)
    Q = [[0.0] * 10 for _ in V]
    for f in F:
        n = norm(cross(sub(V[f[1]], V[f[0]]), sub(V[f[2]], V[f[0]])))
        if not n:
            continue
        area = 0.5 * math.sqrt(dot(cross(sub(V[f[1]], V[f[0]]), sub(V[f[2]], V[f[0]])), cross(sub(V[f[1]], V[f[0]]), sub(V[f[2]], V[f[0]]))))
        q = plane_q(n, V[f[0]], max(area, 1e-6))
        for k in range(3):
            q_add(Q[f[k]], q)
    # edges held: open ones, and those between two colours (a plane through the edge, upright to its face, weighted)
    edge_faces = {}
    for i, f in enumerate(F):
        for k in range(3):
            a, b = f[k], f[(k + 1) % 3]
            edge_faces.setdefault((min(a, b), max(a, b)), []).append(i)
    for (a, b), fs in edge_faces.items():
        if len(fs) == 1 or len(set(F[i][3] for i in fs)) > 1:
            for fi in fs[:1]:
                f = F[fi]
                n = norm(cross(sub(V[f[1]], V[f[0]]), sub(V[f[2]], V[f[0]])))
                e = sub(V[b], V[a])
                if not n:
                    continue
                pn = norm(cross(e, n))
                if not pn:
                    continue
                w = 1000.0 * dot(e, e)
                q = plane_q(pn, V[a], w)
                q_add(Q[a], q); q_add(Q[b], q)
    ver = [0] * len(V)

    def best(a, b):
        q = [Q[a][i] + Q[b][i] for i in range(10)]
        m = [(V[a][i] + V[b][i]) / 2 for i in range(3)]
        cands = [V[a], V[b], m]
        c = min(cands, key=lambda p: q_err(q, p))
        return q_err(q, c), c

    heap = []
    for (a, b) in edge_faces:
        cost, p = best(a, b)
        heapq.heappush(heap, (cost, a, b, ver[a], ver[b]))
    count = len(F)
    while count > target and heap:
        cost, a, b, va, vb = heapq.heappop(heap)
        if ver[a] != va or ver[b] != vb or a == b:
            continue
        if not any(alive[i] for i in vf[a]) or not any(alive[i] for i in vf[b]):
            continue
        _, p = best(a, b)
        # would any face turn over?
        bad = False
        for fi in (vf[a] | vf[b]):
            if not alive[fi]:
                continue
            f = F[fi]
            if a in f[:3] and b in f[:3]:
                continue
            old = [V[f[0]], V[f[1]], V[f[2]]]
            new = [p if f[k] in (a, b) else V[f[k]] for k in range(3)]
            n0 = cross(sub(old[1], old[0]), sub(old[2], old[0]))
            n1 = cross(sub(new[1], new[0]), sub(new[2], new[0]))
            if dot(n0, n1) <= 0.2 * math.sqrt(dot(n0, n0) * dot(n1, n1)) + 1e-18:
                bad = True; break
        if bad:
            continue
        V[a] = p
        q_add(Q[a], Q[b])
        for fi in list(vf[b]):
            if not alive[fi]:
                continue
            f = F[fi]
            if a in f[:3]:
                alive[fi] = False; count -= 1
                for k in range(3):
                    vf[f[k]].discard(fi)
            else:
                for k in range(3):
                    if f[k] == b:
                        f[k] = a
                vf[a].add(fi)
        vf[b] = set()
        ver[a] += 1; ver[b] += 1
        nb = set()
        for fi in vf[a]:
            if alive[fi]:
                nb.update(F[fi][:3])
        nb.discard(a)
        for c in nb:
            cost, _ = best(a, c)
            heapq.heappush(heap, (cost, a, c, ver[a], ver[c]))
    used, out_v, out_f = {}, [], []
    for i, f in enumerate(F):
        if not alive[i]:
            continue
        idx = []
        for k in range(3):
            if f[k] not in used:
                used[f[k]] = len(out_v); out_v.append(V[f[k]])
            idx.append(used[f[k]])
        if len(set(idx)) == 3:
            out_f.append(idx + [f[3]])
    return out_v, out_f


# ---------------------------------------------------------------- packing
def pack(name, verts, faces, cols, origin):
    xs = [v[0] for v in verts]; ys = [v[1] for v in verts]; zs = [v[2] for v in verts]
    if origin == "ground":
        cx, cz, y0 = (min(xs) + max(xs)) / 2, (min(zs) + max(zs)) / 2, min(ys)
        verts = [[v[0] - cx, v[1] - y0, v[2] - cz] for v in verts]
        xs = [v[0] for v in verts]; ys = [v[1] for v in verts]; zs = [v[2] for v in verts]
    lo = [min(xs), min(ys), min(zs)]
    span = [max(max(xs) - lo[0], 1e-6), max(max(ys) - lo[1], 1e-6), max(max(zs) - lo[2], 1e-6)]
    used = sorted(set(f[3] for f in faces))
    cmap = {c: i for i, c in enumerate(used)}
    b = bytearray(struct.pack("<HH", len(verts), len(faces)))
    for v in verts:
        b += bytes(max(0, min(255, round((v[k] - lo[k]) / span[k] * 255))) for k in range(3))
    for f in faces:
        b += struct.pack("<HHHB", f[0], f[1], f[2], cmap[f[3]])
    return {"n": name, "c": [list(cols[c]) for c in used], "box": [round(x, 4) for x in lo + span],
            "d": base64.b64encode(bytes(b)).decode()}


def main():
    art, lst, out = sys.argv[1], sys.argv[2], sys.argv[3]
    want = json.load(open(lst))
    rows, report = [], []
    for name, o in want.items():
        v, f, cols = load(os.path.join(art, o["src"]))
        v, f = weld(v, f)
        before = len(f)
        v, f = simplify(v, f, o.get("tris", 10 ** 9))
        rows.append(pack(name, v, f, cols, o.get("origin", "ground")))
        report.append(f"{name:14s} {before:6d} -> {len(f):5d} triangles")
    with open(out, "w") as fh:
        fh.write("// models packed for Low3D by tools/low3d-models.py: name, colours, box, data (see that file)\n")
        fh.write("const MODELS = {\n" + ",\n".join(json.dumps(r["n"]) + ":" + json.dumps({k: v for k, v in r.items() if k != "n"}, separators=(",", ":")) for r in rows) + "\n};\n")
    print("\n".join(report))
    print(sum(len(r["d"]) for r in rows), "bytes of base64")


if __name__ == "__main__":
    main()
