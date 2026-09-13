# cadxray

*English: [README.en.md](README.en.md)*

**AI 가 FreeCAD 안을 직접 들여다봅니다.** 도면이든 벤더 STEP 이든 STL 이든, 방금 빨개진 스케치든 그대로 던지세요.

![cadxray 데모](https://github.com/WaveSimm/cadxray/releases/download/media-v1/cadxray-demo-ko.gif)

<sub>위 화면은 전부 FreeCAD 1.1.3 에서 실제로 돌린 것이고, 숫자도 툴이 보고한 값 그대로입니다. 직접 해 보려면 [따라하기 실습 10개](https://wavesimm.github.io/cadxray/practice/01-plate-holes/).</sub>

FreeCAD 모델을 AI 코딩 툴(Claude Code·Cursor·VS Code·Codex·Gemini CLI 등 MCP 클라이언트)이 **진단·수정**하게 해 주는 MCP 서버입니다. "Sketch003이 왜 빨간지", "Pad가 왜 실패하는지"를 물으면 Claude가 툴로 직접 들여다보고 원인을 말해 줍니다. 수정은 `execute_code`로 하고, 결과는 `tracked_recompute`와 스크린샷으로 확인합니다.

- 지원: FreeCAD **1.0.x / 1.1.x** (1.1.3에서 검증), Windows · macOS · Linux
- 구성: FreeCAD 안에서 도는 **애드온**(`freecad/cadxray`) + AI 툴이 띄우는 **브릿지**(`bridge/`, 표준 MCP stdio)
- 두 프로그램은 `127.0.0.1:9877`로만 통신합니다 (외부 접속 없음)

---

## 1. 설치 — 명령 두 줄 (Claude Code 기준, 다른 툴은 3장)

**아래 명령은 전부 "터미널"에 입력합니다.** Claude Code 대화창이 아닙니다.
- Windows: 시작 메뉴에서 **PowerShell** 을 찾아 실행 (명령 프롬프트 `cmd`도 됩니다)
- macOS: **터미널**(Terminal) 앱
- Linux: 터미널

**먼저 있어야 하는 것** (없으면 한 번만 설치):

| | 확인 명령 | 없을 때 |
|---|---|---|
| FreeCAD 1.0 이상 | (한 번은 실행해 두세요 — Mod 폴더가 그때 생깁니다) | freecad.org |
| MCP를 지원하는 AI 툴 — 예: [Claude Code](https://claude.com/claude-code) | `claude --version` | 공식 안내대로 설치 후 로그인. Cursor·VS Code·Windsurf·Codex·Gemini CLI 등은 3장 |
| [uv](https://docs.astral.sh/uv/) | `uv --version` | Windows(PowerShell): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 \| iex"` · macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh \| sh` — 설치 후 터미널을 **다시 엽니다** |
| git | `git --version` | Windows: git-scm.com · macOS: `xcode-select --install` |

**설치** — 터미널에 한 줄씩 붙여 넣고 Enter:

```bash
uvx --from git+https://github.com/WaveSimm/cadxray#subdirectory=bridge cadxray install
claude mcp add --scope user cadxray -- uvx --from git+https://github.com/WaveSimm/cadxray#subdirectory=bridge cadxray
```

첫 줄이 애드온을 FreeCAD Mod 폴더에 복사하고(처음엔 내려받느라 10~30초), 둘째 줄이 Claude Code에 등록합니다. 그다음 **FreeCAD를 껐다 켜면** 서버가 자동으로 뜹니다(리포트 뷰에 `[CAD X-ray] 서버 시작 http://127.0.0.1:9877 (툴 36개)`). 끝입니다.

이제 아무 폴더에서나 터미널에 `claude`를 쳐서 Claude Code를 열고, 4장처럼 말로 시키면 됩니다.

막히면 (역시 터미널에):
```bash
uvx --from git+https://github.com/WaveSimm/cadxray#subdirectory=bridge cadxray doctor
```
애드온 설치 여부 · FreeCAD 서버 연결 · 버전 불일치를 한글로 알려 줍니다.

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

## 3. 어느 AI 툴에서 쓰나 — MCP를 지원하는 툴이면 다 됩니다

브릿지는 표준 **MCP(stdio)** 서버라 Claude 말고도 Cursor·VS Code·Windsurf·Codex·Gemini CLI 등 MCP를 지원하는 어느 툴에서나 같은 명령으로 붙습니다. FreeCAD 쪽(1장 첫째 줄, 애드온 설치)은 공통이고, 아래는 **툴별 등록**만 다릅니다. 실행 명령은 어디서나 같습니다:

```
uvx --from git+https://github.com/WaveSimm/cadxray#subdirectory=bridge cadxray
```

| 툴 | 등록 방법 | 확인 |
|---|---|---|
| **Claude Code** (CLI·데스크톱 앱, 설정 공유) | 1장의 둘째 줄 `claude mcp add --scope user …` | `/mcp` → `cadxray · connected · 36 tools` |
| **Claude Desktop** 채팅 앱 | `claude_desktop_config.json`에 아래 JSON (설정 → 개발자 → 설정 편집; Windows `%APPDATA%\Claude\`, macOS `~/Library/Application Support/Claude/`) 후 앱 완전 재시작 | 대화창 도구(🔧)에 `cadxray` |
| **Cursor** | 설정 → MCP → **Add new global MCP server** 로 `~/.cursor/mcp.json`(프로젝트만이면 `.cursor/mcp.json`)에 아래 JSON | 설정 MCP 목록에 초록 점 + 툴 36개 |
| **VS Code** (Copilot 에이전트 모드) | 명령 팔레트 → **MCP: Add Server** → Command(stdio) → 위 실행 명령. 또는 `.vscode/mcp.json`에 아래 VS Code JSON | Copilot 채팅 도구 목록에 `cadxray` |
| **Windsurf** | 설정 → Cascade → MCP → **Add server** → `~/.codeium/windsurf/mcp_config.json`에 아래 JSON | Cascade 도구 목록 |
| **OpenAI Codex CLI** | `codex mcp add cadxray -- uvx --from git+https://github.com/WaveSimm/cadxray#subdirectory=bridge cadxray` (또는 `~/.codex/config.toml`에 아래 TOML) | `codex mcp list` |
| **Gemini CLI** | `gemini mcp add cadxray uvx --from git+https://github.com/WaveSimm/cadxray#subdirectory=bridge cadxray` (또는 `~/.gemini/settings.json`에 아래 JSON) | `/mcp` |
| **Cline · Roo Code · Continue 등** | 각 확장의 MCP 설정 파일에 아래 JSON(`mcpServers` 형식) | 확장의 MCP 패널 |

**표준 JSON** (Claude Desktop · Cursor · Windsurf · Gemini CLI · Cline 계열 공통):

```json
{
  "mcpServers": {
    "cadxray": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/WaveSimm/cadxray#subdirectory=bridge", "cadxray"]
    }
  }
}
```

**VS Code** (`.vscode/mcp.json` — 키가 `servers`입니다):

```json
{
  "servers": {
    "cadxray": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "git+https://github.com/WaveSimm/cadxray#subdirectory=bridge", "cadxray"]
    }
  }
}
```

**Codex CLI** (`~/.codex/config.toml`):

```toml
[mcp_servers.cadxray]
command = "uvx"
args = ["--from", "git+https://github.com/WaveSimm/cadxray#subdirectory=bridge", "cadxray"]
```

공통 주의:
- Windows에서 "uvx를 찾을 수 없다"고 하면 `"command"`에 전체 경로를 넣습니다 — PowerShell에서 `(Get-Command uvx).Source` (보통 `C:\Users\<이름>\.local\bin\uvx.exe`). GUI 앱(Claude Desktop·Cursor)은 터미널과 PATH가 달라 이 문제가 자주 납니다.
- 다른 MCP가 이미 있으면 `mcpServers`(VS Code는 `servers`) 안에 `"cadxray"` 항목만 추가합니다.
- 포트를 바꿨으면 `args` 끝에 `"--port", "9878"`을 붙입니다.
- 첫 실행은 브릿지를 내려받느라 10~30초 걸립니다. 툴이 안 보이면 그 뒤에 한 번 더 연결합니다.
- 어느 툴이든 같은 FreeCAD 서버(127.0.0.1:9877)에 붙으므로 FreeCAD는 하나만 켜 두면 되고, 여러 툴을 동시에 써도 됩니다.
- 사용법(4장)의 CLAUDE.md 워크플로는 Claude Code용 파일입니다. 다른 툴에서는 툴 설명(docstring)만으로도 동작하지만, 진단 순서를 알려 주려면 그 툴의 규칙 파일(Cursor `.cursor/rules`, Codex `AGENTS.md`, Gemini `GEMINI.md` 등)에 CLAUDE.md의 "진단 워크플로" 부분을 복사해 넣으면 됩니다.

## 4. 이렇게 씁니다

> **따라하기 가이드 사이트**: https://wavesimm.github.io/cadxray/ — 설치, 할 수 있는 것, 실습 10개(판에 구멍 뚫기부터 STEP·STL 다시 그리기, 2D 도면, 3D 프린트 검토, 구조 해석까지), 프롬프트 작성법. 영문판은 [/en/](https://wavesimm.github.io/cadxray/en/). 실습 파일은 [Release practice-files-v1](https://github.com/WaveSimm/cadxray/releases/tag/practice-files-v1).

FreeCAD에서 모델을 열어 두고 Claude Code에 말로 시킵니다.

| 이렇게 말하면 | Claude가 하는 일 |
|---|---|
| "지금 열린 모델 구조 파악해줘" | `get_document_graph` → Body·피처·에러 객체 요약 |
| "Sketch003 왜 빨간지 진단해줘" | `get_sketch_diagnostics` → 충돌 제약 번호(GUI 패널 번호와 같음), 남은 자유도, 열린 끝점 |
| "PETG, 0.6 노즐로 서포트 없이 뽑게 봐줘" | `check_printability(profile)` → 번호 목록(얇은 벽·오버행·구멍) → `suggest_orientation` / `apply_print_fixes` 로 선택 적용 → 다시 검사 |
| "고쳐줘" | `suggest_sketch_fixes` → 번호 붙은 후보 목록(예: "1. Line5 끝점과 Arc2 시작점 잇기 → 자유도 3→1") → 사용자가 번호 선택 → `apply_sketch_fixes` |
| "Pad001 에러 원인 찾아서 고쳐줘" | 진단 → 원인 설명 → `execute_code`로 수정 → `tracked_recompute`로 확인 |
| "이 형상 뭔가 이상해" | `analyze_shape` → 유효성, 부피, 면 구성, 깨진 이유 |
| "지금 어떻게 생겼는지 보여줘" | `get_screenshot(view="iso")` → 이미지가 대화에 뜸 |
| "Pad의 Length가 어디서 오는 값이야?" | `inspect_object` → 프로퍼티와 수식(스프레드시트 참조 등) |
| "이 STEP 파일 마운팅 홀 몇 개고 피치 얼마야?" | `import_step` → `find_holes` → 직경·개수·중심·피치 |
| "브라켓이랑 센서 겹치는지 봐줘" | `check_interference` → 겹치는 부피(mm³) |
| "이거 알루미늄이면 몇 g이야?" | `get_mass_properties(density=2.7)` |
| "이거 2D 도면으로 뽑아줘" | `make_drawing` → 3면도·상세·치수·주석·표제란이 든 TechDraw 페이지 + PDF/SVG. `inspect_drawing`으로 치수 값 확인 |
| "이 STL 다시 그려줘" | 참고 메시를 투명으로 띄우고 단면 원 피팅 → `build_features`(CLAUDE.md "STL → 파라메트릭" 절차, `examples/stl_spool_guide_with_m7.py`) |
| "이 STEP 부품 파라메트릭으로 다시 만들어줘" (찰흙으로) | `classify_faces`(면 정체·주축·띠 높이) → `section_profile`(띠 경계) → `build_features`(Pad·Groove·Pocket·Chamfer를 순서대로) → `compare_shapes`(원본과 차집합으로 검증) |

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
| `get_mass_properties` | 부피·표면적·무게중심·관성, 밀도를 주면 질량, `stability`로 접지·전도각, `names`+`densities`로 어셈블리 합산(M16) |
| `classify_faces` | **STEP → 파라메트릭 1단계.** 면마다 정체(평면/원통/원뿔/구/자유곡면). BSpline 면도 표본을 찍어 맞춰 보므로 "가짜 자유곡면"이 걸러짐. 주축·띠 높이(`levels`)·반지름 목록·재구성 판정(`verdict`) |
| `section_profile` | 높이의 단면 윤곽을 스케치용 선분·호·원으로(스케치 로컬 2D). 구멍·카운터보어·챔퍼 자리는 3D에서 메운 뒤 잘라 바깥 윤곽만. BSpline 곡선도 직선·원으로 다시 판별 |
| `build_features` | 스케치 + Pad/Pocket/Groove/Revolution/Fillet/Chamfer 목록을 Body에 **순서대로 쌓고 피처마다 검증**. `profile.section`이면 원본을 직접 트레이스해 좌표가 대화를 오가지 않음. Block·구성점 고정·구성선 축 규칙 내장, `params`는 Spreadsheet로 |
| `compare_shapes` | 부피·면적·bbox 차 + 퍼지 차집합 조각의 bbox — **어디가 틀렸는지** 바로 짚음 |
| `align_shapes` | 같은 부품의 두 인스턴스 사이 강체 변환(관성 주축 + 표면 점 검증). 재구성한 Body를 Link로 여러 자리에 놓을 때. 거울상이면 `mirrored` |
| `make_drawing` | **2D 도면(M8)**: Body·Part·Link 그룹 → TechDraw 페이지(ISO 표제란, 자동 축척·배치, 정면/우측/평면/등각/상세) + 치수(모델 정점·실루엣·원 참조, 값은 모델에서 잼; 뷰 이름·다른 치수와 겹치면 자동으로 밀어냄) + 주석 + 표제란 → PDF/SVG. Link 27개 어셈블리 5뷰·치수 13개 87초 |
| `inspect_drawing` | 페이지의 뷰·치수 값·주석·표제란 읽기. 빈 뷰(모서리 0)·깨진 치수(Invalid) 찾기 |
| `import_mesh` | **STL(M9)**: STL/OBJ/PLY/3MF를 참고용 Mesh 객체로(투명), 닫힘·자기교차 검사 |
| `analyze_mesh` | 메시의 주축·레벨(띠 경계)·띠별 단면 원·공통 중심·**나사(피치·외경·골·방향)**·verdict. `classify_faces`의 메시판 |
| `section_profile` / `compare_shapes` 메시 입력 | 메시 단면 폴리라인을 직선·원호·원으로 피팅해 `build_features`가 그대로 받음 / 불리언 없이 법선 광선 편차(worst 점)로 비교 |
| `build_features` `helix` op | 나사·나선 홈(SubtractiveHelix/AdditiveHelix), 축 중심·피치·높이·방향 |
| `open_document` / `save_document` | FCStd 열기·저장(다른 파일 덮어쓰기는 overwrite 필요) |
| `suggest_sketch_fixes` | **제약 수정 후보(M10)**: 가까운/열린 끝점 잇기, 빠진 수평·수직·같음, 중복·잘못된·충돌 제약 삭제, 남은 자유도용 치수. 후보마다 사본에 적용해 본 효과(DoF·상태)와 확신도. 자동으로 고치지 않음 |
| `apply_sketch_fixes` | 사용자가 고른 후보 id만 적용, 나빠지면 되돌림. 스케치가 그사이 바뀌었으면(fingerprint) 거부 |
| `check_printability` | **3D 프린트(M12)**: 재질·노즐·베드 프로파일로 얇은 벽, 오버행/브릿지(서포트 면적), 작은·수평 구멍, 베드 적합, 첫 층 접지를 검사 → 점수·issues·fix 후보. `paint=True`면 면을 결과 색으로 |
| `estimate_print` | 재료 부피·무게·필라멘트 길이·대략 시간·비용(재질 밀도 표) |
| `suggest_orientation` | 출력 방향 6개 + 현재를 서포트·접지·높이로 채점, 고르면 Placement 적용 |
| `apply_print_fixes` | 출력용 설계 수정을 PartDesign 피처로: 코끼리발 챔퍼, 수직 구멍 지름 보정, 수평 구멍 눈물방울, 얇은 면 두껍게, 오버행 아래 45° 쐐기, 베드 초과 분할(M15) |
| `setup_analysis` | **구조 해석(M13)**: 재질(표 또는 E·ν·밀도·항복) + 고정 면 + 하중(힘·압력·자중) + Gmsh 2차 메시 + CalculiX 솔버를 한 번에. 여러 부품(`names`, 부품별 재질, 접합)·고유진동수(`analysis_type="frequency"`)도(M16) |
| `run_analysis` | CalculiX 정적 해석 → 최대 von Mises 응력·위치, 최대 변위, 안전율(항복/최대), verdict, 3D 뷰에 응력 컬러맵. frequency면 모드별 고유진동수 |
| `inspect_results` | 응력·변위 상위 절점과 면별 최대, 컬러맵 필드 전환 |
| `suggest_reinforcement` | 안전율 미달이면 두께·필렛·리브·재질·하중 후보를 번호 목록으로(자동 적용 없음) |
| `trace_links` | **어셈블리 Link 추적(M14)**: 다른 파일을 가리키는 Link·배열·바인더를 따라 문서 사슬, 깨진 링크(파일 없음), 연결 문서의 Invalid 객체를 한 번에 |

`find_holes`는 오목 원통면의 호 각도(`arc_deg`)로 **구멍 / 필렛 / 슬롯 끝**을 구분하고(`kind`), 같은 축이라도 떨어져 있는 자리파기는 따로 셉니다. `patterns`는 직경·축 방향별로 묶입니다.

**예제** (`execute_code`로 실행):
- `examples/rebuild_bracket_from_step.py` — STEP으로 받은 판+각기둥 브라켓을 면 측정값만으로 파라메트릭 Body(스케치 7·Pad 2·Pocket 5·Fillet 3, 파라미터 15개)로 재구성. 원본과 **차집합 0.0 mm³**
- `examples/step_assembly_to_bodies.py` — STEP 어셈블리(80부품)를 부품별 Body + 접지 조인트 Assembly로 변환. 5.7초
- 벤더 부품(클램프 조 44면, BSpline 전이면·더브테일 홈·립 챔퍼 포함)도 같은 방법으로 부피 차 0.0004 %까지 재구성했습니다. 그 과정에서 확인한 함정(트레이스 기하는 Block으로, 2D 불리언 회피, 1e-5 틈 닫기, 회전 절삭의 과절삭 복원)은 `docs/api-notes.md` 7.5절에 있습니다
- **어셈블리 전체 재구성** — 벤더 STEP 80부품(20종)을 전부 파라메트릭 Body로 다시 만들고(`examples/rebuild_*_with_tools.py`), 종류당 Body 하나에 인스턴스 80개를 `align_shapes`로 배치한 Link + Assembly로 조립(`examples/assemble_from_bodies.py`). 20종 중 identical 15 · match 4 · 0.14 % 1(자유곡면 필렛), 인스턴스 80개 전부 배치·접지, 간섭 0(접촉 9쌍), 3.5분. STEP의 Placement는 인스턴스 변환이 아니라서 형상에서 강체 변환을 찾는 `align_shapes`가 필요했고, D형 캡과 스페이서에 **거울상 인스턴스**가 섞여 있다는 것도 이 과정에서 드러났습니다
- `examples/techdraw_page_from_assembly.py` — 철봉 프레임 어셈블리의 TechDraw 페이지를 손으로 만든 기록(M8 `make_drawing`의 원형). `examples/pole_frame_from_dxf.py`·`cover_from_pdf_drawing.py`·`pcb_from_dxf.py`·`ink_holder_from_photo.py` — DXF·벡터 PDF·사진(조감도)에서 3D를 만든 기록
- `examples/rebuild_2b2_with_tools.py` — 같은 클램프 조를 **M7 툴 네 개만으로** 다시 만든 기록. 손으로 쓰던 200줄이 피처 12개 목록 하나가 됐고, 스케치 12개 전부 DoF 0, `compare_shapes` 판정 identical(부피 차 0.0004 %). BSpline 전이면 8개는 `classify_faces`가 원뿔(축·꼭짓점·반각 59.63°)로 판별했습니다. 그때 확인한 것(법선 부호 뒤집힘, `common()`의 겹친 면, 구성점으로 호 고정, 반지름 반올림의 대가)은 13절

**STL/OBJ**는 구멍·간섭 툴이 직접 못 읽지만(면·솔리드 없음), M9 툴로 다시 그릴 수 있습니다: `import_mesh` → `analyze_mesh`(레벨·단면 원·나사) → `section_profile`(메시 단면 피팅) → `build_features`(`profile.section`에 메시 이름, 나사는 `helix` op) → `compare_shapes`(메시, Body: 광선 편차). 3D 프린트용 스풀 가이드 STL(5,758면)을 이 절차로 메시 정점 전부 0.03 mm 안, 부피 0.014 %로 재구성했습니다(수나사 M44.5×2 포함, `examples/stl_spool_guide_with_m7.py`). `makeShapeFromMesh`로 만든 솔리드에 예전 방식 `compare_shapes`를 부르면 불리언이 10분 넘게 걸리므로 메시 이름을 그대로 넘기세요. 벤더에게 **STEP**을 받으세요.

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
| `classify_faces` | 전부 BSpline인 판 14면 / **벤더 클램프 조 44면**(BSpline 8) | 5.4 / 12 KB | 25 / 73 ms |
| `section_profile` | 후보 높이만 / z=3 단면(구멍 메움) | 0.7 / 1.0 KB | 25 / 65 ms |
| `build_features` | 판 5피처 / **클램프 조 12피처**(단면 트레이스 5회 포함) | 1.2 / 2.5 KB | 180 ms / **2.0 s** |
| `compare_shapes` | 판 vs 재구성 / 클램프 조 vs 재구성 | 0.8 KB | 26 / 780 ms |

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
freecad/cadxray/     FreeCAD 애드온 (stdlib + PySide만 사용)
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
