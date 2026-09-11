"""하우징 3종(end body·middle body·middle cap) 재구성. execute_code에서 exec.

공통 문법: 립(가장 작은 채널) 구간의 YZ 단면을 X로 돌출 → 채널 반지름이 큰 구간만 X축 둘레 회전 절삭
→ 사각 슬롯 → 끝단 63° 베벨 → 발/바닥의 육각 너트 자리 → 구멍.
"""
import FreeCAD
from freecad.cadxray.handlers import reload_handlers
reload_handlers()
from freecad.cadxray.handlers import rebuild, shape_features

SRC = "Unnamed"
results = {}


def sec(name, axis, pos, fill=True, **kw):
    r = rebuild.section_profile(name=name, doc=SRC, axis=axis, position=pos, fill_holes=fill, **kw)
    if not r["ok"]:
        raise RuntimeError(r["error"])
    return r["data"]["wires"]


def hexes(name, axis, pos):
    return [[e["start"] for e in w["elements"]] for w in sec(name, axis, pos, fill=False) if not w["outer"] and w["elements_total"] == 6]


def center_of(poly):
    return [sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly)]


def holes(name, d):
    return [x for x in shape_features.find_holes(name=name, doc=SRC)["data"]["holes"] if x["kind"] == "hole" and abs(x["diameter"] - d) < 0.01]


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
        out["missing"] = [(p["volume"], [round(v, 2) for v in p["bbox"]["min"]], [round(v, 2) for v in p["bbox"]["max"]]) for p in cd["missing_in_b"][:5]]
        out["extra"] = [(p["volume"], [round(v, 2) for v in p["bbox"]["min"]], [round(v, 2) for v in p["bbox"]["max"]]) for p in cd["extra_in_b"][:5]]
    return out


def channel_groove(name, y, z, r, xa, xb):
    """X 방향 채널 구간: XY 평면(z=채널 축 높이)에서 축 y 둘레로 사각형을 360° 회전 절삭."""
    return {"op": "groove", "name": name, "plane": "XY", "position": z, "axis": {"y": y}, "angle": 360.0,
            "profile": {"polygon": [[xa, y], [xb, y], [xb, y + r], [xa, y + r]]}}


def bevels(name, x0, x1, top, drop, run_):
    """양 끝단 윗면 베벨: XZ 평면 삼각형을 Y 방향 관통(midplane)으로 잘라낸다."""
    return {"op": "pocket", "name": name, "plane": "XZ", "position": 10.052724, "through": True, "midplane": True,
            "profile": {"polygons": [[[x1 - run_, top], [x1, top - drop], [x1 + 0.01, top - drop], [x1 + 0.01, top + 1.0], [x1 - run_, top + 1.0]],
                                     [[x0 + run_, top], [x0, top - drop], [x0 - 0.01, top - drop], [x0 - 0.01, top + 1.0], [x0 + run_, top + 1.0]]]}}


AY, YS1, YS2 = 10.052724, -17.947276, 38.052724   # 중앙·측면 채널 y

# ---------------------------------------------------------------- end body
def build_end_body():
    name = "Part__Feature019"; S = {"of": name, "doc": SRC}
    X0, X1 = 230.204512, 286.789155
    Z0, ZM, TOP = 17.679659, 32.679659, 47.679659
    hx = hexes(name, "Z", 25.0)
    screws = holes(name, 3.4)
    screws = [h for h in screws if not any(abs(h["center"][0] - center_of(p)[0]) < 0.5 and abs(h["center"][1] - center_of(p)[1]) < 0.5 for p in hx)]
    feats = [
        # 립 단면(x=X0+1.5)은 베벨 구간이라 윗면이 z=42.68로 낮다 → PadTop(사각형)으로 47.68까지 채우고 Bevels로 다시 깎는다
        {"op": "pad", "name": "PadLip1", "plane": "YZ", "position": X0, "profile": {"section": dict(S, position=X0 + 1.5)}, "length": 3.0},
        {"op": "pad", "name": "PadMain", "plane": "YZ", "position": X0 + 3.0, "profile": {"section": dict(S, position=258.5)}, "length": X1 - X0 - 6.0},
        {"op": "pad", "name": "PadLip2", "plane": "YZ", "position": X1 - 3.0, "profile": {"section": dict(S, position=X1 - 1.5)}, "length": 3.0},
        {"op": "pad", "name": "PadTop", "plane": "XY", "position": TOP - 8.0 + 3.0, "length": 5.0,
         "profile": {"rect": {"center": [(X0 + X1) / 2, 10.052724], "width": X1 - X0, "height": 112.0}}},
        channel_groove("GrooveBig1", AY, ZM, 11.05, X0 + 3.0, X0 + 12.0),
        channel_groove("GrooveBig2", AY, ZM, 11.05, X1 - 12.0, X1 - 3.0),
        {"op": "chamfer", "name": "ChamferBig2", "size": 0.5,
         "edges": {"curve": "Line", "direction": [1, 0, 0], "length": 9.0, "length_tol": 0.05, "bbox": {"min": [X1 - 12.01, None, ZM - 0.01], "max": [X1 - 2.99, None, ZM + 0.01]}}},
        bevels("Bevels", X0, X1, TOP, 8.0, 4.0),
        {"op": "pocket", "name": "PocketHexTraps", "plane": "XY", "position": Z0, "reversed": True, "length": ZM - Z0, "profile": {"polygons": hx}},
        {"op": "pocket", "name": "PocketMount", "plane": "XY", "position": TOP, "through": True,
         "profile": {"circles": [{"center": center_of(p), "diameter": 3.4, "expr": "Params.hole_d", "name": f"mount_d{i}"} for i, p in enumerate(hx)]}},
        {"op": "pocket", "name": "PocketScrews", "plane": "XY", "position": ZM, "reversed": True, "length": 8.6,
         "profile": {"circles": [{"center": h["center"][:2], "diameter": 3.4, "expr": "Params.hole_d", "name": f"screw_d{i}"} for i, h in enumerate(screws)]}},
        {"op": "pocket", "name": "PocketCbores", "plane": "XY", "position": TOP, "length": 6.0,
         "profile": {"circles": [{"center": h["center"][:2], "diameter": 5.6, "expr": "Params.cbore_d", "name": f"cbore_d{i}"} for i, h in enumerate(screws)]}},
    ]
    return run("hs_end_body", name, {"hole_d": 3.4, "cbore_d": 5.6}, feats)


results["end_body"] = build_end_body()


# ---------------------------------------------------------------- middle body
def build_middle_body():
    name = "Part__Feature001"; S = {"of": name, "doc": SRC}
    X0, X1 = 135.789155, 192.789155
    Z0, ZM, TOP = 17.606053, 32.606053, 47.606053
    hx = hexes(name, "Z", 25.0)
    screws = [h for h in holes(name, 3.4) if not any(abs(h["center"][0] - center_of(p)[0]) < 0.5 and abs(h["center"][1] - center_of(p)[1]) < 0.5 for p in hx)]
    feats = [
        {"op": "pad", "name": "PadBlock", "plane": "YZ", "position": X0, "profile": {"section": dict(S, position=136.5)}, "length": X1 - X0},
        {"op": "pad", "name": "PadTop", "plane": "XY", "position": TOP - 8.0 + 2.0 * (136.5 - X0), "length": 8.0 - 2.0 * (136.5 - X0),
         "profile": {"rect": {"center": [(X0 + X1) / 2, 10.052724], "width": X1 - X0, "height": 112.0}}},
        channel_groove("GrooveSide1a", YS1, ZM, 7.55, X0 + 2.0, X0 + 27.0),
        channel_groove("GrooveSide1b", YS1, ZM, 7.55, X0 + 30.0, X0 + 55.0),
        channel_groove("GrooveSide2a", YS2, ZM, 7.55, X0 + 2.0, X0 + 27.0),
        channel_groove("GrooveSide2b", YS2, ZM, 7.55, X0 + 30.0, X0 + 55.0),
        channel_groove("GrooveCenterA", AY, ZM, 5.0, X0 + 17.5, X0 + 24.5),
        channel_groove("GrooveCenterB", AY, ZM, 5.0, X0 + 28.5, X0 + 39.5),
        {"op": "pocket", "name": "PocketSlot", "plane": "XY", "position": ZM, "reversed": True, "length": 6.75,
         "profile": {"rect": {"center": [X0 + 26.5, 10.052724], "width": 4.0, "height": 25.5}}},
        bevels("Bevels", X0, X1, TOP, 8.0, 4.0),
        {"op": "pocket", "name": "PocketHexTraps", "plane": "XY", "position": Z0, "reversed": True, "length": ZM - Z0, "profile": {"polygons": hx}},
        {"op": "pocket", "name": "PocketMount", "plane": "XY", "position": TOP, "through": True,
         "profile": {"circles": [{"center": center_of(p), "diameter": 3.4, "expr": "Params.hole_d", "name": f"mount_d{i}"} for i, p in enumerate(hx)]}},
        {"op": "pocket", "name": "PocketScrews", "plane": "XY", "position": ZM, "reversed": True, "length": 8.6,
         "profile": {"circles": [{"center": h["center"][:2], "diameter": 3.4, "expr": "Params.hole_d", "name": f"screw_d{i}"} for i, h in enumerate(screws)]}},
        {"op": "pocket", "name": "PocketCbores", "plane": "XY", "position": TOP, "length": 6.0,
         "profile": {"circles": [{"center": h["center"][:2], "diameter": 5.6, "expr": "Params.cbore_d", "name": f"cbore_d{i}"} for i, h in enumerate(screws)]}},
    ]
    return run("hs_middle_body", name, {"hole_d": 3.4, "cbore_d": 5.6}, feats)


results["middle_body"] = build_middle_body()


# ---------------------------------------------------------------- middle cap
def build_middle_cap():
    name = "Part__Feature002"; S = {"of": name, "doc": SRC}
    X0, X1 = 135.789155, 192.789155
    Z0, TOP = 18.490072, 32.490072
    hx = hexes(name, "Z", 20.0)
    feats = [
        {"op": "pad", "name": "PadPlate", "plane": "YZ", "position": X0, "profile": {"section": dict(S, position=136.5)}, "length": X1 - X0},
        channel_groove("GrooveSide1a", YS1, TOP, 7.55, X0 + 2.0, X0 + 27.0),
        channel_groove("GrooveSide1b", YS1, TOP, 7.55, X0 + 30.0, X0 + 55.0),
        channel_groove("GrooveSide2a", YS2, TOP, 7.55, X0 + 2.0, X0 + 27.0),
        channel_groove("GrooveSide2b", YS2, TOP, 7.55, X0 + 30.0, X0 + 55.0),
        channel_groove("GrooveCenterA", AY, TOP, 5.0, X0 + 17.5, X0 + 24.5),
        channel_groove("GrooveCenterB", AY, TOP, 5.0, X0 + 28.5, X0 + 39.5),
        {"op": "pocket", "name": "PocketSlot", "plane": "XY", "position": TOP, "length": 6.75,
         "profile": {"rect": {"center": [X0 + 26.5, 10.052724], "width": 4.0, "height": 25.5}}},
        {"op": "pocket", "name": "PocketHexTraps", "plane": "XY", "position": Z0, "reversed": True, "length": 6.0, "profile": {"polygons": hx}},
        {"op": "pocket", "name": "PocketHoles", "plane": "XY", "position": TOP, "length": 7.6,
         "profile": {"circles": [{"center": center_of(p), "diameter": 3.4, "expr": "Params.hole_d", "name": f"hole_d{i}"} for i, p in enumerate(hx)]}},
    ]
    return run("hs_middle_cap", name, {"hole_d": 3.4}, feats)


results["middle_cap"] = build_middle_cap()
_result = results
