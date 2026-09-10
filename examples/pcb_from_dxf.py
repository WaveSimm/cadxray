"""PCB 2D DXF(외곽 OUTLINE 레이어 + 구멍 원) → 3D 보드. FreeCAD 안에서 exec.

DXF는 FreeCAD importDXF로 열지 않는다 — 실크·치수 폴리라인 수백 개가 Draft 객체가 되어 2분 넘게 걸린다(MYB-6ULX 실측).
대신 stdlib로 DXF를 직접 읽어 OUTLINE 폴리라인(꼭짓점 + bulge → 모서리 호)과 CIRCLE(반지름·중심)만 뽑고,
build_features의 elements(선분·호)와 circles로 넘긴다. bulge 0.4142 = tan(90°/4) → 90° 모서리 호.
구멍은 반지름 0.5 mm 이상만(실크 점·비아 제외), Ø3.3은 장착 구멍(Params.mount_d)으로 따로.
"""
import json
import math
import os

DXF_DIR = r"E:\claudereecadMCP"
FILES = {"MYB": "MYB-6ULX_2D.dxf", "MYS": "MYS-6ULX_2D.dxf"}


def parse_dxf(path):
    """ENTITIES 구간에서 폴리라인(레이어, 닫힘, [(x, y, bulge)])과 원(레이어, x, y, r)."""
    lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    pairs = [(lines[i].strip(), lines[i + 1].strip()) for i in range(0, len(lines) - 1, 2)]
    start = next(i for i, (c, v) in enumerate(pairs) if c == "2" and v == "ENTITIES")
    ents, cur = [], None
    for c, v in pairs[start:]:
        if c == "0":
            if v == "ENDSEC":
                break
            cur = {"type": v}
            ents.append(cur)
        elif cur is not None:
            cur.setdefault(c, []).append(v)
    polys, i = [], 0
    while i < len(ents):
        e = ents[i]
        if e["type"] == "POLYLINE":
            verts, j = [], i + 1
            while j < len(ents) and ents[j]["type"] == "VERTEX":
                v = ents[j]
                verts.append((float(v["10"][0]), float(v["20"][0]), float(v.get("42", ["0"])[0])))
                j += 1
            polys.append((e.get("8", ["?"])[0], int(e.get("70", ["0"])[0]) & 1, verts))
            i = j
        else:
            i += 1
    circles = [(e.get("8", ["?"])[0], float(e["10"][0]), float(e["20"][0]), float(e["40"][0])) for e in ents if e["type"] == "CIRCLE"]
    return polys, circles


def outline_elements(verts):
    """bulge 폴리라인 → build_features 요소. bulge b = tan(θ/4): 두 점 사이 호, b>0 반시계."""
    els = []
    n = len(verts)
    for k in range(n):
        x0, y0, b = verts[k]
        x1, y1, _ = verts[(k + 1) % n]
        if abs(b) < 1e-9:
            els.append({"type": "line", "start": [x0, y0], "end": [x1, y1]})
            continue
        theta = 4.0 * math.atan(b)
        chord = math.hypot(x1 - x0, y1 - y0)
        r = chord / (2.0 * math.sin(abs(theta) / 2.0))
        mx, my = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        d = math.sqrt(max(r * r - (chord / 2.0) ** 2, 0.0))
        nx, ny = -(y1 - y0) / chord, (x1 - x0) / chord          # 진행 방향의 왼쪽 법선
        sgn = 1.0 if b > 0 else -1.0
        cx, cy = mx + sgn * nx * d * (1 if abs(theta) <= math.pi else -1), my + sgn * ny * d * (1 if abs(theta) <= math.pi else -1)
        els.append({"type": "arc", "center": [cx, cy], "radius": r, "start": [x0, y0], "end": [x1, y1], "ccw": b > 0})
    return els


HOLES, OUTLINES = {}, {}
for key, fname in FILES.items():
    polys, circles = parse_dxf(os.path.join(DXF_DIR, fname))
    outline = next(v for layer, closed, v in polys if layer == "OUTLINE")
    OUTLINES[key] = outline_elements(outline)
    holes, uniq = [{"center": [round(x, 4), round(y, 4)], "diameter": round(2 * r, 3)} for _, x, y, r in circles if r >= 0.5], []
    for h in holes:
        if not any(abs(h["center"][0] - u["center"][0]) < 1e-3 and abs(h["center"][1] - u["center"][1]) < 1e-3 for u in uniq):
            uniq.append(h)
    HOLES[key] = {"holes": uniq}

import FreeCAD
from CadXray.handlers import rebuild

W, H, R, T = 70.0, 55.0, 1.27, 1.6    # 파라미터 시트용 표기값 (외곽 자체는 DXF에서 읽은 요소를 쓴다)
results = {}
for key, label in (("MYB", "MYB-6ULX"), ("MYS", "MYS-6ULX")):
    doc = "pcb_" + key
    if doc in FreeCAD.listDocuments():
        FreeCAD.closeDocument(doc)
    FreeCAD.newDocument(doc)
    holes = HOLES[key]["holes"]
    mount = [h for h in holes if abs(h["diameter"] - 3.3) < 0.01]
    pins = [h for h in holes if abs(h["diameter"] - 3.3) >= 0.01]
    feats = [
        {"op": "pad", "name": "PadBoard", "plane": "XY", "position": 0.0, "length": "Params.thickness", "profile": {"elements": OUTLINES[key]}},
        {"op": "pocket", "name": "PocketMount", "plane": "XY", "position": T, "through": True,
         "profile": {"circles": [{"center": h["center"], "diameter": h["diameter"], "expr": "Params.mount_d", "name": f"mount_d{i}"} for i, h in enumerate(mount)]}},
        {"op": "pocket", "name": "PocketPins", "plane": "XY", "position": T, "through": True,
         "profile": {"circles": [{"center": h["center"], "diameter": h["diameter"]} for h in pins]}},
    ]
    r = rebuild.build_features(body=label.replace("-", "_"), doc=doc, params={"thickness": T, "mount_d": 3.3, "width": W, "height": H, "corner_r": R}, features=feats)
    body = FreeCAD.getDocument(doc).getObject(label.replace("-", "_"))
    body.Label = label
    bb = body.Shape.BoundBox
    results[key] = {"ok": r["ok"], "stopped_at": r["data"].get("stopped_at") if r["ok"] else r.get("error"),
                    "created": [(c["name"], c.get("dof"), c["status"][:50], c.get("volume_after"), c.get("elements")) for c in r["data"]["created"]] if r["ok"] else None,
                    "mount": len(mount), "pins": len(pins), "faces": len(body.Shape.Faces), "valid": body.Shape.isValid(),
                    "bbox": [round(v, 3) for v in (bb.XMin, bb.XMax, bb.YMin, bb.YMax, bb.ZMin, bb.ZMax)]}
_result = results
