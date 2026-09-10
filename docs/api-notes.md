# FreeCAD API 확인 노트 (freecad-diag-mcp)

확인 기준: FreeCAD 소스 태그 **1.0.2**와 **1.1.3** (2026-09-09, GitHub sparse checkout). 두 태그에서 같은 사실은 `[1.0.2][1.1.3]`, 한쪽만이면 그 태그를 적었다.
소스는 `docs/freecad-src-ref/<태그>/src/...`에 그대로 있다(LGPL-2.1, LICENSE 동봉). 실제 설치 버전에서는 명세 부록 A.1의 라이브 introspection으로 한 번 더 확인한다.

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
- `Solid.Mass == Solid.Volume` (밀도 1). `PrincipalProperties` 키: `Moments`, `RadiusOfGyration`, `FirstAxisOfInertia`, `SecondAxisOfInertia`, `ThirdAxisOfInertia`, `SymmetryAxis`, `SymmetryPoint`. `MatrixOfInertia`는 `Base.Matrix`(`A11`~`A33`), 전역 원점 기준.
- `a.distToShape(b)[0]`: 겹치면 `0.0`, 떨어져 있으면 거리. `a.common(b).Volume`: 10×10×10 두 상자를 5 겹치면 `500.0`.
- `shape.isInside(point, tol, checkFace)`: 구멍 중심축 위 점 → False, 재료 안 → True. 관통 판정 휴리스틱에 쓴다.
- **STEP 이름의 한글** `[라이브 1.1.3, 벤더 파일]`: FreeCAD가 ISO 10303-21 이스케이프를 풀지 않는다. `\X2\c6d4d30c\X0\`(UTF-16BE 16진수)가 Label에 그대로 남는다 → `util.decode_step_text`로 응답에서만 푼다. 실측: `20250624_\X2\c6d4d30c\X0\ …` → `20250624_월파 브라켓(수정본)`.
- **메시(STL)**: `Mesh.insert(path, docName)`으로 `Mesh::Feature`가 생기지만 `Shape`가 없어 위 API를 전혀 쓸 수 없다. `Part.Shape().makeShapeFromMesh((verts, facets), tol)`로 삼각면 컴파운드를 만들 수는 있으나 docstring이 "rather small meshes only"라고 경고하고, 원통면이 없으므로 `find_holes`는 불가. M6 범위 밖.
