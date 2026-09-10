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
- 부품 라이브러리 삽입, FEM, TechDraw, 어셈블리 전용 툴 (STEP 가져오기·형상 분석은 7.12~7.15, M6에 포함)
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

- 헤드리스 배치(FreeCADCmd + 파일 경로로 문서 열기 툴)
- `open_document(path)` / `save_document` (FCStd 저장·열기 — STEP은 7.12로 해결)
- 벽 두께 분석(단면 `slice` 기반 근사), 어셈블리 Link 너머 문서 추적
- 제약 오류 자동 수정 제안(`autoconstraint`, `detectMissingPointOnPointConstraints` 활용)
- 원격 호스트 접속(허용 IP 목록)
- Addon Manager 배포용 `package.xml` 완성

---

## 부록 A. FreeCAD 소스 참조 지도

FreeCAD 저장소 전체를 문서화하지 않는다. 이 MCP가 쓰는 Python API의 정의는 각 모듈의 바인딩 정의 파일(1.0.x는 `*Py.xml`, 1.1.x는 `*.pyi` — 메서드·속성·docstring이 여기서 생성됨)에 있다. 아래 파일들은 **이미 받아서 `docs/freecad-src-ref/1.0.2/`와 `docs/freecad-src-ref/1.1.3/`에 들어 있고**, 거기서 확인한 사실이 `docs/api-notes.md`에 정리되어 있다. 설치 버전이 두 태그와 다를 때만 A.2로 그 태그를 받는다.

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
