"""STL(3D 프린트용 스풀 가이드, 5,758면) → M7 툴만으로 파라메트릭 재구성한 기록 (M8 설계의 근거). FreeCAD 안에서 exec.
전제: 문서 stl_test에 STL이 Mesh::Feature로 들어 있다 (Mesh.insert).

결과: 메시 정점 1,432개 전부 모델 표면에서 0.03 mm 안(평균 0.003), 부피 차 0.014 %, 스케치 전부 DoF 0. 나사 시작부 표본 3점만 0.4~0.9.
M7 툴이 메시에 대해 한 것/못 한 것:
  - classify_faces(makeShapeFromMesh 솔리드): 삼각형 5,758개 전부 plane, 원통 0, levels(z 0/1.97/4.97/27.97/35.97)만 유효. levels[].faces 목록이 수천 개 → 응답 폭발
  - find_holes: 0개 (원통면 없음).  compare_shapes: 퍼지 불리언이 10분 넘게 메인 스레드를 잡음 → FreeCAD 재시작
  - 대신 Mesh.crossSections 폴리라인을 최소제곱 원 피팅 → 반지름 0.01 mm 안. 이 값으로 build_features 6단계 + SubtractiveHelix + 되메움 Pad
읽어 낸 형상: Ø201 원판 t2, 호형 슬롯 4개(r 67.5~87.5, 스포크 폭 20에 잘리고 바깥 모서리 R10), 창 4개(r 32.5~55), 테두리 벽 1×3,
  허브 링 R18~25 h3, 허브 R18.5~22.4 (z 5~28), 수나사 Ø44.5 피치 2 길이 8 (골 Ø42.1, 골 폭 0.62, 60°급 V) — "AMS Male".
  나사는 높이별 단면의 최대 반지름 각도가 1 mm당 180° 도는 것으로 알아냈다(처음엔 캠 돌기로 오해).
검증은 불리언 없이: Body 면 표본점에서 법선 ±방향으로 Mesh.nearestFacetOnRay → 편차, 메시 정점 → Body.distToShape 역방향 편차.
"""
import math
import FreeCAD as App
from CadXray.handlers import rebuild

DOC = "stl_test"
doc = App.getDocument(DOC)
mm = [o for o in doc.Objects if o.TypeId == "Mesh::Feature"][0].Mesh

def fit_circle(pts):
    n = len(pts); sx = sum(p[0] for p in pts) / n; sy = sum(p[1] for p in pts) / n
    u = [(p[0] - sx, p[1] - sy) for p in pts]
    suu = sum(a * a for a, b in u); svv = sum(b * b for a, b in u); suv = sum(a * b for a, b in u)
    suuu = sum(a ** 3 for a, b in u); svvv = sum(b ** 3 for a, b in u); suvv = sum(a * b * b for a, b in u); svuu = sum(b * a * a for a, b in u)
    det = suu * svv - suv * suv
    uc = (0.5 * (suuu + suvv) * svv - 0.5 * (svvv + svuu) * suv) / det; vc = (0.5 * (svvv + svuu) * suu - 0.5 * (suuu + suvv) * suv) / det
    return uc + sx, vc + sy, math.sqrt(uc * uc + vc * vc + (suu + svv) / n)

# 중심: z=1 단면의 바깥 원(211점) 피팅. z 기준: 메시 바닥
cs = mm.crossSections([((0, 0, 1.0), (0, 0, 1))], 0.001)[0]
outer = max(cs, key=len)
CX, CY, R_OUT = fit_circle([(p.x, p.y) for p in outer])
Z0 = mm.BoundBox.ZMin

P = dict(plate_r=100.5, plate_t=2.0, bore_r=18.0, bore_r_hub=18.5, rim_w=1.0, rim_h=3.0, hubring_r=25.0, hub_r=22.4, hub_top=28.0,
         cam_top=36.0, slot_r_in=67.5, slot_r_out=87.5, slot_fillet=10.0, thread_major_r=22.25, thread_minor_r=21.05, thread_pitch=2.0, thread_root_w=0.62, thread_len=8.0, win_r_in=32.5, win_r_out=55.0, spoke_w=20.0)
def pol(r, deg):
    return [CX + r * math.cos(math.radians(deg)), CY + r * math.sin(math.radians(deg))]
def C(): return [CX, CY]

# 슬롯: 환형 조각 r 67.5~87.5을 스포크 띠(|x|,|y| ≤ 10)로 자른 모양. 바깥 모서리만 R10 (원이 r=87.5와 스포크 선에 접함), 안쪽 모서리는 직각
def slot(k):
    ri, ro, h, rf = P["slot_r_in"], P["slot_r_out"], P["spoke_w"] / 2, P["slot_fillet"]
    fc = math.sqrt((ro - rf) ** 2 - (h + rf) ** 2)            # 필렛 중심 (fc, h+rf): r=ro-rf 원 위, 스포크 선에서 rf
    t = math.atan2(h + rf, fc)                                # 필렛과 바깥 호의 접점 각도
    yi = math.sqrt(ri * ri - h * h)
    def rot(x, y):
        a = math.radians(90 * k)
        return [CX + x * math.cos(a) - y * math.sin(a), CY + x * math.sin(a) + y * math.cos(a)]
    tp1 = ((ro) * math.cos(t), (ro) * math.sin(t))            # 첫 필렛 접점 (바깥 호)
    tp2 = ((ro) * math.sin(t), (ro) * math.cos(t))            # 둘째 필렛 접점 (대칭)
    return [
        {"type": "line", "start": rot(yi, h), "end": rot(fc, h)},                                             # 아래 스포크 선 y=h
        {"type": "arc", "center": rot(fc, h + rf), "radius": rf, "start": rot(fc, h), "end": rot(*tp1), "ccw": True},
        {"type": "arc", "center": C(), "radius": ro, "start": rot(*tp1), "end": rot(*tp2), "ccw": True},        # 바깥 호
        {"type": "arc", "center": rot(h + rf, fc), "radius": rf, "start": rot(*tp2), "end": rot(h, fc), "ccw": True},
        {"type": "line", "start": rot(h, fc), "end": rot(h, yi)},                                             # 왼쪽 스포크 선 x=h
        {"type": "arc", "center": C(), "radius": ri, "start": rot(h, yi), "end": rot(yi, h), "ccw": False},     # 안쪽 호
    ]
# 창: 스포크(폭 20) 사이 환형 조각. 1사분면 것을 90°씩 돌린다
def window(k):
    h = P["spoke_w"] / 2; ri, ro = P["win_r_in"], P["win_r_out"]
    yi, yo = math.sqrt(ri * ri - h * h), math.sqrt(ro * ro - h * h)
    A, B, Cc, D = (h, yi), (h, yo), (yo, h), (yi, h)
    def rot(p):
        t = math.radians(90 * k); x, y = p
        return [CX + x * math.cos(t) - y * math.sin(t), CY + x * math.sin(t) + y * math.cos(t)]
    return [
        {"type": "line", "start": rot(A), "end": rot(B)},
        {"type": "arc", "center": C(), "radius": ro, "start": rot(B), "end": rot(Cc), "ccw": False},
        {"type": "line", "start": rot(Cc), "end": rot(D)},
        {"type": "arc", "center": C(), "radius": ri, "start": rot(D), "end": rot(A), "ccw": True},
    ]
circ = lambda r, expr=None: {"type": "circle", "center": C(), "radius": r, "expr": f"2 * ({expr})" if expr else None}   # expr는 지름 수식
feats = [
    {"op": "pad", "name": "PadPlate", "plane": "XY", "position": Z0, "length": "Params.plate_t",
     "profile": {"wires": [[circ(P["plate_r"], "Params.plate_r")], [circ(P["bore_r"], "Params.bore_r")]]}},
    {"op": "pocket", "name": "PocketSlots", "plane": "XY", "position": Z0 + P["plate_t"], "through": True,
     "profile": {"wires": [slot(k) for k in range(4)]}},
    {"op": "pocket", "name": "PocketWindows", "plane": "XY", "position": Z0 + P["plate_t"], "through": True,
     "profile": {"wires": [window(k) for k in range(4)]}},
    {"op": "pad", "name": "PadRings", "plane": "XY", "position": Z0 + P["plate_t"], "length": "Params.rim_h",
     "profile": {"wires": [[circ(P["plate_r"], "Params.plate_r")], [circ(P["plate_r"] - P["rim_w"], "Params.plate_r - Params.rim_w")],
                           [circ(P["hubring_r"], "Params.hubring_r")], [circ(P["bore_r"], "Params.bore_r")]]}},
    {"op": "pad", "name": "PadHub", "plane": "XY", "position": Z0 + P["plate_t"] + P["rim_h"], "length": "Params.hub_top - Params.plate_t - Params.rim_h",
     "profile": {"wires": [[circ(P["hub_r"], "Params.hub_r")], [circ(P["bore_r_hub"], "Params.bore_r_hub")]]}},
    {"op": "pad", "name": "PadThreadCyl", "plane": "XY", "position": Z0 + P["hub_top"], "length": "Params.cam_top - Params.hub_top",
     "profile": {"wires": [[circ(P["thread_major_r"], "Params.thread_major_r")], [circ(P["bore_r_hub"], "Params.bore_r_hub")]]}},
]
if doc.getObject("SpoolGuide"):
    for o in list(doc.getObject("SpoolGuide").Group): doc.removeObject(o.Name)
    doc.removeObject("SpoolGuide")
r = rebuild.build_features(body="SpoolGuide", doc=DOC, params=P, features=feats)
body = doc.getObject("SpoolGuide")
res = {"center": [round(CX, 4), round(CY, 4)], "r_out_fit": round(R_OUT, 3), "z0": round(Z0, 4),
       "ok": r["ok"], "stopped_at": r["data"].get("stopped_at") if r["ok"] else r.get("error"),
       "created": [(c["name"], c.get("dof"), c["status"][:50], round(c.get("volume_after") or 0, 1)) for c in r["data"].get("created", [])] if r["ok"] else None}

# 나사산: build_features에 없는 연산 → PartDesign::SubtractiveHelix를 직접. 홈 단면은 골 중심이 z=hub_top(각도 0°)에 오게, 온전한 한 피치.
# 허브(r 22.4, z<28)까지 잘리므로 마지막에 z 25~28 링을 되메운다 (PadRefill).
import Part, Sketcher
sk = body.newObject("Sketcher::SketchObject", "SketchThread")
sk.AttachmentSupport = [(body.Origin.OriginFeatures[4], "")]        # XZ_Plane: 로컬 x = 전역 X, 로컬 y = 전역 Z, 로컬 z = 전역 -Y
sk.MapMode = "FlatFace"
sk.AttachmentOffset = App.Placement(App.Vector(CX, 0, -CY), App.Rotation())   # 스케치 원점을 부품 축 위로
RMAJ, RMIN, PITCH, RW = P["thread_major_r"], P["thread_minor_r"], P["thread_pitch"], P["thread_root_w"]
FL = (PITCH - RW) / 2
zc = Z0 + P["hub_top"] - PITCH          # 한 바퀴 아래에서 시작 — 각도 0° 이전 구간의 첫 바퀴도 깎이게
pts = [(RMAJ + 1.0, zc - PITCH / 2), (RMAJ, zc - PITCH / 2), (RMIN, zc - RW / 2), (RMIN, zc + RW / 2), (RMAJ, zc + PITCH / 2), (RMAJ + 1.0, zc + PITCH / 2)]
geo = [sk.addGeometry(Part.LineSegment(App.Vector(*pts[i], 0), App.Vector(*pts[(i + 1) % len(pts)], 0)), False) for i in range(len(pts))]
for i in range(len(geo)):
    sk.addConstraint(Sketcher.Constraint("Coincident", geo[i], 2, geo[(i + 1) % len(geo)], 1))
for g in geo:
    sk.addConstraint(Sketcher.Constraint("Block", g))
hx = body.newObject("PartDesign::SubtractiveHelix", "ThreadHelix")
hx.Profile = (sk, [""]); hx.ReferenceAxis = (sk, ["V_Axis"])
hx.Mode = "pitch-height-angle"; hx.Pitch = PITCH; hx.Height = P["thread_len"] + 2 * PITCH; hx.Angle = 0.0
hx.LeftHanded = False; hx.Reversed = False; hx.Outside = False
sk.Visibility = False
doc.recompute()
res["helix"] = (hx.getStatusString(), sk.solve(), sk.FullyConstrained)
r2 = rebuild.build_features(body="SpoolGuide", doc=DOC, create_body=False, features=[
    {"op": "pad", "name": "PadRefill", "plane": "XY", "position": Z0 + P["hub_top"] - 1.5 * P["thread_pitch"], "length": "1.5 * Params.thread_pitch",
     "profile": {"wires": [[circ(P["hub_r"], "Params.hub_r")], [circ(P["bore_r_hub"], "Params.bore_r_hub")]]}}])
res["refill"] = (r2["ok"], r2["data"].get("stopped_at") if r2["ok"] else r2.get("error"))
doc.recompute()
if body.Shape.isValid():
    res["volume"] = round(body.Shape.Volume, 1); res["mesh_volume"] = round(mm.Volume, 1)
    res["volume_diff_pct"] = round((body.Shape.Volume - mm.Volume) / mm.Volume * 100, 3); res["faces"] = len(body.Shape.Faces)
_result = res
