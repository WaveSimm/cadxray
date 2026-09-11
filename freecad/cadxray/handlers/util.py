"""핸들러 공통 — 응답 봉투, 직렬화, 크기 제한, 버전 분기."""

import json
import time
import traceback

import FreeCAD

ADDON_VERSION = "0.11.0"

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
# 확인한 타입만 구조화한다. 나머지는 추측하지 않고 "<타입명> repr" 문자열로 떨어뜨린다.
# (Quantity는 M2에서 라이브 introspection으로 확인 — api-notes 8장)

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


def _quantity_class():
    """Base.Quantity 클래스. 없으면 None. [확인됨: 라이브 1.1.3, 2026-09-10]"""
    try:
        return FreeCAD.Units.Quantity
    except Exception:
        return None


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

    # Base.Quantity — Value(float), Unit.Type("Length"), UserString("15.00 mm")
    # [확인됨: 라이브 1.1.3 introspection, 2026-09-10]
    _Q = _quantity_class()
    if _Q is not None and isinstance(value, _Q):
        return {
            "value": round(float(value.Value), 6),
            "text": str(value.UserString),
            "quantity": str(getattr(value.Unit, "Type", "")),
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


# --- STEP 라벨 디코딩 ---------------------------------------------------------
# FreeCAD는 STEP 이름의 ISO 10303-21 이스케이프를 풀지 않는다 [라이브 1.1.3]:
#   \X2\c6d4d30c\X0\  → UTF-16BE 16진수 → "월파"     \X4\0001F600\X0\ → UTF-32BE
#   \S\c              → Latin-1 상위 반쪽(0x80 + ord)
# 라벨을 내보낼 때만 풀고, 객체의 Label 자체는 건드리지 않는다.

import re as _re

_STEP_X2 = _re.compile(r"\\X2\\([0-9A-Fa-f]+)\\X0\\")
_STEP_X4 = _re.compile(r"\\X4\\([0-9A-Fa-f]+)\\X0\\")
_STEP_S = _re.compile(r"\\S\\(.)")


def decode_step_text(text):
    """STEP 이스케이프가 섞인 문자열을 사람이 읽는 문자열로. 실패하면 원문 그대로."""
    if not isinstance(text, str) or "\\" not in text:
        return text
    try:
        out = _STEP_X4.sub(
            lambda m: "".join(chr(int(m.group(1)[i : i + 8], 16)) for i in range(0, len(m.group(1)), 8)),
            text,
        )
        out = _STEP_X2.sub(
            lambda m: "".join(chr(int(m.group(1)[i : i + 4], 16)) for i in range(0, len(m.group(1)), 4)),
            out,
        )
        out = _STEP_S.sub(lambda m: chr(0x80 + ord(m.group(1))), out)
        return out
    except Exception:
        return text


def label(obj):
    """객체(또는 문서)의 Label을 STEP 이스케이프를 푼 형태로."""
    return decode_step_text(getattr(obj, "Label", "") or "")


# --- 이름으로 객체 찾기 -------------------------------------------------------


def find_object(doc, name):
    """Name 우선, 없으면 Label로 찾는다. 실패하면 (None, 안내메시지)."""
    if not name or not isinstance(name, str):
        return None, "name은 객체 이름(Name) 또는 라벨(Label) 문자열이어야 합니다."
    obj = doc.getObject(name)
    if obj is not None:
        return obj, None
    try:
        matches = doc.getObjectsByLabel(name)
    except Exception:
        matches = []
    if not matches:
        # STEP 이스케이프가 풀린 라벨("월파 브라켓")로 찾는 경우
        matches = [o for o in doc.Objects if label(o) == name]
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        names = ", ".join(o.Name for o in matches)
        return None, f"라벨 '{name}'인 객체가 여러 개입니다: {names}. Name으로 지정하세요."
    sample = ", ".join(o.Name for o in doc.Objects[:15])
    more = " ..." if len(doc.Objects) > 15 else ""
    return None, f"문서 '{doc.Name}'에 '{name}'이(가) 없습니다. 객체 예: {sample}{more}"


def status_string(obj):
    """getStatusString() — 에러면 설명 문자열, 아니면 Touched/Valid. [확인됨: api-notes 2장]"""
    try:
        return obj.getStatusString()
    except Exception:
        return None


# --- 응답 크기 맞추기 ---------------------------------------------------------


def json_size(obj):
    return len(json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"))


def fit_cap(data, key, warnings, floor=5):
    """data[key] 리스트를 하드캡 안에 들어오도록 줄인다. 줄였으면 True.

    rpc_server가 하드캡을 넘는 응답을 에러로 바꿔 버리므로, 그 전에 여기서 깎는다.
    """
    items = data.get(key)
    if not isinstance(items, list):
        return False
    target = int(HARD_CAP_BYTES * 0.9)  # 봉투·다른 필드 몫을 남긴다
    shrunk = False
    while len(items) > floor and json_size(data) > target:
        items[:] = items[: max(floor, int(len(items) * 0.7))]
        shrunk = True
    if shrunk:
        warnings.append(
            f"응답 크기 제한으로 {key}를 {len(items)}개까지만 담았습니다. "
            "필요하면 필터나 max_* 인자를 좁혀서 다시 호출하세요."
        )
    return shrunk
