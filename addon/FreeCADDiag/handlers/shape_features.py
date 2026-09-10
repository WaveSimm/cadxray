"""형상 특징 — find_holes, check_interference, get_mass_properties (명세 7.13~7.15).

STEP처럼 히스토리 없는 형상에서 구멍·간섭·물성을 뽑는다.
API는 전부 api-notes 12장에서 확인한 것만 쓴다 [라이브 1.1.3].
"""

import itertools
import math
import time

import FreeCAD

from . import util

Vec = FreeCAD.Vector


def _shape_or_error(d, name):
    obj, err = util.find_object(d, name)
    if err:
        return None, None, err
    if not hasattr(obj, "Shape"):
        return obj, None, f"'{obj.Name}'({obj.TypeId})에는 Shape가 없습니다."
    s = obj.Shape
    if s.isNull():
        return obj, None, f"'{obj.Name}'의 Shape가 비어 있습니다(null)."
    return obj, s, None


# --- 7.15 get_mass_properties ----------------------------------------------------


def _matrix3(m):
    return [
        [round(m.A11, 4), round(m.A12, 4), round(m.A13, 4)],
        [round(m.A21, 4), round(m.A22, 4), round(m.A23, 4)],
        [round(m.A31, 4), round(m.A32, 4), round(m.A33, 4)],
    ]


def get_mass_properties(name=None, doc=None, density=None):
    """부피·면적·무게중심·관성. density(g/cm³)를 주면 질량(g)도."""
    t0 = time.time()
    d, err = util.get_doc(doc)
    if err:
        return util.error(err)
    obj, shape, err = _shape_or_error(d, name)
    if err:
        return util.error(err)
    solids = shape.Solids
    if not solids:
        return util.error(
            f"'{obj.Name}'에 솔리드가 없습니다({shape.ShapeType}). 면만 있는 형상은 부피를 잴 수 없습니다."
        )

    warnings = []
    volume = sum(s.Volume for s in solids)
    if volume <= 0:
        return util.error("부피가 0 이하입니다. 형상이 뒤집혔거나 깨졌을 수 있습니다 — analyze_shape로 확인하세요.")

    # 무게중심은 부피 가중, 관성 행렬은 합산 (둘 다 전역 원점 기준) [api-notes 12장]
    com = Vec(0, 0, 0)
    inertia = None
    for s in solids:
        com += s.CenterOfMass * s.Volume
        m = s.MatrixOfInertia
        if inertia is None:
            inertia = [[m.A11, m.A12, m.A13], [m.A21, m.A22, m.A23], [m.A31, m.A32, m.A33]]
        else:
            rows = [[m.A11, m.A12, m.A13], [m.A21, m.A22, m.A23], [m.A31, m.A32, m.A33]]
            inertia = [[inertia[i][j] + rows[i][j] for j in range(3)] for i in range(3)]
    com = com * (1.0 / volume)

    data = {
        "document": d.Name,
        "object": obj.Name,
        "label": util.label(obj),
        "solids": len(solids),
        "volume_mm3": round(volume, 4),
        "volume_cm3": round(volume / 1000.0, 6),
        "area_mm2": round(shape.Area, 4),
        "center_of_mass": util.round_vec(com),
        "matrix_of_inertia": [[round(v, 4) for v in row] for row in inertia],
        "matrix_of_inertia_about": "global origin, density 1",
        "bbox": util.serialize(shape.BoundBox),
    }
    if len(solids) == 1:
        try:
            pp = solids[0].PrincipalProperties
            data["principal"] = {
                "moments": [round(float(v), 4) for v in pp["Moments"]],
                "radius_of_gyration": [round(float(v), 4) for v in pp["RadiusOfGyration"]],
            }
        except Exception as e:
            warnings.append(f"PrincipalProperties 읽기 실패: {e}")
    else:
        warnings.append(f"솔리드가 {len(solids)}개라 주축(principal)은 생략했습니다. 부피·무게중심은 합산 값입니다.")

    if density is not None:
        try:
            density = float(density)
            data["density_g_cm3"] = density
            data["mass_g"] = round(volume / 1000.0 * density, 4)
        except Exception:
            warnings.append("density는 숫자(g/cm³)여야 합니다. 질량은 생략했습니다.")
    else:
        data["mass_hint"] = "density(g/cm³)를 주면 mass_g를 계산합니다. 예: 알루미늄 2.7, 강 7.85, ABS 1.04"

    return util.envelope(data, warnings=warnings, t0=t0)


# --- 7.13 find_holes ------------------------------------------------------------


def _canonical_axis(axis):
    a = Vec(axis)
    if a.Length < 1e-12:
        return None
    a.normalize()
    for c in (a.x, a.y, a.z):
        if abs(c) > 1e-9:
            if c < 0:
                a = a * -1
            break
    return a


def _is_concave(face, center, axis):
    """면 중앙의 법선이 축을 향하면 구멍(오목). 원통·원뿔 모두 같은 판정. [라이브 1.1.3 확인]"""
    u0, u1, v0, v1 = face.ParameterRange
    um, vm = (u0 + u1) / 2.0, (v0 + v1) / 2.0
    p = face.valueAt(um, vm)
    n = face.normalAt(um, vm)
    foot = center + axis * ((p - center).dot(axis))
    return (foot - p).dot(n) > 0


def _arc_deg(faces):
    """원통·원뿔면의 u 파라미터는 각도(라디안). 합이 360°면 온전한 구멍. [api-notes 12장]"""
    arc = 0.0
    for _, f in faces:
        try:
            u0, u1, _, _ = f.ParameterRange
            arc += abs(u1 - u0)
        except Exception:
            pass
    return round(min(math.degrees(arc), 360.0), 1)


def _kind(arc_deg):
    # 360° 미만이면 온전한 구멍이 아니다: 90°는 내부 모서리 필렛, 180°는 슬롯 끝
    return "hole" if arc_deg >= 350 else ("fillet" if arc_deg <= 100 else "partial")


def _line_key(axis, foot, tol):
    return (
        round(axis.x / tol), round(axis.y / tol), round(axis.z / tol),
        round(foot.x / tol), round(foot.y / tol), round(foot.z / tol),
    )


def _split_along_axis(items, tol):
    """같은 축선이라도 축 방향으로 떨어져 있으면 다른 구멍이다 (예: 양쪽 벽의 자리파기).
    items = [(tmin, tmax, i, face, extra)] → 겹치는 구간끼리 묶는다."""
    items = sorted(items, key=lambda x: (x[0], x[1]))
    clusters = []
    for lo, hi, i, f, extra in items:
        if clusters and lo <= clusters[-1]["hi"] + tol:
            c = clusters[-1]
            c["hi"] = max(c["hi"], hi)
            c["faces"].append((i, f))
            c["extra"].append(extra)
        else:
            clusters.append({"lo": lo, "hi": hi, "faces": [(i, f)], "extra": [extra]})
    return clusters


def _through(shape, p_lo, p_hi, axis, depth):
    """관통 판정(휴리스틱): 구멍 양 끝 바로 바깥이 재료가 아니면 관통."""
    eps = max(min(0.5, depth * 0.05), 1e-3)
    try:
        open_lo = not shape.isInside(p_lo - axis * eps, 1e-6, True)
        open_hi = not shape.isInside(p_hi + axis * eps, 1e-6, True)
        return bool(open_lo and open_hi)
    except Exception:
        return None


def find_holes(
    name=None,
    doc=None,
    min_radius=0.5,
    max_radius=50.0,
    max_holes=100,
    group_tolerance=0.01,
):
    """원통면을 축·중심·반지름으로 묶어 구멍 직경·위치·깊이·관통 여부를 뽑는다.

    같은 축에 붙은 원뿔면은 countersink(카운터싱크·챔퍼)/drill_point로, 더 큰 원통은
    counterbore로 그 구멍에 붙인다. 필렛·슬롯 끝(호 < 360°)은 구멍으로 세지 않는다.
    """
    t0 = time.time()
    d, err = util.get_doc(doc)
    if err:
        return util.error(err)
    obj, shape, err = _shape_or_error(d, name)
    if err:
        return util.error(err)

    warnings = []
    tol = max(float(group_tolerance), 1e-6)
    cyl_groups = {}   # (r, 축선) → 면 구간들
    cone_groups = {}  # 축선 → 면 구간들
    skipped_convex = 0
    cyl_faces = cone_faces = 0

    for i, f in enumerate(shape.Faces):
        try:
            surf = f.Surface
            stype = type(surf).__name__
            if stype not in ("Cylinder", "Cone"):
                continue
            axis = _canonical_axis(surf.Axis)
            if axis is None:
                continue
            if stype == "Cylinder":
                cyl_faces += 1
                r = float(surf.Radius)
                if r < min_radius or r > max_radius:
                    continue
                center = Vec(surf.Center)
                if not _is_concave(f, center, axis):
                    skipped_convex += 1
                    continue
                foot = center - axis * center.dot(axis)  # 축선이 원점에 가장 가까운 점
                ts = [(Vec(v.Point) - foot).dot(axis) for v in f.Vertexes]
                if not ts:
                    continue
                key = (round(r / tol),) + _line_key(axis, foot, tol)
                cyl_groups.setdefault(key, {"r": r, "axis": axis, "foot": foot, "items": []})
                cyl_groups[key]["items"].append((min(ts), max(ts), i, f, None))
            else:
                cone_faces += 1
                apex = Vec(surf.Apex)
                if not _is_concave(f, apex, axis):
                    skipped_convex += 1
                    continue
                foot = apex - axis * apex.dot(axis)
                pts = [Vec(v.Point) for v in f.Vertexes]
                if not pts:
                    continue
                ts = [(p - foot).dot(axis) for p in pts]
                rs = [((p - foot) - axis * (p - foot).dot(axis)).Length for p in pts]
                r_lo, r_hi = min(rs), max(rs)
                if r_hi < min_radius or r_lo > max_radius:
                    continue
                key = _line_key(axis, foot, tol)
                cone_groups.setdefault(key, {"axis": axis, "foot": foot, "items": []})
                cone_groups[key]["items"].append(
                    (min(ts), max(ts), i, f, {"r_lo": r_lo, "r_hi": r_hi, "semi": float(surf.SemiAngle)})
                )
        except Exception as e:
            warnings.append(f"면 {i} 처리 실패: {e}")

    # 원통 → 구멍 레코드
    records = []
    for g in cyl_groups.values():
        for cl in _split_along_axis(g["items"], tol):
            rec = {"axis": g["axis"], "foot": g["foot"], "r": g["r"], "lo": cl["lo"], "hi": cl["hi"],
                   "faces": cl["faces"], "arc": _arc_deg(cl["faces"]),
                   "line": _line_key(g["axis"], g["foot"], tol)}
            rec["kind"] = _kind(rec["arc"])
            records.append(rec)

    # 원뿔 레코드
    cones = []
    for g in cone_groups.values():
        for cl in _split_along_axis(g["items"], tol):
            ex = cl["extra"]
            cones.append({"axis": g["axis"], "foot": g["foot"], "lo": cl["lo"], "hi": cl["hi"],
                          "faces": cl["faces"], "arc": _arc_deg(cl["faces"]),
                          "line": _line_key(g["axis"], g["foot"], tol),
                          "r_lo": min(e["r_lo"] for e in ex), "r_hi": max(e["r_hi"] for e in ex),
                          "semi": ex[0]["semi"], "used": False})

    near = tol * 10

    def _adjacent(a_lo, a_hi, b_lo, b_hi):
        return abs(a_hi - b_lo) <= near or abs(b_hi - a_lo) <= near

    # 카운터보어: 같은 축선에 이어진 더 큰 원통 → 작은 구멍에 붙이고 목록에서 뺀다
    holes_rec = [r for r in records if r["kind"] == "hole"]
    merged = set()
    for small in holes_rec:
        for big in holes_rec:
            if big is small or id(big) in merged or big["r"] <= small["r"] + tol:
                continue
            if big["line"] == small["line"] and _adjacent(small["lo"], small["hi"], big["lo"], big["hi"]):
                small["counterbore"] = {
                    "diameter": round(2 * big["r"], 4),
                    "depth": round(big["hi"] - big["lo"], 4),
                    "at": "end" if big["lo"] >= small["hi"] - near else "start",
                    "faces": [i for i, _ in big["faces"]],
                }
                small["lo"] = min(small["lo"], big["lo"])
                small["hi"] = max(small["hi"], big["hi"])
                merged.add(id(big))
                break
    records = [r for r in records if id(r) not in merged]

    # 원뿔 붙이기: 좁은 쪽이 구멍 반지름이면 카운터싱크/챔퍼, 넓은 쪽이 구멍이고 좁은 쪽이 0에 가까우면 드릴 끝
    for rec in records:
        if rec["kind"] != "hole":
            continue
        for c in cones:
            if c["used"] or c["line"] != rec["line"] or c["arc"] < 350:
                continue
            if not _adjacent(rec["lo"], rec["hi"], c["lo"], c["hi"]):
                continue
            angle = round(math.degrees(2 * c["semi"]), 1)
            depth = round(c["hi"] - c["lo"], 4)
            at = "end" if c["lo"] >= rec["hi"] - near else "start"
            fit = max(near, rec["r"] * 0.05)
            if abs(c["r_lo"] - rec["r"]) <= fit:
                rec["countersink"] = {
                    "type": "chamfer" if depth < 1.0 else "countersink",
                    "top_diameter": round(2 * c["r_hi"], 4),
                    "angle_deg": angle, "depth": depth, "at": at,
                    "faces": [i for i, _ in c["faces"]],
                }
            elif abs(c["r_hi"] - rec["r"]) <= fit and c["r_lo"] < rec["r"] * 0.2:
                rec["drill_point"] = {"angle_deg": angle, "depth": depth, "at": at,
                                      "faces": [i for i, _ in c["faces"]]}
            else:
                continue
            c["used"] = True
            rec["lo"] = min(rec["lo"], c["lo"])
            rec["hi"] = max(rec["hi"], c["hi"])

    # 공개 항목
    holes = []
    for rec in records:
        axis, foot = rec["axis"], rec["foot"]
        depth = rec["hi"] - rec["lo"]
        p_lo, p_hi = foot + axis * rec["lo"], foot + axis * rec["hi"]
        h = {
            "diameter": round(2 * rec["r"], 4),
            "radius": round(rec["r"], 4),
            "axis": util.round_vec(axis),
            "center": util.round_vec(foot + axis * ((rec["lo"] + rec["hi"]) / 2.0)),
            "start": util.round_vec(p_lo),
            "end": util.round_vec(p_hi),
            "depth": round(depth, 4),
            "through": _through(shape, p_lo, p_hi, axis, depth) if rec["kind"] == "hole" else None,
            "arc_deg": rec["arc"],
            "kind": rec["kind"],
            "faces": [i for i, _ in rec["faces"]],
        }
        for extra in ("counterbore", "countersink", "drill_point"):
            if extra in rec:
                h[extra] = rec[extra]
        holes.append(h)

    # 어느 구멍에도 안 붙은 온전한 오목 원뿔 (원뿔 자리만 있는 경우)
    for c in cones:
        if c["used"] or c["arc"] < 350:
            continue
        axis, foot = c["axis"], c["foot"]
        holes.append({
            "diameter": round(2 * c["r_hi"], 4),
            "radius": round(c["r_hi"], 4),
            "diameter_small": round(2 * c["r_lo"], 4),
            "axis": util.round_vec(axis),
            "center": util.round_vec(foot + axis * ((c["lo"] + c["hi"]) / 2.0)),
            "start": util.round_vec(foot + axis * c["lo"]),
            "end": util.round_vec(foot + axis * c["hi"]),
            "depth": round(c["hi"] - c["lo"], 4),
            "through": False,
            "arc_deg": c["arc"],
            "angle_deg": round(math.degrees(2 * c["semi"]), 1),
            "kind": "cone",
            "faces": [i for i, _ in c["faces"]],
        })

    fillets = [h for h in holes if h["kind"] not in ("hole", "cone")]
    holes.sort(key=lambda h: (h["kind"] != "hole", -h["diameter"], h["center"]))
    for i, h in enumerate(holes):
        h["i"] = i

    # 같은 직경·같은 축 방향끼리 패턴 (온전한 구멍만). 판의 볼트홀과 벽의 옆구멍이 섞이지 않게.
    patterns = []
    by_d = {}
    for h in holes:
        if h["kind"] == "hole":
            by_d.setdefault((h["diameter"], tuple(h["axis"])), []).append(h)
    for (dia, axis), hs in sorted(by_d.items(), key=lambda kv: (-kv[0][0], kv[0][1])):
        centers = [h["center"] for h in hs]
        dists = sorted(
            {
                round(math.dist(a, b), 3)
                for a, b in itertools.combinations(centers, 2)
                if math.dist(a, b) > tol
            }
        )
        pat = {
            "diameter": dia,
            "axis": list(axis),
            "count": len(hs),
            "through": sum(1 for h in hs if h["through"]),
            "centers": centers,
            "pitch": dists[:2],
        }
        n_cb = sum(1 for h in hs if "counterbore" in h)
        n_cs = sum(1 for h in hs if "countersink" in h)
        if n_cb:
            pat["counterbore"] = n_cb
        if n_cs:
            pat["countersink"] = n_cs
        patterns.append(pat)

    n_holes = sum(1 for h in holes if h["kind"] == "hole")
    truncated = len(holes) > max_holes
    data = {
        "document": d.Name,
        "object": obj.Name,
        "label": util.label(obj),
        "cylindrical_faces": cyl_faces,
        "conical_faces": cone_faces,
        "convex_skipped": skipped_convex,
        "holes_total": n_holes,
        "partial_total": len(fillets),
        "holes": holes[:max_holes],
        "patterns": patterns,
        "through_method": "heuristic",
        "radius_range": [min_radius, max_radius],
    }
    if cyl_faces == 0 and cone_faces == 0:
        warnings.append("원통면·원뿔면이 없습니다. 메시(STL)에서 온 형상이거나 구멍이 없는 부품입니다.")
    elif n_holes == 0:
        warnings.append(
            f"원통면 {cyl_faces}개·원뿔면 {cone_faces}개가 있지만 조건에 맞는 구멍이 없습니다"
            f"(볼록 {skipped_convex}개 제외, 반지름 {min_radius}~{max_radius})."
        )
    if fillets:
        warnings.append(
            f"오목 원통면 중 {len(fillets)}개는 호가 360°가 안 되어(kind=fillet/partial) 구멍으로 세지 않았습니다. "
            "내부 모서리 필렛이나 슬롯 끝입니다."
        )
    warnings.append("through는 구멍 양 끝 바깥 지점이 재료 밖인지로 판정한 휴리스틱입니다. 포켓으로 뚫린 구멍은 관통으로 보일 수 있습니다.")
    if truncated:
        warnings.append(f"항목 {len(holes)}개 중 {max_holes}개만 담았습니다. patterns는 전체 기준입니다.")
    if util.fit_cap(data, "holes", warnings):
        truncated = True
    return util.envelope(data, warnings=warnings, truncated=truncated, t0=t0)


# --- 7.14 check_interference ----------------------------------------------------


def _expand(d, name, out, seen):
    """App::Part/그룹이면 안의 형상 객체로 푼다."""
    obj, err = util.find_object(d, name)
    if err:
        return err
    if obj.Name in seen:
        return None
    seen.add(obj.Name)
    if hasattr(obj, "Shape") and not obj.Shape.isNull() and obj.TypeId != "App::Part":
        out.append(obj)
        return None
    group = getattr(obj, "Group", None)
    if group:
        for child in group:
            e = _expand(d, child.Name, out, seen)
            if e:
                return e
        return None
    return f"'{obj.Name}'({obj.TypeId})에는 형상이 없습니다."


def check_interference(
    names=None, doc=None, clearance=0.0, volume_tolerance=1e-6, max_pairs=50, include_ok=False
):
    """부품 쌍마다 최소 거리와 간섭 부피를 잰다.

    기본으로는 문제 있는 쌍(interference / clearance_violation / error)만 pairs에 담는다.
    80부품 어셈블리는 쌍이 3천 개가 넘어 ok까지 다 담으면 응답이 수백 KB가 된다.
    """
    t0 = time.time()
    d, err = util.get_doc(doc)
    if err:
        return util.error(err)
    if isinstance(names, str):
        names = [names]
    if not names:
        return util.error("names에 객체 이름을 2개 이상(또는 App::Part 하나) 주세요.")

    objs, seen = [], set()
    for n in names:
        e = _expand(d, n, objs, seen)
        if e:
            return util.error(e)
    if len(objs) < 2:
        return util.error(f"비교할 형상이 {len(objs)}개뿐입니다. 2개 이상 필요합니다.")

    warnings = []
    all_pairs = list(itertools.combinations(objs, 2))
    truncated = len(all_pairs) > max_pairs
    pairs = []
    summary = {"interference": 0, "clearance_violation": 0, "ok": 0, "error": 0}
    bbox_skipped = 0
    shapes = {o.Name: o.Shape for o in objs}
    boxes = {o.Name: shapes[o.Name].BoundBox for o in objs}

    def _bbox_gap(b1, b2):
        """두 바운딩박스 사이의 최소 축별 간격(겹치면 0). 실제 거리의 하한이다."""
        gx = max(b1.XMin - b2.XMax, b2.XMin - b1.XMax, 0.0)
        gy = max(b1.YMin - b2.YMax, b2.YMin - b1.YMax, 0.0)
        gz = max(b1.ZMin - b2.ZMax, b2.ZMin - b1.ZMax, 0.0)
        return math.sqrt(gx * gx + gy * gy + gz * gz)

    for a, b in all_pairs[:max_pairs]:
        entry = {"a": a.Name, "b": b.Name, "a_label": util.label(a), "b_label": util.label(b)}
        tp = time.time()
        try:
            # 바운딩박스가 clearance 이상 떨어져 있으면 distToShape(쌍당 수십 ms)를 건너뛴다.
            # 80부품 어셈블리에서 3,160쌍 중 대부분이 여기서 끝난다 [실측: 42 ms/쌍 → 0].
            gap = _bbox_gap(boxes[a.Name], boxes[b.Name])
            if gap > max(clearance, 0.0) + 1e-9:
                bbox_skipped += 1
                entry["distance"] = round(gap, 4)
                entry["distance_is_lower_bound"] = True
                entry["interference_volume"] = 0.0
                entry["status"] = "ok"
                entry["ms"] = 0
                summary["ok"] += 1
                pairs.append(entry)
                continue
            dist = float(shapes[a.Name].distToShape(shapes[b.Name])[0])
            entry["distance"] = round(dist, 4)
            vol = 0.0
            if dist <= 1e-9:
                # common()은 느리므로 거리가 0일 때만 [api-notes 12장]
                vol = float(shapes[a.Name].common(shapes[b.Name]).Volume)
            entry["interference_volume"] = round(vol, 4)
            if vol > volume_tolerance:
                entry["status"] = "interference"
            elif dist < clearance:
                entry["status"] = "clearance_violation"
            else:
                entry["status"] = "ok"
        except Exception as e:
            entry["status"] = "error"
            entry["error"] = str(e)
        entry["ms"] = int((time.time() - tp) * 1000)
        summary[entry["status"]] += 1
        pairs.append(entry)

    order = {"interference": 0, "clearance_violation": 1, "error": 2, "ok": 3}
    pairs.sort(key=lambda p: (order[p["status"]], -p.get("interference_volume", 0)))
    checked = len(pairs)
    if not include_ok:
        pairs = [p for p in pairs if p["status"] != "ok"]

    data = {
        "document": d.Name,
        "objects": [o.Name for o in objs],
        "pairs_total": len(all_pairs),
        "pairs_checked": checked,
        "pairs_skipped_by_bbox": bbox_skipped,
        "pairs": pairs,
        "include_ok": bool(include_ok),
        "summary": summary,
        "clearance": clearance,
    }
    if summary["interference"]:
        warnings.append(f"간섭 {summary['interference']}쌍. interference_volume(mm³)가 겹치는 부피입니다.")
    if truncated:
        warnings.append(f"쌍 {len(all_pairs)}개 중 {max_pairs}개만 검사했습니다. names를 좁히거나 max_pairs를 올리세요.")
    if util.fit_cap(data, "pairs", warnings):
        truncated = True
    return util.envelope(data, warnings=warnings, truncated=truncated, t0=t0)


TOOLS = {
    "get_mass_properties": get_mass_properties,
    "find_holes": find_holes,
    "check_interference": check_interference,
}
