> 보관용. 프로젝트를 시작할 때 쓴 작업 지시서이며 M1~M6이 끝난 지금은 역사 기록이다. 현재 안내는 루트 README.md.

# 내일 시작하기 — cadxray

이 묶음은 그 자체로 완결된 작업 지시서입니다. 회사 컴퓨터에서 압축을 풀고 아래 순서대로 하면 됩니다.

## 0. 묶음 내용

| 파일 | 용도 |
|---|---|
| `CADXRAY_SPEC.md` | 개발 명세. Claude Code가 읽고 구현하는 문서 (0장 작업 지침, 7장 툴 명세, 9장 마일스톤, 부록 A 소스 지도) |
| `CLAUDE.md` | Claude Code 프로젝트 지침 시작본. 저장소 루트에 그대로 둔다 |
| `docs/api-notes.md` | FreeCAD 1.0.2·1.1.3 소스에서 확인한 API 사실. 구현의 근거 |
| `docs/freecad-src-ref/` | FreeCAD 소스 발췌(두 버전, LGPL). 노트에 없는 걸 찾을 때만 grep |
| `.mcp.json.example` | Claude Code 연결 설정 템플릿. 경로만 바꿔 `.mcp.json`으로 |

## 1. 회사 컴퓨터에서 먼저 확인할 것 (5분)

```bash
# FreeCAD 버전 — 1.0.x 또는 1.1.x. FreeCAD 메뉴 도움말 > 정보 에서도 확인 가능
# macOS 예:
/Applications/FreeCAD.app/Contents/MacOS/FreeCAD --version

claude --version       # Claude Code
uv --version           # 없으면: curl -LsSf https://astral.sh/uv/install.sh | sh  (macOS/Linux)
git --version
```
FreeCAD Mod 디렉토리 위치는 명세 9장 M1-3에 OS별로 적혀 있다. 이미 설치된 neka-nat MCP 애드온이 있으면 그대로 둔다(포트 9875, 우리는 9877).

## 2. 저장소 만들기

```bash
mkdir -p ~/work/cadxray && cd ~/work/cadxray
git init
# 이 묶음의 내용을 여기에 풀어 넣는다 (START_HERE.md, CADXRAY_SPEC.md, CLAUDE.md, docs/, .mcp.json.example)
git add -A && git commit -m "명세·API 노트·소스 참조 추가"
```

## 3. Claude Code 시작 — 킥오프 프롬프트

저장소 루트에서 `claude`를 실행하고 아래를 그대로 붙여 넣는다.

```
CADXRAY_SPEC.md를 처음부터 끝까지 읽어. 구현 근거는 docs/api-notes.md이고,
노트에 없는 API만 docs/freecad-src-ref/ 나 라이브 introspection(부록 A.1)으로 확인해.
먼저 명세 2장의 환경 확인 항목을 나에게 물어보고, 답을 받은 뒤 9장 M1부터 시작해.
M1이 끝나면 멈추고 "FreeCAD에서 무엇을 해야 하는지"를 한 줄씩 알려줘.
```

Claude Code가 물어볼 것: FreeCAD 버전, OS·설치 방식, uv 유무. 세 가지만 답하면 된다.

## 4. 마일스톤별로 내가 할 일

| 마일스톤 | Wave가 직접 해야 하는 것 |
|---|---|
| M1 | FreeCAD 재시작 → 워크벤치 목록에서 "CAD X-ray" 선택 → Start Server. 그 다음 `claude` 안에서 `/mcp`로 연결 확인 |
| M2 | 아무 모델이나 열어 두기. Claude Code가 `get_document_graph`를 불러 보고 결과 보고 |
| M3 | 테스트 모델(10장)이 자동 생성되므로 특별히 할 것 없음. 결과 확인만 |
| M4 | 스크린샷이 Claude Code에 이미지로 보이는지 확인 |
| M5 | README를 읽고 "내가 다음에 혼자 설치할 수 있겠는가"로 검수 |
| M6 (선택) | 벤더 STEP 파일 하나 준비 |

## 5. 완성 후 매일 쓰는 방법

1. FreeCAD 실행 (자동시작을 켜 두면 서버가 같이 뜬다)
2. 저장소 폴더(또는 `.mcp.json`이 있는 아무 폴더)에서 `claude`
3. "지금 열린 문서 구조 파악해줘", "Sketch003 왜 빨간지 진단해줘", "Pad 에러 원인 찾아서 고쳐줘" 식으로 요청

## 6. Blender (나중에)

Blender는 우리가 만들지 않는다. 기존 blender-mcp를 쓴다:
- Blender 애드온 설치(저장소의 addon.py) → Blender 안에서 서버 시작(포트 9876)
- Claude Code: `claude mcp add --scope user blender -- uvx blender-mcp`
- 텔레메트리 끄려면 env `DISABLE_TELEMETRY=true`
FreeCAD → Blender는 STL/OBJ/glTF로 내보내는 한 방향. 설계 원본은 FreeCAD.

## 7. 막히면

- 연결이 안 됨: FreeCAD에 서버가 떠 있는지(리포트 뷰에 포트 메시지), `.mcp.json` 경로가 절대경로인지, `claude mcp list`
- 애드온 코드 고쳤는데 반영 안 됨: `InitGui.py`/`rpc_server.py`는 FreeCAD 재시작, 핸들러는 `reload_handlers`
- FreeCAD가 멈춤: `execute_code`로 긴 코드를 돌린 것. 짧게 나눠서
