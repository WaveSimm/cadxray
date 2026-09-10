# freecad-diag-mcp

FreeCAD 모델을 Claude Code가 **진단**하게 해 주는 MCP 서버입니다. "Sketch003이 왜 빨간지", "Pad가 왜 실패하는지"를 물으면 Claude가 툴로 직접 들여다보고 원인을 말해 줍니다. 수정은 `execute_code`로 하고, 결과는 `tracked_recompute`와 스크린샷으로 확인합니다.

- 지원: FreeCAD **1.0.x / 1.1.x** (1.1.3에서 검증), Windows · macOS · Linux
- 구성: FreeCAD 안에서 도는 **애드온**(`addon/FreeCADDiag`) + Claude Code가 띄우는 **브릿지**(`bridge/`)
- 두 프로그램은 `127.0.0.1:9877`로만 통신합니다 (외부 접속 없음)

---

## 1. 설치 (처음 한 번)

필요한 것: FreeCAD 1.0 이상, [Claude Code](https://claude.com/claude-code), [uv](https://docs.astral.sh/uv/), Python 3.10 이상, git.

```bash
git clone <이 저장소> freecad-diag-mcp
cd freecad-diag-mcp
python scripts/install_addon.py
```

`install_addon.py`가 OS별 FreeCAD Mod 폴더를 찾아 애드온을 **심링크**로 연결합니다(권한이 없으면 복사). 경로를 직접 주려면 `--dest "<Mod 폴더>"`, 후보만 보려면 `--list`.

| OS | Mod 폴더 |
|---|---|
| Windows | `%APPDATA%\FreeCAD\v1-1\Mod\` (1.0은 `v1-0`) |
| macOS | `~/Library/Application Support/FreeCAD/v1-1/Mod/` |
| Linux | `~/.local/share/FreeCAD/v1-1/Mod/` (Flatpak·snap 경로는 `--list`로 확인) |

## 2. FreeCAD에서 서버 켜기

1. FreeCAD를 껐다 켭니다
2. 워크벤치 목록에서 **FreeCAD Diag**를 고릅니다
3. 메뉴 **FreeCAD Diag → Start Server** — 리포트 뷰에 `서버 시작 http://127.0.0.1:9877 (툴 10개)`가 찍히면 됩니다

같은 메뉴의 **Auto Start**를 켜 두면 다음부터는 FreeCAD를 켤 때 서버가 같이 뜹니다. **Set Port…**로 포트를 바꿀 수 있습니다(바꾸면 아래 3번 설정도 같이).

## 3. Claude Code 연결

저장소 루트의 `.mcp.json.example`을 `.mcp.json`으로 복사하고 경로만 **절대경로**로 바꿉니다:

```json
{
  "mcpServers": {
    "freecad-diag": {
      "command": "uv",
      "args": ["--directory", "E:/claude/freecad-diag-mcp/bridge", "run", "freecad-diag-mcp"]
    }
  }
}
```

그 폴더에서 `claude`를 실행하고 `/mcp`를 치면 `freecad-diag`가 연결된 것으로 보입니다. 다른 폴더에서 쓰려면 사용자 범위로 등록합니다:

```bash
claude mcp add --scope user freecad-diag -- uv --directory "E:/claude/freecad-diag-mcp/bridge" run freecad-diag-mcp
```

포트를 바꿨다면 `args` 끝에 `"--port", "9878"`처럼 추가합니다 (환경변수 `FREECAD_DIAG_PORT`도 됩니다).

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

응답 하드캡은 100 KB입니다(스크린샷 제외). 넘으면 핸들러가 목록을 먼저 줄이고 `warnings`에 알립니다.

## 6. 문제 해결

**"FreeCAD에 연결할 수 없습니다(127.0.0.1:9877)"**
FreeCAD에 서버가 안 떠 있습니다. 리포트 뷰에 `서버 시작` 메시지가 있는지 보고, 없으면 **FreeCAD Diag → Start Server**. `.mcp.json`의 경로가 절대경로인지도 확인하세요.

**워크벤치 목록에 "FreeCAD Diag"가 없다**
`python scripts/install_addon.py --list`로 설치된 폴더가 실제 FreeCAD 버전(v1-0 / v1-1)과 맞는지 보세요. FreeCAD **도움말 → 정보**의 버전과 대조합니다.

**"포트 9877을 열 수 없습니다"**
이미 서버가 떠 있거나 다른 프로그램이 쓰고 있습니다. **Set Port…**로 바꾸고 `.mcp.json`의 `--port`도 같이 바꿉니다.

**툴이 10개보다 적게 보인다 / 새 툴이 안 보인다**
브릿지가 옛 목록을 들고 있는 것입니다. Claude Code에서 `/mcp` → `freecad-diag` → **Reconnect**.

**FreeCAD가 멈췄다**
`execute_code`로 긴 코드를 돌린 것입니다. 메인 스레드에서 실행되므로 중단할 수 없습니다 — 끝나길 기다리거나 FreeCAD를 강제 종료합니다. 코드를 짧게 나눠서 시키세요.

**애드온 코드를 고쳤는데 반영이 안 된다**
`handlers/*.py`는 `reload_handlers` 툴로 다시 읽힙니다. `InitGui.py`·`gui.py`·`rpc_server.py`·`main_thread.py`·`handlers/__init__.py`는 FreeCAD 재시작이 필요합니다.

## 7. 테스트

서버를 켤 필요 없이 FreeCAD 명령줄에서 핸들러를 직접 돌립니다 (66개, 0.5초):

```
"C:\Program Files\FreeCAD 1.1\bin\freecadcmd.exe" tests\in_freecad\test_handlers.py
```

macOS는 `/Applications/FreeCAD.app/Contents/MacOS/FreeCADCmd`, Linux는 `freecadcmd`. GUI가 없어 스크린샷 테스트는 SKIP됩니다. 테스트 모델(`tests/fixtures/make_test_models.py`)은 메모리에만 만들고 저장하지 않습니다.

## 8. 저장소 구성

```
addon/FreeCADDiag/     FreeCAD 애드온 (stdlib + PySide만 사용)
  handlers/            툴 구현 — 파일마다 TOOLS 선언, 자동 등록
bridge/                MCP 브릿지 (의존성: mcp)
scripts/install_addon.py
tests/fixtures/        테스트 모델 생성
tests/in_freecad/      핸들러 테스트 (FreeCADCmd)
docs/api-notes.md      FreeCAD 1.0.2·1.1.3 API 확인 노트 — 구현의 근거
FREECAD_DIAG_MCP_SPEC.md  개발 명세
```

라이선스: MIT (`LICENSE`). `docs/freecad-src-ref/`의 FreeCAD 소스 발췌는 LGPL-2.1입니다.
