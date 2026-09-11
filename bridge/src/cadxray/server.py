"""FreeCAD 진단 MCP 서버 (브릿지).

툴 docstring은 Claude가 읽는 사용설명서다. **언제 부르는지**를 한 줄 넣는다.
"""

from __future__ import annotations

import argparse
import base64
import json

from . import client
from ._mcp_compat import Image, Server

mcp = Server("cadxray")


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
    include_ok: bool = False,
) -> str:
    """부품 쌍마다 최소 거리와 **간섭 부피(mm³)**를 잰다.

    names에 객체 2개 이상, 또는 App::Part 하나(안의 부품을 전부 쌍으로 푼다).
    status: interference(겹침) / clearance_violation(거리 < clearance) / ok.
    기본으로 문제 있는 쌍만 pairs에 담는다(ok는 summary 숫자로만). 전부 보려면 include_ok=True.
    큰 어셈블리는 쌍 수가 폭발하므로(80부품 = 3,160쌍) max_pairs로 제한된다. 쌍당 1~20 ms.
    """
    return client.call(
        "check_interference",
        {
            "names": names,
            "doc": doc,
            "clearance": clearance,
            "volume_tolerance": volume_tolerance,
            "max_pairs": max_pairs,
            "include_ok": include_ok,
        },
        timeout=310,
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
def classify_faces(
    name: str,
    doc: str | None = None,
    samples: int = 5,
    tolerance: float = 1e-3,
    max_faces: int = 200,
    include_analytic: bool = True,
) -> str:
    """면마다 **정체**(plane/cylinder/cone/sphere/torus/free_form)를 판정한다. STEP을 파라메트릭으로 다시 만들기 전 첫 호출.

    BSpline 면도 표본을 찍어 원통·원뿔·평면인지 맞춰 본다(가짜 자유곡면 판별). rebuild에
    verdict(prismatic/mixed/free_form), main_axis, levels(주축에 수직인 평면 높이 = 띠 경계),
    radii(주축 방향 원통 반지름)가 온다. levels 사이 높이로 section_profile을 부른다.
    free_form 면적이 크면 BaseFeature 하이브리드로 간다.
    """
    return client.call(
        "classify_faces",
        {"name": name, "doc": doc, "samples": samples, "tolerance": tolerance,
         "max_faces": max_faces, "include_analytic": include_analytic},
        timeout=130,
    )


@mcp.tool()
def section_profile(
    name: str,
    doc: str | None = None,
    axis: str = "Z",
    position: float | None = None,
    fill_holes: bool = True,
    max_fill_radius: float = 10.0,
    tolerance: float = 1e-5,
    samples: int = 24,
    max_elements: int = 300,
) -> str:
    """축 방향 위치의 **단면 윤곽**을 스케치용 선분·호·원 목록으로 준다.

    position=None이면 후보 높이(levels, vertex_positions)만 준다 — 띠의 중간 높이를 고른 뒤 다시 부른다.
    fill_holes=True(기본)는 구멍·카운터보어·챔퍼 자리를 3D에서 메운 뒤 자르므로 바깥 윤곽만 나온다.
    포켓 안쪽 윤곽이 필요하면 False. 좌표는 sketch_plane의 로컬 2D(XY: X,Y / XZ: X,Z / YZ: Y,Z).
    build_features의 profile.section을 쓰면 이 좌표를 다시 보낼 필요가 없다.
    name이 Mesh::Feature(STL)면 메시 단면 폴리라인을 직선·원호·원으로 피팅한다(fit_tolerance는 메시 편차보다 크게, 기본 0.05).
    """
    return client.call(
        "section_profile",
        {"name": name, "doc": doc, "axis": axis, "position": position, "fill_holes": fill_holes,
         "max_fill_radius": max_fill_radius, "tolerance": tolerance, "samples": samples,
         "max_elements": max_elements},
        timeout=130,
    )


@mcp.tool()
def build_features(
    body: str,
    features: list[dict],
    doc: str | None = None,
    params: dict | None = None,
    create_body: bool = True,
    stop_on_error: bool = True,
) -> str:
    """스케치 + Pad/Pocket/Groove/Revolution/Fillet/Chamfer 목록을 Body에 **순서대로 쌓는다**. 피처마다 재계산·검증.

    각 피처: {"op": "pad", "name": "PadBand1", "plane": "XY", "position": 53.68 (그 평면의 전역 좌표: XY→z, XZ→y, YZ→x),
             "profile": {...}, "length": 8.0 | "Params.h"}
    profile: {"section": {"of": "2B2", "doc": "Unnamed", "position": 55.0, "fill_holes": true}}  ← 좌표를 안 보내도 된다
             | {"elements": [...]} (section_profile 출력) | {"wires": [[...], ...]}
             | {"circles": [{"center": [y, z], "diameter": 3.4, "expr": "Params.hole_d", "name": "hole_d"}]}
             | {"polygon": [[x, y], ...]} | {"rect": {"center": [x, y], "width": w, "height": h}}
    pocket: "through": true 또는 "length"; "reversed": true 로 방향 반전(YZ 평면은 −X로 판다).
    groove/revolution: "axis": {"x": v} 또는 {"y": v} (스케치 로컬), "angle": 360. 프로파일은 축 한쪽에만.
helix(나사·나선 홈, 축 Z): {"op":"helix","profile":{"polygon":[[r,z],...]},"axis_center":[cx,cy],"pitch":2,"height":10,"subtractive":true,"left_handed":false}.
       나선은 프로파일 각도 0°에서 시작하므로 한 피치 아래에서 시작하고 아래를 Pad로 되메운다.
    fillet/chamfer: "size", "edges": ["Edge3", ...] 또는 {"curve": "Circle", "radius": 1.7, "center": [x, null, null]}.
    params={"h": 16}는 Spreadsheet 'Params' 별칭으로 기록되어 수식에서 Params.h로 쓴다.
    떨어진 Pad는 한 Body에 못 넣는다 → 겹치게 순서대로. 실패하면 stopped_at과 status에 원인.
    """
    return client.call(
        "build_features",
        {"body": body, "doc": doc, "features": features, "params": params,
         "create_body": create_body, "stop_on_error": stop_on_error},
        timeout=310,
    )


@mcp.tool()
def compare_shapes(
    a: str,
    b: str,
    doc: str | None = None,
    doc_b: str | None = None,
    fuzzy: float = 1e-4,
    min_piece_volume: float = 1e-3,
    max_pieces: int = 10,
) -> str:
    """두 형상이 **얼마나, 어디가** 다른지. 재구성 검증의 마지막 호출.

    부피·면적·bbox 차와 퍼지 차집합 조각(missing_in_b: 원본에만 있음 / extra_in_b: 새 모델에만 있음)의
    bbox·중심을 준다 — 틀린 곳을 바로 짚는다. verdict: identical(< 0.001 %) / match(< 0.1 %) / different.
    b가 다른 문서면 doc_b. bbox 중심이 어긋나면 Body.Placement 경고.
    a 또는 b가 Mesh::Feature(STL)면 불리언 없이 법선 광선 편차(deviation/reverse_deviation, worst 점)로 비교한다.
    """
    return client.call(
        "compare_shapes",
        {"a": a, "b": b, "doc": doc, "doc_b": doc_b, "fuzzy": fuzzy,
         "min_piece_volume": min_piece_volume, "max_pieces": max_pieces},
        timeout=130,
    )


@mcp.tool()
def align_shapes(
    a: str,
    b: str,
    doc: str | None = None,
    doc_b: str | None = None,
    fuzzy: float = 1e-4,
) -> str:
    """같은 부품의 두 인스턴스 a, b 사이의 **강체 변환**(b = T·a)을 형상에서 찾는다.

    STEP 어셈블리의 Placement는 하위 어셈블리 프레임이라 인스턴스 위치가 아니다. 재구성한 Body를
    여러 자리에 App::Link로 놓을 때 이 툴의 matrix/placement를 Link.Placement에 넣는다.
    관성 주축을 맞춘 뒤 정점·면 위 점이 b 표면에 얼마나 붙는지로 검증한다(match_pct).
    mirrored=true면 거울상이라 Link로는 안 되고 Part::Mirroring 본을 만들어 다시 정렬한다.
    """
    return client.call(
        "align_shapes",
        {"a": a, "b": b, "doc": doc, "doc_b": doc_b, "fuzzy": fuzzy},
        timeout=130,
    )


@mcp.tool()
def make_drawing(
    source: str | list[str],
    doc: str | None = None,
    page: str = "Page",
    template: str | None = None,
    scale: float | None = None,
    views: list | None = None,
    dimensions: list[dict] | None = None,
    notes: list | None = None,
    title: dict | None = None,
    export: str = "pdf",
    out_dir: str | None = None,
    vertex_tolerance: float = 0.05,
    wait_seconds: int = 60,
    line_width: float = 0.35,
    smooth_edges: bool = True,
    avoid_overlap: bool = True,
) -> str:
    """3D 객체로 **TechDraw 2D 도면 페이지**를 만들고 PDF/SVG로 내보낸다 (M8).

    source: Body·Part 이름, 또는 이름 목록/그룹(Link 어셈블리는 자동으로 Part::Compound로 묶는다).
    views: ["front","right","top"](기본) + "iso"/"left"/"rear"/"bottom", 또는 {"type":"front","x":..,"y":..,"scale":..},
           상세는 {"detail": {"base":"front","at":[x,y,z],"radius":20,"scale":0.2,"ref":"A"}}.
    scale: None이면 페이지의 60 %에 맞는 표준 축척 자동. template: 기본 ISO/A3_Landscape_TD.svg(표제란 있음).
    dimensions: [{"view":"front","type":"DistanceX|DistanceY|Distance","from":[x,y,z],"to":[x,y,z],"offset":[dx,dy],"label":"W"},
                 {"view":"top","type":"Diameter","center":[x,y,z],"radius":3},
                 {"view":"front","type":"DistanceX","edges":{"axis":"x","at":[x1,x2]}}]  ← 정점이 없는 실루엣 사이 거리.
    from/to는 모델 정점 좌표(vertex_tolerance 안에서 찾는다). 값은 모델에서 재므로 도면 값 = 모델 값.
    notes: 문자열 목록(주석 한 덩어리) 또는 [{"text":[...],"x":..,"y":..,"size":2.5}].
    title: {"title":..,"subtitle":..,"author":..,"date":..,"scale":..,"number":..,"sheet":..} (템플릿 칸 이름도 됨).
    export: "pdf"|"svg"|"both"|"none". GUI가 없으면 내보내기는 건너뛴다. 배치는 기본값이고 세밀한 위치는 GUI에서 옮긴다.
    line_width: 화면·출력 선 굵기 mm(기본 0.35; FreeCAD 기본 0.7은 화면에서 뭉쳐 보인다). smooth_edges=False면 곡면 경계선(나사 등) 숨김.
    avoid_overlap(기본 True): 치수 글자가 뷰 이름·다른 치수와 겹치면 바깥으로 밀어낸다(offset을 준 것도 겹치면 민다).
    """
    return client.call(
        "make_drawing",
        {"source": source, "doc": doc, "page": page, "template": template, "scale": scale, "views": views,
         "dimensions": dimensions, "notes": notes, "title": title, "export": export, "out_dir": out_dir,
         "vertex_tolerance": vertex_tolerance, "wait_seconds": wait_seconds, "line_width": line_width, "smooth_edges": smooth_edges, "avoid_overlap": avoid_overlap},
        timeout=310,
    )


@mcp.tool()
def inspect_drawing(page: str | None = None, doc: str | None = None) -> str:
    """TechDraw 페이지의 뷰·치수(값)·주석·표제란을 읽는다 (M8). page를 비우면 문서의 유일한 페이지.

    치수 value는 모델에서 잰 값. status가 Invalid면 참조가 깨진 치수, 뷰의 edges가 0이면 소스가 빈 뷰다.
    """
    return client.call("inspect_drawing", {"page": page, "doc": doc}, timeout=70)


@mcp.tool()
def open_document(path: str) -> str:
    """FCStd 파일을 연다(이미 열려 있으면 그 문서를 알려준다). STEP은 import_step, STL은 import_mesh로. (M9)"""
    return client.call("open_document", {"path": path}, timeout=190)


@mcp.tool()
def save_document(doc: str | None = None, path: str | None = None, overwrite: bool = False) -> str:
    """문서를 저장한다 (M9). path 없으면 원래 파일에 덮어쓰고(새 문서면 오류), 있으면 그 경로로 saveAs.

    다른 기존 파일을 덮어쓸 때만 overwrite=true. 사용자가 저장하라고 하기 전에는 부르지 않는다.
    """
    return client.call("save_document", {"doc": doc, "path": path, "overwrite": overwrite}, timeout=190)


@mcp.tool()
def import_mesh(path: str, doc: str | None = None, transparency: int = 70, label: str | None = None) -> str:
    """STL/OBJ/PLY/3MF 메시를 **참고용 Mesh 객체**로 읽는다 (M9). 변환하지 않고 투명하게 띄운다.

    is_solid가 false면 부피·비교를 믿지 말 것. 그다음 analyze_mesh → section_profile(메시 이름) → build_features →
    compare_shapes(메시, Body) 순서로 다시 그린다 (CLAUDE.md "STL → 파라메트릭").
    """
    return client.call("import_mesh", {"path": path, "doc": doc, "transparency": transparency, "label": label}, timeout=190)


@mcp.tool()
def analyze_mesh(
    name: str,
    doc: str | None = None,
    axis: str | None = None,
    fit_tolerance: float = 0.05,
    detect_thread: bool = True,
) -> str:
    """메시의 **주축·레벨(띠 경계)·띠별 단면 원·공통 중심·나사**를 한 번에 (M9). classify_faces의 메시판.

    levels: 주축에 수직인 평면의 위치(면 개수만). bands: 레벨 사이 중간 높이 단면 — 원이면 center·r, 아니면 요소 수.
    center: 단면 원들의 공통 중심(회전체 계열). thread: {pitch, major_r, minor_r, z_from, z_to, handedness} — helix op로 만든다.
    verdict: revolved / prismatic / mixed. 축이 틀리면 axis="X|Y|Z"로.
    """
    return client.call("analyze_mesh", {"name": name, "doc": doc, "axis": axis, "fit_tolerance": fit_tolerance, "detect_thread": detect_thread}, timeout=190)


@mcp.tool()
def suggest_sketch_fixes(
    sketch: str,
    doc: str | None = None,
    coincident_tolerance: float = 0.05,
    angle_tolerance: float = 0.5,
    equal_tolerance: float = 0.01,
    max_gap: float = 5.0,
    evaluate: bool = True,
) -> str:
    """스케치 문제마다 **고칠 후보**를 만든다 (M10). 자동으로 고치지 않는다 — 사용자에게 번호 목록으로 보여 주고 고르게 한다.

    후보 kind: add_coincident(가까운/열린 끝점 잇기), add_horizontal/add_vertical(거의 수평·수직인 선), add_equal(같은 길이·반지름),
    delete_constraint(중복·잘못된·충돌 제약 삭제; 충돌은 exclusive_with로 묶여 하나만 고른다), add_dimension(남은 자유도 → 현재 값 치수, low).
    effect: 사본에 적용해 본 solve 결과(dof·상태). recommended: 효과가 좋고 low가 아닌 것. 적용은 apply_sketch_fixes(ids, fingerprint).
    """
    return client.call("suggest_sketch_fixes", {"sketch": sketch, "doc": doc, "coincident_tolerance": coincident_tolerance, "angle_tolerance": angle_tolerance,
                                                "equal_tolerance": equal_tolerance, "max_gap": max_gap, "evaluate": evaluate}, timeout=190)


@mcp.tool()
def apply_sketch_fixes(
    sketch: str,
    ids: list[int],
    doc: str | None = None,
    fingerprint: str | None = None,
    coincident_tolerance: float = 0.05,
    angle_tolerance: float = 0.5,
    equal_tolerance: float = 0.01,
    max_gap: float = 5.0,
) -> str:
    """suggest_sketch_fixes의 후보 중 **사용자가 고른 id**만 적용한다 (M10). 같은 허용값을 넘겨야 id가 맞는다.

    fingerprint가 다르면(그사이 스케치가 바뀜) 오류. 적용 뒤 상태가 나빠지면 되돌리고 오류. 결과의 after(solve·dof·open_vertices)와
    recompute.invalid_objects를 보고한다.
    """
    return client.call("apply_sketch_fixes", {"sketch": sketch, "ids": ids, "doc": doc, "fingerprint": fingerprint, "coincident_tolerance": coincident_tolerance,
                                              "angle_tolerance": angle_tolerance, "equal_tolerance": equal_tolerance, "max_gap": max_gap}, timeout=190)


@mcp.tool()
def check_printability(name: str, doc: str | None = None, profile: dict | None = None, samples: int = 2000) -> str:
    """3D 프린트 **출력 가능성 검사** (M12). 출력 방향은 +Z(바닥 = 형상의 가장 낮은 면).

    profile: {"material": "PLA|PETG|ABS|ASA|TPU|Nylon", "nozzle": 0.4, "layer": 0.2, "bed": [220,220,250], "walls": 3, "infill": 20,
              "min_wall"|"overhang_deg"|"bridge_max"|"hole_comp"|"density": 재질 표 값 덮어쓰기}.
    검사: 얇은 벽(노즐×2 미만), 오버행(한계각 초과·아래가 빈 면 → 서포트 면적), 브릿지, 작은 구멍(노즐×2 미만), 수평 구멍, 베드 적합, 첫 층 접지.
    결과의 issues(번호·심각도·fix 힌트)를 사용자에게 번호 목록으로 보여 주고, fixes는 apply_print_fixes 후보다.
    """
    return client.call("check_printability", {"name": name, "doc": doc, "profile": profile, "samples": samples}, timeout=190)


@mcp.tool()
def estimate_print(name: str, doc: str | None = None, profile: dict | None = None, speed: float = 50.0) -> str:
    """재료 부피·무게(g)·필라멘트 길이(m, 1.75)·대략 시간(h)·비용 추정 (M12). 슬라이서보다 거칠다(±30 %)."""
    return client.call("estimate_print", {"name": name, "doc": doc, "profile": profile, "speed": speed}, timeout=120)


@mcp.tool()
def suggest_orientation(name: str, doc: str | None = None, profile: dict | None = None, apply: int | None = None) -> str:
    """출력 방향 6개 + 현재 방향을 서포트 면적·접지·높이·베드 적합으로 채점해 순위 (M12).

    apply=<rank>면 그 회전을 객체 Placement에 적용하고 바닥을 z=0에 놓는다(사용자가 고른 뒤에).
    """
    return client.call("suggest_orientation", {"name": name, "doc": doc, "profile": profile, "apply": apply}, timeout=190)


@mcp.tool()
def apply_print_fixes(name: str, fixes: list[dict], doc: str | None = None, profile: dict | None = None) -> str:
    """출력용 설계 수정을 Body에 PartDesign 피처로 쌓는다 (M12). 되돌리기 = 피처 삭제.

    fixes: [{"fix": "elephant_foot", "size": 0.3}, {"fix": "hole_comp", "holes": "vertical"|"all", "comp": 0.2}, {"fix": "teardrop", "holes": [[x,y,z],...]}]
    elephant_foot = 바닥 바깥 모서리 챔퍼, hole_comp = 수직 구멍 지름 보정 Pocket, teardrop = 수평 구멍 위 45° 눈물방울 Pocket.
    오버행 챔퍼·얇은 벽 두껍게·분할은 v1에서 제안만(check의 issues fix: manual). 사용자가 고른 것만 적용한다.
    """
    return client.call("apply_print_fixes", {"name": name, "fixes": fixes, "doc": doc, "profile": profile}, timeout=190)


@mcp.tool()
def reload_handlers() -> str:
    """FreeCAD를 재시작하지 않고 애드온 핸들러 코드를 다시 읽는다. **개발용.**

    애드온의 handlers/*.py를 고친 뒤 호출한다. 새로 추가한 핸들러 파일도 집어 올린다.
    InitGui.py·rpc_server.py·handlers/__init__.py를 고쳤을 때는 FreeCAD 재시작이 필요하다.
    """
    return client.call("reload_handlers", timeout=60)


def main() -> None:
    parser = argparse.ArgumentParser(prog="cadxray")
    parser.add_argument("--host", default=client.default_host())
    parser.add_argument("--port", type=int, default=client.default_port())
    args = parser.parse_args()
    client.configure(args.host, args.port)
    mcp.run()


if __name__ == "__main__":
    main()
