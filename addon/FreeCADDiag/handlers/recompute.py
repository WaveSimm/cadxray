"""재계산 추적 — tracked_recompute (명세 7.7).

recompute 전후의 State·getStatusString()을 비교해서 "무엇이 고쳐졌고 무엇이
새로 깨졌는지"를 돌려준다. 고친 뒤 결과 확인용.
"""

import time

from . import util


def _snapshot(objects):
    return {
        o.Name: {
            "state": list(o.State),
            "status": util.status_string(o),
            "invalid": "Invalid" in o.State,
            "touched": "Touched" in o.State,
        }
        for o in objects
    }


def _entry(name, snap, label_of):
    s = snap.get(name, {})
    return {"name": name, "label": label_of.get(name, name), "status": s.get("status")}


def tracked_recompute(doc=None, objects=None, force=False):
    """재계산하고 전후 상태를 비교한다."""
    t0 = time.time()
    d, err = util.get_doc(doc)
    if err:
        return util.error(err)

    warnings = []
    targets = None
    if objects:
        if isinstance(objects, str):
            objects = [objects]
        targets = []
        missing = []
        for name in objects:
            obj, e = util.find_object(d, name)
            if obj is None:
                missing.append(name)
            else:
                targets.append(obj)
        if missing:
            return util.error(
                f"찾을 수 없는 객체: {', '.join(missing)}. "
                "이름을 확인하려면 get_document_graph를 쓰세요."
            )

    all_objects = d.Objects
    label_of = {o.Name: util.label(o) for o in all_objects}
    before = _snapshot(all_objects)

    try:
        if targets:
            count = d.recompute(targets, bool(force))
        else:
            count = d.recompute(None, bool(force))
    except Exception as e:
        return util.error(f"recompute 실패: {e}", exc=e)

    after = _snapshot(d.Objects)

    new_errors, resolved, persistent, still_touched, changed_status = [], [], [], [], []
    for name, now in after.items():
        was = before.get(name)
        if now["invalid"]:
            if was is None or not was["invalid"]:
                new_errors.append(_entry(name, after, label_of))
            else:
                persistent.append(_entry(name, after, label_of))
        elif was is not None and was["invalid"]:
            resolved.append(_entry(name, after, label_of))
        if now["touched"]:
            still_touched.append(name)
        if was is not None and was["status"] != now["status"] and not now["invalid"]:
            changed_status.append(
                {
                    "name": name,
                    "label": label_of.get(name, name),
                    "before": was["status"],
                    "after": now["status"],
                }
            )

    gone = [n for n in before if n not in after]

    data = {
        "document": d.Name,
        "requested": [o.Name for o in targets] if targets else None,
        "recomputed": int(count) if count is not None else None,
        "new_errors": new_errors,
        "resolved": resolved,
        "persistent": persistent,
        "still_touched": still_touched,
        "changed_status": changed_status,
        "invalid_after": [e["name"] for e in new_errors + persistent],
    }
    if gone:
        data["removed"] = gone

    if new_errors:
        names = ", ".join(e["name"] for e in new_errors)
        warnings.append(f"새로 깨진 객체: {names}. status에 원인이 들어 있습니다.")
    if persistent:
        warnings.append(
            f"고쳐지지 않은 객체: {', '.join(e['name'] for e in persistent)}."
        )
    if still_touched:
        warnings.append(
            f"재계산 후에도 Touched로 남은 객체가 {len(still_touched)}개 있습니다. "
            "의존관계가 얽혀 있으면 force=True로 다시 시도해 보세요."
        )
    if not new_errors and not persistent:
        warnings.append("에러 상태인 객체가 없습니다.")

    return util.envelope(data, warnings=warnings, t0=t0)


TOOLS = {"tracked_recompute": tracked_recompute}
