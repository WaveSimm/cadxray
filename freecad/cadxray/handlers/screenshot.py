"""3D 뷰 캡처 — get_screenshot (명세 7.8).

saveImage는 저장 폴더가 없으면 RuntimeError를 낸다 → tempfile.mkdtemp()를 쓴다.
[확인됨: api-notes 9장]
"""

import base64
import os
import shutil
import tempfile
import time

import FreeCAD

from . import util

# view 이름 → View3DInventor 메서드 [확인됨: api-notes 9장]
_VIEWS = {
    "current": None,
    "iso": "viewIsometric",
    "isometric": "viewIsometric",
    "front": "viewFront",
    "rear": "viewRear",
    "back": "viewRear",
    "top": "viewTop",
    "bottom": "viewBottom",
    "left": "viewLeft",
    "right": "viewRight",
    "axonometric": "viewAxonometric",
    "dimetric": "viewDimetric",
    "trimetric": "viewTrimetric",
}

MAX_SIDE = 4096


def _get_view(doc_name):
    import FreeCADGui

    try:
        gdoc = FreeCADGui.getDocument(doc_name)
    except Exception:
        gdoc = None
    view = getattr(gdoc, "ActiveView", None)
    if view is None:
        gdoc = getattr(FreeCADGui, "ActiveDocument", None)
        view = getattr(gdoc, "ActiveView", None)
    return view


def get_screenshot(
    doc=None, view="current", width=1024, height=768, fit=True, background="White"
):
    """3D 뷰를 PNG로 캡처한다. 브릿지가 MCP 이미지로 바꿔서 돌려준다."""
    t0 = time.time()
    if not FreeCAD.GuiUp:
        return util.error(
            "GUI가 없어 화면을 캡처할 수 없습니다(FreeCADCmd로 실행 중). "
            "FreeCAD를 GUI로 실행하세요."
        )

    d, err = util.get_doc(doc)
    if err:
        return util.error(err)

    key = str(view or "current").lower()
    if key not in _VIEWS:
        return util.error(
            f"알 수 없는 view '{view}'. 쓸 수 있는 값: {', '.join(sorted(_VIEWS))}"
        )

    try:
        width = max(64, min(int(width), MAX_SIDE))
        height = max(64, min(int(height), MAX_SIDE))
    except Exception:
        return util.error("width/height는 정수여야 합니다.")

    v = _get_view(d.Name)
    if v is None or not hasattr(v, "saveImage"):
        return util.error(
            f"문서 '{d.Name}'의 3D 뷰를 찾을 수 없습니다. "
            "FreeCAD에서 그 문서의 3D 창을 한 번 클릭해 활성화한 뒤 다시 호출하세요."
        )

    warnings = []
    method = _VIEWS[key]
    if method:
        try:
            getattr(v, method)()
        except Exception as e:
            warnings.append(f"뷰 '{key}' 설정 실패({e}). 현재 시점 그대로 찍습니다.")
    if fit:
        try:
            v.fitAll()
        except Exception as e:
            warnings.append(f"fitAll 실패: {e}")

    tmpdir = tempfile.mkdtemp(prefix="cadxray_")
    path = os.path.join(tmpdir, "view.png")
    try:
        try:
            v.saveImage(path, width, height, str(background))
        except Exception as e:
            return util.error(f"saveImage 실패: {e}", exc=e)
        if not os.path.exists(path):
            return util.error("saveImage가 파일을 만들지 않았습니다.")
        with open(path, "rb") as fp:
            raw = fp.read()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    data = {
        "document": d.Name,
        "view": key,
        "width": width,
        "height": height,
        "background": str(background),
        "bytes": len(raw),
        "png_base64": base64.b64encode(raw).decode("ascii"),
    }
    return util.envelope(data, warnings=warnings, t0=t0)


# 이 응답은 base64 PNG라 하드캡(100 KB)을 넘길 수 있다. rpc_server가 자르지 않게 한다.
get_screenshot.no_size_cap = True

TOOLS = {"get_screenshot": get_screenshot}
