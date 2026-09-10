"""execute_code — 수정용 탈출구.

메인 스레드에서 exec되므로 무한 루프면 FreeCAD가 멈춘다. 중단할 방법이 없다.
"""

import contextlib
import io
import time
import traceback

import FreeCAD

from . import util


def _namespace(doc):
    ns = {
        "FreeCAD": FreeCAD,
        "App": FreeCAD,
        "doc": doc,
        "math": __import__("math"),
        "json": __import__("json"),
    }
    for mod_name, keys in (
        ("FreeCADGui", ("FreeCADGui", "Gui")),
        ("Part", ("Part",)),
        ("Sketcher", ("Sketcher",)),
        ("PartDesign", ("PartDesign",)),
        ("Draft", ("Draft",)),
        ("Import", ("Import",)),
    ):
        try:
            mod = __import__(mod_name)
        except Exception:
            continue
        for k in keys:
            ns[k] = mod
    return ns


def execute_code(code, doc=None, timeout=300):
    """임의의 Python 코드를 FreeCAD 안에서 실행한다. `_result`에 넣은 값이 반환된다."""
    t0 = time.time()
    if not isinstance(code, str) or not code.strip():
        return util.error("code가 비어 있습니다.")

    target = None
    if doc is not None:
        target, err = util.get_doc(doc)
        if err:
            return util.error(err)
    else:
        target = FreeCAD.ActiveDocument  # 없어도 된다 (문서를 새로 만드는 코드일 수 있음)

    ns = _namespace(target)
    out, err_buf = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err_buf):
            exec(compile(code, "<execute_code>", "exec"), ns, ns)
    except Exception as e:
        return {
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
            "stdout": out.getvalue(),
            "stderr": err_buf.getvalue(),
        }

    result = ns.get("_result", None)
    try:
        result = util.serialize(result)
    except Exception as e:
        result = f"<직렬화 실패: {e}>"

    return util.envelope(
        {"stdout": out.getvalue(), "stderr": err_buf.getvalue(), "result": result},
        t0=t0,
    )
