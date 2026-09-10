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


class DiagSetPort:
    def GetResources(self):
        return {
            "MenuText": "Set Port…",
            "ToolTip": "서버 포트를 바꾼다 (기본 9877). 바꾸면 브릿지 설정도 같이 바꿔야 한다",
        }

    def IsActive(self):
        return True

    def Activated(self):
        from PySide import QtWidgets

        current = settings.get_port()
        value, ok = QtWidgets.QInputDialog.getInt(
            None,
            "FreeCAD Diag",
            "서버 포트 (기본 9877)\n\n"
            "바꾸면 Claude Code의 .mcp.json에도 --port를 같은 값으로 넣어야 합니다.",
            current,
            1024,
            65535,
        )
        if not ok or value == current:
            return
        settings.set_port(value)
        log(f"포트를 {value}로 바꿨습니다.")
        if rpc_server.is_running():
            rpc_server.stop()
            rpc_server.start(settings.get_host(), value)
        else:
            log("Start Server를 누르면 새 포트로 시작합니다.")


class FreeCADDiagWorkbench(FreeCADGui.Workbench):
    MenuText = "FreeCAD Diag"
    ToolTip = "FreeCAD 모델 진단용 MCP 서버"

    def Initialize(self):
        FreeCADGui.addCommand("Diag_StartServer", DiagStartServer())
        FreeCADGui.addCommand("Diag_StopServer", DiagStopServer())
        FreeCADGui.addCommand("Diag_ToggleAutoStart", DiagToggleAutoStart())
        FreeCADGui.addCommand("Diag_SetPort", DiagSetPort())
        cmds = [
            "Diag_StartServer",
            "Diag_StopServer",
            "Diag_ToggleAutoStart",
            "Diag_SetPort",
        ]
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
