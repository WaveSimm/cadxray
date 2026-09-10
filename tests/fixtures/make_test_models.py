"""테스트 모델 생성 (명세 10장). FreeCAD 안에서 실행한다.

    FreeCADCmd tests/fixtures/make_test_models.py          # 전부 만들고 요약 출력
    exec(open(r"...\\make_test_models.py").read())          # 실행 중인 FreeCAD에서
    build("T3_conflict")                                    # 하나만

문서는 메모리에만 만든다(저장하지 않는다). 같은 이름이 이미 열려 있으면 닫고 다시 만든다.
"""

import FreeCAD
import Part
import Sketcher

Vec = FreeCAD.Vector


# --- 공통 ---------------------------------------------------------------------


def _fresh(name):
    if name in FreeCAD.listDocuments():
        FreeCAD.closeDocument(name)
    return FreeCAD.newDocument(name)


def _line(sk, x1, y1, x2, y2):
    """선분 하나를 추가하고 인덱스를 돌려준다."""
    return sk.addGeometry(Part.LineSegment(Vec(x1, y1, 0), Vec(x2, y2, 0)), False)


def _rect(sk, w, h):
    """닫힌 사각형 4선분 + Coincident 4개. 인덱스 [0,1,2,3]."""
    a = _line(sk, 0, 0, w, 0)
    b = _line(sk, w, 0, w, h)
    c = _line(sk, w, h, 0, h)
    d = _line(sk, 0, h, 0, 0)
    for i, j in ((a, b), (b, c), (c, d), (d, a)):
        sk.addConstraint(Sketcher.Constraint("Coincident", i, 2, j, 1))
    return [a, b, c, d]


def _body_with_sketch(doc, sketch_name="Sketch"):
    body = doc.addObject("PartDesign::Body", "Body")
    sk = doc.addObject("Sketcher::SketchObject", sketch_name)
    body.addObject(sk)
    return body, sk


def _pad(doc, body, sk, length=10.0, name="Pad"):
    pad = doc.addObject("PartDesign::Pad", name)
    body.addObject(pad)
    pad.Profile = sk
    pad.Length = length
    return pad


# --- T1 완전 구속 + Pad + 구멍 Pocket ------------------------------------------


def T1_clean():
    doc = _fresh("T1_clean")
    body, sk = _body_with_sketch(doc)
    a, b, c, d = _rect(sk, 20.0, 12.0)
    sk.addConstraint(Sketcher.Constraint("Horizontal", a))
    sk.addConstraint(Sketcher.Constraint("Vertical", b))
    sk.addConstraint(Sketcher.Constraint("Horizontal", c))
    sk.addConstraint(Sketcher.Constraint("Vertical", d))
    sk.addConstraint(Sketcher.Constraint("DistanceX", a, 1, a, 2, 20.0))
    sk.addConstraint(Sketcher.Constraint("DistanceY", b, 1, b, 2, 12.0))
    sk.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, a, 1, 0.0))
    sk.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, a, 1, 0.0))
    pad = _pad(doc, body, sk, 10.0)

    # 관통 구멍
    sk2 = doc.addObject("Sketcher::SketchObject", "SketchHole")
    body.addObject(sk2)
    i = sk2.addGeometry(Part.Circle(Vec(10, 6, 0), Vec(0, 0, 1), 3.0), False)
    sk2.addConstraint(Sketcher.Constraint("Radius", i, 3.0))
    sk2.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, i, 3, 10.0))
    sk2.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, i, 3, 6.0))
    pocket = doc.addObject("PartDesign::Pocket", "Pocket")
    body.addObject(pocket)
    pocket.Profile = sk2
    pocket.Type = 1  # ThroughAll
    # 스케치가 z=0(XY 평면)에 있고 Pad는 +Z로 올라간다. Pocket은 기본적으로
    # 스케치 법선 반대(-Z)로 파므로 아무것도 안 깎인다 → 뒤집어서 +Z로 관통시킨다.
    pocket.Reversed = True
    doc.recompute()
    return doc


# --- T2 제약이 모자란 스케치 ----------------------------------------------------


def T2_underconstrained():
    doc = _fresh("T2_underconstrained")
    body, sk = _body_with_sketch(doc)
    a, b, c, d = _rect(sk, 20.0, 12.0)
    sk.addConstraint(Sketcher.Constraint("Horizontal", a))
    sk.addConstraint(Sketcher.Constraint("Vertical", b))
    sk.addConstraint(Sketcher.Constraint("Horizontal", c))
    sk.addConstraint(Sketcher.Constraint("Vertical", d))
    # 치수 2개와 원점 고정을 일부러 넣지 않는다 → DoF가 남는다
    sk.addConstraint(Sketcher.Constraint("DistanceX", a, 1, a, 2, 20.0))
    _pad(doc, body, sk, 10.0)
    doc.recompute()
    return doc


# --- T3 충돌 제약 ---------------------------------------------------------------


def T3_conflict():
    doc = _fresh("T3_conflict")
    body, sk = _body_with_sketch(doc)
    a, b, c, d = _rect(sk, 20.0, 12.0)
    sk.addConstraint(Sketcher.Constraint("Horizontal", a))
    sk.addConstraint(Sketcher.Constraint("Vertical", b))
    sk.addConstraint(Sketcher.Constraint("Horizontal", c))
    sk.addConstraint(Sketcher.Constraint("Vertical", d))
    sk.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, a, 1, 0.0))
    sk.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, a, 1, 0.0))
    sk.addConstraint(Sketcher.Constraint("DistanceY", b, 1, b, 2, 12.0))
    # 같은 선에 값이 다른 길이 제약 두 개 → conflicting
    sk.addConstraint(Sketcher.Constraint("DistanceX", a, 1, a, 2, 20.0))
    sk.addConstraint(Sketcher.Constraint("DistanceX", a, 1, a, 2, 25.0))
    _pad(doc, body, sk, 10.0)
    doc.recompute()
    return doc


# --- T4 열린 와이어 -------------------------------------------------------------


def T4_open_wire():
    doc = _fresh("T4_open_wire")
    body, sk = _body_with_sketch(doc)
    a = _line(sk, 0, 0, 20, 0)
    b = _line(sk, 20, 0, 20, 12)
    c = _line(sk, 20, 12, 0, 12)
    d = _line(sk, 0, 12, 0, 2)  # (0,0)까지 닿지 않는다 → 열린 와이어
    for i, j in ((a, b), (b, c), (c, d)):
        sk.addConstraint(Sketcher.Constraint("Coincident", i, 2, j, 1))
    # d의 끝점과 a의 시작점은 일부러 잇지 않는다
    _pad(doc, body, sk, 10.0)
    doc.recompute()
    return doc


# --- T5 큰 문서 -----------------------------------------------------------------


def T5_large(count=320):
    doc = _fresh("T5_large")
    for i in range(count):
        box = doc.addObject("Part::Box", "Box%d" % i)
        box.Length, box.Width, box.Height = 10, 10, 10
        box.Placement.Base = Vec((i % 20) * 15, (i // 20) * 15, 0)
    doc.recompute()
    return doc


# --- T6 STEP 왕복 ---------------------------------------------------------------

STEP_PATHS = {}  # 문서 이름 → 내보낸 STEP 파일 경로 (테스트가 import_step에 쓴다)


def T6_step():
    """T1 블록 + Ø6.6 구멍 4개 판 + 일부러 겹친 블록 2개를 STEP으로 내보냈다가 다시 연다.

    결과 문서에는 히스토리(스케치·피처)가 없다. 기대값:
    find_holes(Plate) → Ø6.6 × 4, 피치 [40, 80]  /  check_interference(BlockA, BlockB) → 4000 mm³
    """
    import os
    import tempfile

    import Import

    src = _fresh("T6_src")
    # T1과 같은 형상(20×12×10 블록 + Ø6 관통 구멍)을 히스토리 없이 직접 만든다.
    # T1_clean()을 불러 쓰면 그 문서를 닫아야 해서 다른 테스트가 깨진다.
    block = src.addObject("Part::Feature", "Block")
    block.Label = "Block"
    block.Shape = Part.makeBox(20, 12, 10).cut(Part.makeCylinder(3, 10, Vec(10, 6, 0)))

    plate_shape = Part.makeBox(100, 60, 8)
    for x, y in ((10, 10), (90, 10), (10, 50), (90, 50)):
        plate_shape = plate_shape.cut(Part.makeCylinder(3.3, 8, Vec(x, y, 0)))
    # 20×20 각창 + 안쪽 모서리 R2 → 오목 원통면 4개가 '구멍'이 아니라 필렛으로 분류돼야 한다
    plate_shape = plate_shape.cut(Part.makeBox(20, 20, 8, Vec(40, 20, 0)))
    corner_edges = [
        e for e in plate_shape.Edges
        if type(e.Curve).__name__ == "Line"
        and abs(e.Vertexes[0].Point.x - e.Vertexes[1].Point.x) < 1e-6
        and abs(e.Vertexes[0].Point.y - e.Vertexes[1].Point.y) < 1e-6
        and round(e.Vertexes[0].Point.x) in (40, 60) and round(e.Vertexes[0].Point.y) in (20, 40)
    ]
    plate_shape = plate_shape.makeFillet(2.0, corner_edges)
    # 위 벽 양쪽에서 Ø4 자리파기 1 mm씩 (같은 축, 떨어져 있음 → 구멍 2개로 세야 한다)
    for y0, sign in ((60.0, -1), (0.0, 1)):
        plate_shape = plate_shape.cut(Part.makeCylinder(2.0, 1.0, Vec(75, y0, 4), Vec(0, sign, 0)))
    # M3 접시머리 자리: Ø3.4 관통 + 윗면에 90° 카운터싱크(입구 Ø6.5, 깊이 1.55)
    plate_shape = plate_shape.cut(Part.makeCylinder(1.7, 8, Vec(75, 45, 0)))
    plate_shape = plate_shape.cut(Part.makeCone(1.7, 3.25, 1.55, Vec(75, 45, 6.45), Vec(0, 0, 1)))
    # M3 카운터보어: Ø3.4 관통 + 윗면에서 Ø5.6 깊이 3
    plate_shape = plate_shape.cut(Part.makeCylinder(1.7, 8, Vec(25, 45, 0)))
    plate_shape = plate_shape.cut(Part.makeCylinder(2.8, 3, Vec(25, 45, 5)))
    plate = src.addObject("Part::Feature", "Plate")
    plate.Label = "Plate"
    plate.Shape = plate_shape

    a = src.addObject("Part::Feature", "BlockA")
    a.Label = "BlockA"
    a.Shape = Part.makeBox(20, 20, 20, Vec(0, 0, 30))
    b = src.addObject("Part::Feature", "BlockB")
    b.Label = "BlockB"
    b.Shape = Part.makeBox(20, 20, 20, Vec(10, 0, 30))  # X로 10 겹침 → 10×20×20 = 4000
    src.recompute()

    path = os.path.join(tempfile.mkdtemp(prefix="fcdiag_"), "T6_step.step")
    Import.export([block, plate, a, b], path)
    FreeCAD.closeDocument("T6_src")

    # Import.open은 문서 이름을 "Unnamed"로 만든다 [라이브 1.1.3] → 이름을 정하려고 insert를 쓴다.
    # 결과는 App::Part("T6_src") 안에 Part::Feature 4개 (Name은 Part__Feature…, Label이 원래 이름).
    doc = _fresh("T6_step")
    Import.insert(path, doc.Name)
    doc.recompute()
    STEP_PATHS["T6_step"] = path
    return doc


BUILDERS = {
    "T1_clean": T1_clean,
    "T2_underconstrained": T2_underconstrained,
    "T3_conflict": T3_conflict,
    "T4_open_wire": T4_open_wire,
    "T5_large": T5_large,
    "T6_step": T6_step,
}


def build(name):
    return BUILDERS[name]()


def build_all(names=None):
    """문서를 만들고 이름별 요약을 돌려준다."""
    out = {}
    for name in names or list(BUILDERS):
        doc = BUILDERS[name]()
        invalid = [o.Name for o in doc.Objects if "Invalid" in o.State]
        out[name] = {"objects": len(doc.Objects), "invalid": invalid}
    return out


def close_all():
    for name in list(BUILDERS):
        if name in FreeCAD.listDocuments():
            FreeCAD.closeDocument(name)


if __name__ == "__main__":
    import json

    print(json.dumps(build_all(), ensure_ascii=False, indent=2))
