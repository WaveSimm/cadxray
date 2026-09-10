"""STEP → 파라메트릭 재구성 보조 (명세 7.16~7.19, M7).

classify_faces  : 면마다 정체(평면/원통/원뿔/구/자유곡면)를 판정한다. BSpline 면도 표본을 찍어 맞춰 본다.
section_profile : 축 방향 높이의 단면 윤곽을 스케치에 넣을 수 있는 선분·호·원 목록으로 준다.
build_features  : 스케치 + Pad/Pocket/Groove/Revolution/Fillet/Chamfer 목록을 Body에 순서대로 쌓는다.
compare_shapes  : 두 형상의 부피·면적·bbox 차와 퍼지 차집합 조각(어디가 틀렸나)을 준다.

API는 api-notes 7·7.5·12·13장에서 확인한 것만 쓴다 [라이브 1.1.3]. 수치 알고리즘(3×3 고유값,
원 맞춤)은 stdlib만으로 구현했다 — 애드온은 외부 패키지를 쓸 수 없다.
"""

import math
import time

import FreeCAD
import Part

from . import util
from .shape_features import _arc_deg, _canonical_axis, _is_concave, _line_key, _shape_or_error

Vec = FreeCAD.Vector
TWO_PI = 2.0 * math.pi

_CANON = {"X": Vec(1, 0, 0), "Y": Vec(0, 1, 0), "Z": Vec(0, 0, 1)}
# 스케치 평면 [확인됨: api-notes 7.5]: (Origin 평면 Role, 로컬 x, 로컬 y, 오프셋 부호)
_PLANES = {
    "XY": ("XY_Plane", "X", "Y", 1.0),
    "XZ": ("XZ_Plane", "X", "Z", -1.0),
    "YZ": ("YZ_Plane", "Y", "Z", 1.0),
}
_PLANE_AXIS = {"XY": "Z", "XZ": "Y", "YZ": "X"}


# --- 작은 선형대수 ----------------------------------------------------------------


def _jacobi_eig3(m):
    """대칭 3×3 행렬의 (고유값 오름차순, 고유벡터 Vec 목록). Jacobi 회전."""
    a = [row[:] for row in m]
    v = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    for _ in range(60):
        p, q, mx = 0, 1, 0.0
        for i in range(3):
            for j in range(i + 1, 3):
                if abs(a[i][j]) > mx:
                    p, q, mx = i, j, abs(a[i][j])
        if mx < 1e-18:
            break
        theta = (a[q][q] - a[p][p]) / (2.0 * a[p][q])
        t = (1.0 if theta >= 0 else -1.0) / (abs(theta) + math.sqrt(theta * theta + 1.0))
        c = 1.0 / math.sqrt(t * t + 1.0)
        s = t * c
        for k in range(3):
            akp, akq = a[k][p], a[k][q]
            a[k][p], a[k][q] = c * akp - s * akq, s * akp + c * akq
        for k in range(3):
            apk, aqk = a[p][k], a[q][k]
            a[p][k], a[q][k] = c * apk - s * aqk, s * apk + c * aqk
        for k in range(3):
            vkp, vkq = v[k][p], v[k][q]
            v[k][p], v[k][q] = c * vkp - s * vkq, s * vkp + c * vkq
    order = sorted(range(3), key=lambda i: a[i][i])
    return [a[i][i] for i in order], [Vec(v[0][i], v[1][i], v[2][i]) for i in order]


def _solve3(a, b):
    """3×3 연립방정식 (Cramer). 특이하면 None."""
    det = (
        a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1])
        - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
        + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0])
    )
    if abs(det) < 1e-14:
        return None
    out = []
    for col in range(3):
        m = [row[:] for row in a]
        for r in range(3):
            m[r][col] = b[r]
        d = (
            m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
            - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
            + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
        )
        out.append(d / det)
    return out


def _circle_fit_2d(pts):
    """대수적 원 맞춤(Kåsa). (cx, cy, r, 최대 잔차) 또는 None."""
    n = len(pts)
    if n < 3:
        return None
    sx = sy = sxx = syy = sxy = sz = sxz = syz = 0.0
    for x, y in pts:
        z = x * x + y * y
        sx += x
        sy += y
        sxx += x * x
        syy += y * y
        sxy += x * y
        sz += z
        sxz += x * z
        syz += y * z
    sol = _solve3([[sxx, sxy, sx], [sxy, syy, sy], [sx, sy, float(n)]], [-sxz, -syz, -sz])
    if sol is None:
        return None
    dd, ee, ff = sol
    cx, cy = -dd / 2.0, -ee / 2.0
    rr = cx * cx + cy * cy - ff
    if rr <= 0:
        return None
    r = math.sqrt(rr)
    resid = max(abs(math.hypot(x - cx, y - cy) - r) for x, y in pts)
    return cx, cy, r, resid


def _center_from_normals_2d(pts, nrms):
    """2D 법선 직선들의 최소제곱 교점. Σ(I − m mᵀ)c = Σ(I − m mᵀ)p"""
    a11 = a12 = a22 = b1 = b2 = 0.0
    for (px, py), (mx, my) in zip(pts, nrms):
        length = math.hypot(mx, my)
        if length < 1e-9:
            continue
        mx, my = mx / length, my / length
        a11 += 1.0 - mx * mx
        a12 += -mx * my
        a22 += 1.0 - my * my
        b1 += (1.0 - mx * mx) * px - mx * my * py
        b2 += -mx * my * px + (1.0 - my * my) * py
    det = a11 * a22 - a12 * a12
    if abs(det) < 1e-12:
        return None
    return (a22 * b1 - a12 * b2) / det, (a11 * b2 - a12 * b1) / det


def _line_fit(ts, rs):
    """r = r0 + k·t 최소제곱 → (r0, k, 최대 잔차)"""
    n = len(ts)
    mt, mr = sum(ts) / n, sum(rs) / n
    stt = sum((t - mt) ** 2 for t in ts)
    if stt < 1e-14:
        return mr, 0.0, max(abs(r - mr) for r in rs)
    k = sum((t - mt) * (r - mr) for t, r in zip(ts, rs)) / stt
    r0 = mr - k * mt
    return r0, k, max(abs(r - (r0 + k * t)) for t, r in zip(ts, rs))


def _axis_letter(v, tol=1e-6):
    for letter, c in _CANON.items():
        if abs(abs(v.dot(c)) - 1.0) < tol:
            return letter
    return None


def _perp_frame(axis):
    """축에 수직인 정규직교 (e1, e2). 표준축이면 스케치 평면 규약과 같은 프레임."""
    letter = _axis_letter(axis)
    if letter == "Z":
        return Vec(1, 0, 0), Vec(0, 1, 0)
    if letter == "Y":
        return Vec(1, 0, 0), Vec(0, 0, 1)
    if letter == "X":
        return Vec(0, 1, 0), Vec(0, 0, 1)
    ref = Vec(0, 0, 1) if abs(axis.z) < 0.9 else Vec(1, 0, 0)
    e1 = axis.cross(ref)
    e1.normalize()
    e2 = axis.cross(e1)
    e2.normalize()
    return e1, e2


def _r3(v, nd=4):
    return [round(float(v.x), nd), round(float(v.y), nd), round(float(v.z), nd)]


def _r2(x, y, nd=10):
    # 스케치에 다시 그릴 좌표라 정밀도를 유지한다(6자리로 깎으면 이음매마다 5e-7 틈이 생겨 DoF가 남는다)
    return [round(float(x), nd), round(float(y), nd)]


def _bbox(shape):
    return util.serialize(shape.BoundBox)


# --- 7.16 classify_faces ---------------------------------------------------------


def _sample_face(face, n):
    """면 위 격자 표본 (점, 단위법선). 도메인 밖 점은 버린다. [api-notes 13장]"""
    u0, u1, v0, v1 = face.ParameterRange
    pts, nrms = [], []
    for i in range(n):
        u = u0 + (u1 - u0) * (i + 0.5) / n
        for j in range(n):
            v = v0 + (v1 - v0) * (j + 0.5) / n
            try:
                if not face.isPartOfDomain(u, v):
                    continue
                p = face.valueAt(u, v)
                nv = face.normalAt(u, v)
            except Exception:
                continue
            if nv.Length < 1e-12:
                continue
            nv.normalize()
            pts.append(Vec(p))
            nrms.append(nv)
    return pts, nrms


def _angular_span_deg(pts2, c):
    """중심 c 둘레의 표본 각도가 덮는 범위(도). 가장 큰 빈틈을 360에서 뺀 값."""
    angs = sorted(math.atan2(y - c[1], x - c[0]) % TWO_PI for x, y in pts2)
    if len(angs) < 2:
        return 0.0
    gaps = [angs[i + 1] - angs[i] for i in range(len(angs) - 1)]
    gaps.append(angs[0] + TWO_PI - angs[-1])
    return round(math.degrees(TWO_PI - max(gaps)), 1)


def _boundary_span_deg(face, c2, e1, e2, per_edge=72):
    """면 경계를 잘게 찍어 중심 c2 둘레의 각도 범위(도). 표본 격자보다 정확하다."""
    angs = []
    try:
        for e in face.OuterWire.Edges:
            for p in e.discretize(Number=per_edge):
                x, y = Vec(p).dot(e1), Vec(p).dot(e2)
                if math.hypot(x - c2[0], y - c2[1]) > 1e-9:
                    angs.append(math.atan2(y - c2[1], x - c2[0]) % TWO_PI)
    except Exception:
        return None
    if len(angs) < 2:
        return None
    angs.sort()
    gaps = [angs[i + 1] - angs[i] for i in range(len(angs) - 1)]
    gaps.append(angs[0] + TWO_PI - angs[-1])
    return round(min(360.0, math.degrees(TWO_PI - max(gaps)) + 360.0 / per_edge), 1)


def _abs_dot_stats(nrms, a):
    vals = [abs(v.dot(a)) for v in nrms]
    return sum(vals) / len(vals), max(vals) - min(vals)


def _fit_identity(face, samples, tol):
    """BSpline 등 비해석면의 정체를 표본으로 맞춘다.

    법선의 부호는 믿지 않는다 [라이브 1.1.3: transformGeometry한 원뿔 BSpline의 normalAt이 일부 표본에서
    뒤집혀 나온다] — 모든 판정은 |n·a| 와 점 좌표로 하고, 오목/볼록·법선 방향은 다수결로 정한다.
    """
    pts, nrms = _sample_face(face, samples)
    if len(pts) < 6:
        return {"identity": "free_form", "method": "fit", "reason": "표본 부족", "samples": len(pts)}
    n = len(pts)
    cen = Vec(0, 0, 0)
    for p in pts:
        cen += p
    cen = cen * (1.0 / n)
    nbar = Vec(0, 0, 0)
    for v in nrms:
        nbar += v

    # 후보 축: Σnnᵀ(부호 무관)·공분산의 고유벡터 + X/Y/Z
    mom = [[0.0] * 3 for _ in range(3)]
    cov = [[0.0] * 3 for _ in range(3)]
    nb = nbar * (1.0 / n)
    for v in nrms:
        vv = (v.x, v.y, v.z)
        d = v - nb
        dd = (d.x, d.y, d.z)
        for i in range(3):
            for j in range(3):
                mom[i][j] += vv[i] * vv[j]
                cov[i][j] += dd[i] * dd[j]
    cands = []
    for m in (mom, cov):
        try:
            cands += _jacobi_eig3(m)[1]
        except Exception:
            pass
    cands += [Vec(1, 0, 0), Vec(0, 1, 0), Vec(0, 0, 1)]

    def majority_sign(values):
        return 1.0 if sum(1 if x > 0 else -1 for x in values) >= 0 else -1.0

    # 1) 평면: |n·a| ≡ 1 이고 점이 한 평면 위 (isPlanar가 먼저 답하면 그것으로)
    planar = False
    try:
        planar = bool(face.Surface.isPlanar(tol))
    except Exception:
        pass
    for a in cands:
        mu, spread = _abs_dot_stats(nrms, a)
        if spread < 1e-4 and mu > 1.0 - 1e-4:
            dev_p = max(abs((p - cen).dot(a)) for p in pts)
            if planar or dev_p <= tol:
                nrm = Vec(a) * majority_sign([v.dot(a) for v in nrms])
                nrm.normalize()
                return {
                    "identity": "plane", "method": "fit", "residual": round(dev_p, 9), "samples": n,
                    "normal": _r3(nrm, 6), "position": round(cen.dot(nrm), 6),
                }

    # 2) 축이 있는 면(원통·원뿔): 후보 축마다 축 위치(법선 직선 최소제곱) + r(t) 선형 맞춤, 잔차 최소
    best = None
    seen = set()
    for a0 in cands:
        a = _canonical_axis(a0)
        if a is None:
            continue
        key = tuple(round(c, 4) for c in (a.x, a.y, a.z))
        if key in seen:
            continue
        seen.add(key)
        mu, spread = _abs_dot_stats(nrms, a)
        if spread > 0.05 or mu > 1.0 - 1e-6:
            continue
        e1, e2 = _perp_frame(a)
        p2 = [(p.dot(e1), p.dot(e2)) for p in pts]
        m2 = [(v.dot(e1), v.dot(e2)) for v in nrms]
        c2 = _center_from_normals_2d(p2, m2)
        if c2 is None:
            continue
        ts = [p.dot(a) for p in pts]
        rs = [math.hypot(x - c2[0], y - c2[1]) for x, y in p2]
        r0, k, resid = _line_fit(ts, rs)
        if best is None or resid < best[0]:
            best = (resid, a, e1, e2, c2, r0, k, ts, rs, p2)
    if best is not None and best[0] <= tol:
        resid, a, e1, e2, c2, r0, k, ts, rs, p2 = best
        foot = e1 * c2[0] + e2 * c2[1]
        votes = []
        for p, v in zip(pts, nrms):
            on_axis = foot + a * (p.dot(a))
            votes.append((on_axis - p).dot(v))
        concave = majority_sign(votes) > 0
        span = _boundary_span_deg(face, c2, e1, e2)
        if span is None:
            span = _angular_span_deg(p2, c2)
        if abs(k) < 1e-6:
            r = sum(rs) / n
            return {
                "identity": "cylinder", "method": "fit", "residual": round(resid, 9), "samples": n,
                "radius": round(r, 6), "axis": _r3(a, 6), "axis_letter": _axis_letter(a),
                "center": _r3(foot, 6), "concave": bool(concave), "arc_deg": span,
            }
        t_apex = -r0 / k
        return {
            "identity": "cone", "method": "fit", "residual": round(resid, 9), "samples": n,
            "axis": _r3(a, 6), "axis_letter": _axis_letter(a),
            "apex": _r3(foot + a * t_apex, 6), "semi_angle_deg": round(math.degrees(math.atan(abs(k))), 4),
            "radius_range": [round(min(rs), 6), round(max(rs), 6)],
            "concave": bool(concave), "arc_deg": span,
        }

    # 3) 구: 법선 직선들이 한 점에 모인다 (부호 무관)
    a3 = [[0.0] * 3 for _ in range(3)]
    b3 = [0.0, 0.0, 0.0]
    for p, v in zip(pts, nrms):
        vv = (v.x, v.y, v.z)
        pp = (p.x, p.y, p.z)
        for i in range(3):
            for j in range(3):
                proj = (1.0 if i == j else 0.0) - vv[i] * vv[j]
                a3[i][j] += proj
                b3[i] += proj * pp[j]
    sol = _solve3(a3, b3)
    if sol is not None:
        c = Vec(*sol)
        rs = [(p - c).Length for p in pts]
        r = sum(rs) / n
        resid = max(abs(x - r) for x in rs)
        if resid <= tol and r > 1e-6:
            concave = majority_sign([(c - p).dot(v) for p, v in zip(pts, nrms)]) > 0
            return {
                "identity": "sphere", "method": "fit", "residual": round(resid, 9), "samples": n,
                "radius": round(r, 6), "center": _r3(c, 6), "concave": bool(concave),
            }

    # 4) 자유곡면 — 곡률 통계
    curv = {}
    try:
        u0, u1, v0, v1 = face.ParameterRange
        um, vm = (u0 + u1) / 2.0, (v0 + v1) / 2.0
        kmax = face.Surface.curvature(um, vm, "Max")
        kmin = face.Surface.curvature(um, vm, "Min")
        curv = {"max": round(kmax, 6), "min": round(kmin, 6)}
        kk = max(abs(kmax), abs(kmin))
        if kk > 1e-9:
            curv["min_radius_of_curvature"] = round(1.0 / kk, 4)
    except Exception:
        pass
    out = {"identity": "free_form", "method": "fit", "residual": None, "samples": n, "curvature": curv}
    if best is not None:
        out["best_axis_fit"] = {"axis": _r3(best[1], 4), "residual": round(best[0], 6),
                                "hint": "tolerance를 이 잔차보다 크게 주면 원통·원뿔로 채택된다"}
    return out


def _analytic_identity(face):
    """해석면은 Surface 속성을 그대로 읽는다. [api-notes 12장]"""
    surf = face.Surface
    stype = type(surf).__name__
    if stype == "Plane":
        nrm = Vec(surf.Axis)
        nrm.normalize()
        # 면의 실제 바깥 법선(Orientation 반영)
        try:
            u0, u1, v0, v1 = face.ParameterRange
            nrm = face.normalAt((u0 + u1) / 2.0, (v0 + v1) / 2.0)
            nrm.normalize()
        except Exception:
            pass
        return {"identity": "plane", "normal": _r3(nrm, 6), "position": round(Vec(surf.Position).dot(nrm), 6)}
    if stype == "Cylinder":
        axis = _canonical_axis(surf.Axis)
        center = Vec(surf.Center)
        foot = center - axis * center.dot(axis)
        return {
            "identity": "cylinder", "radius": round(float(surf.Radius), 6), "axis": _r3(axis, 6),
            "axis_letter": _axis_letter(axis), "center": _r3(foot, 6),
            "concave": bool(_is_concave(face, center, axis)), "arc_deg": _arc_deg([(0, face)]),
        }
    if stype == "Cone":
        axis = _canonical_axis(surf.Axis)
        apex = Vec(surf.Apex)
        rs = [((Vec(v.Point) - apex) - axis * (Vec(v.Point) - apex).dot(axis)).Length for v in face.Vertexes]
        return {
            "identity": "cone", "axis": _r3(axis, 6), "axis_letter": _axis_letter(axis), "apex": _r3(apex, 6),
            "semi_angle_deg": round(math.degrees(float(surf.SemiAngle)), 4),
            "radius_range": [round(min(rs), 6), round(max(rs), 6)] if rs else None,
            "concave": bool(_is_concave(face, apex, axis)), "arc_deg": _arc_deg([(0, face)]),
        }
    if stype == "Sphere":
        c = Vec(surf.Center)
        u0, u1, v0, v1 = face.ParameterRange
        p = face.valueAt((u0 + u1) / 2.0, (v0 + v1) / 2.0)
        nv = face.normalAt((u0 + u1) / 2.0, (v0 + v1) / 2.0)
        return {"identity": "sphere", "radius": round(float(surf.Radius), 6), "center": _r3(c, 6),
                "concave": bool((c - p).dot(nv) > 0)}
    if stype == "Toroid":
        axis = _canonical_axis(surf.Axis)
        return {
            "identity": "torus", "major_radius": round(float(surf.MajorRadius), 6),
            "minor_radius": round(float(surf.MinorRadius), 6), "axis": _r3(axis, 6) if axis else None,
            "center": _r3(Vec(surf.Center), 6),
        }
    return None


_ANALYTIC = ("Plane", "Cylinder", "Cone", "Sphere", "Toroid")


def _identify(face, samples, tol):
    stype = type(face.Surface).__name__
    rec = {"surface": stype}
    try:
        if stype in _ANALYTIC:
            ident = _analytic_identity(face)
            if ident:
                ident["method"] = "analytic"
                rec.update(ident)
                return rec
        rec.update(_fit_identity(face, samples, tol))
    except Exception as e:
        rec.update({"identity": "free_form", "method": "error", "error": str(e)})
    return rec


def _main_axis(recs):
    """평면(수직)·원통/원뿔(평행) 면적이 가장 큰 축."""
    cands = {"X": _CANON["X"], "Y": _CANON["Y"], "Z": _CANON["Z"]}
    for r in recs:
        if r.get("identity") in ("cylinder", "cone") and r.get("axis"):
            key = tuple(round(c, 3) for c in r["axis"])
            cands.setdefault(str(key), Vec(*r["axis"]))
    best, best_score = None, -1.0
    for key, ax in cands.items():
        score = 0.0
        for r in recs:
            ident = r.get("identity")
            if ident == "plane" and r.get("normal"):
                dot = abs(Vec(*r["normal"]).dot(ax))
                # 수직인 평면(레벨)은 온전히, 평행한 평면(벽)은 절반만 — 벽은 어느 축에도 평행해 결정력이 약하다
                if abs(dot - 1.0) < 1e-4:
                    score += r["area"]
                elif dot < 1e-4:
                    score += 0.5 * r["area"]
            elif ident in ("cylinder", "cone") and r.get("axis"):
                if abs(abs(Vec(*r["axis"]).dot(ax)) - 1.0) < 1e-4:
                    score += r["area"]
        if score > best_score:
            best, best_score = ax, score
    return best, best_score


def classify_faces(name=None, doc=None, samples=5, tolerance=1e-3, max_faces=200, include_analytic=True):
    """면마다 정체(plane/cylinder/cone/sphere/torus/free_form)를 판정하고 재구성 가능성을 평가한다."""
    t0 = time.time()
    d, err = util.get_doc(doc)
    if err:
        return util.error(err)
    obj, shape, err = _shape_or_error(d, name)
    if err:
        return util.error(err)
    samples = max(3, int(samples))
    tol = max(float(tolerance), 1e-9)
    warnings = []

    recs = []
    for i, f in enumerate(shape.Faces):
        rec = {"i": i}
        rec.update(_identify(f, samples, tol))
        rec["area"] = round(f.Area, 4)
        rec["bbox"] = _bbox(f)
        recs.append(rec)

    area_total = sum(r["area"] for r in recs) or 1.0
    by_surface, by_identity = {}, {}
    for r in recs:
        by_surface[r["surface"]] = by_surface.get(r["surface"], 0) + 1
        by_identity[r["identity"]] = by_identity.get(r["identity"], 0) + 1
    bspline = [r for r in recs if r["surface"] not in _ANALYTIC]
    resolved = [r for r in bspline if r["identity"] != "free_form"]
    free = [r for r in recs if r["identity"] == "free_form"]
    free_area = sum(r["area"] for r in free)

    axis, _ = _main_axis(recs)
    levels = {}
    radii = {}
    aligned_area = 0.0
    if axis is not None:
        for r in recs:
            if r["identity"] == "plane" and r.get("normal"):
                dot = abs(Vec(*r["normal"]).dot(axis))
                if abs(dot - 1.0) < 1e-4 or dot < 1e-4:  # 레벨 평면 + 벽
                    aligned_area += r["area"]
            elif r["identity"] in ("cylinder", "cone") and r.get("axis") and abs(abs(Vec(*r["axis"]).dot(axis)) - 1.0) < 1e-4:
                aligned_area += r["area"]
        for r in recs:
            if r["identity"] == "plane" and r.get("normal") and abs(abs(Vec(*r["normal"]).dot(axis)) - 1.0) < 1e-4:
                pos = round(r["position"] * (1.0 if Vec(*r["normal"]).dot(axis) > 0 else -1.0), 3) + 0.0
                lv = levels.setdefault(pos, {"position": pos, "area": 0.0, "faces": []})
                lv["area"] = round(lv["area"] + r["area"], 4)
                lv["faces"].append(r["i"])
            elif r["identity"] in ("cylinder", "cone") and r.get("axis") and abs(abs(Vec(*r["axis"]).dot(axis)) - 1.0) < 1e-4:
                key = (round(r.get("radius", r.get("radius_range", [0])[-1]), 3), bool(r.get("concave")), r["identity"])
                rd = radii.setdefault(key, {"radius": key[0], "concave": key[1], "identity": key[2], "faces": 0, "area": 0.0})
                rd["faces"] += 1
                rd["area"] = round(rd["area"] + r["area"], 4)
    aligned_pct = round(aligned_area / area_total * 100.0, 2)
    free_pct = round(free_area / area_total * 100.0, 3)
    if free_pct < 0.5 and aligned_pct > 90.0 and len(levels) >= 2:
        verdict = "prismatic"
    elif free_pct < 20.0:
        verdict = "mixed"
    else:
        verdict = "free_form"

    notes = []
    if bspline:
        notes.append(f"BSpline/비해석 면 {len(bspline)}개 중 {len(resolved)}개가 평면·원통·원뿔·구로 판별됨(가짜 자유곡면)")
    if free:
        notes.append(f"진짜 자유곡면 {len(free)}개, 면적 {free_pct} % → " + (
            "무시하거나 필렛으로 근사 가능" if free_pct < 0.5 else "BaseFeature 하이브리드(원본 형상 위에 피처) 권장"))
    if axis is not None:
        notes.append(f"주축 {_axis_letter(axis) or _r3(axis, 3)}: 정렬 면적 {aligned_pct} %, 레벨 {len(levels)}개 — "
                     "section_profile(position=레벨 값 사이)로 띠마다 단면을 뜬다")
    misaligned = [r["i"] for r in recs if r["identity"] == "plane" and axis is not None
                  and abs(Vec(*r["normal"]).dot(axis)) > 1e-4 and abs(abs(Vec(*r["normal"]).dot(axis)) - 1.0) > 1e-4]
    if misaligned:
        notes.append(f"주축에 수직도 평행도 아닌 평면 {len(misaligned)}개(경사면·구배): {misaligned[:10]}")

    faces_out = recs if include_analytic else bspline
    faces_out = faces_out[: max(0, int(max_faces))]
    truncated = len(faces_out) < (len(recs) if include_analytic else len(bspline))
    data = {
        "document": d.Name, "object": obj.Name, "label": util.label(obj),
        "faces_total": len(recs), "faces": faces_out,
        "summary": {
            "by_surface": by_surface, "by_identity": by_identity,
            "bspline_faces": len(bspline), "bspline_resolved": len(resolved),
            "free_form_faces": len(free), "free_form_area_pct": free_pct,
            "area_total": round(area_total, 4), "volume": round(shape.Volume, 4),
        },
        "rebuild": {
            "verdict": verdict, "main_axis": _r3(axis, 6) if axis is not None else None,
            "main_axis_letter": _axis_letter(axis) if axis is not None else None,
            "aligned_area_pct": aligned_pct,
            "levels": sorted(levels.values(), key=lambda x: x["position"])[:50],
            "radii": sorted(radii.values(), key=lambda x: -x["area"])[:30],
            "notes": notes,
        },
        "tolerance": tol,
    }
    if truncated:
        warnings.append(f"faces는 {len(faces_out)}/{len(recs)}개까지입니다. summary·rebuild는 전체 기준입니다.")
    if util.fit_cap(data, "faces", warnings):
        truncated = True
    return util.envelope(data, warnings=warnings, truncated=truncated, t0=t0)


# --- 7.17 section_profile --------------------------------------------------------


def _parse_axis(axis):
    if isinstance(axis, str):
        letter = axis.strip().upper().lstrip("+")
        neg = letter.startswith("-")
        letter = letter.lstrip("-")
        if letter not in _CANON:
            return None, f"axis는 'X'/'Y'/'Z' 또는 [x,y,z]여야 합니다: {axis!r}"
        v = Vec(_CANON[letter])
        return (v * -1.0 if neg else v), None
    try:
        v = Vec(float(axis[0]), float(axis[1]), float(axis[2]))
    except Exception:
        return None, f"axis는 'X'/'Y'/'Z' 또는 [x,y,z]여야 합니다: {axis!r}"
    if v.Length < 1e-12:
        return None, "axis가 영벡터입니다."
    v.normalize()
    return v, None


def _hole_fill_solids(shape, max_fill_radius, margin=0.05):
    """오목 원통·원뿔 그룹(호 합 ≥ 350°) 자리를 덮는 원기둥들. [api-notes 7.5: 2D 불리언 회피]"""
    groups = {}
    for i, f in enumerate(shape.Faces):
        stype = type(f.Surface).__name__
        if stype in ("Plane", "Sphere", "Toroid"):
            continue
        rec = _identify(f, 4, 1e-3)
        if rec.get("identity") not in ("cylinder", "cone") or not rec.get("concave"):
            continue
        axis = Vec(*rec["axis"])
        origin = Vec(*(rec["center"] if rec["identity"] == "cylinder" else rec["apex"]))
        foot = origin - axis * origin.dot(axis)
        rmax = rec["radius"] if rec["identity"] == "cylinder" else max(rec.get("radius_range") or [0])
        if rmax <= 0 or rmax > max_fill_radius:
            continue
        ts = [(Vec(v.Point) - foot).dot(axis) for v in f.Vertexes]
        if not ts:
            continue
        g = groups.setdefault(_line_key(axis, foot, 0.01), {"axis": axis, "foot": foot, "r": 0.0, "lo": min(ts), "hi": max(ts), "angles": [], "faces": 0})
        g["r"] = max(g["r"], rmax)
        g["lo"], g["hi"] = min(g["lo"], min(ts)), max(g["hi"], max(ts))
        # 각도 범위는 면마다 더하지 않고 **합집합**으로 잰다: 같은 축선에 반원 채널이 여러 토막 있으면
        # 합은 360°를 넘지만 덮는 각도는 180°뿐이다 [라이브 1.1.3: end cap의 Ø9 케이블 홈이 원기둥으로 메워져 혹이 됨]
        e1, e2 = _perp_frame(axis)
        try:
            for e in f.OuterWire.Edges:
                for p in e.discretize(Number=36):
                    q = Vec(p) - foot
                    x, y = q.dot(e1), q.dot(e2)
                    if math.hypot(x, y) > 1e-9:
                        g["angles"].append(math.atan2(y, x) % TWO_PI)
        except Exception:
            pass
        g["faces"] += 1
    solids = []
    for g in groups.values():
        angs = sorted(g["angles"])
        if len(angs) < 2:
            continue
        gaps = [angs[i + 1] - angs[i] for i in range(len(angs) - 1)] + [angs[0] + TWO_PI - angs[-1]]
        span = math.degrees(TWO_PI - max(gaps)) + 10.0  # 표본 간격 보정
        if span < 350.0:
            continue
        # 축 방향은 정확히 면의 범위까지만: 여유를 주면 부품 바깥으로 튀어나온 원기둥이 단면에 혹으로 남는다
        # [라이브 1.1.3: 2B2에서 0.05 여유 → 관통 구멍마다 9 mm³ 혹]. 반지름 여유는 챔퍼·불리언 잔재를 덮는 용도.
        length = g["hi"] - g["lo"]
        if length <= 1e-9:
            continue
        base = g["foot"] + g["axis"] * g["lo"]
        try:
            solids.append(Part.makeCylinder(g["r"] + margin, length, base, g["axis"]))
        except Exception:
            pass
    return solids


def _orient(edges):
    """OrderedEdges를 진행 방향 (시작점, 끝점)으로. [api-notes 7.5]"""
    ends = [(Vec(e.Vertexes[0].Point), Vec(e.Vertexes[-1].Point)) for e in edges]
    n = len(ends)
    if n == 1:
        return [ends[0]]
    a0, a1 = ends[0]
    b0, b1 = ends[1]
    d_end = min((a1 - b0).Length, (a1 - b1).Length)
    d_start = min((a0 - b0).Length, (a0 - b1).Length)
    out = [(a0, a1) if d_end <= d_start else (a1, a0)]
    for k in range(1, n):
        p0, p1 = ends[k]
        prev = out[-1][1]
        out.append((p0, p1) if (p0 - prev).Length <= (p1 - prev).Length else (p1, p0))
    return out


def _arc_element(c2, r, s2, e2, m2):
    a0 = math.atan2(s2[1] - c2[1], s2[0] - c2[0])
    a1 = math.atan2(e2[1] - c2[1], e2[0] - c2[0])
    am = math.atan2(m2[1] - c2[1], m2[0] - c2[0])
    sweep_ccw = (a1 - a0) % TWO_PI
    mid_ccw = (am - a0) % TWO_PI
    ccw = mid_ccw <= sweep_ccw
    sweep = sweep_ccw if ccw else TWO_PI - sweep_ccw
    return {
        "type": "arc", "center": _r2(*c2), "radius": round(r, 6),
        "start": _r2(*s2), "end": _r2(*e2), "mid": _r2(*m2),
        "ccw": bool(ccw), "angle_deg": round(math.degrees(sweep), 4),
    }


def _edge_element(edge, p0, p1, frame, tol, samples):
    """엣지 하나 → 2D 요소. frame=(origin, e1, e2). p0→p1이 진행 방향."""
    origin, e1, e2 = frame

    def to2d(p):
        q = Vec(p) - origin
        return q.dot(e1), q.dot(e2)

    c = edge.Curve
    ctype = type(c).__name__
    closed = bool(edge.Closed) or len(edge.Vertexes) < 2 or (p0 - p1).Length < 1e-9
    if ctype == "Line":
        return {"type": "line", "start": _r2(*to2d(p0)), "end": _r2(*to2d(p1))}
    try:
        mid = edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2.0)
    except Exception:
        mid = None
    if ctype == "Circle":
        c2 = to2d(c.Center)
        r = float(c.Radius)
        if closed:
            return {"type": "circle", "center": _r2(*c2), "radius": round(r, 6)}
        return _arc_element(c2, r, to2d(p0), to2d(p1), to2d(mid))
    # BSpline 등: 표본으로 직선 → 원 순서로 맞춘다 [라이브 1.1.3: BSpline 솔리드의 slice는 직선도 BSplineCurve]
    try:
        pts = [to2d(p) for p in edge.discretize(Number=max(8, int(samples)))]
    except Exception:
        pts = []
    if len(pts) >= 3:
        (x0, y0), (x1, y1) = to2d(p0), to2d(p1)
        length = math.hypot(x1 - x0, y1 - y0)
        if length > 1e-12:
            dev = max(abs((x - x0) * (y1 - y0) - (y - y0) * (x1 - x0)) / length for x, y in pts)
            if dev <= tol:
                return {"type": "line", "start": _r2(x0, y0), "end": _r2(x1, y1), "was": ctype}
        fit = _circle_fit_2d(pts)
        if fit is not None and fit[3] <= tol:
            cx, cy, r, _ = fit
            if closed:
                return {"type": "circle", "center": _r2(cx, cy), "radius": round(r, 6), "was": ctype}
            el = _arc_element((cx, cy), r, to2d(p0), to2d(p1), pts[len(pts) // 2])
            el["was"] = ctype
            return el
    return {
        "type": "bspline", "curve": ctype, "start": _r2(*to2d(p0)), "end": _r2(*to2d(p1)),
        "points": [_r2(x, y, 4) for x, y in pts[:: max(1, len(pts) // 12)]][:12], "unsupported": True,
    }


def _wire_elements(wire, frame, tol, samples):
    edges = list(wire.OrderedEdges)
    if not edges:
        return [], 0.0
    ends = _orient(edges)
    els = [_edge_element(e, p0, p1, frame, tol, samples) for e, (p0, p1) in zip(edges, ends)]
    # 다시 그린 호의 끝점이 원래 정점에서 얼마나 벗어나는가 (Sketcher 허용치 1e-7 대비)
    dev = 0.0
    for el in els:
        if el["type"] == "arc":
            cx, cy = el["center"]
            for key in ("start", "end"):
                x, y = el[key]
                dev = max(dev, abs(math.hypot(x - cx, y - cy) - el["radius"]))
    return els, dev


def _local_box(axis, e1, e2, position, lo, hi, thickness=1.0):
    """단면 평면 둘레의 얇은 상자(로컬 2D 범위 lo~hi). 임의 축에서도 쓰려고 폴리곤→돌출로 만든다."""
    base = axis * (float(position) - thickness)
    corners = [
        base + e1 * lo[0] + e2 * lo[1], base + e1 * hi[0] + e2 * lo[1],
        base + e1 * hi[0] + e2 * hi[1], base + e1 * lo[0] + e2 * hi[1],
    ]
    return Part.Face(Part.makePolygon(corners + [corners[0]])).extrude(axis * (2.0 * thickness))


def _section(shape, axis, position, fill_holes, max_fill_radius, tol, samples, exclude=None, clip=None):
    """(frame, wires, filled_count, warnings). 실패는 예외.

    exclude: [{"center": [x, y], "radius": r}] — 단면 평면 둘레에서 원기둥을 3D로 빼고 자른다(귀 영역 등).
    clip: {"min": [x|None, y|None], "max": [x|None, y|None]} — 로컬 2D 범위 밖을 잘라낸다.
    """
    warnings = []
    src = shape
    filled = 0
    if fill_holes:
        solids = _hole_fill_solids(shape, max_fill_radius)
        if solids:
            try:
                src = shape.fuse(solids).removeSplitter()
                filled = len(solids)
            except Exception as e:
                warnings.append(f"구멍 메우기 실패({e}) — 메우지 않은 형상으로 단면을 뜹니다.")
                src = shape
    e1, e2 = _perp_frame(axis)
    origin = axis * float(position)
    frame = (origin, e1, e2)
    if exclude:
        cyls = []
        for c in exclude:
            cx, cy = c["center"]
            base = e1 * float(cx) + e2 * float(cy) + axis * (float(position) - 1.0)
            cyls.append(Part.makeCylinder(float(c["radius"]), 2.0, base, axis))
        src = src.cut(cyls)
    if clip:
        # common()은 상자 면이 부품 면과 겹치면 빈 결과를 준다 [라이브 1.1.3] → 범위 밖을 상자로 cut한다
        bb = src.BoundBox
        big = bb.DiagonalLength + 10.0
        lo = clip.get("min") or [None, None]
        hi = clip.get("max") or [None, None]
        cutters = []
        if lo[0] is not None:
            cutters.append(_local_box(axis, e1, e2, position, [float(lo[0]) - big, -big], [float(lo[0]), big]))
        if hi[0] is not None:
            cutters.append(_local_box(axis, e1, e2, position, [float(hi[0]), -big], [float(hi[0]) + big, big]))
        if lo[1] is not None:
            cutters.append(_local_box(axis, e1, e2, position, [-big, float(lo[1]) - big], [big, float(lo[1])]))
        if hi[1] is not None:
            cutters.append(_local_box(axis, e1, e2, position, [-big, float(hi[1])], [big, float(hi[1]) + big]))
        if cutters:
            src = src.cut(cutters)
    wires = src.slice(axis, float(position))
    out = []
    for w in wires:
        els, dev = _wire_elements(w, frame, tol, samples)
        area = None
        try:
            area = round(Part.Face(w).Area, 4) if w.isClosed() else None
        except Exception:
            pass
        xs = [v for el in els for v in ([el.get("start"), el.get("end")] if el["type"] != "circle" else
                                        [[el["center"][0] - el["radius"], el["center"][1] - el["radius"]],
                                         [el["center"][0] + el["radius"], el["center"][1] + el["radius"]]]) if v]
        bb = [[min(p[0] for p in xs), min(p[1] for p in xs)], [max(p[0] for p in xs), max(p[1] for p in xs)]] if xs else None
        out.append({
            "closed": bool(w.isClosed()), "area": area, "bbox_2d": [[round(v, 4) for v in p] for p in bb] if bb else None,
            "elements_total": len(els), "elements": els,
            "unsupported": sum(1 for el in els if el.get("unsupported")),
            "max_endpoint_deviation": round(dev, 9),
        })
    out.sort(key=lambda w: -(w["area"] or 0.0))
    for k, w in enumerate(out):
        w["outer"] = k == 0
    return frame, out, filled, warnings


def _levels_and_vertices(shape, axis, samples=5):
    levels = {}
    for i, f in enumerate(shape.Faces):
        rec = _identify(f, samples, 1e-3)
        if rec.get("identity") != "plane" or not rec.get("normal"):
            continue
        nrm = Vec(*rec["normal"])
        if abs(abs(nrm.dot(axis)) - 1.0) > 1e-4:
            continue
        pos = round(rec["position"] * (1.0 if nrm.dot(axis) > 0 else -1.0), 3) + 0.0
        lv = levels.setdefault(pos, {"position": pos, "area": 0.0, "faces": []})
        lv["area"] = round(lv["area"] + f.Area, 4)
        lv["faces"].append(i)
    verts = {}
    for v in shape.Vertexes:
        t = round(Vec(v.Point).dot(axis), 3)
        verts[t] = verts.get(t, 0) + 1
    return (sorted(levels.values(), key=lambda x: x["position"]),
            [{"position": k, "vertices": n} for k, n in sorted(verts.items())])


def section_profile(name=None, doc=None, axis="Z", position=None, fill_holes=True, max_fill_radius=10.0,
                    tolerance=1e-5, samples=24, max_elements=300):
    """축 방향 위치의 단면 윤곽을 스케치용 선분·호·원 목록으로. position=None이면 후보 높이만."""
    t0 = time.time()
    d, err = util.get_doc(doc)
    if err:
        return util.error(err)
    obj, shape, err = _shape_or_error(d, name)
    if err:
        return util.error(err)
    ax, err = _parse_axis(axis)
    if err:
        return util.error(err)
    warnings = []
    letter = _axis_letter(ax)
    data = {"document": d.Name, "object": obj.Name, "label": util.label(obj), "axis": _r3(ax, 6), "axis_letter": letter}

    if position is None:
        levels, verts = _levels_and_vertices(shape, ax)
        data.update({"position": None, "levels": levels[:50], "vertex_positions": verts[:100]})
        data["hint"] = "levels 값 사이(띠의 중간 높이)를 position으로 다시 부르면 그 높이의 윤곽을 준다."
        if len(verts) > 100:
            warnings.append(f"vertex_positions는 100/{len(verts)}개까지입니다.")
        return util.envelope(data, warnings=warnings, truncated=len(verts) > 100, t0=t0)

    try:
        frame, wires, filled, w2 = _section(shape, ax, float(position), bool(fill_holes), float(max_fill_radius),
                                            max(float(tolerance), 1e-9), int(samples))
    except Exception as e:
        return util.error(f"단면 추출 실패: {e}", e)
    warnings.extend(w2)
    origin, e1, e2 = frame
    data.update({
        "position": float(position), "frame": {"origin": _r3(origin, 6), "x_dir": _r3(e1, 6), "y_dir": _r3(e2, 6)},
        "sketch_plane": None, "wires": wires, "filled_holes": filled,
        "elements_total": sum(w["elements_total"] for w in wires),
    })
    if letter:
        sign = 1.0 if ax.dot(_CANON[letter]) > 0 else -1.0
        plane = {"Z": "XY", "Y": "XZ", "X": "YZ"}[letter]
        role, lx, ly, off_sign = _PLANES[plane]
        data["sketch_plane"] = {
            "plane": plane, "body_plane": role, "local_x": lx, "local_y": ly,
            "attachment_offset_z": round(float(position) * sign * off_sign, 6),
            "build_features": {"plane": plane, "position": round(float(position) * sign, 6)},
        }
    else:
        warnings.append("축이 X/Y/Z가 아니라 sketch_plane을 줄 수 없습니다. frame으로 직접 부착하세요.")
    if not wires:
        warnings.append("이 위치에서 단면이 비어 있습니다. 형상의 bbox 안인지 확인하세요.")
    unsupported = sum(w["unsupported"] for w in wires)
    if unsupported:
        warnings.append(f"직선·원으로 맞추지 못한 요소 {unsupported}개(type: bspline). 진짜 자유곡선이거나 tolerance가 너무 작습니다.")
    total = data["elements_total"]
    truncated = False
    if total > max_elements:
        budget = int(max_elements)
        for w in wires:
            keep = max(0, min(len(w["elements"]), budget))
            w["elements"] = w["elements"][:keep]
            budget -= keep
        warnings.append(f"요소가 {total}개라 {max_elements}개까지만 담았습니다. build_features의 profile.section을 쓰면 잘리지 않습니다.")
        truncated = True
    for w in wires:
        if util.fit_cap(w, "elements", warnings):
            truncated = True
    return util.envelope(data, warnings=warnings, truncated=truncated, t0=t0)


# --- 7.18 build_features ---------------------------------------------------------


class _BuildError(Exception):
    pass


def _num_or_expr(obj, prop, value, sign=1.0):
    """숫자면 대입, 문자열이면 수식. sign=-1이면 부호를 뒤집는다(XZ 평면 오프셋)."""
    if isinstance(value, str):
        expr = value.strip()
        obj.setExpression(prop, f"-({expr})" if sign < 0 else expr)
    else:
        setattr(obj, prop, float(value) * sign)


def _origin_plane(body, role):
    for o in body.Origin.OriginFeatures:
        if o.Role == role:
            return o
    raise _BuildError(f"Body 원점에 {role}이 없습니다.")


def _make_sketch(d, body, name, plane, position):
    if plane not in _PLANES:
        raise _BuildError(f"plane은 XY/XZ/YZ 중 하나여야 합니다: {plane!r}")
    role, _, _, off_sign = _PLANES[plane]
    sk = d.addObject("Sketcher::SketchObject", name)
    body.addObject(sk)
    sk.AttachmentSupport = [(_origin_plane(body, role), "")]
    sk.MapMode = "FlatFace"
    if position is not None:
        if isinstance(position, str):
            sk.setExpression(".AttachmentOffset.Base.z", f"-({position.strip()})" if off_sign < 0 else position.strip())
        else:
            sk.AttachmentOffset = FreeCAD.Placement(Vec(0, 0, float(position) * off_sign), FreeCAD.Rotation())
    return sk


def _norm_plane(plane):
    p = str(plane or "XY").upper().replace("_PLANE", "")
    return p


def _profile_wires(d, plane, profile, warnings):
    """profile 사양 → 와이어별 요소 목록 [[el, ...], ...]. section은 여기서 뜬다."""
    import Sketcher  # noqa: F401  (존재 확인)

    if not isinstance(profile, dict):
        raise _BuildError("profile은 dict여야 합니다 (section / elements / wires / circles / polygon / rect).")
    if "section" in profile:
        spec = profile["section"]
        src_doc, err = util.get_doc(spec.get("doc")) if spec.get("doc") else (d, None)
        if err:
            raise _BuildError(err)
        obj, shape, err = _shape_or_error(src_doc, spec.get("of") or spec.get("name"))
        if err:
            raise _BuildError(err)
        axis = _CANON[_PLANE_AXIS[plane]]
        if "position" not in spec:
            raise _BuildError("profile.section에 position(전역 좌표)이 필요합니다.")
        frame, wires, filled, w2 = _section(shape, axis, float(spec["position"]), bool(spec.get("fill_holes", True)),
                                            float(spec.get("max_fill_radius", 10.0)), float(spec.get("tolerance", 1e-5)),
                                            int(spec.get("samples", 24)), exclude=spec.get("exclude"), clip=spec.get("clip"))
        warnings.extend(w2)
        if not wires:
            raise _BuildError(f"{obj.Name}의 {_PLANE_AXIS[plane]}={spec['position']} 단면이 비어 있습니다.")
        if spec.get("outer_only", False):
            wires = wires[:1]
        bad = [w for w in wires if w["unsupported"]]
        if bad and not spec.get("approximate_bspline", False):
            raise _BuildError(f"단면에 직선·원으로 맞추지 못한 요소가 {sum(w['unsupported'] for w in bad)}개 있습니다. "
                              "section_profile로 확인하고 tolerance를 조정하거나, 작은 블렌드면 approximate_bspline: true로 "
                              "꺾은선 근사 후 fillet을 거세요.")
        if bad:
            warnings.append(f"자유곡선 요소 {sum(w['unsupported'] for w in bad)}개를 표본점 꺾은선으로 근사했습니다(approximate_bspline).")
        return [_approximate_bsplines(w["elements"]) for w in wires]
    if "elements" in profile:
        return [list(profile["elements"])]
    if "wires" in profile:
        return [list(w) for w in profile["wires"]]
    if "polygons" in profile:
        out = []
        for poly in profile["polygons"]:
            pts = [list(p) for p in poly]
            if len(pts) < 3:
                raise _BuildError("polygons의 각 폴리곤은 점 3개 이상이어야 합니다.")
            out.append([{"type": "line", "start": pts[i], "end": pts[(i + 1) % len(pts)]} for i in range(len(pts))])
        return out
    if "circles" in profile:
        out = []
        for c in profile["circles"]:
            r = c.get("radius")
            if r is None and c.get("diameter") is not None and not isinstance(c["diameter"], str):
                r = float(c["diameter"]) / 2.0
            if r is None:
                raise _BuildError("circle에는 radius 또는 숫자 diameter가 필요합니다 (expr는 별도).")
            out.append([{"type": "circle", "center": list(c["center"]), "radius": float(r),
                         "expr": c.get("expr"), "name": c.get("name")}])
        return out
    if "polygon" in profile:
        pts = [list(p) for p in profile["polygon"]]
        if len(pts) < 3:
            raise _BuildError("polygon은 점 3개 이상이어야 합니다.")
        return [[{"type": "line", "start": pts[i], "end": pts[(i + 1) % len(pts)]} for i in range(len(pts))]]
    if "rect" in profile:
        r = profile["rect"]
        cx, cy = r.get("center", [0.0, 0.0])
        w, h = float(r["width"]) / 2.0, float(r["height"]) / 2.0
        pts = [[cx - w, cy - h], [cx + w, cy - h], [cx + w, cy + h], [cx - w, cy + h]]
        return [[{"type": "line", "start": pts[i], "end": pts[(i + 1) % 4]} for i in range(4)]]
    raise _BuildError("profile에 section / elements / wires / circles / polygon / rect 중 하나가 필요합니다.")


def _approximate_bsplines(elements):
    """type bspline 요소를 표본점을 잇는 선분 목록으로 바꾼다 (작은 블렌드 근사용)."""
    out = []
    for el in elements:
        if el.get("type") != "bspline":
            out.append(el)
            continue
        pts = [list(el["start"])] + [list(p) for p in el.get("points", [])[1:-1]] + [list(el["end"])]
        # 표본점이 시작·끝과 겹치면 뺀다
        clean = [pts[0]]
        for p in pts[1:]:
            if math.hypot(p[0] - clean[-1][0], p[1] - clean[-1][1]) > 1e-6:
                clean.append(p)
        for a, b in zip(clean[:-1], clean[1:]):
            out.append({"type": "line", "start": a, "end": b, "was": "bspline"})
    return out


def _split_wide_arcs(elements, max_deg=150.0):
    """150°를 넘는 호를 중간점에서 둘로 나눈다.

    정확히 180°인 호는 양 끝점을 고정하면 반지름이 현으로 결정돼 Sketcher가 Radius를
    '중복 제약'으로 거부한다 [라이브 1.1.3: Part 25 바닥 단면의 R8.75 반원]. 넓은 호를 나누면 그 특이점을 피한다.
    """
    out = []
    for el in elements:
        if el.get("type") != "arc":
            out.append(el)
            continue
        cx, cy = el["center"]
        r = float(el["radius"])
        (sx, sy), (ex, ey) = el["start"], el["end"]
        a0 = math.atan2(sy - cy, sx - cx)
        a1 = math.atan2(ey - cy, ex - cx)
        ccw = bool(el.get("ccw", True))
        sweep = ((a1 - a0) if ccw else (a0 - a1)) % TWO_PI or TWO_PI
        if math.degrees(sweep) <= max_deg:
            out.append(el)
            continue
        n = int(math.ceil(math.degrees(sweep) / max_deg))
        pts = []
        for k in range(n + 1):
            a = a0 + (sweep * k / n) * (1.0 if ccw else -1.0)
            pts.append([cx + r * math.cos(a), cy + r * math.sin(a)])
        pts[0], pts[-1] = [sx, sy], [ex, ey]
        for k in range(n):
            out.append({"type": "arc", "center": [cx, cy], "radius": r, "start": pts[k], "end": pts[k + 1],
                        "ccw": ccw, "angle_deg": math.degrees(sweep) / n})
    return out


def _draw_wire(sk, elements):
    """요소 목록을 스케치에 옮기고 DoF 0으로 고정한다. [api-notes 7.5]

    선분·원은 Block. 호는 중심·반지름·각도로 다시 그리면 끝점이 원래 정점에서 ~1e-5 벗어나
    (Sketcher 허용치 1e-7) 이웃과 틈이 생기므로, 이음매마다 원래 정점 위치에 Block한 구성점을 두고
    호의 양 끝을 그 점에 Coincident + Radius 로 잡는다 → 호 5 − 1 − 2 − 2 = 0 DoF, 틈은 솔버가 닫는다.
    (틈 있는 이음매만 골라 한쪽을 풀어 주는 방식은 자유 요소가 이어질 때 DoF가 남았다 — 2B2 실측)
    """
    import Sketcher

    chain = []  # (gid, start_pos, end_pos, kind, start_xy, end_xy)
    named = []
    elements = _split_wide_arcs(elements)
    for el in elements:
        t = el.get("type")
        if t == "line":
            (x0, y0), (x1, y1) = el["start"], el["end"]
            gid = sk.addGeometry(Part.LineSegment(Vec(x0, y0, 0), Vec(x1, y1, 0)), False)
            chain.append((gid, 1, 2, "line", (x0, y0), (x1, y1)))
        elif t == "arc":
            cx, cy = el["center"]
            r = float(el["radius"])
            (sx, sy), (ex, ey) = el["start"], el["end"]
            a0 = math.atan2(sy - cy, sx - cx)
            a1 = math.atan2(ey - cy, ex - cx)
            circ = Part.Circle(Vec(cx, cy, 0), Vec(0, 0, 1), r)
            if el.get("ccw", True):
                sweep = (a1 - a0) % TWO_PI or TWO_PI
                gid = sk.addGeometry(Part.ArcOfCircle(circ, a0, a0 + sweep), False)
                chain.append((gid, 1, 2, "arc", (sx, sy), (ex, ey)))
            else:
                sweep = (a0 - a1) % TWO_PI or TWO_PI
                gid = sk.addGeometry(Part.ArcOfCircle(circ, a1, a1 + sweep), False)
                chain.append((gid, 2, 1, "arc", (sx, sy), (ex, ey)))
            sk.addConstraint(Sketcher.Constraint("Radius", gid, r))
        elif t == "circle":
            cx, cy = el["center"]
            r = float(el["radius"])
            gid = sk.addGeometry(Part.Circle(Vec(cx, cy, 0), Vec(0, 0, 1), r), False)
            if el.get("expr"):
                # 지름을 수식으로 걸 때: Block 대신 구성점으로 중심 고정 + 이름 붙인 Diameter
                pid = sk.addGeometry(Part.Point(Vec(cx, cy, 0)), True)
                sk.addConstraint(Sketcher.Constraint("Block", pid))
                sk.addConstraint(Sketcher.Constraint("Coincident", gid, 3, pid, 1))
                cid = sk.addConstraint(Sketcher.Constraint("Diameter", gid, 2.0 * r))
                cname = el.get("name") or f"d{gid}"
                sk.renameConstraint(cid, cname)
                sk.setExpression(f"Constraints.{cname}", str(el["expr"]).strip())
                named.append(cname)
            else:
                sk.addConstraint(Sketcher.Constraint("Block", gid))
        else:
            raise _BuildError(f"지원하지 않는 요소 type {t!r} (line/arc/circle만). bspline은 section tolerance를 키우거나 근사하세요.")

    n = len(chain)
    for gid, _, _, kind, _, _ in chain:
        if kind == "line":
            sk.addConstraint(Sketcher.Constraint("Block", gid))
    if n == 1 and chain[0][3] == "arc":
        sk.addConstraint(Sketcher.Constraint("Block", chain[0][0]))
        return named
    # 이음매 k: chain[k-1]의 끝 ↔ chain[k]의 시작. 호가 닿는 이음매마다 원래 정점에 구성점을 둔다.
    for k in range(n):
        a, b = chain[(k - 1) % n], chain[k]
        if a[3] != "arc" and b[3] != "arc":
            continue
        x, y = b[4]  # 진행 방향 기준 시작점 = 원래 정점
        pid = sk.addGeometry(Part.Point(Vec(x, y, 0)), True)
        sk.addConstraint(Sketcher.Constraint("Block", pid))
        if a[3] == "arc":
            sk.addConstraint(Sketcher.Constraint("Coincident", a[0], a[2], pid, 1))
        if b[3] == "arc":
            sk.addConstraint(Sketcher.Constraint("Coincident", b[0], b[1], pid, 1))
    return named


def _sketch_report(sk):
    try:
        status = sk.solve()
    except Exception as e:
        return {"solve_status": None, "solve_error": str(e)}
    rep = {"solve_status": int(status)}
    if status == 0:
        rep["fully_constrained"] = bool(getattr(sk, "FullyConstrained", False))
        try:
            rep["dof"] = int(sk.DoF)
        except Exception:
            pass
    return rep


def _select_edges(shape, spec):
    """fillet/chamfer 모서리 선택: ["Edge3", ...] 또는 필터 dict."""
    if isinstance(spec, (list, tuple)):
        return [str(s) for s in spec]
    if not isinstance(spec, dict):
        raise _BuildError("edges는 ['Edge3', ...] 또는 필터 dict여야 합니다.")
    curve = spec.get("curve")
    radius = spec.get("radius")
    rtol = float(spec.get("radius_tol", 0.01))
    center = spec.get("center")
    ctol = float(spec.get("center_tol", 0.01))
    length = spec.get("length")
    ltol = float(spec.get("length_tol", 0.01))
    bbox = spec.get("bbox")
    out = []
    for i, e in enumerate(shape.Edges, 1):
        c = e.Curve
        ctype = type(c).__name__
        if curve and ctype != curve:
            continue
        if radius is not None or spec.get("radius_min") is not None or spec.get("radius_max") is not None:
            r = getattr(c, "Radius", None)
            if r is None:
                continue
            if radius is not None and abs(float(r) - float(radius)) > rtol:
                continue
            if spec.get("radius_min") is not None and float(r) < float(spec["radius_min"]):
                continue
            if spec.get("radius_max") is not None and float(r) > float(spec["radius_max"]):
                continue
        if center is not None:
            cc = getattr(c, "Center", None)
            if cc is None:
                cc = e.CenterOfMass
            ok = True
            for want, have in zip(center, (cc.x, cc.y, cc.z)):
                if want is not None and abs(float(want) - have) > ctol:
                    ok = False
            if not ok:
                continue
        if length is not None and abs(e.Length - float(length)) > ltol:
            continue
        if spec.get("direction") is not None:
            # 직선 모서리의 방향이 주어진 벡터와 평행(부호 무관)해야 한다
            if ctype != "Line" or len(e.Vertexes) < 2:
                continue
            dv = Vec(e.Vertexes[-1].Point) - Vec(e.Vertexes[0].Point)
            want = Vec(*[float(v) for v in spec["direction"]])
            if dv.Length < 1e-9 or want.Length < 1e-9:
                continue
            if abs(dv.dot(want)) / (dv.Length * want.Length) < 1.0 - 1e-4:
                continue
        if bbox:
            bb = e.BoundBox
            lo, hi = bbox.get("min", [None] * 3), bbox.get("max", [None] * 3)
            vals = ((bb.XMin, bb.XMax), (bb.YMin, bb.YMax), (bb.ZMin, bb.ZMax))
            ok = True
            for k in range(3):
                if lo[k] is not None and vals[k][0] < float(lo[k]) - ctol:
                    ok = False
                if hi[k] is not None and vals[k][1] > float(hi[k]) + ctol:
                    ok = False
            if not ok:
                continue
        out.append(f"Edge{i}")
    return out


def _write_params(d, params):
    """Spreadsheet 'Params'에 별칭으로 기록. [라이브 1.1.3: getCellFromAlias / getUsedCells]"""
    sheet = d.getObject("Params")
    if sheet is None or sheet.TypeId != "Spreadsheet::Sheet":
        sheet = d.addObject("Spreadsheet::Sheet", "Params")
    used = set(sheet.getUsedCells() or [])
    rows = [int(c[1:]) for c in used if c.startswith("A") and c[1:].isdigit()]
    next_row = (max(rows) + 1) if rows else 1
    written = []
    for k, v in params.items():
        cell = None
        try:
            cell = sheet.getCellFromAlias(k)
        except Exception:
            cell = None
        if cell:
            sheet.set(cell, str(v))
        else:
            sheet.set(f"A{next_row}", str(k))
            sheet.set(f"B{next_row}", str(v))
            sheet.setAlias(f"B{next_row}", str(k))
            next_row += 1
        written.append(str(k))
    d.recompute()
    return written


def _add_feature(d, body, type_id, name, profile=None, **props):
    f = d.addObject(type_id, name)
    body.addObject(f)
    if profile is not None:
        f.Profile = profile
    for k, v in props.items():
        setattr(f, k, v)
    return f


def build_features(body=None, doc=None, features=None, params=None, create_body=True, stop_on_error=True):
    """스케치+피처 목록을 Body에 순서대로 쌓고 피처마다 재계산·검증한다."""
    t0 = time.time()
    d, err = util.get_doc(doc)
    if err:
        return util.error(err)
    if not isinstance(features, list) or not features:
        return util.error("features는 피처 dict의 목록이어야 합니다 (op: pad/pocket/groove/revolution/fillet/chamfer).")
    warnings = []
    body_obj = None
    if body:
        body_obj, _ = util.find_object(d, body)
    if body_obj is None:
        if not create_body:
            return util.error(f"Body '{body}'가 없습니다 (create_body=False).")
        body_obj = d.addObject("PartDesign::Body", body or "Body")
        body_obj.Label = body or "Body"
        d.recompute()
    elif body_obj.TypeId != "PartDesign::Body":
        return util.error(f"'{body_obj.Name}'은(는) PartDesign::Body가 아닙니다({body_obj.TypeId}).")

    written = []
    if params:
        try:
            written = _write_params(d, dict(params))
        except Exception as e:
            return util.error(f"Params 시트 기록 실패: {e}", e)

    created, invalid, stopped_at = [], [], None
    for idx, spec in enumerate(features):
        op = str(spec.get("op", "")).lower()
        name = spec.get("name") or f"{op.capitalize()}{idx + 1}"
        entry = {"op": op, "name": name}
        new_objs = []
        try:
            if op in ("pad", "pocket", "groove", "revolution"):
                plane = _norm_plane(spec.get("plane"))
                wires = _profile_wires(d, plane, spec.get("profile"), warnings)
                sk = _make_sketch(d, body_obj, "Sketch" + name, plane, spec.get("position"))
                new_objs.append(sk)
                if op in ("groove", "revolution"):
                    import Sketcher

                    ax = spec.get("axis") or {}
                    xs = [p[0] for w in wires for el in w for p in (el.get("start"), el.get("end")) if p]
                    ys = [p[1] for w in wires for el in w for p in (el.get("start"), el.get("end")) if p]
                    if "x" in ax:
                        x = float(ax["x"])
                        lo, hi = (min(ys) - 5.0, max(ys) + 5.0) if ys else (-10.0, 10.0)
                        line = Part.LineSegment(Vec(x, lo, 0), Vec(x, hi, 0))
                    elif "y" in ax:
                        y = float(ax["y"])
                        lo, hi = (min(xs) - 5.0, max(xs) + 5.0) if xs else (-10.0, 10.0)
                        line = Part.LineSegment(Vec(lo, y, 0), Vec(hi, y, 0))
                    else:
                        raise _BuildError("groove/revolution에는 axis {'x': v} 또는 {'y': v}(스케치 로컬 좌표)가 필요합니다.")
                    gid = sk.addGeometry(line, True)  # 첫 구성선 → Axis0
                    sk.addConstraint(Sketcher.Constraint("Block", gid))
                named = []
                for w in wires:
                    named += _draw_wire(sk, w)
                entry["sketch"] = sk.Name
                entry["elements"] = sum(len(w) for w in wires)
                entry["wires"] = len(wires)
                if named:
                    entry["named_constraints"] = named
                d.recompute()
                entry.update(_sketch_report(sk))
                sk.Visibility = False

                if op in ("pad", "pocket"):
                    type_id = "PartDesign::Pad" if op == "pad" else "PartDesign::Pocket"
                    f = _add_feature(d, body_obj, type_id, name, sk)
                    new_objs.append(f)
                    if spec.get("type"):
                        f.Type = str(spec["type"])
                    elif op == "pocket" and spec.get("through"):
                        f.Type = "ThroughAll"
                    elif spec.get("length") is not None:
                        _num_or_expr(f, "Length", spec["length"])
                    elif op == "pad":
                        raise _BuildError("pad에는 length(숫자/수식) 또는 type이 필요합니다.")
                    else:
                        raise _BuildError("pocket에는 length / through: true / type 중 하나가 필요합니다.")
                    if spec.get("reversed"):
                        f.Reversed = True
                    if spec.get("midplane"):
                        f.Midplane = True
                else:
                    type_id = "PartDesign::Groove" if op == "groove" else "PartDesign::Revolution"
                    f = _add_feature(d, body_obj, type_id, name, sk)
                    new_objs.append(f)
                    _num_or_expr(f, "Angle", spec.get("angle", 360.0))
                    f.ReferenceAxis = (sk, ["Axis0"])
                    if spec.get("reversed"):
                        f.Reversed = True
            elif op in ("fillet", "chamfer"):
                tip = body_obj.Tip
                if tip is None or tip.Shape.isNull():
                    raise _BuildError("fillet/chamfer 앞에 형상을 만드는 피처가 있어야 합니다.")
                edges = _select_edges(tip.Shape, spec.get("edges"))
                if not edges:
                    raise _BuildError("edges 필터에 맞는 모서리가 없습니다. tip 형상의 모서리를 analyze_shape로 확인하세요.")
                type_id = "PartDesign::Fillet" if op == "fillet" else "PartDesign::Chamfer"
                f = d.addObject(type_id, name)
                new_objs.append(f)
                body_obj.addObject(f)
                f.Base = (tip, edges)
                _num_or_expr(f, "Radius" if op == "fillet" else "Size", spec.get("size", 1.0))
                entry["edges"] = edges
            else:
                raise _BuildError(f"알 수 없는 op {op!r}. pad/pocket/groove/revolution/fillet/chamfer 중 하나.")

            d.recompute()
            bad = [(o.Name, util.status_string(o)) for o in new_objs if "Invalid" in o.State]
            entry["status"] = bad[0][1] if bad else "Valid"
            entry["volume_after"] = round(body_obj.Shape.Volume, 4) if not body_obj.Shape.isNull() else None
            created.append(entry)
            if bad:
                invalid.extend({"name": n, "status": s} for n, s in bad)
                if stop_on_error:
                    stopped_at = name
                    warnings.append(f"'{name}'이 실패해 멈췄습니다: {bad[0][1]}. 실패한 객체는 문서에 남아 있으니 고치거나 지우세요.")
                    break
        except _BuildError as e:
            entry["status"] = f"입력 오류: {e}"
            created.append(entry)
            invalid.append({"name": name, "status": str(e)})
            for o in new_objs:  # 입력 오류로 만든 조각은 치운다
                try:
                    d.removeObject(o.Name)
                except Exception:
                    pass
            if stop_on_error:
                stopped_at = name
                break
        except Exception as e:
            entry["status"] = f"예외: {e}"
            created.append(entry)
            invalid.append({"name": name, "status": str(e)})
            if stop_on_error:
                stopped_at = name
                warnings.append(f"'{name}'에서 예외: {e}")
                break

    d.recompute()
    shape = body_obj.Shape
    data = {
        "document": d.Name, "body": body_obj.Name, "params_written": written, "created": created,
        "volume": round(shape.Volume, 4) if not shape.isNull() else None,
        "valid": bool(not shape.isNull() and shape.isValid()),
        "faces": len(shape.Faces) if not shape.isNull() else 0,
        "invalid": invalid, "stopped_at": stopped_at,
    }
    return util.envelope(data, warnings=warnings, t0=t0)


# --- 7.19 compare_shapes ---------------------------------------------------------


def _pieces(diff, min_vol, max_pieces):
    out = []
    for s in diff.Solids:
        try:
            bb = s.BoundBox
            if min(bb.XLength, bb.YLength, bb.ZLength) < 1e-6 or s.Volume < min_vol:
                continue
            out.append({"volume": round(s.Volume, 6), "bbox": util.serialize(bb), "center": _r3(s.CenterOfMass, 3)})
        except Exception:
            continue
    out.sort(key=lambda p: -p["volume"])
    return out[:max_pieces], round(sum(p["volume"] for p in out), 6), len(out)


def compare_shapes(a=None, b=None, doc=None, doc_b=None, fuzzy=1e-4, min_piece_volume=1e-3, max_pieces=10):
    """두 형상의 부피·면적·bbox 차와 퍼지 차집합 조각(어디가 다른가)."""
    t0 = time.time()
    da, err = util.get_doc(doc)
    if err:
        return util.error(err)
    db, err = util.get_doc(doc_b) if doc_b else (da, None)
    if err:
        return util.error(err)
    oa, sa, err = _shape_or_error(da, a)
    if err:
        return util.error(err)
    ob, sb, err = _shape_or_error(db, b)
    if err:
        return util.error(err)
    warnings = []

    def info(o, s, d):
        return {"object": o.Name, "label": util.label(o), "document": d.Name, "volume": round(s.Volume, 4),
                "area": round(s.Area, 4), "faces": len(s.Faces), "solids": len(s.Solids), "bbox": util.serialize(s.BoundBox)}

    ia, ib = info(oa, sa, da), info(ob, sb, db)
    ba, bb = sa.BoundBox, sb.BoundBox
    bbox_diff = max(abs(ba.XMin - bb.XMin), abs(ba.XMax - bb.XMax), abs(ba.YMin - bb.YMin),
                    abs(ba.YMax - bb.YMax), abs(ba.ZMin - bb.ZMin), abs(ba.ZMax - bb.ZMax))
    center_gap = (ba.Center - bb.Center).Length
    if center_gap > 0.01:
        warnings.append(f"bbox 중심이 {round(center_gap, 3)} mm 어긋나 있습니다. Body.Placement(원본 Placement 복사)를 확인하세요.")

    fz0 = max(float(fuzzy), 0.0)
    vol_a = sa.Volume or 1e-12
    boolean_failed = False
    method = "cut"
    fz = fz0
    try:
        # 면이 겹치는 쌍에서 퍼지 차집합이 형상 전체를 돌려주기도 한다 [api-notes 7.5·13]
        # → 정확한 불리언, 10배·100배 fuzzy 순으로 다시 시도한다
        for fz in (fz0, 0.0, (fz0 or 1e-5) * 10.0, (fz0 or 1e-5) * 100.0):
            missing, missing_total, n_missing = _pieces(sa.cut(sb, fz) if fz else sa.cut(sb), float(min_piece_volume), int(max_pieces))
            extra, extra_total, n_extra = _pieces(sb.cut(sa, fz) if fz else sb.cut(sa), float(min_piece_volume), int(max_pieces))
            biggest = max([p["volume"] for p in missing + extra] or [0.0])
            # 일관성: (missing − extra)는 (Va − Vb)와 같아야 한다. 겹친 면에서 불리언이 큰 덩어리를 돌려주면 어긋난다
            # [라이브 1.1.3: handle clamp — 부피 차 15 mm³인데 missing 1997]
            consistent = abs((missing_total - extra_total) - (sa.Volume - sb.Volume)) <= 0.01 * vol_a + 1.0
            if biggest < 0.5 * vol_a and consistent:
                break
            warnings.append(f"차집합(fuzzy {fz:g})이 형상 전체 또는 일관되지 않은 조각을 돌려줬습니다.")
        else:
            boolean_failed = True
    except Exception as e:
        return util.error(f"차집합 실패: {e}. fuzzy를 키워 보세요(예: 1e-3).", e)
    if boolean_failed:
        # 조각은 못 얻어도 교집합으로 총량은 잰다: missing = Va − Vc, extra = Vb − Vc
        missing, extra, n_missing, n_extra = [], [], 0, 0
        missing_total = extra_total = 0.0
        try:
            vc = (sa.common(sb, fz0) if fz0 else sa.common(sb)).Volume
            # 교집합도 겹친 면에서 조각만 돌려줄 수 있다 → 작은 쪽 부피의 절반은 넘어야 믿는다
            if 0.5 * min(sa.Volume, sb.Volume) < vc <= min(sa.Volume, sb.Volume) + 1e-3:
                missing_total = round(max(sa.Volume - vc, 0.0), 6)
                extra_total = round(max(sb.Volume - vc, 0.0), 6)
                method = "common"
                warnings.append("퍼지 차집합이 실패해(면 겹침) 교집합으로 총량만 계산했습니다. 조각(bbox)은 없습니다.")
            else:
                method = "volume_only"
        except Exception:
            method = "volume_only"
        if method == "volume_only":
            warnings.append("차집합·교집합이 모두 실패했습니다(면 겹침). volume_diff·area_diff로만 판단하세요.")
    # 퍼지 불리언은 얇은 차이를 삼킬 수 있으므로 부피 차 자체도 판정에 넣는다
    diff_pct = max(missing_total + extra_total, abs(sb.Volume - sa.Volume)) / vol_a * 100.0
    if diff_pct < 0.001:
        verdict = "identical"
    elif diff_pct < 0.1:
        verdict = "match"
    else:
        verdict = "different"
    data = {
        "a": ia, "b": ib,
        "volume_diff": round(sb.Volume - sa.Volume, 6), "volume_diff_pct": round((sb.Volume - sa.Volume) / vol_a * 100.0, 6),
        "area_diff": round(sb.Area - sa.Area, 4), "faces_diff": len(sb.Faces) - len(sa.Faces),
        "bbox_max_diff": round(bbox_diff, 6),
        "missing_in_b": missing, "extra_in_b": extra,
        "missing_total": missing_total, "extra_total": extra_total,
        "missing_pieces": n_missing, "extra_pieces": n_extra,
        "diff_pct": round(diff_pct, 6), "verdict": verdict if method != "volume_only" else "unknown", "fuzzy": fz,
        "boolean_failed": boolean_failed, "method": method,
    }
    if n_missing > len(missing) or n_extra > len(extra):
        warnings.append(f"조각은 부피 큰 순으로 {max_pieces}개까지만 담았습니다.")
    return util.envelope(data, warnings=warnings, truncated=n_missing > len(missing) or n_extra > len(extra), t0=t0)


TOOLS = {
    "classify_faces": classify_faces,
    "section_profile": section_profile,
    "build_features": build_features,
    "compare_shapes": compare_shapes,
}
