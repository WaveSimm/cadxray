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
def get_document_graph(
    doc: str | None = None,
    max_objects: int = 200,
    type_filter: str | None = None,
    label_pattern: str | None = None,
    include_sketch_summary: bool = True,
) -> str:
    """문서의 객체 트리·의존관계·문제 객체를 한 번에 본다. **진단의 첫 호출.**

    사용자가 "모델 구조 파악해줘", "뭐가 빨간지 봐줘"라고 하면 이것부터 부른다.
    응답의 invalid_objects에 나온 객체를 inspect_object / get_sketch_diagnostics로 파고든다.

    summary와 invalid_objects는 잘려도 **항상 전체 기준**이다.
    객체가 많으면 type_filter(예: "Sketcher::SketchObject")나 label_pattern(정규식)으로 좁힌다.
    """
    return client.call(
        "get_document_graph",
        {
            "doc": doc,
            "max_objects": max_objects,
            "type_filter": type_filter,
            "label_pattern": label_pattern,
            "include_sketch_summary": include_sketch_summary,
        },
        timeout=60,
    )


@mcp.tool()
def inspect_object(
    doc: str | None = None,
    name: str = "",
    include_shape: bool = True,
    max_list: int = 20,
) -> str:
    """객체 하나의 모든 프로퍼티·수식(ExpressionEngine)·형상 요약·의존관계를 본다.

    get_document_graph에서 문제 객체를 찾은 뒤, 그 객체의 값이 왜 그런지 볼 때 호출한다.
    name은 Name(예: "Pad001") 우선, 없으면 Label로도 찾는다.
    """
    return client.call(
        "inspect_object",
        {"doc": doc, "name": name, "include_shape": include_shape, "max_list": max_list},
        timeout=60,
    )


@mcp.tool()
def get_sketch_diagnostics(
    doc: str | None = None,
    sketch: str = "",
    include_geometry: bool = True,
    include_constraints: bool = True,
    max_items: int = 200,
) -> str:
    """스케치가 **왜 빨간지**를 한 번에 알려준다. 스케치 문제면 이것 하나로 끝난다.

    읽는 순서:
    1. solve_status가 0이 아니면 → conflicting / redundant / malformed 목록을 본다.
       그 번호(id)는 GUI 제약 패널의 번호와 같다. constraints 목록에는 잘려도 항상 들어 있다.
    2. solve_status가 0인데 dof > 0이면 → 구속이 모자란 것이다.
    3. open_vertices가 비어 있지 않으면 → 와이어가 닫히지 않은 것이다.
       이 스케치를 쓰는 Pad/Pocket이 "Wire is not closed."로 실패한다.

    주의: solve_status가 0이 아니면 fully_constrained는 신뢰할 수 없어 null로 온다.
    이 툴은 진단 전에 solve()를 호출한다(문서를 저장하지는 않는다).
    """
    return client.call(
        "get_sketch_diagnostics",
        {
            "doc": doc,
            "sketch": sketch,
            "include_geometry": include_geometry,
            "include_constraints": include_constraints,
            "max_items": max_items,
        },
        timeout=60,
    )


@mcp.tool()
def analyze_shape(
    doc: str | None = None,
    name: str = "",
    max_faces: int = 30,
    max_edges: int = 30,
    bop_check: bool = False,
) -> str:
    """형상의 유효성·부피·면/모서리 구성을 본다. **형상이 왜 이상한가**를 볼 때.

    check_message가 채워져 있으면 형상 자체가 깨진 것이다(자기교차 등).
    PartDesign 피처면 feature_own_shape에 그 피처 자체 형상도 같이 온다
    (Shape는 Body 누적 형상이라 피처만의 결과와 다르다).
    bop_check=True는 정밀하지만 큰 형상에서 느리다.
    """
    return client.call(
        "analyze_shape",
        {
            "doc": doc,
            "name": name,
            "max_faces": max_faces,
            "max_edges": max_edges,
            "bop_check": bop_check,
        },
        timeout=120,
    )


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
