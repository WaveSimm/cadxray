"""어셈블리 Link 너머 문서 추적 (M14, 명세 7.42).

trace_links — 문서의 외부 참조(App::Link·Link 배열·SubShapeBinder·Part 불리언·수식)를 따라가
어느 파일의 어느 객체를 쓰는지, 그 문서에 Invalid 객체가 있는지, 깨진 링크(파일 없음)는 무엇인지 한 번에.
FreeCAD 1.1.3 라이브 확인 사항은 docs/api-notes.md §19.
"""

import os
import re
import time

import FreeCAD

from . import util

_LINK_TYPES = ("App::Link", "App::LinkElement", "App::LinkGroup", "Part::Link")
_MISSING_RX = re.compile(r"Linked file:\s*(.+?)\s*$", re.M)
_MISSING_OBJ_RX = re.compile(r"Linked object:\s*(.+?)\s*$", re.M)


def _doc_of(obj):
    try:
        return obj.Document
    except Exception:  # noqa: BLE001
        return None


def _kind(obj):
    t = obj.TypeId
    if t in ("App::Link", "App::LinkElement", "Part::Link"):
        if getattr(obj, "ElementCount", 0):
            return "link_array"
        return "link"
    if t == "App::LinkGroup":
        return "link_group"
    if "SubShapeBinder" in t:
        return "binder"
    return "reference"


def _broken_info(obj):
    """'Link not restored' 상태면 (객체 이름, 파일 이름)."""
    try:
        if "Invalid" not in obj.State:
            return None
        s = obj.getStatusString() or ""
    except Exception:  # noqa: BLE001
        return None
    if "Link not restored" not in s and "Linked file" not in s:
        return None
    m_file = _MISSING_RX.search(s)
    m_obj = _MISSING_OBJ_RX.search(s)
    return {"object": m_obj.group(1) if m_obj else None, "file": m_file.group(1) if m_file else None, "status": s.splitlines()[0]}


def _doc_summary(d):
    invalid = []
    for o in d.Objects:
        try:
            if "Invalid" in o.State:
                invalid.append(o.Name)
        except Exception:  # noqa: BLE001
            pass
    return {"name": d.Name, "label": util.label(d), "file": d.FileName or None, "open": True, "objects": len(d.Objects),
            "invalid": len(invalid), "invalid_objects": invalid[:20], "modified": bool(getattr(d, "Modified", False))}


def _external_refs(obj, home):
    """obj가 다른 문서의 객체를 직접 가리키는 것들 (OutList 기준)."""
    out = []
    try:
        for o in obj.OutList:
            od = _doc_of(o)
            if od is not None and od.Name != home.Name:
                out.append(o)
    except Exception:  # noqa: BLE001
        pass
    return out


def _final_target(obj):
    try:
        t = obj.getLinkedObject(True)
        return t if t is not None and t is not obj else None
    except Exception:  # noqa: BLE001
        return None


def _entry(obj, home, depth_of):
    kind = _kind(obj)
    direct = None
    try:
        direct = obj.LinkedObject if hasattr(obj, "LinkedObject") else None
    except Exception:  # noqa: BLE001
        direct = None
    ext = _external_refs(obj, home)
    broken = _broken_info(obj)
    final0 = _final_target(obj) if kind != "reference" else None
    final_ext = final0 is not None and _doc_of(final0) is not None and _doc_of(final0).Name != home.Name
    e = {"name": obj.Name, "label": util.label(obj), "type": obj.TypeId, "kind": kind, "external": bool(ext) or final_ext or (broken is not None),
         "state": list(obj.State)}
    if kind == "link_array":
        e["element_count"] = int(getattr(obj, "ElementCount", 0))
    if direct is not None:
        dd = _doc_of(direct)
        e["target"] = {"name": direct.Name, "label": util.label(direct), "type": direct.TypeId, "document": dd.Name if dd else None,
                       "file": (dd.FileName or None) if dd else None, "invalid": "Invalid" in direct.State}
        final = _final_target(obj)
        if final is not None and final is not direct:
            fd = _doc_of(final)
            e["final_target"] = {"name": final.Name, "label": util.label(final), "type": final.TypeId, "document": fd.Name if fd else None}
        hops = 1
        cur = direct
        seen = {obj.Name}
        while cur is not None and hasattr(cur, "LinkedObject") and cur.Name not in seen and hops < 20:
            seen.add(cur.Name)
            try:
                nxt = cur.LinkedObject
            except Exception:  # noqa: BLE001
                nxt = None
            if nxt is None or nxt is cur:
                break
            hops += 1
            cur = nxt
        e["hops"] = hops
    elif ext:
        e["references"] = [{"name": o.Name, "label": util.label(o), "type": o.TypeId, "document": _doc_of(o).Name, "invalid": "Invalid" in o.State} for o in ext[:10]]
        e["references_total"] = len(ext)
    if broken:
        e["broken"] = broken
    return e


def trace_links(doc=None, max_depth=5, max_links=200, include_local=False):
    """문서의 Link/외부 참조를 따라 문서 사슬·깨진 링크·연결 문서의 Invalid 객체를 모은다 (명세 7.42)."""
    t0 = time.time()
    d, err = util.get_doc(doc)
    if err:
        return util.error(err)
    warnings = []
    try:
        max_depth = max(1, int(max_depth))
        documents = {d.Name: dict(_doc_summary(d), depth=0, via=None)}
        links = []
        problems = []
        queue = [(d, 0)]
        visited = {d.Name}
        while queue:
            cur, depth = queue.pop(0)
            for obj in cur.Objects:
                kind = _kind(obj)
                ext = _external_refs(obj, cur)
                broken = _broken_info(obj)
                if kind == "reference" and not ext and broken is None:
                    continue
                final = _final_target(obj) if kind != "reference" else None
                final_ext = final is not None and _doc_of(final) is not None and _doc_of(final).Name != cur.Name
                if final_ext and final not in ext:
                    ext = ext + [final]          # Link의 Link: 직접 대상은 같은 문서지만 최종 대상은 밖
                if kind != "reference" and not ext and broken is None and not include_local:
                    continue          # 같은 문서 안의 Link
                e = _entry(obj, cur, depth)
                e["document"] = cur.Name
                e["depth"] = depth
                links.append(e)
                if broken:
                    problems.append({"kind": "broken_link", "document": cur.Name, "object": obj.Name, "detail": f"{obj.Name}: 파일 '{broken.get('file')}'의 '{broken.get('object')}'을 못 찾았습니다",
                                     "fix": f"open_document('<경로>/{broken.get('file')}') 후 tracked_recompute, 또는 파일 위치 복구"})
                for o in ext:
                    od = _doc_of(o)
                    if od is None or od.Name in visited:
                        continue
                    visited.add(od.Name)
                    documents[od.Name] = dict(_doc_summary(od), depth=depth + 1, via=f"{cur.Name}.{obj.Name}")
                    if depth + 1 < max_depth:
                        queue.append((od, depth + 1))
                    else:
                        warnings.append(f"max_depth {max_depth}에 닿아 '{od.Name}' 너머는 따라가지 않았습니다.")
        # 의존 문서 중 훑지 못한 것(수식 등 OutList에 안 잡히는 참조)
        try:
            for dd in d.getDependentDocuments():
                if dd.Name not in documents:
                    documents[dd.Name] = dict(_doc_summary(dd), depth=None, via="getDependentDocuments")
        except Exception:  # noqa: BLE001
            pass
        for name, info in documents.items():
            if name != d.Name and info["invalid"]:
                problems.append({"kind": "invalid_in_linked", "document": name, "object": info["invalid_objects"][0] if info["invalid_objects"] else None,
                                 "detail": f"연결 문서 '{name}'에 Invalid 객체 {info['invalid']}개: {', '.join(info['invalid_objects'][:5])}",
                                 "fix": f"get_document_graph(doc='{name}') → 진단 워크플로"})
        for i, p in enumerate(problems):
            p["id"] = i + 1
        ext_links = [l for l in links if l["external"]]
        by_doc = {}
        for l in ext_links:
            tgt = (l.get("final_target") or l.get("target") or {}).get("document") or (l.get("references") or [{}])[0].get("document")
            if tgt:
                by_doc[tgt] = by_doc.get(tgt, 0) + 1
        summary = {"documents": len(documents), "external_links": len(ext_links), "local_links": len(links) - len(ext_links), "broken": len([l for l in links if l.get("broken")]),
                   "link_arrays": len([l for l in links if l["kind"] == "link_array"]), "instances": sum(l.get("element_count") or 1 for l in ext_links if l["kind"] in ("link", "link_array")),
                   "by_target_document": by_doc, "problems": len(problems)}
        truncated = len(links) > int(max_links)
        data = {"document": d.Name, "summary": summary, "documents": list(documents.values()), "links": links[: int(max_links)], "links_total": len(links),
                "problems": problems}
        if not ext_links and not problems:
            warnings.append("외부 문서를 가리키는 Link가 없습니다. 같은 문서 안의 Link까지 보려면 include_local=True.")
        if truncated:
            warnings.append(f"링크 {len(links)}개 중 {max_links}개만 담았습니다. summary는 전체 기준입니다.")
    except Exception as e:  # noqa: BLE001
        return util.error(f"링크 추적 실패: {e}", e)
    return util.envelope(data, warnings=warnings, truncated=truncated, t0=t0)


TOOLS = {"trace_links": trace_links}
