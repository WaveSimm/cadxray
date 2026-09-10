# 비-GUI 초기화. FreeCADCmd에서도 실행된다.
#
# 주의: FreeCAD는 이 파일을 별도의 globals/locals로 `exec`한다. 그래서 여기서
# 정의한 함수·클래스는 모듈 수준 이름을 보지 못한다(NameError). 직선 코드만 쓴다.
# 실제 로직은 전부 CadXray 패키지 안에 둔다.
#
# 하는 일: sys.path에 이미 들어와 있는 애드온 디렉토리를 찾아 그 상위(Mod)를
# 넣는다 → `import CadXray`가 가능해진다. 서버는 여기서 시작하지 않는다.

import os
import sys

for _entry in list(sys.path):
    if os.path.basename(os.path.normpath(_entry)) == "CadXray":
        _parent = os.path.dirname(os.path.normpath(_entry))
        if _parent and _parent not in sys.path:
            sys.path.insert(0, _parent)
        break
