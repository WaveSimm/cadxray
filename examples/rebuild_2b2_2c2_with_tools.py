"""2B2·2C2(배럴 + 더브테일 홈 + 시트 립 + 구멍) 공통 빌더. execute_code에서 exec."""
import FreeCAD
from CadXray.handlers import reload_handlers
reload_handlers()
from CadXray.handlers import rebuild, shape_features

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


def jaw_barrel(doc, name, X_BACK, thickness, RB, RG, gz_marks, RS, RL, lz_marks, band2_z=67.0):
    """2B2형: 띠 3 + 배럴 더브테일 홈(+귀 복원) + 시트 립 쐐기 2(+앞 귀 복원) + 구멍·핀·카운터보어·챔퍼."""
    S = {"of": name, "doc": SRC}
    (A1,) = arc_centers(name, 55.0, RB)
    seats = arc_centers(name, 55.0, RS)
    gz0, gz0t, gz1t, gz1 = [zat(name, z) for z in gz_marks]
    lz0, lz0t, lz1t, lz1 = [zat(name, z) for z in lz_marks]
    hs = holes(name)
    main = next(h for h in hs if abs(h["diameter"] - 3.4) < 0.01)
    pins = [h for h in hs if abs(h["diameter"] - 2.2) < 0.01]
    cb = main.get("counterbore") or {}
    X_FRONT = X_BACK + thickness
    feats = [
        {"op": "pad", "name": "PadBand1", "plane": "XY", "position": Z0, "profile": {"section": dict(S, position=55.0)}, "length": lz0t - Z0},
        {"op": "pad", "name": "PadMid", "plane": "XY", "position": lz0, "profile": {"section": dict(S, position=HZ)}, "length": lz1 - lz0},
        {"op": "pad", "name": "PadBand2", "plane": "XY", "position": lz1t, "profile": {"section": dict(S, position=band2_z)}, "length": TOP - lz1t},
        {"op": "groove", "name": "GrooveBarrel", "plane": "XZ", "position": A1[1], "axis": {"x": A1[0]}, "angle": 360.0,
         "profile": {"polygon": [[A1[0] - RG, gz0], [A1[0] - RB, gz0t], [A1[0] - RB, gz1t], [A1[0] - RG, gz1]]}},
        {"op": "pad", "name": "PadEars", "plane": "XY", "position": gz0, "length": gz1 - gz0,
         "profile": {"section": dict(S, position=HZ, exclude=[{"center": [A1[0], A1[1]], "radius": RG}])}},
    ]
    for k, sc in enumerate(seats, 1):
        feats.append({"op": "groove", "name": f"GrooveLip{k}", "plane": "XZ", "position": sc[1], "axis": {"x": sc[0]}, "angle": 360.0,
                      "profile": {"polygons": [[[sc[0] - RL, lz0], [sc[0] - RS, lz0t], [sc[0] - RS, lz0]],
                                               [[sc[0] - RL, lz1], [sc[0] - RS, lz1t], [sc[0] - RS, lz1]]]}})
    feats += [
        {"op": "pad", "name": "PadSeatEars", "plane": "XY", "position": lz0, "length": lz1 - lz0,
         "profile": {"section": dict(S, position=HZ, clip={"min": [X_FRONT, None]})}},
        {"op": "pocket", "name": "PocketHole", "plane": "YZ", "position": X_BACK, "through": True, "reversed": True,
         "profile": {"circles": [{"center": [main["center"][1], HZ], "diameter": 3.4, "expr": "Params.hole_d", "name": "hole_d"}]}},
    ]
    if pins:
        feats.append({"op": "pocket", "name": "PocketPins", "plane": "YZ", "position": X_BACK, "reversed": True, "length": pins[0]["depth"],
                      "profile": {"circles": [{"center": [p["center"][1], HZ], "diameter": 2.2, "expr": "Params.pin_d", "name": f"pin_d{i}"} for i, p in enumerate(pins)]}})
    if cb:
        feats.append({"op": "pocket", "name": "PocketCbore", "plane": "YZ", "position": X_FRONT, "length": cb["depth"],
                      "profile": {"circles": [{"center": [main["center"][1], HZ], "diameter": cb["diameter"], "expr": "Params.cbore_d", "name": "cbore_d"}]}})
    feats.append({"op": "chamfer", "name": "ChamferHoles", "size": 0.5,
                  "edges": {"curve": "Circle", "radius_max": 2.0, "center": [X_BACK, None, None], "center_tol": 1e-3}})
    params = {"hole_d": 3.4, "pin_d": 2.2, "cbore_d": cb.get("diameter", 5.6), "barrel_r": RB, "groove_r": RG, "seat_r": RS, "lip_r": RL}
    return run(doc, name, params, feats)


results["2B2"] = jaw_barrel("jaw_2B2", "Part__Feature004", 20.343193, 12.0, 35.0, 33.620391, (57.391, 58.199, 65.16, 65.968), 17.75, 16.12127, (57.968, 58.923, 64.436, 65.391))
results["2C2"] = jaw_barrel("jaw_2C2", "Part__Feature003", 34.843193, 6.25, 17.5, 15.87546, (57.68, 58.632, 64.727, 65.68), 9.0, 7.35, (57.68, 58.632, 64.727, 65.68))
_result = results
