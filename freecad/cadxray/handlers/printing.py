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


def _planar_normal(f):
    try:
        if f.Surface.__class__.__name__ != "Plane":
            return None
        u0, u1, v0, v1 = f.ParameterRange
        return f.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
    except Exception:  # noqa: BLE001
        return None


def _attached_edges(shape, f, n):
    """평면 오버행 면 f(바깥 법선 n, 아래쪽)에서 재료에 붙어 있는 모서리들: [(edge, mid, o)] o = 면 안쪽에서 바깥으로 나가는 면내 방향."""
    out = []
    for e in f.OuterWire.Edges:
        try:
            mid = e.valueAt((e.FirstParameter + e.LastParameter) / 2)
            t = e.tangentAt((e.FirstParameter + e.LastParameter) / 2)
        except Exception:  # noqa: BLE001
            continue
        o = t.cross(n)
        if o.Length < 1e-9:
            continue
        o.normalize()
        if f.isInside(mid + o * 0.2, 1e-4, True):     # 안쪽을 향하면 뒤집는다
            o = o * -1.0
        q = mid + o * 0.3 - n * 0.3                     # 모서리 너머 + 재료 쪽(법선 반대)
        if shape.isInside(q, 1e-4, True):
            out.append((e, mid, o))
    return out


def _wedge_below(shape, f, n, angle_deg=45.0):
    """f 아래를 45°(angle) 경사로 메우는 솔리드. 붙은 모서리에서 멀어질수록 tan(angle)만큼 내려간다. 없으면 None."""
    att = _attached_edges(shape, f, n)
    if not att or len(att) >= len(f.OuterWire.Edges):
        return None
    angle_deg = max(5.0, float(angle_deg) - 1.0)      # 한계각보다 1° 세워서 다시 검사해도 오버행으로 안 잡히게
    zmin = shape.BoundBox.ZMin
    fb = f.BoundBox
    # 붙은 모서리에서 가장 먼 점까지의 수평 거리
    reach = 0.0
    for v in f.Vertexes:
        dmin = min(e.distToShape(Part.Vertex(v.Point))[0] for e, _, _ in att)
        reach = max(reach, dmin)
    drop = reach / math.tan(math.radians(angle_deg)) + fb.ZLength
    depth = min(drop, fb.ZMax - zmin) + 0.01
    if depth <= 0.05:
        return None
    solid = f.extrude(Vec(0, 0, -depth))
    size = shape.BoundBox.DiagonalLength * 2.0 + 10.0
    for e, mid, o in att:
        # o는 면에서 벽 쪽(모서리 너머)으로 나가는 방향. 벽에서 멀어지는 방향 a = -o 로 갈수록 tan(angle)만큼 내려가는 경사면:
        # (p-mid)·a ≤ (mid.z - p.z)·tan  ⇔  (p-mid)·N ≤ 0,  N = a + Z·tan(angle)  → N 반대쪽을 남긴다
        # 남길 쪽: 벽에서 d만큼 떨어진 곳의 바닥 z ≥ z0 − d/tan(angle) ⇔ (p−mid)·N ≥ 0 (angle은 수직 기준 기울기 = 오버행 한계각과 같은 척도)
        a = Vec(-o.x, -o.y, 0.0)                     # o는 기운 면 안의 방향이라 수평 성분만 쓴다(아니면 각도가 어긋난다)
        if a.Length < 1e-9:
            continue
        a.normalize()
        N = Vec(a.x, a.y, math.tan(math.radians(angle_deg)))
        N.normalize()
        # makeHalfSpace + common은 무한 반공간이라 잘리지 않는다 [라이브 1.1.3] → 로컬 Z를 −N에 맞춘 큰 상자를 −N 쪽(버릴 쪽)에 놓고 cut
        rot = FreeCAD.Rotation(Vec(0, 0, 1), N * -1.0)
        box = Part.makeBox(size, size, size)
        box.Placement = FreeCAD.Placement(mid - rot.multVec(Vec(size / 2, size / 2, 0)), rot)
        try:
            solid = solid.cut(box)
        except Exception:  # noqa: BLE001
            return None
    # 모델 바닥 아래로는 안 내려간다
    if solid.BoundBox.ZMin < zmin - 1e-6:
        box = Part.makeBox(size, size, size, Vec(fb.Center.x - size / 2, fb.Center.y - size / 2, zmin))
        solid = solid.common(box)
    if solid.isNull() or solid.Volume < 1e-6:
        return None
    return solid


def _split_pieces(shape, axis, count=None, size=None, positions=None):
    """축 방향으로 잘라 조각 솔리드 목록. positions(절단 좌표) > count > size 순."""
    bb = shape.BoundBox
    lo, hi = getattr(bb, axis.upper() + "Min"), getattr(bb, axis.upper() + "Max")
    if positions:
        cuts = sorted(float(x) for x in positions if lo < float(x) < hi)
    else:
        if not count:
            count = max(2, int(math.ceil((hi - lo) / float(size))))
        step = (hi - lo) / int(count)
        cuts = [lo + step * i for i in range(1, int(count))]
    bounds = [lo - 1.0] + cuts + [hi + 1.0]
    pieces = []
    big = bb.DiagonalLength * 2 + 10
    for i in range(len(bounds) - 1):
        a, b = bounds[i], bounds[i + 1]
        if axis == "x":
            box = Part.makeBox(b - a, big, big, Vec(a, bb.YMin - 1, bb.ZMin - 1))
        elif axis == "y":
            box = Part.makeBox(big, b - a, big, Vec(bb.XMin - 1, a, bb.ZMin - 1))
        else:
            box = Part.makeBox(big, big, b - a, Vec(bb.XMin - 1, bb.YMin - 1, a))
        piece = shape.common(box)
        if not piece.isNull() and piece.Volume > 1e-6:
            pieces.append(piece)
    return cuts, pieces


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
    # --- M15 자동 수정 후보: 평면 얇은 면은 Pad로 두껍게, 붙은 모서리가 있는 평면 오버행은 45° 쐐기, 베드 초과는 분할
    thick_faces = []
    for t in thin_spots:
        f = faces[int(t["face"][4:]) - 1]
        if _planar_normal(f) is not None and f.Area > 1.0:
            thick_faces.append({"face": t["face"], "point": t["point"], "thickness": t["thickness"], "add": round(prof["min_wall"] - t["thickness"] + 0.05, 3)})
    if thick_faces:
        fixes.append({"fix": "thicken", "faces": [x["face"] for x in thick_faces][:max_items], "spots": thick_faces[:max_items],
                      "detail": f"평면 얇은 면 {len(thick_faces)}곳을 바깥쪽으로 Pad 해 {prof['min_wall']} mm로 (같은 벽의 양면이 잡히면 한쪽만 적용)"})
    wedge_faces = []
    for o in over_faces:
        if o["kind"] != "overhang":
            continue
        f = faces[int(o["face"][4:]) - 1]
        n = _planar_normal(f)
        if n is None:
            continue
        att = _attached_edges(shape, f, n)
        if att and len(att) < len(f.OuterWire.Edges):
            wedge_faces.append({"face": o["face"], "tilt_deg": o["tilt_deg"], "area": o["area"], "attached_edges": len(att)})
    if wedge_faces:
        fixes.append({"fix": "overhang_chamfer", "faces": [x["face"] for x in wedge_faces][:max_items], "angle": limit_tilt,
                      "detail": f"평면 오버행 {len(wedge_faces)}면 아래를 {limit_tilt}° 경사로 메움(서포트 대신 재료 추가 → 무게·모양이 바뀜)"})
    if not fits:
        axis = "x" if bb.XLength >= bb.YLength else "y"
        if bb.ZLength > bed[2] and bb.ZLength >= max(bb.XLength, bb.YLength):
            axis = "z"
        limit = {"x": max(bed[0], bed[1]), "y": max(bed[0], bed[1]), "z": bed[2]}[axis]
        length = {"x": bb.XLength, "y": bb.YLength, "z": bb.ZLength}[axis]
        count = int(math.ceil(length / limit))
        fixes.append({"fix": "split", "axis": axis, "count": count, "detail": f"{axis.upper()} 방향 {length:.1f} mm를 {count}조각(각 ≤ {limit})으로 분할 — 조각은 Part::Feature로 따로 만든다(접합용 핀·홈은 수동)"})
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
        "_over_faces": over_faces, "_thin_all": thin_spots,
    }


_PAINT = {"thin": (0.90, 0.15, 0.15), "overhang": (1.00, 0.55, 0.10), "bridge": (0.95, 0.85, 0.20), "bottom": (0.20, 0.75, 0.30), "ok": (0.80, 0.80, 0.82)}


def _paint_faces(obj, shape, data, on):
    """검사 결과를 면 색으로. on=False면 단색으로 되돌린다 [ShapeAppearance 면별 Material, 라이브 1.1.3]."""
    vo = getattr(obj, "ViewObject", None)
    if vo is None or "ShapeAppearance" not in vo.PropertiesList:
        return None
    base = vo.ShapeAppearance[0] if vo.ShapeAppearance else FreeCAD.Material()
    if not on:
        vo.ShapeAppearance = (base,)
        return {"painted": False}
    kinds = {}
    for o in data["_over_faces"]:
        if o["kind"] in ("overhang", "bridge", "bottom"):
            kinds[o["face"]] = o["kind"]
    for t in data["_thin_all"]:
        kinds[t["face"]] = "thin"                     # 얇은 벽이 우선
    mats = []
    counts = {}
    for i in range(1, len(shape.Faces) + 1):
        k = kinds.get(f"Face{i}", "ok")
        counts[k] = counts.get(k, 0) + 1
        m = FreeCAD.Material()             # Material(other)는 없다 — 새로 만들고 색만 준다 [라이브 1.1.3]
        m.DiffuseColor = _PAINT[k] + (0.0,)
        mats.append(m)
    vo.ShapeAppearance = tuple(mats)
    return {"painted": True, "legend": {"thin": "빨강 = 얇은 벽", "overhang": "주황 = 서포트 필요", "bridge": "노랑 = 브릿지", "bottom": "초록 = 바닥 접지", "ok": "회색"}, "counts": counts}


def check_printability(name=None, doc=None, profile=None, samples=2000, max_items=30, paint=None):
    """출력 가능성 검사 (명세 7.32). paint=True면 면을 결과 색으로 칠하고, False면 되돌린다."""
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
        if paint is not None:
            data["paint"] = _paint_faces(obj, shape, data, bool(paint))
    except _PrintError as e:
        return util.error(str(e))
    except Exception as e:  # noqa: BLE001
        return util.error(f"검사 실패: {e}", e)
    data.pop("_over_faces", None)
    data.pop("_thin_all", None)
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
    """elephant_foot / hole_comp / teardrop / thicken / overhang_chamfer / split (명세 7.35, M15 확장)."""
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
        return util.error("fixes 목록이 필요합니다: [{'fix': 'elephant_foot'|'hole_comp'|'teardrop'|'thicken'|'overhang_chamfer'|'split', ...}]")
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
            elif kind == "thicken":
                min_wall = float(fx.get("min_wall") or prof["min_wall"])
                spots = fx.get("spots")
                if not spots:
                    # 후보를 안 넘겼으면 검사에서 다시 찾는다
                    a = _analyze(obj.Shape, prof, samples=1500, max_items=200, with_holes=False)
                    spots = next((f_["spots"] for f_ in a["fixes"] if f_["fix"] == "thicken"), [])
                if not spots:
                    skipped.append({"fix": kind, "reason": "두껍게 할 평면 얇은 면이 없습니다."}); continue
                done = []
                mesh = None
                for i, sp in enumerate(spots):
                    cur = obj.Shape
                    pnt = Vec(*sp["point"])
                    # 지금 형상에서 그 점에 가장 가까운 평면 면을 다시 찾는다(앞 Pad로 번호가 바뀐다)
                    best = None
                    for fi_, f in enumerate(cur.Faces, 1):
                        if _planar_normal(f) is None:
                            continue
                        fb = f.BoundBox
                        fb.enlarge(0.5)
                        if not fb.isInside(pnt):
                            continue
                        dist = f.distToShape(Part.Vertex(pnt))[0]
                        if best is None or dist < best[0]:
                            best = (dist, fi_, f)
                    if best is None or best[0] > 0.5:
                        skipped.append({"fix": kind, "reason": f"{sp.get('face')} 근처({sp['point']})에 평면이 없습니다."}); continue
                    n = _planar_normal(best[2])
                    mesh = _mesh_of(cur)
                    t_now = _ray(mesh, pnt, Vec(-n.x, -n.y, -n.z), back_off=-_INSET)
                    if t_now is None or t_now >= min_wall - 1e-3:
                        done.append({"face": f"Face{best[1]}", "skipped": "이미 충분", "thickness": round(t_now, 3) if t_now else None}); continue
                    add = round(min_wall - t_now + 0.05, 3)
                    tip = obj.Tip
                    pad = obj.newObject("PartDesign::Pad", f"Thicken{k + 1}_{i + 1}")
                    pad.Profile = (tip, [f"Face{best[1]}"])
                    pad.Length = add
                    d.recompute()
                    if "Invalid" in pad.State:
                        st = pad.getStatusString()
                        obj.removeObject(pad); d.removeObject(pad.Name); obj.Tip = tip; d.recompute()
                        skipped.append({"fix": kind, "reason": f"Face{best[1]} Pad 실패: {st}"}); continue
                    applied.append({"fix": kind, "feature": pad.Name, "status": "Valid", "face": f"Face{best[1]}", "added": add, "volume_after": round(obj.Shape.Volume, 2)})
                    done.append({"face": f"Face{best[1]}", "added": add})
                continue
            elif kind == "overhang_chamfer":
                angle = float(fx.get("angle") or prof["overhang_deg"])
                want = fx.get("faces")
                cur = obj.Shape
                a = _analyze(cur, prof, samples=1500, max_items=200, with_holes=False)
                cand = next((f_["faces"] for f_ in a["fixes"] if f_["fix"] == "overhang_chamfer"), [])
                if want:
                    cand = [c for c in cand if c in want]
                if not cand:
                    skipped.append({"fix": kind, "reason": "쐐기를 붙일 평면 오버행 면이 없습니다."}); continue
                wedges = []
                for fid in cand:
                    f = cur.Faces[int(fid[4:]) - 1]
                    n = _planar_normal(f)
                    w = _wedge_below(cur, f, n, angle)
                    if w is not None:
                        wedges.append((fid, w))
                if not wedges:
                    skipped.append({"fix": kind, "reason": "쐐기 솔리드를 만들지 못했습니다."}); continue
                fused = wedges[0][1]
                for _, w in wedges[1:]:
                    fused = fused.fuse(w)
                helper = d.addObject("PartDesign::Body", f"{obj.Name}_OverhangFill{k + 1}")
                hb = d.addObject("Part::Feature", f"{obj.Name}_OverhangFill{k + 1}_Base")
                hb.Shape = fused.removeSplitter()
                helper.BaseFeature = hb
                d.recompute()
                tip = obj.Tip
                bo = obj.newObject("PartDesign::Boolean", f"OverhangFill{k + 1}")
                bo.Type = "Fuse"
                bo.addObjects([helper])
                d.recompute()
                if helper.ViewObject:
                    helper.ViewObject.Visibility = False
                if "Invalid" in bo.State:
                    st = bo.getStatusString()
                    obj.removeObject(bo); d.removeObject(bo.Name); obj.Tip = tip
                    d.removeObject(helper.Name); d.removeObject(hb.Name); d.recompute()
                    skipped.append({"fix": kind, "reason": f"Boolean Fuse 실패: {st}"}); continue
                applied.append({"fix": kind, "feature": bo.Name, "status": "Valid", "faces": [fid for fid, _ in wedges], "helper_body": helper.Name,
                                "added_volume": round(fused.Volume, 2), "volume_after": round(obj.Shape.Volume, 2)})
                continue
            elif kind == "split":
                axis = str(fx.get("axis") or "x").lower()
                if axis not in ("x", "y", "z"):
                    skipped.append({"fix": kind, "reason": "axis는 x/y/z"}); continue
                bed = prof["bed"]
                size = fx.get("size") or ({"x": max(bed[0], bed[1]), "y": max(bed[0], bed[1]), "z": bed[2]}[axis])
                cuts, pieces = _split_pieces(obj.Shape, axis, count=fx.get("count"), size=size, positions=fx.get("positions"))
                if len(pieces) < 2:
                    skipped.append({"fix": kind, "reason": "조각이 하나뿐입니다(절단 위치가 형상 밖)."}); continue
                made = []
                for i, pc in enumerate(pieces):
                    pf = d.addObject("Part::Feature", f"{obj.Name}_Split{i + 1}")
                    pf.Shape = pc
                    pf.Label = f"{util.label(obj)} 조각 {i + 1}"
                    made.append({"name": pf.Name, "bbox": util.serialize(pc.BoundBox), "volume": round(pc.Volume, 2), "solids": len(pc.Solids)})
                d.recompute()
                if obj.ViewObject:
                    obj.ViewObject.Visibility = False
                applied.append({"fix": kind, "axis": axis, "cuts": [round(c, 2) for c in cuts], "pieces": made,
                                "note": "조각은 Body 밖의 Part::Feature다(원본은 숨김). 접합 핀·홈은 수동"})
                continue
            else:
                skipped.append({"fix": kind, "reason": "모르는 fix. elephant_foot / hole_comp / teardrop / thicken / overhang_chamfer / split"}); continue
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
