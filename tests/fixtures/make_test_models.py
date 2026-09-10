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


BUILDERS = {
    "T1_clean": T1_clean,
    "T2_underconstrained": T2_underconstrained,
    "T3_conflict": T3_conflict,
    "T4_open_wire": T4_open_wire,
    "T5_large": T5_large,
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
