# cadxray — Claude Code 작업 지침

## 문서
- 명세: `CADXRAY_SPEC.md` — 0장 작업 지침, 7장 툴 명세, 9장 마일스톤 순서, 부록 A 소스 지도
- API 근거: `docs/api-notes.md` — FreeCAD 1.0.2·1.1.3에서 확인한 사실. `[확인됨]` 표시의 출처
- 소스 발췌: `docs/freecad-src-ref/<태그>/src/...` — 노트에 없는 것을 찾을 때만 grep. 1.0은 `*Py.xml`, 1.1은 `*.pyi`. **저장소에는 없다**(LGPL 발췌라 gitignore). 로컬에 없으면 `CADXRAY_SPEC.md` 부록 A.2대로 받는다

## 규칙
- 명세 9장의 마일스톤 순서대로. 마일스톤이 끝나면 **멈추고** 결과와 사용자가 할 일을 보고한다
- 명세에 없는 툴은 추가하지 않는다. 필요하면 제안만
- API를 추측으로 쓰지 않는다. 노트 → 소스 → 라이브 introspection 순으로 확인하고, 새로 확인한 것은 노트에 버전 태그와 함께 추가
- 포트(9877)·경로·툴 이름을 바꿔야 하면 먼저 묻는다
- 사용자는 비개발자다. 실행 명령은 복사해서 그대로 쓸 수 있게, 설명은 짧게, 한국어로

## 코드
- 애드온: FreeCAD 내장 Python(버전에 따라 3.10~3.12)에서 돈다. 외부 패키지 없이 stdlib + PySide만
- 브릿지: Python ≥3.10, 의존성 `mcp`만. `uv run cadxray`로 실행
- 핸들러는 순수 함수: 입력은 키워드 인자, 출력은 JSON 직렬화 가능한 dict(봉투 형식). 예외는 잡아서 봉투로
- FreeCAD 객체 접근은 항상 `main_thread.submit`을 통해서. 예외 없음
- 모든 목록형 응답은 `max_*` 파라미터와 `truncated` 플래그를 가진다. 요약은 전체 기준, 상세는 상한까지

## 커밋
- 마일스톤마다 커밋. 메시지는 한국어로, 무엇이 동작하게 됐는지 한 줄

## 테스트
- `"C:\Program Files\FreeCAD 1.1\bin\freecadcmd.exe" tests\in_freecad\test_handlers.py` — 서버 없이 핸들러를 직접 돌린다. GUI가 없어 스크린샷은 SKIP
- 핸들러를 고쳤으면 `reload_handlers` 툴로 다시 읽는다. `init_gui.py`·`rpc_server.py`·`handlers/__init__.py`·`main_thread.py`를 고쳤을 때만 FreeCAD 재시작
- 브릿지(`bridge/`)를 고쳤으면 Claude Code에서 `/mcp` → Reconnect

## 진단 워크플로 (이 MCP를 쓰는 Claude용)
1. `ping` → 연결·버전 확인. `freecad_version`이 1.0인지 1.1인지 기억한다
2. `list_documents` → 대상 문서 확정. 여러 개면 사용자에게 묻는다
3. `get_document_graph` (기본 `max_objects`) → `invalid_objects`와 `summary`부터 본다. `warnings`에 "dof/fully_constrained 값이 서로 맞지 않습니다"가 있으면 그 스케치는 4번으로
4. 문제 객체가 스케치면 `get_sketch_diagnostics`, 형상이면 `analyze_shape`, 그 외는 `inspect_object`
5. 원인을 사용자에게 한 문장으로 설명한다. 스케치 문제면 `suggest_sketch_fixes` → 후보를 **번호 목록**으로 보여 주고(대상·효과·확신도, 충돌 삭제는 "둘 중 하나") 사용자가 고른 번호만 `apply_sketch_fixes(ids, fingerprint)`. `recommended`는 추천일 뿐 자동 적용하지 않는다. 스케치가 아닌 문제는 `execute_code`로 수정
6. `tracked_recompute`로 결과 확인 → `resolved`에 들어갔는지, `new_errors`가 없는지. 필요 시 `get_screenshot(view="iso")`
7. 전체 트리 덤프(`max_objects` 크게)는 사용자가 명시적으로 원할 때만

### STEP(벤더 부품) 분석 워크플로
`import_step` → `get_document_graph`(부품 계층; 객체 Name은 `Part__Feature…`, 원래 이름은 Label) → `analyze_shape(bop_check=True)`로 유효성 → 목적에 따라 `find_holes`(마운팅 홀 직경·피치) / `check_interference`(부품 쌍 겹침) / `get_mass_properties`(밀도를 주면 질량) → 수정이 필요하면 `PartDesign::Body`를 만들고 `BaseFeature`에 넣은 뒤 `execute_code`로 Pocket·Hole을 쌓는다. STL/OBJ(메시)는 면·솔리드가 없어 이 툴들로 분석할 수 없다 — 사용자에게 STEP을 요청한다.

### STEP → 파라메트릭 재구성 워크플로 (M7)
1. `classify_faces` → `rebuild.verdict`(prismatic / mixed / free_form), `main_axis`, `levels`(띠 경계 높이), `radii`. BSpline 면이 사실 원통·원뿔인지 여기서 갈린다. free_form 면적이 크면 BaseFeature 하이브리드(원본 위에 피처)로 간다
2. `section_profile(position=None)` → `vertex_positions`로 띠·홈·립의 z 경계를 읽는다. 기준점(X0, Y0, Z0)은 정점에서 읽고 나머지는 설계값으로 정리한다
3. 띠마다 `build_features`의 `profile.section`(좌표를 토큰에 싣지 않는다)으로 Pad. 아래 띠 → 가운데 → 위 띠 순으로 **겹치게**(떨어진 Pad는 한 Body에 못 넣는다). 회전 홈·립은 `groove` + `polygon`/`polygons`(축 한쪽에만), 360° 절삭이 깎아 버린 귀는 `section`의 `exclude`(원 밖)·`clip`(범위 안)으로 다시 Pad. 구멍은 `find_holes` 값으로 `pocket` + `circles`(지름은 `expr`로 Params에), 챔퍼는 `chamfer` + 모서리 필터
4. 반지름·중심은 `classify_faces`가 준 **측정값 그대로** 쓴다(반올림하면 겹친 면이 9e-6 어긋나 fuse가 부피를 잃는다)
5. `compare_shapes(a=원본, b=Body, doc_b=새 문서)` → `verdict`와 `missing_in_b`/`extra_in_b` 조각의 bbox로 틀린 곳만 고친다. 조각이 없는데 부피가 다르면 `created[].volume_after`를 단계별로 비교한다
6. `build_features`가 `stopped_at`을 돌려주면 그 피처의 `status`가 원인이다. 실패한 객체는 문서에 남는다(Body.Tip이 그것을 가리키므로 지우면 Tip을 되돌린다)
7. 어셈블리 전체를 다시 만들 때: 같은 부품(면 수·부피·크기가 같은 것)은 **종류당 Body 하나**만 만들고, 인스턴스는 `align_shapes(기준 인스턴스, 인스턴스)`의 `matrix`를 `App::Link.Placement`에 넣는다. STEP의 `Placement`는 인스턴스 변환이 아니다. `mirrored: true`면 `Part::Mirroring` 본을 만들어 그것을 다시 정렬한다. 한 문서에 여러 종류를 만들 때는 파라미터·피처 이름에 종류 접두사를 붙인다(`examples/assemble_from_bodies.py`)

### STL(메시) → 파라메트릭 워크플로 (M9 툴, `examples/stl_spool_guide_with_m7.py`는 툴 전 손 절차)
1. `import_mesh(path)` → 참고 메시(투명 70). `is_solid`가 false면 부피·비교를 믿지 않는다
2. `analyze_mesh(name)` → `main_axis`, `levels`(띠 경계), `bands[].circles`(띠별 단면 원의 중심·반지름), `center`(공통 중심), `thread`(피치·외경·골·방향·z 범위), `verdict`. 축이 이상하면 `axis="X|Y|Z"`
3. 띠마다 `build_features`의 `profile.section={"of": 메시이름, "position": z}` 로 Pad/Pocket (좌표를 토큰에 싣지 않는다). 원은 `analyze_mesh`의 반지름·중심을 `circles`로 직접 써도 된다. 단면이 원·직선으로 안 떨어지면 `section_profile(name, position, fit_tolerance=…)`로 먼저 보고, `unsupported` 구간은 `polygon`으로
4. 나사는 `{"op": "helix", "profile": {"polygon": [[r, z], ...]}, "axis_center": center, "pitch": …, "height": …}` — 골 단면 한 피치 전체, 한 피치 아래에서 시작(Height +2피치), 아래 잘린 곳은 Pad로 되메움. 위상은 프로파일 z가 정한다
5. `compare_shapes(a=메시, b=Body)` → 불리언 없이 `deviation`(Body→메시)·`reverse_deviation`(메시→Body)의 max/p95와 `worst` 점. 최대 편차가 큰 점의 위치가 틀린 곳. `makeShapeFromMesh` 솔리드를 넘기지 않는다(불리언 10분)
6. 저장은 `save_document(doc, path)` — 사용자가 시킬 때만

### 2D 도면 워크플로 (M8)
1. 소스 정하기: Body 하나면 그 이름, Link 어셈블리면 그룹 이름(툴이 Part::Compound로 묶는다)
2. `make_drawing(source, views=["front","right","top"(+"iso")], dimensions=[...], notes=[...], title={...}, export="pdf")`. 축척은 비우면 자동(페이지 60 %). 치수는 모델 **정점 좌표**로 지정(`from`/`to`), 원통 실루엣 사이는 `edges={"axis":"x","at":[x1,x2]}`, 구멍은 `type="Diameter", center, radius`. 정점 좌표는 `inspect_object`/`analyze_shape`의 bbox나 `find_holes`에서 읽는다
3. 응답의 `dimensions[].value`가 모델 값과 같은지, `warnings`의 "건너뜀"(정점을 못 찾은 치수)을 본다. `views[].edges`가 0이면 소스가 빈 것
4. 겹침·위치는 `offset`으로 조정하거나 GUI에서 끌어 옮긴다(기본 배치는 대략이다). 큰 어셈블리(Link 수십 개)는 투영에 1분 넘게 걸린다 — `wait_seconds`
5. `inspect_drawing(page)`로 최종 확인. PDF 경로는 `files.pdf`

### 3D 프린트 출력용 검토 워크플로 (M12)
1. 프로파일을 확인한다: 재질(PLA/PETG/ABS/ASA/TPU/Nylon)·노즐·레이어·베드. 모르면 PLA·0.4·0.2·220×220×250으로 하고 그렇게 말한다. 출력 방향은 +Z, 바닥은 가장 낮은 면
2. `check_printability(name, profile)` → `issues`를 번호 목록으로(종류·심각도·위치·fix 힌트). `score`는 참고값. 재질 표는 경험값이라 `warnings`를 그대로 전한다
3. 오버행이 크면 `suggest_orientation` 후보 순위를 보여 주고 사용자가 고르면 `apply=<rank>`
4. `fixes` 중 사용자가 고른 것만 `apply_print_fixes(fixes=[...])` (Body만). 오버행 챔퍼·얇은 벽·분할은 `fix: manual` — `build_features`로 손으로
5. 다시 `check_printability`로 확인, `estimate_print`로 무게·시간·비용

### 구조 해석(FEM) 워크플로 (M13)
1. 사용자에게 셋을 확인한다: 재질(표 이름 또는 E·항복강도), 어디를 잡는지(고정 면), 어디에 얼마(힘 N·방향, 압력 MPa, 자중). 면은 "bottom"/"top" 같은 극단 이름이나 `{"near": [x,y,z]}`(구멍·돌기 좌표는 `find_holes`·`analyze_shape` bbox에서)로 지정한다. 모르면 PLA·자중만으로 시작한다고 말한다
2. `setup_analysis(name, material, fixed, loads)` → `fixed[].faces`·`loads[].faces`가 의도한 면인지 면적으로 확인. 절점이 30만 개를 넘으면 `mesh_size`를 키운다
3. `run_analysis` → `summary.safety_factor`·`verdict`·핫스팟 `face`/`at`를 한 문장으로. 곧바로 `get_screenshot(view="iso")`로 컬러맵을 보여 준다. warnings에 특이점 경고가 있으면 `safety_factor_p99`를 같이 말한다
4. 안전율이 목표(기본 2) 미만이면 `suggest_reinforcement` → 후보를 **번호 목록**으로(종류·기대 안전율·확신도). 사용자가 고르면 `build_features`/`execute_code`로 반영하고 3번을 다시 한다
5. 변위를 보고 싶으면 `inspect_results(field="displacement", show="displacement")`. 해석 객체는 문서에 남는다(같은 이름으로 setup하면 지우고 다시 만든다)
6. 한계를 항상 붙인다: 선형 정적·등방성, FDM 출력물은 층 방향으로 더 약함, 재질 표는 경험값

### 읽을 때 주의
- `suggest_sketch_fixes`의 `effect`는 사본에서 잰 값이다. `add_dimension`(low)은 현재 값을 치수로 굳히는 것이라 설계 치수인지 사용자에게 확인한다. `open_vertices`는 Shape 기준이라 solve만으로는 안 바뀐다(툴이 recompute한다)
- `get_sketch_diagnostics`: `solve_status`가 0이 아니면 `fully_constrained`는 `null`이고 `dof`도 믿을 수 없다. 어느 목록(`conflicting`/`redundant`/`malformed`)이 찼는지로 판단한다. 값이 다른 치수 두 개는 `-4`(과구속)로 나오고 `conflicting`에 들어간다
- 제약 번호는 `id`(1-based, GUI 제약 패널과 같음)와 `index`(0-based, `sk.Constraints[index]`)가 같이 온다. 사용자에게는 `id`로 말한다
- `open_vertices`는 열린 곳 한 군데당 2개(양쪽 끝점)다
- `analyze_shape`의 `shape`는 PartDesign 피처면 Body 누적 형상이다. 피처 자체는 `feature_own_shape`
- `tracked_recompute`에서 실패한 객체는 `Invalid`와 함께 `Touched`도 남는다. 에러 판단은 `Invalid`(= `new_errors`/`persistent`)로
- `find_holes`의 `through`는 휴리스틱이다(구멍 양 끝 바깥이 재료 밖인지). 포켓 바닥으로 뚫린 구멍은 관통으로 보일 수 있다. `center`는 구멍 축의 중간점, `start`/`end`가 양 끝
- `check_interference`는 `distToShape`가 0일 때만 `common()`을 부른다. 큰 어셈블리는 `names`를 좁혀서 여러 번 부른다
- `classify_faces`의 `method: "fit"` 면은 `residual`이 있다. free_form인데 `best_axis_fit.residual`이 작으면 `tolerance`를 그 값보다 크게 주고 다시 부른다
- `section_profile`의 좌표는 스케치 로컬 2D다(XZ 평면은 (X, Z), YZ 평면은 (Y, Z)). `sketch_plane.build_features`를 그대로 `build_features`의 `plane`/`position`에 넣는다
- `analyze_mesh`의 `thread.center`·`center`는 단면 좌표(축이 Z면 X,Y)다. `levels[].facets`는 개수뿐이다
- `open_document`로 다시 연 문서의 이름은 파일명이다(원래 문서 이름은 남지 않는다)
- `make_drawing`의 치수는 Projected 모드라 DistanceX/Y가 뷰 축을 따른다. 상세 뷰(`view`에 `ref` 글자)에서도 같은 방식으로 잰다
- `run_analysis`가 "nonpositive jacobian"으로 실패하면 메시가 찌그러진 것 — `setup_analysis(mesh_size=더 작게)`. 결과 절점 좌표는 변형 전 좌표다
- `compare_shapes`에서 `boolean_failed`가 true면 `missing/extra`는 무시하고 `volume_diff`·`area_diff`로만 판단한다

### 수정 코드 작성 시 주의
- FreeCAD 1.1에는 `Sketch.movePoint`가 없다 → `moveGeometry` / `moveGeometries`. `ping`의 버전을 보고 결정한다
- `execute_code`는 메인 스레드에서 돌아 중단할 수 없다. 긴 작업은 짧게 나눈다
- 수정 전에 사용자에게 무엇을 바꿀지 말한다. 문서 저장(`doc.save()`)은 사용자가 시키기 전엔 하지 않는다
