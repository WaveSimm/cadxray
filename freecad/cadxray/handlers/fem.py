"""FEM 구조 해석 툴 (M13, 명세 7.36~7.39).

setup_analysis      — 해석 컨테이너·재질·고정·하중·Gmsh 메시·CalculiX 솔버를 한 번에
run_analysis        — CalculiX 정적 해석 → 최대 응력·변위·안전율, 결과 컬러맵(후처리 파이프라인) 표시
inspect_results     — 응력·변위 상위 지점과 면별 요약, 컬러맵 필드 전환
suggest_reinforcement — 안전율 미달이면 두께·필렛·리브·재질·하중 후보를 번호 목록으로 (자동 적용 없음)

FreeCAD 1.1.3 라이브 확인 사항은 docs/api-notes.md §18. 선형 정적·등방성만 다룬다.
"""

import math
import os
import re
import tempfile
import time

import FreeCAD
import Part
from FreeCAD import Vector as Vec

from . import util

# 탄성계수 E(MPa)·푸아송비·밀도(g/cm³)·항복강도(MPa). 경험값 — 3D 프린트 재질은 출력물 기준으로 낮춰 잡았다.
FEM_MATERIALS = {
    "PLA": {"E": 3500.0, "nu": 0.36, "density": 1.24, "yield": 45.0, "note": "FDM 출력물 기준(층 방향은 더 약함)"},
    "PETG": {"E": 2000.0, "nu": 0.38, "density": 1.27, "yield": 45.0, "note": "FDM 출력물 기준"},
    "ABS": {"E": 2000.0, "nu": 0.35, "density": 1.04, "yield": 38.0, "note": "FDM 출력물 기준"},
    "ASA": {"E": 2200.0, "nu": 0.38, "density": 1.07, "yield": 40.0, "note": "FDM 출력물 기준"},
    "TPU": {"E": 26.0, "nu": 0.48, "density": 1.21, "yield": 8.0, "note": "탄성체 — 선형 해석은 작은 변형에서만 의미"},
    "NYLON": {"E": 1700.0, "nu": 0.39, "density": 1.13, "yield": 45.0, "note": "FDM 출력물 기준"},
    "PMMA": {"E": 3000.0, "nu": 0.37, "density": 1.18, "yield": 70.0, "note": "아크릴 판재"},
    "POM": {"E": 2800.0, "nu": 0.35, "density": 1.41, "yield": 65.0, "note": "아세탈"},
    "ALUMINUM": {"E": 69000.0, "nu": 0.33, "density": 2.70, "yield": 240.0, "note": "6061-T6 부근"},
    "STEEL": {"E": 210000.0, "nu": 0.30, "density": 7.85, "yield": 235.0, "note": "S235/SS400 부근"},
    "STAINLESS": {"E": 193000.0, "nu": 0.29, "density": 7.90, "yield": 215.0, "note": "304"},
    "BRASS": {"E": 100000.0, "nu": 0.34, "density": 8.50, "yield": 200.0, "note": "C360 부근"},
}
_ALIASES = {"NYLON": "NYLON", "PA": "NYLON", "ALU": "ALUMINUM", "AL": "ALUMINUM", "ALUMINIUM": "ALUMINUM", "SUS": "STAINLESS", "SS304": "STAINLESS",
            "ACRYLIC": "PMMA", "ACETAL": "POM", "DELRIN": "POM"}
_FIELDS = {"von_mises": "vonMises", "displacement": "DisplacementLengths", "principal_max": "PrincipalMax", "principal_min": "PrincipalMin",
           "max_shear": "MaxShear"}
_SHOW = {"von_mises": "von Mises Stress", "displacement": "Displacement Magnitude", "principal_max": "Major Principal Stress",
         "principal_min": "Minor Principal Stress", "max_shear": "Tresca Stress"}
_EXTREMES = {"bottom": ("z", -1), "top": ("z", 1), "xmin": ("x", -1), "xmax": ("x", 1), "ymin": ("y", -1), "ymax": ("y", 1)}


class _FemError(Exception):
    pass


# ---------------------------------------------------------------- 공통

def _shape_or_error(d, name):
    obj, err = util.find_object(d, name)
    if err:
        return None, None, err
    if not hasattr(obj, "Shape") or obj.Shape.isNull():
        return obj, None, f"'{obj.Name}'에 형상이 없습니다."
    if not obj.Shape.Solids:
        return obj, None, f"'{obj.Name}'에 솔리드가 없습니다(면만 있음). 메시면 먼저 다시 그리세요."
    return obj, obj.Shape, None


def resolve_material(material):
    """이름(표) 또는 dict → {"name", "E", "nu", "density", "yield"}."""
    if material is None:
        material = "PLA"
    if isinstance(material, str):
        key = _ALIASES.get(material.strip().upper(), material.strip().upper())
        if key not in FEM_MATERIALS:
            raise _FemError(f"모르는 재질 '{material}'. 가능: {', '.join(FEM_MATERIALS)} 또는 dict(E, nu, density, yield)")
        m = dict(FEM_MATERIALS[key])
        m["name"] = key
        return m
    if isinstance(material, dict):
        base = dict(FEM_MATERIALS.get(_ALIASES.get(str(material.get("name", "")).upper(), str(material.get("name", "")).upper()), {}))
        base.update({k: float(v) for k, v in material.items() if k in ("E", "nu", "density", "yield") and v is not None})
        for k in ("E", "nu", "density", "yield"):
            if k not in base:
                raise _FemError(f"재질 dict에 '{k}'가 없습니다 (E MPa, nu, density g/cm³, yield MPa)")
        base["name"] = str(material.get("name", "custom"))
        base.setdefault("note", "사용자 지정")
        return base
    raise _FemError("material은 이름 문자열 또는 dict여야 합니다.")


def _fem_material_dict(m):
    return {"Name": m["name"], "YoungsModulus": f"{m['E']} MPa", "PoissonRatio": f"{m['nu']}", "Density": f"{m['density'] * 1000.0} kg/m^3",
            "YieldStrength": f"{m['yield']} MPa"}


def _read_material(mat_obj):
    """FemMaterial → 숫자 dict (안전율 계산용)."""
    q = FreeCAD.Units.Quantity
    md = dict(mat_obj.Material)
    out = {"name": md.get("Name", "?")}
    try:
        out["E"] = float(q(md["YoungsModulus"]).getValueAs("MPa"))
        out["nu"] = float(md["PoissonRatio"])
        out["density"] = float(q(md["Density"]).getValueAs("kg/m^3")) / 1000.0
        out["yield"] = float(q(md["YieldStrength"]).getValueAs("MPa")) if md.get("YieldStrength") else None
    except Exception:  # noqa: BLE001
        pass
    return out


def _resolve_faces(shape, sel):
    """면 선택자 → [(index1, Face)]. 문자열 'FaceN' | bottom/top/xmin/xmax/ymin/ymax, dict {"near": [x,y,z]} | {"normal": [..]} | {"faces": [...]}, 목록."""
    if sel is None:
        return []
    if isinstance(sel, (list, tuple)) and not (len(sel) == 3 and all(isinstance(v, (int, float)) for v in sel)):
        out = []
        for s in sel:
            out.extend(_resolve_faces(shape, s))
        seen, uniq = set(), []
        for i, f in out:
            if i not in seen:
                seen.add(i)
                uniq.append((i, f))
        return uniq
    faces = shape.Faces
    bb = shape.BoundBox
    if isinstance(sel, str):
        s = sel.strip()
        if s.lower().startswith("face") and s[4:].isdigit():
            i = int(s[4:])
            if not 1 <= i <= len(faces):
                raise _FemError(f"{s}는 없습니다(면 {len(faces)}개).")
            return [(i, faces[i - 1])]
        key = s.lower()
        if key in _EXTREMES:
            axis, sign = _EXTREMES[key]
            lim = getattr(bb, axis.upper() + ("Max" if sign > 0 else "Min"))
            out = []
            for i, f in enumerate(faces, 1):
                fb = f.BoundBox
                lo, hi = getattr(fb, axis.upper() + "Min"), getattr(fb, axis.upper() + "Max")
                if abs(lo - lim) < 1e-3 and abs(hi - lim) < 1e-3:       # 그 극단에 납작하게 놓인 면
                    out.append((i, f))
            if not out:
                raise _FemError(f"'{s}'에 평평한 면이 없습니다. {{\"near\": [x,y,z]}}로 지정하세요.")
            return out
        raise _FemError(f"면 선택자 '{sel}'를 모릅니다. 'FaceN', bottom/top/xmin/xmax/ymin/ymax, {{\"near\": [x,y,z]}} 중 하나.")
    if isinstance(sel, (list, tuple)) and len(sel) == 3:
        sel = {"near": list(sel)}
    if isinstance(sel, dict):
        if "faces" in sel:
            return _resolve_faces(shape, sel["faces"])
        cand = list(enumerate(faces, 1))
        if "normal" in sel:
            n = Vec(*[float(v) for v in sel["normal"]])
            if n.Length < 1e-9:
                raise _FemError("normal이 0 벡터입니다.")
            n.normalize()
            keep = []
            for i, f in cand:
                try:
                    u0, u1, v0, v1 = f.ParameterRange
                    fn = f.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
                except Exception:  # noqa: BLE001
                    continue
                if fn.dot(n) > 0.95:
                    keep.append((i, f))
            cand = keep
        if "near" in sel:
            p = Vec(*[float(v) for v in sel["near"]])
            v = Part.Vertex(p)
            best = None
            for i, f in cand:
                fb = f.BoundBox
                fb.enlarge(2.0)
                if not fb.isInside(p) and best is not None:
                    continue
                try:
                    dist = f.distToShape(v)[0]
                except Exception:  # noqa: BLE001
                    continue
                if best is None or dist < best[0]:
                    best = (dist, i, f)
            if best is None:
                raise _FemError("near에 맞는 면이 없습니다.")
            return [(best[1], best[2])]
        if not cand or "normal" not in sel:
            raise _FemError("dict 선택자는 near / normal / faces 중 하나가 필요합니다.")
        return cand
    raise _FemError(f"면 선택자 형식을 모릅니다: {sel!r}")


def _face_center(f):
    try:
        return f.CenterOfMass
    except Exception:  # noqa: BLE001
        return f.BoundBox.Center


def _center_of(shape):
    """형상의 (부피 가중) 무게중심. Part.Compound(PartDesign::Body·MultiFuse·cut 결과)는 CenterOfMass가 없다 [라이브 1.1.3]."""
    sols = shape.Solids
    if not sols:
        return shape.BoundBox.Center
    if shape.ShapeType == "Solid" or len(sols) == 1:
        return sols[0].CenterOfMass
    tot = Vec(0, 0, 0)
    vol = 0.0
    for so in sols:
        tot += so.CenterOfMass * so.Volume
        vol += so.Volume
    return tot * (1.0 / vol) if vol > 1e-12 else shape.BoundBox.Center


def _solids_of_parts(parts, comp_shape):
    """부품 → Compound 안 솔리드 번호 목록(1-based). 각 솔리드는 무게중심·부피가 같은 부품 솔리드에 대응시킨다."""
    keys = []
    for o in parts:
        for so in o.Shape.Solids:
            keys.append((o.Name, so.CenterOfMass, so.Volume))
    if not keys:
        raise _FemError("부품에 솔리드가 없습니다.")
    out = {o.Name: [] for o in parts}
    diag = max(1.0, comp_shape.BoundBox.DiagonalLength)
    for i, so in enumerate(comp_shape.Solids, 1):
        c, v = so.CenterOfMass, so.Volume
        best = min(keys, key=lambda k: (k[1] - c).Length + abs(k[2] - v) / max(v, 1e-9))
        if (best[1] - c).Length > 1e-3 * diag or abs(best[2] - v) > 1e-4 * max(v, 1e-9):
            raise _FemError(f"Compound의 Solid{i}(중심 {util.round_vec(c, 2)})가 어느 부품에도 대응하지 않습니다. 부품이 겹치거나(interference) 형상이 바뀐 것입니다.")
        out[best[0]].append(i)
    empty = [k for k, v in out.items() if not v]
    if empty:
        raise _FemError(f"부품 {', '.join(empty)}의 솔리드가 Compound에 없습니다.")
    return out


def _imprint_parts(parts):
    """부품 형상들을 generalFuse로 조각내 맞닿은 면을 새긴 Compound. 겹치는 부품은 조각이 늘어나 _solids_of_parts가 잡아낸다."""
    shapes = []
    for o in parts:
        shapes.extend(o.Shape.Solids)
    if len(shapes) == 1:
        return Part.makeCompound(shapes)
    try:
        res, _ = shapes[0].generalFuse(shapes[1:], 1e-6)
    except Exception as e:  # noqa: BLE001
        raise _FemError(f"부품을 접합면 기준으로 조각내지 못했습니다(generalFuse): {e}")
    if not res.Solids:
        raise _FemError("generalFuse 결과에 솔리드가 없습니다.")
    return res


def _is_planar(face):
    try:
        return isinstance(face.Surface, Part.Plane)
    except Exception:  # noqa: BLE001
        return False


def _bind_material_groups(mesh_obj, an):
    """부품별 재질 → Gmsh가 만든 SolidN Volume 그룹을 재질 객체 이름의 그룹으로 복사한다.

    FreeCAD 작성기는 재질 References(SolidN)를 getNodesBySolid로 요소에 대응시키는데, 곡면 위 절점을 밖으로
    분류해 요소 일부가 어느 재질에도 안 들어간다(CalculiX "no material was assigned"). 메시에 '<재질이름>_...'
    Volume 그룹이 있으면 작성기가 그 요소 목록을 그대로 쓴다(meshtools.get_femelement_sets_from_group_data)
    [라이브 1.1.3 확인]. 반환: {재질이름: 요소 수} 또는 그룹이 없으면 None."""
    fm = mesh_obj.FemMesh
    if fm.GroupCount == 0:
        return None
    by_name = {}
    for g in fm.Groups:
        if fm.getGroupElementType(g) == "Volume":
            by_name[fm.getGroupName(g)] = g
    mats = [m for m in _materials(an) if m.References]
    if not mats:
        return None
    out = {}
    for mo in mats:
        prefix = mo.Name + "_"
        for g in list(fm.Groups):
            if fm.getGroupName(g).startswith(prefix):
                fm.removeGroup(g)
        elems = set()
        for _obj, subs in mo.References:
            for sub in (subs if isinstance(subs, (list, tuple)) else [subs]):
                gid = by_name.get(sub)
                if gid is None:
                    return None
                elems.update(fm.getGroupElements(gid))
        gid = fm.addGroup(prefix + "elements", "Volume")
        fm.addGroupElements(gid, sorted(elems))
        out[mo.Name] = len(elems)
    mesh_obj.FemMesh = fm
    return out


def _shared_interface_nodes(mesh_obj, shape):
    """Gmsh SolidN_Nodes 그룹으로 솔리드 쌍이 공유하는 절점 수(합). 그룹이 없으면 None."""
    fm = mesh_obj.FemMesh
    if fm.GroupCount == 0:
        return None
    sets = []
    names = {fm.getGroupName(g): g for g in fm.Groups}
    for i in range(1, len(shape.Solids) + 1):
        g = names.get(f"Solid{i}_Nodes")
        if g is None:
            return None
        sets.append(set(fm.getGroupElements(g)))
    total = 0
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            total += len(sets[i] & sets[j])
    return total


def _check_inp(path):
    """CalculiX .inp 검증: 모든 요소가 재질 ELSET에 정확히 한 번 들어가는지, *CLOAD/*DLOAD에 하중 줄이 있는지."""
    elements = set()
    elsets = {}
    nested = {}
    section_sets = []
    cload = dload = 0
    block = None
    cur = None
    cont = False
    with open(path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("**"):
                continue
            if line.startswith("*"):
                up = line.upper()
                cont = False
                if up.startswith("*ELEMENT"):
                    block = "element"
                elif up.startswith("*ELSET"):
                    m = re.search(r"ELSET\s*=\s*([^,\s]+)", up)
                    cur = m.group(1) if m else None
                    if cur is not None:
                        elsets.setdefault(cur, set())
                    block = "elset"
                elif up.startswith("*SOLID SECTION") or up.startswith("*SHELL SECTION") or up.startswith("*BEAM SECTION"):
                    m = re.search(r"ELSET\s*=\s*([^,\s]+)", up)
                    if m:
                        section_sets.append(m.group(1))
                    block = None
                elif up.startswith("*CLOAD"):
                    block = "cload"
                elif up.startswith("*DLOAD"):
                    block = "dload"
                else:
                    block = None
                continue
            if block == "element":
                if not cont:
                    try:
                        elements.add(int(line.split(",")[0]))
                    except ValueError:
                        pass
                cont = line.endswith(",")
            elif block == "elset" and cur is not None:
                for tok in line.split(","):
                    tok = tok.strip()
                    if tok.isdigit():
                        elsets[cur].add(int(tok))
                    elif tok:
                        nested.setdefault(cur, []).append(tok.upper())     # 다른 집합 이름(FreeCAD 단일 재질: Evolumes)
            elif block == "cload":
                cload += 1
            elif block == "dload":
                dload += 1
    out = {"elements": len(elements), "material_sets": {}, "uncovered": None, "duplicated": None, "cload_lines": cload, "dload_lines": dload}
    def resolve(name, depth=0):
        name = name.upper()
        if name in ("EVOLUMES", "EALL"):
            return set(elements)
        ids = set(elsets.get(name, ()))
        if depth < 5:
            for sub in nested.get(name, []):
                ids |= resolve(sub, depth + 1)
        return ids

    if section_sets and elements:
        counts = {}
        for name in section_sets:
            ids = resolve(name)
            out["material_sets"][name] = len(ids)
            for e in ids:
                counts[e] = counts.get(e, 0) + 1
        out["uncovered"] = len([e for e in elements if e not in counts])
        out["duplicated"] = len([e for e, n in counts.items() if n > 1])
    return out


def _ccx_binary():
    pref = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Mod/Fem/Ccx").GetString("ccxBinaryPath", "")
    import shutil

    cands = [pref, shutil.which("ccx"), os.path.join(FreeCAD.getHomePath(), "bin", "ccx.exe"), os.path.join(FreeCAD.getHomePath(), "bin", "ccx")]
    for c in cands:
        if c and os.path.isfile(c):
            return os.path.normpath(c)
    raise _FemError("CalculiX(ccx) 실행 파일을 못 찾았습니다. FEM 환경설정에서 경로를 지정하세요.")


def _working_dir(d, an):
    wd = os.path.join(tempfile.gettempdir(), "cadxray_fem", d.Name, an.Name)
    os.makedirs(wd, exist_ok=True)
    return wd


def _members(an):
    grp = list(an.Group)
    mesh = next((o for o in grp if o.isDerivedFrom("Fem::FemMeshObject")), None)
    solver = next((o for o in grp if "Solver" in o.TypeId or o.Name.startswith("Solver")), None)
    mats = [o for o in grp if o.isDerivedFrom("App::MaterialObjectPython") or o.TypeId.startswith("App::MaterialObject")]
    mat = mats[0] if mats else None
    results = [o for o in grp if o.isDerivedFrom("Fem::FemResultObject")]
    pipes = [o for o in grp if o.TypeId == "Fem::FemPostPipeline"]
    return mesh, solver, mat, results, pipes


def _materials(an):
    return [o for o in an.Group if o.isDerivedFrom("App::MaterialObjectPython") or o.TypeId.startswith("App::MaterialObject")]


def _weakest_material(an):
    """여러 재질이면 항복강도가 가장 낮은 것(보수적). 안전율 계산용."""
    mats = [_read_material(m) for m in _materials(an)]
    mats = [m for m in mats if m.get("yield")]
    if not mats:
        return None
    return min(mats, key=lambda m: m["yield"])


def _find_analysis(d, analysis):
    if analysis:
        an, err = util.find_object(d, analysis)
        if err:
            return None, err
        if an.TypeId != "Fem::FemAnalysis":
            return None, f"'{an.Name}'은 해석 컨테이너(Fem::FemAnalysis)가 아닙니다."
        return an, None
    ans = [o for o in d.Objects if o.TypeId == "Fem::FemAnalysis"]
    if len(ans) == 1:
        return ans[0], None
    if not ans:
        return None, "해석 컨테이너가 없습니다. setup_analysis를 먼저 부르세요."
    return None, f"해석 컨테이너가 {len(ans)}개입니다: {', '.join(o.Name for o in ans)}. analysis로 지정하세요."


def _target_of(an):
    """메시 객체의 Shape 링크 → 해석 대상 객체."""
    mesh, *_ = _members(an)
    if mesh is not None and getattr(mesh, "Shape", None) is not None:
        return mesh.Shape
    return None


def _run_gmsh(mesh_obj):
    from femmesh import gmshtools

    t = time.time()
    err = gmshtools.GmshTools(mesh_obj).create_mesh()
    if err:
        raise _FemError(f"Gmsh 메시 실패: {err}")
    fm = mesh_obj.FemMesh
    return {"nodes": fm.NodeCount, "elements": fm.VolumeCount, "seconds": round(time.time() - t, 1)}


# ---------------------------------------------------------------- 7.36 setup_analysis

_ANALYSIS_TYPES = ("static", "frequency")


def setup_analysis(name=None, doc=None, material="PLA", fixed=None, loads=None, mesh_size=None, order="2nd", analysis="Analysis",
                   names=None, analysis_type="static", modes=5):
    """해석 컨테이너 + 재질 + 고정 + 하중 + Gmsh 메시 + CalculiX 솔버 (명세 7.36). names=[...]면 여러 부품을 Compound로 묶어 접합(공유 절점) 해석."""
    t0 = time.time()
    d, err = util.get_doc(doc)
    if err:
        return util.error(err)
    parts = []
    if names:
        if isinstance(names, str):
            names = [names]
        for nm in names:
            o, _, e = _shape_or_error(d, nm)
            if e:
                return util.error(e)
            parts.append(o)
        obj, shape = None, None
    else:
        obj, shape, err = _shape_or_error(d, name)
        if err:
            return util.error(err)
    analysis_type = str(analysis_type or "static").lower()
    if analysis_type not in _ANALYSIS_TYPES:
        return util.error(f"analysis_type은 {' / '.join(_ANALYSIS_TYPES)} 중 하나입니다. (buckling은 CalculiX가 멈춰 FreeCAD가 죽는 것을 확인해 뺐다)")
    warnings = []
    try:
        import ObjectsFem

        per_part = bool(parts) and isinstance(material, dict) and any(k in [o.Name for o in parts] + [util.label(o) for o in parts] for k in material)
        mat = None if per_part else resolve_material(material)
        fixed_sel = fixed if isinstance(fixed, list) else ([fixed] if fixed else [])
        if not fixed_sel:
            raise _FemError("fixed(고정 면)가 필요합니다. 예: [\"bottom\"] 또는 [{\"near\": [x,y,z]}]")
        loads = loads or []
        if not loads and analysis_type == "static":
            warnings.append("하중이 없습니다. self_weight라도 넣어야 의미 있는 결과가 나옵니다.")

        # 기존 같은 이름의 해석은 지운다(구성 재현)
        old = d.getObject(analysis)
        if old is not None:
            if old.TypeId != "Fem::FemAnalysis":
                raise _FemError(f"'{analysis}'는 이미 다른 객체입니다. analysis 이름을 바꾸세요.")
            for o in list(old.Group):
                if o.Name in [x.Name for x in d.Objects]:
                    d.removeObject(o.Name)
            for o in [x for x in d.Objects if x.Name.startswith(analysis + "_dir") or x.Name == analysis + "_Parts"]:
                d.removeObject(o.Name)
            d.removeObject(old.Name)
            warnings.append(f"기존 '{analysis}'를 지우고 다시 만들었습니다.")

        an = ObjectsFem.makeAnalysis(d, analysis)
        created = [an.Name]

        mats_out = []
        if parts:
            # 여러 부품 → generalFuse로 맞닿은 면을 서로 새긴(imprint) Compound. 그래야 Gmsh가 접합면 절점을 공유시켜
            # 접합(bonded)으로 풀린다 — 단순 Part::Compound는 한 면이 다른 면 안에 부분적으로 놓이면(원판 위 작은 원통 등)
            # 절점을 공유하지 않아 부품이 따로 놀고 변위가 발산한다 [라이브 1.1.3, api-notes §18]
            comp = d.addObject("Part::Feature", analysis + "_Parts")
            comp.Shape = _imprint_parts(parts)
            comp.Label = f"{analysis} 부품 묶음"
            d.recompute()
            if comp.ViewObject:
                comp.ViewObject.Visibility = False
            obj, shape = comp, comp.Shape
            created.append(comp.Name)
            # 부품 → Compound 솔리드 번호 (솔리드별 무게중심·부피로 대응; Body·MultiFuse처럼 Compound인 부품도 된다)
            solids_of = _solids_of_parts(parts, shape)
            if per_part:
                for o in parts:
                    spec = material.get(o.Name, material.get(util.label(o), material.get("default", "PLA")))
                    m = resolve_material(spec)
                    mo = ObjectsFem.makeMaterialSolid(d, f"Material_{o.Name}")
                    mo.Material = _fem_material_dict(m)
                    mo.References = [(comp, f"Solid{i}") for i in solids_of[o.Name]]
                    an.addObject(mo)
                    created.append(mo.Name)
                    mats_out.append(dict(m, part=o.Name, solid=solids_of[o.Name][0], solids=solids_of[o.Name]))
                mat = min(mats_out, key=lambda m: m["yield"])
            touching = 0
            sols = shape.Solids
            for i in range(len(sols)):
                for j in range(i + 1, len(sols)):
                    try:
                        if sols[i].distToShape(sols[j])[0] < 1e-6:
                            touching += 1
                    except Exception:  # noqa: BLE001
                        pass
            if touching == 0 and len(parts) > 1:
                warnings.append("부품끼리 맞닿은 곳이 없습니다 — 따로 노는 부품은 고정이 없으면 해석이 실패합니다.")
        if not per_part:
            mo = ObjectsFem.makeMaterialSolid(d, "Material")
            mo.Material = _fem_material_dict(mat)
            an.addObject(mo)
            created.append(mo.Name)
            mats_out = [mat]

        fixed_out = []
        ref_faces = []                      # 고정·하중이 걸린 면 — 곡면이 있으면 2차 요소 중간 절점을 곡면에 둔다
        for k, sel in enumerate(fixed_sel):
            fl = _resolve_faces(shape, sel)
            ref_faces.extend(f for _, f in fl)
            c = ObjectsFem.makeConstraintFixed(d, f"Fixed{k + 1}" if len(fixed_sel) > 1 else "Fixed")
            c.References = [(obj, f"Face{i}") for i, _ in fl]
            an.addObject(c)
            created.append(c.Name)
            fixed_out.append({"selector": sel, "faces": [f"Face{i}" for i, _ in fl], "area": round(sum(f.Area for _, f in fl), 2)})

        loads_out = []
        for k, ld in enumerate(loads):
            if not isinstance(ld, dict) or "type" not in ld:
                raise _FemError(f"loads[{k}]는 {{\"type\": force|pressure|self_weight, ...}} 형식이어야 합니다.")
            typ = str(ld["type"]).lower()
            rec = {"type": typ}
            if typ == "force":
                fl = _resolve_faces(shape, ld.get("faces"))
                if not fl:
                    raise _FemError(f"loads[{k}] force에 faces가 필요합니다.")
                ref_faces.extend(f for _, f in fl)
                c = ObjectsFem.makeConstraintForce(d, f"Force{k + 1}")
                c.References = [(obj, f"Face{i}") for i, _ in fl]
                c.Force = f"{float(ld.get('value', 0.0))} N"
                dirv = ld.get("direction")
                if dirv is not None:
                    v = Vec(*[float(x) for x in dirv])
                    if v.Length < 1e-9:
                        raise _FemError(f"loads[{k}] direction이 0 벡터입니다.")
                    v.normalize()
                    ln = d.addObject("Part::Feature", f"{analysis}_dir{k + 1}")
                    ln.Shape = Part.makeLine(Vec(0, 0, 0), v * 10.0)
                    ln.Label = f"{analysis} 하중 방향 {k + 1}"
                    if ln.ViewObject:
                        ln.ViewObject.Visibility = False
                    c.Direction = (ln, ["Edge1"])
                    c.Reversed = False
                    created.append(ln.Name)
                    rec["direction"] = [round(v.x, 4), round(v.y, 4), round(v.z, 4)]
                else:
                    rec["direction"] = "face normal"
                an.addObject(c)
                created.append(c.Name)
                rec.update({"faces": [f"Face{i}" for i, _ in fl], "value_n": float(ld.get("value", 0.0)), "area": round(sum(f.Area for _, f in fl), 2)})
            elif typ == "pressure":
                fl = _resolve_faces(shape, ld.get("faces"))
                if not fl:
                    raise _FemError(f"loads[{k}] pressure에 faces가 필요합니다.")
                ref_faces.extend(f for _, f in fl)
                c = ObjectsFem.makeConstraintPressure(d, f"Pressure{k + 1}")
                c.References = [(obj, f"Face{i}") for i, _ in fl]
                c.Pressure = f"{float(ld.get('value', 0.0))} MPa"
                c.Reversed = bool(ld.get("reversed", False))
                an.addObject(c)
                created.append(c.Name)
                rec.update({"faces": [f"Face{i}" for i, _ in fl], "value_mpa": float(ld.get("value", 0.0)), "reversed": c.Reversed})
            elif typ in ("self_weight", "gravity"):
                c = ObjectsFem.makeConstraintSelfWeight(d, "SelfWeight")
                g = ld.get("direction", [0, 0, -1])
                v = Vec(*[float(x) for x in g])
                v.normalize()
                c.GravityDirection = v
                an.addObject(c)
                created.append(c.Name)
                rec.update({"direction": [round(v.x, 4), round(v.y, 4), round(v.z, 4)], "g": 9.81})
            else:
                raise _FemError(f"loads[{k}] type '{typ}'는 지원하지 않습니다 (force / pressure / self_weight).")
            loads_out.append(rec)

        # 메시
        mesh = ObjectsFem.makeMeshGmsh(d, "Mesh")
        mesh.Shape = obj
        bb = shape.BoundBox
        if mesh_size is None:
            diag = bb.DiagonalLength
            mesh_size = max(0.5, min(10.0, round(diag / 30.0, 2)))
        mesh.CharacteristicLengthMax = f"{float(mesh_size)} mm"
        mesh.ElementOrder = "2nd" if str(order).startswith("2") else "1st"
        # 2차 요소의 중간 절점: 기본은 직선 변(SecondOrderLinear) — 곡면(나사 등)에서 휜 요소는 CalculiX가 "nonpositive jacobian"으로
        # 거부한다 [라이브 1.1.3]. 단, 고정·하중 면이 곡면이면 직선 변의 중간 절점이 표면을 벗어나 FreeCAD 작성기가 그 면의 요소를
        # 못 찾는다(getccxVolumesByFace 0개 → *CLOAD/*DLOAD 비고 응력 0) → 그때는 중간 절점을 곡면에 둔다 [라이브 1.1.3]
        curved_refs = [f for f in ref_faces if not _is_planar(f)]
        mesh.SecondOrderLinear = not curved_refs
        if mesh.ElementOrder == "1st":
            warnings.append("1차 요소는 굽힘 강성을 2배 가까이 과대평가합니다(외팔보 검증). 정확도가 필요하면 order='2nd'.")
        elif curved_refs:
            warnings.append(f"고정·하중 면 중 {len(curved_refs)}개가 곡면입니다 — 2차 요소 중간 절점을 곡면 위에 둡니다(직선 변이면 그 면에 하중이 실리지 않음). "
                            "CalculiX가 'nonpositive jacobian'으로 실패하면 mesh_size를 줄이거나 order='1st', 또는 하중 면을 평면으로 나누세요.")
        an.addObject(mesh)
        created.append(mesh.Name)
        mesh_info = _run_gmsh(mesh)
        mesh_info.update({"size": float(mesh_size), "order": mesh.ElementOrder, "second_order_linear": bool(mesh.SecondOrderLinear)})
        if parts and len(parts) > 1:
            shared = _shared_interface_nodes(mesh, shape)
            if shared is not None:
                mesh_info["interface_shared_nodes"] = shared
                if shared == 0 and touching:
                    warnings.append("맞닿은 부품 사이에 공유 절점이 없습니다 — 부품이 따로 놀아 변위가 발산합니다. 부품 형상을 확인하세요.")
        if per_part:
            groups = _bind_material_groups(mesh, an)
            if groups:
                mesh_info["material_groups"] = groups
                if sum(groups.values()) != mesh_info["elements"]:
                    warnings.append(f"재질 그룹 요소 합({sum(groups.values())})이 전체 요소({mesh_info['elements']})와 다릅니다 — 부품이 겹치는지 확인하세요.")
            else:
                warnings.append("Gmsh 솔리드 그룹이 없어 재질을 절점 분류로 대응합니다 — 곡면 부품이면 요소 일부가 재질을 못 받을 수 있습니다(run_analysis가 검증).")
        if mesh_info["nodes"] > 300000:
            warnings.append(f"절점 {mesh_info['nodes']}개 — 해석이 수 분 걸릴 수 있습니다. mesh_size를 키우세요.")

        sol = ObjectsFem.makeSolverCalculiXCcxTools(d, "Solver")
        sol.AnalysisType = analysis_type
        if analysis_type == "frequency":
            sol.EigenmodesCount = max(1, int(modes))
        sol.WorkingDir = _working_dir(d, an)
        an.addObject(sol)
        created.append(sol.Name)
        d.recompute()
    except _FemError as e:
        return util.error(str(e))
    except Exception as e:  # noqa: BLE001
        return util.error(f"해석 구성 실패: {e}", e)
    data = {"document": d.Name, "object": obj.Name, "label": util.label(obj), "analysis": an.Name, "created": created, "analysis_type": analysis_type,
            "material": mat, "materials": mats_out, "parts": [o.Name for o in parts] if parts else None,
            "fixed": fixed_out, "loads": loads_out, "mesh": mesh_info,
            "solver": f"CalculiX {analysis_type} ({mesh.ElementOrder}-order tets)" + (f", modes {int(modes)}" if analysis_type == "frequency" else ""),
            "next": f"run_analysis(analysis='{an.Name}')"}
    if parts and len(parts) > 1:
        warnings.append("부품 사이는 완전 접합(절점 공유)으로 풉니다. 미끄러짐·마찰 접촉은 지원하지 않습니다.")
    warnings.append("재질 표는 경험값입니다(FDM 출력물은 층 방향으로 더 약함). material dict로 덮어쓸 수 있습니다.")
    return util.envelope(data, warnings=warnings, t0=t0)


# ---------------------------------------------------------------- 결과 읽기

def _node_positions(res):
    return res.Mesh.FemMesh.Nodes      # {node_id: Vector}


def _argmax(values):
    if not values:
        return None
    return max(range(len(values)), key=lambda k: values[k])


def _nearest_face(shape, p, faces_cache=None):
    """점에 가장 가까운 면 (index1, dist)."""
    v = Part.Vertex(p)
    best = None
    for i, f in enumerate(shape.Faces, 1):
        fb = f.BoundBox
        fb.enlarge(1.0)
        if not fb.isInside(p):
            continue
        try:
            dist = f.distToShape(v)[0]
        except Exception:  # noqa: BLE001
            continue
        if best is None or dist < best[1]:
            best = (i, dist)
            if dist < 1e-3:
                break
    return best


def _percentile(values, q):
    if not values:
        return None
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((len(s) - 1) * q))))
    return s[k]


def _summarize(res, shape, mat):
    vm = list(res.vonMises)
    dl = list(res.DisplacementLengths)
    nodes = _node_positions(res)
    ids = list(res.NodeNumbers)
    out = {"nodes": len(ids)}
    warnings = []
    if vm and len(vm) == len(ids):
        i = _argmax(vm)
        p = nodes[ids[i]]
        nf = _nearest_face(shape, p)
        p99 = _percentile(vm, 0.99)
        out["von_mises"] = {"max": round(vm[i], 3), "p99": round(p99, 3), "mean": round(sum(vm) / len(vm), 3), "node": ids[i],
                            "at": util.round_vec(p, 2), "face": f"Face{nf[0]}" if nf else None}
        if p99 and vm[i] > 3.0 * p99:
            warnings.append(f"최대 응력({round(vm[i], 1)})이 상위 1 % 값({round(p99, 1)})의 3배를 넘습니다 — 날카로운 모서리·점 고정의 응력 특이점일 수 있습니다. 필렛을 넣거나 p99를 기준으로 보세요.")
    if dl and len(dl) == len(ids):
        j = _argmax(dl)
        p = nodes[ids[j]]
        vec = list(res.DisplacementVectors)[j] if len(res.DisplacementVectors) == len(ids) else None
        out["displacement"] = {"max": round(dl[j], 4), "node": ids[j], "at": util.round_vec(p, 2),
                               "direction": util.round_vec(vec.normalize(), 3) if vec is not None and vec.Length > 1e-12 else None,
                               "percent_of_size": round(dl[j] / max(shape.BoundBox.DiagonalLength, 1e-9) * 100.0, 3)}
    for key, prop in (("principal_max", "PrincipalMax"), ("principal_min", "PrincipalMin")):
        vals = list(getattr(res, prop, []) or [])
        if vals and len(vals) == len(ids):
            k = _argmax(vals) if key == "principal_max" else min(range(len(vals)), key=lambda t: vals[t])
            out[key] = {"value": round(vals[k], 3), "node": ids[k], "at": util.round_vec(nodes[ids[k]], 2)}
    if mat and mat.get("yield") and out.get("von_mises"):
        sf = mat["yield"] / max(out["von_mises"]["max"], 1e-9)
        sf99 = mat["yield"] / max(out["von_mises"]["p99"], 1e-9)
        out["safety_factor"] = round(sf, 2)
        out["safety_factor_p99"] = round(sf99, 2)
        out["yield_strength"] = mat["yield"]
        out["verdict"] = "ok" if sf >= 2.0 else ("marginal" if sf >= 1.0 else "fail")
        out["verdict_detail"] = {"ok": "안전율 2 이상", "marginal": "항복은 안 하지만 안전율 2 미만", "fail": "항복강도 초과 — 영구 변형·파손"}[out["verdict"]]
    return out, warnings


def _show_pipeline(d, an, res, field_key):
    import ObjectsFem

    for o in [o for o in an.Group if o.TypeId == "Fem::FemPostPipeline"]:
        d.removeObject(o.Name)
    pipe = ObjectsFem.makePostVtkResult(d, [res], "Result")
    an.addObject(pipe)
    d.recompute()
    label = _SHOW.get(field_key, field_key)
    if pipe.ViewObject:
        try:
            pipe.ViewObject.Field = label
        except Exception:  # noqa: BLE001
            label = None
        target = _target_of(an)
        for o in [target] + [m for m in an.Group if m.isDerivedFrom("Fem::FemMeshObject")]:
            if o is not None and o.ViewObject:
                o.ViewObject.Visibility = False
    return pipe, label


# ---------------------------------------------------------------- 7.37 run_analysis

def run_analysis(analysis=None, doc=None, show="von_mises"):
    """CalculiX 정적 해석 실행 → 요약 + 컬러맵 (명세 7.37)."""
    t0 = time.time()
    d, err = util.get_doc(doc)
    if err:
        return util.error(err)
    an, err = _find_analysis(d, analysis)
    if err:
        return util.error(err)
    warnings = []
    try:
        from femtools import ccxtools

        mesh, sol, mat_obj, _, _ = _members(an)
        if mesh is None or sol is None:
            raise _FemError("해석에 메시 또는 솔버가 없습니다. setup_analysis로 다시 만드세요.")
        target = mesh.Shape
        if target is None or not hasattr(target, "Shape"):
            raise _FemError("메시가 가리키는 형상이 없습니다.")
        shape = target.Shape
        mesh_info = None
        if mesh.FemMesh.NodeCount == 0:
            mesh_info = _run_gmsh(mesh)
            _bind_material_groups(mesh, an)
        wd = _working_dir(d, an)
        sol.WorkingDir = wd
        t1 = time.time()
        if FreeCAD.ActiveDocument is None or FreeCAD.ActiveDocument.Name != d.Name:
            FreeCAD.setActiveDocument(d.Name)      # ccxtools가 ActiveDocument를 본다 [헤드리스 1.1.3: None이면 getObject 오류]
        try:
            os.chdir(wd)                            # 현재 폴더가 지워진 곳이면 ccx 실행이 WinError 2로 실패한다 [라이브 1.1.3]
        except Exception:  # noqa: BLE001
            pass
        atype = str(getattr(sol, "AnalysisType", "static"))
        if atype not in _ANALYSIS_TYPES:
            raise _FemError(f"AnalysisType '{atype}'는 지원하지 않습니다 (static / frequency).")
        fea = ccxtools.FemToolsCcx(an, sol)
        fea.purge_results()
        fea.update_objects()
        fea.setup_working_dir(wd)
        fea.setup_ccx(ccx_binary=_ccx_binary())
        msg = fea.check_prerequisites()
        if msg:
            raise _FemError(f"해석 준비 오류: {msg.strip()}")
        fea.write_inp_file()
        inp_check = _check_inp(fea.inp_file_name)
        if inp_check["uncovered"]:
            raise _FemError(f"요소 {inp_check['uncovered']}개(전체 {inp_check['elements']})가 어느 재질에도 배정되지 않았습니다(CalculiX 'no material was assigned'). "
                            f"재질 ELSET: {inp_check['material_sets']}. 부품이 겹치지 않는지 확인하고 setup_analysis를 다시 부르세요.")
        if inp_check["duplicated"]:
            warnings.append(f"요소 {inp_check['duplicated']}개가 재질 ELSET 두 개 이상에 들어 있습니다 — 부품이 겹치는 곳입니다. CalculiX는 마지막 재질을 씁니다.")
        has_force = any(o.isDerivedFrom("Fem::ConstraintForce") for o in an.Group)
        has_dload = any(o.isDerivedFrom("Fem::ConstraintPressure") or o.isDerivedFrom("Fem::ConstraintSelfWeight") for o in an.Group)
        if atype == "static":
            if has_force and inp_check["cload_lines"] == 0:
                raise _FemError("힘 하중이 요소에 실리지 않았습니다(.inp의 *CLOAD가 비어 있음 → 응력 0이 나옵니다). 하중 면이 곡면이면 setup_analysis를 다시 불러 "
                                "중간 절점을 곡면에 두게 하거나(자동), 평면으로 나누거나, pressure로 바꾸세요.")
            if has_dload and inp_check["dload_lines"] == 0:
                raise _FemError("압력·자중이 요소에 실리지 않았습니다(.inp의 *DLOAD가 비어 있음). 하중 면이 곡면이면 setup_analysis를 다시 부르거나 평면으로 나누세요.")
        ret = fea.ccx_run()
        stdout = getattr(fea, "ccx_stdout", "") or ""
        stderr = getattr(fea, "ccx_stderr", "") or ""
        if ret != 0 or "*ERROR" in stdout:
            tail = (stderr or stdout)[-600:]
            raise _FemError(f"CalculiX 실패(ret {ret}): {tail.strip()}")
        fea.load_results()
        solve_s = round(time.time() - t1, 1)
        results = [o for o in an.Group if o.isDerivedFrom("Fem::FemResultObject")]
        if not results:
            raise _FemError("결과 객체가 만들어지지 않았습니다. 작업 폴더의 .frd를 확인하세요: " + wd)
        res = results[0]
        mat = _weakest_material(an)
        if atype == "frequency":
            modes = []
            for o in sorted(results, key=lambda r: int(getattr(r, "Eigenmode", 0) or 0)):
                dl = list(o.DisplacementLengths)
                modes.append({"mode": int(getattr(o, "Eigenmode", 0) or 0), "frequency_hz": round(float(getattr(o, "EigenmodeFrequency", 0.0)), 2),
                              "result": o.Name, "shape_max_rel": round(max(dl), 3) if dl else None})
            summary = {"nodes": len(list(res.NodeNumbers)), "modes": modes, "first_frequency_hz": modes[0]["frequency_hz"] if modes else None,
                       "note": "고유진동수(Hz). 모드 변위는 정규화된 상대값이라 크기는 의미 없고 모양만 본다. 가진 주파수가 1차 고유진동수 근처면 공진"}
            pipe, shown = _show_pipeline(d, an, res, "displacement")
        else:
            summary, w2 = _summarize(res, shape, mat)
            warnings.extend(w2)
            if len(_materials(an)) > 1:
                summary["safety_note"] = f"재질이 여럿이라 항복강도는 가장 낮은 {mat['name']}({mat['yield']} MPa) 기준"
            pipe, shown = _show_pipeline(d, an, res, show or "von_mises")
        d.recompute()
    except _FemError as e:
        return util.error(str(e))
    except Exception as e:  # noqa: BLE001
        return util.error(f"해석 실행 실패: {e}", e)
    data = {"document": d.Name, "analysis": an.Name, "analysis_type": atype, "object": target.Name, "material": mat, "result": res.Name, "pipeline": pipe.Name,
            "shown_field": shown, "solve_seconds": solve_s, "working_dir": wd, "summary": summary, "inp_check": inp_check}
    if mesh_info:
        data["mesh"] = mesh_info
    warnings.append("선형 정적·등방성 해석입니다. 화면의 컬러맵은 get_screenshot(view='iso')로 잡을 수 있습니다.")
    return util.envelope(data, warnings=warnings, t0=t0)


# ---------------------------------------------------------------- 7.38 inspect_results

def inspect_results(analysis=None, doc=None, field="von_mises", top_n=10, show=None, max_faces=10):
    """상위 절점·면별 요약, 컬러맵 필드 전환 (명세 7.38)."""
    t0 = time.time()
    d, err = util.get_doc(doc)
    if err:
        return util.error(err)
    an, err = _find_analysis(d, analysis)
    if err:
        return util.error(err)
    try:
        mesh, sol, mat_obj, results, pipes = _members(an)
        if not results:
            raise _FemError("결과가 없습니다. run_analysis를 먼저 부르세요.")
        res = results[0]
        key = str(field).lower()
        if key not in _FIELDS:
            raise _FemError(f"field는 {', '.join(_FIELDS)} 중 하나입니다.")
        vals = list(getattr(res, _FIELDS[key], []) or [])
        ids = list(res.NodeNumbers)
        if not vals or len(vals) != len(ids):
            raise _FemError(f"결과에 {key} 값이 없습니다.")
        shape = mesh.Shape.Shape
        nodes = _node_positions(res)
        order = sorted(range(len(vals)), key=lambda k: -vals[k] if key != "principal_min" else vals[k])
        top = []
        per_face = {}
        for k in order[: int(top_n)]:
            p = nodes[ids[k]]
            nf = _nearest_face(shape, p)
            fid = f"Face{nf[0]}" if nf else None
            top.append({"node": ids[k], "value": round(vals[k], 4), "at": util.round_vec(p, 2), "face": fid})
            if fid and fid not in per_face:
                per_face[fid] = {"face": fid, "max": round(vals[k], 4), "count": 0}
            if fid:
                per_face[fid]["count"] += 1
        faces = sorted(per_face.values(), key=lambda r: -r["max"] if key != "principal_min" else r["max"])
        shown = None
        if show:
            skey = str(show).lower()
            if skey not in _SHOW:
                raise _FemError(f"show는 {', '.join(_SHOW)} 중 하나입니다.")
            _, shown = _show_pipeline(d, an, res, skey)
            d.recompute()
        stats = {"max": round(max(vals), 4), "min": round(min(vals), 4), "mean": round(sum(vals) / len(vals), 4), "p99": round(_percentile(vals, 0.99), 4)}
    except _FemError as e:
        return util.error(str(e))
    except Exception as e:  # noqa: BLE001
        return util.error(f"결과 조회 실패: {e}", e)
    data = {"document": d.Name, "analysis": an.Name, "field": key, "unit": "mm" if key == "displacement" else "MPa", "stats": stats,
            "top": top, "faces": faces[: int(max_faces)], "faces_total": len(faces), "shown_field": shown}
    return util.envelope(data, truncated=len(faces) > int(max_faces), t0=t0)


# ---------------------------------------------------------------- 7.39 suggest_reinforcement

def _local_thickness(shape, p, normal):
    """핫스팟에서 면 법선 반대쪽으로 광선 → 두께."""
    try:
        from . import printing

        mesh = printing._mesh_of(shape)
        t = printing._ray(mesh, p, Vec(-normal.x, -normal.y, -normal.z), back_off=-printing._INSET)
        return t
    except Exception:  # noqa: BLE001
        return None


def _concave_edge_near(shape, face_idx, p, tol):
    """핫스팟 근처(tol)에서 그 면과 이웃 면이 안쪽으로 꺾이는 모서리가 있으면 (edge_index1, angle_deg)."""
    f = shape.Faces[face_idx - 1]
    v = Part.Vertex(p)
    best = None
    for e in f.Edges:
        try:
            dist = e.distToShape(v)[0]
        except Exception:  # noqa: BLE001
            continue
        if dist > tol:
            continue
        anc = [a for a in shape.ancestorsOfType(e, Part.Face) if not a.isSame(f)]
        if not anc:
            continue
        g = anc[0]
        mid = e.valueAt((e.FirstParameter + e.LastParameter) / 2)
        try:
            n1 = f.normalAt(*f.Surface.parameter(mid))
            n2 = g.normalAt(*g.Surface.parameter(mid))
        except Exception:  # noqa: BLE001
            continue
        ang = math.degrees(math.acos(max(-1.0, min(1.0, n1.dot(n2)))))
        if ang < 10.0 or ang > 170.0:      # 180°는 다른 솔리드의 맞닿은 면(접합면)이라 오목 모서리가 아니다
            continue
        q = mid + (n1 - n2) * 0.2
        if shape.isInside(q, 1e-4, True):     # 두 법선 차 방향이 재료 안 → 오목 모서리
            eidx = next((i for i, se in enumerate(shape.Edges, 1) if se.isSame(e)), None)
            if best is None or dist < best[2]:
                best = (eidx, round(ang, 1), dist)
    return best


def _mesh_size_of(mesh_obj, shape):
    try:
        return float(mesh_obj.CharacteristicLengthMax.getValueAs("mm"))
    except Exception:  # noqa: BLE001
        return max(0.5, shape.BoundBox.DiagonalLength / 30.0)


def _sub_solid(obj, sub):
    return obj.Shape.Solids[int(sub[5:]) - 1] if sub.startswith("Solid") else None


def _node_yields(an, mesh_obj):
    """재질이 여럿일 때 절점별 항복강도(MPa). 재질 References의 솔리드 절점은 Gmsh 'SolidN_Nodes' 그룹(없으면 getNodesBySolid)으로.
    두 부품 경계 절점은 낮은 쪽. 재질이 하나면 None."""
    mats = _materials(an)
    if len(mats) < 2:
        return None
    fm = mesh_obj.FemMesh
    names = {fm.getGroupName(g): g for g in fm.Groups} if fm.GroupCount else {}
    per = {}
    for mo in mats:
        y = _read_material(mo).get("yield")
        if not y or not mo.References:
            continue
        nodes = set()
        for obj, subs in mo.References:
            for sub in (subs if isinstance(subs, (list, tuple)) else [subs]):
                g = names.get(sub + "_Nodes")
                if g is not None:
                    nodes.update(fm.getGroupElements(g))
                else:
                    so = _sub_solid(obj, sub)
                    if so is not None:
                        nodes.update(fm.getNodesBySolid(so))
        for n in nodes:
            per[n] = min(per.get(n, y), y)
    return per


def _fixed_faces(an):
    out = []
    for c in an.Group:
        if not c.isDerivedFrom("Fem::ConstraintFixed"):
            continue
        for obj, subs in c.References:
            for sub in (subs if isinstance(subs, (list, tuple)) else [subs]):
                if sub.startswith("Face"):
                    try:
                        out.append(obj.Shape.Faces[int(sub[4:]) - 1])
                    except Exception:  # noqa: BLE001
                        pass
    return out


def _pick_hotspot(res, shape, an, mesh_obj, weakest):
    """보강 기준 핫스팟. 절점마다 (응력 / 그 부품의 항복강도)가 가장 큰 곳을 고르되, 고정면에서 요소 크기 2배 안의
    급증(바깥 최대의 2배 초과)은 응력 특이점으로 보고 제외한다. 외팔보 뿌리처럼 고정면 근처가 진짜 최대인 경우(완만)는 그대로 둔다."""
    vm = list(res.vonMises)
    ids = list(res.NodeNumbers)
    nodes = _node_positions(res)
    per = _node_yields(an, mesh_obj) or {}
    y0 = weakest["yield"]

    def yld(n):
        return per.get(n, y0)

    order = sorted(range(len(ids)), key=lambda k: -(vm[k] / yld(ids[k])))
    radius = 2.0 * _mesh_size_of(mesh_obj, shape)
    faces = _fixed_faces(an)
    boxes = []
    for f in faces:
        bb = f.BoundBox
        bb.enlarge(radius)
        boxes.append(bb)

    def near_fixed(p):
        v = Part.Vertex(p)
        for f, bb in zip(faces, boxes):
            if not bb.isInside(p):
                continue
            try:
                if f.distToShape(v)[0] < radius:
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False

    spike, chosen, skipped = None, None, 0
    for k in order[:3000]:
        if faces and near_fixed(nodes[ids[k]]):
            if spike is None:
                spike = k
            skipped += 1
            continue
        chosen = k
        break
    notes = []
    if chosen is None:
        chosen = order[0]
    if spike is not None and chosen != spike:
        s_spike = vm[spike] / yld(ids[spike])
        s_ch = vm[chosen] / yld(ids[chosen])
        if s_spike > 2.0 * s_ch:
            notes.append(f"최대 응력 절점 {ids[spike]}({round(vm[spike], 1)} MPa, {util.round_vec(nodes[ids[spike]], 1)})은 고정면에서 {round(radius, 1)} mm 안이고 "
                         f"바깥 최대의 {round(s_spike / s_ch, 1)}배라 응력 특이점으로 보고 제외했습니다(고정면 근처 절점 {skipped}개). 보강 기준은 그 다음 핫스팟입니다.")
        else:
            chosen = spike
            notes.append("최대 응력이 고정면 근처지만 바깥 최대의 2배 이내라(완만한 굽힘 응력) 특이점으로 보지 않았습니다.")
    if per:
        notes.append("재질이 여럿이라 절점마다 그 부품의 항복강도로 안전율을 계산했습니다(부품 경계 절점은 낮은 쪽).")
    k = chosen
    p = nodes[ids[k]]
    nf = _nearest_face(shape, p)
    y = yld(ids[k])
    hot = {"max": round(vm[k], 3), "node": ids[k], "at": util.round_vec(p, 2), "face": f"Face{nf[0]}" if nf else None,
           "yield": y, "safety_factor": round(y / max(vm[k], 1e-9), 2), "global_max": round(max(vm), 3) if vm else None}
    return hot, notes


def suggest_reinforcement(analysis=None, doc=None, target_safety=2.0, max_items=10):
    """안전율 미달 시 보강 후보 번호 목록 (명세 7.39). 자동 적용 없음."""
    t0 = time.time()
    d, err = util.get_doc(doc)
    if err:
        return util.error(err)
    an, err = _find_analysis(d, analysis)
    if err:
        return util.error(err)
    warnings = []
    try:
        mesh, sol, mat_obj, results, _ = _members(an)
        if not results:
            raise _FemError("결과가 없습니다. run_analysis를 먼저 부르세요.")
        res = results[0]
        if str(getattr(sol, "AnalysisType", "static")) != "static":
            raise _FemError("보강 제안은 정적(static) 해석 결과에서만 됩니다.")
        target = mesh.Shape
        shape = target.Shape
        mat = _weakest_material(an) or {}
        if not mat.get("yield"):
            raise _FemError("재질에 항복강도가 없어 안전율을 계산할 수 없습니다.")
        summary, w2 = _summarize(res, shape, mat)
        warnings.extend(w2)
        vm = summary.get("von_mises")
        if not vm:
            raise _FemError("응력 결과가 없습니다.")
        hot, hot_notes = _pick_hotspot(res, shape, an, mesh, mat)
        vm = dict(vm)
        vm.update(hot)                                     # p99는 전체 기준, max·위치·항복강도는 고른 핫스팟 기준
        sf = hot["safety_factor"]
        summary["safety_factor_hotspot"] = sf
        target_safety = float(target_safety)
        need = target_safety / max(sf, 1e-9)              # 응력을 이만큼 줄여야 한다
        p = Vec(*vm["at"])
        fidx = int(vm["face"][4:]) if vm.get("face") else None
        cands = []
        if sf >= target_safety:
            data = {"document": d.Name, "analysis": an.Name, "safety_factor": sf, "target": target_safety, "summary": summary, "hotspot": vm, "hotspot_selection": hot_notes,
                    "candidates": [],
                    "note": f"안전율 {sf} ≥ 목표 {target_safety}. 보강이 필요 없습니다. 무게를 줄이고 싶으면 두께를 지금의 {round(100.0 / math.sqrt(sf / target_safety))} %까지 줄여도 목표를 지킵니다(굽힘 기준, 좌굴·변위는 따로 확인)."}
            return util.envelope(data, warnings=warnings, t0=t0)

        # 1) 핫스팟 두께 키우기
        thick = None
        normal = None
        if fidx:
            f = shape.Faces[fidx - 1]
            try:
                u, v = f.Surface.parameter(p)
                normal = f.normalAt(u, v)
                thick = _local_thickness(shape, p, normal)
            except Exception:  # noqa: BLE001
                pass
        if thick:
            t_bend = thick * math.sqrt(need)
            t_axial = thick * need
            cands.append({"kind": "thicken", "detail": f"최대 응력 지점({vm['face']}, {vm['at']})의 두께 {round(thick, 2)} mm → 굽힘이면 {round(t_bend, 2)} mm, 인장/전단이면 {round(t_axial, 2)} mm",
                          "expected_safety": target_safety, "confidence": "medium",
                          "how": "build_features pad/pocket 또는 스케치 치수 변경. 3D 프린트면 노즐 배수(0.8·1.2·1.6)로 올림"})
        # 2) 오목 모서리 필렛
        if fidx:
            ce = _concave_edge_near(shape, fidx, p, tol=max(1.5, (thick or 1.0)))
            if ce:
                r = max(1.0, round((thick or 2.0) / 2.0, 1))
                cands.append({"kind": "fillet", "detail": f"최대 응력이 오목 모서리 Edge{ce[0]}(꺾임 {ce[1]}°) 근처입니다. R{r} 필렛으로 응력 집중을 완화(보통 20~50 % 감소)",
                              "expected_safety": round(sf * 1.3, 2), "confidence": "high" if vm["max"] > 3.0 * vm["p99"] else "medium",
                              "how": f"build_features {{\"op\": \"fillet\", \"edges\": [\"Edge{ce[0]}\"], \"radius\": {r}}}"})
        # 3) 리브
        disp = summary.get("displacement")
        if disp and disp.get("direction") and normal is not None:
            dv = Vec(*disp["direction"])
            if abs(dv.dot(normal)) > 0.7:
                rib_t = max(2.0, round((thick or 2.0), 1))
                cands.append({"kind": "rib", "detail": f"처짐 방향 {disp['direction']}이 {vm['face']} 법선과 나란합니다 — 그 면에 처짐 방향으로 세운 리브(두께 {rib_t}, 높이 {rib_t * 3}) 추가. 굽힘 강성은 높이의 세제곱으로 늘어납니다",
                              "expected_safety": round(sf * 2.0, 2), "confidence": "low",
                              "how": "build_features pad(리브 단면 폴리곤)"})
        # 4) 재질
        better = [k for k, m in FEM_MATERIALS.items() if m["yield"] / vm["max"] >= target_safety and m["yield"] > vm["yield"]]
        if better:
            cands.append({"kind": "material", "detail": f"재질 변경으로 목표 달성: {', '.join(better[:6])} (항복강도/최대응력 ≥ {target_safety})",
                          "expected_safety": round(FEM_MATERIALS[better[0]]["yield"] / vm["max"], 2), "confidence": "high",
                          "how": "setup_analysis(material=...) 다시"})
        # 5) 하중 줄이기
        allow = vm["yield"] / target_safety
        cands.append({"kind": "load", "detail": f"허용 응력 {round(allow, 1)} MPa가 되려면 하중을 {round(allow / vm['max'] * 100.0, 0)} %로 (선형이라 비례)",
                      "expected_safety": target_safety, "confidence": "high", "how": "설계 조건 변경"})
        # 6) 특이점
        if vm["max"] > 3.0 * vm["p99"]:
            cands.append({"kind": "mesh", "detail": f"최대 응력이 상위 1 %({vm['p99']} MPa)의 3배 이상 — 특이점 가능. p99 기준 안전율은 {summary['safety_factor_p99']}. 메시를 절반 크기로 다시 해석해 값이 계속 오르면 특이점(무시하거나 필렛)",
                          "expected_safety": summary["safety_factor_p99"], "confidence": "medium", "how": "setup_analysis(mesh_size=현재/2) → run_analysis"})
        for i, c in enumerate(cands):
            c["id"] = i + 1
    except _FemError as e:
        return util.error(str(e))
    except Exception as e:  # noqa: BLE001
        return util.error(f"보강 제안 실패: {e}", e)
    data = {"document": d.Name, "analysis": an.Name, "safety_factor": sf, "target": target_safety, "stress_reduction_needed": round((1.0 - 1.0 / need) * 100.0, 1),
            "hotspot": vm, "hotspot_selection": hot_notes, "candidates": cands[: int(max_items)], "candidates_total": len(cands)}
    warnings.append("후보는 자동 적용하지 않습니다. 고른 것을 build_features/execute_code로 반영한 뒤 run_analysis로 다시 확인하세요.")
    return util.envelope(data, warnings=warnings, truncated=len(cands) > int(max_items), t0=t0)


TOOLS = {
    "setup_analysis": setup_analysis,
    "run_analysis": run_analysis,
    "inspect_results": inspect_results,
    "suggest_reinforcement": suggest_reinforcement,
}
