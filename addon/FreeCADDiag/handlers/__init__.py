"""핸들러 레지스트리.

툴 이름 → 함수. 새 툴을 추가할 때 여기에만 등록하면 RPC/브릿지 양쪽이
자동으로 알게 된다 (RPC 메서드는 `call` 하나뿐 — 명세 6.2).
"""

import importlib

# reload_handlers가 다시 읽을 모듈들. 새 핸들러 모듈을 추가하면 여기에도 넣는다.
_HANDLER_MODULES = [
    "util",
    "documents",
    "execute",
]

REGISTRY = {}


def _build():
    from . import documents, execute

    REGISTRY.clear()
    REGISTRY.update(
        {
            "ping": documents.ping,
            "list_documents": documents.list_documents,
            "execute_code": execute.execute_code,
            "reload_handlers": reload_handlers,
        }
    )


def reload_handlers():
    """FreeCAD 재시작 없이 핸들러 코드를 다시 읽는다 (개발용)."""
    import time

    from . import util

    t0 = time.time()
    reloaded, failed = [], []
    for name in _HANDLER_MODULES:
        try:
            mod = importlib.import_module(f"{__name__}.{name}")
            importlib.reload(mod)
            reloaded.append(name)
        except Exception as e:
            failed.append({"module": name, "error": str(e)})
    _build()
    return util.envelope(
        {"reloaded": reloaded, "failed": failed, "tools": sorted(REGISTRY.keys())},
        warnings=["reload_handlers는 개발용입니다. InitGui.py·rpc_server.py 변경은 FreeCAD 재시작이 필요합니다."],
        t0=t0,
    )


_build()
