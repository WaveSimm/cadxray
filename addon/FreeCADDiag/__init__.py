"""FreeCAD Diag 애드온 패키지.

FreeCAD는 Mod/<Name>/ 를 sys.path에 넣기 때문에 하위 모듈이 전역 이름으로
보일 수 있다(다른 애드온과 충돌 위험). InitGui.py에서 상위 Mod 디렉토리를
sys.path에 넣고 `FreeCADDiag.xxx`로만 import한다.
"""

__version__ = "0.1.0"
