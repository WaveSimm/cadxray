# 워크벤치 등록. FreeCAD GUI가 실행할 때만 돌아간다.
#
# 주의: Init.py와 마찬가지로 별도 globals로 `exec`되므로 여기서 함수·클래스를
# 정의하면 모듈 수준 이름을 보지 못한다. 직선 코드만 두고 실제 등록은
# CadXray/gui.py가 한다. 이 파일이나 gui.py를 고치면 FreeCAD를 재시작한다.

import os
import sys

for _entry in list(sys.path):
    if os.path.basename(os.path.normpath(_entry)) == "CadXray":
        _parent = os.path.dirname(os.path.normpath(_entry))
        if _parent and _parent not in sys.path:
            sys.path.insert(0, _parent)
        break

from CadXray import gui as _cadxray_gui

_cadxray_gui.register()
