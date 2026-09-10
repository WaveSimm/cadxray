"""애드온 설정 — FreeCAD 파라미터에 저장한다.

경로: User parameter:BaseApp/Preferences/Mod/FreeCADDiag
"""

import FreeCAD

PARAM_PATH = "User parameter:BaseApp/Preferences/Mod/FreeCADDiag"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9877


def _p():
    return FreeCAD.ParamGet(PARAM_PATH)


def get_port():
    return int(_p().GetInt("Port", DEFAULT_PORT))


def set_port(port):
    _p().SetInt("Port", int(port))


def get_host():
    return _p().GetString("Host", DEFAULT_HOST) or DEFAULT_HOST


def get_autostart():
    # 기본 켜짐: 설치하면 FreeCAD를 켤 때 서버가 같이 뜬다 (127.0.0.1 전용이라 외부 노출 없음).
    # 사용자가 메뉴에서 끄면 그 값이 저장돼 유지된다.
    return bool(_p().GetBool("AutoStart", True))


def set_autostart(value):
    _p().SetBool("AutoStart", bool(value))
