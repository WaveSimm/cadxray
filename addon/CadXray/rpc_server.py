"""XML-RPC 서버 (127.0.0.1:9877).

메서드는 하나뿐이다: call(tool_name, params_json) -> json_string
툴을 추가해도 RPC 계층은 손대지 않는다 (명세 6.2).
"""

import inspect
import json
import threading
import traceback
from xmlrpc.server import SimpleXMLRPCServer

import FreeCAD

from . import main_thread
from .handlers import REGISTRY
from .handlers import util

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9877

_server = None
_thread = None
_bound = (None, None)

# 툴별 메인 스레드 대기 시간(초). 없으면 기본값.
_DEFAULT_TIMEOUT = 60


def _timeout_for(tool, params):
    if tool == "execute_code":
        try:
            return int(params.get("timeout", 300)) + 10
        except Exception:
            return 310
    if tool == "analyze_shape":
        # bop_check=True는 큰 형상에서 오래 걸린다 [api-notes 12장]
        return 120 if params.get("bop_check") else _DEFAULT_TIMEOUT
    if tool in ("tracked_recompute", "import_step"):
        # 큰 문서의 전체 재계산·큰 STEP 가져오기는 오래 걸릴 수 있다
        return 300
    if tool in ("find_holes", "check_interference"):
        # 수백 면 어셈블리 — common()이 느리다 [api-notes 12장]
        return 120
    if tool in ("classify_faces", "section_profile", "compare_shapes", "align_shapes"):
        # 면 표본 추출·3D fuse·퍼지 불리언 (M7)
        return 120
    if tool == "build_features":
        # 피처마다 recompute — 피처 수에 비례
        return 300
    return _DEFAULT_TIMEOUT


def _dump(obj, capped=True):
    text = json.dumps(obj, ensure_ascii=False, default=str)
    if capped and len(text.encode("utf-8")) > util.HARD_CAP_BYTES:
        return json.dumps(
            {
                "ok": False,
                "error": f"응답이 하드캡({util.HARD_CAP_BYTES // 1024} KB)을 넘었습니다. "
                         "max_* 파라미터를 줄여서 다시 호출하세요.",
                "size_bytes": len(text.encode("utf-8")),
            },
            ensure_ascii=False,
        )
    return text


def call(tool_name, params_json="{}"):
    """브릿지가 부르는 유일한 RPC 메서드. 항상 JSON 문자열을 돌려준다."""
    try:
        params = json.loads(params_json) if params_json else {}
        if not isinstance(params, dict):
            return _dump(util.error("params_json은 JSON 객체여야 합니다."))
    except Exception as e:
        return _dump(util.error(f"params_json 파싱 실패: {e}"))

    fn = REGISTRY.get(tool_name)
    if fn is None:
        return _dump(
            util.error(f"알 수 없는 툴 '{tool_name}'. 사용 가능: {', '.join(sorted(REGISTRY))}")
        )

    # 인자 검증을 먼저 한다 — 메인 스레드에 넘기기 전에 친절한 메시지를 주기 위함.
    try:
        inspect.signature(fn).bind(**params)
    except TypeError as e:
        return _dump(util.error(f"'{tool_name}' 인자 오류: {e}"))

    # params를 클로저로 넘긴다. submit의 `timeout` 인자와 툴 인자 이름이
    # 겹치는 경우(execute_code의 timeout)를 피하기 위함이다.
    try:
        result = main_thread.submit(
            lambda: fn(**params), timeout=_timeout_for(tool_name, params)
        )
    except TypeError as e:
        return _dump(util.error(f"'{tool_name}' 인자 오류: {e}"))
    except Exception as e:
        return _dump(util.error(f"'{tool_name}' 실행 실패: {e}", exc=e))

    if not isinstance(result, dict):
        result = util.envelope(result)
    # get_screenshot처럼 base64를 담는 툴은 하드캡에서 제외한다(핸들러가 선언).
    return _dump(result, capped=not getattr(fn, "no_size_cap", False))


def list_tools():
    return json.dumps(sorted(REGISTRY.keys()))


def is_running():
    return _server is not None


def address():
    return _bound


def start(host=DEFAULT_HOST, port=DEFAULT_PORT):
    global _server, _thread, _bound
    if _server is not None:
        FreeCAD.Console.PrintMessage(
            f"[CAD X-ray] 이미 실행 중입니다 ({_bound[0]}:{_bound[1]})\n"
        )
        return True

    try:
        _server = SimpleXMLRPCServer(
            (host, port), allow_none=True, logRequests=False
        )
    except OSError as e:
        _server = None
        FreeCAD.Console.PrintError(
            f"[CAD X-ray] 포트 {port}을 열 수 없습니다: {e}\n"
            "  다른 프로그램이 쓰고 있거나 서버가 이미 떠 있습니다.\n"
        )
        return False

    _server.register_function(call, "call")
    _server.register_function(list_tools, "list_tools")
    _server.register_introspection_functions()

    main_thread.start()
    _thread = threading.Thread(target=_server.serve_forever, name="CadXrayRPC", daemon=True)
    _thread.start()
    _bound = (host, port)
    FreeCAD.Console.PrintMessage(
        f"[CAD X-ray] 서버 시작 http://{host}:{port}  (툴 {len(REGISTRY)}개)\n"
    )
    return True


def stop():
    global _server, _thread, _bound
    if _server is None:
        FreeCAD.Console.PrintMessage("[CAD X-ray] 서버가 실행 중이 아닙니다\n")
        return False
    try:
        _server.shutdown()
        _server.server_close()
    except Exception:
        FreeCAD.Console.PrintError(f"[CAD X-ray] 종료 중 오류\n{traceback.format_exc()}")
    _server = None
    _thread = None
    _bound = (None, None)
    main_thread.stop()
    FreeCAD.Console.PrintMessage("[CAD X-ray] 서버 중지\n")
    return True
