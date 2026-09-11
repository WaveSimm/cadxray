"""벤더 STEP 클램프 조(2B2, 44면)를 M7 툴(build_features / compare_shapes)만으로 재구성한 기록.

FreeCAD 안에서 exec 하거나, 같은 내용을 Claude가 MCP 툴 호출로 보낸다. 손으로 200줄을 쓰던 일이
피처 12개짜리 목록 하나로 줄었다. 아래 수치는 이렇게 얻었다:
  - classify_faces  : BSpline 전이면 8개 → 원뿔(축 Z, 꼭짓점 A1, 반각 59.63°), 원통 반지름(35 / 33.620391 / 17.75 / 16.12127)
  - section_profile(position=None) : vertex_positions 로 띠·홈·립의 z 경계
  - find_holes      : Ø3.4 관통 + Ø5.6×4 카운터보어 + 0.5 챔퍼, Ø2.2×5 핀 2개
결과: compare_shapes → volume_diff +0.035 mm³ (0.0004 %), verdict identical, 스케치 12개 전부 DoF 0.

    SRC_DOC / SRC_NAME : STEP을 연 문서와 그 안의 부품 객체 Name (get_document_graph로 확인)
반지름은 classify_faces가 준 값을 반올림하지 말고 그대로 쓴다 — 33.6204로 쓰면 겹친 면이 9e-6 어긋나 0.6 mm³를 잃는다.
"""
import FreeCAD

from freecad.cadxray.handlers import rebuild

SRC_DOC, SRC_NAME = "Unnamed", "Part__Feature004"
DOC = "jaw_2B2_tools"

if DOC in FreeCAD.listDocuments():
    FreeCAD.closeDocument(DOC)
FreeCAD.newDocument(DOC)

# 정점에서 읽은 기준점과 설계값
X0, Y0, Z0 = 20.343193, 45.052724, 53.679659      # 뒤판 x, 중심 구멍 y, 바닥 z
HZ = Z0 + 8.0                                      # 구멍 높이
A1 = (38.176526, Y0)                               # 배럴 축
A2, A3 = (44.009859, 27.552724), (44.009859, 62.552724)   # 시트 축 2개
RB, RG = 35.0, 33.620391                           # 배럴 띠 / 더브테일 홈 바닥
RS, RL = 17.75, 16.12127                           # 시트 / 립
GZ0, GZ1, GT = 57.390984, 65.968334, 0.80829       # 홈 z 범위, 전이 높이
LZ0, LZ1, LT = 57.968334, 65.390984, 0.954646      # 립 z 범위, 전이 높이
PIN_DY = 14.250464

params = {
    "x_back": X0, "thickness": 12.0, "z_bottom": Z0, "height": 16.0,
    "band1_h": LZ0 + LT - Z0, "band2_z": LZ1 - LT, "mid_z0": LZ0, "mid_h": LZ1 - LZ0,
    "groove_z0": GZ0, "groove_h": GZ1 - GZ0, "barrel_x": A1[0], "barrel_y": A1[1], "barrel_r": RB, "groove_r": RG,
    "seat_x": A2[0], "seat_y1": A2[1], "seat_y2": A3[1], "seat_r": RS, "lip_r": RL,
    "hole_d": 3.4, "cbore_d": 5.6, "cbore_depth": 4.0, "chamfer": 0.5,
    "pin_d": 2.2, "pin_depth": 5.0, "pin_dy": PIN_DY, "hole_z": HZ,
}
SRC = {"of": SRC_NAME, "doc": SRC_DOC}
xb, xs = A1[0], A2[0]
lip_wedges = [
    [[xs - RL, LZ0], [xs - RS, LZ0 + LT], [xs - RS, LZ0]],
    [[xs - RL, LZ1], [xs - RS, LZ1 - LT], [xs - RS, LZ1]],
]
features = [
    # 1. 띠 세 개 — 원본 단면을 그대로 트레이스 (구멍은 3D에서 메워진 채로)
    {"op": "pad", "name": "PadBand1", "plane": "XY", "position": "Params.z_bottom",
     "profile": {"section": dict(SRC, position=55.0)}, "length": "Params.band1_h"},
    {"op": "pad", "name": "PadMid", "plane": "XY", "position": "Params.mid_z0",
     "profile": {"section": dict(SRC, position=HZ)}, "length": "Params.mid_h"},
    {"op": "pad", "name": "PadBand2", "plane": "XY", "position": "Params.band2_z",
     "profile": {"section": dict(SRC, position=67.0)}, "length": "Params.z_bottom + Params.height - Params.band2_z"},
    # 2. 배럴 더브테일 홈 (회전 절삭) + 홈이 깎아 버린 귀 복원 (가운데 단면에서 홈 반지름 원 밖만)
    {"op": "groove", "name": "GrooveBarrel", "plane": "XZ", "position": "Params.barrel_y", "axis": {"x": xb},
     "profile": {"polygon": [[xb - RG, GZ0], [xb - RB, GZ0 + GT], [xb - RB, GZ1 - GT], [xb - RG, GZ1]]}},
    {"op": "pad", "name": "PadEars", "plane": "XY", "position": "Params.groove_z0",
     "profile": {"section": dict(SRC, position=HZ, exclude=[{"center": [xb, A1[1]], "radius": RG}])},
     "length": "Params.groove_h"},
    # 3. 시트 립 전이 쐐기 (회전 절삭 ×2) + 앞판 앞으로 나온 띠 귀 복원
    {"op": "groove", "name": "GrooveLip1", "plane": "XZ", "position": "Params.seat_y1", "axis": {"x": xs},
     "profile": {"polygons": lip_wedges}},
    {"op": "groove", "name": "GrooveLip2", "plane": "XZ", "position": "Params.seat_y2", "axis": {"x": xs},
     "profile": {"polygons": lip_wedges}},
    {"op": "pad", "name": "PadSeatEars", "plane": "XY", "position": "Params.mid_z0",
     "profile": {"section": dict(SRC, position=HZ, clip={"min": [X0 + 12.0, None]})}, "length": "Params.mid_h"},
    # 4. 구멍 — find_holes 값. YZ 평면(법선 +X)에서 뒤판 안쪽으로 파므로 reversed
    {"op": "pocket", "name": "PocketHole", "plane": "YZ", "position": "Params.x_back", "through": True, "reversed": True,
     "profile": {"circles": [{"center": [Y0, HZ], "diameter": 3.4, "expr": "Params.hole_d", "name": "hole_d"}]}},
    {"op": "pocket", "name": "PocketPins", "plane": "YZ", "position": "Params.x_back", "length": "Params.pin_depth", "reversed": True,
     "profile": {"circles": [{"center": [Y0 - PIN_DY, HZ], "diameter": 2.2, "expr": "Params.pin_d", "name": "pin_d"},
                             {"center": [Y0 + PIN_DY, HZ], "diameter": 2.2, "expr": "Params.pin_d", "name": "pin_d2"}]}},
    {"op": "pocket", "name": "PocketCbore", "plane": "YZ", "position": "Params.x_back + Params.thickness",
     "length": "Params.cbore_depth",
     "profile": {"circles": [{"center": [Y0, HZ], "diameter": 5.6, "expr": "Params.cbore_d", "name": "cbore_d"}]}},
    {"op": "chamfer", "name": "ChamferHoles", "size": "Params.chamfer",
     "edges": {"curve": "Circle", "radius_max": 2.0, "center": [X0, None, None], "center_tol": 1e-3}},
]

built = rebuild.build_features(body="Body", doc=DOC, params=params, features=features)
compared = rebuild.compare_shapes(a=SRC_NAME, doc=SRC_DOC, b="Body", doc_b=DOC) if built["ok"] else None
_result = {
    "built": [(c["name"], c.get("dof"), c["status"], c.get("volume_after")) for c in built["data"]["created"]] if built["ok"] else built,
    "stopped_at": built["data"].get("stopped_at") if built["ok"] else None,
    "compare": {k: compared["data"].get(k) for k in ("volume_diff", "diff_pct", "verdict", "missing_in_b", "extra_in_b")} if compared and compared["ok"] else compared,
}
