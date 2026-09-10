"""FreeCAD 진단 MCP 서버 (브릿지).

툴 docstring은 Claude가 읽는 사용설명서다. **언제 부르는지**를 한 줄 넣는다.
"""

from __future__ import annotations

import argparse
import base64
import json

from . import client
from ._mcp_compat import Image, Server

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


@mcp.tool()
def tracked_recompute(
    doc: str | None = None,
    objects: list[str] | None = None,
    force: bool = False,
) -> str:
    """재계산하고 **무엇이 고쳐졌고 무엇이 새로 깨졌는지**를 돌려준다.

    execute_code로 모델을 고친 **뒤에 반드시 호출**해서 결과를 확인한다.
    - resolved: 이번에 고쳐진 객체
    - new_errors: 이번 수정 때문에 새로 깨진 객체 (status에 원인)
    - persistent: 아직 안 고쳐진 객체
    objects를 주면 그 객체만 재계산한다. 전체를 강제로 다시 계산하려면 force=True.
    """
    return client.call(
        "tracked_recompute",
        {"doc": doc, "objects": objects, "force": force},
        timeout=310,
    )


@mcp.tool()
def get_screenshot(
    doc: str | None = None,
    view: str = "current",
    width: int = 1024,
    height: int = 768,
    fit: bool = True,
    background: str = "White",
):
    """3D 뷰를 PNG로 캡처해 이미지로 돌려준다.

    수정 결과를 눈으로 확인할 때, 또는 사용자가 "지금 어떻게 생겼는지 보여줘"라고 할 때.
    view: current | iso | front | rear | top | bottom | left | right |
          axonometric | dimetric | trimetric
    GUI 없이 실행 중이면(FreeCADCmd) 에러를 돌려준다.
    """
    raw = client.call_raw(
        "get_screenshot",
        {
            "doc": doc,
            "view": view,
            "width": width,
            "height": height,
            "fit": fit,
            "background": background,
        },
        timeout=120,
    )
    if not raw.get("ok"):
        return json.dumps(raw, ensure_ascii=False, indent=2)
    try:
        png = base64.b64decode(raw["data"]["png_base64"])
    except Exception as e:
        return json.dumps(
            {"ok": False, "error": f"PNG 디코딩 실패: {e}"}, ensure_ascii=False
        )
    return Image(data=png, format="png")


@mcp.tool()
def import_step(
    path: str,
    doc: str | None = None,
    merge: bool = False,
    use_link_group: bool = False,
    import_hidden: bool = False,
    mode: int = 0,
    max_objects: int = 100,
) -> str:
    """STEP/IGES 파일을 문서에 넣고 생긴 객체(부품·솔리드)를 요약한다.

    사용자가 벤더 STEP을 분석해 달라고 할 때 첫 호출. doc이 없으면 새 문서를 만든다.
    가져온 뒤 get_document_graph → analyze_shape(bop_check=True) → find_holes /
    check_interference / get_mass_properties 순으로 본다.
    merge=True면 솔리드가 하나로 합쳐져 간섭 검사·구멍 검출이 어려워진다 — 기본값(False) 권장.
    STL/OBJ 같은 메시 파일은 받지 않는다(면·솔리드가 없어 분석 불가).
    """
    return client.call(
        "import_step",
        {
            "path": path,
            "doc": doc,
            "merge": merge,
            "use_link_group": use_link_group,
            "import_hidden": import_hidden,
            "mode": mode,
            "max_objects": max_objects,
        },
        timeout=310,
    )


@mcp.tool()
def find_holes(
    name: str,
    doc: str | None = None,
    min_radius: float = 0.5,
    max_radius: float = 50.0,
    max_holes: int = 100,
    group_tolerance: float = 0.01,
) -> str:
    """원통면에서 **구멍**의 직경·중심·축·깊이·관통 여부를 뽑는다. 마운팅 홀 패턴 확인용.

    patterns에 같은 직경끼리 개수·중심·최소 피치가 묶여 온다.
    through는 휴리스틱이다(구멍 양 끝 바깥이 재료 밖인지). 보스·축 같은 볼록 원통은 제외한다.
    """
    return client.call(
        "find_holes",
        {
            "name": name,
            "doc": doc,
            "min_radius": min_radius,
            "max_radius": max_radius,
            "max_holes": max_holes,
            "group_tolerance": group_tolerance,
        },
        timeout=130,
    )


@mcp.tool()
def check_interference(
    names: list[str],
    doc: str | None = None,
    clearance: float = 0.0,
    volume_tolerance: float = 1e-6,
    max_pairs: int = 50,
) -> str:
    """부품 쌍마다 최소 거리와 **간섭 부피(mm³)**를 잰다.

    names에 객체 2개 이상, 또는 App::Part 하나(안의 부품을 전부 쌍으로 푼다).
    status: interference(겹침) / clearance_violation(거리 < clearance) / ok.
    큰 어셈블리는 쌍 수가 폭발하므로 max_pairs로 제한된다.
    """
    return client.call(
        "check_interference",
        {
            "names": names,
            "doc": doc,
            "clearance": clearance,
            "volume_tolerance": volume_tolerance,
            "max_pairs": max_pairs,
        },
        timeout=130,
    )


@mcp.tool()
def get_mass_properties(
    name: str,
    doc: str | None = None,
    density: float | None = None,
) -> str:
    """부피(mm³)·표면적·무게중심·관성 행렬. density(g/cm³)를 주면 질량(g)도 계산한다.

    예: 알루미늄 2.7, 강 7.85, 스테인리스 7.9, ABS 1.04, PLA 1.24.
    """
    return client.call(
        "get_mass_properties",
        {"name": name, "doc": doc, "density": density},
        timeout=60,
    )


@mcp.tool()
def reload_handlers() -> str:
    """FreeCAD를 재시작하지 않고 애드온 핸들러 코드를 다시 읽는다. **개발용.**

    애드온의 handlers/*.py를 고친 뒤 호출한다. 새로 추가한 핸들러 파일도 집어 올린다.
    InitGui.py·rpc_server.py·handlers/__init__.py를 고쳤을 때는 FreeCAD 재시작이 필요하다.
    """
    return client.call("reload_handlers", timeout=60)


def main() -> None:
    parser = argparse.ArgumentParser(prog="freecad-diag-mcp")
    parser.add_argument("--host", default=client.default_host())
    parser.add_argument("--port", type=int, default=client.default_port())
    args = parser.parse_args()
    client.configure(args.host, args.port)
    mcp.run()


if __name__ == "__main__":
    main()
