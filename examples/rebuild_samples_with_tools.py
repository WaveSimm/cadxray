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


# ================================================================ 샘플 4·5 (2026-09-10 추가)
# end cap : 하우징 엔드캡 — YZ 단면(10° 구배 옆면, 케이블 홈 3개, 립 챔퍼)을 X로 돌출 + 끝 립 3 mm + Ø22.1 구간 2개(회전 절삭 + 립 챔퍼)
#           + 아래에서 육각 너트 자리 8개 + 위에서 Ø3.4 8개.  8피처, match (0.005 %)
# handle clamp : collar와 같은 몸통 + 양쪽 팔(XZ 프로파일을 Y로 돌출 후 원통으로 다듬기) + 너트 채널 4 + 나사 2 + 피벗.
#           R2 블렌드(자유곡면 13개, 4.4 %)는 Fillet이 실패해 남김 → 8피처, 부피 차 0.14 %. 하이브리드가 필요한 경우.

def section_polygons(name, axis, position):
    """단면의 안쪽 육각 와이어 꼭짓점을 그대로 폴리곤으로 (너트 자리 위치·방향을 손으로 읽지 않아도 된다)."""
    s = rebuild.section_profile(name=name, doc=SRC_DOC, axis=axis, position=position, fill_holes=False)
    return [[e["start"] for e in w["elements"]] for w in s["data"]["wires"] if not w["outer"] and w["elements_total"] == 6]


E = {"of": "Part__Feature013", "doc": SRC_DOC}
EZ0, ETOP = 18.606053, 32.606053
EX0, EX1, EXL = -34.210845, 22.373798, -31.210845
EAY = 10.052724                         # 중앙 케이블 홈 축 (X 방향, z = 윗면)
hexes8 = section_polygons("Part__Feature013", "Z", 20.0)
centers8 = [[sum(p[0] for p in h) / 6, sum(p[1] for p in h) / 6] for h in hexes8]
endcap_feats = [
    {"op": "pad", "name": "PadLip", "plane": "YZ", "position": "Params.x0", "profile": {"section": dict(E, position=-33.0)}, "length": "Params.lip"},
    {"op": "pad", "name": "PadMain", "plane": "YZ", "position": EXL, "profile": {"section": dict(E, position=0.0)}, "length": "Params.length"},
]
for k, (xa, xb) in enumerate(((-31.210845, -22.210845), (10.373798, 19.373798)), 1):
    # Ø22.1 구간: 윗면 평면에 놓인 X 방향 축 둘레로 사각형을 360° 회전 절삭 → 반원 홈. 립 챔퍼는 X 방향 직선 모서리만 골라서
    endcap_feats.append({"op": "groove", "name": f"GrooveBig{k}", "plane": "XY", "position": ETOP, "axis": {"y": EAY}, "angle": 360.0,
                         "profile": {"polygon": [[xa, EAY], [xb, EAY], [xb, EAY + 11.05], [xa, EAY + 11.05]]}})
    endcap_feats.append({"op": "chamfer", "name": f"ChamferBig{k}", "size": "Params.lip_chamfer",
                         "edges": {"curve": "Line", "direction": [1, 0, 0], "length": xb - xa, "length_tol": 0.05,
                                   "bbox": {"min": [xa - 0.01, None, ETOP - 0.01], "max": [xb + 0.01, None, ETOP + 0.01]}}})
endcap_feats += [
    {"op": "pocket", "name": "PocketHexTraps", "plane": "XY", "position": "Params.z0", "reversed": True, "length": "Params.hex_depth", "profile": {"polygons": hexes8}},
    {"op": "pocket", "name": "PocketHoles", "plane": "XY", "position": "Params.top", "length": "Params.hole_depth",
     "profile": {"circles": [{"center": c, "diameter": 3.4, "expr": "Params.hole_d", "name": f"hole_d{i}"} for i, c in enumerate(centers8)]}},
]
endcap = run("endcap_tools", "Part__Feature013",
             {"x0": EX0, "lip": 3.0, "length": EX1 - EXL, "z0": EZ0, "top": ETOP, "hex_depth": 6.0, "hole_d": 3.4, "hole_depth": 7.6, "lip_chamfer": 0.5},
             endcap_feats)

Hc = {"of": "Part__Feature025", "doc": SRC_DOC}
HX0, HXB = 306.789155, 322.789155       # 몸통 x 범위 (팔은 그 뒤)
HAY, HAZ, HRO = 10.052724, 32.606053, 12.852074
hexes2 = section_polygons("Part__Feature025", "Y", 18.0)
centers2 = [[sum(p[0] for p in h) / 6, sum(p[1] for p in h) / 6] for h in hexes2]
handle = run("handle_tools", "Part__Feature025",
    {"x0": HX0, "body_len": HXB - HX0, "y_ear1": 16.052724, "y_ear2": 4.052724, "y_bore": HAY, "hole_d": 3.4,
     "arm_y1": 14.552724, "arm_y2": 5.552724, "arm_w": 8.36},
    [
        {"op": "pad", "name": "PadBody", "plane": "YZ", "position": "Params.x0", "profile": {"section": dict(Hc, position=307.0)}, "length": "Params.body_len"},
        # 팔 단면은 R2 블렌드 영역 밖(y=16 / y=4)에서, 몸통(x<322.789)은 clip으로 빼고, 뿌리 블렌드 1개는 꺾은선 근사
        {"op": "pad", "name": "PadArm1", "plane": "XZ", "position": "Params.arm_y1", "reversed": True, "length": "Params.arm_w",
         "profile": {"section": dict(Hc, position=16.0, outer_only=True, clip={"min": [HXB, None]}, approximate_bspline=True)}},
        {"op": "pad", "name": "PadArm2", "plane": "XZ", "position": "Params.arm_y2", "length": "Params.arm_w",
         "profile": {"section": dict(Hc, position=4.0, outer_only=True, clip={"min": [HXB, None]}, approximate_bspline=True)}},
        # 팔 바깥을 몸통 원통(R12.852)으로 다듬기: X축 둘레 회전 절삭, r > R
        {"op": "groove", "name": "GrooveTrim", "plane": "XY", "position": HAZ, "axis": {"y": HAY}, "angle": 360.0,
         "profile": {"polygon": [[HXB, HAY + HRO], [341.0, HAY + HRO], [341.0, HAY + 30.0], [HXB, HAY + 30.0]]}},
        {"op": "pocket", "name": "NutChannels1", "plane": "XZ", "position": "Params.y_ear1", "through": True, "profile": {"polygons": hexes2}},
        {"op": "pocket", "name": "NutChannels2", "plane": "XZ", "position": "Params.y_ear2", "through": True, "reversed": True, "profile": {"polygons": hexes2}},
        {"op": "pocket", "name": "PocketScrews", "plane": "XZ", "position": "Params.y_bore", "through": True, "midplane": True,
         "profile": {"circles": [{"center": c, "diameter": 3.4, "expr": "Params.hole_d", "name": f"screw_d{i}"} for i, c in enumerate(centers2)]}},
        {"op": "pocket", "name": "PocketPivot", "plane": "XZ", "position": "Params.y_bore", "through": True, "midplane": True,
         "profile": {"circles": [{"center": [332.789155, 32.545], "diameter": 3.4, "expr": "Params.hole_d", "name": "pivot_d"}]}},
        # R2 블렌드는 PartDesign Fillet이 실패한다(BRep_API: command not done) — 원본을 BaseFeature로 두는 하이브리드가 답
    ])

_result.update({"endcap": endcap, "handle": handle})


# ================================================================ 샘플 6·7 (2026-09-10 추가)
# foot   : 5° 구배 외벽 트레이 — 바닥 사각형 Pad(taper −5) + 사각 공동 Pocket + 로드 노치(R15 원통 0.8 + 45° 원뿔 플레어) 회전 절삭.
#          3피처, match (부피 차 0.003 %). 플레어는 진짜 자유곡면이라 classify_faces(tolerance=0.005)의 원뿔 판정으로 근사
# handle : 회전체 바(플랜지 R11·45° 챔퍼·R10) → 위아래 평면 포켓 → 납작한 탱(R7.5 끝) Pad → R5 필렛 → 피벗.  6피처, identical
F = {"of": "Part__Feature015", "doc": SRC_DOC}
FAY, FAZ = 10.052724, 32.679659                     # 로드 축 (X 방향)
FX0, FX1, FY0, FY1 = -38.523175, 26.686128, -53.259606, 73.365054   # 바닥 사각형 (classify_faces의 구배면 normal·position에서)
foot = run("foot_tools", "Part__Feature015",
    {"z0": 12.679659, "height": 15.0, "draft": -5.0, "cavity_depth": 10.0},
    [
        {"op": "pad", "name": "PadShell", "plane": "XY", "position": "Params.z0", "length": "Params.height", "taper": "Params.draft",
         "profile": {"rect": {"center": [(FX0 + FX1) / 2, (FY0 + FY1) / 2], "width": FX1 - FX0, "height": FY1 - FY0}}},
        {"op": "pocket", "name": "PocketCavity", "plane": "XY", "position": "Params.z0 + Params.height", "length": "Params.cavity_depth",
         "profile": {"rect": {"center": [(-34.210845 + 22.373798) / 2, (-45.947276 + 66.052724) / 2], "width": 22.373798 + 34.210845, "height": 66.052724 + 45.947276}}},
        {"op": "groove", "name": "GrooveNotch", "plane": "XY", "position": FAZ, "axis": {"y": FAY}, "angle": 360.0,
         "profile": {"polygon": [[-34.210845, FAY], [-34.210845, FAY + 15.0], [-35.010845, FAY + 15.0], [-39.5, FAY + 19.489155], [-39.5, FAY]]}},
    ])

BAY, BAZ = 10.052724, 32.545                        # 바 축 (X 방향)
BX0, BX1 = 344.789155, 394.789155                   # 플랜지 뒷면 ~ 끝
half = [[BX0, BAZ], [BX0, BAZ + 11.0], [BX0 + 1.5, BAZ + 11.0], [BX0 + 2.5, BAZ + 10.0], [BX1 - 2.5, BAZ + 10.0], [BX1 - 1.5, BAZ + 11.0], [BX1, BAZ + 11.0], [BX1, BAZ]]
tang = [{"type": "line", "start": [BX0, BAZ - 7.5], "end": [332.789155, BAZ - 7.5]},
        {"type": "arc", "center": [332.789155, BAZ], "radius": 7.5, "start": [332.789155, BAZ - 7.5], "end": [332.789155, BAZ + 7.5], "ccw": False},
        {"type": "line", "start": [332.789155, BAZ + 7.5], "end": [BX0, BAZ + 7.5]},
        {"type": "line", "start": [BX0, BAZ + 7.5], "end": [BX0, BAZ - 7.5]}]
handle_bar = run("handle_bar_tools", "Part__Feature053",
    {"axis_y": BAY, "tang_y0": 6.352724, "tang_t": 7.4, "pivot_d": 3.4, "fillet_r": 5.0},
    [
        # XZ 평면(y = 축 y)의 위쪽 반단면을 X 방향 축(로컬 y = z값) 둘레로 360°
        {"op": "revolution", "name": "RevBar", "plane": "XZ", "position": "Params.axis_y", "axis": {"y": BAZ}, "angle": 360.0, "profile": {"polygon": half}},
        {"op": "pocket", "name": "FlatTop", "plane": "XY", "position": BAZ + 7.5, "through": True, "reversed": True,
         "profile": {"rect": {"center": [(BX0 + BX1) / 2, BAY], "width": BX1 - BX0 + 2.0, "height": 30.0}}},
        {"op": "pocket", "name": "FlatBottom", "plane": "XY", "position": BAZ - 7.5, "through": True,
         "profile": {"rect": {"center": [(BX0 + BX1) / 2, BAY], "width": BX1 - BX0 + 2.0, "height": 30.0}}},
        {"op": "pad", "name": "PadTang", "plane": "XZ", "position": "Params.tang_y0", "reversed": True, "length": "Params.tang_t", "profile": {"elements": tang}},
        {"op": "fillet", "name": "FilletTang", "size": "Params.fillet_r",
         "edges": {"curve": "Line", "direction": [0, 0, 1], "bbox": {"min": [BX0 - 0.01, None, None], "max": [BX0 + 0.01, None, None]}}},
        {"op": "pocket", "name": "PocketPivot", "plane": "XZ", "position": "Params.axis_y", "through": True, "midplane": True,
         "profile": {"circles": [{"center": [332.789155, BAZ], "diameter": 3.4, "expr": "Params.pivot_d", "name": "pivot_d"}]}},
    ])

_result.update({"foot": foot, "handle_bar": handle_bar})
