"""메인 스레드 실행기.

FreeCAD 객체는 메인(GUI) 스레드에서만 만질 수 있다. XML-RPC 서버는 별도
스레드에서 돌기 때문에, 요청을 큐에 넣고 QTimer가 메인 스레드에서 꺼내
실행한 뒤 결과를 돌려준다.
"""

import queue
import threading
import traceback

import FreeCAD

_tasks = queue.Queue()
_timer = None
_INTERVAL_MS = 50
_main_ident = None   # start()를 부른 스레드 = 메인 스레드


def submit(fn, *args, timeout=60, **kwargs):
    """RPC 스레드에서 호출한다. 메인 스레드에서 실행한 결과를 기다려 반환."""
    # 이벤트 루프가 없거나(FreeCADCmd) 이미 메인 스레드면 바로 실행한다.
    # 메인 스레드에서 큐에 넣고 기다리면 QTimer가 돌 수 없어 FreeCAD가 멈춘다
    # (예: execute_code 안에서 rpc_server.call을 부르는 경우).
    if not FreeCAD.GuiUp or threading.get_ident() == _main_ident:
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            return {"ok": False, "error": str(e), "traceback": traceback.format_exc()}

    box, done = {}, threading.Event()
    _tasks.put((fn, args, kwargs, box, done))
    if not done.wait(timeout):
        box["abandoned"] = True
        return {
            "ok": False,
            "error": f"timeout after {timeout}s "
                     "(FreeCAD 메인 스레드가 응답하지 않습니다. 실행 중인 작업이 끝나길 기다리거나 FreeCAD를 확인하세요)",
        }
    return box.get("result")


def _pump():
    """QTimer가 메인 스레드에서 주기적으로 호출한다."""
    while True:
        try:
            fn, args, kwargs, box, done = _tasks.get_nowait()
        except queue.Empty:
            return
        if box.get("abandoned"):
            # 호출자가 이미 타임아웃으로 포기한 작업 — 실행하지 않는다.
            continue
        try:
            box["result"] = fn(*args, **kwargs)
        except Exception as e:
            box["result"] = {"ok": False, "error": str(e), "traceback": traceback.format_exc()}
        finally:
            done.set()


def start():
    global _timer, _main_ident
    _main_ident = threading.get_ident()
    if not FreeCAD.GuiUp or _timer is not None:
        return
    from PySide import QtCore

    _timer = QtCore.QTimer()
    _timer.timeout.connect(_pump)
    _timer.start(_INTERVAL_MS)


def stop():
    global _timer
    if _timer is not None:
        _timer.stop()
        _timer = None


def is_running():
    return _timer is not None
