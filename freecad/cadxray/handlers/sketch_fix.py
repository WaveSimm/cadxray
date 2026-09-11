"""suggest_sketch_fixes, apply_sketch_fixes — 제약 오류 수정 후보 (M10, 명세 7.29·7.30).

자동으로 고치지 않는다. 후보(추가/삭제)와 예상 효과(사본에 적용해 solve)를 주고, 사용자가 고른 id만 적용한다.
[라이브 1.1.3, 2026-09-11] detectMissingPointOnPointConstraints(tol) → MissingPointOnPointConstraints = (g1, p1, g2, p2, type);
detectMissingVerticalHorizontalConstraints(deg) → MissingVerticalHorizontalConstraints = (geo, pos, -2000, 0, 2=H|3=V);
detectMissingEqualityConstraints(tol) → MissingLineEqualityConstraints / MissingRadiusConstraints = (g1, 0, g2, 0);
getGeometryWithDependentParameters() → [(geo, pos)] 자유 요소.
"""

import hashlib
import math
import time

import FreeCAD
import Sketcher

from . import util
from .sketch_diag import _DIMENSIONAL, _POS_NAME, _SOLVE_STATUS, _ids

Vec = FreeCAD.Vector
_UNDEF = -2000
_SHORT = {"Part::GeomLineSegment": "Line", "Part::GeomCircle": "Circle", "Part::GeomArcOfCircle": "Arc", "Part::GeomPoint": "Point",
          "Part::GeomBSplineCurve": "BSpline", "Part::GeomEllipse": "Ellipse", "Part::GeomArcOfEllipse": "ArcOfEllipse"}


class _FixError(Exception):
    pass


def _sketch_or_error(d, name):
    obj, err = util.find_object(d, name)
    if err:
        return None, err
    if obj.TypeId != "Sketcher::SketchObject":
        return None, f"'{obj.Name}'은(는) 스케치가 아닙니다({obj.TypeId})."
    return obj, None


def _snapshot(sk):
    try:
        status = int(sk.solve())
    except Exception as e:  # noqa: BLE001
        return {"solve_status": None, "solve_text": f"solve 실패: {e}", "dof": None}
    snap = {"solve_status": status, "solve_text": _SOLVE_STATUS.get(status, str(status)),
            "dof": int(sk.DoF) if status == 0 else None,
            "fully_constrained": bool(sk.FullyConstrained) if status == 0 else None,
            "conflicting": [x["id"] for x in _ids(sk.ConflictingConstraints)],
            "redundant": [x["id"] for x in _ids(sk.RedundantConstraints)],
            "malformed": [x["id"] for x in _ids(sk.MalformedConstraints)]}
    try:
        snap["open_vertices"] = len(sk.OpenVertices)
    except Exception:  # noqa: BLE001
        snap["open_vertices"] = None
    return snap


def _fingerprint(sk):
    h = hashlib.sha1()
    for c in sk.Constraints:
        h.update(f"{c.Type}:{c.First}:{c.FirstPos}:{c.Second}:{c.SecondPos}:{round(float(c.Value), 6)}|".encode())
    return f"g{sk.GeometryCount}c{sk.ConstraintCount}:{h.hexdigest()[:10]}"


def _label(sk, geo, pos=0):
    if geo == -1:
        base = "H축"
    elif geo == -2:
        base = "V축"
    elif geo < 0:
        base = f"외부{-geo - 3}"
    else:
        try:
            base = _SHORT.get(sk.Geometry[geo].TypeId, "Geo") + str(geo)
        except Exception:  # noqa: BLE001
            base = f"Geo{geo}"
    if pos in (1, 2, 3):
        return base + "." + _POS_NAME[pos]
    return base


def _point(sk, geo, pos):
    if geo == -1 or geo == -2:
        return Vec(0, 0, 0)
    g = sk.Geometry[geo]
    if pos == 1:
        return Vec(g.StartPoint) if hasattr(g, "StartPoint") else None
    if pos == 2:
        return Vec(g.EndPoint) if hasattr(g, "EndPoint") else None
    if pos == 3:
        return Vec(g.Center) if hasattr(g, "Center") else None
    return None


def _make_constraint(c):
    """후보 dict → Sketcher.Constraint."""
    k = c["constraint"]
    t = k["type"]
    if t == "Coincident":
        return Sketcher.Constraint("Coincident", k["first"], k["first_pos"], k["second"], k["second_pos"])
    if t in ("Horizontal", "Vertical"):
        return Sketcher.Constraint(t, k["first"])
    if t == "Equal":
        return Sketcher.Constraint("Equal", k["first"], k["second"])
    if t in ("DistanceX", "DistanceY"):
        return Sketcher.Constraint(t, k["first"], k["first_pos"], k["second"], k["second_pos"], float(k["value"]))
    if t == "Radius":
        return Sketcher.Constraint("Radius", k["first"], float(k["value"]))
    raise _FixError(f"지원하지 않는 제약 종류 {t!r}")


def _apply_to(sk, cands):
    """후보 목록을 스케치에 적용 (삭제는 인덱스 내림차순 먼저)."""
    dels = sorted([c["constraint_index"] for c in cands if c["action"] == "delete"], reverse=True)
    for idx in dels:
        sk.delConstraint(idx)
    added = []
    for c in cands:
        if c["action"] == "add":
            added.append(sk.addConstraint(_make_constraint(c)))
    return added


def _candidates(sk, coincident_tolerance, angle_tolerance, equal_tolerance, max_gap, add_dimensions=True):
    """후보 목록(평가 전). 각 항목: kind, action, targets, constraint(추가) 또는 constraint_index/id(삭제), detail, confidence."""
    out = []
    ext = len(sk.ExternalGeometry) if hasattr(sk, "ExternalGeometry") else 0
    cons = list(sk.Constraints)
    hv_have = {c.First for c in cons if c.Type in ("Horizontal", "Vertical")}
    coinc_have = {(c.First, c.FirstPos, c.Second, c.SecondPos) for c in cons if c.Type == "Coincident"}
    coinc_have |= {(b, bp, a, ap) for a, ap, b, bp in coinc_have}

    # 1) 빠진 일치 (가까운 끝점)
    try:
        sk.detectMissingPointOnPointConstraints(float(coincident_tolerance))
        for t in sk.MissingPointOnPointConstraints:
            g1, p1, g2, p2 = int(t[0]), int(t[1]), int(t[2]), int(t[3])
            if (g1, p1, g2, p2) in coinc_have:
                continue
            a, b = _point(sk, g1, p1), _point(sk, g2, p2)
            dist = (a - b).Length if a and b else None
            out.append({"kind": "add_coincident", "action": "add", "targets": [_label(sk, g1, p1), _label(sk, g2, p2)],
                        "constraint": {"type": "Coincident", "first": g1, "first_pos": p1, "second": g2, "second_pos": p2},
                        "detail": f"끝점 거리 {round(dist, 4) if dist is not None else '?'} mm", "confidence": "high"})
    except Exception as e:  # noqa: BLE001
        out.append({"kind": "note", "detail": f"detectMissingPointOnPointConstraints 실패: {e}"})
    # 1b) 더 멀리 떨어진 열린 끝점 쌍 (허용값 밖 ~ max_gap)
    try:
        open_pts = [Vec(v) for v in sk.OpenVertices]
    except Exception:  # noqa: BLE001
        open_pts = []
    if open_pts:
        ends = []
        for i, g in enumerate(sk.Geometry):
            for pos in (1, 2):
                p = _point(sk, i, pos)
                if p is not None:
                    ends.append((i, pos, p))
        opens = []
        for v in open_pts:
            best = min(ends, key=lambda e: (e[2] - v).Length, default=None)
            if best and (best[2] - v).Length < 1e-6:
                opens.append(best)
        seen = {tuple(sorted(((c["constraint"]["first"], c["constraint"]["first_pos"]), (c["constraint"]["second"], c["constraint"]["second_pos"]))))
                for c in out if c.get("kind") == "add_coincident"}
        for k, (g1, p1, a) in enumerate(opens):
            best = None
            for g2, p2, b in opens[k + 1:]:
                if g2 == g1:
                    continue
                dd = (a - b).Length
                if dd <= float(max_gap) and (best is None or dd < best[0]):
                    best = (dd, g2, p2)
            if best and best[0] > float(coincident_tolerance):
                key = tuple(sorted(((g1, p1), (best[1], best[2]))))
                if key in seen:
                    continue
                seen.add(key)
                out.append({"kind": "add_coincident", "action": "add", "targets": [_label(sk, g1, p1), _label(sk, best[1], best[2])],
                            "constraint": {"type": "Coincident", "first": g1, "first_pos": p1, "second": best[1], "second_pos": best[2]},
                            "detail": f"열린 끝점, 거리 {round(best[0], 4)} mm (형상이 그만큼 움직인다)", "confidence": "medium" if best[0] <= 1.0 else "low"})

    # 2) 빠진 수평/수직
    try:
        sk.detectMissingVerticalHorizontalConstraints(float(angle_tolerance))
        for t in sk.MissingVerticalHorizontalConstraints:
            geo, typ = int(t[0]), int(t[4])
            if geo in hv_have or geo < 0:
                continue
            g = sk.Geometry[geo]
            if g.TypeId != "Part::GeomLineSegment":
                continue
            dx, dy = g.EndPoint.x - g.StartPoint.x, g.EndPoint.y - g.StartPoint.y
            ang = math.degrees(math.atan2(dy, dx))
            if typ == 2:
                dev = min(abs(ang), abs(abs(ang) - 180.0))
                name, kind = "Horizontal", "add_horizontal"
            else:
                dev = abs(abs(ang) - 90.0)
                name, kind = "Vertical", "add_vertical"
            out.append({"kind": kind, "action": "add", "targets": [_label(sk, geo)], "constraint": {"type": name, "first": geo},
                        "detail": f"기울기 {round(dev, 3)}°", "confidence": "high" if dev < 0.05 else "medium"})
    except Exception as e:  # noqa: BLE001
        out.append({"kind": "note", "detail": f"detectMissingVerticalHorizontalConstraints 실패: {e}"})

    # 3) 빠진 같음 (선 길이·반지름)
    try:
        sk.detectMissingEqualityConstraints(float(equal_tolerance))
        eq_have = {tuple(sorted((c.First, c.Second))) for c in cons if c.Type == "Equal"}
        for prop, what in (("MissingLineEqualityConstraints", "길이"), ("MissingRadiusConstraints", "반지름")):
            for t in getattr(sk, prop):
                g1, g2 = int(t[0]), int(t[2])
                if tuple(sorted((g1, g2))) in eq_have:
                    continue
                out.append({"kind": "add_equal", "action": "add", "targets": [_label(sk, g1), _label(sk, g2)], "constraint": {"type": "Equal", "first": g1, "second": g2},
                            "detail": f"{what} 같음", "confidence": "medium"})
    except Exception as e:  # noqa: BLE001
        out.append({"kind": "note", "detail": f"detectMissingEqualityConstraints 실패: {e}"})

    # 4) 삭제 후보: 중복 / 잘못된 / 충돌
    snap = _snapshot(sk)

    def con_desc(idx):
        c = cons[idx]
        s = f"#{idx + 1} {c.Type}"
        if c.Type in _DIMENSIONAL:
            s += f" = {round(float(c.Value), 4)}"
        s += " (" + _label(sk, c.First, c.FirstPos)
        if c.Second != _UNDEF:
            s += " ↔ " + _label(sk, c.Second, c.SecondPos)
        return s + ")"

    for cid in snap.get("redundant", []):
        out.append({"kind": "delete_constraint", "action": "delete", "constraint_index": cid - 1, "constraint_id": cid, "targets": [con_desc(cid - 1)],
                    "detail": "중복 제약 — 지워도 형상이 유지된다", "confidence": "high"})
    for cid in snap.get("malformed", []):
        out.append({"kind": "delete_constraint", "action": "delete", "constraint_index": cid - 1, "constraint_id": cid, "targets": [con_desc(cid - 1)],
                    "detail": "잘못된 제약(참조가 깨짐)", "confidence": "high"})
    conf = snap.get("conflicting", [])
    for cid in conf:
        others = [x for x in conf if x != cid]
        out.append({"kind": "delete_constraint", "action": "delete", "constraint_index": cid - 1, "constraint_id": cid, "targets": [con_desc(cid - 1)],
                    "detail": "충돌 제약 중 하나 — 남는 쪽 값이 설계값이면 이것을 지운다", "confidence": "medium", "_exclusive_group": "conflict", "_others": others})

    # 5) 남은 자유도 → 치수 후보 (설계 치수는 사용자만 안다 → low)
    if add_dimensions and snap.get("solve_status") == 0 and (snap.get("dof") or 0) > 0:
        try:
            free = sk.getGeometryWithDependentParameters()
        except Exception:  # noqa: BLE001
            free = []
        seen_pts = set()
        for geo, pos in free:
            geo, pos = int(geo), int(pos)
            if geo < 0:
                continue
            g = sk.Geometry[geo]
            if pos in (1, 2, 3):
                p = _point(sk, geo, pos)
                if p is None or (geo, pos) in seen_pts:
                    continue
                seen_pts.add((geo, pos))
                for typ, val, axis in (("DistanceX", p.x, "X"), ("DistanceY", p.y, "Y")):
                    out.append({"kind": "add_dimension", "action": "add", "targets": [_label(sk, geo, pos)],
                                "constraint": {"type": typ, "first": -1, "first_pos": 1, "second": geo, "second_pos": pos, "value": round(float(val), 6)},
                                "detail": f"원점에서 {axis} 거리 {round(float(val), 4)} (현재 값)", "confidence": "low"})
            elif pos == 0 and g.TypeId in ("Part::GeomCircle", "Part::GeomArcOfCircle"):
                out.append({"kind": "add_dimension", "action": "add", "targets": [_label(sk, geo)],
                            "constraint": {"type": "Radius", "first": geo, "value": round(float(g.Radius), 6)},
                            "detail": f"반지름 {round(float(g.Radius), 4)} (현재 값)", "confidence": "low"})
    return out, snap


def _finish(cands):
    """id·key·exclusive_with 부여."""
    for i, c in enumerate(cands):
        c["id"] = i + 1
        if c["action"] == "add":
            k = c["constraint"]
            c["key"] = f"{c['kind']}:{k.get('first')}.{k.get('first_pos', 0)}-{k.get('second', '')}.{k.get('second_pos', 0)}:{k['type']}"
        else:
            c["key"] = f"delete:{c['constraint_id']}"
    for c in cands:
        if c.get("_exclusive_group"):
            c["exclusive_with"] = [x["id"] for x in cands if x is not c and x.get("_exclusive_group") == c["_exclusive_group"]]
    for c in cands:
        c.pop("_exclusive_group", None)
        c.pop("_others", None)
    return cands


def _evaluate(d, sk, cands):
    """후보마다 사본에 적용해 solve 결과를 effect에 넣는다. 원본은 건드리지 않는다."""
    for c in cands:
        copy = None
        try:
            copy = d.copyObject(sk, False)
            _apply_to(copy, [c])
            copy.solve()
            copy.recompute()          # OpenVertices는 Shape 기준 → solve만으로는 안 바뀐다 [api-notes 4장]
            c["effect"] = _snapshot(copy)
        except Exception as e:  # noqa: BLE001
            c["effect"] = {"error": str(e)}
        finally:
            if copy is not None:
                try:
                    d.removeObject(copy.Name)
                except Exception:  # noqa: BLE001
                    pass


def _better(before, eff):
    if not eff or eff.get("solve_status") is None or "error" in eff:
        return False
    if eff["solve_status"] != 0:
        return False
    if before.get("solve_status") != 0:
        return True   # 실패 → 성공
    return (eff.get("dof") or 0) < (before.get("dof") or 0) or (eff.get("open_vertices") or 0) < (before.get("open_vertices") or 0)


def suggest_sketch_fixes(sketch=None, doc=None, coincident_tolerance=0.05, angle_tolerance=0.5, equal_tolerance=0.01, max_gap=5.0,
                         evaluate=True, max_suggestions=50):
    """스케치 문제마다 고칠 후보와 예상 효과. 자동으로 고치지 않는다. [확인됨: api-notes 4장 + 17장]"""
    t0 = time.time()
    d, err = util.get_doc(doc)
    if err:
        return util.error(err)
    sk, err = _sketch_or_error(d, sketch)
    if err:
        return util.error(err)
    warnings = []
    n_before = sk.ConstraintCount
    try:
        cands, before = _candidates(sk, coincident_tolerance, angle_tolerance, equal_tolerance, max_gap)
    except Exception as e:  # noqa: BLE001
        return util.error(f"후보 생성 실패: {e}", e)
    notes = [c["detail"] for c in cands if c.get("kind") == "note"]
    cands = [c for c in cands if c.get("kind") != "note"]
    warnings.extend(notes)
    truncated = False
    if len(cands) > int(max_suggestions):
        cands = cands[:int(max_suggestions)]
        truncated = True
        warnings.append(f"후보가 {max_suggestions}개까지만 담겼습니다.")
    _finish(cands)
    if evaluate:
        _evaluate(d, sk, cands)
        sk.solve()
    if sk.ConstraintCount != n_before:
        warnings.append("원본 스케치의 제약 수가 바뀌었습니다 — 버그입니다. 되돌리세요(Ctrl+Z).")
    recommended = [c["id"] for c in cands if c["confidence"] != "low" and not c.get("exclusive_with") and (not evaluate or _better(before, c.get("effect")))]
    for c in cands:
        if c["action"] == "add" and "constraint_index" in c:
            del c["constraint_index"]
    data = {"document": d.Name, "sketch": sk.Name, "label": util.label(sk), "before": before, "fingerprint": _fingerprint(sk),
            "suggestions": cands, "recommended": recommended,
            "hint": "번호를 골라 apply_sketch_fixes(ids=[...], fingerprint=...)로 적용한다. exclusive_with에 묶인 후보는 하나만 고른다."}
    if not cands:
        data["hint"] = "고칠 후보가 없습니다." + (" 스케치는 완전 구속입니다." if before.get("dof") == 0 else "")
    return util.envelope(data, warnings=warnings, truncated=truncated, t0=t0)


def apply_sketch_fixes(sketch=None, ids=None, doc=None, fingerprint=None, coincident_tolerance=0.05, angle_tolerance=0.5, equal_tolerance=0.01,
                       max_gap=5.0, recompute=True):
    """suggest_sketch_fixes의 후보 중 고른 id만 적용하고 결과를 확인한다. 나빠지면 되돌린다."""
    t0 = time.time()
    d, err = util.get_doc(doc)
    if err:
        return util.error(err)
    sk, err = _sketch_or_error(d, sketch)
    if err:
        return util.error(err)
    if not ids:
        return util.error("ids에 적용할 후보 번호 목록이 필요합니다 (suggest_sketch_fixes의 id).")
    fp = _fingerprint(sk)
    if fingerprint and fingerprint != fp:
        return util.error(f"스케치가 후보를 만든 뒤 바뀌었습니다(fingerprint {fingerprint} ≠ {fp}). suggest_sketch_fixes를 다시 부르세요.")
    try:
        cands, before = _candidates(sk, coincident_tolerance, angle_tolerance, equal_tolerance, max_gap)
    except Exception as e:  # noqa: BLE001
        return util.error(f"후보 생성 실패: {e}", e)
    cands = _finish([c for c in cands if c.get("kind") != "note"])
    by_id = {c["id"]: c for c in cands}
    chosen = []
    for i in ids:
        try:
            i = int(i)
        except Exception:
            return util.error(f"id가 정수가 아닙니다: {i!r}")
        if i not in by_id:
            return util.error(f"id {i}가 없습니다. 후보 id: 1..{len(cands)}")
        chosen.append(by_id[i])
    ids_set = {c["id"] for c in chosen}
    for c in chosen:
        clash = ids_set & set(c.get("exclusive_with", []))
        if clash:
            return util.error(f"id {c['id']}와 {sorted(clash)}는 같이 고를 수 없습니다(충돌 제약 중 하나만 삭제).")
    # 되돌리기용 백업 (제약을 값으로 저장)
    saved = [(c.Type, c.First, c.FirstPos, c.Second, c.SecondPos, c.Third, c.ThirdPos, float(c.Value), c.Name, c.Driving) for c in sk.Constraints]
    try:
        _apply_to(sk, chosen)
        sk.solve()
        sk.recompute()                # OpenVertices 갱신
        after = _snapshot(sk)
    except Exception as e:  # noqa: BLE001
        after = {"error": str(e)}
    worse = ("error" in after) or (after.get("solve_status") not in (0,) and before.get("solve_status") == 0) or \
            (after.get("conflicting") and not before.get("conflicting"))
    if worse:
        # 되돌리기: 제약 전부 지우고 저장본으로 복원
        try:
            sk.deleteAllConstraints()
            for t in saved:
                typ, f, fp_, s, sp, th, thp, val, name, driving = t
                if s == _UNDEF:
                    c = Sketcher.Constraint(typ, f, fp_, val) if typ in _DIMENSIONAL else (Sketcher.Constraint(typ, f, fp_) if fp_ else Sketcher.Constraint(typ, f))
                elif th == _UNDEF:
                    c = Sketcher.Constraint(typ, f, fp_, s, sp, val) if typ in _DIMENSIONAL else Sketcher.Constraint(typ, f, fp_, s, sp)
                else:
                    c = Sketcher.Constraint(typ, f, fp_, s, sp, th, thp, val) if typ in _DIMENSIONAL else Sketcher.Constraint(typ, f, fp_, s, sp, th, thp)
                idx = sk.addConstraint(c)
                if name:
                    sk.renameConstraint(idx, name)
                if not driving:
                    sk.setDriving(idx, False)
            sk.solve()
        except Exception as e:  # noqa: BLE001
            return util.error(f"적용 후 상태가 나빠져 되돌리려 했으나 실패했습니다: {e}. Ctrl+Z로 되돌리세요.", e)
        return util.error(f"적용하면 스케치가 나빠집니다({after}). 되돌렸습니다. 다른 후보를 고르세요.")
    rec = None
    if recompute:
        d.recompute()
        bad = [o.Name for o in d.Objects if "Invalid" in o.State]
        rec = {"invalid_objects": bad, "sketch_state": util.status_string(sk)}
    data = {"document": d.Name, "sketch": sk.Name, "applied": [{"id": c["id"], "kind": c["kind"], "targets": c["targets"]} for c in chosen],
            "before": before, "after": after, "recompute": rec, "fingerprint": _fingerprint(sk)}
    return util.envelope(data, t0=t0)


TOOLS = {"suggest_sketch_fixes": suggest_sketch_fixes, "apply_sketch_fixes": apply_sketch_fixes}
