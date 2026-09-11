"""어셈블리(Link 인스턴스) → TechDraw 페이지: 정면·우측·평면 + 상세 2개 + 치수 13개 + 주석 + 표제란, PDF/SVG 내보내기.
pole_frame 문서(examples/pole_frame_from_dxf.py)로 만든 것. FreeCAD GUI 안에서 exec (페이지 창이 열려 있어야 한다).

FreeCAD 1.1.3에서 확인한 규칙 (docs/api-notes.md §14):
- DrawViewPart.Source에 App::Link를 직접 주면 뷰가 비어 나온다(가시 모서리 0). Link들을 Part::Compound(Links)로 묶어 Source로 준다
- View.X/Y는 page.addView(view) **뒤에** 넣는다. 앞에 넣으면 addView가 페이지 중앙으로 되돌린다
- TechDraw.makeDistanceDim3d는 페이지가 열려 있어야 하고 반환값이 None이며, 만든 코스메틱 정점이 축척과 안 맞아 값이 틀린다 → 쓰지 않는다
- 치수는 DrawViewDimension을 직접 만들어 References3D=[(compound,'VertexN'),…] + MeasureType='Projected'로. 'True'는 두 점의 3D 직선거리라 DistanceX/Y가 무시된다
- 정점이 없는 거리(기둥 면 사이 2500)는 References2D=[(view,('EdgeA','EdgeB'))]로 실루엣 모서리 두 개를 참조. 모서리 번호는 재투영·축척 변경 때 바뀔 수 있으니 getVisibleEdges()로 매번 찾는다
- 치수는 ScaleType='Custom', Scale=소유 뷰.getScale()로 맞춘다. 뷰 축척을 바꾸면 다시 맞춘다
- 기본 템플릿 Default_Template_A4_Landscape.svg는 테두리·표제란이 없는 빈 페이지. ISO/A3_Landscape_TD.svg(EditableTexts: FC-Title, Subtitle, AuthorName, CreationDate, scale, drawing_number, SheetNumber …)를 쓴다
- 내보내기: TechDrawGui.exportPageAsPdf(page, path) / exportPageAsSvg
"""
import os
import FreeCAD as App
import FreeCADGui as Gui
import TechDrawGui

DOC = "pole_frame"
doc = App.getDocument(DOC)
App.setActiveDocument(DOC)
for o in list(doc.Objects):
    if o.TypeId.startswith("TechDraw::"):
        doc.removeObject(o.Name)

# 소스: Link 인스턴스를 Part::Compound로
comp = doc.getObject("FrameShape") or doc.addObject("Part::Compound", "FrameShape")
comp.Links = list(doc.getObject("Frame").Group)
doc.recompute()
if App.GuiUp:
    comp.ViewObject.Visibility = False       # 숨겨도 투영된다

page = doc.addObject("TechDraw::DrawPage", "Page_Frame")
tpl = doc.addObject("TechDraw::DrawSVGTemplate", "Template_Frame")
tpl.Template = os.path.join(App.getResourceDir(), "Mod", "TechDraw", "Templates", "ISO", "A3_Landscape_TD.svg")
page.Template = tpl
SC = 1 / 40.0

def view(name, direction, xdir, x, y, scale=SC, caption=None):
    v = doc.addObject("TechDraw::DrawViewPart", name)
    v.Source = [comp]
    v.Direction, v.XDirection = App.Vector(*direction), App.Vector(*xdir)
    v.ScaleType, v.Scale = "Custom", scale
    if caption:
        v.Caption = caption
    page.addView(v)
    v.X, v.Y = x, y                          # addView 뒤에
    return v

front = view("ViewFront", (0, -1, 0), (1, 0, 0), 78, 165, caption="FRONT")
right = view("ViewRight", (1, 0, 0), (0, 1, 0), 158, 165, caption="RIGHT")
top = view("ViewTop", (0, 0, 1), (1, 0, 0), 225, 262, caption="TOP")
doc.recompute()
gc = front.getGeometricCenter()

def detail(name, base, model_xz, radius, scale, x, y, ref):
    dv = doc.addObject("TechDraw::DrawViewDetail", name)
    dv.BaseView, dv.Source = base, base.Source
    dv.AnchorPoint = App.Vector(model_xz[0] - gc.x, model_xz[1] - gc.z, 0)   # BaseView 좌표(축척 전 모델 mm, 뷰 중심 기준)
    dv.Radius, dv.Reference = radius, ref
    dv.ScaleType, dv.Scale = "Custom", scale
    page.addView(dv)
    dv.X, dv.Y = x, y
    return dv

detA = detail("DetailA", front, (0, 1300), 150, 1 / 5.0, 235, 165, "A")
detB = detail("DetailB", front, (0, 150), 400, 1 / 10.0, 330, 165, "B")
doc.recompute()

# 치수: 컴파운드 정점 참조(Projected). 정점은 좌표로 찾는다
verts = [(i + 1, v.Point) for i, v in enumerate(comp.Shape.Vertexes)]
def vertex(**want):
    for i, p in verts:
        if all(abs(getattr(p, k) - val) < 0.05 for k, val in want.items()):
            return f"Vertex{i}"
    raise RuntimeError(f"정점 없음: {want}")

def dim3(view, kind, a, b, x, y, label):
    d = doc.addObject("TechDraw::DrawViewDimension", "Dim_" + label)
    d.Type, d.MeasureType = kind, "Projected"
    d.References3D = [(comp, vertex(**a)), (comp, vertex(**b))]
    d.References2D = [(view, "")]
    page.addView(d)
    d.X, d.Y = x, y
    return d

R = 133.7
dim3(front, "DistanceY", dict(z=0, x=-300), dict(x=R, y=0, z=6000), -56, 0, "H6000")
dim3(front, "DistanceY", dict(z=550, x=-75), dict(z=5050, x=-75), 46, -10, "Tube4500")
dim3(front, "DistanceY", dict(z=0, x=-400), dict(x=25, y=-211.37, z=1100), -42, -60, "Hole1100")   # 각관 Ø50 구멍의 심 정점
dim3(front, "DistanceX", dict(x=-400, z=-1000), dict(x=400, z=-1000), 0, -93, "Found800")
dim3(front, "DistanceY", dict(x=400, z=-1000), dict(x=400, z=0), 22, -80, "Found1000")
dim3(right, "DistanceX", dict(y=-900, z=0, x=-300), dict(y=900, z=0, x=-300), 0, -93, "Base1800")
dim3(right, "DistanceX", dict(y=-211.37, z=550), dict(y=-111.37, z=550), -20, 80, "TubeD100")
dim3(detA, "DistanceY", dict(x=25, y=-211.37, z=1300), dict(x=25, y=-211.37, z=1500), 22, 0, "Pitch200")
dim3(detA, "DistanceX", dict(x=-75, z=550), dict(x=75, z=550), 0, -26, "TubeW150")
dim3(detB, "DistanceY", dict(x=-153.7, y=5, z=10), dict(x=-153.7, y=5, z=410), -34, 0, "Gusset400")   # 거싯 정점은 y=±5(판 두께)
dim3(detB, "DistanceX", dict(x=-283.7, y=5, z=10), dict(x=-133.7, y=5, z=410), 0, 36, "GussetW150")
dim3(detB, "DistanceX", dict(x=-300, y=-900, z=0), dict(x=300, y=-900, z=0), 0, -46, "Base600")

# 기둥 면 사이 2500: 정점이 없어 정면도의 세로 실루엣 모서리 두 개를 참조
sc = front.getScale()
edges = front.getVisibleEdges()
def vertical_edge_at(xmodel):
    xt = (xmodel - gc.x) * sc
    cands = [(i, abs(e.Vertexes[0].Point.y - e.Vertexes[-1].Point.y)) for i, e in enumerate(edges)
             if abs(e.Vertexes[0].Point.x - e.Vertexes[-1].Point.x) < 1e-3 and abs(e.Vertexes[0].Point.x - xt) < 0.05]
    return max(cands, key=lambda c: c[1])[0]
d = doc.addObject("TechDraw::DrawViewDimension", "Dim_Span2500")
d.Type, d.MeasureType = "DistanceX", "Projected"
d.References2D = [(front, (f"Edge{vertical_edge_at(R)}", f"Edge{vertical_edge_at(2767.4 - R)}"))]
page.addView(d)
d.X, d.Y = 0, 96
for o in doc.Objects:
    if o.TypeId == "TechDraw::DrawViewDimension":
        o.ScaleType, o.Scale = "Custom", o.References2D[0][0].getScale()

note = doc.addObject("TechDraw::DrawViewAnnotation", "Note")
note.Text = ["PIPE-250A SCH160 (OD267.4 x 28.4t) x2  /  PIPE-150A SCH160 (OD165.2 x 18.2t) x1, L2500 (coped, raw 2557)",
             "TUBE 150x100x4.5 L4500 x2 : HOLE D50 x20 @200 (1st 1100 from parapet) + M8 x4 (66)",
             "GUSSET PL10t 150x400 x16  /  BASE PL10t 600x1800 x2  /  CAP PL6t D240 x2  /  SUS316",
             "FOUNDATION 800x1000 (DEPTH 1800 ASSUMED)   TUBE WALL 4.5 ASSUMED"]
note.TextSize = 2.4
page.addView(note)
note.X, note.Y = 300, 96
et = dict(tpl.EditableTexts)
et.update({"FC-Title": "POLE FRAME - YEONDAE HARBOR", "Subtitle": "FRONT / RIGHT / TOP 1:40   DETAIL A 1:5   DETAIL B 1:10",
           "AuthorName": "cadxray", "CreationDate": "2026-09-11", "scale": "1:40 (A 1:5, B 1:10)", "drawing_number": "PF-001",
           "SheetNumber": "1/1", "SupervisorName": "-", "CheckDate": "-", "Weight": "-"})
tpl.EditableTexts = et
doc.recompute()
Gui.getDocument(DOC).getObject("Page_Frame").doubleClicked()     # 페이지 창 열기 (내보내기에 필요)
Gui.updateGui()
OUT = os.path.join(os.path.expanduser("~"), "pole_frame_page")
TechDrawGui.exportPageAsPdf(page, OUT + ".pdf")
TechDrawGui.exportPageAsSvg(page, OUT + ".svg")
_result = {"dims": sorted((o.Label, round(o.getRawValue(), 1)) for o in doc.Objects if o.TypeId == "TechDraw::DrawViewDimension"),
           "invalid": [o.Name for o in doc.Objects if not o.isValid()], "pdf": OUT + ".pdf"}
