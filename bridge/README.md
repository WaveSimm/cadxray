# cadxray (브릿지)

Claude Code와 FreeCAD 애드온(XML-RPC 127.0.0.1:9877)을 잇는 MCP 서버. 애드온(`freecad/cadxray`)이 패키지에 동봉되어 있다.

```bash
cadxray                 # MCP 서버 실행 (Claude Code가 부른다)
cadxray install         # 동봉 애드온을 FreeCAD Mod 폴더에 복사
cadxray install --dev   # 저장소 체크아웃을 심링크로 (개발용)
cadxray doctor          # 설치·연결 진단
```

설치·사용 안내는 저장소 루트의 README.md를 보세요.
