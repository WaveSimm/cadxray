"""ping, list_documents — 연결 확인과 문서 목록."""

import time

import FreeCAD

from . import util


def ping():
    """연결 확인과 버전 파악. [확인됨: api-notes 1·3장]"""
    t0 = time.time()
    docs = FreeCAD.listDocuments()
    active = FreeCAD.ActiveDocument
    return util.envelope(
        {
            "freecad_version": util.version_string(),
            "gui": bool(FreeCAD.GuiUp),
            "active_document": active.Name if active else None,
            "documents": len(docs),
            "addon_version": util.ADDON_VERSION,
        },
        t0=t0,
    )


def list_documents():
    """열린 문서 목록. [확인됨: api-notes 3장]"""
    t0 = time.time()
    active = FreeCAD.ActiveDocument
    active_name = active.Name if active else None
    out = []
    for name, doc in FreeCAD.listDocuments().items():
        out.append(
            {
                "name": name,
                "label": util.label(doc),
                "filename": doc.FileName or None,
                "object_count": len(doc.Objects),
                "active": name == active_name,
                # App.Document에는 Modified 속성이 없다. isSaved()/isTouched()를 쓴다.
                # [확인됨: 라이브 1.1.3 introspection, 소스 1.0.2·1.1.3]
                "saved": bool(doc.isSaved()),
                "modified": not bool(doc.isSaved()),
                "touched": bool(doc.isTouched()),
            }
        )
    return util.envelope(out, t0=t0)


def open_document(path=None):
    """FCStd를 연다. 이미 열려 있으면 그 문서. (명세 7.28)"""
    import os

    t0 = time.time()
    if not path or not os.path.isfile(str(path)):
        return util.error(f"파일이 없습니다: {path}")
    if not str(path).lower().endswith(".fcstd"):
        return util.error("FCStd 파일만 엽니다. STEP/IGES는 import_step, STL은 import_mesh로.")
    full = os.path.abspath(str(path))
    key = os.path.normcase(os.path.realpath(full))
    for name, d in FreeCAD.listDocuments().items():
        if d.FileName and os.path.normcase(os.path.realpath(d.FileName)) == key:
            return util.envelope({"name": name, "label": util.label(d), "filename": d.FileName, "objects": len(d.Objects), "already_open": True}, t0=t0)
    try:
        d = FreeCAD.openDocument(full)
    except Exception as e:  # noqa: BLE001
        return util.error(f"열기 실패: {e}", e)
    FreeCAD.setActiveDocument(d.Name)
    # FreeCAD는 다시 연 문서의 이름을 파일명으로 짓는다(원래 문서 이름은 남지 않는다) [라이브 1.1.3]
    return util.envelope({"name": d.Name, "label": util.label(d), "filename": d.FileName, "objects": len(d.Objects), "already_open": False}, t0=t0)


def save_document(doc=None, path=None, overwrite=False):
    """문서를 저장한다. path 없으면 원래 파일에, 있으면 saveAs. 다른 기존 파일을 덮어쓰려면 overwrite. (명세 7.28)"""
    import os

    t0 = time.time()
    d, err = util.get_doc(doc)
    if err:
        return util.error(err)
    try:
        if path:
            full = os.path.abspath(str(path))
            if not full.lower().endswith(".fcstd"):
                return util.error(f"저장 경로는 .FCStd여야 합니다: {full}")
            same = bool(d.FileName) and os.path.normcase(os.path.realpath(d.FileName)) == os.path.normcase(os.path.realpath(full))
            if os.path.exists(full) and not same and not overwrite:
                return util.error(f"이미 있는 파일입니다: {full}. 덮어쓰려면 overwrite=true.")
            os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
            d.saveAs(full)
        else:
            if not d.FileName:
                return util.error(f"문서 '{d.Name}'은 아직 파일이 없습니다. path를 주세요.")
            d.save()
    except Exception as e:  # noqa: BLE001
        return util.error(f"저장 실패: {e}", e)
    size = os.path.getsize(d.FileName) if d.FileName and os.path.exists(d.FileName) else None
    return util.envelope({"name": d.Name, "filename": d.FileName, "bytes": size, "objects": len(d.Objects)}, t0=t0)


TOOLS = {"ping": ping, "list_documents": list_documents, "open_document": open_document, "save_document": save_document}
