"""사진·조감도(치수 5개만) → 3D. Claude가 그림을 읽고 비율로 나머지를 정한 예. FreeCAD 안에서 exec.

만년필 잉크병 보관대 (조감도 2장 → 3D). 주어진 치수: 폭 16.3, 높이 8.2, 병 포함 13 (cm), 구멍 1 Ø1.8, 구멍 2~4 Ø2.7.
나머지(깊이 35, 윗바 12, 옆벽 10, 아랫바 21, 구멍 위치, 받침 홈 2, 장식판 홈 1, 병 Ø26/캡 Ø28)는 사진 비율로 정한 값.
좌표: X 폭(0~163), Y 깊이(앞면 y=0), Z 높이(0~82)."""
import FreeCAD as App
from CadXray.handlers import rebuild

DOC = "ink_holder"
if DOC in App.listDocuments():
    App.closeDocument(DOC)
App.newDocument(DOC)
P = dict(width=163.0, height=82.0, depth=35.0, top_t=12.0, side_t=10.0, bottom_t=21.0, window_r=6.0,
         hole1_d=18.0, hole_d=27.0, recess_d=2.0, recess_clear=1.5, plate_w=143.0, plate_h=12.0, plate_d=1.0, edge_r=2.0,
         vial_d=26.0, vial_l=96.0, cap_d=28.0, cap_l=15.0)
W, H, D = P["width"], P["height"], P["depth"]
XS = [25.0, 60.0, 97.0, 134.0]                 # 구멍 중심 X (사진 비율)
YC = D / 2
win_z0, win_z1 = P["bottom_t"], H - P["top_t"]  # 창 21~70

def build(body, feats):
    r = rebuild.build_features(body=body, doc=DOC, params=P, features=feats)
    if not r["ok"] or r["data"].get("stopped_at"):
        raise RuntimeError(f"{body}: {r.get('error') or r['data']['stopped_at']} :: {[(c['name'], c['status'][:60]) for c in r['data'].get('created', [])]}")
    return [(c["name"], c.get("dof"), c.get("edges")) for c in r["data"]["created"]]

log = {}
log["InkHolder"] = build("InkHolder", [
    {"op": "pad", "name": "PadFrame", "plane": "XZ", "position": 0.0, "length": "Params.depth", "reversed": True,
     "profile": {"rect": {"center": [W / 2, H / 2], "width": W, "height": H}}},
    {"op": "pocket", "name": "PocketWindow", "plane": "XZ", "position": 0.0, "through": True, "midplane": True,
     "profile": {"rect": {"center": [W / 2, (win_z0 + win_z1) / 2], "width": W - 2 * P["side_t"], "height": win_z1 - win_z0}}},
    {"op": "fillet", "name": "FilletWindow", "size": "Params.window_r",
     "edges": {"direction": [0, 1, 0], "length": D, "bbox": {"min": [P["side_t"] - 0.5, None, win_z0 - 0.5], "max": [W - P["side_t"] + 0.5, None, win_z1 + 0.5]}}},
    {"op": "pocket", "name": "PocketTopHoles", "plane": "XY", "position": H, "length": "Params.top_t + 0.5",
     "profile": {"circles": [{"center": [XS[0], YC], "diameter": P["hole1_d"], "expr": "Params.hole1_d", "name": "hole1"}] +
                            [{"center": [x, YC], "diameter": P["hole_d"], "expr": "Params.hole_d", "name": f"hole{i + 2}"} for i, x in enumerate(XS[1:])]}},
    {"op": "pocket", "name": "PocketRecess", "plane": "XY", "position": win_z0, "length": "Params.recess_d",
     "profile": {"circles": [{"center": [XS[0], YC], "diameter": P["hole1_d"] + P["recess_clear"], "expr": "Params.hole1_d + Params.recess_clear"}] +
                            [{"center": [x, YC], "diameter": P["hole_d"] + P["recess_clear"], "expr": "Params.hole_d + Params.recess_clear"} for x in XS[1:]]}},
    {"op": "pocket", "name": "PocketPlate", "plane": "XZ", "position": 0.0, "length": "Params.plate_d",
     "profile": {"rect": {"center": [W / 2, P["bottom_t"] / 2], "width": P["plate_w"], "height": P["plate_h"]}}},
    {"op": "fillet", "name": "FilletOuter", "size": "Params.edge_r", "edges": {"direction": [0, 0, 1], "length": H}},
])
log["Vial"] = build("Vial", [
    {"op": "pad", "name": "PadVial", "plane": "XY", "position": 0.0, "length": "Params.vial_l",
     "profile": {"circles": [{"center": [0, 0], "diameter": P["vial_d"], "expr": "Params.vial_d"}]}},
    {"op": "fillet", "name": "FilletBottom", "size": 4.0, "edges": {"curve": "Circle", "center": [0, 0, 0]}},
])
log["Cap"] = build("Cap", [        # 캡은 별도 바디 — 몸통(투명)과 외관을 따로 주려고
    {"op": "pad", "name": "PadCap", "plane": "XY", "position": 0.0, "length": "Params.cap_l",
     "profile": {"circles": [{"center": [0, 0], "diameter": P["cap_d"], "expr": "Params.cap_d"}]}},
    {"op": "chamfer", "name": "ChamferCap", "size": 1.0, "edges": {"curve": "Circle", "center": [0, 0, P["cap_l"]]}},
])
doc = App.getDocument(DOC)
grp = doc.addObject("App::DocumentObjectGroup", "Vials")
for i, x in enumerate(XS[1:]):
    l = doc.addObject("App::Link", f"Vial_{i + 1}")
    l.LinkedObject = doc.getObject("Vial")
    l.Placement = App.Placement(App.Vector(x, YC, win_z0 - P["recess_d"]), App.Rotation())
    grp.addObject(l)
    c = doc.addObject("App::Link", f"Cap_{i + 1}")
    c.LinkedObject = doc.getObject("Cap")
    c.Placement = App.Placement(App.Vector(x, YC, win_z0 - P["recess_d"] + P["vial_l"]), App.Rotation())
    grp.addObject(c)
if App.GuiUp:
    doc.getObject("Vial").ViewObject.Visibility = False
    doc.getObject("Cap").ViewObject.Visibility = False
doc.recompute()
h = doc.getObject("InkHolder").Shape
bb = h.BoundBox
_result = {"features": log, "valid": h.isValid(), "volume_cm3": round(h.Volume / 1000, 1), "faces": len(h.Faces),
           "bbox": [round(v, 1) for v in (bb.XMin, bb.XMax, bb.YMin, bb.YMax, bb.ZMin, bb.ZMax)],
           "vial_top_z": round(doc.getObject("Cap_1").Shape.BoundBox.ZMax, 1), "invalid": [o.Name for o in doc.Objects if not o.isValid()]}

# 외관: 검붉은 아노다이징 알루미늄(보관대), 유리(병 몸통, Transparency 70), 검정(캡). FreeCAD 1.1은 ViewObject.ShapeAppearance = (App.Material,)로 준다.
# Body에 주고 피처들에도 같은 값을 복사해야 Tip이 바뀌어도 색이 유지된다. Link는 OverrideMaterial=False면 원본 색을 따른다.
# Material.Transparency(면별)는 3D 뷰에 안 먹는다 → ViewObject.Transparency(객체 전체)를 쓴다. 그래서 캡을 별도 바디로 뺐다.
def appearance(obj, rgb, specular=0.55, shininess=0.7, transparency=0.0):
    m = App.Material()
    m.DiffuseColor, m.SpecularColor, m.AmbientColor = rgb, (specular,) * 3, tuple(c * 0.4 for c in rgb)
    m.Shininess, m.Transparency = shininess, transparency
    for o in [obj] + list(obj.Group):
        if hasattr(o.ViewObject, "ShapeAppearance"):
            o.ViewObject.ShapeAppearance = (m,)
            o.ViewObject.Transparency = int(transparency * 100)
if App.GuiUp:
    appearance(doc.getObject("InkHolder"), (0.40, 0.05, 0.08))
    appearance(doc.getObject("Vial"), (0.80, 0.90, 0.95), specular=0.9, shininess=0.95, transparency=0.70)
    appearance(doc.getObject("Cap"), (0.06, 0.06, 0.07), specular=0.8, shininess=0.9)
