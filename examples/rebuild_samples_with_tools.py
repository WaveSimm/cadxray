"""벤더 어셈블리의 형태가 다른 부품 3개를 M7 툴만으로 재구성한 기록. FreeCAD 안에서 exec.

    spacerA : 단차 판 — 레일 + 판, 아래에서 판 육각 너트 자리 2개, 위에서 카운터보어 2개, 관통 2개, 아래에서 막힌 구멍 2개
              (0.4 mm 희생층을 사이에 둔 3D 프린팅용 설계).  6피처, identical (부피 차 0.0)
    collar  : 분할 클램프 링 — YZ 단면 하나를 X로 8 mm 돌출(보어·슬릿·R10 필렛 포함) + 양쪽 귀에 육각 너트 채널 + Ø3.4 관통.
              4피처, match (0.0013 %)
    Part 25 : D형 캡 — 육각 자리·희생층·60° 원뿔 슬롯(동쪽 215°)·코어·30° 경사 절단·Ø3.4·바닥 0.5 챔퍼 15모서리.
              9피처, 부피 차 0.02 %

수치는 classify_faces(정체·반지름·레벨) / section_profile(position=None → 정점 z 히스토그램) / find_holes(구멍)에서 읽었다.
좌표는 벤더 STEP의 어셈블리 위치 그대로다(부품 Name은 get_document_graph로 확인).
"""
import math

import FreeCAD

from CadXray.handlers import rebuild

SRC_DOC = "Unnamed"


def hexagon(cx, cy, across_flats, first_angle_deg):
    """중심·A/F·첫 꼭짓점 각도로 육각형 6점. 플랫이 x축에 수직이면 30, y(z)축에 수직이면 0."""
    r = across_flats / math.sqrt(3)
    return [[cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a))]
            for a in range(first_angle_deg, first_angle_deg + 360, 60)]


def run(doc_name, src_name, params, features):
    if doc_name in FreeCAD.listDocuments():
        FreeCAD.closeDocument(doc_name)
    FreeCAD.newDocument(doc_name)
    built = rebuild.build_features(body="Body", doc=doc_name, params=params, features=features)
    if not built["ok"] or built["data"]["stopped_at"]:
        return {"built": built}
    cmp_ = rebuild.compare_shapes(a=src_name, doc=SRC_DOC, b="Body", doc_b=doc_name)
    return {"features": [(c["name"], c.get("dof"), c["status"]) for c in built["data"]["created"]],
            "compare": {k: cmp_["data"].get(k) for k in ("volume_diff", "diff_pct", "verdict", "method")}}


# ---------------------------------------------------------------- spacerA (Part__Feature038)
S = {"of": "Part__Feature038", "doc": SRC_DOC}
Z0, CY = 42.606053, -38.947276
spacer = run("spacerA_tools", "Part__Feature038",
    {"z0": Z0, "rail_h": 5.0, "base_h": 6.0, "hex_af": 5.6, "hex_depth": 3.0, "cbore_d": 5.6, "cbore_depth": 3.0, "hole_d": 3.4, "blind_depth": 2.6},
    [
        {"op": "pad", "name": "PadRail", "plane": "XY", "position": "Params.z0", "profile": {"section": dict(S, position=45.0)}, "length": "Params.rail_h"},
        {"op": "pad", "name": "PadBase", "plane": "XY", "position": "Params.z0 + Params.rail_h", "profile": {"section": dict(S, position=52.0)}, "length": "Params.base_h"},
        # 아랫면에서 위로(+Z) 파는 포켓: XY 스케치의 Pocket 기본 방향은 −Z → reversed
        {"op": "pocket", "name": "PocketHexTraps", "plane": "XY", "position": "Params.z0 + Params.rail_h", "reversed": True, "length": "Params.hex_depth",
         "profile": {"polygons": [hexagon(191.789155, CY, 5.6, 30), hexagon(209.068451, CY, 5.6, 30)]}},
        {"op": "pocket", "name": "PocketCbores", "plane": "XY", "position": "Params.z0 + Params.rail_h + Params.base_h", "length": "Params.cbore_depth",
         "profile": {"circles": [{"center": [168.509859, CY], "diameter": 5.6, "expr": "Params.cbore_d", "name": "cbore_d"},
                                 {"center": [185.789155, CY], "diameter": 5.6, "expr": "Params.cbore_d", "name": "cbore_d2"}]}},
        {"op": "pocket", "name": "PocketThrough", "plane": "XY", "position": "Params.z0 + Params.rail_h + Params.base_h", "through": True,
         "profile": {"circles": [{"center": [191.789155, CY], "diameter": 3.4, "expr": "Params.hole_d", "name": "hole_d"},
                                 {"center": [209.068451, CY], "diameter": 3.4, "expr": "Params.hole_d", "name": "hole_d2"}]}},
        {"op": "pocket", "name": "PocketBlind", "plane": "XY", "position": "Params.z0 + Params.rail_h", "reversed": True, "length": "Params.blind_depth",
         "profile": {"circles": [{"center": [168.509859, CY], "diameter": 3.4, "expr": "Params.hole_d", "name": "hole_d3"},
                                 {"center": [185.789155, CY], "diameter": 3.4, "expr": "Params.hole_d", "name": "hole_d4"}]}},
    ])

# ---------------------------------------------------------------- collar (Part__Feature041), 주축 X
C = {"of": "Part__Feature041", "doc": SRC_DOC}
HX, HZ = -38.210845, 24.18564          # 클램프 나사 축 (x, z)
collar = run("collar_tools", "Part__Feature041",
    {"x0": -42.210845, "width": 8.0, "hole_d": 3.4, "hex_af": 5.6, "y_bore": 10.052724, "y_ear1": 16.052724, "y_ear2": 4.052724},
    [
        # 너트 채널 x 범위(−41.44~−34.98) 밖인 x=−41.9에서 단면을 떠야 채널에 깎이지 않은 온전한 윤곽이 나온다
        {"op": "pad", "name": "PadProfile", "plane": "YZ", "position": "Params.x0", "profile": {"section": dict(C, position=-41.9)}, "length": "Params.width"},
        # XZ 스케치의 Pocket 기본 방향은 +Y. 귀 1은 y=16.05에서 바깥(+Y)으로, 귀 2는 y=4.05에서 바깥(−Y)으로 → reversed
        {"op": "pocket", "name": "NutChannel1", "plane": "XZ", "position": "Params.y_ear1", "through": True, "profile": {"polygon": hexagon(HX, HZ, 5.6, 0)}},
        {"op": "pocket", "name": "NutChannel2", "plane": "XZ", "position": "Params.y_ear2", "through": True, "reversed": True, "profile": {"polygon": hexagon(HX, HZ, 5.6, 0)}},
        {"op": "pocket", "name": "PocketScrew", "plane": "XZ", "position": "Params.y_bore", "through": True, "midplane": True,
         "profile": {"circles": [{"center": [HX, HZ], "diameter": 3.4, "expr": "Params.hole_d", "name": "hole_d"}]}},
    ])

# ---------------------------------------------------------------- Part 25 (Part__Feature), D형 캡
D = {"of": "Part__Feature", "doc": SRC_DOC}
src = FreeCAD.getDocument(SRC_DOC).getObject("Part__Feature").Shape


def z_at(approx):
    """정점 z 히스토그램(section_profile position=None)은 3자리라, 정확한 값은 정점에서 읽는다."""
    return sorted({round(v.Point.z, 6) for v in src.Vertexes if abs(v.Point.z - approx) < 0.003})[0]


Z0, TOP = 53.679659, 62.479659
Z_HEX, Z_FLOOR, Z_CONE0, Z_CONE1, Z_SLOPE = z_at(56.68), z_at(57.08), z_at(57.391), z_at(58.344), z_at(60.88)
AXX, AXY = 111.651784, -16.197276      # 회전 축 (R8.75·R7.1 원통 중심)
HX2, HY2 = 116.026784, -16.197276      # Ø3.4 구멍 = 육각 중심
RC, RS = 7.1, 8.75                     # 코어 반지름 / 스커트 바깥 반지름 (원뿔은 RC→RS, 반각 60°)


def y_on_slope(z):                      # 경사면: −0.5·y + 0.866025·z = 61.514789 (classify_faces의 normal·position)
    return (0.8660254 * z - 61.514789) / 0.5


slot = [[AXX + RC, Z_CONE0], [AXX + RS, Z_CONE1], [AXX + RC, Z_CONE1]]   # 슬롯은 +x(육각·구멍) 쪽 215°
part25 = run("D_tools", "Part__Feature",
    {"z0": Z0, "hex_depth": Z_HEX - Z0, "web_h": Z_CONE0 - Z_HEX, "skirt_h": Z_CONE1 - Z_CONE0, "core_h": TOP - Z_CONE1,
     "slot_angle": 107.4, "hole_d": 3.4, "hole_depth": TOP - Z_FLOOR, "chamfer": 0.5},
    [
        {"op": "pad", "name": "PadLower", "plane": "XY", "position": "Params.z0", "profile": {"section": dict(D, position=55.0)}, "length": "Params.hex_depth"},
        {"op": "pad", "name": "PadWeb", "plane": "XY", "position": Z_HEX, "profile": {"section": dict(D, position=56.9)}, "length": "Params.web_h"},
        {"op": "pad", "name": "PadSkirt", "plane": "XY", "position": Z_CONE0, "profile": {"section": dict(D, position=(Z_CONE0 + Z_CONE1) / 2, outer_only=True)}, "length": "Params.skirt_h"},
        {"op": "pad", "name": "PadCore", "plane": "XY", "position": Z_CONE1, "profile": {"section": dict(D, position=59.5)}, "length": "Params.core_h"},
        # 회전 절삭은 스케치 평면에서 한쪽으로만 쓸므로 양쪽 대칭은 reversed 하나 더
        {"op": "groove", "name": "GrooveSlotA", "plane": "XZ", "position": AXY, "axis": {"x": AXX}, "angle": "Params.slot_angle", "profile": {"polygon": slot}},
        {"op": "groove", "name": "GrooveSlotB", "plane": "XZ", "position": AXY, "axis": {"x": AXX}, "angle": "Params.slot_angle", "reversed": True, "profile": {"polygon": slot}},
        {"op": "pocket", "name": "PocketSlope", "plane": "YZ", "position": AXX, "through": True, "midplane": True,
         "profile": {"polygon": [[y_on_slope(Z_SLOPE), Z_SLOPE], [y_on_slope(TOP), TOP], [-30.0, TOP], [-30.0, Z_SLOPE]]}},
        {"op": "pocket", "name": "PocketHole", "plane": "XY", "position": TOP, "length": "Params.hole_depth",
         "profile": {"circles": [{"center": [HX2, HY2], "diameter": 3.4, "expr": "Params.hole_d", "name": "hole_d"}]}},
        # 바닥면 높이의 모서리 전부(바깥 윤곽 + 육각 구멍 + 로브) → 15개
        {"op": "chamfer", "name": "ChamferBottom", "size": "Params.chamfer", "edges": {"bbox": {"max": [None, None, Z0]}}},
    ])

_result = {"spacerA": spacer, "collar": collar, "part25": part25}
