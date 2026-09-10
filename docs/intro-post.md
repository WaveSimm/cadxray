# 소개글 초안 (2026-09-10)

## 한국어 — 커뮤니티·블로그용

**cadxray: FreeCAD 모델을 Claude가 "투시"해서 진단하는 MCP 서버**

FreeCAD를 쓰다 보면 스케치가 빨개졌는데 어느 제약이 문제인지, Pad가 왜 실패하는지, 벤더가 준 STEP에 구멍이 몇 개인지 하나하나 클릭해서 봐야 합니다. cadxray는 그 일을 Claude에게 맡깁니다. "Sketch003 왜 빨간지 진단해줘"라고 하면 Claude가 FreeCAD 안을 직접 읽고 원인을 말해 주고, 시키면 고치고, 고친 결과를 재계산·스크린샷으로 확인합니다.

**뭘 할 수 있나**
- 스케치 진단: 충돌·중복 제약 번호(GUI 제약 패널 번호 그대로), 남은 자유도, 열린 끝점
- 형상 진단: 유효성, 깨진 이유, 부피·면 구성
- 재계산 추적: 고친 뒤 무엇이 풀렸고 무엇이 새로 깨졌는지
- STEP 분석: 구멍 직경·피치·카운터보어·카운터싱크·나사 규격 추정, 부품 간섭(80부품 3,160쌍 6.5초), 질량
- 모든 결과는 크기 제한이 있는 JSON이라 토큰을 아낍니다

**실제로 해 본 것**
- 제 PartDesign 모델에서 자유도가 남은 스케치와 제약 빠진 모서리를 찾아 고침
- 벤더 STEP 브라켓을 면 측정만으로 파라메트릭 Body로 재구성 — 원본과 차집합 0 mm³
- 80부품 벤더 어셈블리를 부품별 Body + Assembly로 변환

**설치는 두 줄** (터미널): 자세한 건 README
```
uvx --from git+https://github.com/WaveSimm/cadxray#subdirectory=bridge cadxray install
claude mcp add --scope user cadxray -- uvx --from git+https://github.com/WaveSimm/cadxray#subdirectory=bridge cadxray
```
Claude Code CLI·데스크톱 앱·Claude Desktop 채팅 앱 모두 됩니다.

**솔직한 한계**: FreeCAD 1.1.3 / Windows에서만 검증했습니다. 1.0.x나 macOS에서 써 보신 분은 결과를 알려 주시면 감사하겠습니다. 구멍의 관통 여부는 휴리스틱이고, 나사산은 STEP에 없어서 지름으로 추정만 합니다. STL은 안 됩니다.

theosib/FreeCAD-MCP-Server의 툴 설계와 neka-nat/freecad-mcp의 애드온 패턴을 참고해 처음부터 다시 만들었습니다. MIT.

https://github.com/WaveSimm/cadxray

---

## English — FreeCAD forum / r/FreeCAD

**cadxray — an MCP server that lets Claude X-ray your FreeCAD model**

I built a small MCP server so that Claude (Claude Code or the Claude Desktop app) can look inside a live FreeCAD document instead of guessing. You ask "why is Sketch003 red?" and it reads the solver state — conflicting constraint IDs (the same numbers as in the constraint panel), remaining DoF, open vertices — explains the cause, fixes it if you tell it to, and verifies with a tracked recompute and a screenshot.

**What it does (14 tools)**
- Sketch diagnostics: conflicting/redundant constraints, DoF, open wires, missing coincidences
- Shape diagnostics: validity, `check()` message, volume, faces by surface type
- Tracked recompute: what got resolved vs. what broke after an edit
- STEP analysis: holes with counterbore/countersink/chamfer, bolt patterns and pitch, ISO metric thread hints, interference between parts (80-part assembly, 3,160 pairs, 6.5 s), mass properties
- Every response is size-capped JSON so it stays cheap in tokens

**Things I actually did with it**
- Found a sketch with 1 DoF left and four unconstrained corners in my own PartDesign model and fixed them
- Rebuilt a vendor STEP bracket as a parametric Body from face measurements alone — 0.0 mm³ difference to the original
- Converted an 80-part vendor STEP assembly into one Body per part inside an Assembly with grounded joints

**Install** is two lines in a terminal (details in the README):
```
uvx --from git+https://github.com/WaveSimm/cadxray#subdirectory=bridge cadxray install
claude mcp add --scope user cadxray -- uvx --from git+https://github.com/WaveSimm/cadxray#subdirectory=bridge cadxray
```
Then restart FreeCAD; the addon starts its local server automatically. Works with Claude Code CLI, the Claude Code desktop app and the Claude Desktop chat app.

**Honest limits**: verified on FreeCAD 1.1.3 / Windows only so far — reports from 1.0.x and macOS/Linux users would be very welcome. Hole "through" detection is a heuristic; threads aren't in STEP so they're inferred from diameter; STL meshes are out of scope.

`docs/api-notes.md` in the repo records every FreeCAD API fact the tools rely on, tagged with the version it was verified against — including a few surprises (e.g. `solve()` returns `-4`, not `-3`, for two conflicting dimensions; `FullyConstrained` keeps a stale `True` after a failed solve).

Tool design follows theosib/FreeCAD-MCP-Server, the addon server pattern follows neka-nat/freecad-mcp; the code was written from a spec, not copied. MIT.

https://github.com/WaveSimm/cadxray
