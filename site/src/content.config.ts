import { defineCollection, z } from 'astro:content';
import { docsLoader, i18nLoader } from '@astrojs/starlight/loaders';
import { docsSchema, i18nSchema } from '@astrojs/starlight/schema';

export const collections = {
  docs: defineCollection({
    loader: docsLoader(),
    // comments: false 인 페이지(게시판 등)는 하단 댓글을 붙이지 않는다 (components/overrides/Footer.astro)
    schema: docsSchema({ extend: z.object({ comments: z.boolean().optional() }) }),
  }),
  // 다국어(ko·en) UI 문구. 두 언어 모두 Starlight 내장 번역이 있어 파일은 비워 둔다.
  // 이 선언이 없으면 빌드가 «collection "i18n" does not exist» 경고를 낸다.
  i18n: defineCollection({ loader: i18nLoader(), schema: i18nSchema() }),
};
