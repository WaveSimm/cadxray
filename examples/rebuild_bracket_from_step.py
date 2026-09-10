"""월파 브라켓 파라메트릭 재구성 — STEP 면 측정값 기반. FreeCAD 안에서 exec한다.

Spreadsheet 'Params'의 값을 바꾸면 전체가 따라 바뀐다.
"""
import FreeCAD
import Part
import Sketcher

V = FreeCAD.Vector
DOC = "bracket_param"
if DOC in FreeCAD.listDocuments():
    FreeCAD.closeDocument(DOC)
doc = FreeCAD.newDocument(DOC)
log = []

# ---------------------------------------------------------------- 파라미터
P = doc.addObject("Spreadsheet::Sheet", "Params")
PARAMS = [
    ("plate_size", 100), ("plate_t", 3), ("plate_r", 5),
    ("center_d", 20), ("bolt_d", 10), ("pcd", 66),
    ("tube_w", 40), ("tube_h", 50), ("tube_r", 2.5), ("wall", 2), ("inner_r", 1),
    ("side_d", 10), ("side_z", 20), ("y_hole_depth", 2), ("x_recess", 1),
]
for row, (k, v) in enumerate(PARAMS, start=1):
    P.set(f"A{row}", k)
    P.set(f"B{row}", str(v))
    P.setAlias(f"B{row}", k)
doc.recompute()

body = doc.addObject("PartDesign::Body", "Body")
body.Label = "월파브라켓"
doc.recompute()


def plane(role):
    for o in body.Origin.OriginFeatures:
        if o.Role == role:
            return o
    raise RuntimeError(role)


def sketch(name, role, offset_expr=None):
    sk = doc.addObject("Sketcher::SketchObject", name)
    body.addObject(sk)
    sk.AttachmentSupport = [(plane(role), "")]
    sk.MapMode = "FlatFace"
    if offset_expr:
        sk.setExpression(".AttachmentOffset.Base.z", offset_expr)
    return sk


def rect(sk, w, h, wname, hname, w_expr, h_expr):
    """원점 대칭 사각형. 이름 붙인 치수 제약에 수식을 건다."""
    a = sk.addGeometry(Part.LineSegment(V(-w / 2, -h / 2, 0), V(w / 2, -h / 2, 0)), False)
    b = sk.addGeometry(Part.LineSegment(V(w / 2, -h / 2, 0), V(w / 2, h / 2, 0)), False)
    c = sk.addGeometry(Part.LineSegment(V(w / 2, h / 2, 0), V(-w / 2, h / 2, 0)), False)
    d = sk.addGeometry(Part.LineSegment(V(-w / 2, h / 2, 0), V(-w / 2, -h / 2, 0)), False)
    for i, j in ((a, b), (b, c), (c, d), (d, a)):
        sk.addConstraint(Sketcher.Constraint("Coincident", i, 2, j, 1))
    sk.addConstraint(Sketcher.Constraint("Horizontal", a))
    sk.addConstraint(Sketcher.Constraint("Horizontal", c))
    sk.addConstraint(Sketcher.Constraint("Vertical", b))
    sk.addConstraint(Sketcher.Constraint("Vertical", d))
    sk.addConstraint(Sketcher.Constraint("Symmetric", a, 1, b, 2, -1, 1))
    iw = sk.addConstraint(Sketcher.Constraint("DistanceX", a, 1, a, 2, w))
    sk.renameConstraint(iw, wname)
    ih = sk.addConstraint(Sketcher.Constraint("DistanceY", b, 1, b, 2, h))
    sk.renameConstraint(ih, hname)
    sk.setExpression(f"Constraints.{wname}", w_expr)
    sk.setExpression(f"Constraints.{hname}", h_expr)


def circle_at_origin(sk, d, dname, d_expr):
    c = sk.addGeometry(Part.Circle(V(0, 0, 0), V(0, 0, 1), d / 2), False)
    sk.addConstraint(Sketcher.Constraint("Coincident", c, 3, -1, 1))
    i = sk.addConstraint(Sketcher.Constraint("Diameter", c, d))
    sk.renameConstraint(i, dname)
    sk.setExpression(f"Constraints.{dname}", d_expr)
    return c


def vertical_edges(shape, ax, ay, zmin, zmax, tol=1e-3):
    out = []
    for i, e in enumerate(shape.Edges, 1):
        if type(e.Curve).__name__ != "Line":
            continue
        p0, p1 = e.Vertexes[0].Point, e.Vertexes[-1].Point
        if abs(p0.x - p1.x) > tol or abs(p0.y - p1.y) > tol:
            continue
        if abs(abs(p0.x) - ax) > tol or abs(abs(p0.y) - ay) > tol:
            continue
        lo, hi = sorted((p0.z, p1.z))
        if abs(lo - zmin) > tol or abs(hi - zmax) > tol:
            continue
        out.append(f"Edge{i}")
    return out


def feature(type_id, name, profile=None, **props):
    f = doc.addObject(type_id, name)
    body.addObject(f)
    if profile is not None:
        f.Profile = profile
    for k, v in props.items():
        setattr(f, k, v)
    return f


def fillet(name, base, edges, r_expr):
    f = doc.addObject("PartDesign::Fillet", name)
    body.addObject(f)
    f.Base = (base, edges)
    f.setExpression("Radius", r_expr)
    return f


def step(name):
    doc.recompute()
    bad = [o.Name + ": " + o.getStatusString() for o in doc.Objects if "Invalid" in o.State]
    log.append({"step": name, "tip": body.Tip.Name, "invalid": bad,
                "volume": round(body.Shape.Volume, 3) if not body.Shape.isNull() else None})
    if bad:
        raise RuntimeError(f"{name}: {bad}")


# ---------------------------------------------------------------- 1. 판
sk_plate = sketch("SketchPlate", "XY_Plane")
rect(sk_plate, 100, 100, "size_x", "size_y", "Params.plate_size", "Params.plate_size")
pad_plate = feature("PartDesign::Pad", "PadPlate", sk_plate)
pad_plate.setExpression("Length", "Params.plate_t")
step("PadPlate")
fil_plate = fillet("FilletPlate", pad_plate, vertical_edges(pad_plate.Shape, 50, 50, 0, 3), "Params.plate_r")
step("FilletPlate")

# 2. 판 구멍 (판 윗면에서 아래로 관통)
sk_holes = sketch("SketchPlateHoles", "XY_Plane", "Params.plate_t")
circle_at_origin(sk_holes, 20, "center_d", "Params.center_d")
bolts = []
for sx, sy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
    c = sk_holes.addGeometry(Part.Circle(V(33 * sx, 33 * sy, 0), V(0, 0, 1), 5), False)
    bolts.append(c)
    if sx:
        sk_holes.addConstraint(Sketcher.Constraint("PointOnObject", c, 3, -1))
        if sx > 0:
            i = sk_holes.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, c, 3, 33))
        else:
            i = sk_holes.addConstraint(Sketcher.Constraint("DistanceX", c, 3, -1, 1, 33))
    else:
        sk_holes.addConstraint(Sketcher.Constraint("PointOnObject", c, 3, -2))
        if sy > 0:
            i = sk_holes.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, c, 3, 33))
        else:
            i = sk_holes.addConstraint(Sketcher.Constraint("DistanceY", c, 3, -1, 1, 33))
    sk_holes.setExpression(f"Constraints[{i}]", "Params.pcd / 2")
i = sk_holes.addConstraint(Sketcher.Constraint("Diameter", bolts[0], 10))
sk_holes.renameConstraint(i, "bolt_d")
sk_holes.setExpression("Constraints.bolt_d", "Params.bolt_d")
for c in bolts[1:]:
    sk_holes.addConstraint(Sketcher.Constraint("Equal", bolts[0], c))
pk_holes = feature("PartDesign::Pocket", "PocketPlateHoles", sk_holes, Type="ThroughAll")
step("PocketPlateHoles")

# 3. 각기둥
sk_tube = sketch("SketchTube", "XY_Plane", "Params.plate_t")
rect(sk_tube, 40, 40, "tube_w", "tube_h_", "Params.tube_w", "Params.tube_w")
pad_tube = feature("PartDesign::Pad", "PadTube", sk_tube)
pad_tube.setExpression("Length", "Params.tube_h")
step("PadTube")
fil_tube = fillet("FilletTube", pad_tube, vertical_edges(pad_tube.Shape, 20, 20, 3, 53), "Params.tube_r")
step("FilletTube")

# 4. 내부 공동 (위에서 아래로, 판 윗면까지)
sk_cav = sketch("SketchCavity", "XY_Plane", "Params.plate_t + Params.tube_h")
rect(sk_cav, 36, 36, "inner_w", "inner_h", "Params.tube_w - 2 * Params.wall", "Params.tube_w - 2 * Params.wall")
pk_cav = feature("PartDesign::Pocket", "PocketCavity", sk_cav)
pk_cav.setExpression("Length", "Params.tube_h")
step("PocketCavity")
fil_cav = fillet("FilletCavity", pk_cav, vertical_edges(pk_cav.Shape, 18, 18, 3, 53), "Params.inner_r")
step("FilletCavity")

# 5. -Y 벽 Ø10 관통 (XZ 평면 법선은 -Y → 오프셋 +tube_w/2 가 y=-20)
sk_y = sketch("SketchSideY", "XZ_Plane", "Params.tube_w / 2")
cy = sk_y.addGeometry(Part.Circle(V(0, 20, 0), V(0, 0, 1), 5), False)
sk_y.addConstraint(Sketcher.Constraint("PointOnObject", cy, 3, -2))
i = sk_y.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, cy, 3, 20))
sk_y.renameConstraint(i, "side_z")
sk_y.setExpression("Constraints.side_z", "Params.side_z")
i = sk_y.addConstraint(Sketcher.Constraint("Diameter", cy, 10))
sk_y.renameConstraint(i, "side_d")
sk_y.setExpression("Constraints.side_d", "Params.side_d")
pk_y = feature("PartDesign::Pocket", "PocketSideY", sk_y)
pk_y.setExpression("Length", "Params.y_hole_depth")
step("PocketSideY")

# 6. ±X 벽 Ø10 자리파기 1 mm (YZ 평면 법선 +X)
for tag, off_expr, reversed_ in (("Xp", "Params.tube_w / 2", False), ("Xn", "-Params.tube_w / 2", True)):
    sk_x = sketch("SketchSide" + tag, "YZ_Plane", off_expr)
    cx = sk_x.addGeometry(Part.Circle(V(0, 20, 0), V(0, 0, 1), 5), False)
    sk_x.addConstraint(Sketcher.Constraint("PointOnObject", cx, 3, -2))
    i = sk_x.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, cx, 3, 20))
    sk_x.renameConstraint(i, "side_z")
    sk_x.setExpression("Constraints.side_z", "Params.side_z")
    i = sk_x.addConstraint(Sketcher.Constraint("Diameter", cx, 10))
    sk_x.renameConstraint(i, "side_d")
    sk_x.setExpression("Constraints.side_d", "Params.side_d")
    pk_x = feature("PartDesign::Pocket", "PocketSide" + tag, sk_x, Reversed=reversed_)
    pk_x.setExpression("Length", "Params.x_recess")
    step("PocketSide" + tag)

# ---------------------------------------------------------------- 검증
for o in doc.Objects:
    if o.TypeId == "Sketcher::SketchObject":
        o.Visibility = False
doc.recompute()
new = body.Shape
result = {"document": DOC, "steps": log, "volume": round(new.Volume, 4),
          "faces": len(new.Faces), "valid": new.isValid()}

orig = None
for dn, d in FreeCAD.listDocuments().items():
    for o in d.Objects:
        if "be0cb77ccf13" in o.Label or "월파" in o.Label:
            orig = o.Shape
            result["original"] = f"{dn}.{o.Name}"
if orig is not None:
    result["original_volume"] = round(orig.Volume, 4)
    result["missing_from_new"] = round(orig.cut(new).Volume, 4)   # 원본엔 있는데 새 모델엔 없는 부피
    result["extra_in_new"] = round(new.cut(orig).Volume, 4)       # 새 모델에만 있는 부피
    result["original_faces"] = len(orig.Faces)
_result = result
