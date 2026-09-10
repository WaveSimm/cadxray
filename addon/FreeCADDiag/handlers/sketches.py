"""스케치 진단 — get_sketch_diagnostics (명세 7.5).

절차는 api-notes 4장 그대로다: solve() → 결과 속성 읽기 →
detectMissingPointOnPointConstraints() → OpenVertices.
솔버 객체(Sketcher.Sketch)는 복제하지 않는다.
"""

import time

from . import util

_SKETCH_TYPE = "Sketcher::SketchObject"

# solve() 반환 코드 [확인됨: api-notes 4.2, 라이브 1.1.3]
_SOLVE_STATUS = {
    0: "성공",
    -1: "솔버 오류 (solver error)",
    -2: "중복 제약 (redundant constraints)",
    -3: "충돌 제약 (conflicting constraints)",
    -4: "과구속 (over-constrained)",
    -5: "잘못된 제약 (malformed constraints)",
}

# Value가 의미를 갖는 제약 타입. 나머지는 0.0이 들어 있어도 null로 낸다.
_DIMENSIONAL = {
    "Distance",
    "DistanceX",
    "DistanceY",
    "Angle",
    "Radius",
    "Diameter",
    "Weight",
    "SnellsLaw",
}

_POS_NAME = {0: "edge", 1: "start", 2: "end", 3: "mid"}

_UNDEFINED_GEO = -2000  # [확인됨: api-notes 4.4]


def _decode_geo(geo_id, external_count):
    """GeoId를 사람이 읽을 수 있게 푼다. 미정의면 None."""
    if geo_id == _UNDEFINED_GEO:
        return None
    if geo_id >= 0:
        return {"geo": geo_id}
    if geo_id == -1:
        return {"geo": -1, "axis": "H"}
    if geo_id == -2:
        return {"geo": -2, "axis": "V"}
    ext = -geo_id - 3  # -3 → ExternalGeometry[0]
    out = {"geo": geo_id, "external": ext}
    if not (0 <= ext < external_count):
        out["note"] = "ExternalGeometry 범위 밖"
    return out


def _geometry_entry(sk, i, geo):
    entry = {"i": i, "type": geo.TypeId}
    try:
        entry["construction"] = bool(sk.getConstruction(i))
    except Exception:
        pass

    t = geo.TypeId
    try:
        if t == "Part::GeomLineSegment":
            entry["start"] = util.round_vec(geo.StartPoint)
            entry["end"] = util.round_vec(geo.EndPoint)
        elif t == "Part::GeomCircle":
            entry["center"] = util.round_vec(geo.Center)
            entry["radius"] = round(float(geo.Radius), 4)
        elif t == "Part::GeomArcOfCircle":
            entry["center"] = util.round_vec(geo.Center)
            entry["radius"] = round(float(geo.Radius), 4)
            entry["start"] = util.round_vec(geo.StartPoint)
            entry["end"] = util.round_vec(geo.EndPoint)
        elif t == "Part::GeomPoint":
            entry["point"] = [round(float(geo.X), 4), round(float(geo.Y), 4), round(float(geo.Z), 4)]
        elif t in ("Part::GeomEllipse", "Part::GeomArcOfEllipse"):
            entry["center"] = util.round_vec(geo.Center)
            entry["major_radius"] = round(float(geo.MajorRadius), 4)
            entry["minor_radius"] = round(float(geo.MinorRadius), 4)
            if t == "Part::GeomArcOfEllipse":
                entry["start"] = util.round_vec(geo.StartPoint)
                entry["end"] = util.round_vec(geo.EndPoint)
        elif t == "Part::GeomBSplineCurve":
            entry["degree"] = int(geo.Degree)
            entry["poles"] = int(geo.NbPoles)
            entry["start"] = util.round_vec(geo.StartPoint)
            entry["end"] = util.round_vec(geo.EndPoint)
    except Exception as e:
        entry["error"] = f"좌표 읽기 실패: {e}"
    return entry


def _constraint_entry(i, con, external_count):
    entry = {
        "i": i,
        "id": i + 1,  # GUI 제약 패널 번호 (1-based) [확인됨: api-notes 4.3]
        "type": con.Type,
        "name": con.Name or "",
        "first": con.First,
        "first_pos": con.FirstPos,
        "first_pos_name": _POS_NAME.get(con.FirstPos, str(con.FirstPos)),
        "driving": bool(con.Driving),
        "active": bool(con.IsActive),
    }
    ref = _decode_geo(con.First, external_count)
    if ref and "geo" in ref and con.First < 0:
        entry["first_ref"] = ref
    if con.Second != _UNDEFINED_GEO:
        entry["second"] = con.Second
        entry["second_pos"] = con.SecondPos
        entry["second_pos_name"] = _POS_NAME.get(con.SecondPos, str(con.SecondPos))
        if con.Second < 0:
            entry["second_ref"] = _decode_geo(con.Second, external_count)
    else:
        entry["second"] = None
    if con.Third != _UNDEFINED_GEO:
        entry["third"] = con.Third
        entry["third_pos"] = con.ThirdPos
        if con.Third < 0:
            entry["third_ref"] = _decode_geo(con.Third, external_count)
    entry["value"] = round(float(con.Value), 6) if con.Type in _DIMENSIONAL else None
    return entry


def _ids(raw):
    """솔버가 주는 1-based 번호 → [{"id": 1-based, "index": 0-based}]."""
    out = []
    for n in raw or []:
        try:
            n = int(n)
        except Exception:
            continue
        out.append({"id": n, "index": n - 1})
    return out


def _attachment(sk):
    out = {"map_mode": str(getattr(sk, "MapMode", ""))}
    # 1.x는 AttachmentSupport. Support는 0.21 이하 이름이라 폴백으로만 둔다.
    # [확인됨: api-notes 10장, 라이브 1.1.3에 Support 없음]
    support = getattr(sk, "AttachmentSupport", None)
    if support is None:
        support = getattr(sk, "Support", None)
    items = []
    for link in support or []:
        try:
            obj, subs = link
            items.append({"object": obj.Name, "sub": [str(s) for s in subs if s]})
        except Exception:
            items.append({"raw": str(link)})
    out["support"] = items
    offset = getattr(sk, "AttachmentOffset", None)
    if offset is not None:
        try:
            out["offset"] = util.serialize(offset)
        except Exception:
            pass
    return out


def get_sketch_diagnostics(
    doc=None, sketch=None, include_geometry=True, include_constraints=True, max_items=200
):
    """스케치가 '왜 빨간지'를 한 번에 알려준다."""
    t0 = time.time()
    d, err = util.get_doc(doc)
    if err:
        return util.error(err)
    sk, err = util.find_object(d, sketch)
    if err:
        return util.error(err)
    try:
        is_sketch = sk.isDerivedFrom(_SKETCH_TYPE)
    except Exception:
        is_sketch = sk.TypeId == _SKETCH_TYPE
    if not is_sketch:
        return util.error(
            f"'{sk.Name}'은 스케치가 아닙니다({sk.TypeId}). inspect_object를 쓰세요."
        )

    warnings = []

    # ① solve()를 먼저. DoF·Conflicting… 은 모두 '마지막 solve' 값이다.
    try:
        status = int(sk.solve())
    except Exception as e:
        return util.error(f"solve() 실패: {e}", exc=e)

    conflicting = _ids(sk.ConflictingConstraints)
    redundant = _ids(sk.RedundantConstraints)
    partially_redundant = _ids(sk.PartiallyRedundantConstraints)
    malformed = _ids(sk.MalformedConstraints)

    dof = int(sk.DoF)
    fully_constrained = bool(sk.FullyConstrained)

    # ③ 누락된 점-점 제약은 detect를 부른 뒤에야 목록이 채워진다
    missing_pop = []
    try:
        sk.detectMissingPointOnPointConstraints()
        for m in sk.MissingPointOnPointConstraints:
            missing_pop.append(
                {
                    "first": m[0],
                    "first_pos": m[1],
                    "second": m[2],
                    "second_pos": m[3],
                    "type": str(m[4]) if len(m) > 4 else None,
                }
            )
    except Exception as e:
        warnings.append(f"누락 제약 검출 실패: {e}")

    # ④ OpenVertices — recompute된 Shape 기준, 스케치 로컬 좌표
    open_vertices = []
    try:
        open_vertices = [
            [round(float(v[0]), 4), round(float(v[1]), 4), round(float(v[2]), 4)]
            for v in sk.OpenVertices
        ]
    except Exception as e:
        warnings.append(f"OpenVertices 읽기 실패: {e}")

    geometry = list(sk.Geometry)
    constraints = list(sk.Constraints)
    external_count = len(sk.ExternalGeometry)
    construction_count = 0
    for i in range(len(geometry)):
        try:
            if sk.getConstruction(i):
                construction_count += 1
        except Exception:
            pass

    data = {
        "document": d.Name,
        "sketch": sk.Name,
        "label": sk.Label,
        "state": list(sk.State),
        "status": util.status_string(sk),
        "solve_status": status,
        "solve_status_text": _SOLVE_STATUS.get(status, f"알 수 없는 코드 {status}"),
        "dof": dof,
        "fully_constrained": fully_constrained,
        "conflicting": conflicting,
        "redundant": redundant,
        "partially_redundant": partially_redundant,
        "malformed": malformed,
        "open_vertices": open_vertices,
        "missing_point_on_point": len(missing_pop),
        "missing_point_on_point_details": missing_pop,
        "attachment": _attachment(sk),
        "placement": util.serialize(sk.Placement),
        "counts": {
            "geometry": len(geometry),
            "constraints": len(constraints),
            "external": external_count,
            "construction": construction_count,
        },
    }

    # 해석을 사람이 읽을 문장으로. 스케치가 빨간 이유를 여기서 한 줄로 준다.
    if status != 0:
        data["fully_constrained"] = None
        warnings.append(
            f"solve()가 {status}({_SOLVE_STATUS.get(status, '?')})로 실패했습니다. "
            "FullyConstrained는 solve 성공 시에만 갱신되므로 신뢰할 수 없어 null로 냈습니다. "
            "DoF도 마지막 성공 solve 값일 수 있습니다."
        )
    elif dof > 0:
        warnings.append(f"자유도가 {dof} 남았습니다(미완전 구속).")
    if open_vertices:
        warnings.append(
            f"열린 끝점이 {len(open_vertices)}개 있습니다(와이어가 닫히지 않음). "
            "이 스케치를 쓰는 Pad/Pocket은 실패합니다."
        )
    if missing_pop:
        warnings.append(f"거의 겹치지만 제약이 없는 점이 {len(missing_pop)}쌍 있습니다.")

    truncated = False

    if include_geometry:
        data["geometry"] = [
            _geometry_entry(sk, i, g) for i, g in enumerate(geometry[:max_items])
        ]
        if len(geometry) > max_items:
            truncated = True

    if include_constraints:
        flagged = set()
        for group in (conflicting, redundant, partially_redundant, malformed):
            for item in group:
                flagged.add(item["index"])
        picked = list(range(min(len(constraints), max_items)))
        # 문제로 지목된 제약은 잘리더라도 반드시 포함한다 (명세 7.5)
        extra = sorted(i for i in flagged if 0 <= i < len(constraints) and i not in picked)
        data["constraints"] = [
            _constraint_entry(i, constraints[i], external_count) for i in picked + extra
        ]
        if len(constraints) > max_items:
            truncated = True
            if extra:
                warnings.append(
                    f"제약 {len(constraints)}개 중 {max_items}개 + 문제로 지목된 "
                    f"{len(extra)}개를 담았습니다."
                )

    if truncated and not any("담았습니다" in w for w in warnings):
        warnings.append(
            f"geometry/constraints는 각 {max_items}개까지입니다. counts는 전체 기준입니다."
        )

    if util.fit_cap(data, "geometry", warnings):
        truncated = True
    if util.fit_cap(data, "constraints", warnings):
        truncated = True

    return util.envelope(data, warnings=warnings, truncated=truncated, t0=t0)


TOOLS = {"get_sketch_diagnostics": get_sketch_diagnostics}
