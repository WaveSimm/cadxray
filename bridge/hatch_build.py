"""애드온(freecad/ · package.xml · LICENSE)을 wheel 안에 넣는 빌드 훅.

이 파일들은 저장소 루트에 있다(FreeCAD Addon Manager 가 거기를 본다).
그래서 빌드 위치에 따라 상대 경로가 달라진다.

- 저장소에서 바로 빌드 → `../freecad`
- sdist 를 풀어서 빌드(pip 이 소스로 설치할 때) → `./freecad`
  (sdist 는 아래 [tool.hatch.build.targets.sdist.force-include] 가 루트에 넣는다)

정적 force-include 로는 한쪽만 맞출 수 있어 wheel 을 sdist 에서 만들 때 깨졌다.
여기서 두 위치를 모두 보고 있는 쪽을 쓴다.
"""

import os

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

# (원본 이름, wheel 안에서의 위치)
ADDON_FILES = (
    ("freecad", "cadxray/addon/freecad"),
    ("package.xml", "cadxray/addon/package.xml"),
    ("LICENSE", "cadxray/addon/LICENSE"),
)


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        missing = []
        for name, dest in ADDON_FILES:
            for base in ("..", "."):
                src = os.path.normpath(os.path.join(self.root, base, name))
                if os.path.exists(src):
                    build_data["force_include"][src] = dest
                    break
            else:
                missing.append(name)
        if missing:
            raise FileNotFoundError(
                "애드온 파일을 찾을 수 없습니다: "
                + ", ".join(missing)
                + " — 저장소 루트나 sdist 루트에 있어야 합니다."
            )
