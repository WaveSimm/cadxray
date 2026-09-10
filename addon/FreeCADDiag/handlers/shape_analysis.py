"""형상 분석 — analyze_shape (명세 7.6)."""

import time

from . import util


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
        "label": util.label(obj),
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


TOOLS = {"analyze_shape": analyze_shape}
