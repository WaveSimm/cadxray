"""핸들러 공통 — 응답 봉투, 직렬화, 크기 제한, 버전 분기."""

import time
import traceback

import FreeCAD

ADDON_VERSION = "0.1.0"

# 하드캡. 이 크기를 넘으면 응답을 잘라서 경고를 붙인다 (명세 3장 원칙 4).
HARD_CAP_BYTES = 100 * 1024


def envelope(data, warnings=None, truncated=False, t0=None):
    return {
        "ok": True,
        "data": data,
        "warnings": warnings or [],
        "truncated": bool(truncated),
        "elapsed_ms": int((time.time() - t0) * 1000) if t0 else 0,
    }


def error(msg, exc=None):
    out = {"ok": False, "error": str(msg)}
    if exc is not None:
        out["traceback"] = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        )
    return out


def freecad_version():
    """(major, minor) 정수 튜플. API 분기용. [확인됨: api-notes 1장]"""
    v = FreeCAD.Version()
    return int(v[0]), int(v[1])


def version_string():
    v = FreeCAD.Version()
    return ".".join(str(x) for x in v[:3])


def get_doc(name=None):
    """문서를 찾아 반환. 없으면 (None, 에러메시지)."""
    if name:
        doc = FreeCAD.getDocument(name) if name in FreeCAD.listDocuments() else None
        if doc is None:
            known = ", ".join(FreeCAD.listDocuments().keys()) or "(열린 문서 없음)"
            return None, f"문서 '{name}'을 찾을 수 없습니다. 열린 문서: {known}"
        return doc, None
    doc = FreeCAD.ActiveDocument
    if doc is None:
        return None, "활성 문서가 없습니다. FreeCAD에서 문서를 열거나 doc 인자로 이름을 주세요."
    return doc, None


def round_vec(v, nd=4):
    return [round(float(v.x), nd), round(float(v.y), nd), round(float(v.z), nd)]


# --- 직렬화 -----------------------------------------------------------------
# M1에서는 execute_code의 `_result`를 돌려주는 데 필요한 만큼만 구현한다.
# Quantity 등 아직 확인하지 않은 타입은 추측하지 않고 문자열로 떨어뜨린다.
# (M2에서 라이브 introspection으로 확인한 뒤 확장 — 명세 6.4)

_MAX_DEPTH = 6


def shape_summary(shape):
    """Part.Shape 요약. 원본은 절대 덤프하지 않는다. [확인됨: api-notes 6장]"""
    try:
        if shape.isNull():
            return {"null": True}
        bb = shape.BoundBox
        return {
            "shape_type": shape.ShapeType,
            "is_null": False,
            "is_valid": bool(shape.isValid()),
            "solids": len(shape.Solids),
            "faces": len(shape.Faces),
            "edges": len(shape.Edges),
            "vertexes": len(shape.Vertexes),
            "bbox": {
                "min": [round(bb.XMin, 4), round(bb.YMin, 4), round(bb.ZMin, 4)],
                "max": [round(bb.XMax, 4), round(bb.YMax, 4), round(bb.ZMax, 4)],
                "size": [round(bb.XLength, 4), round(bb.YLength, 4), round(bb.ZLength, 4)],
            },
        }
    except Exception as e:
        return {"error": f"shape 요약 실패: {e}"}


def _is_shape(value):
    try:
        import Part

        return isinstance(value, Part.Shape)
    except Exception:
        return False


def serialize(value, depth=0, max_list=50):
    """FreeCAD 타입 → JSON 직렬화 가능한 값."""
    if depth > _MAX_DEPTH:
        return f"<depth limit: {type(value).__name__}>"

    if value is None or isinstance(value, (bool, int, float, str)):
        return value

    if isinstance(value, FreeCAD.Vector):
        return round_vec(value)

    if isinstance(value, FreeCAD.Rotation):
        return {"axis": round_vec(value.Axis), "angle_deg": round(value.Angle * 180.0 / 3.141592653589793, 4)}

    if isinstance(value, FreeCAD.Placement):
        return {
            "base": round_vec(value.Base),
            "rotation_axis": round_vec(value.Rotation.Axis),
            "rotation_angle_deg": round(value.Rotation.Angle * 180.0 / 3.141592653589793, 4),
        }

    if isinstance(value, FreeCAD.BoundBox):
        return {
            "min": [round(value.XMin, 4), round(value.YMin, 4), round(value.ZMin, 4)],
            "max": [round(value.XMax, 4), round(value.YMax, 4), round(value.ZMax, 4)],
            "size": [round(value.XLength, 4), round(value.YLength, 4), round(value.ZLength, 4)],
        }

    if _is_shape(value):
        return shape_summary(value)

    # DocumentObject → 이름
    if hasattr(value, "TypeId") and hasattr(value, "Name") and hasattr(value, "Document"):
        return value.Name

    if isinstance(value, dict):
        return {str(k): serialize(v, depth + 1, max_list) for k, v in value.items()}

    if isinstance(value, (list, tuple)):
        items = list(value)
        # (obj, [subnames]) 링크 튜플
        if (
            len(items) == 2
            and hasattr(items[0], "TypeId")
            and hasattr(items[0], "Name")
            and isinstance(items[1], (list, tuple))
        ):
            return {"object": items[0].Name, "sub": [str(s) for s in items[1]]}
        out = [serialize(v, depth + 1, max_list) for v in items[:max_list]]
        if len(items) > max_list:
            out.append({"_truncated": len(items)})
        return out

    return f"<{type(value).__name__}> {value}"
