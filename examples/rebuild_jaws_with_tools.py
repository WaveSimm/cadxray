"""조 계열 6종 + 원기둥 2종을 M7 툴로 재구성. execute_code에서 exec."""
import FreeCAD
from freecad.cadxray.handlers import reload_handlers
reload_handlers()
from freecad.cadxray.handlers import rebuild, shape_features

SRC = "Unnamed"
Z0, TOP, HZ = 53.679659, 69.679659, 61.679659
results = {}


def shape(name):
    return FreeCAD.getDocument(SRC).getObject(name).Shape


def zat(name, approx, tol=0.003):
    zs = sorted({round(v.Point.z, 6) for v in shape(name).Vertexes if abs(v.Point.z - approx) < tol})
    if not zs:
        raise RuntimeError(f"{name}: z≈{approx} 정점 없음")
    return zs[0]


def sec(name, axis, pos, fill=True, **kw):
    r = rebuild.section_profile(name=name, doc=SRC, axis=axis, position=pos, fill_holes=fill, **kw)
    if not r["ok"]:
        raise RuntimeError(r["error"])
    return r["data"]["wires"]


def arc_centers(name, z, radius, tol=1e-3):
    out = []
    for w in sec(name, "Z", z):
        for e in w["elements"]:
            if e["type"] == "arc" and abs(e["radius"] - radius) < tol:
                c = tuple(e["center"])
                if not any(abs(c[0] - o[0]) < 1e-3 and abs(c[1] - o[1]) < 1e-3 for o in out):
                    out.append(c)
    return out


def hexes(name, axis, pos):
    return [[e["start"] for e in w["elements"]] for w in sec(name, axis, pos, fill=False) if not w["outer"] and w["elements_total"] == 6]


def center_of(poly):
    return [sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly)]


def holes(name):
    return [x for x in shape_features.find_holes(name=name, doc=SRC)["data"]["holes"] if x["kind"] == "hole"]


def run(doc, src, params, feats, stop=True):
    if doc in FreeCAD.listDocuments():
        FreeCAD.closeDocument(doc)
    FreeCAD.newDocument(doc)
    r = rebuild.build_features(body="Body", doc=doc, params=params, features=feats, stop_on_error=stop)
    out = {"ok": r["ok"], "warnings": r.get("warnings", [])}
    if not r["ok"]:
        out["error"] = r["error"]
        return out
    out["created"] = [(c["name"], c.get("dof"), c["status"][:50], c.get("volume_after")) for c in r["data"]["created"]]
    out["stopped_at"] = r["data"]["stopped_at"]
    if r["data"]["stopped_at"] is None:
        c = rebuild.compare_shapes(a=src, doc=SRC, b="Body", doc_b=doc)
        cd = c["data"]
        out["compare"] = {k: cd.get(k) for k in ("volume_diff", "volume_diff_pct", "diff_pct", "verdict", "method")}
        out["missing"] = [(p["volume"], [round(v, 2) for v in p["bbox"]["min"]], [round(v, 2) for v in p["bbox"]["max"]]) for p in cd["missing_in_b"][:4]]
        out["extra"] = [(p["volume"], [round(v, 2) for v in p["bbox"]["min"]], [round(v, 2) for v in p["bbox"]["max"]]) for p in cd["extra_in_b"][:4]]
    return out


def dovetail(ax, r_groove, r_band, z0, z0t, z1t, z1, side):
    """회전 홈 프로파일: 축에서 side(+1 동/−1 서) 쪽, 띠 반지름과 홈 반지름 사이 사다리꼴."""
    return [[ax + side * r_groove, z0], [ax + side * r_band, z0t], [ax + side * r_band, z1t], [ax + side * r_groove, z1]]


def lip_wedges(ax, r_lip, r_seat, lz0, lz0t, lz1t, lz1, side):
    return [[[ax + side * r_lip, lz0], [ax + side * r_seat, lz0t], [ax + side * r_seat, lz0]],
            [[ax + side * r_lip, lz1], [ax + side * r_seat, lz1t], [ax + side * r_seat, lz1]]]


# ---------------------------------------------------------------- 2C1 (Part 6): 얇은 호 판, 앞면 더브테일 홈, 앞에서 육각 자리, 뒤에서 구멍·핀
def jaw_small(doc, name, X_BACK, R_BAND, R_GROOVE, z_marks, hex_x, hex_depth_from_back, pin_dy, pin_depth):
    S = {"of": name, "doc": SRC}
    (A,) = arc_centers(name, 55.0, R_BAND)
    z0, z0t, z1t, z1 = [zat(name, z) for z in z_marks]
    hx = hexes(name, "X", hex_x)
    hc = center_of(hx[0])
    feats = [
        {"op": "pad", "name": "PadFull", "plane": "XY", "position": Z0, "profile": {"section": dict(S, position=55.0)}, "length": TOP - Z0},
        {"op": "groove", "name": "GrooveDove", "plane": "XZ", "position": A[1], "axis": {"x": A[0]}, "angle": 360.0,
         "profile": {"polygon": dovetail(A[0], R_GROOVE, R_BAND, z0, z0t, z1t, z1, +1)}},
        # 육각 너트 자리: 뒤판에서 hex_depth 뒤 평면부터 앞(+X) 끝까지
        {"op": "pocket", "name": "PocketHex", "plane": "YZ", "position": X_BACK + hex_depth_from_back, "reversed": True, "through": True, "profile": {"polygon": hx[0]}},
        {"op": "pocket", "name": "PocketHole", "plane": "YZ", "position": X_BACK, "reversed": True, "through": True,
         "profile": {"circles": [{"center": [hc[0], HZ], "diameter": 3.4, "expr": "Params.hole_d", "name": "hole_d"}]}},
        {"op": "pocket", "name": "PocketPins", "plane": "YZ", "position": X_BACK, "reversed": True, "length": pin_depth,
         "profile": {"circles": [{"center": [hc[0] - pin_dy, HZ], "diameter": 2.2, "expr": "Params.pin_d", "name": "pin_d"},
                                 {"center": [hc[0] + pin_dy, HZ], "diameter": 2.2, "expr": "Params.pin_d", "name": "pin_d2"}]}},
        {"op": "chamfer", "name": "ChamferBack", "size": 0.5, "edges": {"curve": "Circle", "radius_max": 2.0, "center": [X_BACK, None, None], "center_tol": 1e-3}},
    ]
    return run(doc, name, {"hole_d": 3.4, "pin_d": 2.2, "band_r": R_BAND, "groove_r": R_GROOVE}, feats)


results["2C1"] = jaw_small("jaw_2C1", "Part__Feature012", 123.735118, 17.5, 15.87546, (57.68, 58.632, 64.727, 65.68), 128.0, 3.75, 7.0, 3.0)
results["2B1"] = jaw_small("jaw_2B1", "Part__Feature037", 138.235118, 35.0, 33.620391, (57.391, 58.199, 65.16, 65.968), 150.0, 8.0, 14.250464, 5.0)


# ---------------------------------------------------------------- 2A1: R70 호 판, 바깥 더브테일 홈, 앞에서 육각 채널 2, 뒤에서 구멍 2
def build_2a1():
    name = "Part__Feature006"; S = {"of": name, "doc": SRC}
    X_BACK = -10.156807
    (A,) = arc_centers(name, 55.0, 70.0)
    z0, z0t, z1t, z1 = [zat(name, z) for z in (57.391, 58.344, 65.016, 65.968)]
    hx = hexes(name, "X", -30.0)
    feats = [
        {"op": "pad", "name": "PadFull", "plane": "XY", "position": Z0, "profile": {"section": dict(S, position=55.0)}, "length": TOP - Z0},
        {"op": "groove", "name": "GrooveDove", "plane": "XZ", "position": A[1], "axis": {"x": A[0]}, "angle": 360.0,
         "profile": {"polygon": dovetail(A[0], 68.373631, 70.0, z0, z0t, z1t, z1, -1)}},
        {"op": "pocket", "name": "PocketHexChannels", "plane": "YZ", "position": X_BACK - 15.0, "through": True, "profile": {"polygons": hx}},
        {"op": "pocket", "name": "PocketHoles", "plane": "YZ", "position": X_BACK, "through": True,
         "profile": {"circles": [{"center": [center_of(h)[0], HZ], "diameter": 3.4, "expr": "Params.hole_d", "name": f"hole_d{i}"} for i, h in enumerate(hx)]}},
        {"op": "chamfer", "name": "ChamferBack", "size": 0.5, "edges": {"curve": "Circle", "radius_max": 2.0, "center": [X_BACK, None, None], "center_tol": 1e-3}},
    ]
    return run("jaw_2A1", name, {"hole_d": 3.4}, feats)


results["2A1"] = build_2a1()


# ---------------------------------------------------------------- 2A2: 2B2와 같은 문법 (띠 3 + 바깥 홈 + 시트 립 쐐기 2 + 구멍·카운터보어·챔퍼)
def build_2a2():
    name = "Part__Feature043"; S = {"of": name, "doc": SRC}
    X_BACK, X_FRONT = -10.156807, -10.156807 + 25.0
    (A1,) = arc_centers(name, 55.0, 70.0)
    seats = arc_centers(name, 55.0, 35.25)
    gz0, gz0t, gz1t, gz1 = [zat(name, z) for z in (57.391, 58.344, 65.016, 65.968)]
    lz0, lz0t, lz1t, lz1 = [zat(name, z) for z in (57.68, 58.49, 64.869, 65.68)]
    hs = holes(name)
    ys = sorted({round(h["center"][1], 6) for h in hs if abs(h["diameter"] - 3.4) < 0.01})
    feats = [
        {"op": "pad", "name": "PadBand1", "plane": "XY", "position": Z0, "profile": {"section": dict(S, position=55.0)}, "length": lz0t - Z0},
        {"op": "pad", "name": "PadMid", "plane": "XY", "position": lz0, "profile": {"section": dict(S, position=HZ)}, "length": lz1 - lz0},
        {"op": "pad", "name": "PadBand2", "plane": "XY", "position": lz1t, "profile": {"section": dict(S, position=67.5)}, "length": TOP - lz1t},
        {"op": "groove", "name": "GrooveOuter", "plane": "XZ", "position": A1[1], "axis": {"x": A1[0]}, "angle": 360.0,
         "profile": {"polygon": dovetail(A1[0], 68.373631, 70.0, gz0, gz0t, gz1t, gz1, -1)}},
    ]
    # 바깥 홈(360°)이 끝단 돌기(R3.08, |y| > 72)까지 깎으므로 가운데 단면의 끝단만 홈 z 범위로 되살린다
    feats.append({"op": "pad", "name": "PadTipA", "plane": "XY", "position": gz0, "length": gz1 - gz0,
                  "profile": {"section": dict(S, position=HZ, clip={"min": [13.0, 73.0]})}})
    feats.append({"op": "pad", "name": "PadTipB", "plane": "XY", "position": gz0, "length": gz1 - gz0,
                  "profile": {"section": dict(S, position=HZ, clip={"min": [13.0, None], "max": [None, -52.0]})}})
    for k, sc in enumerate(seats, 1):
        feats.append({"op": "groove", "name": f"GrooveLip{k}", "plane": "XZ", "position": sc[1], "axis": {"x": sc[0]}, "angle": 360.0,
                      "profile": {"polygons": lip_wedges(sc[0], 33.866627, 35.25, lz0, lz0t, lz1t, lz1, -1)}})
    feats += [
        {"op": "pocket", "name": "PocketHoles", "plane": "YZ", "position": X_BACK, "reversed": True, "through": True,
         "profile": {"circles": [{"center": [y, HZ], "diameter": 3.4, "expr": "Params.hole_d", "name": f"hole_d{i}"} for i, y in enumerate(ys)]}},
        {"op": "pocket", "name": "PocketCbores", "plane": "YZ", "position": X_FRONT, "length": 10.0,
         "profile": {"circles": [{"center": [y, HZ], "diameter": 5.6, "expr": "Params.cbore_d", "name": f"cbore_d{i}"} for i, y in enumerate(ys)]}},
        {"op": "chamfer", "name": "ChamferBack", "size": 0.5, "edges": {"curve": "Circle", "radius_max": 2.0, "center": [X_BACK, None, None], "center_tol": 1e-3}},
    ]
    return run("jaw_2A2", name, {"hole_d": 3.4, "cbore_d": 5.6}, feats)


results["2A2"] = build_2a2()


# ---------------------------------------------------------------- 2holder / Part 1: 오목 베이 + 립 + 카운터보어 5개
def build_holder(doc, name, side, cbore_depth):
    S = {"of": name, "doc": SRC}
    (A,) = arc_centers(name, 55.0, 70.25)
    lz0, lz0t, lz1t, lz1 = [zat(name, z) for z in (57.68, 58.634, 64.725, 65.68)]
    hs = [h for h in holes(name) if abs(h["diameter"] - 3.4) < 0.01]
    feats = [
        {"op": "pad", "name": "PadBand1", "plane": "XY", "position": Z0, "profile": {"section": dict(S, position=55.0)}, "length": lz0t - Z0},
        {"op": "pad", "name": "PadMid", "plane": "XY", "position": lz0, "profile": {"section": dict(S, position=HZ)}, "length": lz1 - lz0},
        {"op": "pad", "name": "PadBand2", "plane": "XY", "position": lz1t, "profile": {"section": dict(S, position=66.2)}, "length": TOP - lz1t},
        {"op": "groove", "name": "GrooveLip", "plane": "XZ", "position": A[1], "axis": {"x": A[0]}, "angle": 360.0,
         "profile": {"polygons": lip_wedges(A[0], 68.619978, 70.25, lz0, lz0t, lz1t, lz1, side)}},
        {"op": "pocket", "name": "PocketHoles", "plane": "XY", "position": TOP, "through": True,
         "profile": {"circles": [{"center": h["center"][:2], "diameter": 3.4, "expr": "Params.hole_d", "name": f"hole_d{i}"} for i, h in enumerate(hs)]}},
        {"op": "pocket", "name": "PocketCbores", "plane": "XY", "position": TOP, "length": cbore_depth,
         "profile": {"circles": [{"center": h["center"][:2], "diameter": 5.6, "expr": "Params.cbore_d", "name": f"cbore_d{i}"} for i, h in enumerate(hs)]}},
    ]
    return run(doc, name, {"hole_d": 3.4, "cbore_d": 5.6, "cbore_depth": cbore_depth}, feats)


results["2holder"] = build_holder("jaw_2holder", "Part__Feature052", -1, 1.5)
results["Part1"] = build_holder("jaw_Part1", "Part__Feature077", +1, 3.0)


# ---------------------------------------------------------------- rod / leadscrew: X 방향 원기둥
def build_rod(doc, name):
    c = rebuild.classify_faces(name=name, doc=SRC)["data"]
    cyl = next(f for f in c["faces"] if f["identity"] == "cylinder")
    bb = shape(name).BoundBox
    feats = [{"op": "pad", "name": "PadRod", "plane": "YZ", "position": bb.XMin, "length": bb.XLength,
              "profile": {"circles": [{"center": [cyl["center"][1], cyl["center"][2]], "diameter": 2 * cyl["radius"], "expr": "Params.rod_d", "name": "rod_d"}]}}]
    return run(doc, name, {"rod_d": 2 * cyl["radius"], "length": bb.XLength}, feats)


results["rod"] = build_rod("rod_tools", "Part__Feature028")
results["leadscrew"] = build_rod("leadscrew_tools", "Part__Feature074")
_result = results
