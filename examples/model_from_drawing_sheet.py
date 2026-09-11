"""2D 도면(PDF/스캔 이미지) → 3D 모델 시험 기록. FreeCAD 위키 'Basic Part Design Tutorial'의 A3 도면 시트로.

입력: 등각 투상 한 장 + 치수 12개 (39·7·7·26·21·16.7·5·5·11·11·17·17). Claude가 그림을 읽고 아래 피처 4개로 옮겼다.
판독에서 갈렸던 것 두 가지와 결론:
  - 블록 높이 기준: 도면의 "21"은 블록 윗면~바닥, "16.7"은 블록 앞면 높이 → 블록 z 4.3~21. 튜토리얼 순서(노치 먼저 → 노치로
    낮아진 꼭짓점에 블록)를 따르면 저절로 그렇게 된다
  - 립 노치 위치: 끝단 모서리에서 11(블록 위까지 이어짐), 깊이 5. 처음엔 블록 안쪽에 두었다가 순서를 따져 고쳤다
  - 경사면 17×17 포켓은 튜토리얼처럼 뒷면 투영 사각형(17 × 13.2)을 −Y로 관통시킨다. 옆 7·위 11 오프셋은 경사 길이 기준
검증: 원본 STEP이 없으므로 결과 bbox 53×26×26, 스케치 4개 DoF 0, 스크린샷과 도면 시트 비교.
"""
import math

import FreeCAD

from freecad.cadxray.handlers import rebuild

DOC = "tutorial_drawing"
if DOC in FreeCAD.listDocuments():
    FreeCAD.closeDocument(DOC)
FreeCAD.newDocument(DOC)

L, D, H, LEDGE = 53.0, 26.0, 26.0, 5.0          # 길이(X), 깊이(Y), 뒤쪽 높이(Z), 위 턱 폭
BW, BH = 7.0, 16.7                              # 끝 블록 폭(X)·높이
NW, ND = 11.0, 5.0                              # 립 노치 폭(X)·깊이(Z), 끝단 모서리에서
BTOP = H - ND                                   # 블록 윗면 = 노치 바닥 (21)
P, POFF_SIDE, POFF_TOP = 17.0, 7.0, 11.0        # 경사면 포켓 17×17, 옆·위 오프셋(경사 길이 기준)
slant = math.hypot(D - LEDGE, H)
kz = H / slant                                  # 경사 길이 → z 투영
pz_top = H - POFF_TOP * kz
pz_bot = pz_top - P * kz
px1 = L / 2 - BW - POFF_SIDE
px0 = px1 - P

params = {"length": L, "depth": D, "height": H, "ledge": LEDGE, "block_w": BW, "block_h": BH, "notch_w": NW, "notch_d": ND, "pocket": P}
features = [
    # 1. 쐐기 프로파일(YZ 평면: 로컬 x=Y, y=Z)을 X로 ±26.5 돌출
    {"op": "pad", "name": "PadBase", "plane": "YZ", "position": 0.0, "midplane": True, "length": "Params.length",
     "profile": {"polygon": [[0.0, 0.0], [0.0, H], [-LEDGE, H], [-D, 0.0]]}},
    # 2. 뒷면(y=0)에서 −Y로 관통하는 립 노치 2개. XZ 스케치 Pocket 기본 방향은 +Y → reversed
    {"op": "pocket", "name": "PocketNotches", "plane": "XZ", "position": 0.0, "through": True, "reversed": True,
     "profile": {"polygons": [[[L / 2 - NW, H - ND], [L / 2, H - ND], [L / 2, H], [L / 2 - NW, H]],
                              [[-L / 2, H - ND], [-L / 2 + NW, H - ND], [-L / 2 + NW, H], [-L / 2, H]]]}},
    # 3. 끝 블록 2개: 뒷면에서 −Y로 26 (XZ Pad 기본 방향 = −Y)
    {"op": "pad", "name": "PadBlocks", "plane": "XZ", "position": 0.0, "length": "Params.depth",
     "profile": {"polygons": [[[L / 2 - BW, BTOP - BH], [L / 2, BTOP - BH], [L / 2, BTOP], [L / 2 - BW, BTOP]],
                              [[-L / 2, BTOP - BH], [-L / 2 + BW, BTOP - BH], [-L / 2 + BW, BTOP], [-L / 2, BTOP]]]}},
    # 4. 경사면 17×17 창: 뒷면 투영 사각형을 −Y로 관통
    {"op": "pocket", "name": "PocketWindow", "plane": "XZ", "position": 0.0, "through": True, "reversed": True,
     "profile": {"rect": {"center": [(px0 + px1) / 2, (pz_top + pz_bot) / 2], "width": P, "height": pz_top - pz_bot}}},
]
r = rebuild.build_features(body="Tutorial", doc=DOC, params=params, features=features)
body = FreeCAD.getDocument(DOC).getObject("Tutorial")
bb = body.Shape.BoundBox
_result = {"stopped_at": r["data"]["stopped_at"], "dof": [c.get("dof") for c in r["data"]["created"]],
           "bbox": [round(v, 3) for v in (bb.XMin, bb.XMax, bb.YMin, bb.YMax, bb.ZMin, bb.ZMax)], "volume": round(body.Shape.Volume, 2)}
