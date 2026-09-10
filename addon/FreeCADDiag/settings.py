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
    return bool(_p().GetBool("AutoStart", False))


def set_autostart(value):
    _p().SetBool("AutoStart", bool(value))
