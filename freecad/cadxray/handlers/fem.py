"""FEM 구조 해석 툴 (M13, 명세 7.36~7.39).

setup_analysis      — 해석 컨테이너·재질·고정·하중·Gmsh 메시·CalculiX 솔버를 한 번에
run_analysis        — CalculiX 정적 해석 → 최대 응력·변위·안전율, 결과 컬러맵(후처리 파이프라인) 표시
inspect_results     — 응력·변위 상위 지점과 면별 요약, 컬러맵 필드 전환
suggest_reinforcement — 안전율 미달이면 두께·필렛·리브·재질·하중 후보를 번호 목록으로 (자동 적용 없음)

FreeCAD 1.1.3 라이브 확인 사항은 docs/api-notes.md §18. 선형 정적·등방성만 다룬다.
"""

import math
import os
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
    mat = next((o for o in grp if o.isDerivedFrom("App::MaterialObjectPython") or o.TypeId.startswith("App::MaterialObject")), None)
    results = [o for o in grp if o.isDerivedFrom("Fem::FemResultObject")]
    pipes = [o for o in grp if o.TypeId == "Fem::FemPostPipeline"]
    return mesh, solver, mat, results, pipes


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

def setup_analysis(name=None, doc=None, material="PLA", fixed=None, loads=None, mesh_size=None, order="2nd", analysis="Analysis"):
    """해석 컨테이너 + 재질 + 고정 + 하중 + Gmsh 메시 + CalculiX 솔버 (명세 7.36)."""
    t0 = time.time()
    d, err = util.get_doc(doc)
    if err:
        return util.error(err)
    obj, shape, err = _shape_or_error(d, name)
    if err:
        return util.error(err)
    warnings = []
    try:
        import ObjectsFem

        mat = resolve_material(material)
        fixed_sel = fixed if isinstance(fixed, list) else ([fixed] if fixed else [])
        if not fixed_sel:
            raise _FemError("fixed(고정 면)가 필요합니다. 예: [\"bottom\"] 또는 [{\"near\": [x,y,z]}]")
        loads = loads or []
        if not loads:
            warnings.append("하중이 없습니다. self_weight라도 넣어야 의미 있는 결과가 나옵니다.")

        # 기존 같은 이름의 해석은 지운다(구성 재현)
        old = d.getObject(analysis)
        if old is not None:
            if old.TypeId != "Fem::FemAnalysis":
                raise _FemError(f"'{analysis}'는 이미 다른 객체입니다. analysis 이름을 바꾸세요.")
            for o in list(old.Group):
                if o.Name in [x.Name for x in d.Objects]:
                    d.removeObject(o.Name)
            for o in [x for x in d.Objects if x.Name.startswith(analysis + "_dir")]:
                d.removeObject(o.Name)
            d.removeObject(old.Name)
            warnings.append(f"기존 '{analysis}'를 지우고 다시 만들었습니다.")

        an = ObjectsFem.makeAnalysis(d, analysis)
        created = [an.Name]

        mo = ObjectsFem.makeMaterialSolid(d, "Material")
        mo.Material = _fem_material_dict(mat)
        an.addObject(mo)
        created.append(mo.Name)

        fixed_out = []
        for k, sel in enumerate(fixed_sel):
            fl = _resolve_faces(shape, sel)
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
        mesh.SecondOrderLinear = True      # 곡면(나사 등)에서 휜 2차 요소는 CalculiX가 "nonpositive jacobian"으로 거부한다 → 직선 변 [라이브 1.1.3]
        if mesh.ElementOrder == "1st":
            warnings.append("1차 요소는 굽힘 강성을 2배 가까이 과대평가합니다(외팔보 검증). 정확도가 필요하면 order='2nd'.")
        an.addObject(mesh)
        created.append(mesh.Name)
        mesh_info = _run_gmsh(mesh)
        mesh_info.update({"size": float(mesh_size), "order": mesh.ElementOrder})
        if mesh_info["nodes"] > 300000:
            warnings.append(f"절점 {mesh_info['nodes']}개 — 해석이 수 분 걸릴 수 있습니다. mesh_size를 키우세요.")

        sol = ObjectsFem.makeSolverCalculiXCcxTools(d, "Solver")
        sol.AnalysisType = "static"
        sol.WorkingDir = _working_dir(d, an)
        an.addObject(sol)
        created.append(sol.Name)
        d.recompute()
    except _FemError as e:
        return util.error(str(e))
    except Exception as e:  # noqa: BLE001
        return util.error(f"해석 구성 실패: {e}", e)
    data = {"document": d.Name, "object": obj.Name, "label": util.label(obj), "analysis": an.Name, "created": created,
            "material": mat, "fixed": fixed_out, "loads": loads_out, "mesh": mesh_info, "solver": "CalculiX static (2nd-order tets)" if mesh.ElementOrder == "2nd" else "CalculiX static (1st-order tets)",
            "next": f"run_analysis(analysis='{an.Name}')"}
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
        wd = _working_dir(d, an)
        sol.WorkingDir = wd
        t1 = time.time()
        if FreeCAD.ActiveDocument is None or FreeCAD.ActiveDocument.Name != d.Name:
            FreeCAD.setActiveDocument(d.Name)      # ccxtools가 ActiveDocument를 본다 [헤드리스 1.1.3: None이면 getObject 오류]
        fea = ccxtools.FemToolsCcx(an, sol)
        fea.purge_results()
        fea.update_objects()
        fea.setup_working_dir(wd)
        fea.setup_ccx(ccx_binary=_ccx_binary())
        msg = fea.check_prerequisites()
        if msg:
            raise _FemError(f"해석 준비 오류: {msg.strip()}")
        fea.write_inp_file()
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
        mat = _read_material(mat_obj) if mat_obj is not None else None
        summary, w2 = _summarize(res, shape, mat)
        warnings.extend(w2)
        pipe, shown = _show_pipeline(d, an, res, show or "von_mises")
        d.recompute()
    except _FemError as e:
        return util.error(str(e))
    except Exception as e:  # noqa: BLE001
        return util.error(f"해석 실행 실패: {e}", e)
    data = {"document": d.Name, "analysis": an.Name, "object": target.Name, "material": mat, "result": res.Name, "pipeline": pipe.Name,
            "shown_field": shown, "solve_seconds": solve_s, "working_dir": wd, "summary": summary}
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
        if ang < 10.0:
            continue
        q = mid + (n1 - n2) * 0.2
        if shape.isInside(q, 1e-4, True):     # 두 법선 차 방향이 재료 안 → 오목 모서리
            eidx = next((i for i, se in enumerate(shape.Edges, 1) if se.isSame(e)), None)
            if best is None or dist < best[2]:
                best = (eidx, round(ang, 1), dist)
    return best


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
        target = mesh.Shape
        shape = target.Shape
        mat = _read_material(mat_obj) if mat_obj is not None else {}
        if not mat.get("yield"):
            raise _FemError("재질에 항복강도가 없어 안전율을 계산할 수 없습니다.")
        summary, w2 = _summarize(res, shape, mat)
        warnings.extend(w2)
        vm = summary.get("von_mises")
        if not vm:
            raise _FemError("응력 결과가 없습니다.")
        sf = summary["safety_factor"]
        target_safety = float(target_safety)
        need = target_safety / max(sf, 1e-9)              # 응력을 이만큼 줄여야 한다
        p = Vec(*vm["at"])
        fidx = int(vm["face"][4:]) if vm.get("face") else None
        cands = []
        if sf >= target_safety:
            data = {"document": d.Name, "analysis": an.Name, "safety_factor": sf, "target": target_safety, "summary": summary, "candidates": [],
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
        better = [k for k, m in FEM_MATERIALS.items() if m["yield"] / vm["max"] >= target_safety and k != mat.get("name")]
        if better:
            cands.append({"kind": "material", "detail": f"재질 변경으로 목표 달성: {', '.join(better[:6])} (항복강도/최대응력 ≥ {target_safety})",
                          "expected_safety": round(FEM_MATERIALS[better[0]]["yield"] / vm["max"], 2), "confidence": "high",
                          "how": "setup_analysis(material=...) 다시"})
        # 5) 하중 줄이기
        allow = mat["yield"] / target_safety
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
            "hotspot": vm, "candidates": cands[: int(max_items)], "candidates_total": len(cands)}
    warnings.append("후보는 자동 적용하지 않습니다. 고른 것을 build_features/execute_code로 반영한 뒤 run_analysis로 다시 확인하세요.")
    return util.envelope(data, warnings=warnings, truncated=len(cands) > int(max_items), t0=t0)


TOOLS = {
    "setup_analysis": setup_analysis,
    "run_analysis": run_analysis,
    "inspect_results": inspect_results,
    "suggest_reinforcement": suggest_reinforcement,
}
