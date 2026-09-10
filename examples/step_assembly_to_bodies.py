"""STEP으로 연 어셈블리(부품 = Part::Feature 덩어리)를 Body + Assembly 로 바꾼다. FreeCAD 안에서 exec.

결과: 부품마다 PartDesign::Body (BaseFeature = 원본 형상) → 원본은 못 고치지만 그 위에
Pocket·Hole 같은 피처를 파라메트릭으로 덧붙일 수 있다. 전부 접지(Grounded) 조인트로 지금 위치에 고정.
움직여야 할 부품은 나중에 JointObject.Joint(...)로 조인트를 붙인다 (docs/api-notes.md 11.5).

    SRC_DOC = "Unnamed"      # STEP을 연 문서
    OUT     = r"...\\clamp_assembly.FCStd"
"""
import os
import time

import FreeCAD
import JointObject

SRC_DOC = "Unnamed"
DOC = "clamp_assembly"
OUT = r"C:/path/to/clamp_assembly.FCStd"

t0 = time.time()
src = FreeCAD.getDocument(SRC_DOC)
if DOC in FreeCAD.listDocuments():
    FreeCAD.closeDocument(DOC)
d = FreeCAD.newDocument(DOC)

asm = d.addObject("Assembly::AssemblyObject", "Assembly")
asm.Label = "Assembly 1"
jg = d.addObject("Assembly::JointGroup", "Joints")
asm.addObject(jg)

bodies, errors = [], []
for o in src.Objects:
    if o.TypeId != "Part::Feature":
        continue
    try:
        pf = d.addObject("Part::Feature", "Base_" + o.Name)
        pf.Shape = o.Shape.copy()          # Placement가 같이 옮겨진다
        pf.Label = o.Label + " (원본 형상)"
        pf.Visibility = False
        body = d.addObject("PartDesign::Body", "Body_" + o.Name)
        body.BaseFeature = pf
        body.Placement = o.Placement       # Body는 BaseFeature의 Placement를 버린다 → 직접 준다
        body.Label = o.Label
        asm.addObject(body)
        bodies.append(body)
    except Exception as e:
        errors.append((o.Label, str(e)))
d.recompute()

for b in bodies:                           # 전부 지금 위치에 접지
    g = d.addObject("App::FeaturePython", "Ground_" + b.Name)
    JointObject.GroundedJoint(g, b)
    jg.addObject(g)
d.recompute()
solve = asm.solve()

# 검증: 원본과 위치·부피가 같은가
misplaced = []
for o in src.Objects:
    if o.TypeId != "Part::Feature":
        continue
    b = d.getObject("Body_" + o.Name)
    if (b.Shape.BoundBox.Center - o.Shape.BoundBox.Center).Length > 0.01:
        misplaced.append(o.Label)
vol_src = sum(o.Shape.Volume for o in src.Objects if o.TypeId == "Part::Feature")
vol_new = sum(b.Shape.Volume for b in bodies)

d.saveAs(OUT)
result = {
    "bodies": len(bodies), "errors": errors, "misplaced": misplaced, "solve": solve,
    "invalid": [o.Name for o in d.Objects if "Invalid" in o.State],
    "volume_src": round(vol_src, 2), "volume_new": round(vol_new, 2),
    "elapsed_s": round(time.time() - t0, 1), "saved": OUT, "size_mb": round(os.path.getsize(OUT) / 1e6, 2),
}
