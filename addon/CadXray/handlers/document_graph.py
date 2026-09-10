"""문서 구조 — get_document_graph, inspect_object (명세 7.3·7.4)."""

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
        "label": util.label(obj),
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
        selected = [o for o in selected if rx.search(util.label(o))]

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
                "label": util.label(obj),
                "tip": tip.Name if tip is not None else None,
                "features": [f.Name for f in getattr(obj, "Group", [])],
            }
        )

    data = {
        "document": d.Name,
        "label": util.label(d),
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
        "label": util.label(obj),
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


TOOLS = {
    "get_document_graph": get_document_graph,
    "inspect_object": inspect_object,
}
