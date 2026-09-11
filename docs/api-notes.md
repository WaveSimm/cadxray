# FreeCAD API 확인 노트 (cadxray)

확인 기준: FreeCAD 소스 태그 **1.0.2**와 **1.1.3** (2026-09-09, GitHub sparse checkout). 두 태그에서 같은 사실은 `[1.0.2][1.1.3]`, 한쪽만이면 그 태그를 적었다.
소스 발췌는 로컬 `docs/freecad-src-ref/<태그>/src/...`에서 봤다(LGPL-2.1). 저장소에는 넣지 않는다 — 필요하면 `CADXRAY_SPEC.md` 부록 A.2의 sparse checkout으로 받는다. 실제 설치 버전에서는 명세 부록 A.1의 라이브 introspection으로 한 번 더 확인한다.

---

## 0. 바인딩 정의 파일 — 1.0과 1.1이 다르다

| 버전 | Python API 정의 파일 | 예 |
|---|---|---|
| 1.0.x | `*Py.xml` | `src/Mod/Sketcher/App/SketchObjectPy.xml` |
| 1.1.x | `*.pyi` (이름에 `Py` 없음) | `src/Mod/Sketcher/App/SketchObject.pyi` |

구현부는 두 버전 모두 `*PyImp.cpp`. docstring은 xml/pyi에서 생성된다.

---

## 1. `App.Version()` `[1.0.2][1.1.3]`

문자열 리스트, 순서 고정:
`[Major, Minor, Point, Revision, RepositoryURL, RevisionDate, RevisionBranch, RevisionHash]`
→ `major, minor = int(v[0]), int(v[1])`로 분기한다. (`src/App/ApplicationPy.cpp` `sGetVersion`)

---

## 2. `App.DocumentObject` `[1.0.2][1.1.3]`

- `State` → `list[str]`. 가능한 값: `Touched`, `Invalid`, `Recompute`, `Recompute2`, `Restore`, `Expanded`, `Partial`, `Importing`, `Up-to-date` (`DocumentObjectPyImp.cpp getState`)
- `getStatusString()` → 에러 상태면 **문서가 가진 에러 설명 문자열**(없으면 `"Error"`), 아니면 `"Touched"` / `"Valid"`. `[1.1.3]`에서 `"Freezed"` 추가. (`DocumentObject.cpp`) → tracked_recompute와 document_graph의 `status` 필드에 그대로 쓴다.
- 의존관계: `OutList`, `InList`, `OutListRecursive`, `InListRecursive`
- 식별: `Name`, `FullName`, `ID`, `Document`; 상태: `MustExecute`, `isValid()`, `recompute()`, `touch()`, `purgeTouched()`
- `ViewObject` — GUI가 없으면 `None`
- 프로퍼티(속성으로 접근): `Label`, `Label2`, `ExpressionEngine`(`[(prop, expr), ...]`), `Visibility` (`DocumentObject.h`)
- PropertyContainer 공통: `PropertiesList`, `getPropertyByName(name)`, `getTypeIdOfProperty(name)`, `getGroupOfProperty(name)`, `getDocumentationOfProperty(name)`, `getPropertyStatus(name)`, `getEditorMode(name)`
- `[1.1.3]` 추가: `Placement` 속성, `getPlacementOf()`
- **덤프하면 안 되는 프로퍼티 타입** `[라이브 1.1.3 확인, 2026-09-10]` — `inspect_object`는 타입명만 남긴다:
  `Part::PropertyPartShape`(Shape/AddSubShape/PreviewShape), `Part::PropertyGeometryList`, `Sketcher::PropertyConstraintList`, `App::PropertyPythonObject`(Proxy), `Mesh::PropertyMeshKernel`, `Points::PropertyPointKernel`, `Materials::PropertyMaterial`(repr에 메모리 주소가 들어가 호출마다 값이 바뀐다)
- `ExpressionEngine`은 프로퍼티 목록에도 나오고 속성으로도 읽힌다. 값 형태: `[('Length', '<<Spreadsheet>>.height')]` `[라이브 1.1.3]`

## 3. `App.Document` `[1.0.2][1.1.3]`

- `recompute(objs=None) -> int` — 재계산된 피처 수 반환. 실패 객체는 예외가 아니라 `State`에 `Invalid`가 들어간다.
  - `[라이브 1.1.3 확인, 2026-09-10]` 두 번째 인자로 강제 재계산 플래그를 받는다: `doc.recompute(None, False)`, `doc.recompute([obj], False)` 모두 동작. 이미 Up-to-date인 객체만 주면 `0`을 돌려준다.
  - 실패한 객체는 `Invalid`와 함께 **`Touched`도 남는다**. 그래서 `still_touched`가 비지 않는 것이 정상 — 에러 판단은 `Invalid`로 한다.
  - 에러 설명 예 `[라이브 1.1.3]`: `Pad.Length = 0` → `getStatusString()`이 `"Cannot create a pad with a total length of zero."`
- `mustExecute()`, `purgeTouched()`, `Objects`, `RootObjects`, `getObject(name)`, `FileName`, `Name`, `Label`
- **정정** `[라이브 1.1.3 확인, 2026-09-10]`: `Document.Modified` 속성은 **없다**(`AttributeError`). 저장 여부는 `isSaved() -> bool`, 변경 여부는 `isTouched() -> bool`. 두 메서드는 1.0.2 `DocumentPy.xml`·1.1.3 `Document.pyi` 양쪽에 있다. `Modified`는 GUI 쪽(`Gui.Document`) 이름이다. → `list_documents`는 `saved`/`modified`(=`not isSaved()`)/`touched`를 준다.
- 그 밖에 실제로 있는 것 `[라이브 1.1.3]`: `Temporary`, `Uid`, `Id`, `TransientDir`, `LastModifiedDate`, `LastModifiedBy`, `CreatedBy`, `CreationDate`, `RecomputesFrozen`, `Recomputing`, `DependencyGraph`, `TopologicalSortedObjects`, `findObjects()`, `getObjectsByLabel()`
- 모듈: `FreeCAD.listDocuments()` → dict, `FreeCAD.getDocument(name)`, `FreeCAD.ActiveDocument`, `FreeCAD.GuiUp`

---

## 4. `Sketcher.SketchObject` — 진단의 핵심 `[1.0.2][1.1.3]`

### 4.1 solve 결과 속성 (모두 SketchObject 자체에 있음 — 솔버 객체 우회 불필요)

| 속성 | 의미 | 주의 |
|---|---|---|
| `DoF` (int) | 마지막 solve의 자유도 (`getLastDoF`) | **solve() 또는 recompute 이후에만 유효** |
| `ConflictingConstraints` (list[int]) | 충돌 제약 번호 | **1-based**(아래 4.2) |
| `RedundantConstraints` (list[int]) | 중복 제약 번호 | 1-based |
| `PartiallyRedundantConstraints` (list[int]) | 부분 중복 | 1-based |
| `MalformedConstraints` (list[int]) | 잘못된 제약 | 1-based |
| `FullyConstrained` (bool 프로퍼티) | solve **성공(err==0)일 때만** `lastDoF == 0`으로 갱신 | solve 실패 시 이전 값이 남는다 → 반드시 `solve_status`와 함께 판단 |
| `OpenVertices` (list[(x,y,z)]) | edge가 1개뿐인 정점 = 열린 와이어 끝점. `Shape`에서 즉시 계산, **스케치 로컬 좌표** | recompute된 `Shape` 기준이므로 최신 상태를 보려면 recompute 후 읽는다 |
| `MissingPointOnPointConstraints` 외 3종 | `(First, FirstPos, Second, SecondPos, Type)` 튜플 리스트 | **`detectMissingPointOnPointConstraints(precision, includeconstruction)` 등을 먼저 호출해야 채워짐**(반환값 = 개수) |
| `GeometryCount`, `ConstraintCount`, `AxisCount` | 개수 | |
| `GeometryFacadeList` | 각 지오메트리의 `Construction`, `Blocked`, `Id`, `InternalType`, `GeometryLayerId`, `Tag`, `Geometry` | construction 플래그는 `getConstruction(geoId)`도 두 버전 모두 있음 |

프로퍼티: `Geometry`, `Constraints`, `ExternalGeometry`, `Placement`, `AttachmentSupport`, `MapMode`, `AttachmentOffset`, `Shape`

### 4.2 `solve()` 반환 코드 `[1.0.2][1.1.3]` (docstring 원문 기준)
```
 0  성공
-4  over-constrained          ← 우선순위 1
-3  conflicting constraints   ← 2
-5  malformed constraints     ← 3
-1  solver error              ← 4
-2  redundant constraints     ← 5
```
`solve_status_text`는 이 표로 만든다.

**라이브 검증** `[1.1.3, 2026-09-10]` — `tests/fixtures/make_test_models.py`의 T1~T4로 확인:

| 상황 | `solve()` | `DoF` | `FullyConstrained` | 채워지는 목록 |
|---|---|---|---|---|
| 완전 구속 (T1) | `0` | `0` | `True` | — |
| 치수 부족 (T2) | `0` | `3` | `False` | — |
| 같은 선에 값이 다른 길이 제약 2개 (T3) | **`-4`** (`-3` 아님) | `-1` | `True` ← **거짓값** | `ConflictingConstraints = [12, 13]` |
| 열린 와이어 (T4) | `0` | `10` | `False` | `OpenVertices` 2개 |

- **중요**: 값이 다른 중복 치수는 문서 설명상 "conflicting"이지만 `solve()`는 **`-4`(over-constrained)**를 돌려주고, 목록은 `ConflictingConstraints`에 들어간다. 코드는 반환값이 아니라 **어느 목록이 찼는지**로 판단해야 한다.
- **중요**: solve 실패 시 `FullyConstrained`가 `True`로, `DoF`가 `-1`로 남는다(T3). → `solve_status != 0`이면 `fully_constrained`를 `null`로 내보낸다.
- 저장된 문서를 막 열었을 때 `DoF`는 실제와 다를 수 있다(실측: 열자마자 `0` → `solve()` 후 `1`). **반드시 solve()를 먼저.**
- `getStatusString()`(T3): `"Over-constrained sketch\nRemove at least one of the following conflicting constraints:12\n, 13\n"` — 번호가 1-based임을 다시 확인해 준다.
- 열린 곳이 한 군데여도 `OpenVertices`는 **2개**(맞물리지 않은 양쪽 끝점 각각). 그 스케치를 쓰는 Pad는 `State`에 `Invalid`, `getStatusString()`이 `"Wire is not closed."`.

### 4.3 제약 번호는 1-based
솔버가 제약을 추가할 때 `tag = ++ConstraintsCounter`(0에서 시작)로 붙이고(`Sketch.cpp`), `ConflictingConstraints` 등은 이 tag를 그대로 돌려준다. GUI 제약 패널의 번호와 같다. Python `sk.Constraints[i]`로 접근하려면 **`i = id - 1`**. 응답에는 `id`(1-based)와 `index`(0-based)를 둘 다 넣는다.

### 4.4 GeoId 규칙 (`GeoEnum.h`)
- `-1` = H축(및 RootPoint), `-2` = V축, `-3` 이하 = 외부 지오메트리 (`ExternalGeometry[-GeoId-1]`), `-2000` = 미정의
- `PointPos`: `0` none(edge 자체), `1` start, `2` end, `3` mid

### 4.5 Constraint 속성 (`Sketcher.Constraint`)
`Type`(str), `First`, `FirstPos`, `Second`, `SecondPos`, `Third`, `ThirdPos`, `Value`(float), `Name`, `Driving`, `InVirtualSpace`, `IsActive`, `LabelDistance`, `LabelPosition`

`Type` 문자열: `Coincident`, `Horizontal`, `Vertical`, `Parallel`, `Tangent`, `Distance`, `DistanceX`, `DistanceY`, `Angle`, `Perpendicular`, `Radius`, `Equal`, `PointOnObject`, `Symmetric`, `InternalAlignment`, `SnellsLaw`, `Block`, `Diameter`, `Weight` (`Constraint.h`)

### 4.6 버전 차이
- `[1.1.3]` **`movePoint` 삭제** → `moveGeometry(...)`, `moveGeometries(...)`로 대체. `execute_code`로 스케치를 수정하는 코드를 쓸 때 1.1에서는 `movePoint`를 쓰면 안 된다(정확한 시그니처는 `SketchObject.pyi` 참조).
- `[1.1.3]` 추가: `delConstraints`, `setGeometryIds`, `setVisibility`, `setAllowUnaligned`
- `Sketcher.Sketch`(솔버 객체)의 `Conflicts`/`Redundancies`/`Constraint`는 존재하지만 **사용하지 않는다** — 위 SketchObject 속성으로 충분.

---

## 5. Part 지오메트리 (스케치 요소) `[1.0.2][1.1.3]`

| 클래스 (`TypeId`) | 좌표 속성 |
|---|---|
| `Part::GeomLineSegment` | `StartPoint`, `EndPoint` |
| `Part::GeomCircle` | `Radius`, `Center`, `Axis`, `Location` (Conic) |
| `Part::GeomArcOfCircle` | `Radius`, `Center`, `Circle`, `StartPoint`, `EndPoint`(BoundedCurve), `FirstParameter`, `LastParameter` |
| `Part::GeomPoint` | `X`, `Y`, `Z` |
| `Part::GeomEllipse` / `GeomArcOfEllipse` | `MajorRadius`, `MinorRadius`, `Center`, `Focal` |
| `Part::GeomBSplineCurve` | `Degree`, `NbPoles`, `NbKnots`, `StartPoint`, `EndPoint`, `KnotSequence` |

공통: `TypeId`, `Tag`; GeometryCurve: `value(u)`, `length()`, `isClosed()`, `discretize(...)`

---

## 6. `Part.Shape` (TopoShape ← ComplexGeoData) `[1.0.2][1.1.3]`

- ComplexGeoData: `BoundBox`, `CenterOfGravity`, `Placement`
- TopoShape: `ShapeType`, `Orientation`, `Faces`, `Edges`, `Vertexes`, `Wires`, `Shells`, `Solids`, `CompSolids`, `Compounds`, `SubShapes`, `Length`, `Area`, `Volume`
- `isNull()`, `isValid()`, `isClosed()`, `check(runBopCheck=False)` — 문제가 있으면 **예외를 던진다** → `try/except Exception as e`로 메시지를 `check_message`에 담는다. 수리: `fix(prec, mintol, maxtol)`, `removeSplitter()`
- Face: `Surface`, `Wire`, `OuterWire`, `Mass`, `CenterOfMass`, `Tolerance`, `ParameterRange` (+ 상속 `Area`, `Orientation`)
- Edge: `Curve`, `Length`, `Closed`, `Degenerated`, `FirstParameter`, `LastParameter`, `Continuity`
- 면/모서리 분류: `type(face.Surface).__name__` → `Plane`, `Cylinder`, `Cone`, `Sphere`, `Toroid`, `BSplineSurface`, `BezierSurface`, `SurfaceOfRevolution`, `SurfaceOfExtrusion`, `OffsetSurface` / `type(edge.Curve).__name__` → `Line`, `Circle`, `Ellipse`, `BSplineCurve`, `BezierCurve`, `Hyperbola`, `Parabola`
- BoundBox: `XMin/XMax/YMin/YMax/ZMin/ZMax`, `XLength/YLength/ZLength`, `Center`, `DiagonalLength`
- `[1.1.3]` `makeOffset` 추가, `Location`·`oldFuse` 삭제 (진단에 무관)

---

## 7. PartDesign `[1.0.2][1.1.3]`

- `PartDesign::Body` (← `Part::BodyBase` + OriginGroupExtension): `Tip`(PropertyLink), `BaseFeature`, `Group`(PropertyLinkList — 피처 목록), `Origin`, py 속성 `VisibleFeature`, 메서드 `insertObject()`
- `PartDesign::Feature`: `BaseFeature`, `Shape`(**Body 누적 형상**), `getBaseObject()`; `[1.1.3]` `SuppressedShape`
- `PartDesign::FeatureAddSub`(Pad, Pocket, Revolution, Groove, Loft, Pipe, Helix 등): **`AddSubShape`** = 그 피처 자체의 형상
  - **정정** `[라이브 1.1.3 확인, 2026-09-10]`: `AddSubType`은 Pad에 Python 속성으로 **없다**(`AttributeError`). C++ 쪽 이름이고 바인딩에 노출되지 않는다. `AddSubShape`는 정상. → `analyze_shape`는 `AddSubType`이 있을 때만 `add_sub_type`을 넣는다.
  - `Pad`(1.1.3)의 실제 `PropertiesList` 확인 예: `AddSubShape`, `AllowMultiFace`, `AlongSketchNormal`, `BaseFeature`, `Direction`, `Length`, `Length2`, `Midplane`, `Offset`, `PreviewShape`, `Profile`, `ReferenceAxis`, `Refine`, `Reversed`, `Shape`, `ShapeMaterial`, `SideType`, `Type`, `UpToFace`
- 타입 문자열 예: `PartDesign::Body`, `PartDesign::Pad`, `PartDesign::Pocket`, `PartDesign::Fillet`, `PartDesign::Chamfer`, `PartDesign::Hole`, `PartDesign::LinearPattern`

---

## 7.5 PartDesign으로 STEP 재구성할 때 확인한 것 `[라이브 1.1.3, 2026-09-10]`

- **Sketch에 트레이스한 기하는 Block으로 고정한다.** `Coincident`를 시작/끝점을 잘못 짝지어 걸면 솔버가 윤곽을 통째로 비틀어 면적이 음수가 되는 자기교차 스케치가 된다(실제로 겪음). 원본 단면(`shape.slice`)에서 옮긴 선분·호는 이미 1e-7 안에서 맞물려 있으므로 `Sketcher.Constraint("Block", geoId)`만 걸면 DoF 0이고 Pad가 닫힌 와이어를 만든다.
- 호는 `Part.ArcOfCircle(Part.Circle(center, normal, r), a0, a1)`로 CCW만 받는다. 두 끝점 각도 차가 π보다 크면 시작·끝을 바꿔 짧은 호로 만든다(180° 넘는 호는 없다고 가정).
- `PartDesign::Groove`(회전 절삭)의 축은 스케치 구성선으로 준다: 구성선을 먼저 추가하면 `ReferenceAxis = (sketch, ["Axis0"])`. 프로파일은 축 한쪽에만 있어야 하고 `Angle=360`.
- XZ 평면 스케치: 로컬 x = 전역 x, 로컬 y = 전역 z, 법선 −Y → `AttachmentOffset.Base.z = −y`가 평면 y. YZ 평면: 로컬 x = 전역 y, 로컬 y = 전역 z, 법선 +X → Pocket은 −X로 파므로 뒤판에서 안쪽으로 파려면 `Reversed=True`.
- 서로 떨어진 Pad는 한 Body에 넣을 수 없다("multiple solids") → 겹치는 순서로 쌓는다(아래 띠 → 가운데 → 위 띠).
- **정확한 불리언은 면이 겹치는 두 형상에서 실패한다.** 원본과 재구성본처럼 면이 일치하는 쌍은 `a.cut(b)`가 null이나 전체를 돌려준다 → `a.cut(b, 1e-4)`(퍼지)로 하고, 두께 0인 조각(BoundBox 한 변이 0)은 무시한다. 잔차 판정은 부피·면적·bbox 차 + 퍼지 차집합의 실제 조각으로.
- **2D 면 불리언은 피한다.** `Part.Face.fuse`로 단면의 구멍을 메우려 하면 면이 갈라지고(5개) 직선이 BSplineCurve로 바뀐다. 대신 **3D에서** 구멍 자리를 `Part.makeBox`로 덮어 `shape.fuse(boxes).removeSplitter()` 한 사본을 만들고 그것을 `slice`하면 바깥 윤곽 하나가 Line/Circle만으로 나온다. 귀(ear) 영역 같은 부분 윤곽도 `face.extrude(V(0,0,1)).cut(cylinder/box)` 후 다시 `slice`로 뜬다.
- **불리언이 만든 정점은 이상적인 원에서 ~1e-5 벗어난다.** 원본 정점은 이웃 요소끼리 공유돼 있어 틈이 0으로 보이지만, 중심·반지름·각도로 다시 그린 호의 끝점은 이웃과 9e-6 어긋나고 Sketcher(허용치 1e-7)는 "Wire is not closed"를 낸다. 틈은 **그려진 기하(`sk.Geometry[i].StartPoint/EndPoint`)** 기준으로 재고, 틈이 있는 이음매에선 반지름 큰 쪽 요소를 Block 대신 `Radius` + 이웃과 `Coincident`(진행 방향으로 짝지은 PointPos)로 잡는다 → 솔버가 틈을 닫고 DoF 0. `get_sketch_diagnostics`의 `open_vertices`·`missing_point_on_point`가 이걸 바로 보여준다.
- 회전 절삭(Groove)은 360°라 부품 윤곽 밖(앞판 앞으로 나온 귀 등)까지 깎는다. 원본의 절삭 공기가 어느 면에서 끝나는지 확인하고, 깎인 영역을 같은 z 범위의 Pad로 되돌린다(배럴 홈 → 가운데 귀, 시트 립 → 앞판 앞 띠 귀).
- 어셈블리에서 온 STEP 부품은 좌표 끝자리가 지저분하다(예: 34.843193). 정점에서 기준점(X0,Y0,Z0)을 읽으면 나머지 치수는 깔끔한 설계값(6.25, 8.75, 1.65/tan60…)으로 떨어진다.

## 8. Base 타입 (직렬화) `[1.0.2][1.1.3]`

| 타입 | 속성 |
|---|---|
| `Vector` | `x`, `y`, `z` (소문자), `Length` |
| `Placement` | `Base`(Vector), `Rotation`, `Matrix` |
| `Rotation` | `Axis`, `Angle`(라디안), `Q`(쿼터니언 튜플), `RawAxis` |
| `BoundBox` | 6장 참조 |

### `Base.Quantity` `[라이브 1.1.3 확인, 2026-09-10]`

`App::PropertyLength` 등 단위 프로퍼티를 `getPropertyByName()`으로 읽으면 float이 아니라 `Base.Quantity`가 온다. `isinstance(v, FreeCAD.Units.Quantity)`로 판별한다.

| 속성 | 값 예 |
|---|---|
| `Value` | `15.0` (float, 내부 단위 = mm) |
| `Unit` | `Unit: mm (1,0,0,0,0,0,0,0) [Length]` — `Unit.Type` → `"Length"` |
| `UserString` | `"15.00 mm"` (사용자 표시 정밀도 적용) |
| `Format` | `{'Precision': 2, 'NumberFormat': 'f', 'Denominator': 8}` |

메서드는 `getValueAs`, `getUserPreferred`, `toStr`뿐. → `serialize`는 `{"value": 15.0, "text": "15.00 mm", "quantity": "Length"}`로 낸다.

---

## 9. 3D 뷰 (`FreeCADGui` View3DInventor) `[1.0.2][1.1.3]`

- 얻기: `FreeCADGui.getDocument(name).ActiveView` 또는 `FreeCADGui.ActiveDocument.ActiveView`. GUI가 없으면(FreeCADCmd) 불가.
- 뷰 프리셋: `viewIsometric()`, `viewFront()`, `viewTop()`, `viewRight()`, `viewRear()`, `viewBottom()`, `viewLeft()`, `viewAxonometric()`, `viewDimetric()`, `viewTrimetric()`, `fitAll()`, `zoomIn()`, `zoomOut()`, `viewPosition(...)`, `getCamera()/setCamera()`, `getCameraType()/setCameraType()`, `getSize()`
- `saveImage(filename, width=-1, height=-1, background="Current", comment="$MIBA", samples=<기본>)` — `PyArg_ParseTuple("et|iissi")`. `background`는 `"Current"` 또는 QColor가 이해하는 이름/hex(`"White"`, `"Black"`, `"#ffffff"`, `"Transparent"`). **저장 디렉토리가 없으면 RuntimeError**. 오프스크린 렌더러라 창이 가려져 있어도 된다.

`[라이브 1.1.3 확인, 2026-09-10]`
- `FreeCADGui.getDocument(name).ActiveView` + `viewIsometric()` + `fitAll()` + `saveImage(path, w, h, "White")` 조합이 그대로 동작한다. 400×300~2400×1800까지 확인.
- 소요 시간은 크기와 무관하게 대략 **350~470 ms**(뷰 전환·fitAll 포함).
- PNG 크기 실측: 단순 모델 800×600 ≈ 8.6 KB, 2400×1800 ≈ 33 KB. 박스 320개 모델 2400×1800 ≈ **145 KB** → base64로 194 KB.
  → 스크린샷 응답은 하드캡(100 KB)을 넘길 수 있다. `get_screenshot.no_size_cap = True`로 표시하고 `rpc_server._dump`가 그 툴만 캡을 건너뛴다.

---

## 10. 부착 (AttachExtension) `[1.0.2][1.1.3]`

`AttachmentSupport`(PropertyLinkSubList), `MapMode`(enum 문자열), `AttachmentOffset`(Placement), `MapReversed`, `MapPathParameter`.
`Support`는 0.21 이하에서만 쓰던 이름 — 1.x 대상인 이 프로젝트에서는 `AttachmentSupport`만 쓰고, `hasattr` 폴백만 둔다.

`[라이브 1.1.3 확인, 2026-09-10]`
- `hasattr(sk, "Support")` → **False**. 폴백은 실제로 쓰이지 않는다(코드는 그대로 둔다).
- `AttachmentSupport` 값 형태: `[(<DocumentObject>, ('XY_Plane',))]` — 리스트 안의 (객체, 서브이름 튜플). Body 안 스케치는 평면을 직접 가리키지 않고 **Origin 객체의 서브요소**(`Origin` + `'XY_Plane'`)를 가리킨다.
- 부착이 없으면 `MapMode == "Deactivated"`, `AttachmentSupport == []`.

---

## 11. 명세(7장)에 반영한 결론

1. **`get_sketch_diagnostics` 절차**: `sk.solve()` → `DoF`/`Conflicting…`/`Redundant…`/`PartiallyRedundant…`/`Malformed…`/`FullyConstrained` 읽기 → `detectMissingPointOnPointConstraints()` 호출 후 `MissingPointOnPointConstraints` 읽기 → `OpenVertices` 읽기. 솔버 객체(`Sketcher.Sketch`) 복제는 하지 않는다.
2. 충돌·중복 번호는 1-based. 응답에 `id`와 `index`를 둘 다 넣고, 잘리더라도 해당 제약은 항상 포함한다.
3. `getStatusString()`으로 에러 설명을 얻을 수 있다 → `tracked_recompute`의 `status`, `get_document_graph`의 `status`에 사용.
4. `Shape.check()`는 예외로 보고한다 → 예외 메시지를 `check_message`로.
5. 1.1.x에서 `movePoint`가 없다 → CLAUDE.md의 "수정 코드 작성 시 주의"에 기록.
6. `saveImage`는 저장 폴더가 있어야 하고 `background` 문자열은 QColor 이름을 받는다.

---

## 11.5 Assembly 워크벤치 스크립팅 `[라이브 1.1.3 확인, 2026-09-10]`

FreeCAD 1.x 내장 Assembly를 `execute_code`로 만들 수 있다 (MCP 전용 툴은 없음 — 명세 밖).

- 타입: `Assembly::AssemblyObject`, `Assembly::JointGroup`, `Assembly::AssemblyLink`, `Assembly::BomObject/BomGroup`, `Assembly::ViewGroup`, `Assembly::SimulationGroup`
- 조인트 종류 `JointObject.JointTypes` (인덱스 순): `Fixed, Revolute, Cylindrical, Slider, Ball, Distance, Parallel, Perpendicular, Angle, RackPinion, Screw, Gears, Belt`
- 만드는 순서 (순서가 중요):
  ```python
  import JointObject
  asm = doc.addObject("Assembly::AssemblyObject", "Assembly")
  jg  = doc.addObject("Assembly::JointGroup", "Joints"); asm.addObject(jg)
  lk  = doc.addObject("App::Link", "Link_x"); lk.LinkedObject = part; asm.addObject(lk)
  g = doc.addObject("App::FeaturePython", "Grounded"); JointObject.GroundedJoint(g, lk); jg.addObject(g)
  j = doc.addObject("App::FeaturePython", "Joint"); jg.addObject(j)   # ← JointGroup에 먼저 넣고
  JointObject.Joint(j, 2)                                             #    초기화 (Cylindrical). 순서 바꾸면 assembly.Type NoneType 에러
  j.Reference1 = (asm, ["Link_x.Face3"])                              # PropertyXLinkSub: (어셈블리, ["링크이름.면이름"]) 형태만 받는다
  j.Reference2 = (asm, ["Link_y.Face7"])                              #   [(obj, (sub,))] 형태는 "Expect input sequence of size 2"
  doc.recompute(); asm.solve()                                        # 0 = 성공, 링크 Placement가 움직인다
  ```
- **문서 간 링크는 원본 문서가 저장돼 있어야 한다** (`RuntimeError: Linked document not saved`). STEP을 연 `Unnamed` 문서의 부품을 다른 문서에서 링크하려면 먼저 저장하거나, 같은 문서 안에서 만든다.
- **STEP 부품을 Body에 넣을 때** (`body.BaseFeature = part_feature`): STEP 임포터는 형상을 로컬 좌표 + `Placement`로 저장하는데, Body는 BaseFeature의 Placement를 **버린다** → 80부품이 전부 원점 근처로 흩어진다(실제로 겪음). `body.Placement = part.Placement`를 따로 주면 원위치. `part.Shape.copy()`는 Placement를 품고 있어 `Part::Feature`에 넣으면 Placement가 그대로 옮겨진다.
- `Assembly::AssemblyObject.Group`에는 부품 외에 `Assembly::JointGroup`과 접지 조인트(`App::FeaturePython`, Shape 없음)가 같이 들어 있다. 어셈블리를 부품 목록으로 풀 때 이것들을 건너뛰어야 한다(`check_interference`의 `_expand`).
- 80부품 접지 어셈블리 생성 실측: 5.7초, 파일 4.6 MB(원본 형상 80 + Body 80 + 원점 81 = 객체 970개). `asm.solve()` 0.
- `GroundedJoint`는 프로퍼티 `ObjectToGround` 하나. 어느 면이 어느 면과 맞물리는지(조인트 참조)는 자동으로 알 수 없다 — 사람이 지정하거나 `find_holes`/`analyze_shape`로 축·반지름이 맞는 원통면을 골라 준다.

## 12. STEP 가져오기·형상 분석 (M6용) `[1.0.2][1.1.3]`

### Import 모듈 (`src/Mod/Import/App/AppImportPy.cpp`)
- `Import.open(name, docName=None, importHidden=bool, merge=bool, useLinkGroup=bool, mode=int)` — 새 문서 생성
- `Import.insert(name, docName, importHidden=bool, merge=bool, useLinkGroup=bool, mode=int)` — 기존 문서에 삽입
- `mode` (`ImportOCAF2.h` `ImportMode`): `0` SingleDoc, `1` GroupPerDoc, `2` GroupPerDir, `3` ObjectPerDoc, `4` ObjectPerDir
- `merge=True`면 솔리드를 하나로 합친다. 부품별 분석을 하려면 False.
- `Import.export(objs, filename)` — STEP 내보내기 (테스트 fixture 생성에 사용)
- 결과 객체: `Part::Feature`(솔리드), 어셈블리 구조가 있으면 `App::Part`(또는 `useLinkGroup=True`면 `App::LinkGroup`) 계층. 히스토리(스케치·피처) 없음.

### 형상 분석 API
- 원통면: `type(face.Surface).__name__ == "Cylinder"` → `face.Surface.Radius`, `.Center`, `.Axis` (Cylinder.pyi / CylinderPy.xml)
- 평면: `face.Surface.Position`, `.Axis` (Plane)
- 솔리드 물성 (TopoShapeSolid): `Mass`, `CenterOfMass`, `MatrixOfInertia`, `StaticMoments`, `PrincipalProperties`(dict), `OuterShell`, `getMomentOfInertia()`, `getRadiusOfGyration()`. `Mass`는 밀도 1 기준 = 부피.
- 거리·간섭: `a.distToShape(b, tol=1e-7) -> (dist, [(p1, p2), ...], infos)`; `a.common(b)` 또는 `a.common((b, c), tolerance)` → 교집합 Shape, `.Volume`으로 간섭 부피
- 유효성: `shape.check(True)` — BOP 검사 포함, 문제 시 예외. 큰 형상에서는 느림.
- 단위: FreeCAD 내부 길이 단위는 mm. 질량 = Volume(mm³)/1000 × 밀도(g/cm³) [g].

### 라이브 확인 `[1.1.3, 2026-09-10]`
- docstring은 `Import.open(string)`, `Import.insert(string,string)`, `Import.export(list,string)`만 보여주지만 키워드 인자(`importHidden`, `merge`, `useLinkGroup`, `mode`)는 소스대로 받는다. 코드는 `TypeError` 폴백을 둔다.
- `Cylinder` 표면 속성: `Radius`, `Axis`, `Center` (+ `UPeriod`, `VPeriod`, `Rotation`). `Center`는 축 위의 한 점.
- **구멍/보스 판정**: 면 중앙 `p = face.valueAt(u, v)`, `n = face.normalAt(u, v)`, 축 위 발 `foot`에 대해 `(foot - p)·n > 0`이면 오목(구멍). `normalAt`이 면의 `Orientation`(구멍면은 `Reversed`)을 반영하므로 따로 뒤집지 않는다. 구멍 → True, 보스 → False 확인.
- `Part.makeCylinder`로 뺀 구멍은 원통면 **1개**, 스케치 원으로 Pocket한 구멍은 보통 반원통 **2개** → 축·반지름·축선으로 묶어야 한다.
- **나사산은 STEP에 없다** `[벤더 어셈블리 실측]`: 80부품 중 나사산을 모델링한 부품 0개. `leadscrew`조차 Ø8×365 매끈한 원통 하나(원통 1·평면 2). 암나사는 탭 드릴 지름의 민구멍으로 온다 → `find_holes`는 지름을 ISO 미터나사 표(탭 드릴·ISO 273 관통)와 대조해 `thread_hint`를 추정으로만 붙인다. 나선 BSpline 면에서 피치를 재는 기능은 만들지 않았다(대상 파일이 없음).
- **원뿔면** `[라이브 1.1.3, 벤더 어셈블리 원뿔 302개]`: `type(face.Surface).__name__ == "Cone"`, 속성 `Apex`, `Axis`(꼭짓점에서 넓어지는 방향), `Center`, `Radius`(기준 반지름), `SemiAngle`(**라디안**, 반각). 45° 챔퍼는 SemiAngle π/4, 90° 카운터싱크는 π/4, 118° 드릴 끝은 59°. 오목/볼록 판정은 원통과 같은 방법(`normalAt`이 축을 향하면 오목)이 그대로 통한다. 반지름은 축 위치에 선형이므로 면 꼭짓점의 축 거리로 양 끝 반지름을 구한다.
- 원통면 `face.ParameterRange`의 `(u0, u1)`은 **각도(라디안)**. 온전한 구멍은 합이 2π, 내부 모서리 필렛은 π/2(90°), 슬롯 끝은 π. `[벤더 STEP 실측]` 각기둥 내부 R1 필렛 4개가 처음엔 "Ø2 막힌 구멍"으로 잡혔다 → `arc_deg`로 `kind`를 나눈다.
- 같은 축선·같은 반지름이라도 **축 방향으로 떨어진** 면은 다른 구멍이다. `[벤더 STEP 실측]` ±X 벽의 1 mm 자리파기 2개가 40 mm 관통 하나로 묶였다 → 면별 축 구간을 구해 겹치는 것끼리만 묶는다.
- `Solid.Mass == Solid.Volume` (밀도 1). `PrincipalProperties` 키: `Moments`, `RadiusOfGyration`, `FirstAxisOfInertia`, `SecondAxisOfInertia`, `ThirdAxisOfInertia`, `SymmetryAxis`, `SymmetryPoint`. `MatrixOfInertia`는 `Base.Matrix`(`A11`~`A33`), 전역 원점 기준.
- `a.distToShape(b)[0]`: 겹치면 `0.0`, 떨어져 있으면 거리. `a.common(b).Volume`: 10×10×10 두 상자를 5 겹치면 `500.0`.
- **속도 실측** `[1.1.3, 80부품 3,149면 어셈블리]`: `distToShape`는 100면급 부품 쌍에서 **중앙값 36 ms, 최대 171 ms** → 3,160쌍 전부면 약 130 s. 바운딩박스가 떨어진 쌍은 `distToShape` 없이 축별 간격(실거리의 하한)으로 끝낸다 → 대부분의 쌍이 0 ms. `App::Part.Shape`는 자식 전체의 compound라 `Solids`가 80개로 나온다(질량 합산에 그대로 쓸 수 있음).
- 응답 크기: 쌍 300개를 전부 담으면 88 KB(브릿지 하드캡 안이지만 Claude Code 표시 한도 초과) → 기본은 문제 쌍만 담는다.
- `shape.isInside(point, tol, checkFace)`: 구멍 중심축 위 점 → False, 재료 안 → True. 관통 판정 휴리스틱에 쓴다.
- **STEP 이름의 한글** `[라이브 1.1.3, 벤더 파일]`: FreeCAD가 ISO 10303-21 이스케이프를 풀지 않는다. `\X2\c6d4d30c\X0\`(UTF-16BE 16진수)가 Label에 그대로 남는다 → `util.decode_step_text`로 응답에서만 푼다. 실측: `20250624_\X2\c6d4d30c\X0\ …` → `20250624_월파 브라켓(수정본)`.
- **메시(STL)**: `Mesh.insert(path, docName)`으로 `Mesh::Feature`가 생기지만 `Shape`가 없어 위 API를 전혀 쓸 수 없다. `Part.Shape().makeShapeFromMesh((verts, facets), tol)`로 삼각면 컴파운드를 만들 수는 있으나 docstring이 "rather small meshes only"라고 경고하고, 원통면이 없으므로 `find_holes`는 불가. M6 범위 밖.

## 13. STEP → 파라메트릭 재구성 툴(M7)에서 확인한 것 `[라이브 1.1.3, 2026-09-10]`

### 면 정체 판별 (classify_faces)
- 면 표본: `face.ParameterRange` 격자에서 `face.isPartOfDomain(u, v)`가 True인 점만 `face.valueAt(u, v)`·`face.normalAt(u, v)`. `Surface.isPlanar(tol)`, `Surface.curvature(u, v, "Max"|"Min"|"Gauss"|"Mean")`도 BSpline 면에서 동작한다.
- **`normalAt`의 부호를 믿으면 안 된다.** `transformGeometry`로 만든 원뿔 BSpline 면은 같은 면 안에서도 일부 표본의 법선이 뒤집혀 나온다(z 성분 ±0.707 섞임). 그래서 축 판정은 `|n·a|`의 분산으로, 오목/볼록·법선 방향은 표본 다수결로 한다.
- 벤더 STEP의 BSpline 전이면(2B2 더브테일·립)은 **원뿔에 6.6e-5 잔차**로 맞는다 — 법선 z 성분이 2e-4 흔들려 법선 공분산의 최소 고유값이 0이 아니므로(4e-5 vs 총 0.08) "최소 고유값 ≈ 0" 기준으로는 못 잡는다. 후보 축(Σnnᵀ·공분산 고유벡터 + X/Y/Z)마다 축 위치(법선 직선 최소제곱)와 r(t) 선형 맞춤을 다 해 보고 잔차 최소를 고른다. 2B2 결과: 축 Z, 꼭짓점 (38.176526, 45.052724, ·), 반각 59.63°, 반지름 33.758~34.862 — 손으로 읽은 값과 일치.
- `Shape.transformGeometry(Matrix())`는 **모든 면을 BSplineSurface로 바꾼다**(항등 행렬이어도). 가짜 자유곡면 fixture(T7)를 만드는 데 쓴다. 유효성은 유지되지만 원통·원뿔의 BSpline 근사 때문에 **부피가 0.012 % 줄어든다**(18514.18 → 18512.00 mm³) — `compare_shapes`로는 identical이 아니라 match.
- BSpline 솔리드의 `slice`는 직선도 `BSplineCurve`(Degree 1, NbPoles 2), 원은 Degree 5·134 poles로 돌려준다 → 단면 요소는 `edge.discretize(Number=n)` 표본으로 직선(최대 편차)·원(대수적 원 맞춤 잔차) 순서로 다시 판별해야 한다.

### 단면 (section_profile)
- **`common()`은 상자 면이 부품 면과 정확히 겹치면 빈 결과**를 준다(2B2 앞판 x=32.343193에 맞춘 상자: 부피 0, 1e-3 어긋나면 정상). 같은 자리에서 `cut()`은 정상 → 범위 밖을 상자로 `cut`해서 클립한다.
- 구멍 메우기 원기둥은 **축 방향 여유를 주면 안 된다**: 부품 밖으로 0.05 튀어나온 원기둥이 단면 윤곽에 혹(관통 구멍당 9 mm³)으로 남는다. 축 방향은 면 정점 범위 그대로, 반지름만 +0.05.
- 채우기 대상은 오목 원통·원뿔 그룹 중 **호 합 ≥ 350°**인 것만. 필렛(90°)·슬롯 끝(180°)을 메우면 윤곽이 바뀐다. BSpline으로 맞춘 면의 호 범위는 표본 격자로는 과소평가되므로(4×4 격자 → 270°) 면 경계(`OuterWire.Edges[i].discretize`)의 각도 범위로 잰다.

### 스케치 트레이스 (build_features)
- 호를 "틈이 있는 이음매만 골라 한쪽을 Radius+Coincident로 풀어 주는" 7.5절 방식은 **자유 요소가 이어지면 DoF가 남고**(2B2 아래 띠 DoF 3), 경우에 따라 과구속(-4)도 났다. 대신 **이음매마다 원래 정점에 Block한 구성점(`Part.Point`, construction=True)을 두고 호의 양 끝을 그 점에 Coincident + Radius**로 잡으면 호 5 − 1 − 2 − 2 = 0, 선분은 Block → 모든 단면 스케치 DoF 0 (2B2 12개 전부).
- 호의 시작·끝 각도는 끝점 좌표에서 다시 계산한다. 4자리로 반올림한 `angle_deg`를 쓰면 끝점이 r·1.7e-6 어긋난다.
- 단면 좌표를 6자리로 반올림하면 이음매마다 5e-7 틈 → DoF가 남는다. 스케치로 돌아갈 좌표는 10자리.
- **반지름은 측정값 그대로 쓴다.** 홈 바닥 33.620391을 33.6204로 반올림해 귀(ear) 영역을 뜨면 귀의 호 면이 홈 바닥 면과 9e-6 어긋난 채 겹쳐 Pad의 fuse가 0.6 mm³(0.006 %)를 잃는다. 정확히 같은 값이면 0.0004 %.
- Spreadsheet: `sheet.getUsedCells()` → ['A1', 'B1', …], `sheet.getCellFromAlias("h")` → 'B1', `sheet.getContents("B1")` → '16'. 빈 셀 `get()`은 "Invalid cell address or property" 예외. Sketch에는 `DoF`, `FullyConstrained`, `solve()`가 있다.
- Groove/Revolution의 축 구성선은 **프로파일보다 먼저** 추가해야 `Axis0`이다. 빈 Body에 Groove를 넣으면 실패하지 않고 회전체를 만든다(1.1.3).

### 검증 (compare_shapes)
- 면이 겹치는 두 형상의 퍼지 차집합(`cut(b, 1e-4)`)은 **형상 전체를 조각으로 돌려주기도 한다**(챔퍼까지 만든 2B2). fuzzy를 10배씩 키우면(1e-3) 정상 조각이 나오지만 얇은 차이는 삼킨다 → 판정은 max(조각 합, |부피 차|)로. 조각이 전혀 안 잡히는데 부피가 다르면 얇은 층(near-coincident 면)이다 — 피처별 부피를 옛 결과와 비교해 찾았다.
- 슬랩(`common(box)`)으로 z 구간별 부피를 재는 방법은 겹친 면 때문에 구간당 ~0.1 mm³ 오차가 있어 0.5 mm³ 이하 차이는 못 찾는다.

### 샘플 3종(spacerA·collar·Part 25)에서 추가로 확인한 것 `[라이브 1.1.3, 2026-09-10]`
- **정확히 180°인 호**는 양 끝을 고정하면 반지름이 현으로 결정돼 Sketcher가 `Radius`를 "redundant constraint"로 거부하고 Pad가 실패한다(Part 25 바닥 단면의 R8.75 반원). 150°를 넘는 호는 중간점에서 나눠 그린다(`_split_wide_arcs`) → DoF 0.
- 단면의 **안쪽 와이어 bbox**가 어느 쪽에 있는지로 슬롯·홈의 방향을 읽는다. Part 25의 원뿔 슬롯은 R8.75 둥근 쪽(서)이 아니라 육각·구멍 쪽(동)에 있었다 — 호의 시작각(252.6°)에서 ccw 214.8°는 0°를 지난다. 회전 절삭은 스케치 평면에서 `Angle`만큼 한쪽으로 쓸므로, 양쪽 대칭은 같은 프로파일로 `reversed` 하나 더 (Midplane 없이도 됨).
- 육각 너트 자리는 `polygons`(중심·A/F로 계산한 6점)로 바로 판다. 플랫이 X에 수직이면 꼭짓점은 30°+k·60°, Z에 수직이면 0°+k·60°.
- 챔퍼 대상 모서리는 `edges: {"bbox": {"max": [null, null, z0]}}`처럼 **바닥면 높이**로 고르면 바깥 윤곽·육각 구멍·로브 챔퍼 15개가 한 번에 잡힌다.
- 챔퍼·경사 절단까지 만든 부품에서 `cut(b, 1e-4)`·정확한 cut·1e-3·1e-2 전부 형상 전체를 돌려줬다 → `common()` 교집합으로 총량(missing = Va − Vc, extra = Vb − Vc)을 재는 fallback을 둔다(`method: "common"`).

### 샘플 4·5(end cap·handle clamp)에서 추가로 확인한 것 `[라이브 1.1.3, 2026-09-10]`
- **구멍 메우기의 각도는 합이 아니라 합집합으로** 잰다. end cap의 Ø9 케이블 홈은 같은 축선에 반원 면이 세 토막(168°+180°+180°)이라 합은 528°지만 덮는 각도는 180° — 합으로 판정하면 원기둥으로 메워져 윗면 위로 반원 혹이 생긴다(부피 3.5 % 오차). 면 경계를 36점씩 찍어 각도 합집합의 최대 빈틈으로 판정한다.
- 챔퍼 대상 모서리 필터에 `direction: [1,0,0]`(직선 방향, 부호 무관)이 필요했다. 길이·bbox만으로는 채널 끝벽 윗변(길이 9.05, Y 방향)이 립 모서리(길이 9, X 방향)와 섞인다.
- 팔·리브처럼 **필렛(블렌드)이 있는 면을 단면으로 뜰 때는 블렌드 영역 밖에서** 뜬다. handle clamp의 팔은 바깥 원통에서 2 mm 안쪽까지 R2 블렌드라 y=1 단면은 이미 깎인 윤곽(자유곡선 4개)이고, y=4 단면은 뿌리 블렌드 1개뿐이다. `section_profile`을 y를 바꿔 가며 불러 `unsupported`가 가장 적은 곳을 고른다.
- 작은 블렌드(뿌리 R2)는 `approximate_bspline: true`로 표본점 꺾은선으로 근사하고 나중에 Fillet으로 되살린다. 근사한 선분도 Block이라 DoF 0.
- 몸통 원통에 붙은 팔은 XZ 프로파일을 Y로 돌출한 뒤 X축 둘레 회전 절삭(r > R 영역, 360°)으로 바깥을 원통에 맞추면 된다.
- PartDesign Fillet R2를 팔 모서리 12개에 한 번에 걸면 `BRep_API: command not done`. 실패한 Fillet은 Body.Tip이 그것을 가리키므로 지운 뒤 `Tip = Base`로 되돌려야 한다.
- `common()` fallback도 겹친 면에서 조각만 돌려줄 수 있다(handle clamp: Va 10790에 교집합 7) → 작은 쪽 부피의 절반을 넘을 때만 믿고, 아니면 `method: "volume_only"`.

### 샘플 6·7(foot·handle)에서 확인한 것 `[라이브 1.1.3, 2026-09-10]`
- `PartDesign::Pad.TaperAngle`: **음수가 위로 갈수록 좁아지는(안쪽) 구배**. foot의 5° 구배 외벽은 바닥 사각형 + TaperAngle −5 로 한 번에 나온다(부피 120,114.8 vs 원뿔대 공식 120,109). `build_features`의 pad에 `taper` 필드.
- `PartDesign::Revolution`도 Groove와 같이 첫 구성선을 `ReferenceAxis=(sketch, ["Axis0"])`로. XZ 평면에서 X 방향 축은 `axis: {"y": z값}`(로컬 y = 전역 Z). handle(플랜지·챔퍼·바 반단면 8점) → 회전체 + 위아래 평면 포켓 + 탱 Pad + R5 필렛 + 피벗 6피처로 **identical(6e-6 %)** — 첫 시도.
- foot의 노치 플레어는 진짜 BSpline이지만 `classify_faces`가 `best_axis_fit`(잔차 0.0036)으로 원뿔 힌트를 줬고, `tolerance=0.005`로 다시 부르면 cone(반각 44.9°, 반지름 15.8~18.6)으로 판정한다. 원통(R15, 0.8 mm) + 45° 원뿔 회전 절삭으로 근사하면 부피 차 0.003 %, 노치 부근 국소 차 ~18 mm³.
- 5° 구배 벽의 노치처럼 **축이 살짝 기운(2.4°) 원뿔 판정**은 축 정렬 회전 절삭으로 근사할 수밖에 없다. 기운 축은 `axis: {x|y}` 구성선으로 표현할 수 없다(향후: 스케치 회전 지원 여부 검토).

### 전체 재구성·조립(20종 80개)에서 확인한 것 `[라이브 1.1.3, 2026-09-10]`
- **STEP 어셈블리의 `Placement`는 인스턴스 변환이 아니다.** 같은 부품 31개의 로컬 형상(Placement를 뺀 것)이 서로 다르다 — Import가 하위 어셈블리 프레임을 Placement에 넣고 나머지 변환은 Shape에 구워 넣는다. 인스턴스 배치는 형상에서 직접 찾아야 한다(`align_shapes`).
- `align_shapes`: `Solid.PrincipalProperties`의 `FirstAxisOfInertia`… 로 주축을 맞춘 뒤 검증. 검증에 `common()`은 못 쓴다(회전 사본에서 80 %), `isInside(tol, True)`도 표면 위 점을 놓친다(같은 자리 사본 87.5 %) → 정점·면 위 점(`valueAt` 파라미터 중앙)을 옮겨 `distToShape(Part.Vertex)` ≤ tol 인 비율로 잰다. 곡면의 `CenterOfMass`는 표면 밖이라 프로브로 쓰면 안 된다.
- D형 캡 31개 중 일부는 **거울상**(왼손 기저에서만 100 %). Link의 Placement로는 반사를 못 하므로 `Part::Mirroring`(Source·Base·Normal) 본을 만들어 그것을 정렬한다. `Part::Mirroring`의 Shape는 Compound라 `CenterOfMass`가 없다 → `CenterOfGravity`.
- 대칭 부품(rod)은 주 관성모멘트가 겹쳐 주축이 임의다 → 축 둘레 45° 간격 후보를 더해 100 %.
- 문서 이름이 숫자로 시작하면 FreeCAD가 앞에 `_`를 붙인다(`2C1_tools` → `_2C1_tools`) → 스크립트가 문서를 못 찾는다.
- `section` `clip` 상자는 형상의 로컬 2D 범위 전체를 덮어야 한다. 원점 기준 ±대각선으로 잡으면 원점에서 먼 부품(2C2, y 45~80)은 일부만 잘려 앞 귀 복원이 전체 단면을 다시 더해 립 쐐기를 메웠다.
- 스크립트를 '기록 모드'(build_features 가로채기)로 다시 실행해 피처 목록만 모을 때, 스크립트 안의 `reload_handlers()`가 가로채기를 되돌린다 → 그 줄을 빼고 exec.

## 14. TechDraw 스크립팅 `[라이브 1.1.3 확인, 2026-09-11]`

`examples/techdraw_page_from_assembly.py`로 확인. 전용 툴(M8)은 아직 명세에 없어 `execute_code`로 만든다.

- `TechDraw::DrawViewPart.Source`에 `App::Link`를 직접 넣으면 뷰가 "Valid"인데 `getVisibleEdges()`가 0개 — 형상을 못 뽑는다. Link들을 `Part::Compound(Links=[…])`로 묶어 Source로 준다. 컴파운드를 숨겨도(`ViewObject.Visibility=False`) 투영된다
- 뷰 `X`/`Y`는 `page.addView(view)` **뒤에** 넣는다. 앞에 넣으면 addView가 페이지 중앙(148.5, 105)으로 되돌린다
- `TechDraw.makeDistanceDim3d(view, 'DistanceY', p1, p2)`: 페이지 창이 열려 있지 않으면 "DDH::makeDistDim - dim not found" 또는 Access violation. 열려 있으면 치수를 만들지만 **반환값은 None**이고, 만든 코스메틱 정점이 축척과 맞지 않아 값이 50배 등으로 틀린다. 쓰지 않는다
- 치수는 `TechDraw::DrawViewDimension`을 직접 만든다: `Type='DistanceX|DistanceY|Distance'`, `References3D=[(compound,'VertexN'),(compound,'VertexM')]`, `References2D=[(view,'')]`, `MeasureType='Projected'`. `'True'`는 두 정점의 3D 직선거리라 DistanceX/Y 구분이 무시된다(6000 → 6087). 정점 번호는 `compound.Shape.Vertexes`에서 좌표로 찾는다(1-based)
- 정점이 없는 거리(원통 실루엣 사이)는 `References2D=[(view, ('EdgeA','EdgeB'))]`로 세로 모서리 두 개를 참조한다. 모서리 번호는 `view.getVisibleEdges()`의 인덱스(0-based)와 같았다. 재투영·축척 변경으로 바뀔 수 있으니 매번 찾는다
- 치수 `ScaleType`은 기본 'Page'(=1.0). 뷰 축척과 다르면 값이 틀리므로 `ScaleType='Custom'`, `Scale=view.getScale()`로 맞춘다. 뷰 축척을 바꾸면 치수도 다시 맞춘다(안 맞추면 2500이 2000으로)
- `DrawViewDetail`: `BaseView`, `Source`(=BaseView.Source), `AnchorPoint`(BaseView 좌표 = 축척 전 모델 mm, 뷰 기하 중심 `getGeometricCenter()` 기준), `Radius`(모델 mm), `Reference`('A'), `ScaleType/Scale`
- `DrawViewAnnotation`: `Text`(줄 목록), `TextSize`, X/Y (addView 뒤)
- 기본 템플릿 `Templates/Default_Template_A4_Landscape.svg`는 11줄짜리 빈 페이지(테두리·표제란·EditableTexts 없음). 표제란은 `Templates/ISO/A3_Landscape_TD.svg` 등(EditableTexts: FC-Title, Subtitle, AuthorName, CreationDate, SupervisorName, CheckDate, scale, Weight, drawing_number, SheetNumber, copyright). 다른 크기는 `ISO/A?_Landscape_ISO5457_advanced|minimal|notitleblock.svg`, `ASME/`
- 페이지 창 열기: `Gui.getDocument(doc).getObject(page).doubleClicked()` (반환 True). 내보내기 `TechDrawGui.exportPageAsPdf(page, path)` / `exportPageAsSvg` — 페이지 크기(A3=1191×842 pt)로 나온다
- 뷰 방향: 정면 `Direction (0,-1,0)`, `XDirection (1,0,0)`; 우측면 `(1,0,0)` / `(0,1,0)`; 평면 `(0,0,1)` / `(1,0,0)`; 등각 `(1,-1,1)` / `(1,1,0)`
- **투영은 비동기다** `[라이브 1.1.3, 2026-09-11]`: DrawViewPart의 HLR이 별도 스레드에서 돌고 결과가 메인 이벤트 루프로 들어온다. 한 번의 `execute_code`/툴 호출 안에서 recompute 직후 `getVisibleEdges()`를 부르면 0개다(Link 27개 컴파운드 정면도 ≈ 20초). `QtCore.QCoreApplication.instance().processEvents()`를 돌리며 모서리가 생길 때까지 기다린다(`handlers/drawing.py::_wait_for_views`). FreeCADCmd(헤드리스)에서는 동기적으로 끝난다. Python에는 `waitingForHlr` 같은 메서드가 없다
- 상세 뷰(DrawViewDetail)의 `getGeometricCenter()`는 앵커 기준이라 3D 점을 뷰 좌표로 투영해 원 모서리를 찾을 때 어긋난다 → 반지름이 맞는 원이 하나뿐이면 그것을 쓴다
- `DrawViewAnnotation.X`는 글자 블록의 중앙이다(왼쪽 끝이 아니다)

## 15. 외관(색·투명) `[라이브 1.1.3 확인, 2026-09-11]`

- `ViewObject.ShapeAppearance = (App.Material,)` — `DiffuseColor`/`SpecularColor`/`AmbientColor`/`Shininess`. Body에 주면 Tip에도 적용되지만 피처마다 복사해 두는 편이 안전(`examples/ink_holder_from_photo.py`)
- 면별 `Material.Transparency`(ShapeAppearance를 면 수만큼 준 경우)는 3D 뷰에서 투명으로 그려지지 않는다. 투명은 `ViewObject.Transparency = 0~100`(객체 전체)로만. 부분만 투명하려면 바디를 나눈다
- `App::Link`는 `OverrideMaterial=False`(기본)면 원본 Body의 색·투명을 따른다. Link에 따로 `Transparency`를 주지 않아도 된다
- **함정**: 피처를 지우고 `body.Tip`을 이전 피처로 되돌리면 그 피처의 `ViewObject.Visibility`가 False인 채 남아 Body(와 그 Link 전부)가 화면에서 사라진다. 형상은 멀쩡하다. `body.Tip.ViewObject.Visibility = True`로 켠다

## 16. Mesh(STL) API와 나사(Helix) `[라이브 1.1.3 확인, 2026-09-11]`

`examples/stl_spool_guide_with_m7.py`에서 확인. M8 설계 근거.

- 읽기: `Mesh.insert(path, docName)` → `Mesh::Feature`. `Mesh.Mesh`: `CountFacets`, `CountPoints`, `Points`(각 `.x .y .z`), `BoundBox`, `Volume`, `isSolid()`, `hasNonManifolds()`, `hasSelfIntersections()`
- `mesh.crossSections([((px,py,pz),(nx,ny,nz)), ...], tol)` → 평면마다 폴리라인 목록(각 폴리라인은 `Vector` 목록, 닫힌 것은 첫 점이 끝에 반복). 5,758면 메시에서 단면 하나 수 ms. 최소제곱 원 피팅(Kasa)으로 반지름을 0.01 mm 안에 얻었다
- `mesh.getPlanarSegments(dev, min_facets)` → 면 인덱스 목록의 목록. `getSegmentsOfType("Cylinder", dev, min)`은 삼각형화된 원통을 못 찾았다(스풀 가이드 0개, 시험 판 2구멍 중 1개) — 원통은 단면 원 피팅으로 잡는다
- `Part.Shape().makeShapeFromMesh(mesh.Topology, tol)` + `Part.makeSolid`: 5,758면 → 1.6 s, 부피 일치. 그러나 이 솔리드로 `compare_shapes`(퍼지 불리언)를 부르면 **10분 넘게 메인 스레드가 막힌다** — 메시 비교는 불리언 금지
- `mesh.nearestFacetOnRay((sx,sy,sz), (dx,dy,dz))` → `{facet_index: (x,y,z)}` dict, 못 맞히면 빈 dict. 표본점 900개 × 양방향 ≈ 0.8 s. 시작점을 표면 뒤 0.6 mm에 두면 자기 면을 맞힌다(5 mm는 얇은 판 반대편을 맞힘)
- 역방향: 메시 정점(≤ 1,500) → `shape.distToShape(Part.Vertex(p))[0]` ≈ 4 s
- `execute_code` 결과 직렬화는 리스트 중첩 깊이에 한계가 있다(`"<depth limit: float>"`). 깊은 구조는 문자열로 평탄화해 돌려준다
- `PartDesign::SubtractiveHelix`(`AdditiveHelix`도 같음): `Profile=(sketch, [""])`, `ReferenceAxis=(sketch, ["V_Axis"])`, `Mode="pitch-height-angle"`, `Pitch`, `Height`, `Angle`, `LeftHanded`, `Reversed`, `Outside`. 프로파일 스케치를 XZ 평면에 붙일 때 축을 부품 중심 (cx, cy)로 옮기려면 `AttachmentOffset = Placement(Vector(cx, 0, -cy))` — XZ 평면의 로컬 z가 전역 **−Y**다(로컬 x=X, y=Z). 오른나사(z 증가에 각도 증가)는 `LeftHanded=False`
- 나선은 프로파일 각도(0°)에서 시작해 그 이전 각도 구간의 첫 바퀴는 깎이지 않는다 → 한 피치 아래에서 시작하고(Height +2 피치) 아래쪽에 잘린 부분은 Pad로 되메운다. 위상: 프로파일의 골 중심 z가 각도 0°에서의 골 위치와 같아야 한다(단면에서 z별 최대 반지름 각도로 잰다)
- 나사 판별 신호: 높이별 단면의 최대 반지름 각도가 z에 비례해 돈다(피치 2 → 1 mm당 180°). 정점을 (각도, z)로 펼쳐 그리면 사선 줄무늬. 단면 z 간격은 피치의 절반보다 작아야 각도가 접히지 않는다(`analyze_mesh`는 0.2 mm, 최대 60장). 한 단면의 원 피팅 중심은 산 쪽으로 치우치므로 여러 높이의 피팅 중심을 평균한다
- 메시 단면 폴리라인 피팅 규칙(`handlers/mesh.py::polyline_to_elements`, 스풀 가이드 실측 2026-09-11): (1) 꼭짓점 검출(RDP) 허용값은 피팅 허용값 이하 — 크면 직선 끝에 붙은 필렛 첫 점이 직선 구간에 섞여 "직선도 원도 아님"이 된다. (2) 호 병합 판정은 rms가 아니라 **최대 잔차** — 긴 호 끝에 직선 점 한두 개가 섞여도 rms는 작아 가짜 호(R70.6)가 생긴다. (3) 닫힌 고리는 꺾임각이 가장 큰 꼭짓점에서 시작 — 호 중간에서 시작하면 그 호가 둘로 갈라진다. 결과: 슬롯(호·직선·R10·호·R10·직선) 6요소, 창 4요소, 최대 잔차 0.022
- `Mesh.Facet`: `Area`, `Normal`, `Points`(3점), `PointIndices`, `NeighbourIndices`. `getPlanarSegments(dev, min_facets)`는 면이 min_facets보다 적은 평면을 버린다(작은 면은 삼각형 2개) → 레벨은 면별 법선으로 직접 묶는다(`handlers/mesh.py::_mesh_levels`)
- `FreeCAD.openDocument(path)`로 연 문서의 `Name`은 파일명에서 온다(저장 전 이름은 남지 않는다). 소문자로 정규화한 경로를 넘기면 이름도 소문자가 된다 — 비교만 `os.path.normcase(realpath)`로, 열 때는 원래 경로로

## 17. 스케치 제약 자동 감지·수정 API `[라이브 1.1.3 확인, 2026-09-11]`

`handlers/sketch_fix.py`에서 사용.

- `sk.detectMissingPointOnPointConstraints(tol)` → 개수. 결과는 `sk.MissingPointOnPointConstraints` = [(geo1, pos1, geo2, pos2, type)] (type 1 = Coincident). `makeMissingPointOnPointCoincident(bool)`은 감지된 것을 전부 적용 — 선별 적용은 `addConstraint(Sketcher.Constraint("Coincident", g1, p1, g2, p2))`로 직접
- `sk.detectMissingVerticalHorizontalConstraints(deg)` → `MissingVerticalHorizontalConstraints` = [(geo, 0, -2000, 0, type)] type 2 = Horizontal, 3 = Vertical. 이미 정확히 수평인 선도(제약이 없으면) 들어온다
- `sk.detectMissingEqualityConstraints(tol)` → `MissingLineEqualityConstraints` = [(g1, 0, g2, 0)], `MissingRadiusConstraints` = [(g1, 0, g2, 0)]
- `sk.getGeometryWithDependentParameters()` → [(geo, pos)] 솔버가 자유롭다고 보는 요소(pos 0 = 모서리, 1/2/3 = 점). 남은 DoF의 위치를 알려준다
- `sk.autoRemoveRedundants(bool)`, `sk.autoconstraint`, `sk.analyseMissingPointOnPointCoincident`(끝점 접선/수직 분석), `deleteAllConstraints()`도 있다
- `sk.OpenVertices`는 **Shape 기준**이라 `solve()`만으로는 갱신되지 않는다 → `sk.recompute()`(객체 단위) 뒤에 읽는다
- `doc.copyObject(sk, False)`로 스케치 사본을 만들어 후보를 적용·solve해 보면 원본이 안 바뀐다(Body 밖에 생김, 쓰고 `removeObject`). 헤드리스 콘솔에 "Importing project files" 진행 메시지가 찍힌다
- 제약을 값으로 저장해 되돌리기: `(Type, First, FirstPos, Second, SecondPos, Third, ThirdPos, Value, Name, Driving)` → `deleteAllConstraints()` 후 `addConstraint` 재생성 + `renameConstraint`·`setDriving`
