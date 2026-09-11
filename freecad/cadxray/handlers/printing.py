"""3D 프린트 출력용 검사·추정·방향·수정 (M12, 명세 7.31~7.35).

check_printability: 얇은 벽·오버행·브릿지·작은/수평 구멍·베드 적합·첫 층 접지 → 점수·issues·fixes
estimate_print: 재료 부피·무게·필라멘트 길이·대략 시간·비용
suggest_orientation: 6방향 + 현재 방향 채점
apply_print_fixes: elephant_foot / hole_comp / teardrop 을 PartDesign 피처로

광선은 형상을 메시로 바꿔 Mesh.nearestFacetOnRay로 쏜다(빠르다) [api-notes 16장]. 출력 방향 +Z, 바닥 = bbox ZMin.
재질 표는 슬라이서 기본값 수준의 경험값이다 — profile로 덮어쓴다.
"""

import math
import time

import FreeCAD
import Part

from . import util

Vec = FreeCAD.Vector

# 경험값: 밀도 g/cm3, 서포트 없이 되는 최대 기울기(수직 기준 °), 브릿지 최대 스팬 mm, 수직 구멍 지름 보정 mm, 수축률 %
MATERIALS = {
    "PLA": {"density": 1.24, "overhang_deg": 50.0, "bridge_max": 40.0, "hole_comp": 0.2, "shrink_pct": 0.3},
    "PETG": {"density": 1.27, "overhang_deg": 45.0, "bridge_max": 25.0, "hole_comp": 0.25, "shrink_pct": 0.5},
    "ABS": {"density": 1.04, "overhang_deg": 45.0, "bridge_max": 20.0, "hole_comp": 0.3, "shrink_pct": 0.8},
    "ASA": {"density": 1.07, "overhang_deg": 45.0, "bridge_max": 20.0, "hole_comp": 0.3, "shrink_pct": 0.7},
    "TPU": {"density": 1.21, "overhang_deg": 40.0, "bridge_max": 10.0, "hole_comp": 0.3, "shrink_pct": 0.8},
    "NYLON": {"density": 1.14, "overhang_deg": 40.0, "bridge_max": 15.0, "hole_comp": 0.35, "shrink_pct": 1.5},
}
_DEFAULT_PROFILE = {"material": "PLA", "nozzle": 0.4, "layer": 0.2, "bed": [220.0, 220.0, 250.0], "walls": 3, "infill": 20.0, "price_per_kg": 25000.0}


class _PrintError(Exception):
    pass


def resolve_profile(profile):
    """사용자 profile + 재질 표 → 완성된 프로파일. 알 수 없는 재질은 오류."""
    p = dict(_DEFAULT_PROFILE)
    p.update({k: v for k, v in (profile or {}).items() if v is not None})
    mat = str(p.get("material", "PLA")).upper()
    if mat not in MATERIALS:
        raise _PrintError(f"모르는 재질 {p.get('material')!r}. 가능: {', '.join(MATERIALS)} (또는 min_wall·overhang_deg·bridge_max·hole_comp·density를 직접 주세요)")
    m = MATERIALS[mat]
    p["material"] = mat
    p.setdefault("density", m["density"])
    p.setdefault("overhang_deg", m["overhang_deg"])
    p.setdefault("bridge_max", m["bridge_max"])
    p.setdefault("hole_comp", m["hole_comp"])
    p.setdefault("shrink_pct", m["shrink_pct"])
    p.setdefault("min_wall", 2.0 * float(p["nozzle"]))
    p.setdefault("min_hole", max(2.0, 2.0 * float(p["nozzle"])))   # 2 mm 미만 구멍은 FDM에서 막히거나 찌그러진다(경험값)
    for k in ("nozzle", "layer", "infill", "min_wall", "min_hole", "overhang_deg", "bridge_max", "hole_comp", "density", "price_per_kg"):
        p[k] = float(p[k])
    p["walls"] = int(p["walls"])
    p["bed"] = [float(v) for v in p["bed"]]
    return p


def _shape_or_error(d, name):
    obj, err = util.find_object(d, name)
    if err:
        return None, None, err
    if not hasattr(obj, "Shape") or obj.Shape.isNull():
        return obj, None, f"'{obj.Name}'에 형상이 없습니다."
    if not obj.Shape.Solids:
        return obj, None, f"'{obj.Name}'에 솔리드가 없습니다(면만 있음). 메시면 먼저 다시 그리세요."
    return obj, obj.Shape, None


_INSET = 0.1    # 광선 출발점을 면 안쪽으로 넣는 거리 (> 메시 편차 0.05)


def _mesh_of(shape, deflection=0.05):
    import MeshPart

    return MeshPart.meshFromShape(Shape=shape, LinearDeflection=deflection, AngularDeflection=0.3, Relative=False)


def _ray(mesh, p, d, back_off=0.0):
    """p에서 d 방향으로 광선. 맞은 점까지 거리(p 기준) 또는 None.

    back_off<0이면 p에서 d 쪽으로 |back_off|만큼 들어간 곳에서 출발(자기 면을 피한다). 반환값은 항상 p 기준 거리.
    nearestFacetOnRay는 직선 교차라 뒤쪽 면을 돌려주므로 foraminate로 전부 받아 앞쪽(t>0)만 고른다 [라이브 1.1.3].
    """
    s = Vec(p.x - d.x * back_off, p.y - d.y * back_off, p.z - d.z * back_off)
    try:
        hits = mesh.foraminate((s.x, s.y, s.z), (d.x, d.y, d.z))
    except Exception:  # noqa: BLE001
        return None
    best = None
    for q in hits.values():
        t = (Vec(*q) - s).dot(d)
        if t > 1e-4 and (best is None or t < best):
            best = t
    return None if best is None else best - back_off


def _face_samples(face, n_side):
    u0, u1, v0, v1 = face.ParameterRange
    out = []
    for i in range(n_side):
        for j in range(n_side):
            u = u0 + (u1 - u0) * (i + 0.5) / n_side
            v = v0 + (v1 - v0) * (j + 0.5) / n_side
            if not face.isPartOfDomain(u, v):
                continue
            p = face.valueAt(u, v)
            n = face.normalAt(u, v)     # 솔리드의 바깥 법선 (Orientation 반영됨 — 직접 뒤집으면 바닥면을 놓친다 [라이브 1.1.3])
            out.append((p, n))
    if out:
        return out
    # 격자가 전부 구멍·바깥에 떨어진 면(구멍 많은 바닥판 등) → 삼각분할 무게중심으로 대체 [라이브 1.1.3: 스풀 가이드 바닥 Face20이 4×4 격자에서 0점]
    try:
        verts, tris = face.tessellate(1.0)
    except Exception:  # noqa: BLE001
        return out
    step = max(1, len(tris) // max(n_side * n_side, 1))
    for k in range(0, len(tris), step):
        a, b, c = (verts[i] for i in tris[k])
        cen = Vec((a.x + b.x + c.x) / 3, (a.y + b.y + c.y) / 3, (a.z + b.z + c.z) / 3)
        try:
            u, v = face.Surface.parameter(cen)
            out.append((face.valueAt(u, v), face.normalAt(u, v)))
        except Exception:  # noqa: BLE001
            continue
    return out


def _analyze(shape, prof, samples=2000, max_items=30, with_holes=True, doc=None, obj=None):
    """check_printability의 본체. shape는 이미 놓인 상태(출력 방향 +Z)."""
    bb = shape.BoundBox
    zmin = bb.ZMin
    mesh = _mesh_of(shape)
    faces = shape.Faces
    per_face = max(2, int(math.sqrt(max(samples, 16) / max(len(faces), 1))) + 1)
    limit_tilt = prof["overhang_deg"]
    thin_spots, tmin = [], None
    over_faces = []
    support_area = 0.0
    bottom_area = 0.0
    bridge_faces = []
    for fi, f in enumerate(faces, 1):
        pts = _face_samples(f, min(per_face, max(2, int(math.sqrt(f.Area) / 4) + 2)))
        if not pts:
            continue
        # --- 얇은 벽: 안쪽으로 광선. 메시가 실제 면에서 0.05까지 벗어나므로 0.1 안쪽에서 출발해 자기 면을 피한다
        local_min = None
        for p, n in pts:
            t = _ray(mesh, p, Vec(-n.x, -n.y, -n.z), back_off=-_INSET)
            if t is not None and (local_min is None or t < local_min[0]):
                local_min = (t, p)
        if local_min and local_min[0] < prof["min_wall"]:
            thin_spots.append({"face": f"Face{fi}", "thickness": round(local_min[0], 3), "point": [round(local_min[1].x, 2), round(local_min[1].y, 2), round(local_min[1].z, 2)]})
        if local_min and (tmin is None or local_min[0] < tmin):
            tmin = local_min[0]
        # --- 오버행: 아래를 향한 표본
        down = [(p, n) for p, n in pts if n.z < -1e-6]
        if not down:
            continue
        nz = sum(n.z for p, n in down) / len(down)
        tilt = math.degrees(math.asin(max(-1.0, min(1.0, -nz))))     # 수직 벽 0°, 수평 아래면 90°
        on_bed = all(abs(p.z - zmin) < 0.05 for p, n in down)
        if on_bed:
            bottom_area += f.Area
            over_faces.append({"face": f"Face{fi}", "tilt_deg": round(tilt, 1), "area": round(f.Area, 2), "kind": "bottom"})
            continue
        if tilt <= limit_tilt:
            continue
        # 아래가 비어 있나: 아래로 광선 (자기 자신 제외)
        gaps = []
        for p, n in down:
            g = _ray(mesh, p, Vec(0, 0, -1), back_off=-_INSET)
            gaps.append(g if g is not None else (p.z - zmin))
        gap = min(gaps) if gaps else 0.0
        if gap < prof["layer"] * 0.5:
            continue                       # 바로 아래에 재료가 있다 (접촉)
        kind = "overhang"
        span = None
        # 수평으로 뻗은 폭(reach)이 노즐 2배 이하면 층마다 조금씩 나가는 것이라 서포트 없이 된다(나사 플랭크·작은 챔퍼)
        nx, ny = sum(n.x for p, n in down) / len(down), sum(n.y for p, n in down) / len(down)
        fb0 = f.BoundBox
        reach = abs(nx) * fb0.XLength + abs(ny) * fb0.YLength
        if tilt <= 89.0 and reach <= max(2.0 * prof["nozzle"], 1.0):
            over_faces.append({"face": f"Face{fi}", "tilt_deg": round(tilt, 1), "area": round(f.Area, 2), "kind": "minor", "reach": round(reach, 2)})
            continue
        if tilt > 89.0:
            # 수평 아래면: 짧은 변 방향 양끝 바깥에 재료가 있어야 브릿지(캔틸레버는 한쪽만 지지 → 오버행)
            fb = f.BoundBox
            along_x = fb.XLength <= fb.YLength
            span = round(fb.XLength if along_x else fb.YLength, 2)
            zc = fb.ZMin - 0.1
            if along_x:
                ends = [Vec(fb.XMin - 0.3, fb.Center.y, zc), Vec(fb.XMax + 0.3, fb.Center.y, zc)]
            else:
                ends = [Vec(fb.Center.x, fb.YMin - 0.3, zc), Vec(fb.Center.x, fb.YMax + 0.3, zc)]
            supported = all(_ray(mesh, e, Vec(0, 0, -1)) is not None or shape.isInside(e, 1e-3, True) for e in ends)
            if supported and span <= prof["bridge_max"]:
                kind = "bridge"
        rec = {"face": f"Face{fi}", "tilt_deg": round(tilt, 1), "area": round(f.Area, 2), "kind": kind, "gap": round(gap, 2)}
        if span is not None:
            rec["span"] = span
        over_faces.append(rec)
        if kind == "bridge":
            bridge_faces.append(rec)
        else:
            support_area += f.Area
    thin_spots.sort(key=lambda t: t["thickness"])
    over_faces.sort(key=lambda t: (t["kind"] == "bottom", -t["area"]))
    # --- 구멍
    small, horizontal, vertical = [], [], []
    if with_holes and obj is not None and doc is not None:
        from .shape_features import find_holes

        r = find_holes(name=obj.Name, doc=doc.Name, max_holes=200)
        if r.get("ok"):
            for h in r["data"]["holes"]:
                ax = Vec(*h["axis"])
                rec = {"diameter": h["diameter"], "center": h["center"], "axis": h["axis"], "through": h.get("through"), "depth": h.get("depth")}
                if h["diameter"] < prof["min_hole"]:
                    small.append(rec)
                if abs(ax.z) < 0.2:
                    horizontal.append(rec)
                elif abs(ax.z) > 0.98:
                    vertical.append(rec)
    # --- 베드
    bed = prof["bed"]
    fits = (bb.XLength <= bed[0] and bb.YLength <= bed[1]) or (bb.XLength <= bed[1] and bb.YLength <= bed[0])
    fits = fits and bb.ZLength <= bed[2]
    # --- 점수·issues
    issues, fixes = [], []
    score = 100.0
    if not fits:
        issues.append({"kind": "bed", "severity": "high", "detail": f"베드 {bed[0]}×{bed[1]}×{bed[2]}에 안 들어갑니다: {round(bb.XLength, 1)}×{round(bb.YLength, 1)}×{round(bb.ZLength, 1)}", "fix": "manual: 축소·분할"})
        score -= 30
    if thin_spots:
        issues.append({"kind": "thin_wall", "severity": "high" if thin_spots[0]["thickness"] < prof["nozzle"] else "medium",
                       "detail": f"노즐 {prof['nozzle']}에서 최소 벽 {prof['min_wall']} mm 미만인 곳 {len(thin_spots)}곳 (가장 얇은 {thin_spots[0]['thickness']} mm, {thin_spots[0]['face']})", "fix": "manual: 두께를 노즐 배수(0.8·1.2·1.6)로"})
        score -= min(25, 5 * len(thin_spots))
    if support_area > 0:
        worst = [o for o in over_faces if o["kind"] == "overhang"][:5]
        issues.append({"kind": "overhang", "severity": "medium", "detail": f"서포트가 필요한 면적 {round(support_area, 1)} mm² ({len([o for o in over_faces if o['kind'] == 'overhang'])}면, 한계 {limit_tilt}°): " + ", ".join(f"{o['face']} {o['tilt_deg']}°" for o in worst),
                       "fix": "suggest_orientation 또는 45° 챔퍼로 오버행 줄이기(manual)"})
        score -= min(25, support_area / 100.0)
    if bridge_faces:
        issues.append({"kind": "bridge", "severity": "low", "detail": f"브릿지 {len(bridge_faces)}곳 (최대 스팬 {max(b['span'] for b in bridge_faces)} mm ≤ {prof['bridge_max']})", "fix": "냉각 강화·속도 낮춤(슬라이서)"})
        score -= 3
    if small:
        issues.append({"kind": "small_hole", "severity": "medium", "detail": f"노즐×2({prof['min_hole']}) 미만 구멍 {len(small)}개: " + ", ".join(f"Ø{h['diameter']}" for h in small[:5]), "fix": "manual: 키우거나 후가공(드릴)"})
        score -= 5
    if horizontal:
        issues.append({"kind": "horizontal_hole", "severity": "low", "detail": f"수평 구멍 {len(horizontal)}개 (위쪽이 처짐): " + ", ".join(f"Ø{h['diameter']}" for h in horizontal[:5]), "fix": "teardrop"})
        fixes.append({"fix": "teardrop", "holes": [h["center"] for h in horizontal], "detail": "수평 구멍 위에 45° 눈물방울"})
        score -= 3
    if vertical:
        fixes.append({"fix": "hole_comp", "holes": "vertical", "comp": prof["hole_comp"], "detail": f"수직 구멍 {len(vertical)}개 지름 +{prof['hole_comp']} ({prof['material']} 수축 보정)"})
    fixes.append({"fix": "elephant_foot", "size": round(max(prof["layer"] * 1.5, 0.3), 2), "detail": "바닥 바깥 모서리 챔퍼(첫 층 퍼짐 보정)"})
    ratio = (bb.ZLength / math.sqrt(bottom_area)) if bottom_area > 1e-6 else None
    if ratio is not None and ratio > 4:
        issues.append({"kind": "adhesion", "severity": "medium", "detail": f"키가 크고 접지가 작습니다(높이/√접지 = {round(ratio, 1)}). 넘어짐·뒤틀림 위험", "fix": "suggest_orientation / 브림"})
        score -= 5
    if bottom_area < 1e-6:
        issues.append({"kind": "adhesion", "severity": "high", "detail": "바닥에 평평한 면이 없습니다", "fix": "suggest_orientation"})
        score -= 15
    for i, it in enumerate(issues):
        it["id"] = i + 1
    return {
        "profile_used": prof, "bbox": util.serialize(bb), "fits_bed": fits, "bottom_area": round(bottom_area, 2), "volume": round(shape.Volume, 2),
        "thin_walls": {"min_thickness": round(tmin, 3) if tmin is not None else None, "min_wall": prof["min_wall"], "spots": thin_spots[:max_items], "spots_total": len(thin_spots)},
        "overhangs": {"support_area": round(support_area, 2), "limit_deg": limit_tilt, "bridges": len(bridge_faces),
                      "minor": len([o for o in over_faces if o["kind"] == "minor"]),
                      "faces": [o for o in over_faces if o["kind"] not in ("bottom", "minor")][:max_items], "faces_total": len([o for o in over_faces if o["kind"] not in ("bottom", "minor")])},
        "holes": {"small": small[:max_items], "horizontal": horizontal[:max_items], "vertical": len(vertical)},
        "score": int(round(max(0.0, score))), "issues": issues, "fixes": fixes,
    }


def check_printability(name=None, doc=None, profile=None, samples=2000, max_items=30):
    """출력 가능성 검사 (명세 7.32)."""
    t0 = time.time()
    d, err = util.get_doc(doc)
    if err:
        return util.error(err)
    obj, shape, err = _shape_or_error(d, name)
    if err:
        return util.error(err)
    try:
        prof = resolve_profile(profile)
        data = _analyze(shape, prof, samples=int(samples), max_items=int(max_items), doc=d, obj=obj)
    except _PrintError as e:
        return util.error(str(e))
    except Exception as e:  # noqa: BLE001
        return util.error(f"검사 실패: {e}", e)
    data.update({"document": d.Name, "object": obj.Name, "label": util.label(obj)})
    warnings = ["재질 표 값은 경험값입니다(슬라이서 기본값 수준). profile로 덮어쓰세요."]
    truncated = data["thin_walls"]["spots_total"] > max_items or data["overhangs"]["faces_total"] > max_items
    return util.envelope(data, warnings=warnings, truncated=truncated, t0=t0)


def estimate_print(name=None, doc=None, profile=None, speed=50.0):
    """재료·무게·길이·시간·비용 대략 추정 (명세 7.33)."""
    t0 = time.time()
    d, err = util.get_doc(doc)
    if err:
        return util.error(err)
    obj, shape, err = _shape_or_error(d, name)
    if err:
        return util.error(err)
    try:
        prof = resolve_profile(profile)
    except _PrintError as e:
        return util.error(str(e))
    vol = shape.Volume
    area = shape.Area
    wall_t = prof["walls"] * prof["nozzle"]
    shell = min(vol, area * wall_t)                      # 벽 + 상하면 근사
    inner = max(vol - shell, 0.0) * prof["infill"] / 100.0
    v_mat = shell + inner
    mass = v_mat / 1000.0 * prof["density"]
    fil_len_m = v_mat / (math.pi * 0.875 ** 2) / 1000.0
    extrude_rate = prof["nozzle"] * prof["layer"] * float(speed)   # mm3/s
    time_h = v_mat / extrude_rate / 3600.0 * 1.3
    data = {"document": d.Name, "object": obj.Name, "material": prof["material"], "density": prof["density"],
            "volume_model": round(vol, 1), "volume_material": round(v_mat, 1), "shell_volume": round(shell, 1), "infill_volume": round(inner, 1),
            "mass_g": round(mass, 1), "filament_m": round(fil_len_m, 2), "time_h": round(time_h, 2), "cost": round(mass / 1000.0 * prof["price_per_kg"]),
            "assumptions": {"walls": prof["walls"], "nozzle": prof["nozzle"], "layer": prof["layer"], "infill_pct": prof["infill"], "speed_mm_s": float(speed), "travel_factor": 1.3}}
    return util.envelope(data, warnings=["슬라이서보다 거친 추정(±30 %)입니다."], t0=t0)


_ORIENTATIONS = [
    ("current", None, 0.0),
    ("+Z down (flip)", Vec(1, 0, 0), 180.0),
    ("-X down", Vec(0, 1, 0), -90.0),
    ("+X down", Vec(0, 1, 0), 90.0),
    ("-Y down", Vec(1, 0, 0), 90.0),
    ("+Y down", Vec(1, 0, 0), -90.0),
]


def suggest_orientation(name=None, doc=None, profile=None, apply=None, samples=800):
    """6방향 + 현재 방향을 채점해 순위 (명세 7.34). apply=순위 index면 그 회전을 적용."""
    t0 = time.time()
    d, err = util.get_doc(doc)
    if err:
        return util.error(err)
    obj, shape, err = _shape_or_error(d, name)
    if err:
        return util.error(err)
    try:
        prof = resolve_profile(profile)
    except _PrintError as e:
        return util.error(str(e))
    results = []
    for label, axis, ang in _ORIENTATIONS:
        s = shape.copy()
        if axis is not None:
            s.rotate(Vec(0, 0, 0), axis, ang)
        try:
            a = _analyze(s, prof, samples=int(samples), max_items=5, with_holes=False)
        except Exception as e:  # noqa: BLE001
            results.append({"orientation": label, "error": str(e)})
            continue
        bb = s.BoundBox
        score = 100.0 - min(40.0, a["overhangs"]["support_area"] / 100.0) - (0 if a["fits_bed"] else 30) - min(15.0, bb.ZLength / 20.0) \
            + min(15.0, a["bottom_area"] / 200.0)
        results.append({"orientation": label, "rotation": {"axis": [axis.x, axis.y, axis.z] if axis else None, "angle": ang},
                        "support_area": a["overhangs"]["support_area"], "bottom_area": a["bottom_area"], "height": round(bb.ZLength, 2),
                        "fits_bed": a["fits_bed"], "bridges": a["overhangs"]["bridges"], "score": round(score, 1)})
    ranked = sorted([r for r in results if "error" not in r], key=lambda r: -r["score"])
    for i, r in enumerate(ranked):
        r["rank"] = i + 1
    applied = None
    if apply is not None:
        try:
            pick = ranked[int(apply) - 1]
        except Exception:
            return util.error(f"apply는 1..{len(ranked)} 순위 번호여야 합니다.")
        rot = pick["rotation"]
        pl = obj.Placement
        if rot["axis"] is not None:
            extra = FreeCAD.Rotation(Vec(*rot["axis"]), rot["angle"])
            pl = FreeCAD.Placement(pl.Base, extra.multiply(pl.Rotation))
        obj.Placement = pl
        d.recompute()
        bb = obj.Shape.BoundBox
        obj.Placement = FreeCAD.Placement(Vec(pl.Base.x, pl.Base.y, pl.Base.z - bb.ZMin), pl.Rotation)
        d.recompute()
        applied = {"rank": pick["rank"], "orientation": pick["orientation"], "placement": util.serialize(obj.Placement)}
    data = {"document": d.Name, "object": obj.Name, "candidates": ranked, "best": ranked[0] if ranked else None, "applied": applied,
            "hint": "rank 1이 서포트 최소·접지 최대·낮은 높이. 마음에 들면 apply=<rank>로 적용(바닥을 z=0에 놓는다)."}
    return util.envelope(data, t0=t0)


def apply_print_fixes(name=None, doc=None, profile=None, fixes=None):
    """elephant_foot / hole_comp / teardrop 을 Body에 PartDesign 피처로 (명세 7.35)."""
    t0 = time.time()
    d, err = util.get_doc(doc)
    if err:
        return util.error(err)
    obj, shape, err = _shape_or_error(d, name)
    if err:
        return util.error(err)
    if obj.TypeId != "PartDesign::Body":
        return util.error(f"'{obj.Name}'은(는) PartDesign::Body가 아닙니다({obj.TypeId}). 피처를 쌓으려면 Body가 필요합니다.")
    if not fixes:
        return util.error("fixes 목록이 필요합니다: [{'fix': 'elephant_foot'|'hole_comp'|'teardrop', ...}]")
    try:
        prof = resolve_profile(profile)
    except _PrintError as e:
        return util.error(str(e))
    from .rebuild import build_features
    from .shape_features import find_holes

    v_before = shape.Volume
    bb = shape.BoundBox
    applied, skipped = [], []
    holes_r = find_holes(name=obj.Name, doc=d.Name, max_holes=200)
    holes = [h for h in (holes_r["data"]["holes"] if holes_r.get("ok") else []) if h.get("kind", "hole") == "hole"]
    for k, fx in enumerate(fixes):
        kind = str(fx.get("fix", "")).lower()
        try:
            if kind == "elephant_foot":
                size = float(fx.get("size", max(prof["layer"] * 1.5, 0.3)))
                feats = [{"op": "chamfer", "name": f"ElephantFoot{k + 1}", "size": size,
                          "edges": {"bbox": {"min": [None, None, bb.ZMin - 0.01], "max": [None, None, bb.ZMin + 0.01]}}}]
                r = build_features(body=obj.Name, doc=d.Name, create_body=False, features=feats)
            elif kind == "hole_comp":
                comp = float(fx.get("comp") or prof["hole_comp"])
                which = fx.get("holes", "vertical")
                sel = [h for h in holes if (which == "all" or abs(Vec(*h["axis"]).z) > 0.98)]
                if not sel:
                    skipped.append({"fix": kind, "reason": "보정할 수직 구멍이 없습니다."}); continue
                # 구멍마다 위쪽 끝에서 아래로 (depth) 파는 Pocket
                feats = []
                for i, h in enumerate(sel):
                    top = max(h["start"][2], h["end"][2])
                    depth = float(h.get("depth") or abs(h["start"][2] - h["end"][2]))
                    feats.append({"op": "pocket", "name": f"HoleComp{k + 1}_{i + 1}", "plane": "XY", "position": top,
                                  "length": depth + 0.01 if not h.get("through") else None, "through": bool(h.get("through")),
                                  "profile": {"circles": [{"center": [h["center"][0], h["center"][1]], "diameter": h["diameter"] + comp}]}})
                    if feats[-1]["length"] is None:
                        del feats[-1]["length"]
                r = build_features(body=obj.Name, doc=d.Name, create_body=False, features=feats)
            elif kind == "teardrop":
                sel = [h for h in holes if abs(Vec(*h["axis"]).z) < 0.2]
                want = fx.get("holes")
                if want:
                    sel = [h for h in sel if any(Vec(*h["center"]).distanceToPoint(Vec(*c)) < 1.0 for c in want)]
                if not sel:
                    skipped.append({"fix": kind, "reason": "수평 구멍이 없습니다."}); continue
                feats = []
                for i, h in enumerate(sel):
                    ax = Vec(*h["axis"]); r_ = h["diameter"] / 2.0
                    cx, cy, cz = h["center"]
                    depth = float(h.get("depth") or abs(Vec(*h["start"]).distanceToPoint(Vec(*h["end"])))) + 0.02
                    # 축이 X면 YZ 평면(로컬 Y,Z), 축이 Y면 XZ 평면(로컬 X,Z)
                    if abs(ax.x) > 0.8:
                        plane, pos, cu = "YZ", min(h["start"][0], h["end"][0]) - 0.01, cy
                        reversed_ = False
                    elif abs(ax.y) > 0.8:
                        plane, pos, cu = "XZ", max(h["start"][1], h["end"][1]) + 0.01, cx
                        reversed_ = False
                    else:
                        skipped.append({"fix": kind, "reason": f"축이 X/Y가 아닌 수평 구멍은 v1에서 안 됩니다: {h['axis']}"}); continue
                    apex = r_ * math.sqrt(2.0)
                    a45 = r_ / math.sqrt(2.0)
                    els = [
                        {"type": "arc", "center": [cu, cz], "radius": r_, "start": [cu + a45, cz + a45], "end": [cu - a45, cz + a45], "ccw": True},   # 아래쪽 270°
                        {"type": "line", "start": [cu - a45, cz + a45], "end": [cu, cz + apex]},
                        {"type": "line", "start": [cu, cz + apex], "end": [cu + a45, cz + a45]},
                    ]
                    spec = {"op": "pocket", "name": f"Teardrop{k + 1}_{i + 1}", "plane": plane, "position": pos, "profile": {"elements": els}}
                    if h.get("through"):
                        spec["through"] = True
                    else:
                        spec["length"] = depth
                    if plane == "XZ":
                        spec["reversed"] = True     # XZ 포켓 기본 +Y → 재료 안쪽(-Y)으로
                    feats.append(spec)
                if not feats:
                    continue
                r = build_features(body=obj.Name, doc=d.Name, create_body=False, features=feats)
            else:
                skipped.append({"fix": kind, "reason": "모르는 fix. elephant_foot / hole_comp / teardrop"}); continue
            if not r["ok"]:
                skipped.append({"fix": kind, "reason": r.get("error")}); continue
            st = r["data"].get("stopped_at")
            for c in r["data"]["created"]:
                applied.append({"fix": kind, "feature": c["name"], "status": c["status"][:60], "volume_after": c.get("volume_after")})
            if st:
                skipped.append({"fix": kind, "reason": f"{st} 실패: " + next((c["status"] for c in r["data"]["created"] if c["name"] == st), "?")})
        except Exception as e:  # noqa: BLE001
            skipped.append({"fix": kind, "reason": f"{type(e).__name__}: {e}"})
    d.recompute()
    data = {"document": d.Name, "object": obj.Name, "applied": applied, "skipped": skipped,
            "volume_before": round(v_before, 2), "volume_after": round(obj.Shape.Volume, 2), "valid": bool(obj.Shape.isValid()),
            "hint": "되돌리려면 만들어진 피처를 지운다. 확인은 check_printability를 다시 부른다."}
    return util.envelope(data, t0=t0)


TOOLS = {"check_printability": check_printability, "estimate_print": estimate_print, "suggest_orientation": suggest_orientation,
         "apply_print_fixes": apply_print_fixes}
