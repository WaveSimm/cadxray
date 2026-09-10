"""구조 파악 — get_document_graph, inspect_object, analyze_shape (명세 7.3·7.4·7.6)."""

import re
import time

from . import util

_SKETCH_TYPE = "Sketcher::SketchObject"
_BODY_TYPE = "PartDesign::Body"

# 값을 직렬화하지 않고 타입명만 남길 프로퍼티 타입 (덤프하면 응답이 폭발한다)
_OPAQUE_PROP_TYPES = {
    "App::PropertyPythonObject",
    "Part::PropertyPartShape",
    "Part::PropertyGeometryList",
    "Sketcher::PropertyConstraintList",
    "Mesh::PropertyMeshKernel",
    "Points::PropertyPointKernel",
    # repr에 메모리 주소가 들어가 호출할 때마다 값이 달라진다 [확인됨: 라이브 1.1.3]
    "Materials::PropertyMaterial",
}


# --- 7.3 get_document_graph --------------------------------------------------


def _is_type(obj, type_id):
    try:
        return obj.isDerivedFrom(type_id)
    except Exception:
        return obj.TypeId == type_id


def _obj_entry(obj, include_sketch_summary):
    entry = {
        "name": obj.Name,
        "label": obj.Label,
        "type": obj.TypeId,
        "state": list(obj.State),
        "status": util.status_string(obj),
        "out": [o.Name for o in obj.OutList],
        "in": [o.Name for o in obj.InList],
        "visible": bool(getattr(obj, "Visibility", False)),
    }
    if include_sketch_summary and _is_type(obj, _SKETCH_TYPE):
        # solve()를 부르지 않는다. 마지막 solve 값을 그대로 읽기만 한다.
        # (정확한 진단은 get_sketch_diagnostics — 명세 7.5)
        try:
            entry["sketch"] = {
                "dof": int(obj.DoF),
                "fully_constrained": bool(obj.FullyConstrained),
            }
        except Exception as e:
            entry["sketch"] = {"error": str(e)}
    return entry


def get_document_graph(
    doc=None,
    max_objects=200,
    type_filter=None,
    label_pattern=None,
    include_sketch_summary=True,
):
    """문서의 객체 그래프와 문제 객체를 한 번에 준다. 진단의 첫 호출."""
    t0 = time.time()
    d, err = util.get_doc(doc)
    if err:
        return util.error(err)

    warnings = []
    all_objects = d.Objects

    # 요약과 invalid_objects는 필터·상한과 무관하게 **항상 전체** 기준 (명세 7.3)
    by_type = {}
    invalid_objects = []
    touched = 0
    for obj in all_objects:
        by_type[obj.TypeId] = by_type.get(obj.TypeId, 0) + 1
        state = obj.State
        if "Invalid" in state:
            invalid_objects.append(obj.Name)
        if "Touched" in state:
            touched += 1

    summary = {
        "objects": len(all_objects),
        "invalid": len(invalid_objects),
        "touched": touched,
        "by_type": dict(sorted(by_type.items(), key=lambda kv: -kv[1])),
    }

    # 필터
    selected = list(all_objects)
    if type_filter:
        selected = [
            o for o in selected if o.TypeId == type_filter or _is_type(o, type_filter)
        ]
        if not selected:
            warnings.append(
                f"type_filter '{type_filter}'에 맞는 객체가 없습니다. "
                f"이 문서의 타입: {', '.join(sorted(by_type))}"
            )
    if label_pattern:
        try:
            rx = re.compile(label_pattern)
        except re.error as e:
            return util.error(f"label_pattern 정규식 오류: {e}")
        selected = [o for o in selected if rx.search(o.Label)]

    truncated = len(selected) > max_objects
    entries = [_obj_entry(o, include_sketch_summary) for o in selected[:max_objects]]

    bodies = []
    for obj in all_objects:
        if not _is_type(obj, _BODY_TYPE):
            continue
        tip = getattr(obj, "Tip", None)
        bodies.append(
            {
                "name": obj.Name,
                "label": obj.Label,
                "tip": tip.Name if tip is not None else None,
                "features": [f.Name for f in getattr(obj, "Group", [])],
            }
        )

    data = {
        "document": d.Name,
        "label": d.Label,
        "summary": summary,
        "bodies": bodies,
        "roots": [o.Name for o in d.RootObjects],
        "objects": entries,
        "invalid_objects": invalid_objects,
    }
    # DoF·FullyConstrained는 마지막 solve 값이다. 둘이 모순이면(자유도 0인데
    # 완전구속이 아님) 마지막 solve가 실패했다는 뜻 — 정확한 진단은 7.5로 넘긴다.
    # [확인됨: api-notes 4.1]
    stale = [
        e["name"]
        for e in entries
        if e.get("sketch", {}).get("dof") == 0
        and e.get("sketch", {}).get("fully_constrained") is False
    ]
    if stale:
        warnings.append(
            f"스케치 {', '.join(stale)}의 dof/fully_constrained 값이 서로 맞지 않습니다"
            "(마지막 solve 실패 가능성). get_sketch_diagnostics로 확인하세요."
        )

    if truncated:
        warnings.append(
            f"객체 {len(selected)}개 중 {max_objects}개만 담았습니다. "
            "summary와 invalid_objects는 전체 기준입니다. "
            "type_filter나 label_pattern으로 좁히세요."
        )
    if util.fit_cap(data, "objects", warnings):
        truncated = True

    return util.envelope(data, warnings=warnings, truncated=truncated, t0=t0)


# --- 7.4 inspect_object ------------------------------------------------------


def _property_entry(obj, prop, max_list):
    type_id = None
    try:
        type_id = obj.getTypeIdOfProperty(prop)
    except Exception:
        pass

    if type_id in _OPAQUE_PROP_TYPES:
        return {"type": type_id, "value": f"<{type_id} — 값 생략>"}

    try:
        value = obj.getPropertyByName(prop)
    except Exception as e:
        return {"type": type_id, "error": f"읽기 실패: {e}"}

    try:
        return {"type": type_id, "value": util.serialize(value, max_list=max_list)}
    except Exception as e:
        return {"type": type_id, "error": f"직렬화 실패: {e}"}


def inspect_object(doc=None, name=None, include_shape=True, max_list=20):
    """객체 하나의 프로퍼티·수식·형상·의존관계를 전부 본다."""
    t0 = time.time()
    d, err = util.get_doc(doc)
    if err:
        return util.error(err)
    obj, err = util.find_object(d, name)
    if err:
        return util.error(err)

    warnings = []
    props = {}
    for prop in obj.PropertiesList:
        props[prop] = _property_entry(obj, prop, max_list)

    expressions = []
    try:
        expressions = [[str(p), str(e)] for p, e in (obj.ExpressionEngine or [])]
    except Exception:
        pass

    data = {
        "document": d.Name,
        "name": obj.Name,
        "label": obj.Label,
        "type": obj.TypeId,
        "state": list(obj.State),
        "status": util.status_string(obj),
        "visible": bool(getattr(obj, "Visibility", False)),
        "properties": props,
        "expressions": expressions,
        "out": [o.Name for o in obj.OutList],
        "in": [o.Name for o in obj.InList],
    }

    if include_shape and hasattr(obj, "Shape"):
        data["shape"] = util.shape_summary(obj.Shape)

    limit = int(util.HARD_CAP_BYTES * 0.9)
    if util.json_size(data) > limit:
        order = sorted(props, key=lambda p: util.json_size(props[p]))
        dropped = []
        while order and util.json_size(data) > limit:
            big = order.pop()
            props[big] = {"type": props[big].get("type"), "value": "<크기 제한으로 생략>"}
            dropped.append(big)
        warnings.append(
            f"크기 제한으로 프로퍼티 값을 생략했습니다: {', '.join(dropped)}. "
            "필요하면 execute_code로 그 프로퍼티만 읽으세요."
        )
        return util.envelope(data, warnings=warnings, truncated=True, t0=t0)

    return util.envelope(data, warnings=warnings, t0=t0)


# --- 7.6 analyze_shape -------------------------------------------------------


def _count_by(items, key_of):
    out = {}
    for it in items:
        try:
            key = key_of(it)
        except Exception:
            key = "<unknown>"
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def _try(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def analyze_shape(doc=None, name=None, max_faces=30, max_edges=30, bop_check=False):
    """형상의 유효성·부피·면/모서리 구성을 본다. '형상이 왜 이상한가'용."""
    t0 = time.time()
    d, err = util.get_doc(doc)
    if err:
        return util.error(err)
    obj, err = util.find_object(d, name)
    if err:
        return util.error(err)
    if not hasattr(obj, "Shape"):
        return util.error(
            f"'{obj.Name}'({obj.TypeId})에는 Shape가 없습니다. inspect_object를 쓰세요."
        )

    warnings = []
    shape = obj.Shape
    data = {
        "document": d.Name,
        "object": obj.Name,
        "label": obj.Label,
        "type": obj.TypeId,
        "status": util.status_string(obj),
    }

    if shape.isNull():
        data["is_null"] = True
        warnings.append("Shape가 비어 있습니다(null). 재계산에 실패했거나 아직 계산되지 않았습니다.")
        return util.envelope(data, warnings=warnings, t0=t0)

    # check()는 문제가 있으면 예외를 던진다 [확인됨: api-notes 6장]
    check_message = None
    try:
        shape.check(bool(bop_check))
    except Exception as e:
        check_message = str(e)

    bb = shape.BoundBox
    faces, edges = shape.Faces, shape.Edges
    data.update(
        {
            "shape_type": shape.ShapeType,
            "is_null": False,
            "is_valid": bool(_try(shape.isValid, False)),
            "check_message": check_message,
            "bop_check": bool(bop_check),
            "solids": len(shape.Solids),
            "shells": len(shape.Shells),
            "wires": len(shape.Wires),
            "faces": len(faces),
            "edges": len(edges),
            "vertexes": len(shape.Vertexes),
            "volume": _try(lambda: round(shape.Volume, 4)),
            "area": _try(lambda: round(shape.Area, 4)),
            "length": _try(lambda: round(shape.Length, 4)),
            "bbox": {
                "min": [round(bb.XMin, 4), round(bb.YMin, 4), round(bb.ZMin, 4)],
                "max": [round(bb.XMax, 4), round(bb.YMax, 4), round(bb.ZMax, 4)],
                "size": [round(bb.XLength, 4), round(bb.YLength, 4), round(bb.ZLength, 4)],
                "diagonal": round(bb.DiagonalLength, 4),
            },
            "center_of_mass": _try(lambda: util.round_vec(shape.CenterOfGravity)),
            "closed": _try(shape.isClosed),
            "faces_by_surface": _count_by(faces, lambda f: type(f.Surface).__name__),
            "edges_by_curve": _count_by(edges, lambda e: type(e.Curve).__name__),
        }
    )

    data["face_details"] = [
        {
            "i": i,
            "surface": _try(lambda f=f: type(f.Surface).__name__, "<unknown>"),
            "area": _try(lambda f=f: round(f.Area, 4)),
            "orientation": _try(lambda f=f: str(f.Orientation)),
            "center": _try(lambda f=f: util.round_vec(f.CenterOfMass)),
        }
        for i, f in enumerate(faces[:max_faces])
    ]
    data["edge_details"] = [
        {
            "i": i,
            "curve": _try(lambda e=e: type(e.Curve).__name__, "<unknown>"),
            "length": _try(lambda e=e: round(e.Length, 4)),
            "closed": _try(lambda e=e: bool(e.Closed)),
        }
        for i, e in enumerate(edges[:max_edges])
    ]

    truncated = len(faces) > max_faces or len(edges) > max_edges
    if truncated:
        warnings.append(
            f"상세는 면 {min(len(faces), max_faces)}/{len(faces)}개, "
            f"모서리 {min(len(edges), max_edges)}/{len(edges)}개까지입니다. "
            "집계(faces_by_surface·edges_by_curve)는 전체 기준입니다."
        )

    # PartDesign 피처의 Shape는 Body 누적 형상이므로 피처 자체 형상도 함께 준다
    # [확인됨: api-notes 7장]
    # AddSubType은 1.1.3 Pad에 Python 속성으로 노출되지 않는다 [확인됨: 라이브 1.1.3]
    own = getattr(obj, "AddSubShape", None)
    if own is not None:
        data["feature_own_shape"] = util.shape_summary(own)
        sub_type = getattr(obj, "AddSubType", None)
        if sub_type is not None:
            data["add_sub_type"] = str(sub_type)

    if check_message:
        warnings.append(f"Shape.check() 실패: {check_message}")

    if util.fit_cap(data, "face_details", warnings):
        truncated = True
    if util.fit_cap(data, "edge_details", warnings):
        truncated = True

    return util.envelope(data, warnings=warnings, truncated=truncated, t0=t0)
