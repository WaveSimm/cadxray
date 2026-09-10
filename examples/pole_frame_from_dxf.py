"""구조 DXF(연대포구 철봉 도면(각관부착).dxf, 1/40 도면이지만 모델 좌표는 실치수 mm) → 3D 프레임. FreeCAD 안에서 exec.

읽는 법: ezdxf로 modelspace의 LWPOLYLINE·CIRCLE·DIMENSION(get_measurement)·TEXT·MULTILEADER·블록(BRACKET1)을 뽑고
ezdxf.addons.drawing으로 영역별 PNG를 그려 눈으로 대조했다. 부품표(BOM)가 TEXT로 들어 있어 파이프 규격은 거기서 읽었다.
- 기둥 PIPE-250A SCH160(OD 267.4×28.4t) 2본, 파라펫 상단 기준 높이 6000. 도면의 정면도는 기둥을 216(=200A OD)으로 그려 놓아 BOM과 다르다 → BOM을 따랐다
- 가로 PIPE-150A(OD 165.2×18.2t) 1본: 기둥 사이 2500(치수), 윗면이 기둥 윗면과 같은 높이. 양 끝을 기둥 곡면으로 코핑해 소재 길이 2557.1
- 각관 150×100(두께 4.5 가정) 4500, 기둥 앞면에 부착. 윗면도의 77.67로 기둥이 각관에 22.33 파고드는 것을 읽어 뒷면 코핑.
  Ø50 구멍 20개 @200(첫 구멍 지면 1100), 구멍마다 M8(Ø8) 4개가 66 간격 십자. 도면의 "□50"은 BOM의 "%%C240"처럼 Ø 기호 깨짐
- 가로 파이프 Ø50 구멍 5개(500/500/250/250/500/500), 앞뒤 관통
- 기둥 앞면 개구부: 점검구 100×150(z 5491), 케이블 인입구 50×100(z 50, 중심에서 56.5 옆) — MULTILEADER 글자로 확인
- 받침: 베이스 플레이트 10t 600×1800, 거싯 10t 150×400 8장/기둥(BRACKET1 블록 모양, 스나이프 R20은 직선 근사), 캡 6t Ø240
- 기초 콘크리트 800×1000(정면), 깊이 1800 가정. 도면에 있는 각관 하단 120×250, 기둥 하단 150×250은 뜻이 불명확해 넣지 않았다
"""
import math
import FreeCAD as App
from CadXray.handlers import rebuild

DOC = "pole_frame"
if DOC in App.listDocuments():
    App.closeDocument(DOC)
doc = App.newDocument(DOC)

P = dict(pole_od=267.4, pole_t=28.4, pole_h=6000.0, span=2500.0, bar_od=165.2, bar_t=18.2,
         plate_t=10.0, base_w=600.0, base_l=1800.0, gusset_w=150.0, gusset_h=400.0, cap_d=240.0, cap_t=6.0,
         tube_w=150.0, tube_d=100.0, tube_t=4.5, tube_len=4500.0, tube_z0=550.0, tube_gap=77.67,
         hole_d=50.0, hole_pitch=200.0, hole_z0=1100.0, hole_n=20, bolt_d=8.0, bolt_off=33.0,
         insp_w=100.0, insp_h=150.0, insp_z0=5491.0, cable_w=50.0, cable_h=100.0, cable_z0=50.0, cable_dx=-56.5,
         found_w=800.0, found_l=1800.0, found_h=1000.0)
R = P["pole_od"] / 2
pitch = P["span"] + P["pole_od"]                                 # 기둥 중심 거리 2767.4
sag = R - math.sqrt(R * R - (P["bar_od"] / 2) ** 2)              # 가로 파이프 코핑 깊이 28.6
bar_raw = P["span"] + 2 * sag

def build(body, feats, params=None):
    r = rebuild.build_features(body=body, doc=DOC, params=params, features=feats, create_body=True)
    if not r["ok"] or r["data"].get("stopped_at"):
        raise RuntimeError(f"{body}: {r.get('error') or r['data']['stopped_at']} :: {[c['status'] for c in r['data'].get('created', [])]}")
    return [(c["name"], c.get("dof")) for c in r["data"]["created"]]

log = {}
# 1. 기둥 PIPE-250A: z 10~6000, 앞면(-Y)에 점검구·케이블 인입구 (앞 벽만 절삭: XZ 스케치에서 -Y로 140)
log["Pole"] = build("Pole", [
    {"op": "pad", "name": "PadPipe", "plane": "XY", "position": P["plate_t"], "length": "Params.pole_h - Params.plate_t",
     "profile": {"circles": [{"center": [0, 0], "diameter": P["pole_od"], "expr": "Params.pole_od", "name": "pole_od"},
                             {"center": [0, 0], "diameter": P["pole_od"] - 2 * P["pole_t"], "expr": "Params.pole_od - 2 * Params.pole_t", "name": "pole_id"}]}},
    {"op": "pocket", "name": "PocketOpenings", "plane": "XZ", "position": 0.0, "length": R + 10, "reversed": True,
     "profile": {"polygons": [
         [[-P["insp_w"] / 2, P["insp_z0"]], [P["insp_w"] / 2, P["insp_z0"]], [P["insp_w"] / 2, P["insp_z0"] + P["insp_h"]], [-P["insp_w"] / 2, P["insp_z0"] + P["insp_h"]]],
         [[P["cable_dx"] - P["cable_w"] / 2, P["cable_z0"]], [P["cable_dx"] + P["cable_w"] / 2, P["cable_z0"]],
          [P["cable_dx"] + P["cable_w"] / 2, P["cable_z0"] + P["cable_h"]], [P["cable_dx"] - P["cable_w"] / 2, P["cable_z0"] + P["cable_h"]]]]}},
], params=P)
# 2. 가로 파이프 PIPE-150A: X 방향, 중심 원점, 양 끝 기둥 곡면으로 코핑, Ø50 구멍 5개(앞뒤 관통)
xs = [500, 1000, 1250, 1500, 2000]
log["Bar"] = build("Bar", [
    {"op": "pad", "name": "PadBar", "plane": "YZ", "position": 0.0, "midplane": True, "length": bar_raw,
     "profile": {"circles": [{"center": [0, 0], "diameter": P["bar_od"], "expr": "Params.bar_od", "name": "bar_od"},
                             {"center": [0, 0], "diameter": P["bar_od"] - 2 * P["bar_t"], "expr": "Params.bar_od - 2 * Params.bar_t", "name": "bar_id"}]}},
    {"op": "pocket", "name": "PocketCope", "plane": "XY", "position": 0.0, "through": True, "midplane": True,
     "profile": {"circles": [{"center": [-pitch / 2, 0], "diameter": P["pole_od"], "expr": "Params.pole_od"},
                             {"center": [pitch / 2, 0], "diameter": P["pole_od"], "expr": "Params.pole_od"}]}},
    {"op": "pocket", "name": "PocketHoles", "plane": "XZ", "position": 0.0, "through": True, "midplane": True,
     "profile": {"circles": [{"center": [x - P["span"] / 2, 0], "diameter": P["hole_d"], "expr": "Params.hole_d"} for x in xs]}},
])
# 3. 각관 150x100x4.5: 바닥 중심 원점, Z 방향 4500, 뒷면을 기둥 곡면으로 코핑, 앞면에 Ø50 + M8x4 (관통)
yc = -P["tube_d"] / 2 + P["tube_gap"] + R                        # 각관 로컬에서 기둥 중심 y (161.37)
zs = [P["hole_z0"] - P["tube_z0"] + k * P["hole_pitch"] for k in range(P["hole_n"])]
holes = [{"center": [0, z], "diameter": P["hole_d"], "expr": "Params.hole_d"} for z in zs]
for z in zs:
    for dx, dz in ((P["bolt_off"], 0), (-P["bolt_off"], 0), (0, P["bolt_off"]), (0, -P["bolt_off"])):
        holes.append({"center": [dx, z + dz], "diameter": P["bolt_d"], "expr": "Params.bolt_d"})
w, d, t = P["tube_w"] / 2, P["tube_d"] / 2, P["tube_t"]
log["Tube"] = build("Tube", [
    {"op": "pad", "name": "PadTube", "plane": "XY", "position": 0.0, "length": "Params.tube_len",
     "profile": {"polygons": [[[-w, -d], [w, -d], [w, d], [-w, d]], [[-w + t, -d + t], [w - t, -d + t], [w - t, d - t], [-w + t, d - t]]]}},
    {"op": "pocket", "name": "PocketCope", "plane": "XY", "position": 0.0, "through": True, "midplane": True,
     "profile": {"circles": [{"center": [0, yc], "diameter": P["pole_od"], "expr": "Params.pole_od"}]}},
    {"op": "pocket", "name": "PocketHoles", "plane": "XZ", "position": 0.0, "through": True, "midplane": True,
     "profile": {"circles": holes}},
])
# 4. 거싯 PLATE 10t 400x150 (BRACKET1 블록 모양, 스나이프 20은 직선으로), 기둥 중심 원점, -X 쪽에 세움
g = [[-R - 150, 0], [-R - 20, 0], [-R, 20], [-R, 400], [-R - 20, 400], [-R - 150, 20]]
log["Gusset"] = build("Gusset", [{"op": "pad", "name": "PadGusset", "plane": "XZ", "position": 0.0, "midplane": True, "length": "Params.plate_t", "profile": {"polygon": g}}])
# 5. 베이스 플레이트 10t 600x1800, 6. 캡 플레이트 6t Ø240, 7. 기초 콘크리트 800x1800x1000 (아래로)
log["BasePlate"] = build("BasePlate", [{"op": "pad", "name": "PadBase", "plane": "XY", "position": 0.0, "length": "Params.plate_t",
                                        "profile": {"rect": {"center": [0, 0], "width": P["base_w"], "height": P["base_l"]}}}])
log["CapPlate"] = build("CapPlate", [{"op": "pad", "name": "PadCap", "plane": "XY", "position": 0.0, "length": "Params.cap_t",
                                      "profile": {"circles": [{"center": [0, 0], "diameter": P["cap_d"], "expr": "Params.cap_d"}]}}])
log["Foundation"] = build("Foundation", [{"op": "pad", "name": "PadFound", "plane": "XY", "position": 0.0, "length": "Params.found_h", "reversed": True,
                                          "profile": {"rect": {"center": [0, 0], "width": P["found_w"], "height": P["found_l"]}}}])

# 인스턴스 배치
grp = doc.addObject("App::DocumentObjectGroup", "Frame")
def link(name, body, x, y, z, rot=0.0):
    l = doc.addObject("App::Link", name)
    l.LinkedObject = doc.getObject(body)
    l.Placement = App.Placement(App.Vector(x, y, z), App.Rotation(App.Vector(0, 0, 1), rot))
    grp.addObject(l)
    return l
for i, x in enumerate((0.0, pitch)):
    s = f"_{i + 1}"
    link("Pole" + s, "Pole", x, 0, 0)
    link("CapPlate" + s, "CapPlate", x, 0, P["pole_h"])
    link("BasePlate" + s, "BasePlate", x, 0, 0)
    link("Foundation" + s, "Foundation", x, 0, 0)
    link("Tube" + s, "Tube", x, -yc, P["tube_z0"])
    for k in range(8):
        link(f"Gusset{s}_{k + 1}", "Gusset", x, 0, P["plate_t"], 45.0 * k)
link("Bar_1", "Bar", pitch / 2, 0, P["pole_h"] - P["bar_od"] / 2)
for b in ("Pole", "Bar", "Tube", "Gusset", "BasePlate", "CapPlate", "Foundation"):
    doc.getObject(b).ViewObject.Visibility = False if App.GuiUp else None
doc.recompute()
bad = [o.Name for o in doc.Objects if not o.isValid()]
bb = App.BoundBox()
for o in grp.Group:
    bb.add(o.Shape.BoundBox)
_result = {"features": log, "links": len(grp.Group), "invalid": bad, "bar_raw": round(bar_raw, 2), "pitch": pitch,
           "bbox": [round(v, 1) for v in (bb.XMin, bb.XMax, bb.YMin, bb.YMax, bb.ZMin, bb.ZMax)]}
