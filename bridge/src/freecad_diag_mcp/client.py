"""FreeCAD 애드온과 통신하는 XML-RPC 클라이언트.

FreeCAD가 꺼져 있어도 브릿지는 죽지 않는다. 연결에 실패하면 사용자가
무엇을 켜야 하는지 알려주는 봉투를 돌려준다 (명세 3장 원칙 5).
"""

from __future__ import annotations

import http.client
import json
import os
import socket
import xmlrpc.client

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9877
DEFAULT_TIMEOUT = 120.0

_host = DEFAULT_HOST
_port = DEFAULT_PORT


def configure(host: str | None = None, port: int | None = None) -> None:
    global _host, _port
    if host:
        _host = host
    if port:
        _port = int(port)


def default_host() -> str:
    return os.environ.get("FREECAD_DIAG_HOST", DEFAULT_HOST)


def default_port() -> int:
    try:
        return int(os.environ.get("FREECAD_DIAG_PORT", DEFAULT_PORT))
    except ValueError:
        return DEFAULT_PORT


def address() -> tuple[str, int]:
    return _host, _port


class _TimeoutTransport(xmlrpc.client.Transport):
    """소켓 타임아웃을 지정할 수 있는 Transport."""

    def __init__(self, timeout: float):
        super().__init__()
        self._timeout = timeout

    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = self._timeout
        return conn


def _not_connected() -> dict:
    return {
        "ok": False,
        "error": (
            f"FreeCAD에 연결할 수 없습니다({_host}:{_port}). "
            "FreeCAD를 실행하고 워크벤치 'FreeCAD Diag'에서 'Start Server'를 누르거나 "
            "자동시작(Auto Start)을 켜 주세요."
        ),
    }


def call_raw(tool: str, params: dict | None = None, timeout: float = DEFAULT_TIMEOUT) -> dict:
    """툴을 호출하고 응답 봉투(dict)를 그대로 돌려준다.

    params는 dict로 받는다(**kwargs가 아니다). 툴 인자에 `timeout` 같은 이름이
    있어도 이 함수의 인자와 충돌하지 않게 하기 위함이다.
    """
    params = params or {}
    proxy = xmlrpc.client.ServerProxy(
        f"http://{_host}:{_port}",
        allow_none=True,
        transport=_TimeoutTransport(timeout),
    )
    try:
        raw = proxy.call(tool, json.dumps(params, ensure_ascii=False, default=str))
    except (ConnectionRefusedError, socket.gaierror, OSError) as e:
        if isinstance(e, socket.timeout) or isinstance(e, TimeoutError):
            return {
                "ok": False,
                "error": (
                    f"FreeCAD 응답이 {timeout:.0f}초 안에 오지 않았습니다. "
                    "FreeCAD가 무거운 작업 중이거나 멈춰 있을 수 있습니다."
                ),
            }
        return _not_connected()
    except http.client.HTTPException:
        return _not_connected()
    except xmlrpc.client.Fault as e:
        return {"ok": False, "error": f"애드온 오류: {e.faultString}"}

    try:
        return json.loads(raw)
    except Exception as e:
        return {"ok": False, "error": f"응답 파싱 실패: {e}", "raw": str(raw)[:2000]}


def call(tool: str, params: dict | None = None, timeout: float = DEFAULT_TIMEOUT) -> str:
    """MCP 툴이 그대로 반환할 JSON 문자열."""
    return json.dumps(call_raw(tool, params, timeout), ensure_ascii=False, indent=2)
