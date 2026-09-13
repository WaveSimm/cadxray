// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

// cadxray 가이드 사이트 (GitHub Pages: https://wavesimm.github.io/cadxray/)
export default defineConfig({
  site: 'https://wavesimm.github.io',
  base: '/cadxray',
  integrations: [
    starlight({
      title: { ko: 'FreeCAD AI 모델링 가이드', en: 'FreeCAD AI Modeling Guide' },
      description: 'AI 코딩 툴(Claude Code · Codex CLI · Gemini CLI)과 cadxray 로 FreeCAD 1.1.3 에서 3D 모델을 말로 만드는 법 — 설치, 할 수 있는 것, 따라하기 실습 10개, 프롬프트 작성법',
      // 한국어가 기본(/cadxray/...), 영문은 /cadxray/en/... 에 얹는다.
      // 기존 한국어 URL 을 그대로 두려고 root 로케일을 ko 로 잡았다.
      defaultLocale: 'root',
      locales: {
        root: { label: '한국어', lang: 'ko' },
        en: { label: 'English', lang: 'en' },
      },
      // 순서: 글꼴 → 토큰 → Starlight 테마 → 사이트 전용
      customCss: [
        'pretendard/dist/web/variable/pretendardvariable.css',
        './src/styles/tokens.css',
        './src/styles/starlight-theme.css',
        './src/styles/custom.css',
      ],
      // 방문자 통계 (GoatCounter) — 쿠키·개인정보 없이 페이지별 조회수만 센다.
      // 통계는 https://wavesim.goatcounter.com 에서 본다.
      head: [
        {
          tag: 'script',
          attrs: {
            'data-goatcounter': 'https://wavesim.goatcounter.com/count',
            async: true,
            src: 'https://gc.zgo.at/count.js',
          },
        },
      ],
      social: [{ icon: 'github', label: 'GitHub', href: 'https://github.com/WaveSimm/cadxray' }],
      editLink: { baseUrl: 'https://github.com/WaveSimm/cadxray/edit/master/site/' },
      tableOfContents: { minHeadingLevel: 2, maxHeadingLevel: 3 },
      lastUpdated: false,
      pagination: true,
      sidebar: [
        { label: '첫 화면', translations: { en: 'Home' }, link: '/' },
        { label: '시작하기', translations: { en: 'Start here' }, items: [{ autogenerate: { directory: 'start' } }] },
        { label: '설치', translations: { en: 'Install' }, items: [{ autogenerate: { directory: 'setup' } }] },
        { label: 'AI 툴 연결', translations: { en: 'Connect an AI tool' }, items: [{ autogenerate: { directory: 'ai' } }] },
        { label: '할 수 있는 것', translations: { en: 'What it can do' }, items: [{ autogenerate: { directory: 'features' } }] },
        { label: '따라하기 실습', translations: { en: 'Hands-on exercises' }, items: [{ autogenerate: { directory: 'practice' } }] },
        { label: '프롬프트 작성법', translations: { en: 'Writing prompts' }, items: [{ autogenerate: { directory: 'prompt' } }] },
        { label: '참고', translations: { en: 'Reference' }, collapsed: true, items: [{ autogenerate: { directory: 'ref' } }] },
      ],
    }),
  ],
});
