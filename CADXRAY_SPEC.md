> 2026-09-10 이름 변경: 이 명세는 `freecad-diag-mcp`라는 이름으로 작성됐고, 구현 완료 후 `cadxray`로 바뀌었다. 본문의 이름은 일괄 치환한 것이다.

# cadxray 개발 명세

FreeCAD 모델 **진단**에 특화한 경량 MCP 서버. 기존 모델을 불러와 AI가 구조·상태를 파악하고, 수정은 `execute_code`로 하는 워크플로를 목표로 한다.

---

## 0. Claude Code 작업 지침

- 이 문서를 처음부터 끝까지 읽은 뒤 **9장의 마일스톤 순서대로** 구현한다. 각 마일스톤이 끝나면 멈추고 결과와 다음 단계를 보고한다.
- 명세에 없는 툴을 추가하지 않는다. 필요하다고 판단되면 먼저 제안한다.
- FreeCAD API는 `docs/api-notes.md`(소스 태그 1.0.2·1.1.3에서 확인한 사실)를 기준으로 구현한다. `[확인됨]` 표시는 그 노트에 근거가 있다는 뜻이다. 노트에 없는 API를 써야 하면 `docs/freecad-src-ref/`의 소스나 라이브 introspection(부록 A.1)으로 확인하고 노트에 추가한다. 추측으로 구현하지 않는다.
- 사용자는 코드를 직접 작성하지 않는 사람이다. 설치·실행 명령은 README에 **복사해서 실행할 수 있는 형태**로 정확히 적는다.
- 포트, 경로, 툴 이름 등 이 문서에 정해진 값을 바꿔야 하면 바꾸기 전에 물어본다.
- 참고 구현(5장)의 코드를 가져올 때는 MIT 라이선스 표기를 유지한다.

---

## 1. 목표와 범위

### 목표
- Claude Code가 **열려 있는 FreeCAD 문서**를 읽고, 스케치 제약 상태·형상 유효성·recompute 에러를 구조화된 JSON으로 받는다.
- 응답 크기가 제어되어 수백 개 객체가 있는 모델에서도 컨텍스트가 폭발하지 않는다.
- 수정은 `execute_code` 하나로 처리한다(생성·편집 전용 툴은 만들지 않는다).

### 비목표 (v1에서 제외)
- 부품 라이브러리 삽입, FEM, 어셈블리 전용 툴 (STEP 가져오기·형상 분석은 7.12~7.15 M6, 메시(STL)는 M7 툴 + execute_code(M7 부록, 12.1), TechDraw는 M8로 추가)
- 원격 호스트 접속(localhost만)
- 헤드리스(FreeCADCmd) 모드 — 구조상 가능하게 두되 v1에서는 테스트하지 않음

---

## 2. 환경 (구현 시작 전 사용자에게 확인)

| 항목 | 확인할 내용 |
|---|---|
| FreeCAD 버전 | 1.0 / 1.1 중 어느 것인지. API 차이가 있음(11장) |
| OS·설치 방식 | macOS 앱 번들 / Windows / Linux(AppImage·Flatpak·snap·패키지) — Mod 디렉토리 경로가 달라짐 |
| 브릿지 Python | 3.10 이상, `uv` 설치 여부 |
| 기존 MCP | neka-nat freecad-mcp 애드온이 이미 설치되어 있고 포트 **9875**를 사용 중. 본 프로젝트는 **9877**을 써서 공존한다 |

---

## 3. 아키텍처

```
Claude Code  ←stdio(MCP)→  브릿지 (uv / Python / FastMCP)
                              ↓ XML-RPC  http://127.0.0.1:9877
                           FreeCAD 애드온 (워크벤치 CadXray)
                              ↓ 큐 + QTimer
                           메인 스레드에서 핸들러 실행
```

### 설계 원칙
1. **FreeCAD 객체는 메인 스레드에서만 만진다.** RPC 스레드는 요청을 큐에 넣고 결과를 기다린다.
2. **모든 핸들러는 JSON 직렬화 가능한 dict를 반환**하고, RPC 계층은 그것을 `json.dumps`한 문자열로 넘긴다(XML-RPC 타입 제한 회피).
3. **응답 봉투를 통일**한다.
   ```json
   {"ok": true, "data": {...}, "warnings": [], "truncated": false, "elapsed_ms": 12}
   {"ok": false, "error": "메시지", "traceback": "..."}
   ```
4. **출력 크기 제어는 기본값**이다. 모든 목록형 툴은 `max_*` 파라미터와 `truncated` 플래그를 가진다. 응답 목표 20 KB 이하, 하드캡 100 KB.
5. **브릿지는 FreeCAD가 꺼져 있어도 죽지 않는다.** 연결 실패 시 사용자에게 무엇을 켜야 하는지 알려주는 문자열을 반환한다.

---

## 4. 저장소 구조

```
cadxray/
├── addon/
│   └── CadXray/                 # FreeCAD Mod 디렉토리에 심링크/복사
│       ├── Init.py                  # 비-GUI 초기화 (비워두거나 로깅만)
│       ├── InitGui.py               # 워크벤치 등록, 메뉴/툴바
│       ├── package.xml              # 애드온 메타데이터 (Addon Manager 호환)
│       ├── settings.py              # 자동시작 설정 (FreeCAD ParamGet)
│       ├── main_thread.py           # 큐 + QTimer 실행기
│       ├── rpc_server.py            # XML-RPC 서버 (스레드), 핸들러 디스패치
│       └── handlers/
│           ├── __init__.py          # 핸들러 레지스트리, reload 지원
│           ├── util.py              # 직렬화, 크기 제한, 응답 봉투, 버전 분기
│           ├── documents.py         # ping, list_documents
│           ├── document_graph.py    # get_document_graph, inspect_object
│           ├── sketch_diag.py       # get_sketch_diagnostics
│           ├── shape_analysis.py    # analyze_shape
│           ├── recompute.py         # tracked_recompute
│           ├── screenshot.py        # get_screenshot
│           ├── execute.py           # execute_code
│           ├── step_import.py       # import_step (M6)
│           └── shape_features.py    # find_holes, check_interference, get_mass_properties (M6)
├── bridge/
│   ├── pyproject.toml
│   └── src/cadxray/
│       ├── __init__.py
│       ├── client.py                # XML-RPC 클라이언트 래퍼, 타임아웃, 에러 메시지
│       └── server.py                # FastMCP 툴 정의, main()
├── scripts/
│   └── install_addon.py             # OS/버전별 Mod 경로 탐지 후 심링크
├── tests/
│   ├── fixtures/make_test_models.py # 진단용 테스트 모델 생성 (FreeCAD 안에서 실행)
│   └── in_freecad/test_handlers.py  # FreeCADCmd로 실행하는 핸들러 테스트
├── docs/
│   ├── api-notes.md                 # 확인된 FreeCAD API 사실 (버전 태그 포함) — 구현의 기준
│   └── freecad-src-ref/             # FreeCAD 소스 발췌 (1.0.2, 1.1.3) — 부록 A.3의 파일들, LGPL
├── .mcp.json                        # Claude Code 프로젝트 스코프 설정
├── CLAUDE.md                        # 이 MCP를 쓰는 AI를 위한 워크플로 지침 (10장)
└── README.md                        # 사용자용 설치·사용 안내 (한국어)
```

---

## 5. 참고 구현

| 프로젝트 | 가져올 것 | 위치 |
|---|---|---|
| neka-nat/freecad-mcp (MIT) | 메인 스레드 큐 + QTimer 폴링 + XML-RPC 서버 패턴, 워크벤치 메뉴, 자동시작 설정 저장 | `addon/FreeCADMCP/rpc_server/rpc_server.py` |
| theosib/FreeCAD-MCP-Server | 진단 툴의 이름·응답 설계 (`get_document_graph`, `get_sketch_diagnostics`, `tracked_recompute`, `reload_handlers`) | README의 툴 표 |

neka-nat의 서버 골격을 먼저 읽고 패턴을 이해한 뒤, 본 프로젝트 구조에 맞게 다시 작성한다. 그대로 복사하지 않는다(그쪽은 생성·편집 툴이 섞여 있다).

---

## 6. 애드온 상세

### 6.1 main_thread.py — 메인 스레드 실행기

```python
import queue, threading
import FreeCAD

_tasks = queue.Queue()
_timer = None

def submit(fn, *args, timeout=60, **kwargs):
    """RPC 스레드에서 호출. 메인 스레드 실행 결과를 기다려 반환."""
    if not FreeCAD.GuiUp:            # FreeCADCmd: 이벤트 루프 없음 → 즉시 실행
        return fn(*args, **kwargs)
    box, done = {}, threading.Event()
    _tasks.put((fn, args, kwargs, box, done))
    if not done.wait(timeout):
        return {"ok": False, "error": f"timeout after {timeout}s (메인 스레드가 바쁨)"}
    return box["result"]

def _pump():
    while True:
        try: fn, args, kwargs, box, done = _tasks.get_nowait()
        except queue.Empty: return
        try: box["result"] = fn(*args, **kwargs)
        except Exception as e:
            import traceback
            box["result"] = {"ok": False, "error": str(e), "traceback": traceback.format_exc()}
        finally: done.set()

def start():
    global _timer
    if FreeCAD.GuiUp and _timer is None:
        from PySide import QtCore
        _timer = QtCore.QTimer(); _timer.timeout.connect(_pump); _timer.start(100)

def stop():
    global _timer
    if _timer: _timer.stop(); _timer = None
```

- `execute_code`는 사용자 코드가 길게 돌 수 있으므로 timeout을 크게(기본 300초) 둔다. 메인 스레드에서 exec되므로 실제로 중단시킬 수는 없다 — README에 명시.

### 6.2 rpc_server.py — XML-RPC 서버

- `SimpleXMLRPCServer(("127.0.0.1", 9877), allow_none=True, logRequests=False)`
- `serve_forever()`를 데몬 스레드에서 실행. `stop()`은 `server.shutdown()` + `server_close()`.
- 등록 메서드는 하나로 통일: `call(tool_name: str, params_json: str) -> str`. 내부에서 `handlers.REGISTRY[tool_name](**params)`를 `main_thread.submit`으로 실행하고 결과 dict를 `json.dumps(..., ensure_ascii=False, default=str)`로 반환.
  - 툴을 추가할 때 RPC 메서드를 새로 등록할 필요가 없고, 브릿지도 툴 이름만 넘기면 된다.
- 예외는 반드시 잡아서 `{"ok": false, ...}` 봉투로 반환한다(XML-RPC Fault로 새지 않게).

### 6.3 InitGui.py — 워크벤치

- 워크벤치 이름: **CAD X-ray**. 명령 3개: `CadXray_StartServer`, `CadXray_StopServer`, `CadXray_ToggleAutoStart`.
- 상태는 `FreeCAD.Console.PrintMessage`로 리포트 뷰에 출력(포트, 실행 중 여부).
- 자동시작: `FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Mod/CadXray")`에 `AutoStart` bool 저장. 켜져 있으면 GUI 로딩 완료 후 서버 시작(neka-nat 방식 참고 — QTimer.singleShot으로 지연 시작).
- 포트는 같은 ParamGet에 `Port` int로 저장, 기본 9877.

### 6.4 핸들러 공통 (util.py)

- `envelope(data, warnings=None, truncated=False, t0=None)` / `error(msg)`.
- `serialize(value, depth=0)`: FreeCAD 타입 → JSON.
  - `FreeCAD.Vector` → `[x, y, z]` (소수 4자리 반올림)
  - `FreeCAD.Placement` → `{"base": [x,y,z], "rotation_axis": [..], "rotation_angle_deg": a}`
  - `FreeCAD.Rotation` → 축·각
  - `DocumentObject` → `obj.Name`, 객체 리스트 → 이름 리스트
  - `(obj, [subnames])` 링크 튜플 → `{"object": name, "sub": [...]}`
  - `Part.Shape` → `shape_summary()` (타입, 유효성, 면/모서리 수, 바운딩박스) — 절대 원본 덤프 금지
  - `Quantity` → `{"value": v, "unit": u}`
  - 길이 > `max_list` 리스트 → 앞 N개 + `"_truncated": total`
- `freecad_version()`: `FreeCAD.Version()` → `(major, minor)` 튜플. API 분기용.
- `get_doc(name)`: name이 None이면 `FreeCAD.ActiveDocument`, 없으면 에러 메시지.
- `attachment_support(obj)`: `AttachmentSupport` `[확인됨: 1.0.2·1.1.3 모두]`. `Support`는 0.21 이하 이름이므로 `hasattr` 폴백만 둔다.
- `check_shape(shape, bop)`: `shape.check(bop)`는 문제가 있으면 **예외**를 던진다 `[확인됨]` → 예외 메시지를 `check_message`로 반환.

---

## 7. 툴 명세

모든 툴은 `doc` 파라미터가 생략되면 활성 문서를 사용한다. 이름은 브릿지와 애드온에서 동일하게 쓴다.

### 7.1 `ping`
- 입력: 없음
- 출력: `{"freecad_version": "1.0.1", "gui": true, "active_document": "Body001", "documents": 2, "addon_version": "0.1.0"}`
- 용도: 연결 확인, 버전 파악. 브릿지가 연결 실패 시 안내 메시지를 만드는 근거.

### 7.2 `list_documents`
- 출력: `[{"name", "label", "filename", "object_count", "active": bool, "modified": bool}]`
- API: `FreeCAD.listDocuments()`, `doc.FileName`, `doc.Modified`

### 7.3 `get_document_graph`
- 입력: `doc=None, max_objects=200, type_filter=None (예: "Sketcher::SketchObject"), label_pattern=None (정규식), include_sketch_summary=True`
- 출력:
  ```json
  {
    "document": "Bracket",
    "summary": {"objects": 143, "invalid": 2, "touched": 5, "by_type": {"PartDesign::Pad": 12, "Sketcher::SketchObject": 15, ...}},
    "bodies": [{"name": "Body", "label": "Body", "tip": "Pocket003", "features": ["Sketch", "Pad", ...]}],
    "roots": ["Body", "Part001"],
    "objects": [
      {"name": "Sketch002", "label": "BasePlate", "type": "Sketcher::SketchObject",
       "state": ["Invalid"], "status": "Sketch has open wire", "out": ["XY_Plane"], "in": ["Pad002"],
       "visible": true, "sketch": {"dof": 3, "fully_constrained": false}}
    ],
    "invalid_objects": ["Sketch002", "Pad002"]
  }
  ```
- API: `doc.Objects`, `doc.RootObjects`, `obj.TypeId`, `obj.State`(값: Touched/Invalid/Recompute/Recompute2/Restore/Expanded/Partial/Importing/Up-to-date), `obj.getStatusString()` `[확인됨: 에러 상태면 문서의 에러 설명 문자열, 아니면 "Touched"/"Valid", 1.1은 "Freezed" 추가]`, `obj.OutList`, `obj.InList`, `obj.Visibility`, `PartDesign::Body`의 `Group`·`Tip` `[확인됨]`.
- 크기 제어: `objects`는 `max_objects`까지만. 초과 시 `truncated: true`와 함께 `summary`·`invalid_objects`는 **항상 전체** 기준으로 계산한다(잘려도 문제 객체는 놓치지 않게).
- `include_sketch_summary`는 스케치마다 `DoF`/`FullyConstrained`만 읽는다(solve 호출 없이 속성만 — 비용이 크면 옵션 기본값을 False로).

### 7.4 `inspect_object`
- 입력: `doc=None, name, include_shape=True, max_list=20`
- 출력: `{"name", "label", "type", "state", "status", "properties": {prop: {"type": "App::PropertyLength", "value": ...}}, "expressions": [[prop, expr]], "shape": shape_summary, "out": [...], "in": [...]}`
- API: `obj.PropertiesList`, `obj.getTypeIdOfProperty(p)`, `obj.getPropertyByName(p)`, `obj.ExpressionEngine`
- `Shape` 프로퍼티는 값 대신 `shape_summary`로 대체. `Proxy`, `ViewObject` 등 직렬화 불가 항목은 타입명만.

### 7.5 `get_sketch_diagnostics`
스케치가 "왜 빨간지"를 한 번에 알려주는 핵심 툴.
- 입력: `doc=None, sketch, include_geometry=True, include_constraints=True, max_items=200`
- 출력:
  ```json
  {
    "sketch": "Sketch002",
    "solve_status": 0,
    "dof": 0, "fully_constrained": true,
    "solve_status_text": "conflicting constraints",
    "conflicting": [{"id": 12, "index": 11}, {"id": 15, "index": 14}], "redundant": [], "partially_redundant": [], "malformed": [],
    "open_vertices": [[10.0, 5.0, 0.0]],
    "missing_point_on_point": 0,
    "attachment": {"support": {"object": "XY_Plane", "sub": []}, "map_mode": "FlatFace"},
    "placement": {...},
    "counts": {"geometry": 8, "constraints": 14, "external": 1, "construction": 2},
    "geometry": [{"i": 0, "type": "Part::GeomLineSegment", "construction": false, "start": [0,0,0], "end": [10,0,0]},
                 {"i": 3, "type": "Part::GeomCircle", "center": [5,5,0], "radius": 2.0}],
    "constraints": [{"i": 0, "type": "Coincident", "name": "", "first": 0, "first_pos": 2, "second": 1, "second_pos": 1, "value": null, "driving": true, "active": true}]
  }
  ```
- API:
  - 절차 `[확인됨: api-notes 4장]`: ① `status = sk.solve()` → ② `sk.DoF`, `sk.ConflictingConstraints`, `sk.RedundantConstraints`, `sk.PartiallyRedundantConstraints`, `sk.MalformedConstraints`, `sk.FullyConstrained` 읽기 → ③ `sk.detectMissingPointOnPointConstraints()` 호출 후 `sk.MissingPointOnPointConstraints` 읽기 → ④ `sk.OpenVertices` 읽기. 모두 SketchObject 자체 속성이므로 `Sketcher.Sketch()` 솔버 객체 복제는 **하지 않는다**.
  - `solve()` 반환 코드 `[확인됨]`: 0 성공, -4 over-constrained, -3 conflicting, -5 malformed, -1 solver error, -2 redundant (이 순서가 우선순위). 응답에 `solve_status_text`로 풀어 쓴다.
  - 주의 `[확인됨]`: `DoF`·`Conflicting…` 등은 마지막 solve 값이므로 ①을 먼저 한다. `FullyConstrained`는 solve 성공 시에만 갱신되므로 실패 시 이전 값이 남는다 → `solve_status`와 함께 판단. `OpenVertices`는 recompute된 `Shape` 기준, 스케치 로컬 좌표.
  - 충돌/중복 번호는 **1-based**(GUI 제약 패널 번호와 동일) `[확인됨]`. 응답의 `conflicting` 등에는 `[{"id": 12, "index": 11}]`처럼 둘 다 넣고, `constraints` 목록의 `i`는 0-based로 통일한다.
  - 지오메트리 `[확인됨]`: `sk.Geometry[i].TypeId`(`Part::GeomLineSegment` 등), LineSegment `StartPoint/EndPoint`, Circle `Center/Radius`, ArcOfCircle `Center/Radius/StartPoint/EndPoint`, Point `X/Y`. construction 여부는 `sk.getConstruction(i)`(두 버전 모두) 또는 `sk.GeometryFacadeList[i].Construction`.
  - GeoId `[확인됨]`: -1 H축, -2 V축, -3 이하 외부 지오메트리(`ExternalGeometry[-GeoId-1]`). PointPos: 0 none, 1 start, 2 end, 3 mid. 응답에서 음수 GeoId는 `{"geo": -3, "external": 0}`처럼 풀어 준다.
  - 제약: `sk.Constraints[i]`의 `Type, Name, First, FirstPos, Second, SecondPos, Third, ThirdPos, Value, Driving, IsActive`
  - 부착: `AttachmentSupport`/`Support`, `MapMode`
- 크기 제어: geometry·constraints는 `max_items`까지. 단 `conflicting`/`redundant`에 나온 인덱스의 제약은 잘리더라도 **항상 포함**한다.

### 7.6 `analyze_shape`
- 입력: `doc=None, name, max_faces=30, max_edges=30, bop_check=False`
- 출력:
  ```json
  {
    "object": "Pad", "shape_type": "Solid", "is_null": false, "is_valid": true, "check_message": null,
    "solids": 1, "shells": 1, "faces": 14, "edges": 36, "vertexes": 24,
    "volume": 1234.5, "area": 890.1, "bbox": {"min": [..], "max": [..], "size": [..]},
    "center_of_mass": [..],
    "faces_by_surface": {"Plane": 10, "Cylinder": 4},
    "edges_by_curve": {"Line": 28, "Circle": 8},
    "face_details": [{"i": 0, "surface": "Plane", "area": 100.0, "orientation": "Forward"}],
    "closed": true
  }
  ```
- API `[확인됨: api-notes 6장]`: `obj.Shape`, `isNull()`, `isValid()`, `check(bop_check)`(문제 시 예외 → 메시지를 `check_message`로), `Volume/Area/Length`, `BoundBox`(`XMin…ZMax`, `XLength…`, `Center`, `DiagonalLength`), `Solids/Shells/Faces/Edges/Vertexes/Wires`, `face.Surface` 타입명(`type(face.Surface).__name__`), `edge.Curve` 타입명, `shape.isClosed()`, `CenterOfGravity`(ComplexGeoData) 또는 `Solids[0].CenterOfMass`.
- PartDesign 피처는 `Shape`가 Body 누적 형상이므로, `AddSubShape`(FeatureAddSub 계열: Pad·Pocket·Revolution·Groove·Loft·Pipe·Helix) `[확인됨]`가 있으면 그 요약도 `feature_own_shape`로 함께 준다.
- 집계(`faces_by_surface`)는 항상 전체, 상세는 `max_faces`까지.

### 7.7 `tracked_recompute`
- 입력: `doc=None, objects=None (이름 리스트, None이면 전체)`
- 출력: `{"recomputed": 12, "new_errors": [{"name", "status"}], "resolved": [...], "persistent": [...], "still_touched": [...]}`
- 구현: 전후로 `obj.State`·`getStatusString()` 스냅샷 → `doc.recompute()` 또는 `doc.recompute([objs])`(반환값 = 재계산 피처 수 `[확인됨]`) → diff. `status`에는 `getStatusString()`의 에러 설명 문자열이 그대로 들어간다.

### 7.8 `get_screenshot`
- 입력: `doc=None, view="current" | "iso" | "front" | "top" | "right" | ..., width=1024, height=768, fit=True, background="White"`
- 출력: `{"png_base64": "...", "width", "height", "view"}`
- API `[확인됨: api-notes 9장]`: `FreeCADGui.getDocument(doc).ActiveView`(없으면 `FreeCADGui.ActiveDocument.ActiveView`), 프리셋 `viewIsometric/viewFront/viewTop/viewRight/viewRear/viewBottom/viewLeft/viewAxonometric/viewDimetric/viewTrimetric`, `fitAll()`, `saveImage(path, w, h, background)` — `background`는 `"Current"`/`"White"`/`"Black"`/`"Transparent"`/hex, **저장 폴더가 없으면 RuntimeError**이므로 `tempfile.mkdtemp()`를 쓴다 → 파일을 읽어 base64. GUI가 없으면 에러 봉투.
- 브릿지에서는 MCP `Image` 콘텐츠로 변환해 반환한다(7.11).

### 7.9 `execute_code`
- 입력: `code, doc=None, timeout=300`
- 출력: `{"stdout": "...", "stderr": "...", "result": <직렬화된 `_result` 변수 값 또는 null>}`
- 구현: 네임스페이스에 `FreeCAD, App, FreeCADGui, Gui, Part, Sketcher, PartDesign(가능하면), doc(활성 문서), math, json` 주입. `contextlib.redirect_stdout/stderr`로 캡처. 코드가 `_result`에 값을 넣으면 `serialize`해 반환. 예외는 traceback 포함 봉투.
- 툴 docstring에 "수정용 탈출구. 진단은 전용 툴을 먼저 쓸 것"을 명시.

### 7.10 `reload_handlers` (개발용)
- `handlers` 패키지 모듈들을 `importlib.reload`. FreeCAD를 재시작하지 않고 핸들러 코드를 반영하기 위함. README에 "개발자용"으로 표기.

### 7.11 브릿지(server.py)

```python
from mcp.server.fastmcp import FastMCP, Image
from .client import call, ConnectError

mcp = FastMCP("cadxray")

@mcp.tool()
def get_sketch_diagnostics(sketch: str, doc: str | None = None,
                           include_geometry: bool = True, include_constraints: bool = True,
                           max_items: int = 200) -> str:
    """스케치의 solve 상태, DOF, 충돌/중복 제약, 열린 정점, 지오메트리·제약 목록을 반환한다.
    스케치가 빨갛게 표시되거나 Pad/Pocket이 실패할 때 가장 먼저 호출한다."""
    return call("get_sketch_diagnostics", sketch=sketch, doc=doc,
                include_geometry=include_geometry, include_constraints=include_constraints,
                max_items=max_items)

@mcp.tool()
def get_screenshot(doc: str | None = None, view: str = "current",
                   width: int = 1024, height: int = 768, fit: bool = True) -> Image | str:
    """3D 뷰를 PNG로 캡처한다. view: current|iso|front|top|right|rear|bottom|left"""
    raw = call_raw("get_screenshot", doc=doc, view=view, width=width, height=height, fit=fit)
    if not raw.get("ok"): return json.dumps(raw, ensure_ascii=False)
    import base64
    return Image(data=base64.b64decode(raw["data"]["png_base64"]), format="png")

def main():
    mcp.run()   # stdio
```

- `client.py`: `ServerProxy(f"http://{host}:{port}", allow_none=True)`. 소켓 타임아웃은 커스텀 `Transport`로 설정(기본 120초, `execute_code`는 timeout+10). `ConnectionRefusedError`/`socket.timeout`을 잡아 다음 문자열로 반환:
  > FreeCAD에 연결할 수 없습니다(127.0.0.1:9877). FreeCAD를 실행하고 워크벤치 'CAD X-ray'에서 'Start Server'를 누르거나 자동시작을 켜 주세요.
- 실행 인자: `--host`(기본 127.0.0.1), `--port`(기본 9877). 환경변수 `CADXRAY_PORT`도 허용.
- 툴 docstring은 Claude가 읽는 사용 설명서다. **언제 부르는지**를 한 줄씩 넣는다.
- `pyproject.toml`: `requires-python = ">=3.10"`, `dependencies = ["mcp>=1.2"]`, `[project.scripts] cadxray = "cadxray.server:main"`, 빌드 백엔드 hatchling.

### 7.12 `import_step` (M6)
STEP/IGES처럼 히스토리 없는 파일을 문서에 넣고, 생긴 객체를 돌려준다.
- 입력: `path, doc=None (None이면 새 문서), merge=False, use_link_group=False, import_hidden=False, mode=0`
- 출력:
  ```json
  {"document": "Sensor_Bracket", "created": [{"name": "Part", "label": "BRACKET-01", "type": "App::Part", "children": ["Solid", "Solid001"]},
                                             {"name": "Solid", "label": "body", "type": "Part::Feature", "solids": 1, "faces": 142, "valid": true}],
   "top_level": ["Part"], "solids_total": 2, "invalid": [], "bbox": {"min": [..], "max": [..], "size": [..]}}
  ```
- API `[확인됨: api-notes 12장]`: 새 문서면 `Import.open(path)`, 기존 문서면 `Import.insert(path, docName, importHidden=, merge=, useLinkGroup=, mode=)`. `mode`: 0 SingleDoc, 1 GroupPerDoc, 2 GroupPerDir, 3 ObjectPerDoc, 4 ObjectPerDir. 생성 객체는 호출 전후 `doc.Objects` 차집합으로 구한다.
- `merge=True`면 솔리드가 하나의 compound로 합쳐진다. 간섭 검사·홀 검출을 하려면 기본값(False)으로 부품을 분리해 두는 게 낫다 — docstring에 적는다.
- 크기 제어: `created`는 `max_objects`(기본 100)까지, 요약(`solids_total`, `invalid`, `bbox`)은 항상 전체.

### 7.13 `find_holes` (M6)
원통면을 축·중심으로 묶어 구멍 직경과 위치를 뽑는다. 마운팅 홀 패턴 확인용.
- 입력: `name, doc=None, min_radius=0.5, max_radius=50.0, max_holes=100, group_tolerance=0.01`
- 출력:
  ```json
  {"object": "Solid", "holes": [{"i": 0, "diameter": 6.6, "axis": [0,0,1], "center": [12.5, 40.0, 0.0],
                                 "depth": 8.0, "through": true, "faces": [17, 18]}],
   "patterns": [{"diameter": 6.6, "count": 4, "centers": [[..],[..],[..],[..]], "pitch": [25.0, 80.0]}],
   "truncated": false}
  ```
- API `[확인됨]`: `for i, f in enumerate(shape.Faces)`: `type(f.Surface).__name__ == "Cylinder"` → `f.Surface.Radius`, `f.Surface.Axis`, `f.Surface.Center`. 같은 축·같은 축선상 중심·같은 반지름인 면을 한 구멍으로 묶는다(반원통 면 2개가 한 구멍인 경우가 흔함). 깊이는 그 면들의 `BoundBox`를 축 방향으로 투영한 길이. 관통 여부는 구멍 축을 따라 `shape.BoundBox` 양끝 밖에서 안쪽으로 `distToShape` 또는 `isInside`로 판정 — 휴리스틱이므로 응답에 `"through_method": "heuristic"`을 넣는다.
- 원통면이 볼록(보스·축)인지 오목(구멍)인지 구분: 면 중앙점의 법선이 축을 향하면 구멍. `f.normalAt(u, v)`와 `f.Surface.Center` 방향으로 판정한다.
- `patterns`: 같은 직경끼리 묶어 개수와 중심 좌표를 준다. PCD·피치는 AI가 좌표에서 계산해도 되므로 `pitch`는 두 방향 최소 간격만 준다.

### 7.14 `check_interference` (M6)
부품 쌍의 간섭 부피와 최소 거리.
- 입력: `names (2개 이상), doc=None, clearance=0.0, volume_tolerance=1e-6, max_pairs=50`
- 출력:
  ```json
  {"pairs": [{"a": "Bracket", "b": "Sensor", "distance": 0.0, "interference_volume": 12.4, "status": "interference"},
             {"a": "Bracket", "b": "Bolt", "distance": 0.35, "interference_volume": 0.0, "status": "clearance_violation"}],
   "summary": {"interference": 1, "clearance_violation": 1, "ok": 3}, "truncated": false}
  ```
- API `[확인됨]`: `d = a.Shape.distToShape(b.Shape)[0]`; `d == 0`이면 `a.Shape.common(b.Shape).Volume`으로 간섭 부피. `status`: 부피 > `volume_tolerance` → `interference`, 아니면 `d < clearance` → `clearance_violation`, 아니면 `ok`.
- `common()`은 큰 형상에서 느리다. `distToShape`가 0일 때만 호출하고, 쌍 수는 `max_pairs`로 제한한다. 이름 대신 `App::Part` 하나를 주면 그 안의 `Part::Feature`들을 쌍으로 푼다.

### 7.15 `get_mass_properties` (M6)
- 입력: `name, doc=None, density=None (g/cm³)`
- 출력: `{"volume_mm3": 12345.6, "area_mm2": 8901.2, "center_of_mass": [..], "matrix_of_inertia": [[..]*3]*3, "principal": {"RadiusOfGyration": [..], "Moments": [..]}, "mass_g": 33.3 (density 있을 때), "solids": 1}`
- API `[확인됨]`: `shape.Volume`, `shape.Area`, 솔리드별 `Solids[i].CenterOfMass`, `Solids[i].MatrixOfInertia`, `Solids[i].PrincipalProperties`(dict). 다중 솔리드면 부피 가중 합산. 단위는 FreeCAD 내부 mm 기준 → `mass_g = Volume(mm³) / 1000 × density(g/cm³)`.

STEP 분석 워크플로(CLAUDE.md에 추가): `import_step` → `get_document_graph`(부품 계층) → `analyze_shape(bop_check=True)`로 유효성 → 목적에 따라 `find_holes` / `check_interference` / `get_mass_properties` → 수정이 필요하면 `PartDesign::Body`를 만들고 `BaseFeature`에 넣은 뒤 `execute_code`로 Pocket·Hole을 쌓는다.

### 7.16 `classify_faces` (M7)
면마다 **정체**(plane / cylinder / cone / sphere / torus / free_form)를 판정한다. 해석면은 `Surface` 속성을 그대로 읽고, BSpline·Bezier 등은 면 위에 표본점·법선을 찍어 평면→원통·원뿔→구 순으로 맞춰 본다(잔차 ≤ `tolerance`면 채택). STEP의 "가짜 자유곡면"(사실은 원통·평면)을 가려내는 것이 목적.
- 입력: `name, doc=None, samples=5 (면당 samples² 표본), tolerance=1e-3, max_faces=200, include_analytic=True (False면 해석면은 집계만)`
- 출력:
  ```json
  {"object": "2B2", "faces_total": 44,
   "faces": [{"i": 3, "surface": "BSplineSurface", "identity": "cylinder", "method": "fit", "residual": 2e-6,
              "radius": 35.0, "axis": [0,0,1], "axis_letter": "Z", "center": [38.18, 45.05, 0.0], "concave": true, "arc_deg": 118.2, "area": 210.3, "bbox": {...}},
             {"i": 7, "surface": "Plane", "identity": "plane", "method": "analytic", "normal": [0,0,1], "position": 53.68, "area": 812.0},
             {"i": 9, "surface": "BSplineSurface", "identity": "cone", "axis": [..], "apex": [..], "semi_angle_deg": 45.0, "radius_range": [1.7, 3.25], "concave": true},
             {"i": 12, "surface": "BSplineSurface", "identity": "free_form", "residual": 0.83, "curvature": {"max": 0.12, "min": -0.03}}],
   "summary": {"by_surface": {"Plane": 20, "BSplineSurface": 24}, "by_identity": {"plane": 24, "cylinder": 16, "cone": 2, "free_form": 2},
               "bspline_faces": 24, "bspline_resolved": 22, "free_form_faces": 2, "free_form_area_pct": 1.2, "area_total": 5120.4},
   "rebuild": {"verdict": "prismatic | mixed | free_form", "main_axis": [0,0,1], "main_axis_letter": "Z",
               "levels": [{"position": 53.68, "area": 812.0, "faces": [7, 8]}, {"position": 69.68, "area": 790.1, "faces": [11]}],
               "radii": [{"radius": 35.0, "concave": false, "faces": 2}, {"radius": 1.7, "concave": true, "faces": 4}],
               "notes": ["BSpline 면 24개 중 22개가 원통·평면으로 판별됨(가짜 자유곡면)", "..."]}}
  ```
- 판정 `[확인됨: api-notes 13장]`: `face.ParameterRange` 격자에서 `face.isPartOfDomain(u,v)`인 점만 `face.valueAt/normalAt`. 법선이 전부 같고 점이 한 평면 위 → plane. 법선 공분산의 최소 고유값 ≈ 0이면 축이 있다(원통·원뿔 모두 법선이 축과 일정한 각): 축에 수직인 평면에 투영해 법선 직선들의 최소제곱 교점 = 축 위치, 축 좌표 t에 대한 반지름 r(t)가 상수면 cylinder, 선형이면 cone(반각 = atan|dr/dt|, 꼭짓점 = r=0인 t). 그 밖에 법선 직선들이 한 점에 모이면 sphere. 전부 실패하면 free_form(곡률 통계 첨부). 오목/볼록은 표본 중앙의 법선이 축을 향하는지로.
- `rebuild.main_axis`: 그 축에 수직인 평면 면적 + 평행한 원통·원뿔 면적이 가장 큰 축(X/Y/Z와 원통 축 후보 중). `levels`는 주축에 수직인 평면을 높이별로 묶은 것 — `section_profile`에서 단면을 뜰 높이의 후보다. `verdict`: 자유곡면 면적 < 0.5 %이고 주축 정렬 면적 > 90 % → prismatic, 자유곡면 < 20 % → mixed(하이브리드: BaseFeature + 피처), 그 밖에 free_form.

### 7.17 `section_profile` (M7)
축 방향 위치의 **단면 윤곽**을 스케치에 바로 옮길 수 있는 선분·호·원 목록으로 준다. `build_features`의 `profile.section`이 내부에서 이것을 부른다.
- 입력: `name, doc=None, axis="Z" | [x,y,z], position=None, fill_holes=True, max_fill_radius=10.0, tolerance=1e-5, samples=24, max_elements=300`
- `position=None`이면 단면을 뜨지 않고 후보 높이만 준다: 축에 수직인 평면의 위치(`levels`)와 정점 좌표 히스토그램(`vertex_positions`).
- 출력:
  ```json
  {"object": "2B2", "axis": [0,0,1], "position": 55.0,
   "sketch_plane": {"plane": "XY_Plane", "attachment_offset_z": 55.0, "local_x": "X", "local_y": "Y"},
   "wires": [{"closed": true, "outer": true, "area": 1234.5, "bbox_2d": [[x0,y0],[x1,y1]], "elements_total": 14,
              "elements": [{"type": "line", "start": [x,y], "end": [x,y]},
                           {"type": "arc", "center": [x,y], "radius": 35.0, "start": [x,y], "end": [x,y], "mid": [x,y], "ccw": true, "angle_deg": 118.2},
                           {"type": "circle", "center": [x,y], "radius": 1.7}],
              "unsupported": 0, "max_endpoint_deviation": 9e-6}],
   "filled_holes": 3, "elements_total": 14}
  ```
- 좌표는 스케치 로컬 2D `[확인됨: api-notes 7.5]`: XY 평면 (X, Y), XZ 평면 (X, Z)·오프셋 −y, YZ 평면 (Y, Z). 축이 ±X/±Y/±Z가 아니면 `sketch_plane`은 null이고 임의 프레임(`frame`)만 준다.
- `fill_holes` `[확인됨: api-notes 7.5·13]`: 2D 면 불리언은 피한다. 오목 원통·원뿔 그룹(호 합 ≥ 350°, 최대 반지름 ≤ `max_fill_radius`) 자리를 3D에서 원기둥(반지름 +0.05, 축 방향은 면 범위 그대로)으로 `fuse`한 사본을 `removeSplitter()`한 뒤 `slice`한다 → 구멍·카운터보어·챔퍼 자리가 없는 바깥 윤곽만 나온다. 포켓처럼 안쪽 윤곽이 필요하면 `fill_holes=False`.
- `build_features`의 `profile.section`에서만 쓰는 추가 인자 `[확인됨: api-notes 13]`: `exclude: [{"center": [x, y], "radius": r}]`(단면 평면 둘레에서 원기둥을 3D로 뺀 뒤 자른다 — 회전 절삭이 깎은 귀 영역), `clip: {"min": [x|null, y|null], "max": [...]}`(범위 밖을 상자로 `cut`한다; `common`은 겹친 면에서 빈 결과를 주므로 쓰지 않는다).
- 요소 판정: `Line`/`Circle`은 그대로, `BSplineCurve` 등은 `edge.discretize(Number=samples)` 표본으로 직선(최대 편차 ≤ `tolerance`) → 원(대수적 원 맞춤 잔차 ≤ `tolerance`) 순으로 맞춘다. BSpline 솔리드의 `slice`는 직선도 `BSplineCurve`(차수 1)로 돌려주므로 필수 `[라이브 1.1.3]`. 못 맞춘 요소는 `type: "bspline"`에 표본점을 넣고 `unsupported`에 센다.
- 진행 방향은 `wire.OrderedEdges`를 끝점 매칭으로 정렬한 것. 호의 `ccw`는 호 중간점이 시작→끝 반시계 방향 안에 있는지로 정하므로 180° 넘는 호도 맞다.

### 7.18 `build_features` (M7)
스케치 + 피처 목록을 Body에 **순서대로 쌓고** 하나 끝날 때마다 재계산·검증한다. 트레이스 규칙(Block, 틈은 Radius+Coincident, 구성선 축)은 내장.
- 입력: `body, doc=None, features=[...], params=None, create_body=True, stop_on_error=True`
  - `params`: `{"height": 16.0, ...}` → Spreadsheet `Params`에 별칭으로 기록(있으면 값만 갱신). 피처의 수치 필드(`position`, `length`, `size`, `angle`, 원의 `diameter`)는 숫자 또는 수식 문자열(`"Params.height"`)을 받는다.
  - 피처 공통: `{"op": ..., "name": "PadBand1"}`. 스케치 기반 op는 `"plane": "XY"|"XZ"|"YZ"`, `"position"`: 그 평면의 전역 좌표(XY→z, XZ→y, YZ→x; 오프셋 부호는 내부에서 맞춘다), `"profile"`.
  - `profile`(하나 선택): `{"section": {"of": "2B2", "doc": "Unnamed", "position": 55.0, "fill_holes": true, "exclude": [...], "clip": {...}}}`(축은 plane에서 정해진다) / `{"elements": [...]}`(7.17 형식, 와이어 하나) / `{"wires": [[...], [...]]}` / `{"circles": [{"center": [x,y], "diameter": 3.4, "expr": "Params.hole_d", "name": "hole_d"}]}` / `{"polygon": [[x,y], ...]}` / `{"polygons": [[[x,y], ...], ...]}` / `{"rect": {"center": [x,y], "width": w, "height": h}}`
  - `profile.section` 추가 옵션: `outer_only`(안쪽 와이어 제외), `approximate_bspline`(자유곡선을 표본점 꺾은선으로), `exclude`, `clip`(7.17). `edges` 필터 추가: `direction: [dx,dy,dz]`(직선 방향, 부호 무관), `radius_min/max`, `length/length_tol`, `bbox`
  - `pad`: `length` | `type`("UpToLast" 등), `reversed`, `midplane`, `taper`(구배 각도, 음수 = 안으로) · `pocket`: `length` | `through: true`(ThroughAll) | `type`, `reversed` · `groove`/`revolution`: `axis: {"x": v} | {"y": v}`(스케치 로컬 좌표의 구성선), `angle`(기본 360) · `fillet`/`chamfer`: `size`, `edges`: `["Edge3", ...]` 또는 필터 `{"curve": "Circle", "radius": 1.7, "radius_tol": 0.01, "radius_min": .., "radius_max": .., "center": [x|null, y|null, z|null], "center_tol": 0.01, "length": .., "bbox": {...}}` — 직전 피처(Body Tip)의 모서리에서 고른다.
- 출력:
  ```json
  {"body": "Body", "params_written": ["height", ...],
   "created": [{"op": "pad", "name": "PadBand1", "sketch": "SketchBand1", "elements": 14, "solve_status": 0, "fully_constrained": true, "volume_after": 8123.4, "status": "Valid"},
               {"op": "chamfer", "name": "ChamferHoles", "edges": ["Edge12", "Edge15"], "volume_after": 8100.1, "status": "Valid"}],
   "volume": 8100.1, "valid": true, "invalid": [], "stopped_at": null}
  ```
- API `[확인됨: api-notes 7·7.5·13]`: 스케치는 `AttachmentSupport=[(Origin 평면, "")]`, `MapMode="FlatFace"`, 오프셋은 `AttachmentOffset.Base.z`(수식이면 `setExpression(".AttachmentOffset.Base.z", ...)`). 호는 `Part.ArcOfCircle(Part.Circle(c, Z, r), a0, a1)` CCW만, 각도는 끝점에서 다시 계산. **트레이스 고정 규칙**: 선분·원은 Block, 호는 이음매마다 원래 정점에 Block한 구성점을 두고 양 끝 Coincident + Radius(호 5 − 1 − 2 − 2 = 0 DoF; 틈은 솔버가 닫는다). 지름 수식이 있는 원은 Block 대신 구성점(Block) + 중심 Coincident + 이름 붙인 `Diameter` 제약에 수식. Groove/Revolution 축은 첫 구성선 → `ReferenceAxis=(sketch, ["Axis0"])`. Fillet/Chamfer는 `Base=(tip, ["EdgeN", ...])`. 피처마다 `doc.recompute()` 후 `Invalid`면 `stop_on_error`에 따라 중단하고 `stopped_at`·상태 문자열을 돌려준다.
- 이 툴은 문서를 저장하지 않는다. 만든 스케치는 `Visibility=False`.

### 7.19 `compare_shapes` (M7)
두 형상이 **얼마나, 어디가** 다른지. 재구성 검증용.
- 입력: `a, b, doc=None, doc_b=None, fuzzy=1e-4, min_piece_volume=1e-3, max_pieces=10`
- 출력:
  ```json
  {"a": {"object": "2B2", "document": "Unnamed", "volume": 8123.4, "area": 5120.4, "faces": 44},
   "b": {...},
   "volume_diff": -0.03, "volume_diff_pct": 0.0004, "area_diff": 0.2, "bbox_max_diff": 0.0,
   "missing_in_b": [{"volume": 0.02, "bbox": {...}, "center": [..]}], "extra_in_b": [],
   "missing_total": 0.02, "extra_total": 0.0, "verdict": "identical | match | different"}
  ```
- API `[확인됨: api-notes 7.5]`: 면이 겹치는 쌍은 정확한 불리언이 실패하므로 `a.cut(b, fuzzy)`·`b.cut(a, fuzzy)`로 차집합을 뜨고, 두께 0인 조각(bbox 한 변 < 1e-6)과 `min_piece_volume` 미만 조각은 버린다. `verdict`: (missing+extra)/volume_a < 0.001 % → identical, < 0.1 % → match, 그 밖에 different. bbox 중심이 0.01 이상 어긋나면 "Body.Placement 확인" 경고.

### 7.20 `align_shapes` (M7)
같은 부품의 두 인스턴스 사이의 **강체 변환**(b = T·a)을 형상에서 찾는다. STEP 어셈블리의 `Placement`는 하위 어셈블리 프레임이라 인스턴스 변환이 아니므로(같은 종류인데 로컬 형상이 다르다 `[라이브 1.1.3]`), 재구성한 Body 하나를 여러 자리에 Link로 놓을 때 쓴다.
- 입력: `a, b, doc=None, doc_b=None, fuzzy=1e-4`
- 출력: `{"placement": {"base": [..], "rotation_axis": [..], "rotation_angle_deg": ..}, "matrix": [[..]*4], "match_pct": 99.99, "candidates_tried": 4, "symmetric": false}`
- 방법 `[확인됨: api-notes 13장]`: 무게중심을 맞추고 관성 주축(`Solid.PrincipalProperties`의 First/Second/ThirdAxisOfInertia)을 대응시킨다. 주축 부호가 정해지지 않으므로 오른손 조합 4가지를 모두 시도해 `a`를 옮긴 형상과 `b`의 교집합 부피가 가장 큰 것을 고른다(`match_pct` = 교집합/부피). 주 관성모멘트가 겹치는(대칭) 부품은 축이 임의라 후보를 더 만든다(축 둘레 90° 회전들). 형상이 같으면 어느 변환이든 결과는 같으므로 대칭성은 문제가 아니다.
- `match_pct < 99`면 경고 — 두 인스턴스가 다른 부품(변형)일 수 있다.

STEP → 파라메트릭 워크플로(CLAUDE.md에 추가): `classify_faces`(정체·주축·레벨·verdict) → `section_profile(position=None)`으로 띠 후보 확인 → 띠마다 `build_features`의 `profile.section`으로 Pad(아래→위, 겹치게) → 홈·립은 `groove`(구성선 축, 폴리곤) → 구멍은 `find_holes` 결과로 `pocket`+`circles`(+`chamfer`) → `compare_shapes`로 차집합 조각의 bbox를 보고 틀린 곳만 고친다. 자유곡면이 많으면(verdict free_form) BaseFeature 하이브리드로.

### 7.21 `make_drawing` (M8)
3D 객체(Body·Part::Feature·Link 그룹)로 TechDraw 페이지를 만들고 PDF/SVG로 내보낸다. 배치는 기본값이고 세밀한 위치는 GUI에서 손으로 옮긴다.
- 입력: `source`(객체 이름 또는 이름 목록 — Link 여러 개면 `Part::Compound`로 묶는다), `doc=None`, `page="Page"`, `template="ISO/A3_Landscape_TD.svg"`, `scale=None`(None이면 뷰가 페이지의 60 %에 들어가게 1:1·1:2·1:5·1:10·1:20·1:50·1:100 중 자동), `views=["front","right","top"]`(+ `"iso"`, 상세는 `{"detail": {"base": "front", "at": [x, z], "radius": 20, "scale": 0.2, "ref": "A"}}`), `dimensions=[{"view": "front", "type": "DistanceX|DistanceY|Distance", "from": {"x":..,"y":..,"z":..}, "to": {...}, "offset": [dx, dy]}]`(정점을 좌표로 찾아 References3D + Projected; 정점이 없으면 실루엣 모서리 두 개 참조로 `"edges_x": [x1, x2]`), `notes=[...]`, `title={"FC-Title": ..., "scale": ..., ...}`, `export="pdf|svg|both|none"`, `out_dir=None`(None이면 문서 폴더 또는 홈)
- 출력: `{"page", "template", "views": [{"name", "type", "scale", "x", "y", "edges"}], "dimensions": [{"name", "type", "value", "status"}], "warnings", "files": {"pdf": path, "svg": path}}`
- 규칙 `[확인됨: api-notes 14장]`: Link는 Compound로; View.X/Y는 addView 뒤에; 치수 ScaleType Custom = 뷰 축척; 페이지 창을 열고(`ViewObject.doubleClicked()`) 내보낸다; 기본 A4 템플릿은 빈 페이지이므로 ISO 템플릿을 기본값으로. 치수 정점을 못 찾으면 그 치수만 건너뛰고 `warnings`에 적는다.
- GUI 없이(FreeCADCmd) 부르면 페이지·뷰·치수는 만들되 내보내기는 건너뛰고 경고.

### 7.22 `inspect_drawing` (M8)
- 입력: `page`, `doc=None`
- 출력: `{"template", "size": [w, h], "views": [{"name", "type", "source", "scale", "x", "y", "status", "edges"}], "dimensions": [{"name", "type", "value", "references": "3D|2D", "status"}], "annotations": [...], "editable_texts": {...}}`
- 치수 값은 `getRawValue()`. `status`가 Touched면 재계산이 필요한 것, Invalid면 참조가 깨진 것.

### 7.23 `import_mesh` (M9)
STL/OBJ/PLY/3MF 메시를 **참고용 Mesh 객체**로 읽는다(변환하지 않는다). 투명도를 올려 새로 그리는 Body와 겹쳐 보게 한다.
- 입력: `path, doc=None, transparency=70, label=None`
- 출력: `{"name", "label", "facets", "points", "is_solid", "non_manifold", "self_intersections", "bbox", "size", "volume"(is_solid일 때), "elapsed_ms"}`
- `is_solid`가 false면 경고(부피·비교 신뢰 불가). 파일이 없거나 형식이 아니면 오류 봉투.
- 방법 `[라이브 1.1.3]`: `Mesh.insert(path, docName)` → `Mesh::Feature`; `Mesh.isSolid()`, `hasNonManifolds()`, `hasSelfIntersections()`, `BoundBox`, `Volume`. `ViewObject.Transparency`로 투명.

### 7.24 `analyze_mesh` (M9)
메시의 **주축·띠(레벨)·단면 원**을 한 번에 뽑는다. `classify_faces`의 메시판 — 삼각형 면을 하나씩 보지 않고 평면 세그먼트와 단면 원 피팅으로 정체를 잡는다.
- 입력: `name, doc=None, axis=None(자동), dev=0.05, min_facets=10, max_levels=30, max_segments=50`
- 출력: `{"main_axis", "main_axis_letter", "levels": [{"position", "area", "facets"}], "center": [x, y] | null(단면 원들의 공통 중심), "bands": [{"from", "to", "mid", "circles": [{"center", "r", "rms"}], "wires": n}], "segments": [{"normal", "position", "area", "facets"}], "verdict": "prismatic|revolved|mixed|free_form", "notes": [...]}`
- 방법 `[라이브 1.1.3]`: `getPlanarSegments(dev, min_facets)`로 평면 세그먼트 → 법선을 면적 가중으로 묶어 주축(가장 큰 평면 면적의 법선) → 주축에 수직인 세그먼트의 위치가 `levels`. 레벨 사이 중간 높이마다 `crossSections`로 폴리라인을 얻어 최소제곱 원 피팅(rms < dev면 원). 원들의 중심이 모두 같으면 `center`(회전체 계열). `getSegmentsOfType("Cylinder")`는 원통을 못 찾는 경우가 많아(스풀 가이드 STL에서 0개) 쓰지 않는다.
- **목록은 개수만**: `levels[].facets`는 숫자다(면 인덱스 목록을 넣으면 5,758면 메시에서 응답이 수백 KB가 된다 — `classify_faces`가 메시 솔리드에서 그랬다).

### 7.25 `section_profile` 메시 입력 (M9)
`name`이 `Mesh::Feature`면 `crossSections`의 폴리라인을 **직선·원호·원으로 피팅**해 7.17과 같은 형식(`elements`, `sketch_plane`)으로 준다. `build_features`의 `profile.section`도 그대로 메시를 받는다.
- 추가 입력: `fit_tolerance=0.05`(피팅 허용 rms, 메시 편차보다 크게), `corner_tolerance=0.15`(꼭짓점 검출 RDP)
- 방법: 폴리라인 전체가 한 원에 맞으면 `circle`. 아니면 Douglas-Peucker로 꼭짓점을 뽑고, 인접 구간을 늘려 가며 원 피팅이 되면 `arc`, 아니면 `line`. 맞지 않는 구간은 그 폴리라인 조각을 `line` 여러 개로 남기고 `unsupported`에 센다(`approximate_bspline`과 같은 취급).
- 출력에 `fit`: `{"points_in", "elements_out", "max_residual"}` 추가. `fill_holes`는 메시에서는 "반지름 `max_fill_radius` 이하의 닫힌 안쪽 원을 버린다"로 동작한다.
- 높이별 단면의 최대 반지름 각도가 z에 비례해 돌면 **나사**다(스풀 가이드: 1 mm당 180° = 피치 2). `analyze_mesh`가 `thread: {major_r, minor_r, pitch, z_from, z_to, handedness}`로 보고하고, 생성은 7.27의 `helix` op로 받는다. 원·직선으로도 나사로도 안 떨어지는 단면만 폴리라인을 `polygon`으로 쓴다.

### 7.26 `compare_shapes` 메시 입력 (M9)
`a`가 `Mesh::Feature`면 **불리언을 쓰지 않는다**. 5,758면 메시 솔리드의 퍼지 차집합은 FreeCAD 메인 스레드를 10분 넘게 잡았다 `[라이브 1.1.3, 2026-09-11]`.
- 방법: `b`(Body)의 면마다 표본점(면 중심 + UV 격자, 전체 ≤ `samples`=2000)을 잡고 법선 방향 ±로 `Mesh.nearestFacetOnRay`를 쏴 메시까지의 거리 = 편차. 반대로 메시 정점 표본(≤ 2000)에서 `b.distToShape(Part.Vertex)`로 역방향 편차. 부피 차·bbox 차는 그대로.
- 출력: `{"volume_a", "volume_b", "volume_diff_pct", "bbox_diff", "deviation": {"max", "mean", "p95", "samples", "worst": [{"point", "distance", "face_b"}]}, "reverse_deviation": {...}, "verdict"}`. verdict: `max < 0.1 mm`·부피 0.5 % 안 → match, 그 밖에 different. 메시 대 메시는 지원하지 않는다.
- `worst` 점의 위치가 곧 "어디가 틀렸나"다(퍼지 차집합 조각의 bbox 역할).

### 7.27 `build_features`의 `helix` op (M9)
나사·나선 홈. `PartDesign::SubtractiveHelix`/`AdditiveHelix` [확인됨: api-notes 16장].
- 피처: `{"op": "helix", "name": "Thread", "profile": {"polygon": [[r, z], ...]}, "axis_center": [cx, cy], "pitch": 2.0, "height": 10.0 | "turns": 5, "angle": 0, "left_handed": false, "reversed": false, "subtractive": true, "outside": false}`
- 프로파일은 축을 지나는 XZ 평면 스케치(로컬 x = 축에서의 반지름, y = 전역 Z). 스케치는 `AttachmentOffset`으로 축을 `axis_center`에 맞춘다(XZ 평면의 로컬 z가 전역 −Y).
- 축은 Z만 지원한다(회전체 부품 기준). 시작 위상은 프로파일의 z가 정한다. 나선은 프로파일 각도(0°)에서 시작해 그 이전 각도의 첫 바퀴는 깎이지 않으므로, 나사가 어떤 면에서 끝나야 하면 한 피치 아래에서 시작하고 그 아래를 Pad로 되메운다(호출자가 한다 — 예제 `examples/stl_spool_guide_with_m7.py`).

### 7.28 `open_document` / `save_document` (M9)
- `open_document(path)` → FCStd를 연다(이미 열려 있으면 그 문서). 출력: `{"name", "label", "filename", "objects", "already_open"}`. 없는 파일·FCStd가 아니면 오류.
- `save_document(doc=None, path=None, overwrite=False)` → `path`가 없으면 `doc.save()`(파일 이름이 없는 새 문서면 오류로 경로를 요구), 있으면 `saveAs`. 다른 기존 파일을 덮어쓸 때는 `overwrite=true`가 있어야 한다. 출력: `{"name", "filename", "bytes", "objects"}`. 사용자가 시키기 전에는 저장하지 않는다는 CLAUDE.md 규칙은 그대로다(툴이 있어도 부르는 건 사용자 지시가 있을 때).

### 7.29 `suggest_sketch_fixes` (M10)
스케치의 문제(열린 끝점·빠진 수평/수직·빠진 같음·중복·충돌·남은 자유도)마다 **고칠 후보**를 만든다. 자동으로 고치지 않는다 — 후보와 예상 효과를 주고 사용자가 고른다.
- 입력: `sketch, doc=None, coincident_tolerance=0.05, angle_tolerance=0.5, equal_tolerance=0.01, evaluate=True, max_suggestions=50`
- 출력: `{"sketch", "before": {"solve_status", "dof", "fully_constrained", "conflicting", "redundant", "malformed", "open_vertices"}, "fingerprint", "suggestions": [{"id", "key", "kind", "action": "add|delete", "targets": ["Line3.end", "Arc2.start"], "constraint_id", "detail", "effect": {"solve_status", "dof", "conflicting", "redundant"}, "confidence": "high|medium|low", "exclusive_with": [ids]}], "recommended": [ids]}`
- 후보 종류 `[라이브 1.1.3 확인, 2026-09-11]`:
  - `add_coincident`: `detectMissingPointOnPointConstraints(tol)` → `MissingPointOnPointConstraints` = (geo1, pos1, geo2, pos2, type). 끝점 거리를 detail에
  - `add_horizontal` / `add_vertical`: `detectMissingVerticalHorizontalConstraints(angle)` → `MissingVerticalHorizontalConstraints` = (geo, pos, -2000, 0, type 2=Horizontal/3=Vertical). 이미 H/V/축평행 제약이 있는 선은 뺀다. 기울기(도)를 detail에
  - `add_equal`: `detectMissingEqualityConstraints(tol)` → `MissingLineEqualityConstraints`(선 쌍), `MissingRadiusConstraints`(원·호 쌍)
  - `delete_constraint`: 솔버의 `RedundantConstraints`(지워도 형상 유지 → high), `ConflictingConstraints`(값이 다른 치수 둘이면 각각 "이것을 삭제" 후보 두 개, `exclusive_with`로 묶음, 결과 치수를 detail에 → medium), `MalformedConstraints`(high)
  - `add_dimension`: 솔브가 되는데 DoF가 남으면 `getGeometryWithDependentParameters()`의 자유 요소마다 원점 기준 DistanceX/DistanceY(현재 값) 또는 Radius(현재 값) 후보 → low(설계 치수는 사용자만 안다)
- `evaluate=True`면 후보마다 **스케치 사본**(`doc.copyObject`)에 적용해 `solve()`하고 DoF·상태 변화를 `effect`에 넣는다(원본은 건드리지 않는다, 사본은 지운다). `recommended`는 effect가 좋아지고(상태 0, DoF 감소, 충돌·중복 없음) confidence가 low가 아닌 것.
- `fingerprint`(요소 수·제약 수·제약 종류 해시)는 apply 때 같은 스케치인지 확인용.

### 7.30 `apply_sketch_fixes` (M10)
- 입력: `sketch, ids=[...], doc=None, fingerprint=None, coincident_tolerance=0.05, angle_tolerance=0.5, equal_tolerance=0.01`
- 같은 허용값으로 후보를 다시 만들어 id를 맞춘다. `fingerprint`가 다르면(그사이 스케치가 바뀜) 오류. `exclusive_with`끼리 같이 고르면 오류.
- 삭제는 인덱스 내림차순으로 먼저, 추가는 그 뒤. 적용 후 `solve()` → `doc.recompute()` → `{"applied": [...], "before", "after": {"solve_status", "dof", "fully_constrained", ...}, "recompute": {"resolved", "new_errors"}}`. 상태가 나빠지면(충돌 생김) 되돌리고 오류로 알린다.
- 사용자가 고른 것만 적용한다. 대화에서는 Claude가 후보를 번호 목록으로 보여 주고 사용자가 번호를 고른다(CLAUDE.md 워크플로).

---

## 8. Claude Code 연결

프로젝트 루트 `.mcp.json` (경로는 절대경로로 사용자 환경에 맞게):
```json
{
  "mcpServers": {
    "cadxray": {
      "command": "uv",
      "args": ["--directory", "/ABS/PATH/cadxray/bridge", "run", "cadxray"]
    }
  }
}
```
또는 CLI:
```bash
claude mcp add --scope project cadxray -- uv --directory /ABS/PATH/cadxray/bridge run cadxray
claude mcp list          # 등록 확인
```
Claude Code 안에서 `/mcp`로 연결 상태를 본다. README에는 위 두 방법을 모두 적고, `claude mcp add` 문법이 바뀌었을 수 있으니 실패하면 `claude mcp add --help`를 보라고 안내한다.

---

## 9. 구현 순서 (마일스톤)

### M1 — 골격과 왕복 확인
1. `addon/CadXray`: `main_thread.py`, `rpc_server.py`, `InitGui.py`, `handlers/documents.py`(`ping`, `list_documents`), `handlers/execute.py`
2. `bridge`: `client.py`, `server.py`에 `ping`, `list_documents`, `execute_code`
3. `scripts/install_addon.py`: OS·버전별 Mod 경로 탐지 → 심링크(실패 시 복사). 경로 후보:
   - macOS: `~/Library/Application Support/FreeCAD/v1-0/Mod/`, `.../v1-1/Mod/`
   - Windows: `%APPDATA%\FreeCAD\Mod\` (1.x 하위 경로 존재 여부 확인)
   - Linux: `~/.local/share/FreeCAD/Mod/`, `~/.local/share/FreeCAD/v1-1/Mod/`, `~/.FreeCAD/Mod/`, Flatpak `~/.var/app/org.freecad.FreeCAD/data/FreeCAD/v1-1/Mod/`, snap `~/snap/freecad/common/Mod/`
4. **완료 기준**: FreeCAD에서 서버 시작 → Claude Code `/mcp`에서 연결 → `ping`이 버전을 돌려주고 `execute_code("print(App.ActiveDocument.Name)")`가 stdout을 돌려준다.

### M2 — 구조 파악 툴
1. `util.py`의 `serialize`, `shape_summary`, 봉투, 크기 제한
2. `get_document_graph`, `inspect_object`, `analyze_shape`
3. **완료 기준**: 테스트 모델(10장)에서 세 툴이 명세의 JSON 형태로 응답하고, 300개 객체 모델에서 `get_document_graph(max_objects=50)`가 `truncated: true`와 함께 20 KB 이하로 나온다.

### M3 — 스케치 진단
1. `docs/api-notes.md`의 4장(스케치)을 **설치된 버전에서** 부록 A.1의 라이브 introspection으로 재확인하고, 다르면 노트에 버전 태그와 함께 추가
2. `get_sketch_diagnostics`
3. **완료 기준**: DOF가 남은 스케치, 충돌 제약 스케치, 열린 와이어 스케치 각각에서 해당 필드가 정확히 채워진다.

### M4 — recompute·스크린샷·개발 편의
1. `tracked_recompute`, `get_screenshot`(MCP Image 반환), `reload_handlers`
2. 자동시작 설정, 포트 설정
3. **완료 기준**: 깨진 Pad를 `execute_code`로 고친 뒤 `tracked_recompute`가 `resolved`에 그 객체를 보고하고, `get_screenshot(view="iso")`가 Claude Code에 이미지로 표시된다.

### M5 — 문서·테스트·정리
1. `README.md`(한국어): 설치 → 서버 시작 → Claude Code 연결 → 사용 예시 프롬프트 → 문제 해결
2. `CLAUDE.md`(10장 워크플로)
3. `tests/in_freecad/test_handlers.py`: `FreeCADCmd tests/in_freecad/test_handlers.py`로 실행 가능하게(GUI 필요한 스크린샷은 스킵)
4. 응답 크기·시간 측정 결과를 README에 표로 기록

### M6 — STEP 가져오기·형상 분석 (M5 이후, 선택)
1. `import_step`, `get_mass_properties`
2. `find_holes` — 반원통 면 병합, 오목/볼록 판정, 관통 휴리스틱
3. `check_interference`
4. **완료 기준**: 테스트 STEP(10장 `T6_step`)에서 구멍 4개의 직경·위치가 실제 값과 0.01 mm 이내로 맞고, 의도적으로 겹쳐 놓은 두 부품이 `interference`로 보고되며, 벤더 어셈블리 STEP(수백 면)에서 `find_holes`가 10초 안에 끝난다.

### M7 — STEP → 파라메트릭 재구성 보조 (M6 이후, 2026-09-10 추가)
손으로 세 번 반복한 절차(면 조사 → 띠 높이 → 단면 트레이스 → 회전 절삭·구멍 → 퍼지 차집합 검증)에서 기계적인 부분을 툴로 만든다. 완전 자동 피처 인식은 비목표 — 어떤 피처로 볼지는 Claude가 정하고, 툴은 측정·트레이스·생성·검증만 한다.
1. `classify_faces` — BSpline 면 정체 판별(평면/원통/원뿔/구), 주축·레벨·verdict
2. `section_profile` — 단면 윤곽을 스케치 요소로, 구멍 자리 3D 메우기, BSpline 곡선 정체 판별
3. `build_features` — 스케치+Pad/Pocket/Groove/Revolution/Fillet/Chamfer를 순서대로 쌓고 피처마다 검증. Block·틈 닫기·구성선 축 규칙 내장. `profile.section`으로 좌표를 토큰에 실어 나르지 않는다
4. `compare_shapes` — 부피·면적·bbox 차 + 퍼지 차집합 조각의 bbox
5. **완료 기준**: `T7_rebuild`(전부 BSpline 면으로 바뀐 프리즘 부품)에서 `classify_faces`가 모든 면을 plane/cylinder로 판별하고 verdict가 prismatic, `section_profile`이 닫힌 윤곽을 Line/Arc만으로 주며, `build_features` 4단계로 재구성한 Body가 `compare_shapes`에서 identical(< 0.001 %). 벤더 부품 2B2를 새 툴만으로 다시 만들어 이전 손 작업과 같은 0.0004 % 이내.

### M7 부록 — 메시(STL)는 M7 툴 + `execute_code`로 (2026-09-11 확인, 별도 마일스톤 없음)
STL은 면·솔리드가 없어 M6·M7 툴이 직접 못 읽지만, 스풀 가이드 STL(5,758면)을 M7 툴만으로 다시 그려 메시 정점 전부가 0.03 mm 안, 부피 차 0.014 %가 나왔다(`examples/stl_spool_guide_with_m7.py`). 절차는 CLAUDE.md "STL → 파라메트릭" 항목. 툴은 M9(7.23~7.27)에서 만든다. 주의: `makeShapeFromMesh` 솔리드에 `compare_shapes`를 부르면 불리언이 10분 넘게 메인 스레드를 잡는다 — 메시 비교는 `execute_code`의 광선 편차로 한다.

### M8 — 2D 도면 (M7 이후, 2026-09-11 추가)
`execute_code`로 손으로 해 본 절차(`examples/techdraw_page_from_assembly.py`, api-notes §14)를 툴로 만든다.
1. `make_drawing` (7.21) — 소스 객체(Body·Part·Link 그룹) → 페이지(템플릿·축척) + 뷰(정면/우측/평면/등각/상세) + 치수(3D 정점·모서리 참조, Projected) + 주석 + 표제란 → PDF/SVG. 뷰 X/Y는 addView 뒤에, 치수 축척은 뷰와 맞추는 규칙 내장
2. `inspect_drawing` (7.22) — 페이지의 뷰·치수·주석 목록과 값, 상태(Touched/Invalid), 내보낸 파일 경로
3. **완료 기준**: `T8_drawing`(T1 PartDesign 부품)에서 `make_drawing`이 3면도 + 치수 4개(길이·폭·높이·구멍 지름)를 만들고 값이 모델과 같으며, PDF가 A4 한 장으로 나온다. 철봉 프레임(Link 27개)에서 상세 2개·치수 13개짜리 페이지가 예제와 같은 결과를 낸다.

### M9 — 문서 저장·열기 + 메시(STL) 툴 (M8 이후, 2026-09-11 추가)
M7 부록의 손 절차(스풀 가이드에서 `execute_code` 200줄)를 툴로 굳힌다. 판독(어떤 피처로 볼지)은 여전히 Claude가 하고, 툴은 읽기·측정·단면 피팅·생성·비교만 한다.
1. `open_document` / `save_document` (7.28)
2. `import_mesh` (7.23), `analyze_mesh` (7.24) — `handlers/mesh.py`
3. `section_profile` 메시 입력 (7.25), `build_features`의 `profile.section`도 메시를 받게
4. `compare_shapes` 메시 입력 (7.26) — 불리언 없이 법선 광선 편차
5. `build_features`의 `helix` op (7.27)
6. `classify_faces`·`section_profile`의 `levels[].faces` 목록 상한(`max_level_faces`, 기본 20)
7. **완료 기준**: `T9_mesh`(T7 "Plate"를 STL로 내보내 다시 읽은 "PlateMesh")에서 `import_mesh`가 is_solid, `analyze_mesh`가 levels [0, 6, 10] ±0.02·verdict prismatic, `section_profile(z=3)`이 선분 4개(안쪽 원 버림)·`z=8`이 선분 4개 + 원 2개(r 3.3 ±0.02), 그 단면으로 `build_features` → `compare_shapes(PlateMesh, Body)`가 max 편차 < 0.05 mm·부피 0.5 % 안. `helix` op로 판 위 원기둥에 피치 2 홈을 판 Body가 유효하고 부피가 줄며, 그것을 메시로 바꿔 `analyze_mesh`가 pitch 2 ±0.05를 잡는다. `save_document`→`open_document` 왕복 뒤 객체 수가 같다.

### M10 — 제약 오류 자동 수정 제안 (M9 이후, 2026-09-11 추가)
`get_sketch_diagnostics`가 찾은 문제를 고칠 후보로 바꾸고, 사용자가 고른 것만 적용한다. FreeCAD의 `detectMissing*`·`MissingXxxConstraints`·솔버 목록·`getGeometryWithDependentParameters`를 쓴다(api-notes 4장 + 라이브 확인).
1. `suggest_sketch_fixes` (7.29) — `handlers/sketch_fix.py`
2. `apply_sketch_fixes` (7.30)
3. CLAUDE.md 진단 워크플로 5단계에 넣는다: 진단 → 후보 목록(번호) → 사용자 선택 → 적용 → `tracked_recompute`
4. **완료 기준**: `T4_open_wire`에서 열린 끝점 쌍에 `add_coincident` 후보가 나오고 적용하면 `open_vertices`가 0, `T3_conflict`에서 충돌 치수 둘에 대해 `delete_constraint` 후보 두 개가 `exclusive_with`로 묶여 나오며 하나를 적용하면 solve 0, `T2_underconstrained`에서 `add_dimension`/`add_horizontal` 후보 적용으로 DoF 0. `T10_fixes`(0.02 벌어진 사각형 + 0.3° 기운 선 + 같은 길이 선 + 같은 반지름 원)에서 후보 4종이 모두 나오고 `recommended`만 적용하면 열린 끝점 0·DoF 감소. 원본 스케치는 evaluate 뒤에도 제약 수가 같다. 잘못된 id·바뀐 fingerprint는 오류.

---

## 10. 검증 시나리오와 CLAUDE.md 워크플로

### 테스트 모델 (`tests/fixtures/make_test_models.py`, FreeCAD 안에서 실행)
| 문서 | 내용 | 기대 진단 |
|---|---|---|
| `T1_clean` | 완전 구속 사각 스케치 + Pad + 구멍 Pocket | invalid 0, dof 0, valid shape |
| `T2_underconstrained` | 제약 2개 빠진 스케치 | dof > 0, fully_constrained false |
| `T3_conflict` | 같은 선에 길이 제약 두 개(값 다름) | solve 실패, conflicting에 두 인덱스 |
| `T4_open_wire` | 한 점이 안 맞물린 사각형 + Pad | Pad Invalid, open_vertices 1개, status에 원인 문자열 |
| `T5_large` | 300개 이상 객체(배열/복제) | truncated 동작, 응답 < 20 KB, 응답 시간 < 5초 |
| `T6_step` | T1을 STEP으로 내보낸 뒤 다시 가져온 것 + Ø6.6 구멍 4개 판 + 일부러 겹치게 놓은 블록 2개 (fixtures가 `Import.export`로 생성) | 히스토리 없음(스케치 0), `find_holes`가 구멍 4개·Ø6.6, `check_interference`가 블록 쌍을 `interference`로 보고 |
| `T7_rebuild` | 단차 판(60×40×10, 위 절반 4 mm 단차) + Ø6.6 관통 2개 + Ø10×3 카운터보어 + 0.5 챔퍼를 `Part::Feature` "Plate"로, 같은 형상을 `transformGeometry`로 전부 BSpline 면으로 바꾼 "PlateB" (M7) | `classify_faces(PlateB)`: 면 전부 plane/cylinder, verdict prismatic, levels [0, 6, 10]. `section_profile(z=3)`: 닫힌 선분 4개(구멍 메움). `build_features` Pad·Pad·Pocket·Pocket·Chamfer → `compare_shapes(Plate, Body)` identical |
| `T8_drawing` | T1(PartDesign 판 + 구멍)과 pole_frame(Link 27개, `examples/pole_frame_from_dxf.py`) (M8) | `make_drawing(T1)`: 뷰 3개·치수 4개 값이 모델과 같음, PDF A4 1장. `inspect_drawing`이 치수 값을 그대로 돌려줌 |
| `T9_mesh` | T7의 "Plate"를 `MeshPart.meshFromShape`(LinearDeflection 0.02)로 STL에 내보내 `Mesh.insert`로 다시 읽은 `Mesh::Feature` "PlateMesh" (M9) | `import_mesh`: is_solid. `analyze_mesh`: levels [0, 6, 10], verdict prismatic. `section_profile(PlateMesh, z=3)`: 선분 4개. `build_features` → `compare_shapes(PlateMesh, Body)` max 편차 < 0.05 |
| `T10_fixes` | 0.02 mm 벌어진 사각형(끝점 3곳만 일치) + 0.3° 기운 선 + 길이 같은 선 2개 + 반지름 같은 원 2개 (M10) | `suggest_sketch_fixes`: add_coincident 1, add_horizontal/vertical ≥ 4, add_equal 2(선·반지름), effect 있음. `apply_sketch_fixes(recommended)` 뒤 open_vertices 0, DoF 감소 |

### CLAUDE.md에 넣을 진단 워크플로 (이 MCP를 사용하는 AI용)
1. `ping` → 연결·버전 확인
2. `list_documents` → 대상 문서 확정
3. `get_document_graph` (기본 `max_objects`) → `invalid_objects`와 `summary`부터 본다
4. 문제 객체가 스케치면 `get_sketch_diagnostics`, 형상이면 `analyze_shape`, 그 외는 `inspect_object`
5. 원인을 사용자에게 한 문장으로 설명하고 수정 방향을 제시한 뒤 `execute_code`로 수정
6. `tracked_recompute`로 결과 확인 → 필요 시 `get_screenshot(view="iso")`
7. 전체 트리 덤프(`max_objects` 크게)는 사용자가 명시적으로 원할 때만
8. 수정 코드 작성 시: FreeCAD 1.1에는 `Sketch.movePoint`가 없다(`moveGeometry`/`moveGeometries` 사용). `ping`의 버전을 보고 결정한다

---

## 11. 알려진 함정

- **메인 스레드**: RPC 스레드에서 FreeCAD 객체를 만지면 크래시하거나 멈춘다. 모든 핸들러는 `main_thread.submit`을 거친다. 예외 없음.
- **FreeCAD 1.0/1.1 API 차이** `[확인됨]`: 진단에 쓰는 API는 두 버전이 같다. 다른 것은 바인딩 정의 파일 형식(1.0 `*Py.xml` → 1.1 `*.pyi`), 1.1에서 `Sketch.movePoint` 삭제(`moveGeometry`로 대체), `getStatusString()`의 `"Freezed"` 추가, PySide 2/6 차이(`from PySide import QtCore`로 통일). `util.freecad_version()`으로 분기하고 새로 확인한 것은 `docs/api-notes.md`에 남긴다.
- **XML-RPC 타입 제한**: 32비트 초과 정수·bytes·None. 응답을 JSON 문자열로만 넘겨 회피한다. PNG는 base64.
- **출력 폭발**: 사람이 만든 모델은 `Sketch017`, `Pad009`처럼 이름이 의미 없고 객체가 수백 개다. 요약·집계는 전체, 상세는 상한 — 이 원칙을 모든 툴에 적용한다.
- **스크린샷은 GUI 전용**: FreeCADCmd에서는 에러 봉투를 돌려준다.
- **애드온 코드 변경 반영**: `InitGui.py`·`rpc_server.py` 변경은 FreeCAD 재시작 필요. 핸들러만 바꿨으면 `reload_handlers`.
- **포트 충돌**: neka-nat 애드온(9875)과 공존. 두 서버를 같이 켜도 되지만 Claude Code에는 두 MCP의 `execute_code`가 모두 보이므로 툴 이름 충돌을 피하려면 이 서버의 툴 이름을 그대로 두고, 필요 시 사용자가 한쪽 MCP를 끈다.
- **recompute 부작용**: `tracked_recompute`는 문서를 실제로 바꾼다. 툴 docstring에 명시한다.
- **`execute_code` 중단 불가**: 무한 루프면 FreeCAD가 멈춘다. 코드를 짧게 나눠 실행하라고 CLAUDE.md에 적는다.

---

## 12. 이후 확장 후보 (v1 이후, 지금은 구현하지 않음)

- ~~헤드리스 배치(FreeCADCmd + 파일 경로로 문서 열기 툴)~~ — 2026-09-11 사용자 판단으로 제외
- 벽 두께 분석(단면 `slice` 기반 근사), 어셈블리 Link 너머 문서 추적
- ~~원격 호스트 접속(허용 IP 목록)~~ — 2026-09-11 제외. 다른 PC의 FreeCAD가 필요해지면 코드 수정 없이 SSH 터널(`ssh -L 9877:localhost:9877 원격PC`)로 먼저 쓴다. execute_code가 있어 원격을 여는 것은 그 PC를 여는 것과 같다
- Addon Manager 배포용 `package.xml` 완성


---

## 부록 A. FreeCAD 소스 참조 지도

FreeCAD 저장소 전체를 문서화하지 않는다. 이 MCP가 쓰는 Python API의 정의는 각 모듈의 바인딩 정의 파일(1.0.x는 `*Py.xml`, 1.1.x는 `*.pyi` — 메서드·속성·docstring이 여기서 생성됨)에 있다. 아래 파일들은 로컬 `docs/freecad-src-ref/1.0.2/`와 `docs/freecad-src-ref/1.1.3/`에 받아 두고 봤으며(LGPL이라 **저장소에는 넣지 않는다**, gitignore), 거기서 확인한 사실이 `docs/api-notes.md`에 정리되어 있다. 설치 버전이 두 태그와 다를 때만 A.2로 그 태그를 받는다.

### A.1 검증 순서 (반드시 이 순서로)
1. **라이브 introspection 먼저** — 실행 중인 FreeCAD에 `execute_code`로 물어본다. 설치된 버전의 실제 API가 나오므로 가장 정확하다.
   ```python
   import Sketcher, Part
   sk = doc.getObject("Sketch")
   _result = {
       "version": App.Version()[:3],
       "sketch_attrs": [a for a in dir(sk) if not a.startswith("_")],
       "solver_attrs": [a for a in dir(Sketcher.Sketch()) if not a.startswith("_")],
       "solve_doc": sk.solve.__doc__,
       "status_doc": sk.getStatusString.__doc__,
       "shape_check_doc": Part.Shape.check.__doc__,
   }
   ```
   확인할 것: `DoF`, `ConflictingConstraints`, `RedundantConstraints`, `PartiallyRedundantConstraints`, `MalformedConstraints`, `FullyConstrained`, `OpenVertices`, `MissingPointOnPointConstraints`, `GeometryFacadeList`, `getConstruction`, `AttachmentSupport`가 `sketch_attrs`에 있는지, `solve_doc`의 반환 코드가 api-notes 4.2와 같은지, 1.1이면 `movePoint`가 없고 `moveGeometry`가 있는지.
2. **소스는 "의미" 확인용** — 반환 코드 의미, 속성이 언제 갱신되는지(solve 후인지 recompute 후인지), 외부 지오메트리 인덱스 규칙처럼 docstring만으로 부족한 것만 소스에서 본다.
3. 확인 결과는 `docs/api-notes.md`에 **버전 태그와 함께** 기록한다. 예: `[1.0.1] sk.DoF 존재, solve() 이후 갱신됨`.

### A.2 소스 받기 (sparse checkout)
전체 클론(수 GB)은 하지 않는다. 설치된 버전과 같은 태그를 받는다(`App.Version()`으로 확인).
```bash
git clone --filter=blob:none --sparse --depth 1 --branch <설치된 버전 태그> \
    https://github.com/FreeCAD/FreeCAD.git freecad-src
cd freecad-src
git sparse-checkout set src/App src/Base src/Gui \
    src/Mod/Sketcher/App src/Mod/Part/App src/Mod/PartDesign/App
```
태그 이름은 `git ls-remote --tags https://github.com/FreeCAD/FreeCAD.git | grep -E '1\.[01]'`로 확인한다(2026-09 기준 최신: 1.0.2, 1.1.3). `freecad-src/`는 `.gitignore`에 넣는다. 1.1.x에서는 아래 표의 `*Py.xml`을 같은 이름의 `*.pyi`(예: `SketchObjectPy.xml` → `SketchObject.pyi`)로 바꿔 읽는다.

### A.3 파일 지도

| 파일 | 여기서 확인할 것 | 관련 툴 |
|---|---|---|
| `src/App/DocumentObjectPy.xml` | `State`, `getStatusString()`(Invalid일 때 에러 설명을 주는지), `OutList`, `InList`, `isValid()`, `recompute()`, `ExpressionEngine`, `Visibility` | get_document_graph, inspect_object, tracked_recompute |
| `src/App/DocumentObject.cpp`, `DocumentObjectPyImp.cpp`, `DocumentObject.h` | `getStatusString()` 구현(에러 설명 반환), `State` 문자열 목록, `Label`/`ExpressionEngine`/`Visibility` 프로퍼티 | tracked_recompute, get_document_graph |
| `src/App/DocumentPy.xml` | `recompute()` 시그니처와 반환값, `Objects`, `RootObjects`, `FileName`, `Modified` | list_documents, tracked_recompute |
| `src/App/PropertyContainerPy.xml` | `PropertiesList`, `getPropertyByName`, `getTypeIdOfProperty`, `getGroupOfProperty` | inspect_object |
| `src/Base/VectorPy.xml`, `PlacementPy.xml`, `RotationPy.xml`, `BoundBoxPy.xml` | 직렬화에 쓸 속성 이름(`Base`, `Rotation`, `Axis`, `Angle`, `XMin`…`ZMax`, `XLength`…) | util.serialize |
| `src/Mod/Sketcher/App/SketchObjectPy.xml` (1.1: `SketchObject.pyi`) | `solve()` 반환 코드, `DoF`, `ConflictingConstraints`, `RedundantConstraints`, `PartiallyRedundantConstraints`, `MalformedConstraints`, `OpenVertices`, `MissingPointOnPointConstraints`, `GeometryFacadeList`, `getConstruction`, `detect*` | get_sketch_diagnostics |
| `src/Mod/Sketcher/App/SketchObject.cpp`, `SketchObject.h` | `FullyConstrained`(C++ PropertyBool)가 solve 성공 시에만 갱신되는 지점, `getLastConflicting` 등 | get_sketch_diagnostics의 `fully_constrained` 해석 |
| `src/Mod/Sketcher/App/SketchPy.xml` (1.1: `Sketch.pyi`) | 솔버 객체 `Sketcher.Sketch` — 참고만. SketchObject 속성으로 충분하므로 **사용하지 않음** | — |
| `src/Mod/Sketcher/App/ConstraintPy.xml` (1.1: `Constraint.pyi`), `Constraint.h` | `Type`, `Name`, `First/FirstPos`, `Second/SecondPos`, `Third/ThirdPos`, `Value`, `Driving`, `IsActive`, `InVirtualSpace`; `Constraint.h`의 타입 문자열 목록 | 제약 목록 |
| `src/Mod/Sketcher/App/GeometryFacadePy.xml` (1.1: `GeometryFacade.pyi`) | `Construction`, `Blocked`, `Id`, `InternalType`, `GeometryLayerId` | 지오메트리 목록의 construction 플래그 |
| `src/Mod/Sketcher/App/GeoEnum.h` | GeoId 규칙(-1 H축, -2 V축, -3 이하 외부, -2000 미정의), `PointPos`(0 none/1 start/2 end/3 mid) | 제약 인덱스 해석 |
| `src/Mod/Sketcher/App/SketchAnalysis.cpp` | `OpenVertices` 계산 방식(Shape 기준, 로컬 좌표), `detectMissingPointOnPointConstraints` | get_sketch_diagnostics |
| `src/Mod/Part/App/TopoShapePy.xml` (1.1: `TopoShape.pyi`), `src/App/ComplexGeoDataPy.xml` (1.1: `ComplexGeoData.pyi`) | `isValid()`, `check(runBopCheck)`(예외로 보고), `isNull()`, `isClosed()`, `Volume`, `Area`, `Solids/Shells/Faces/Edges/Vertexes`; `BoundBox`·`CenterOfGravity`는 ComplexGeoData 쪽 | analyze_shape |
| `src/Mod/Part/App/TopoShapeFacePy.xml`, `TopoShapeEdgePy.xml` (1.1: `TopoShapeFace.pyi`, `TopoShapeEdge.pyi`) | `Surface`, `Curve`, `Area`, `Length`, `Orientation`, `Closed`, `Degenerated` | analyze_shape 상세 |
| `src/Mod/Part/App/LineSegmentPy.xml`, `CirclePy.xml`, `ArcOfCirclePy.xml`, `PointPy.xml`, `BSplineCurvePy.xml`, `EllipsePy.xml` + 부모 `ConicPy.xml`, `ArcOfConicPy.xml`, `BoundedCurvePy.xml` (1.1: 같은 이름 `.pyi`) | 좌표 속성명 — `Center`는 Conic/ArcOfConic, `StartPoint/EndPoint`는 LineSegment·BSplineCurve·BoundedCurve(호)에 있음 | 스케치 지오메트리 좌표 |
| `src/Mod/Part/App/BodyBase.h`, `src/App/GroupExtension.h`, `src/Mod/PartDesign/App/FeatureAddSub.h`, `Feature.h` | `Tip`(BodyBase), `Group`(GroupExtension), `AddSubShape`(FeatureAddSub), `BaseFeature` | get_document_graph의 bodies, analyze_shape의 feature_own_shape |
| `src/Gui/View3DPy.cpp` | `saveImage(path, w, h, background, comment, samples)` 인자 파싱, 배경 문자열 처리(QColor 이름), 뷰 프리셋 메서드 목록, `fitAll()` | get_screenshot |
| `src/App/ApplicationPy.cpp` | `Version()` 리스트 순서(Major, Minor, Point, Revision, URL, Date, Branch, Hash) | ping, util.freecad_version |

### A.4 온라인 참조 (소스 대신 빨리 볼 때)
- Python API 레퍼런스(Doxygen): https://freecad.github.io/SourceDoc/ — 클래스별 Python 메서드 목록
- 위키 "Sketcher scripting", "Part scripting", "FreeCAD Scripting Basics" — 예제 코드. 단 위키는 버전 표기가 없는 경우가 많으니 최종 확인은 A.1의 라이브 introspection으로 한다.

### A.5 하지 말 것
- `src/Mod/Sketcher/App/planegcs/`(솔버 내부), `src/3rdParty/`, `src/Mod/*/Gui/`(TaskPanel 등 GUI 코드) — 이 MCP에는 필요 없다. 읽지 않는다.
- 소스 전체를 요약한 문서를 만들지 않는다. `docs/api-notes.md`에는 **실제로 확인한 사실**만 버전 태그와 함께 적는다.
