"""핸들러 레지스트리.

툴 이름 → 함수. 새 툴을 추가할 때 여기에만 등록하면 RPC/브릿지 양쪽이
자동으로 알게 된다 (RPC 메서드는 `call` 하나뿐 — 명세 6.2).
"""

import importlib
import pkgutil

# reload_handlers가 다시 읽을 모듈들. util이 먼저여야 한다(나머지가 util을 쓴다).
# 파일을 새로 추가해도 pkgutil이 찾아내므로 여기 손댈 필요는 없다.
_HANDLER_MODULES = ["util", "documents", "structure", "execute"]


def _discover_modules():
    """패키지 안의 핸들러 모듈 이름. util을 맨 앞에 둔다."""
    found = [m.name for m in pkgutil.iter_modules(__path__)]
    ordered = [n for n in _HANDLER_MODULES if n in found]
    ordered += [n for n in found if n not in ordered]
    return ordered

REGISTRY = {}


def _build():
    from . import documents, execute, structure

    REGISTRY.clear()
    REGISTRY.update(
        {
            "ping": documents.ping,
            "list_documents": documents.list_documents,
            "get_document_graph": structure.get_document_graph,
            "inspect_object": structure.inspect_object,
            "analyze_shape": structure.analyze_shape,
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
    for name in _discover_modules():
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
