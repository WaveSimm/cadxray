# cadxray

*English: [README.en.md](README.en.md)*

FreeCAD 모델을 Claude Code가 **진단**하게 해 주는 MCP 서버입니다. "Sketch003이 왜 빨간지", "Pad가 왜 실패하는지"를 물으면 Claude가 툴로 직접 들여다보고 원인을 말해 줍니다. 수정은 `execute_code`로 하고, 결과는 `tracked_recompute`와 스크린샷으로 확인합니다.

- 지원: FreeCAD **1.0.x / 1.1.x** (1.1.3에서 검증), Windows · macOS · Linux
- 구성: FreeCAD 안에서 도는 **애드온**(`addon/CadXray`) + Claude Code가 띄우는 **브릿지**(`bridge/`)
- 두 프로그램은 `127.0.0.1:9877`로만 통신합니다 (외부 접속 없음)

---

## 1. 설치 — 명령 두 줄

필요한 것: FreeCAD 1.0 이상(한 번은 실행해 둔 상태), [Claude Code](https://claude.com/claude-code), [uv](https://docs.astral.sh/uv/), git.

```bash
uvx --from git+https://github.com/WaveSimm/cadxray#subdirectory=bridge cadxray install
claude mcp add --scope user cadxray -- uvx --from git+https://github.com/WaveSimm/cadxray#subdirectory=bridge cadxray
```

첫 줄이 애드온을 FreeCAD Mod 폴더에 복사하고, 둘째 줄이 Claude Code에 등록합니다. 그다음 **FreeCAD를 껐다 켜면** 서버가 자동으로 뜹니다(리포트 뷰에 `서버 시작 http://127.0.0.1:9877`). 끝입니다.

막히면:
```bash
uvx --from git+https://github.com/WaveSimm/cadxray#subdirectory=bridge cadxray doctor
```
애드온 설치 여부 · FreeCAD 서버 연결 · 버전 불일치를 한글로 알려 줍니다.

> 이 저장소가 비공개인 동안은 위 명령이 남의 컴퓨터에서 안 됩니다(GitHub 로그인 필요). 그때는 아래 개발자 설치를 쓰세요.

**개발자 설치** (저장소를 직접 고치면서 쓸 때):
```bash
git clone https://github.com/WaveSimm/cadxray.git && cd cadxray/bridge
uv run cadxray install --dev        # 심링크 — 코드를 고치면 바로 반영
claude mcp add --scope user cadxray -- uv --directory "<이 폴더의 절대경로>" run cadxray
```

**FreeCAD Addon Manager**로도 됩니다: 설정 → 사용자 저장소에 `https://github.com/WaveSimm/cadxray` 추가 → "CAD X-ray" 설치. (브릿지 등록은 둘째 줄 그대로.)

| OS | 애드온이 들어가는 Mod 폴더 |
|---|---|
| Windows | `%APPDATA%\FreeCAD\v1-1\Mod\` (1.0은 `v1-0`) |
| macOS | `~/Library/Application Support/FreeCAD/v1-1/Mod/` |
| Linux | `~/.local/share/FreeCAD/v1-1/Mod/` (Flatpak·snap은 `install --dest` 로 지정) |

이 프로젝트는 [theosib/FreeCAD-MCP-Server](https://github.com/theosib/FreeCAD-MCP-Server)의 진단 툴 설계와 [neka-nat/freecad-mcp](https://github.com/neka-nat/freecad-mcp)의 애드온 서버 패턴을 참고해 다시 만든 것입니다.

## 2. FreeCAD 쪽 조작 (보통은 할 일 없음)

서버는 FreeCAD를 켤 때 **자동으로 시작**됩니다. 워크벤치 **CAD X-ray** 메뉴에 있는 것:

| 메뉴 | 용도 |
|---|---|
| Start / Stop Server | 수동 시작·중지 |
| Auto Start | 자동시작 켜기/끄기 (기본 켜짐) |
| Set Port… | 포트 변경 (기본 9877). 바꾸면 `claude mcp add` 명령 끝에 `--port 9878`을 붙입니다 |

## 3. Claude Code 연결 확인

`claude`를 실행하고 `/mcp`를 치면 `cadxray`가 연결된 것으로 보입니다. 안 보이면 `doctor`부터.

## 4. 이렇게 씁니다

FreeCAD에서 모델을 열어 두고 Claude Code에 말로 시킵니다.

| 이렇게 말하면 | Claude가 하는 일 |
|---|---|
| "지금 열린 모델 구조 파악해줘" | `get_document_graph` → Body·피처·에러 객체 요약 |
| "Sketch003 왜 빨간지 진단해줘" | `get_sketch_diagnostics` → 충돌 제약 번호(GUI 패널 번호와 같음), 남은 자유도, 열린 끝점 |
| "Pad001 에러 원인 찾아서 고쳐줘" | 진단 → 원인 설명 → `execute_code`로 수정 → `tracked_recompute`로 확인 |
| "이 형상 뭔가 이상해" | `analyze_shape` → 유효성, 부피, 면 구성, 깨진 이유 |
| "지금 어떻게 생겼는지 보여줘" | `get_screenshot(view="iso")` → 이미지가 대화에 뜸 |
| "Pad의 Length가 어디서 오는 값이야?" | `inspect_object` → 프로퍼티와 수식(스프레드시트 참조 등) |
| "이 STEP 파일 마운팅 홀 몇 개고 피치 얼마야?" | `import_step` → `find_holes` → 직경·개수·중심·피치 |
| "브라켓이랑 센서 겹치는지 봐줘" | `check_interference` → 겹치는 부피(mm³) |
| "이거 알루미늄이면 몇 g이야?" | `get_mass_properties(density=2.7)` |

### 툴 목록

| 툴 | 하는 일 |
|---|---|
| `ping` | 연결·FreeCAD 버전 확인 |
| `list_documents` | 열린 문서 목록 |
| `get_document_graph` | 객체 트리·의존관계·문제 객체. **진단의 시작점** |
| `inspect_object` | 객체 하나의 모든 프로퍼티·수식·형상 요약 |
| `get_sketch_diagnostics` | 스케치 solve 결과, 자유도, 충돌/중복 제약, 열린 끝점 |
| `analyze_shape` | 형상 유효성·부피·면/모서리 구성 |
| `tracked_recompute` | 재계산 전후 비교 — 고쳐진 것 / 새로 깨진 것 |
| `get_screenshot` | 3D 뷰 PNG (iso, front, top … 12가지) |
| `execute_code` | FreeCAD 안에서 Python 실행 (수정용) |
| `reload_handlers` | 애드온 코드 다시 읽기 (개발용) |
| `import_step` | STEP/IGES 가져오기 + 생긴 부품 요약 |
| `find_holes` | 구멍 직경·중심·깊이·관통 여부, 카운터보어·카운터싱크·챔퍼·드릴 끝을 구멍에 붙여서, 같은 직경끼리 패턴·피치. 지름을 ISO 미터나사 표와 대조해 `thread_hint`(M3 탭 드릴 / M6 관통 …)를 **추정**으로 붙임 |
| `check_interference` | 부품 쌍 최소 거리·간섭 부피. 기본은 문제 쌍만 담고, 바운딩박스가 떨어진 쌍은 계산 없이 건너뜀 |
| `get_mass_properties` | 부피·표면적·무게중심·관성, 밀도를 주면 질량 |

`find_holes`는 오목 원통면의 호 각도(`arc_deg`)로 **구멍 / 필렛 / 슬롯 끝**을 구분하고(`kind`), 같은 축이라도 떨어져 있는 자리파기는 따로 셉니다. `patterns`는 직경·축 방향별로 묶입니다.

**예제** (`execute_code`로 실행):
- `examples/rebuild_bracket_from_step.py` — STEP으로 받은 판+각기둥 브라켓을 면 측정값만으로 파라메트릭 Body(스케치 7·Pad 2·Pocket 5·Fillet 3, 파라미터 15개)로 재구성. 원본과 **차집합 0.0 mm³**
- `examples/step_assembly_to_bodies.py` — STEP 어셈블리(80부품)를 부품별 Body + 접지 조인트 Assembly로 변환. 5.7초
- 벤더 부품(클램프 조 44면, BSpline 전이면·더브테일 홈·립 챔퍼 포함)도 같은 방법으로 부피 차 0.0004 %까지 재구성했습니다. 그 과정에서 확인한 함정(트레이스 기하는 Block으로, 2D 불리언 회피, 1e-5 틈 닫기, 회전 절삭의 과절삭 복원)은 `docs/api-notes.md` 7.5절에 있습니다

**STL/OBJ는 안 됩니다.** 메시(삼각형 뭉치)라 면·솔리드가 없어서 구멍·간섭·부피 툴이 전혀 동작하지 않습니다. 벤더에게 **STEP**을 받으세요.

모든 응답은 `{"ok", "data", "warnings", "truncated", "elapsed_ms"}` 봉투이고, 목록형 응답은 `max_*` 인자로 크기를 조절합니다. 요약(`summary`, `invalid_objects`)은 잘려도 항상 전체 기준입니다.

## 5. 응답 크기·시간 (FreeCAD 1.1.3, Windows)

`tests/in_freecad/test_handlers.py`가 만드는 테스트 모델과 실제 부품 모델(31객체)에서 측정한 값입니다.

| 툴 | 경우 | 응답 크기 | 시간 |
|---|---|---|---|
| `ping` | — | 190 B | 0 ms |
| `get_document_graph` | 13객체 | 2.8 KB | 0 ms |
| `get_document_graph` | 실제 부품 31객체 | 7.1 KB | 2 ms |
| `get_document_graph` | **320객체**, `max_objects=50` | **10.5 KB** (truncated) | 1 ms |
| `get_document_graph` | 320객체, 기본 `max_objects=200` | 31.7 KB (truncated) | 3 ms |
| `inspect_object` | Pad | 3.5 KB | 2 ms |
| `analyze_shape` | Pocket (구멍 있는 블록) | 2.6 KB | 7 ms |
| `get_sketch_diagnostics` | 완전 구속 / 충돌 제약 | 3.7 / 4.3 KB | 0 ms |
| `tracked_recompute` | 13객체 전체 | 0.5 KB | 8 ms |
| `get_screenshot` | 800×600 | 12 KB | 430 ms |
| `get_screenshot` | 2400×1800, 320객체 | 194 KB | 470 ms |
| `import_step` | 부품 4개 STEP (새 문서 / 기존 문서) | 1.7 KB | 85 / 41 ms |
| `find_holes` | Ø6.6 × 4 판 | 1.4 KB | 3 ms |
| `find_holes` | **벤더 STEP** 58면(BSpline 49) / 46면(원통 28) | 1.6 / 5.6 KB | **422 / 44 ms** |
| `check_interference` | 부품 4개 = 6쌍 | 1.4 KB | 31 ms |
| `check_interference` | 벤더 STEP 2개 (겹침 → `common()` 호출) | 0.8 KB | 838 ms |
| `check_interference` | **벤더 어셈블리 80부품 = 3,160쌍** (bbox로 2,989쌍 건너뜀) | 2.2 KB | **6.5 s** |
| `find_holes` | 어셈블리 부품 100면 (구멍 20 + 필렛 7) | 5 KB | 112 ms |
| `get_mass_properties` | 구멍 뚫린 판 / 벤더 STEP / 어셈블리 80부품 | 0.7 KB | 2 / 135 / 2068 ms |

응답 하드캡은 100 KB입니다(스크린샷 제외). 넘으면 핸들러가 목록을 먼저 줄이고 `warnings`에 알립니다.

## 6. 문제 해결

**"FreeCAD에 연결할 수 없습니다(127.0.0.1:9877)"**
FreeCAD가 꺼져 있거나 서버가 안 떴습니다. 먼저 `cadxray doctor`(1장의 긴 명령)를 돌리면 어느 쪽인지 알려 줍니다. FreeCAD가 켜져 있는데도 안 뜨면 리포트 뷰를 보고, **CAD X-ray → Auto Start**가 꺼져 있으면 켭니다.

**워크벤치 목록에 "CAD X-ray"가 없다**
`doctor`의 1번 항목이 설치된 폴더와 버전을 보여 줍니다. 폴더가 실제 FreeCAD 버전(v1-0 / v1-1)과 맞는지 FreeCAD **도움말 → 정보**와 대조하고, 다르면 `install --dest "<맞는 Mod 폴더>"`.

**"포트 9877을 열 수 없습니다"**
이미 서버가 떠 있거나 다른 프로그램이 쓰고 있습니다. **Set Port…**로 바꾸고 `claude mcp add` 명령 끝에 `--port 9878`을 붙여 다시 등록합니다.

**툴이 10개보다 적게 보인다 / 새 툴이 안 보인다**
브릿지가 옛 목록을 들고 있는 것입니다. Claude Code에서 `/mcp` → `cadxray` → **Reconnect**.

**FreeCAD가 멈췄다**
`execute_code`로 긴 코드를 돌린 것입니다. 메인 스레드에서 실행되므로 중단할 수 없습니다 — 끝나길 기다리거나 FreeCAD를 강제 종료합니다. 코드를 짧게 나눠서 시키세요.

**애드온 코드를 고쳤는데 반영이 안 된다**
`handlers/*.py`는 `reload_handlers` 툴로 다시 읽힙니다. `InitGui.py`·`gui.py`·`rpc_server.py`·`main_thread.py`·`handlers/__init__.py`는 FreeCAD 재시작이 필요합니다.

## 7. 테스트

서버를 켤 필요 없이 FreeCAD 명령줄에서 핸들러를 직접 돌립니다 (109개, 1초):

```
"C:\Program Files\FreeCAD 1.1\bin\freecadcmd.exe" tests\in_freecad\test_handlers.py
```

macOS는 `/Applications/FreeCAD.app/Contents/MacOS/FreeCADCmd`, Linux는 `freecadcmd`. GUI가 없어 스크린샷 테스트는 SKIP됩니다. 테스트 모델(`tests/fixtures/make_test_models.py`)은 메모리에만 만들고 저장하지 않습니다.

## 8. 저장소 구성

```
addon/CadXray/     FreeCAD 애드온 (stdlib + PySide만 사용)
  handlers/            툴 구현 — 파일마다 TOOLS 선언, 자동 등록
bridge/                MCP 브릿지 (의존성: mcp)
scripts/install_addon.py
tests/fixtures/        테스트 모델 생성
tests/in_freecad/      핸들러 테스트 (FreeCADCmd)
docs/api-notes.md      FreeCAD 1.0.2·1.1.3 API 확인 노트 — 구현의 근거
docs/archive/          작업 시작 때 쓴 지시서 (기록용)
CADXRAY_SPEC.md  개발 명세
```

라이선스: MIT (`LICENSE`). 구현 근거로 참고한 FreeCAD 소스 발췌(LGPL-2.1)는 저장소에 넣지 않았습니다 — 받는 법은 `CADXRAY_SPEC.md` 부록 A.2.
