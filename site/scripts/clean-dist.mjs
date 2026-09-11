// dist/ 를 빌드 전에 비웁니다.
//
// 배경: Node v24.6.0 의 fs.rmSync({ recursive: true }) 는 Windows 에서 경로에 비ASCII 문자(예: 한글 폴더명)가 있으면
// 프로세스가 0xC0000409(STATUS_STACK_BUFFER_OVERRUN) 로 즉시 종료됩니다. Astro 는 빌드 시작 시 emptyDir(outDir) 에서
// 이 API 를 호출하므로, dist/ 가 이미 있으면 `astro build` 가 아무 메시지 없이 죽습니다.
// 이 스크립트는 rmSync 대신 unlinkSync / rmdirSync 로 트리를 직접 지워 그 경로를 피합니다.
// (Node 를 24.7 이상 또는 22 LTS 로 바꾸면 필요 없지만, 그대로 두어도 무해합니다.)
import { existsSync, lstatSync, readdirSync, rmdirSync, unlinkSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

function removeTree(p) {
  const st = lstatSync(p);
  if (st.isDirectory() && !st.isSymbolicLink()) {
    for (const name of readdirSync(p)) removeTree(join(p, name));
    rmdirSync(p);
  } else {
    unlinkSync(p);
  }
}

const dist = fileURLToPath(new URL('../dist/', import.meta.url));
if (existsSync(dist)) {
  const t = Date.now();
  removeTree(dist);
  console.log(`[clean-dist] dist/ 삭제 완료 (${Date.now() - t} ms)`);
}
