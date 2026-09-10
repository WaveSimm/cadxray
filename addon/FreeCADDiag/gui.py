"""워크벤치·명령 정의. InitGui.py가 register()를 부른다.

InitGui.py 안에서 클래스를 정의하면 FreeCAD의 exec 방식 때문에 모듈 수준
이름이 보이지 않는다. 그래서 GUI 코드는 전부 여기(정상적인 모듈)에 둔다.
"""

import FreeCAD
import FreeCADGui

from . import rpc_server, settings


def log(msg):
    FreeCAD.Console.PrintMessage(f"[FreeCAD Diag] {msg}\n")


class DiagStartServer:
    def GetResources(self):
        return {
            "MenuText": "Start Server",
            "ToolTip": f"진단 MCP 서버를 시작한다 (127.0.0.1:{settings.get_port()})",
        }

    def IsActive(self):
        return not rpc_server.is_running()

    def Activated(self):
        rpc_server.start(settings.get_host(), settings.get_port())


class DiagStopServer:
    def GetResources(self):
        return {"MenuText": "Stop Server", "ToolTip": "진단 MCP 서버를 중지한다"}

    def IsActive(self):
        return rpc_server.is_running()

    def Activated(self):
        rpc_server.stop()


class DiagToggleAutoStart:
    def GetResources(self):
        return {
            "MenuText": "Auto Start",
            "ToolTip": "FreeCAD를 켤 때 서버를 자동으로 시작한다",
            "Checkable": settings.get_autostart(),
        }

    def IsActive(self):
        return True

    def Activated(self, index=None):
        new_value = not settings.get_autostart()
        settings.set_autostart(new_value)
        log(f"자동시작 {'켜짐' if new_value else '꺼짐'}")


class FreeCADDiagWorkbench(FreeCADGui.Workbench):
    MenuText = "FreeCAD Diag"
    ToolTip = "FreeCAD 모델 진단용 MCP 서버"

    def Initialize(self):
        FreeCADGui.addCommand("Diag_StartServer", DiagStartServer())
        FreeCADGui.addCommand("Diag_StopServer", DiagStopServer())
        FreeCADGui.addCommand("Diag_ToggleAutoStart", DiagToggleAutoStart())
        cmds = ["Diag_StartServer", "Diag_StopServer", "Diag_ToggleAutoStart"]
        self.appendToolbar("FreeCAD Diag", cmds)
        self.appendMenu("FreeCAD Diag", cmds)

    def Activated(self):
        if rpc_server.is_running():
            host, port = rpc_server.address()
            log(f"서버 실행 중 http://{host}:{port}")
        else:
            log(
                "서버 중지 상태. 메뉴 'FreeCAD Diag > Start Server'로 시작하세요 "
                f"(포트 {settings.get_port()}, 자동시작 "
                f"{'켜짐' if settings.get_autostart() else '꺼짐'})"
            )

    def GetClassName(self):
        return "Gui::PythonWorkbench"


def _autostart():
    if settings.get_autostart() and not rpc_server.is_running():
        rpc_server.start(settings.get_host(), settings.get_port())


def register():
    """워크벤치를 등록하고, 자동시작이 켜져 있으면 지연 시작을 예약한다."""
    FreeCADGui.addWorkbench(FreeCADDiagWorkbench())
    try:
        if settings.get_autostart():
            from PySide import QtCore

            # GUI 로딩이 끝난 뒤에 시작한다.
            QtCore.QTimer.singleShot(3000, _autostart)
    except Exception as e:
        FreeCAD.Console.PrintError(f"[FreeCAD Diag] 자동시작 예약 실패: {e}\n")
