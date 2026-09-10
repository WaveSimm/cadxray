#!/usr/bin/env python3
"""애드온을 FreeCAD Mod 디렉토리에 연결한다.

기본은 심링크(저장소를 고치면 FreeCAD에 바로 반영). 권한이 없으면 복사한다.

    python scripts/install_addon.py            # 자동 탐지 후 설치
    python scripts/install_addon.py --list     # 후보 경로만 보여준다
    python scripts/install_addon.py --dest "<경로>"
    python scripts/install_addon.py --copy     # 심링크 대신 복사
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

ADDON_NAME = "CadXray"
SRC = Path(__file__).resolve().parent.parent / "addon" / ADDON_NAME


def candidates() -> list[Path]:
    """OS별 Mod 디렉토리 후보. 존재하는 것을 앞에 둔다 (명세 9장 M1-3)."""
    home = Path.home()
    out: list[Path] = []

    if sys.platform == "darwin":
        base = home / "Library" / "Application Support" / "FreeCAD"
        out += [base / "v1-1" / "Mod", base / "v1-0" / "Mod", base / "Mod"]
    elif os.name == "nt":
        appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        base = appdata / "FreeCAD"
        out += [base / "v1-1" / "Mod", base / "v1-0" / "Mod", base / "Mod"]
    else:
        base = home / ".local" / "share" / "FreeCAD"
        out += [
            base / "v1-1" / "Mod",
            base / "v1-0" / "Mod",
            base / "Mod",
            home / ".FreeCAD" / "Mod",
            home / ".var" / "app" / "org.freecad.FreeCAD" / "data" / "FreeCAD" / "v1-1" / "Mod",
            home / ".var" / "app" / "org.freecad.FreeCAD" / "data" / "FreeCAD" / "Mod",
            home / "snap" / "freecad" / "common" / "Mod",
        ]

    existing = [p for p in out if p.is_dir()]
    return existing + [p for p in out if p not in existing]


def install(dest_dir: Path, use_copy: bool = False) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / ADDON_NAME

    if target.is_symlink() or target.exists():
        print(f"기존 항목을 지웁니다: {target}")
        if target.is_symlink() or target.is_file():
            target.unlink()
        else:
            shutil.rmtree(target)

    if not use_copy:
        try:
            target.symlink_to(SRC, target_is_directory=True)
            print(f"심링크 생성: {target} -> {SRC}")
            return target
        except (OSError, NotImplementedError) as e:
            print(f"심링크 실패({e}) — 복사로 전환합니다.")

    shutil.copytree(SRC, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    print(f"복사 완료: {target}")
    print("  주의: 복사본입니다. 저장소 코드를 고치면 이 스크립트를 다시 실행해야 합니다.")
    return target


def main() -> int:
    ap = argparse.ArgumentParser(description="CAD X-ray 애드온 설치")
    ap.add_argument("--dest", help="Mod 디렉토리 경로를 직접 지정")
    ap.add_argument("--copy", action="store_true", help="심링크 대신 복사")
    ap.add_argument("--list", action="store_true", help="후보 경로만 출력")
    args = ap.parse_args()

    if not SRC.is_dir():
        print(f"애드온 소스를 찾을 수 없습니다: {SRC}", file=sys.stderr)
        return 1

    cands = candidates()
    if args.list:
        for p in cands:
            print(f"{'있음  ' if p.is_dir() else '없음  '}{p}")
        return 0

    dest = Path(args.dest).expanduser() if args.dest else None
    if dest is None:
        dest = next((p for p in cands if p.is_dir()), None)
        if dest is None:
            print("Mod 디렉토리를 찾지 못했습니다. --list로 후보를 보고 --dest로 지정하세요.", file=sys.stderr)
            return 1
        print(f"Mod 디렉토리: {dest}")

    install(dest, use_copy=args.copy)
    print()
    print("다음 단계:")
    print("  1. FreeCAD를 껐다가 다시 켠다")
    print("  2. 워크벤치 목록에서 'CAD X-ray'를 고른다")
    print("  3. 메뉴 'CAD X-ray > Start Server'를 누른다 (리포트 뷰에 포트가 찍힌다)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
