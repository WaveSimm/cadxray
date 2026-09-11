// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

// cadxray 가이드 사이트 (GitHub Pages: https://wavesimm.github.io/cadxray/)
export default defineConfig({
  site: 'https://wavesimm.github.io',
  base: '/cadxray',
  integrations: [
    starlight({
      title: 'FreeCAD AI 모델링 가이드',
      description: 'AI 코딩 툴(Claude Code · Codex CLI · Gemini CLI)과 cadxray 로 FreeCAD 1.1.3 에서 3D 모델을 말로 만드는 법 — 설치, 할 수 있는 것, 따라하기 실습 10개, 프롬프트 작성법',
      defaultLocale: 'root',
      locales: { root: { label: '한국어', lang: 'ko' } },
      // 순서: 글꼴 → 토큰 → Starlight 테마 → 사이트 전용
      customCss: [
        'pretendard/dist/web/variable/pretendardvariable.css',
        './src/styles/tokens.css',
        './src/styles/starlight-theme.css',
        './src/styles/custom.css',
      ],
      social: [{ icon: 'github', label: 'GitHub', href: 'https://github.com/WaveSimm/cadxray' }],
      editLink: { baseUrl: 'https://github.com/WaveSimm/cadxray/edit/master/site/' },
      tableOfContents: { minHeadingLevel: 2, maxHeadingLevel: 3 },
      lastUpdated: false,
      pagination: true,
      sidebar: [
        { label: '첫 화면', link: '/' },
        { label: '시작하기', items: [{ autogenerate: { directory: 'start' } }] },
        { label: '설치', items: [{ autogenerate: { directory: 'setup' } }] },
        { label: 'AI 툴 연결', items: [{ autogenerate: { directory: 'ai' } }] },
        { label: '할 수 있는 것', items: [{ autogenerate: { directory: 'features' } }] },
        { label: '따라하기 실습', items: [{ autogenerate: { directory: 'practice' } }] },
        { label: '프롬프트 작성법', items: [{ autogenerate: { directory: 'prompt' } }] },
        { label: '참고', collapsed: true, items: [{ autogenerate: { directory: 'ref' } }] },
      ],
    }),
  ],
});
