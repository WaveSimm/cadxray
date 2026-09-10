"""freecad-diag-mcp 명령줄.

    freecad-diag-mcp                          MCP 서버 실행 (Claude Code가 부른다)
    freecad-diag-mcp install [--dev] [--dest 경로]   애드온을 FreeCAD에 설치
    freecad-diag-mcp doctor                   무엇이 안 되는지 진단

install은 패키지에 동봉된 애드온(addon/FreeCADDiag)을 FreeCAD Mod 폴더에 복사한다.
--dev 는 저장소 체크아웃을 심링크로 연결한다(코드를 고치면 바로 반영).
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import socket
import sys
from pathlib import Path

from . import client

ADDON_NAME = "FreeCADDiag"
REPO_URL = "https://github.com/WaveSimm/freecad-diag-mcp"
GIT_SPEC = f"git+{REPO_URL}#subdirectory=bridge"


# --- 경로 --------------------------------------------------------------------


def bundled_addon_dir() -> Path | None:
    p = Path(__file__).resolve().parent / "addon" / ADDON_NAME
    return p if (p / "InitGui.py").is_file() else None


def repo_addon_dir() -> Path | None:
    """저장소 체크아웃에서 실행 중이면 addon/FreeCADDiag (bridge/src/freecad_diag_mcp/cli.py 기준)."""
    try:
        p = Path(__file__).resolve().parents[3] / "addon" / ADDON_NAME
    except IndexError:
        return None
    return p if (p / "InitGui.py").is_file() else None


def mod_candidates() -> list[Path]:
    """OS별 FreeCAD Mod 폴더 후보. 존재하는 것을 앞에 둔다."""
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


def addon_version(path: Path) -> str | None:
    try:
        text = (path / "package.xml").read_text(encoding="utf-8")
        m = re.search(r"<version>([^<]+)</version>", text)
        return m.group(1).strip() if m else None
    except Exception:
        return None


def installed_addons() -> list[tuple[Path, str | None, bool]]:
    """(경로, 버전, 심링크 여부) - 존재하는 Mod 폴더 안의 FreeCADDiag."""
    out = []
    for mod in mod_candidates():
        target = mod / ADDON_NAME
        if target.is_dir() or target.is_symlink():
            out.append((target, addon_version(target), target.is_symlink()))
    return out


# --- install --------------------------------------------------------------------


def cmd_install(args: argparse.Namespace) -> int:
    if args.dev:
        src = repo_addon_dir()
        if src is None:
            print("--dev 는 저장소 체크아웃(bridge/ 옆에 addon/ 이 있는 곳)에서만 됩니다.", file=sys.stderr)
            return 1
    else:
        src = bundled_addon_dir() or repo_addon_dir()
        if src is None:
            print("동봉된 애드온을 찾을 수 없습니다. 패키지가 깨졌습니다.", file=sys.stderr)
            return 1

    if args.dest:
        dest_dir = Path(args.dest).expanduser()
    else:
        dest_dir = next((p for p in mod_candidates() if p.is_dir()), None)
        if dest_dir is None:
            print("FreeCAD Mod 폴더를 찾지 못했습니다. FreeCAD를 한 번 실행한 뒤 다시 하거나 --dest 로 지정하세요.")
            for p in mod_candidates():
                print("   후보:", p)
            return 1
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / ADDON_NAME

    if target.is_symlink() or target.exists():
        print(f"기존 설치를 지웁니다: {target}")
        if target.is_symlink() or target.is_file():
            target.unlink()
        else:
            shutil.rmtree(target)

    mode = "복사"
    if args.dev:
        try:
            target.symlink_to(src, target_is_directory=True)
            mode = "심링크"
        except (OSError, NotImplementedError) as e:
            print(f"심링크 실패({e}) - 복사로 전환합니다. (Windows는 개발자 모드가 필요합니다)")
            shutil.copytree(src, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    else:
        shutil.copytree(src, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    print(f"애드온 {mode} 완료: {target}  (버전 {addon_version(target) or '?'})")
    print()
    print("다음 단계:")
    print("  1. FreeCAD를 껐다가 다시 켭니다 - 서버가 자동으로 시작됩니다 (리포트 뷰에 '서버 시작 ... 9877')")
    print("  2. Claude Code에 등록합니다 (한 번만). 이 줄을 그대로 붙여 넣으세요:")
    print()
    print(f"     {register_command()}")
    print()
    print("  3. 확인: freecad-diag-mcp doctor")
    return 0


def register_command() -> str:
    """이 실행 파일이 어떻게 설치됐는지에 따라 알맞은 claude mcp add 명령."""
    repo = repo_addon_dir()
    if repo is not None:
        bridge = repo.parents[1] / "bridge"
        return f'claude mcp add --scope user freecad-diag -- uv --directory "{bridge}" run freecad-diag-mcp'
    return f"claude mcp add --scope user freecad-diag -- uvx --from {GIT_SPEC} freecad-diag-mcp"


# --- doctor ---------------------------------------------------------------------


def _ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def _bad(msg: str, fix: str | None = None) -> None:
    print(f"  [!!] {msg}")
    if fix:
        print(f"       → {fix}")


def cmd_doctor(args: argparse.Namespace) -> int:
    problems = 0
    print(f"freecad-diag-mcp doctor  (Python {sys.version.split()[0]}, {sys.platform})")
    print()

    print("1. 애드온 설치")
    found = installed_addons()
    if not found:
        problems += 1
        _bad("FreeCAD Mod 폴더에 FreeCADDiag 가 없습니다.", "freecad-diag-mcp install")
        for p in mod_candidates()[:3]:
            print(f"       후보 폴더: {p}  ({'있음' if p.is_dir() else '없음'})")
    for path, ver, link in found:
        _ok(f"{path}  버전 {ver or '?'}  {'(심링크 - 개발용)' if link else ''}")

    print("2. FreeCAD 서버 (127.0.0.1:%d)" % client.default_port())
    host, port = client.default_host(), client.default_port()
    client.configure(host, port)
    s = socket.socket()
    s.settimeout(1.5)
    try:
        s.connect((host, port))
        port_open = True
    except Exception:
        port_open = False
    finally:
        s.close()
    if not port_open:
        problems += 1
        _bad(
            "포트가 닫혀 있습니다 - FreeCAD가 꺼져 있거나 서버가 안 떴습니다.",
            "FreeCAD를 켜세요. 자동시작이 꺼져 있으면 워크벤치 'FreeCAD Diag' → Start Server",
        )
    else:
        r = client.call_raw("ping", timeout=10)
        if r.get("ok"):
            d = r["data"]
            _ok(f"FreeCAD {d.get('freecad_version')}  GUI={d.get('gui')}  애드온 {d.get('addon_version')}  열린 문서 {d.get('documents')}개")
            if found and d.get("addon_version") and found[0][1] and d["addon_version"] != found[0][1]:
                _bad(f"실행 중인 애드온({d['addon_version']})과 설치된 파일({found[0][1]})의 버전이 다릅니다.", "FreeCAD를 재시작하세요.")
        else:
            problems += 1
            _bad(f"포트는 열렸지만 ping 실패: {r.get('error')}", "다른 프로그램이 9877을 쓰고 있을 수 있습니다. FreeCAD Diag → Set Port… 로 바꾸세요.")

    print("3. Claude Code 등록")
    print("     claude mcp list  로 'freecad-diag' 가 보여야 합니다. 없으면:")
    print(f"     {register_command()}")

    print()
    if problems:
        print(f"문제 {problems}개. 위의 → 를 따라 하세요.")
        return 1
    print("전부 정상입니다. Claude Code에서 '지금 열린 모델 진단해줘' 라고 해 보세요.")
    return 0


# --- main -------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    # Windows 콘솔(cp949)에서 못 찍는 글자가 있어도 죽지 않게
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    parser = argparse.ArgumentParser(prog="freecad-diag-mcp", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default=client.default_host(), help="애드온 서버 주소 (기본 127.0.0.1)")
    parser.add_argument("--port", type=int, default=client.default_port(), help="애드온 서버 포트 (기본 9877)")
    sub = parser.add_subparsers(dest="cmd")
    p_inst = sub.add_parser("install", help="애드온을 FreeCAD Mod 폴더에 설치")
    p_inst.add_argument("--dev", action="store_true", help="저장소 체크아웃을 심링크로 연결 (개발용)")
    p_inst.add_argument("--dest", help="Mod 폴더 경로를 직접 지정")
    sub.add_parser("doctor", help="설치·연결 상태 진단")
    sub.add_parser("serve", help="MCP 서버 실행 (기본 동작)")

    args = parser.parse_args(argv)
    if args.cmd == "install":
        return cmd_install(args)
    if args.cmd == "doctor":
        return cmd_doctor(args)

    from . import server

    client.configure(args.host, args.port)
    server.mcp.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
