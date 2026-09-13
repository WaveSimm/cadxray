# cadxray 가이드 사이트

https://wavesimm.github.io/cadxray/ — AI 코딩 툴과 cadxray 로 FreeCAD 1.1.3 에서 3D 모델을 말로 만드는 법(설치·할 수 있는 것·실습 10개·프롬프트 작성법). 영문판은 [/en/](https://wavesimm.github.io/cadxray/en/) — 한국어가 기본 로케일이고 영문은 `src/content/docs/en/` 아래 같은 구조로 둔다.

```bash
cd site && npm ci && npm run build   # dist/ 생성. 미리보기: npm run dev
```

Astro + Starlight 정적 사이트. `.github/workflows/site.yml` 이 master 의 `site/**` 변경을 GitHub Pages 로 배포한다.
실습 입력·완성 파일은 Release [practice-files-v1](https://github.com/WaveSimm/cadxray/releases/tag/practice-files-v1) 자산이다(리포에 넣지 않는다 — Addon Manager 가 리포 전체를 clone 한다).

콘텐츠는 `src/content/docs/` 의 MDX 다. 고칠 것은 이 폴더를 직접 수정하거나 Issues 로.
