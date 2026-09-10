"""STEP/IGES 가져오기 — import_step (명세 7.12).

히스토리 없는 파일을 문서에 넣고, 생긴 객체를 돌려준다.
새 문서: Import.open(path) / 기존 문서: Import.insert(path, docName) [확인됨: api-notes 12장]
"""

import os
import time

import FreeCAD

from . import util

_EXTENSIONS = {".step", ".stp", ".iges", ".igs"}


def _shape_of(obj):
    try:
        s = obj.Shape
        return None if s.isNull() else s
    except Exception:
        return None


def _entry(obj):
    e = {"name": obj.Name, "label": obj.Label, "type": obj.TypeId}
    group = getattr(obj, "Group", None)
    if group is not None and not hasattr(obj, "Shape"):
        e["children"] = [o.Name for o in group]
        return e
    s = _shape_of(obj)
    if s is not None:
        e["solids"] = len(s.Solids)
        e["faces"] = len(s.Faces)
        try:
            e["valid"] = bool(s.isValid())
        except Exception:
            e["valid"] = None
    return e


def _call_import(fn, path, doc_name, import_hidden, merge, use_link_group, mode):
    """키워드 인자를 지원하면 쓰고, 아니면(구버전) 위치 인자만 쓴다."""
    kwargs = {
        "importHidden": bool(import_hidden),
        "merge": bool(merge),
        "useLinkGroup": bool(use_link_group),
        "mode": int(mode),
    }
    args = (path,) if doc_name is None else (path, doc_name)
    try:
        return fn(*args, **kwargs), True
    except TypeError:
        return fn(*args), False


def import_step(
    path,
    doc=None,
    merge=False,
    use_link_group=False,
    import_hidden=False,
    mode=0,
    max_objects=100,
):
    """STEP/IGES를 문서에 넣고 생긴 객체를 요약한다."""
    t0 = time.time()
    if not path or not isinstance(path, str):
        return util.error("path는 파일 경로 문자열이어야 합니다.")
    path = os.path.abspath(os.path.expanduser(path))
    ext = os.path.splitext(path)[1].lower()
    if ext not in _EXTENSIONS:
        return util.error(
            f"지원하지 않는 확장자 '{ext}'. STEP(.step/.stp)·IGES(.iges/.igs)만 됩니다. "
            "STL/OBJ 같은 메시는 형상(면·솔리드)이 없어 이 툴로 분석할 수 없습니다."
        )
    if not os.path.isfile(path):
        return util.error(f"파일이 없습니다: {path}")
    try:
        import Import
    except Exception as e:
        return util.error(f"Import 모듈을 불러올 수 없습니다: {e}")

    warnings = []
    try:
        if doc is None:
            before = set(FreeCAD.listDocuments().keys())
            _, kw_ok = _call_import(Import.open, path, None, import_hidden, merge, use_link_group, mode)
            new_names = [n for n in FreeCAD.listDocuments().keys() if n not in before]
            if new_names:
                d = FreeCAD.getDocument(new_names[0])
            else:
                d = FreeCAD.ActiveDocument
                warnings.append("새 문서가 감지되지 않아 활성 문서를 대상으로 봅니다.")
            created_objs = list(d.Objects)
        else:
            d, err = util.get_doc(doc)
            if err:
                return util.error(err)
            before_objs = {o.Name for o in d.Objects}
            _, kw_ok = _call_import(Import.insert, path, d.Name, import_hidden, merge, use_link_group, mode)
            created_objs = [o for o in d.Objects if o.Name not in before_objs]
    except Exception as e:
        return util.error(f"가져오기 실패: {e}", exc=e)

    if not kw_ok:
        warnings.append(
            "이 FreeCAD의 Import.open/insert가 키워드 인자를 받지 않아 merge·mode 등은 무시됐습니다."
        )
    try:
        d.recompute()
    except Exception as e:
        warnings.append(f"recompute 실패: {e}")

    created_names = {o.Name for o in created_objs}
    solids_total = 0
    invalid = []
    bb = None
    for o in created_objs:
        if "Invalid" in o.State:
            invalid.append(o.Name)
        s = _shape_of(o)
        if s is None or getattr(o, "Group", None) is not None and not o.TypeId.startswith("Part::"):
            continue
        # App::Part / 그룹은 Shape가 없거나 자식 형상을 겹쳐 세게 되므로 Part:: 계열만 센다
        if not o.TypeId.startswith("Part::"):
            continue
        solids_total += len(s.Solids)
        try:
            if not s.isValid() and o.Name not in invalid:
                invalid.append(o.Name)
        except Exception:
            pass
        try:
            b = s.BoundBox
            if bb is None:
                bb = FreeCAD.BoundBox(b)
            else:
                bb.add(b)
        except Exception:
            pass

    top_level = [
        o.Name
        for o in created_objs
        if not any(p.Name in created_names for p in o.InList)
    ]

    truncated = len(created_objs) > max_objects
    data = {
        "document": d.Name,
        "path": path,
        "created_total": len(created_objs),
        "created": [_entry(o) for o in created_objs[:max_objects]],
        "top_level": top_level,
        "solids_total": solids_total,
        "invalid": invalid,
        "bbox": util.serialize(bb) if bb is not None else None,
    }
    if created_objs and solids_total == 0:
        warnings.append("솔리드가 하나도 없습니다. 파일이 면(surface)만 담고 있거나 가져오기가 실패했을 수 있습니다.")
    if invalid:
        warnings.append(f"유효하지 않은 형상: {', '.join(invalid)}. analyze_shape(bop_check=True)로 확인하세요.")
    if truncated:
        warnings.append(f"객체 {len(created_objs)}개 중 {max_objects}개만 담았습니다. 요약은 전체 기준입니다.")
    if util.fit_cap(data, "created", warnings):
        truncated = True
    return util.envelope(data, warnings=warnings, truncated=truncated, t0=t0)


TOOLS = {"import_step": import_step}
