"""20종 Body를 한 문서에 만들고 80개 인스턴스를 Link로 배치해 Assembly로 묶는다. execute_code에서 exec.

1) 각 빌더 스크립트를 '기록 모드'로 실행해 (params, features)만 모은다 (build_features를 가로챈다)
2) 한 문서(clamp_param)에 종류별 Body — 파라미터·피처 이름에 종류 접두사
3) 원본 80개 인스턴스마다 align_shapes(기준 인스턴스 → 인스턴스)로 Placement를 얻어 App::Link 배치. 거울상은 Part::Mirroring 본을 따로
4) Assembly::AssemblyObject + 접지 조인트, 인스턴스별 compare_shapes, check_interference
"""
import copy
import os
import re
import time

import FreeCAD
import JointObject
from CadXray.handlers import reload_handlers
reload_handlers()
from CadXray.handlers import rebuild, shape_features, util

SRC = "Unnamed"
DOC = "clamp_param"
EXAMPLES = "E:/claude/freecadMCP/examples"   # 저장소 위치에 맞게 바꾼다
SCRATCH = EXAMPLES
t_start = time.time()

# ---------------------------------------------------------------- 1. 빌더 스크립트를 기록 모드로 실행
recorded = {}   # doc_name → (params, features)
_real_build, _real_compare = rebuild.build_features, rebuild.compare_shapes


def _rec_build(body=None, doc=None, features=None, params=None, **kw):
    recorded[doc] = (dict(params or {}), copy.deepcopy(features))
    return {"ok": True, "data": {"created": [], "stopped_at": None, "invalid": [], "volume": 0, "valid": True, "faces": 0, "params_written": []}, "warnings": []}


def _rec_compare(**kw):
    import collections
    data = collections.defaultdict(lambda: None, {"missing_in_b": [], "extra_in_b": [], "verdict": "rec", "diff_pct": 0.0, "volume_diff": 0.0, "method": "rec"})
    return {"ok": True, "data": data, "warnings": []}


rebuild.build_features, rebuild.compare_shapes = _rec_build, _rec_compare
open_before = set(FreeCAD.listDocuments())
try:
    for path in (os.path.join(EXAMPLES, "rebuild_samples_with_tools.py"), os.path.join(SCRATCH, "rebuild_jaws_with_tools.py"),
                 os.path.join(SCRATCH, "rebuild_housings_with_tools.py"), os.path.join(SCRATCH, "rebuild_2b2_2c2_with_tools.py")):
        ns = {"__name__": "__rec__"}
        # 스크립트의 reload_handlers()는 가로채기를 되돌리므로 기록 모드에서는 뺀다
        exec(open(path, encoding="utf-8").read().replace("reload_handlers()", "pass"), ns, ns)
finally:
    rebuild.build_features, rebuild.compare_shapes = _real_build, _real_compare
    for n in set(FreeCAD.listDocuments()) - open_before:   # 기록 모드가 만든 빈 문서 정리
        FreeCAD.closeDocument(n)

# 종류 키 → (기록 문서명, 기준 인스턴스 Name, 제외할 피처 이름 접두사)
TYPES = {
    "spacerA": ("spacerA_tools", "Part__Feature038", ()),
    "collar": ("collar_tools", "Part__Feature041", ()),
    "Dcap": ("D_tools", "Part__Feature", ()),
    "endcap": ("endcap_tools", "Part__Feature013", ("ChamferBig2",)),
    "handleclamp": ("handle_tools", "Part__Feature025", ("FilletArm",)),
    "foot": ("foot_tools", "Part__Feature015", ()),
    "handle": ("handle_bar_tools", "Part__Feature053", ()),
    "j2C1": ("jaw_2C1", "Part__Feature012", ()),
    "j2B1": ("jaw_2B1", "Part__Feature037", ()),
    "j2A1": ("jaw_2A1", "Part__Feature006", ()),
    "j2A2": ("jaw_2A2", "Part__Feature043", ()),
    "holder2": ("jaw_2holder", "Part__Feature052", ()),
    "part1": ("jaw_Part1", "Part__Feature077", ()),
    "rod": ("rod_tools", "Part__Feature028", ()),
    "leadscrew": ("leadscrew_tools", "Part__Feature074", ()),
    "endbody": ("hs_end_body", "Part__Feature019", ()),
    "midbody": ("hs_middle_body", "Part__Feature001", ()),
    "midcap": ("hs_middle_cap", "Part__Feature002", ()),
    "j2B2": ("jaw_2B2", "Part__Feature004", ()),
    "j2C2": ("jaw_2C2", "Part__Feature003", ()),
}
missing_rec = [k for k, (rd, _, _) in TYPES.items() if rd not in recorded]
if missing_rec:
    raise RuntimeError(f"기록되지 않은 종류: {missing_rec} / 기록됨: {sorted(recorded)}")


def prefixed(key, params, feats):
    """파라미터 이름·수식·피처 이름에 종류 접두사를 붙인다 (한 문서에 Params 시트와 피처가 함께 있으므로)."""
    pre = key + "_"
    pmap = {k: pre + k for k in params}
    new_params = {pre + k: v for k, v in params.items()}

    def fix(v):
        if isinstance(v, str):
            return re.sub(r"Params\.([A-Za-z_][A-Za-z0-9_]*)", lambda m: "Params." + pmap.get(m.group(1), m.group(1)), v)
        if isinstance(v, dict):
            return {k: fix(x) for k, x in v.items()}
        if isinstance(v, list):
            return [fix(x) for x in v]
        return v

    out = []
    for f in feats:
        f2 = fix(copy.deepcopy(f))
        f2["name"] = pre + f2.get("name", "F")
        out.append(f2)
    return new_params, out


# ---------------------------------------------------------------- 2. 종류별 Body
if DOC in FreeCAD.listDocuments():
    FreeCAD.closeDocument(DOC)
d = FreeCAD.newDocument(DOC)
type_report = {}
for key, (rdoc, src_name, drop) in TYPES.items():
    params, feats = recorded[rdoc]
    feats = [f for f in feats if not any(f.get("name", "").startswith(dp) for dp in drop)]
    params, feats = prefixed(key, params, feats)
    r = rebuild.build_features(body="B_" + key, doc=DOC, params=params, features=feats, stop_on_error=True)
    rep = {"features": len(feats), "stopped_at": r["data"]["stopped_at"] if r["ok"] else r.get("error")}
    if r["ok"] and r["data"]["stopped_at"] is None:
        c = rebuild.compare_shapes(a=src_name, doc=SRC, b="B_" + key, doc_b=DOC)
        rep["verdict"] = c["data"]["verdict"]; rep["diff_pct"] = c["data"]["diff_pct"]
    type_report[key] = rep
    body = d.getObject("B_" + key)
    if body is not None:
        body.Label = key
d.recompute()

# ---------------------------------------------------------------- 3. 인스턴스 → Link
src_doc = FreeCAD.getDocument(SRC)
groups = {}
for o in src_doc.Objects:
    if o.TypeId != "Part::Feature" or o.Shape.isNull():
        continue
    s = o.Shape; bb = s.BoundBox
    sig = (len(s.Faces), round(s.Volume, 1), tuple(sorted(round(v, 1) for v in (bb.XLength, bb.YLength, bb.ZLength))))
    groups.setdefault(sig, []).append(o)
src_to_key = {src: key for key, (_, src, _) in TYPES.items()}

asm = d.addObject("Assembly::AssemblyObject", "Assembly")
asm.Label = "clamp_param"
jg = d.addObject("Assembly::JointGroup", "Joints")
asm.addObject(jg)
mirrors = {}
instances = []
for sig, objs in groups.items():
    ref = next((o for o in objs if o.Name in src_to_key), None)
    if ref is None:
        instances.append({"group": [o.Name for o in objs], "error": "기준 종류 없음"})
        continue
    key = src_to_key[ref.Name]
    body = d.getObject("B_" + key)
    for o in objs:
        al = rebuild.align_shapes(a=ref.Name, b=o.Name, doc=SRC)
        rec = {"instance": o.Name, "label": util.label(o), "type": key, "match_pct": al["data"]["match_pct"] if al["ok"] else None, "mirrored": al["data"].get("mirrored") if al["ok"] else None}
        if not al["ok"]:
            rec["error"] = al["error"]; instances.append(rec); continue
        target = body
        if al["data"]["mirrored"]:
            if key not in mirrors:
                m = d.addObject("Part::Mirroring", "M_" + key)
                m.Source = body
                m.Base = ref.Shape.CenterOfMass
                m.Normal = FreeCAD.Vector(0, 0, 1)
                m.Label = key + "_mirror"
                d.recompute()
                mirrors[key] = m
            target = mirrors[key]
            al = rebuild.align_shapes(a=target.Name, doc=DOC, b=o.Name, doc_b=SRC)
            rec["match_pct_mirror"] = al["data"]["match_pct"] if al["ok"] else None
            if not al["ok"] or al["data"]["mirrored"]:
                rec["error"] = "거울상 본 정렬 실패"; instances.append(rec); continue
        mtx = al["data"]["matrix"]
        link = d.addObject("App::Link", "L_" + o.Name)
        link.LinkedObject = target
        link.Placement = FreeCAD.Placement(FreeCAD.Matrix(*[v for row in mtx for v in row]))
        link.Label = util.label(o)
        asm.addObject(link)
        g = d.addObject("App::FeaturePython", "G_" + o.Name)
        JointObject.GroundedJoint(g, link)
        jg.addObject(g)
        rec["link"] = link.Name
        instances.append(rec)
for key in TYPES:
    b = d.getObject("B_" + key)
    if b is not None:
        b.Visibility = False
for m in mirrors.values():
    m.Visibility = False
d.recompute()
solve = asm.solve()

# ---------------------------------------------------------------- 4. 검증
verify = []
for rec in instances:
    if "link" not in rec:
        continue
    link = d.getObject(rec["link"])
    try:
        c = rebuild.compare_shapes(a=rec["instance"], doc=SRC, b=link.Name, doc_b=DOC)
        rec["verdict"] = c["data"]["verdict"]; rec["diff_pct"] = c["data"]["diff_pct"]
    except Exception as e:
        rec["verdict"] = f"error {e}"
    verify.append((rec["label"], rec["type"], rec.get("mirrored"), rec.get("verdict"), rec.get("diff_pct")))
inter = shape_features.check_interference(names=["Assembly"], doc=DOC, max_pairs=20)
_result = {
    "types": type_report,
    "instances_total": len(instances), "links": sum(1 for r in instances if "link" in r), "mirrors": sorted(mirrors),
    "errors": [r for r in instances if "error" in r],
    "verdicts": {v: sum(1 for x in verify if x[3] == v) for v in set(x[3] for x in verify)},
    "worst": sorted([x for x in verify if x[4] is not None], key=lambda x: -x[4])[:8],
    "solve": solve,
    "interference": {k: inter["data"].get(k) for k in ("pairs_total", "summary", "pairs_skipped_by_bbox")} if inter["ok"] else inter,
    "elapsed_s": round(time.time() - t_start, 1),
}
