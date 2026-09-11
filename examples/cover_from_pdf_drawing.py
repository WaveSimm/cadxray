"""PDF 2D 도면(커버가공_수치.pdf, 1:1 벡터) → 커버 판 2장. FreeCAD 안에서 exec.

읽는 법: pymupdf로 page.get_drawings()의 원(4-curve 경로)·사각형('re')과 get_text("words")의 치수 글자를 뽑는다.
1 pt = 25.4/72 mm 로 환산했더니 치수 글자(36.38)와 원 중심 거리(103.1 pt)가 맞아 1:1 축척으로 확인.
- 바깥 사각형 224.28×169.37 = 커버 판, 안쪽 사각형 206.70×151.82 = 치수 기준(각 변 8.79 안쪽). 판 두께는 도면에 없어 3 mm 가정
- 안테나 구멍(Ø7×4)의 높이 114.98은 치수가 없어 벡터에서 측정
- 도면 2(센서 확장 로거)는 적힌 치수(27.40 / 23.80)와 그려진 원 위치(27.80 / 26.0)가 0.4·2.2 mm 어긋난다. 적힌 치수를 따랐다
- 커넥터 플랜지 사각형과 그 안의 작은 구멍 4개는 치수가 없어(커넥터 외형 참고선) 가공하지 않았다
"""
import FreeCAD
from freecad.cadxray.handlers import rebuild

PW, PH, INS, T = 224.28, 169.37, 8.79, 3.0
def P(x, y): return [round(INS + x, 3), round(INS + y, 3)]

# 도면 1: DATA LOGGER
x18 = [27.40, 27.40 + 36.38, 27.40 + 2 * 36.38, 27.40 + 3 * 36.38]      # 27.40 63.78 100.16 136.54
x25 = x18[-1] + 40.35                                                    # 176.89
ant = [120.40, 138.10, 165.30, 183.00]                                   # 206.70-23.70=183.00 ← 17.70/27.20/17.70 역산
logger = {
    "d18": [P(x, y) for y in (23.80, 23.80 + 50.40) for x in x18],
    "d25": [P(x25, 24.10), P(x25, 24.10 + 50.50)],
    "d7": [P(x, 114.98) for x in ant],                                    # Y는 도면에 치수 없음 → 벡터에서 측정
}
# 도면 2: 센서 확장 로거 (적힌 치수대로)
x2 = [27.40, 27.40 + 37.72]
for _ in range(3): x2.append(x2[-1] + 37.80)                              # 27.40 65.12 102.92 140.72 178.52
sensor = {"d18": [P(x, y) for y in (23.80, 23.80 + 50.50) for x in x2]}

results = {}
for doc, body, holes in (("cover_logger", "Cover_DataLogger", logger), ("cover_sensor", "Cover_SensorExt", sensor)):
    if doc in FreeCAD.listDocuments():
        FreeCAD.closeDocument(doc)
    FreeCAD.newDocument(doc)
    feats = [{"op": "pad", "name": "PadPlate", "plane": "XY", "position": 0.0, "length": "Params.thickness",
              "profile": {"rect": {"center": [PW / 2, PH / 2], "width": PW, "height": PH}}}]
    for key, d, pname in (("d18", 18.0, "hole_d18"), ("d25", 25.0, "hole_d25"), ("d7", 7.0, "hole_d7")):
        if key in holes:
            feats.append({"op": "pocket", "name": "Pocket_" + key.upper(), "plane": "XY", "position": T, "through": True,
                          "profile": {"circles": [{"center": c, "diameter": d, "expr": "Params." + pname, "name": f"{pname}_{i}"} for i, c in enumerate(holes[key])]}})
    params = {"plate_w": PW, "plate_h": PH, "inset": INS, "thickness": T, "hole_d18": 18.0}
    if "d25" in holes: params.update(hole_d25=25.0, hole_d7=7.0)
    r = rebuild.build_features(body=body, doc=doc, params=params, features=feats)
    b = FreeCAD.getDocument(doc).getObject(body)
    bb = b.Shape.BoundBox
    results[doc] = {"ok": r["ok"], "stopped_at": r["data"].get("stopped_at") if r["ok"] else r.get("error"),
                    "created": [(c["name"], c.get("dof"), c["status"][:40], round(c.get("volume_after") or 0, 1)) for c in r["data"]["created"]] if r["ok"] else None,
                    "faces": len(b.Shape.Faces), "valid": b.Shape.isValid(),
                    "bbox": [round(v, 2) for v in (bb.XMin, bb.XMax, bb.YMin, bb.YMax, bb.ZMin, bb.ZMax)]}
_result = results
