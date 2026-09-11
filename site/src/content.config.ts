import { defineCollection, z } from 'astro:content';
import { docsLoader } from '@astrojs/starlight/loaders';
import { docsSchema } from '@astrojs/starlight/schema';

export const collections = {
  docs: defineCollection({
    loader: docsLoader(),
    // comments: false 인 페이지(게시판 등)는 하단 댓글을 붙이지 않는다 (components/overrides/Footer.astro)
    schema: docsSchema({ extend: z.object({ comments: z.boolean().optional() }) }),
  }),
};
