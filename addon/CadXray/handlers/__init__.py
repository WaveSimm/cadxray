"""핸들러 레지스트리.

각 핸들러 모듈이 자기 툴을 `TOOLS = {"이름": 함수}`로 선언한다. 이 파일은 그것을
모아 올리기만 한다 — 새 핸들러 파일을 추가할 때 여기를 고칠 필요가 없고,
`reload_handlers`가 FreeCAD 재시작 없이 새 파일을 집어 올린다.
(RPC 메서드는 `call` 하나뿐 — 명세 6.2)
"""

import importlib
import pkgutil

# util은 나머지가 쓰므로 항상 먼저. 그 밖의 순서는 상관없다.
_FIRST = ["util"]

# REGISTRY는 rpc_server가 같은 dict 객체를 들고 있다.
# 절대 새 dict로 갈아 끼우지 말고 clear/update로만 바꾼다.
REGISTRY = {}


def _discover_modules():
    """패키지 안의 핸들러 모듈 이름. util을 맨 앞에 둔다."""
    found = [m.name for m in pkgutil.iter_modules(__path__)]
    ordered = [n for n in _FIRST if n in found]
    ordered += [n for n in found if n not in ordered]
    return ordered


def _build():
    """각 모듈의 TOOLS를 모아 REGISTRY를 제자리에서 다시 채운다."""
    collected = {"reload_handlers": reload_handlers}
    conflicts = []
    for name in _discover_modules():
        mod = importlib.import_module(f"{__name__}.{name}")
        for tool, fn in getattr(mod, "TOOLS", {}).items():
            if tool in collected and tool != "reload_handlers":
                conflicts.append(tool)
            collected[tool] = fn
    REGISTRY.clear()
    REGISTRY.update(collected)
    return conflicts


def reload_handlers():
    """FreeCAD 재시작 없이 핸들러 코드를 다시 읽는다 (개발용).

    새로 추가한 핸들러 파일도 집어 올린다. `InitGui.py`·`rpc_server.py`·
    이 파일 자체를 고쳤을 때만 FreeCAD 재시작이 필요하다.
    """
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

    warnings = [
        "reload_handlers는 개발용입니다. InitGui.py·rpc_server.py·handlers/__init__.py "
        "변경은 FreeCAD 재시작이 필요합니다."
    ]
    try:
        conflicts = _build()
        if conflicts:
            warnings.append(f"툴 이름이 겹칩니다(뒤에 읽은 모듈이 이깁니다): {', '.join(conflicts)}")
    except Exception as e:
        failed.append({"module": "__init__._build", "error": str(e)})

    return util.envelope(
        {"reloaded": reloaded, "failed": failed, "tools": sorted(REGISTRY.keys())},
        warnings=warnings,
        t0=t0,
    )


_build()
