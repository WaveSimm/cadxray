"""FreeCAD GUI 진입점 — 애드온 관리자/FreeCAD가 `freecad.cadxray.init_gui`를 import한다.

네임스페이스 레이아웃(freecad/<이름>/)이라 sys.path를 건드리지 않는다 [Addon Academy: Structuring].
서버 시작·워크벤치 등록은 gui.register()가 한다. 이 파일이나 gui.py를 고치면 FreeCAD를 재시작한다.
"""

from . import gui

gui.register()
