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


TOOLS = {"ping": ping, "list_documents": list_documents}
