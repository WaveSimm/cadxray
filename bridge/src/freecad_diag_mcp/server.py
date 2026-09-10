"""FreeCAD 진단 MCP 서버 (브릿지).

툴 docstring은 Claude가 읽는 사용설명서다. **언제 부르는지**를 한 줄 넣는다.
"""

from __future__ import annotations

import argparse

from . import client
from ._mcp_compat import Server

mcp = Server("freecad-diag")


@mcp.tool()
def ping() -> str:
    """FreeCAD 연결과 버전을 확인한다. 다른 툴을 쓰기 전에 가장 먼저 호출한다.

    응답의 freecad_version(1.0 / 1.1)에 따라 쓸 수 있는 API가 달라진다.
    """
    return client.call("ping", timeout=15)


@mcp.tool()
def list_documents() -> str:
    """열려 있는 FreeCAD 문서 목록을 반환한다.

    작업 대상 문서를 정할 때, 또는 사용자가 "지금 열린 파일"을 말할 때 호출한다.
    """
    return client.call("list_documents", timeout=30)


@mcp.tool()
def execute_code(code: str, doc: str | None = None, timeout: int = 300) -> str:
    """FreeCAD 안에서 Python 코드를 실행한다. **모델 수정용 탈출구**다.

    진단은 전용 툴(get_document_graph, get_sketch_diagnostics 등)을 먼저 쓴다.
    `_result` 변수에 값을 넣으면 직렬화해서 돌려준다.
    사용 가능한 이름: FreeCAD/App, FreeCADGui/Gui, Part, Sketcher, doc(대상 문서), math, json.

    주의: 코드는 FreeCAD 메인 스레드에서 돌기 때문에 중단할 수 없다.
    무한 루프나 아주 긴 작업을 넣으면 FreeCAD가 멈춘다. 짧게 나눠서 실행할 것.
    """
    return client.call(
        "execute_code",
        {"code": code, "doc": doc, "timeout": timeout},
        timeout=timeout + 15,
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="freecad-diag-mcp")
    parser.add_argument("--host", default=client.default_host())
    parser.add_argument("--port", type=int, default=client.default_port())
    args = parser.parse_args()
    client.configure(args.host, args.port)
    mcp.run()


if __name__ == "__main__":
    main()
