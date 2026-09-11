"""import_mesh, analyze_mesh + 메시 단면 피팅·편차 (M9, 명세 7.23~7.26).

STL/OBJ 메시는 면·솔리드가 없어 Part 툴이 못 읽는다. 여기서는 Mesh API만 쓴다 [확인됨: api-notes 16장]:
- crossSections → 폴리라인 → 최소제곱 원 피팅(Kasa) / Douglas-Peucker 꼭짓점 → 직선·원호·원
- 면 법선을 축과 비교해 레벨(띠 경계)을 잡는다 (getSegmentsOfType("Cylinder")는 원통을 못 찾는다)
- 비교는 불리언 없이 Body 면 표본점에서 법선 방향 광선(nearestFacetOnRay) + 메시 정점 → distToShape
"""

import math
import os
import time

import FreeCAD
import Part

from . import util

Vec = FreeCAD.Vector


# --- 2D 피팅 ---------------------------------------------------------------------


def fit_circle(pts):
    """최소제곱 원 피팅(Kasa). pts: [(x, y)] → (cx, cy, r, rms) 또는 None(퇴화)."""
    n = len(pts)
    if n < 3:
        return None
    sx = sum(p[0] for p in pts) / n
    sy = sum(p[1] for p in pts) / n
    u = [(p[0] - sx, p[1] - sy) for p in pts]
    suu = sum(a * a for a, b in u)
    svv = sum(b * b for a, b in u)
    suv = sum(a * b for a, b in u)
    suuu = sum(a ** 3 for a, b in u)
    svvv = sum(b ** 3 for a, b in u)
    suvv = sum(a * b * b for a, b in u)
    svuu = sum(b * a * a for a, b in u)
    det = suu * svv - suv * suv
    if abs(det) < 1e-12:
        return None
    uc = (0.5 * (suuu + suvv) * svv - 0.5 * (svvv + svuu) * suv) / det
    vc = (0.5 * (svvv + svuu) * suu - 0.5 * (suuu + suvv) * suv) / det
    cx, cy = uc + sx, vc + sy
    r2 = uc * uc + vc * vc + (suu + svv) / n
    if r2 <= 0:
        return None
    r = math.sqrt(r2)
    res = [abs(math.hypot(p[0] - cx, p[1] - cy) - r) for p in pts]
    rms = math.sqrt(sum(v * v for v in res) / n)
    return cx, cy, r, rms, max(res)


def _rdp(pts, eps):
    """Douglas-Peucker: 열린 폴리라인의 꼭짓점 인덱스."""
    if len(pts) < 3:
        return list(range(len(pts)))
    ax, ay = pts[0]
    bx, by = pts[-1]
    L = math.hypot(bx - ax, by - ay)
    dmax, idx = -1.0, 0
    for i in range(1, len(pts) - 1):
        if L < 1e-12:
            d = math.hypot(pts[i][0] - ax, pts[i][1] - ay)
        else:
            d = abs((by - ay) * pts[i][0] - (bx - ax) * pts[i][1] + bx * ay - by * ax) / L
        if d > dmax:
            dmax, idx = d, i
    if dmax > eps:
        left = _rdp(pts[:idx + 1], eps)
        right = _rdp(pts[idx:], eps)
        return left[:-1] + [i + idx for i in right]
    return [0, len(pts) - 1]


def _arc_element(run, c):
    cx, cy, r = c[0], c[1], c[2]
    (x0, y0), (x1, y1) = run[0], run[-1]
    mid = run[len(run) // 2]
    a0 = math.atan2(y0 - cy, x0 - cx)
    am = math.atan2(mid[1] - cy, mid[0] - cx)
    a1 = math.atan2(y1 - cy, x1 - cx)
    ccw = ((am - a0) % (2 * math.pi)) < ((a1 - a0) % (2 * math.pi))
    return {"type": "arc", "center": [round(cx, 6), round(cy, 6)], "radius": round(r, 6),
            "start": [round(x0, 6), round(y0, 6)], "end": [round(x1, 6), round(y1, 6)], "ccw": bool(ccw)}


def polyline_to_elements(pts, closed, fit_tol=0.05, corner_tol=0.15, max_radius=5000.0):
    """2D 폴리라인 → 스케치 요소(line/arc/circle) 목록, 맞추지 못한 조각 수, 최대 잔차.

    닫힌 폴리라인 전체가 한 원에 맞으면 circle 하나. 아니면 RDP 꼭짓점을 잡고, 인접 구간을 늘려 가며
    원에 맞으면 arc, 두 점 사이면 line. 원·직선 어느 쪽도 아닌 구간은 line 여러 개로 남기고 unsupported로 센다.
    """
    pts = [tuple(p) for p in pts]
    if closed and len(pts) > 1 and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) < 1e-9:
        pts = pts[:-1]
    n = len(pts)
    if n < 2:
        return [], 0, 0.0
    if closed and n >= 8:
        c = fit_circle(pts)
        if c and c[4] < 2 * fit_tol and c[3] < fit_tol and c[2] < max_radius:
            return [{"type": "circle", "center": [round(c[0], 6), round(c[1], 6)], "radius": round(c[2], 6)}], 0, round(c[3], 6)
    # 꼭짓점 검출 허용값은 피팅 허용값보다 크면 안 된다: 직선 끝에 붙은 필렛 첫 점(편차 0.09)이 직선 구간에 섞여
    # "직선도 원도 아님"이 된다 [스풀 가이드 슬롯 실측, 2026-09-11]. 메시 정점은 원래 곡선 위에 있으므로 작아도 된다
    eps = min(float(corner_tol), float(fit_tol))
    ring = list(pts) + ([pts[0]] if closed else [])
    corners = _rdp(ring, eps)
    if closed and len(corners) > 2:
        # 닫힌 고리는 임의 점에서 시작한다. 호 중간에서 시작하면 그 호가 둘로 갈라지므로, 꺾임각이 가장 큰
        # 꼭짓점(진짜 모서리)에서 시작하도록 고리를 돌린다 [스풀 가이드 창 윤곽 실측]
        def turn(i):
            a, b, c = pts[(i - 1) % n], pts[i], pts[(i + 1) % n]
            v1 = (b[0] - a[0], b[1] - a[1]); v2 = (c[0] - b[0], c[1] - b[1])
            l1 = math.hypot(*v1) or 1e-12; l2 = math.hypot(*v2) or 1e-12
            cosang = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (l1 * l2)))
            return math.degrees(math.acos(cosang))
        cand = [c for c in corners[:-1]]
        k = max(cand, key=turn) if cand else 0
        ring = pts[k:] + pts[:k] + [pts[k]]
        corners = _rdp(ring, eps)
    els, unsupported, max_res = [], 0, 0.0
    i = 0
    while i < len(corners) - 1:
        best = None
        j = i + 1
        while j + 1 < len(corners):
            run = ring[corners[i]:corners[j + 1] + 1]
            c = fit_circle(run)
            if c and c[4] < fit_tol and c[2] < max_radius and len(run) >= 4:
                # 호가 실제로 휘었는지: 현에서 최대 거리 > fit_tol
                (x0, y0), (x1, y1) = run[0], run[-1]
                L = math.hypot(x1 - x0, y1 - y0) or 1e-12
                sag = max(abs((y1 - y0) * p[0] - (x1 - x0) * p[1] + x1 * y0 - y1 * x0) / L for p in run)
                if sag > fit_tol:
                    best = (j + 1, c)
                j += 1
            else:
                break
        if best:
            jend, c = best
            run = ring[corners[i]:corners[jend] + 1]
            els.append(_arc_element(run, c))
            max_res = max(max_res, c[3])
            i = jend
            continue
        run = ring[corners[i]:corners[i + 1] + 1]
        a, b = run[0], run[-1]
        L = math.hypot(b[0] - a[0], b[1] - a[1]) or 1e-12
        dev = max(abs((b[1] - a[1]) * p[0] - (b[0] - a[0]) * p[1] + b[0] * a[1] - b[1] * a[0]) / L for p in run)
        if dev > fit_tol and len(run) > 2:
            # 직선도 원도 아님 → 점을 그대로 잇는다
            unsupported += 1
            for p, q in zip(run[:-1], run[1:]):
                els.append({"type": "line", "start": [round(p[0], 6), round(p[1], 6)], "end": [round(q[0], 6), round(q[1], 6)], "approx": True})
            max_res = max(max_res, dev)
        else:
            els.append({"type": "line", "start": [round(a[0], 6), round(a[1], 6)], "end": [round(b[0], 6), round(b[1], 6)]})
            max_res = max(max_res, dev)
        i += 1
    # 닫힌 고리의 마지막 요소 끝이 첫 요소 시작과 같은지는 RDP가 보장(ring 끝 = 시작점)
    return els, unsupported, round(max_res, 6)


def _perp_frame(axis):
    """rebuild의 프레임과 같아야 build_features 스케치 좌표(XY: X,Y / XZ: X,Z / YZ: Y,Z)와 맞는다."""
    from .rebuild import _perp_frame as _pf

    return _pf(Vec(axis).normalize())


def _shoelace(pts):
    n = len(pts)
    return abs(sum(pts[k][0] * pts[(k + 1) % n][1] - pts[(k + 1) % n][0] * pts[k][1] for k in range(n))) / 2.0


def mesh_cross_section(mesh, axis, position, tol=0.0005):
    """축 위치의 단면 폴리라인들: [(pts2d, closed, pts3d)] (프레임 로컬 2D)."""
    a = Vec(axis).normalize()
    e1, e2 = _perp_frame(a)
    origin = a * float(position)
    polys = mesh.crossSections([((origin.x, origin.y, origin.z), (a.x, a.y, a.z))], tol)
    out = []
    for w in (polys[0] if polys else []):
        if len(w) < 2:
            continue
        closed = (w[0] - w[-1]).Length < 1e-6
        pts2 = [((p - origin).dot(e1), (p - origin).dot(e2)) for p in w]
        out.append((pts2, closed, list(w)))
    return (origin, e1, e2), out


def mesh_section(mesh, axis, position, fill_holes=True, max_fill_radius=10.0, fit_tol=0.05, corner_tol=0.15):
    """_section과 같은 형식: (frame, wires, filled_count, warnings)."""
    frame, polys = mesh_cross_section(mesh, axis, position)
    warnings = []
    wires = []
    for pts2, closed, _ in polys:
        els, unsupported, res = polyline_to_elements(pts2, closed, fit_tol, corner_tol)
        if not els:
            continue
        area = round(_shoelace(pts2[:-1] if closed and len(pts2) > 1 and pts2[0] == pts2[-1] else pts2), 4) if closed else None
        xs = [p[0] for p in pts2]
        ys = [p[1] for p in pts2]
        wires.append({
            "closed": bool(closed), "area": area, "bbox_2d": [[round(min(xs), 4), round(min(ys), 4)], [round(max(xs), 4), round(max(ys), 4)]],
            "elements_total": len(els), "elements": els, "unsupported": unsupported,
            "max_endpoint_deviation": 0.0, "fit": {"points_in": len(pts2), "max_residual": res},
        })
    wires.sort(key=lambda w: -(w["area"] or 0.0))
    filled = 0
    if fill_holes and wires:
        keep = [wires[0]]
        for w in wires[1:]:
            els = w["elements"]
            if len(els) == 1 and els[0]["type"] == "circle" and els[0]["radius"] <= float(max_fill_radius):
                filled += 1
                continue
            keep.append(w)
        wires = keep
    for k, w in enumerate(wires):
        w["outer"] = k == 0
    if not polys:
        warnings.append("이 위치에서 메시 단면이 비어 있습니다.")
    return frame, wires, filled, warnings


# --- 레벨·주축 ----------------------------------------------------------------------


def _mesh_levels(mesh, axis, pos_tol=0.02, min_area_ratio=0.002):
    """축에 수직인 면들을 위치별로 묶는다 → [{position, area, facets}], 정점 위치 히스토그램."""
    a = Vec(axis).normalize()
    buckets = {}
    total = 0.0
    for f in mesh.Facets:
        nrm = Vec(*f.Normal)
        if nrm.Length < 1e-9:
            continue
        if abs(abs(nrm.dot(a)) - 1.0) > 1e-4:
            continue
        p = f.Points[0]
        pos = Vec(*p).dot(a)
        key = round(pos / pos_tol) * pos_tol
        b = buckets.setdefault(key, [0.0, 0, 0.0])
        b[0] += f.Area
        b[1] += 1
        b[2] += pos * f.Area
        total += f.Area
    levels = []
    biggest = max((b[0] for b in buckets.values()), default=0.0)
    for key, (area, count, wpos) in buckets.items():
        if area < min_area_ratio * biggest:
            continue
        levels.append({"position": round(wpos / area, 3) + 0.0, "area": round(area, 3), "facets": count})
    levels.sort(key=lambda x: x["position"])
    hist = {}
    for p in mesh.Points:
        t = round(Vec(p.x, p.y, p.z).dot(a), 2)
        hist[t] = hist.get(t, 0) + 1
    verts = [{"position": k, "vertices": n} for k, n in sorted(hist.items(), key=lambda kv: -kv[1])[:20]]
    verts.sort(key=lambda v: v["position"])
    return levels, verts


def _main_axis(mesh):
    """X/Y/Z 중 그 축에 수직인 평면 면적이 가장 큰 것."""
    score = {"X": 0.0, "Y": 0.0, "Z": 0.0}
    for f in mesh.Facets:
        n = Vec(*f.Normal)
        for k, c in (("X", Vec(1, 0, 0)), ("Y", Vec(0, 1, 0)), ("Z", Vec(0, 0, 1))):
            if abs(abs(n.dot(c)) - 1.0) < 1e-4:
                score[k] += f.Area
    letter = max(score, key=score.get)
    return {"X": Vec(1, 0, 0), "Y": Vec(0, 1, 0), "Z": Vec(0, 0, 1)}[letter], letter, {k: round(v, 2) for k, v in score.items()}


def _mesh_or_error(d, name):
    obj, err = util.find_object(d, name)
    if err:
        return None, None, err
    if obj.TypeId != "Mesh::Feature" or not hasattr(obj, "Mesh"):
        return obj, None, f"'{obj.Name}'({obj.TypeId})은(는) Mesh::Feature가 아닙니다."
    return obj, obj.Mesh, None


def is_mesh_object(obj):
    return obj is not None and obj.TypeId == "Mesh::Feature" and hasattr(obj, "Mesh")


# --- 7.23 import_mesh ---------------------------------------------------------------


def import_mesh(path=None, doc=None, transparency=70, label=None):
    """STL/OBJ/PLY/3MF를 참고용 Mesh 객체로 읽는다(변환하지 않는다). [확인됨: api-notes 16장]"""
    t0 = time.time()
    if not path or not os.path.isfile(str(path)):
        return util.error(f"파일이 없습니다: {path}")
    ext = os.path.splitext(str(path))[1].lower()
    if ext not in (".stl", ".ast", ".obj", ".ply", ".3mf", ".off", ".bms", ".amf"):
        return util.error(f"메시 파일이 아닙니다({ext}). STL/OBJ/PLY/3MF만 됩니다. STEP은 import_step으로.")
    import Mesh

    if doc:
        d, err = util.get_doc(doc)
        if err:
            return util.error(err)
    else:
        d = FreeCAD.ActiveDocument or FreeCAD.newDocument(os.path.splitext(os.path.basename(str(path)))[0][:40] or "Mesh")
    before = {o.Name for o in d.Objects}
    try:
        Mesh.insert(str(path), d.Name)
    except Exception as e:  # noqa: BLE001
        return util.error(f"메시 읽기 실패: {e}", e)
    new = [o for o in d.Objects if o.Name not in before and o.TypeId == "Mesh::Feature"]
    if not new:
        return util.error("메시 객체가 만들어지지 않았습니다(빈 파일?).")
    obj = new[-1]
    if label:
        obj.Label = str(label)
    warnings = []
    if FreeCAD.GuiUp and transparency:
        try:
            obj.ViewObject.Transparency = int(transparency)
        except Exception:  # noqa: BLE001
            pass
    m = obj.Mesh
    bb = m.BoundBox
    solid = bool(m.isSolid())
    if not solid:
        warnings.append("닫힌(솔리드) 메시가 아닙니다. 부피·편차 비교를 믿지 마세요.")
    data = {
        "document": d.Name, "name": obj.Name, "label": util.label(obj), "path": str(path),
        "facets": m.CountFacets, "points": m.CountPoints, "is_solid": solid,
        "non_manifold": bool(m.hasNonManifolds()), "self_intersections": bool(m.hasSelfIntersections()) if m.CountFacets < 200000 else None,
        "bbox": util.serialize(bb), "size": [round(bb.XLength, 4), round(bb.YLength, 4), round(bb.ZLength, 4)],
        "volume": round(m.Volume, 4) if solid else None, "transparency": int(transparency) if FreeCAD.GuiUp else None,
    }
    d.recompute()
    return util.envelope(data, warnings=warnings, t0=t0)


# --- 7.24 analyze_mesh --------------------------------------------------------------


def _polar(pts2, c):
    return [(math.degrees(math.atan2(p[1] - c[1], p[0] - c[0])) % 360.0, math.hypot(p[0] - c[0], p[1] - c[1])) for p in pts2]


def _crest_angle(pr, top_frac=0.05):
    rs = sorted(r for a, r in pr)
    thr = rs[max(0, int(len(rs) * (1 - top_frac)) - 1)]
    hi = [a for a, r in pr if r >= thr]
    s = sum(math.sin(math.radians(a)) for a in hi)
    c = sum(math.cos(math.radians(a)) for a in hi)
    return math.degrees(math.atan2(s, c)) % 360.0


def _detect_thread(mesh, axis, z0, z1, center2, dz=0.2, max_steps=60):
    """띠 안에서 최대 반지름 각도가 z에 비례해 돌면 나사. → dict 또는 None.

    z 간격은 피치의 절반보다 작아야 각도가 접히지 않는다(별칭) → 기본 0.2 mm, 최대 60장.
    중심은 여러 높이의 원 피팅 중심 평균으로 다시 잡는다(산이 한쪽에 있어 한 단면의 피팅 중심은 치우친다).
    """
    if z1 - z0 < 1.0:
        return None
    n = int(min(max_steps, max(6, (z1 - z0) / dz)))
    zs = [z0 + (z1 - z0) * (k + 0.5) / n for k in range(n)]
    outers = []
    for z in zs:
        _, polys = mesh_cross_section(mesh, axis, z)
        outer = max(polys, key=lambda p: _shoelace(p[0]) if p[1] else 0.0, default=None)
        if outer is None:
            return None
        outers.append(outer[0])
    fits = [fit_circle(o) for o in outers]
    fits = [f for f in fits if f]
    if len(fits) >= 3:
        cx = sum(f[0] for f in fits) / len(fits)
        cy = sum(f[1] for f in fits) / len(fits)
        center2 = [cx, cy]
    angs, rmax, rmin = [], 0.0, 1e9
    for o in outers:
        pr = _polar(o, center2)
        rs = [r for a, r in pr]
        if max(rs) - min(rs) < 0.2:
            return None
        angs.append(_crest_angle(pr))
        rmax, rmin = max(rmax, max(rs)), min(rmin, min(rs))
    # 각도 펼치기
    un = [angs[0]]
    for a in angs[1:]:
        prev = un[-1]
        d = (a - prev + 180.0) % 360.0 - 180.0
        un.append(prev + d)
    dz = zs[1] - zs[0]
    rates = [(un[k + 1] - un[k]) / dz for k in range(len(un) - 1)]
    mean = sum(rates) / len(rates)
    if abs(mean) < 5.0:
        return None
    spread = max(abs(r - mean) for r in rates)
    if spread > 0.35 * abs(mean):
        return None
    pitch = 360.0 / abs(mean)
    return {"major_r": round(rmax, 3), "minor_r": round(rmin, 3), "pitch": round(pitch, 3), "z_from": round(z0, 3), "z_to": round(z1, 3),
            "handedness": "right" if mean > 0 else "left", "deg_per_mm": round(mean, 2), "center": [round(center2[0], 4), round(center2[1], 4)]}


def analyze_mesh(name=None, doc=None, axis=None, fit_tolerance=0.05, max_levels=30, max_bands=30, detect_thread=True, max_wires=8):
    """메시의 주축·레벨·띠별 단면 원·공통 중심·나사·verdict. 목록은 개수만. [확인됨: api-notes 16장]"""
    t0 = time.time()
    d, err = util.get_doc(doc)
    if err:
        return util.error(err)
    obj, mesh, err = _mesh_or_error(d, name)
    if err:
        return util.error(err)
    warnings = []
    if axis:
        from .rebuild import _axis_letter, _parse_axis  # noqa: WPS433

        ax, err = _parse_axis(axis)
        if err:
            return util.error(err)
        letter = _axis_letter(ax)
        scores = None
    else:
        ax, letter, scores = _main_axis(mesh)
    levels, verts = _mesh_levels(mesh, ax)
    bb = mesh.BoundBox
    lo = Vec(bb.XMin, bb.YMin, bb.ZMin).dot(ax) if ax.dot(Vec(1, 1, 1)) > 0 else Vec(bb.XMax, bb.YMax, bb.ZMax).dot(ax)
    hi = Vec(bb.XMax, bb.YMax, bb.ZMax).dot(ax) if ax.dot(Vec(1, 1, 1)) > 0 else Vec(bb.XMin, bb.YMin, bb.ZMin).dot(ax)
    lo, hi = min(lo, hi), max(lo, hi)
    cuts = sorted({round(lo, 3), round(hi, 3)} | {lv["position"] for lv in levels})
    bands = []
    centers, approx_centers = [], []
    n_circle_wires = n_wires = 0
    for z0, z1 in zip(cuts[:-1], cuts[1:]):
        if z1 - z0 < 0.05:
            continue
        mid = (z0 + z1) / 2.0
        try:
            _, wires, _, _ = mesh_section(mesh, ax, mid, fill_holes=False, fit_tol=fit_tolerance)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"z={mid:.3f} 단면 실패: {e}")
            continue
        circles, others = [], []
        for w in wires:
            n_wires += 1
            els = w["elements"]
            if len(els) == 1 and els[0]["type"] == "circle":
                n_circle_wires += 1
                circles.append({"center": els[0]["center"], "r": els[0]["radius"], "rms": w["fit"]["max_residual"]})
                centers.append(tuple(els[0]["center"]))
            else:
                others.append({"elements": len(els), "lines": sum(1 for e in els if e["type"] == "line"), "arcs": sum(1 for e in els if e["type"] == "arc"),
                               "unsupported": w["unsupported"], "closed": w["closed"], "bbox_2d": w["bbox_2d"], "area": w["area"]})
                if w["closed"] and w["bbox_2d"]:
                    (x0, y0), (x1, y1) = w["bbox_2d"]
                    if abs((x1 - x0) - (y1 - y0)) < 0.1 * max(x1 - x0, y1 - y0, 1e-9):   # 정사각 bbox = 둥근 윤곽 후보
                        approx_centers.append(((x0 + x1) / 2.0, (y0 + y1) / 2.0))
        bands.append({"from": z0, "to": z1, "mid": round(mid, 3), "circles": circles[:max_wires], "wires": others[:max_wires],
                      "wires_total": len(wires)})
    center2, center_source = None, None
    if centers:
        cx = sorted(c[0] for c in centers)[len(centers) // 2]
        cy = sorted(c[1] for c in centers)[len(centers) // 2]
        if all(math.hypot(c[0] - cx, c[1] - cy) < max(0.2, 4 * fit_tolerance) for c in centers):
            center2, center_source = [round(cx, 4), round(cy, 4)], "circles"
    if center2 is None and approx_centers:
        # 원은 아니지만(나사·다각형) 둥근 윤곽들의 최소제곱 원 중심 — 나사 감지용 근사 중심
        cx = sorted(c[0] for c in approx_centers)[len(approx_centers) // 2]
        cy = sorted(c[1] for c in approx_centers)[len(approx_centers) // 2]
        if all(math.hypot(c[0] - cx, c[1] - cy) < 1.0 for c in approx_centers):
            center2, center_source = [round(cx, 4), round(cy, 4)], "approx"
    thread = None
    if detect_thread and center2:
        for b in bands:
            outer_is_circle = bool(b["circles"]) and (not b["wires"] or (b["wires"][0]["area"] or 0) <= max(math.pi * c["r"] ** 2 for c in b["circles"]))
            if b["wires"] and not outer_is_circle:
                th = _detect_thread(mesh, ax, b["from"], b["to"], center2)
                if th:
                    thread = th
                    if center_source == "approx":
                        center2, center_source = th["center"], "thread"
                    break
    if n_wires and n_circle_wires >= 0.8 * n_wires and center2:
        verdict = "revolved"
    elif bands and all(not w["unsupported"] for b in bands for w in b["wires"]):
        verdict = "prismatic"
    else:
        verdict = "mixed"
    # 주축 3D 좌표계에서의 중심 (축이 Z면 (x, y))
    e1, e2 = _perp_frame(ax)
    center3 = None
    if center2:
        c3 = e1 * center2[0] + e2 * center2[1]
        center3 = [round(c3.x, 4), round(c3.y, 4), round(c3.z, 4)]
    data = {
        "document": d.Name, "object": obj.Name, "label": util.label(obj),
        "facets": mesh.CountFacets, "is_solid": bool(mesh.isSolid()), "volume": round(mesh.Volume, 4) if mesh.isSolid() else None,
        "bbox": util.serialize(bb),
        "main_axis": [round(ax.x, 6), round(ax.y, 6), round(ax.z, 6)], "main_axis_letter": letter, "axis_scores": scores,
        "extent": [round(lo, 3), round(hi, 3)],
        "levels": levels[:max_levels], "levels_total": len(levels), "vertex_positions": verts,
        "bands": bands[:max_bands], "bands_total": len(bands),
        "center": center2, "center_source": center_source, "center_3d": center3, "thread": thread, "verdict": verdict,
        "notes": [],
    }
    if center2 and center_source == "circles":
        data["notes"].append(f"단면 원 {n_circle_wires}/{n_wires}개가 공통 중심 {center2}를 가진다 — 회전체 계열. build_features의 원 중심에 이 값을 쓴다.")
    elif center2:
        data["notes"].append(f"둥근 윤곽의 근사 중심 {center2} (원 피팅은 안 됨 — 나사·다각형).")
    if thread:
        data["notes"].append(f"나사: 피치 {thread['pitch']}, 외경 r {thread['major_r']}, 골 r {thread['minor_r']}, z {thread['z_from']}~{thread['z_to']}, {thread['handedness']}-hand. build_features의 helix op로 만든다.")
    if not levels:
        warnings.append("주축에 수직인 평면이 없습니다. 축이 틀렸거나 자유곡면 부품입니다(axis 인자로 지정).")
    if len(levels) > max_levels:
        warnings.append(f"levels는 {max_levels}/{len(levels)}개까지입니다.")
    truncated = len(levels) > max_levels or len(bands) > max_bands
    return util.envelope(data, warnings=warnings, truncated=truncated, t0=t0)


# --- 7.26 메시 편차 ------------------------------------------------------------------


def mesh_deviation(mesh, shape, samples=1500, reverse_samples=1500, back_off=0.6):
    """Body 면 표본 → 메시(법선 ± 광선) 편차, 메시 정점 → Body 거리. 둘 다 최대/평균/p95와 최악 점."""
    t0 = time.time()
    faces = shape.Faces
    per_face = max(2, int(math.sqrt(max(samples, 4) / max(len(faces), 1))) + 1)
    pts = []
    for fi, f in enumerate(faces):
        u0, u1, v0, v1 = f.ParameterRange
        n_side = max(2, min(per_face, int(math.sqrt(f.Area) / 6) + 2))
        for i in range(n_side):
            for j in range(n_side):
                u = u0 + (u1 - u0) * (i + 0.5) / n_side
                v = v0 + (v1 - v0) * (j + 0.5) / n_side
                if not f.isPartOfDomain(u, v):
                    continue
                pts.append((fi + 1, f.valueAt(u, v), f.normalAt(u, v)))
    devs, miss = [], 0
    for fi, p, n in pts:
        best = None
        for sgn in (1.0, -1.0):
            dvec = Vec(n.x * sgn, n.y * sgn, n.z * sgn)
            start = Vec(p.x - dvec.x * back_off, p.y - dvec.y * back_off, p.z - dvec.z * back_off)
            try:
                hit = mesh.nearestFacetOnRay((start.x, start.y, start.z), (dvec.x, dvec.y, dvec.z))
            except Exception:  # noqa: BLE001
                hit = None
            if hit:
                q = Vec(*list(hit.values())[0])
                dist = (q - p).Length
                if best is None or dist < best:
                    best = dist
        if best is None:
            miss += 1
        else:
            devs.append((best, fi, p))
    devs.sort(key=lambda t: -t[0])
    fwd = None
    if devs:
        vals = [t[0] for t in devs]
        fwd = {"samples": len(pts), "missed": miss, "max": round(vals[0], 4), "mean": round(sum(vals) / len(vals), 4),
               "p95": round(vals[int(len(vals) * 0.05)], 4),
               "worst": [{"distance": round(t[0], 4), "face": f"Face{t[1]}", "point": [round(t[2].x, 2), round(t[2].y, 2), round(t[2].z, 2)]} for t in devs[:5]]}
    mpts = mesh.Points
    step = max(1, len(mpts) // max(reverse_samples, 1))
    rev = []
    for k in range(0, len(mpts), step):
        v = mpts[k]
        try:
            dd = shape.distToShape(Part.Vertex(Vec(v.x, v.y, v.z)))[0]
        except Exception:  # noqa: BLE001
            continue
        rev.append((dd, (round(v.x, 2), round(v.y, 2), round(v.z, 2))))
    rev.sort(key=lambda t: -t[0])
    back = None
    if rev:
        vals = [t[0] for t in rev]
        back = {"samples": len(rev), "max": round(vals[0], 4), "mean": round(sum(vals) / len(vals), 4), "p95": round(vals[int(len(vals) * 0.05)], 4),
                "worst": [{"distance": round(t[0], 4), "point": list(t[1])} for t in rev[:5]]}
    return {"body_to_mesh": fwd, "mesh_to_body": back, "elapsed_ms": int((time.time() - t0) * 1000)}


TOOLS = {"import_mesh": import_mesh, "analyze_mesh": analyze_mesh}
