"""make_drawing, inspect_drawing — TechDraw 2D 도면 (M8, 명세 7.21·7.22).

`examples/techdraw_page_from_assembly.py`로 손으로 확인한 절차를 그대로 툴에 넣었다.
규칙 [확인됨: api-notes 14장]:
- App::Link·그룹은 DrawViewPart.Source에 직접 못 넣는다(빈 뷰) → Part::Compound로 묶는다
- View.X/Y는 page.addView() 뒤에 넣어야 남는다
- 치수는 DrawViewDimension을 직접 만든다. 3D 정점 참조 + MeasureType 'Projected'. 값이 틀리지 않게
  ScaleType 'Custom', Scale = 소유 뷰의 getScale()
- 기본 A4 템플릿은 빈 페이지 → ISO 템플릿이 기본값
- 내보내기는 GUI에서 페이지 창을 연 뒤에만 된다
"""

import math
import os
import time

import FreeCAD
import Part

from . import util

_TEMPLATE_DEFAULT = os.path.join("ISO", "A3_Landscape_TD.svg")
_STD_SCALES = [2.0, 1.0, 0.5, 0.2, 0.1, 0.05, 0.04, 0.025, 0.02, 0.01, 0.005, 0.002, 0.001]

# 뷰 종류 → (Direction, XDirection). 정면 = -Y에서 본다(FreeCAD 'Front' 뷰와 같다)
_VIEW_DIRS = {
    "front": ((0, -1, 0), (1, 0, 0)),
    "rear": ((0, 1, 0), (-1, 0, 0)),
    "left": ((-1, 0, 0), (0, -1, 0)),
    "right": ((1, 0, 0), (0, 1, 0)),
    "top": ((0, 0, 1), (1, 0, 0)),
    "bottom": ((0, 0, -1), (1, 0, 0)),
    "iso": ((1, -1, 1), (1, 1, 0)),
}
_TITLE_ALIASES = {
    "title": "FC-Title", "subtitle": "Subtitle", "author": "AuthorName", "date": "CreationDate",
    "scale": "scale", "number": "drawing_number", "sheet": "SheetNumber", "weight": "Weight",
    "supervisor": "SupervisorName", "check_date": "CheckDate",
}


class _DrawError(Exception):
    pass


def _vec(t):
    return FreeCAD.Vector(float(t[0]), float(t[1]), float(t[2]))


def _template_path(template):
    """템플릿 이름/경로 → 절대 경로. 없으면 후보 목록과 함께 오류."""
    base = os.path.join(FreeCAD.getResourceDir(), "Mod", "TechDraw", "Templates")
    cand = template if os.path.isabs(template) else os.path.join(base, template)
    if os.path.isfile(cand):
        return cand
    iso = os.path.join(base, "ISO")
    names = sorted(f for f in os.listdir(iso) if f.endswith(".svg")) if os.path.isdir(iso) else []
    raise _DrawError(f"템플릿을 찾을 수 없습니다: {cand}. 예: " + ", ".join("ISO/" + n for n in names[:12]))


def _resolve_source(doc, source, page_name):
    """source(이름 또는 목록) → (뷰 소스 객체, 원본 객체 목록, 전체 형상, 경고).

    Link·그룹·여러 객체면 Part::Compound '<page>_Source'로 묶는다(재사용).
    """
    names = [source] if isinstance(source, str) else list(source or [])
    if not names:
        raise _DrawError("source에 객체 이름(또는 목록)이 필요합니다.")
    objs = []
    for n in names:
        obj, err = util.find_object(doc, n)
        if err:
            raise _DrawError(err)
        if obj.TypeId == "App::DocumentObjectGroup":
            objs.extend(o for o in obj.Group if hasattr(o, "Shape"))
        else:
            objs.append(obj)
    if not objs:
        raise _DrawError("source에 형상을 가진 객체가 없습니다.")
    for o in objs:
        if not hasattr(o, "Shape") or o.Shape.isNull():
            raise _DrawError(f"{o.Name}에 형상이 없습니다.")
    warnings = []
    need_compound = len(objs) > 1 or objs[0].TypeId in ("App::Link", "App::LinkGroup")
    if need_compound:
        cname = f"{page_name}_Source"
        comp = doc.getObject(cname)
        if comp is None or comp.TypeId != "Part::Compound":
            comp = doc.addObject("Part::Compound", cname)
        comp.Links = objs
        doc.recompute()
        if FreeCAD.GuiUp:
            comp.ViewObject.Visibility = False
        warnings.append(f"Link/여러 객체라 Part::Compound '{cname}'로 묶어 소스로 썼습니다(숨김).")
        shape = comp.Shape
        return comp, objs, shape, warnings
    return objs[0], objs, objs[0].Shape, warnings


def _remove_page(doc, page_name):
    """같은 이름의 페이지와 그 뷰·치수·주석·템플릿을 지운다."""
    page = doc.getObject(page_name)
    if page is None or page.TypeId != "TechDraw::DrawPage":
        return
    names = [v.Name for v in page.Views]
    if page.Template is not None:
        names.append(page.Template.Name)
    for n in names:
        if doc.getObject(n) is not None:
            doc.removeObject(n)
    doc.removeObject(page_name)


def _auto_scale(bb, W, H, view_types):
    """뷰 묶음이 페이지의 60 % 안에 들어가는 표준 축척."""
    X, Y, Z = max(bb.XLength, 1e-3), max(bb.YLength, 1e-3), max(bb.ZLength, 1e-3)
    width = X + (Y if any(v in ("left", "right") for v in view_types) else 0) + (X if "iso" in view_types else 0)
    height = Z + (Y if any(v in ("top", "bottom") for v in view_types) else 0)
    for s in _STD_SCALES:
        if s * width <= 0.6 * W and s * height <= 0.6 * H:
            return s
    return _STD_SCALES[-1]


def _project(view, p):
    """3D 점 → 뷰 2D(축척 전, 뷰 기하 중심 기준). y는 위쪽이 +."""
    d = FreeCAD.Vector(view.Direction).normalize()
    x = FreeCAD.Vector(view.XDirection).normalize()
    y = d.cross(x)
    gc = view.getGeometricCenter()
    q = FreeCAD.Vector(p) - gc
    return q.dot(x), q.dot(y)


def _wait_for_views(views, seconds, warnings):
    """뷰 투영(HLR)이 끝날 때까지 이벤트를 돌리며 기다린다.

    TechDraw 1.1은 투영을 별도 스레드로 돌리고 결과를 메인 이벤트 루프로 넘긴다. 툴이 메인 스레드를
    잡고 있으면 결과가 못 들어와 뷰가 빈 채로 남는다(가시 모서리 0) [라이브 1.1.3]. 그래서 여기서
    processEvents를 돌린다. GUI 없는 FreeCADCmd에서는 동기적으로 끝나므로 바로 통과한다.
    """
    try:
        from PySide import QtCore
        app = QtCore.QCoreApplication.instance()
    except Exception:  # noqa: BLE001
        app = None
    t_end = time.time() + float(seconds)
    pending = list(views)
    while pending and time.time() < t_end:
        if app is not None:
            app.processEvents()
        still = []
        for v in pending:
            try:
                if len(v.getVisibleEdges()) == 0:
                    still.append(v)
            except Exception:  # noqa: BLE001
                still.append(v)
        pending = still
        if pending:
            time.sleep(0.05)
    if pending:
        warnings.append("뷰 투영이 " + f"{seconds}초 안에 끝나지 않았습니다: " + ", ".join(v.Name for v in pending)
                        + " — 큰 어셈블리면 wait_seconds를 늘리세요.")
    return not pending


def _nearest_vertex(shape, p, tol):
    """shape.Vertexes에서 p에 가장 가까운 정점 'VertexN'(1-based)과 거리."""
    best, bi = None, None
    for i, v in enumerate(shape.Vertexes):
        dd = (v.Point - p).Length
        if best is None or dd < best:
            best, bi = dd, i + 1
    if best is None or best > tol:
        return None, best
    return f"Vertex{bi}", best


def _visible_edges(view):
    """뷰의 가시 모서리. conventional=True(y 위쪽 +)를 먼저, 안 되면 기본."""
    try:
        return view.getVisibleEdges(True)
    except Exception:  # noqa: BLE001
        return view.getVisibleEdges()


def _find_edge(view, kind, value, tol_mm=0.05):
    """뷰의 가시 모서리에서 kind='x'|'y'(값 = 뷰 좌표 mm, 축척 후)인 세로/가로 직선 중 가장 긴 것 → 'EdgeN'.

    y는 정확한 부호로 먼저 찾고, 없을 때만 반대 부호(y-아래 좌표계)로 다시 찾는다.
    """
    edges = _visible_edges(view)
    for sign in ((1,) if kind == "x" else (1, -1)):
        best = None
        for i, e in enumerate(edges):
            if len(e.Vertexes) < 2:
                continue
            a, b = e.Vertexes[0].Point, e.Vertexes[-1].Point
            if kind == "x":
                if abs(a.x - b.x) < 1e-3 and abs(a.x - value) < tol_mm:
                    L = abs(a.y - b.y)
                    if best is None or L > best[1]:
                        best = (i, L)
            else:
                if abs(a.y - b.y) < 1e-3 and abs(a.y - sign * value) < tol_mm:
                    L = abs(a.x - b.x)
                    if best is None or L > best[1]:
                        best = (i, L)
        if best:
            return f"Edge{best[0]}"
    return None


def _find_circle_edge(view, center2d, radius_scaled, tol_mm=0.05):
    """뷰의 가시 모서리에서 중심(축척 후 뷰 좌표)·반지름이 맞는 원/호 → 'EdgeN'. y 부호는 양쪽 다 시도."""
    edges = _visible_edges(view)
    cands = []
    for i, e in enumerate(edges):
        c = e.Curve
        if type(c).__name__ != "Circle":
            continue
        if abs(c.Radius - radius_scaled) > tol_mm:
            continue
        dist = min(math.hypot(c.Center.x - center2d[0], c.Center.y - sy * center2d[1]) for sy in (1, -1))
        cands.append((dist, i))
    if not cands:
        return None
    cands.sort()
    # 상세 뷰는 기하 중심이 앵커 기준이라 투영 좌표가 어긋날 수 있다 → 반지름이 맞는 원이 하나뿐이면 그것
    if cands[0][0] < tol_mm or len(cands) == 1:
        return f"Edge{cands[0][1]}"
    return None


def make_drawing(source=None, doc=None, page="Page", template=None, scale=None, views=None, dimensions=None,
                 notes=None, title=None, export="pdf", out_dir=None, vertex_tolerance=0.05, max_dimensions=50,
                 wait_seconds=60, line_width=0.35, smooth_edges=True):
    """3D 객체 → TechDraw 페이지(뷰·치수·주석·표제란) → PDF/SVG. [확인됨: api-notes 14장]"""
    t0 = time.time()
    d, err = util.get_doc(doc)
    if err:
        return util.error(err)
    warnings = []
    try:
        import TechDraw  # noqa: F401  (워크벤치 모듈 존재 확인)

        src_obj, objs, shape, w = _resolve_source(d, source, page)
        warnings.extend(w)
        tpl_path = _template_path(template or _TEMPLATE_DEFAULT)
        _remove_page(d, page)
        pg = d.addObject("TechDraw::DrawPage", page)
        tpl = d.addObject("TechDraw::DrawSVGTemplate", page + "_Template")
        tpl.Template = tpl_path
        pg.Template = tpl
        d.recompute()
        W, H = float(tpl.Width), float(tpl.Height)
        if W <= 0 or H <= 0:
            raise _DrawError(f"템플릿 크기를 읽지 못했습니다: {tpl_path}")

        # --- 뷰 목록 정리 ----------------------------------------------------------
        view_specs = []
        for v in (views if views is not None else ["front", "right", "top"]):
            if isinstance(v, str):
                view_specs.append({"type": v.lower()})
            elif isinstance(v, dict) and "detail" in v:
                view_specs.append({"type": "detail", **v["detail"]})
            elif isinstance(v, dict):
                spec = dict(v)
                spec["type"] = str(spec.get("type", "front")).lower()
                view_specs.append(spec)
            else:
                raise _DrawError(f"views 항목을 이해할 수 없습니다: {v!r}")
        std_types = [s["type"] for s in view_specs if s["type"] != "detail"]
        for t in std_types:
            if t not in _VIEW_DIRS:
                raise _DrawError(f"지원하지 않는 뷰 {t!r}. 가능: {', '.join(_VIEW_DIRS)} 또는 {{'detail': {{...}}}}")
        bb = shape.BoundBox
        s = float(scale) if scale else _auto_scale(bb, W, H, std_types)
        X, Y, Z = bb.XLength, bb.YLength, bb.ZLength

        # --- 자동 배치 (3각법: 정면 왼쪽 아래, 우측면 오른쪽, 평면 위. 세로 묶음은 가용 높이 안에 중앙) -------
        margin, gap = 22.0, 18.0
        bottom = max(60.0, H * 0.22)                      # 표제란 위
        has_top = any(t in ("top", "bottom") for t in std_types)
        has_side = any(t in ("left", "right") for t in std_types)
        stack_h = s * Z + (s * Y + gap if has_top else 0)
        avail_h = (H - 12.0) - bottom
        fy = bottom + s * Z / 2 + max(0.0, (avail_h - stack_h) / 2)
        fx = margin + 10 + s * X / 2 + (s * (X + Y) / 2 + gap if "left" in std_types else 0)
        right_x = fx + s * (X + Y) / 2 + gap
        pos = {
            "front": (fx, fy), "rear": (fx, fy), "bottom": (fx, fy - s * (Z + Y) / 2 - gap),
            "right": (right_x, fy), "left": (fx - s * (X + Y) / 2 - gap, fy),
            "top": (fx, fy + s * (Z + Y) / 2 + gap),
            "iso": (min(W - margin - 45 - s * max(X, Y) * 0.6, (right_x if has_side else fx) + s * (Y if has_side else X) / 2 + gap + s * max(X, Y) * 0.6),
                    fy + (s * (Z + Y) / 2 + gap if has_top else 0)),
        }
        notes_xy = ((W - 185.0) / 2, bottom - 12.0)   # 표제란(오른쪽 아래) 왼쪽의 빈 띠. X는 글자 블록 중앙, 줄은 아래로 이어진다
        created = {}
        base_views = {}
        pending_details = []
        for spec in view_specs:
            t = spec["type"]
            if t == "detail":
                pending_details.append(spec)
                continue
            name = spec.get("name") or ("View" + t.capitalize())
            v = d.addObject("TechDraw::DrawViewPart", name)
            v.Source = [src_obj]
            direction, xdir = _VIEW_DIRS[t]
            v.Direction = _vec(direction)
            v.XDirection = _vec(xdir)
            v.ScaleType = "Custom"
            v.Scale = float(spec.get("scale", s))
            if spec.get("caption") is not None:
                v.Caption = str(spec["caption"])
            elif spec.get("caption", True):
                v.Caption = t.upper()
            pg.addView(v)
            x, y = pos.get(t, (W / 2, H / 2))
            v.X, v.Y = float(spec.get("x", x)), float(spec.get("y", y))   # addView 뒤에 넣어야 남는다
            created[v.Name] = (v, t)
            base_views[t] = v
            base_views[v.Name] = v
        d.recompute()
        _wait_for_views([v for v, _ in created.values()], wait_seconds, warnings)
        # 상세 뷰: BaseView 기하 중심 기준 뷰 좌표(축척 전)
        detail_x = W - margin - 45
        detail_y_next = H - 22.0
        for k, spec in enumerate(pending_details):
            base = base_views.get(str(spec.get("base", "front")))
            if base is None:
                raise _DrawError(f"detail의 base 뷰 '{spec.get('base')}'가 없습니다. 먼저 views에 넣으세요.")
            at = spec.get("at")
            if not at or len(at) != 3:
                raise _DrawError("detail에는 at=[x, y, z](모델 좌표)가 필요합니다.")
            u, vv = _project(base, _vec(at))
            ref = str(spec.get("ref", chr(ord("A") + k)))
            dv = d.addObject("TechDraw::DrawViewDetail", spec.get("name") or ("Detail" + ref))
            dv.BaseView = base
            dv.Source = base.Source
            dv.AnchorPoint = FreeCAD.Vector(u, vv, 0)
            dv.Radius = float(spec.get("radius", 10.0))
            dv.Reference = ref
            dv.ScaleType = "Custom"
            dv.Scale = float(spec.get("scale", min(1.0, s * 5)))
            pg.addView(dv)
            r_page = dv.Radius * dv.Scale
            dv.X, dv.Y = float(spec.get("x", detail_x)), float(spec.get("y", detail_y_next - r_page))
            detail_y_next -= 2 * r_page + 16
            created[dv.Name] = (dv, "detail")
            base_views[dv.Name] = dv
            base_views[ref] = dv
        d.recompute()
        if pending_details:
            _wait_for_views([v for v, t in created.values() if t == "detail"], wait_seconds, warnings)

        # --- 치수 -----------------------------------------------------------------
        dims_out = []
        dim_specs = list(dimensions or [])
        if len(dim_specs) > max_dimensions:
            warnings.append(f"dimensions는 {max_dimensions}개까지만 만듭니다({len(dim_specs)}개 요청).")
            dim_specs = dim_specs[:max_dimensions]
        for i, ds in enumerate(dim_specs):
            try:
                view = base_views.get(str(ds.get("view", "front")))
                if view is None:
                    raise _DrawError(f"view '{ds.get('view')}'가 없습니다.")
                kind = str(ds.get("type", "Distance"))
                label = str(ds.get("label") or f"Dim{i + 1}")
                dim = d.addObject("TechDraw::DrawViewDimension", "Dim_" + label)
                dim.Type = kind
                dim.MeasureType = "Projected"
                sc = view.getScale()
                if kind in ("Diameter", "Radius"):
                    c = ds.get("center")
                    r = ds.get("radius")
                    if not c or r is None:
                        raise _DrawError("Diameter/Radius 치수에는 center=[x,y,z], radius가 필요합니다.")
                    u, vv = _project(view, _vec(c))
                    edge = _find_circle_edge(view, (u * sc, vv * sc), float(r) * sc, tol_mm=max(0.05, vertex_tolerance * sc))
                    if edge is None:
                        raise _DrawError(f"뷰 {view.Name}에서 중심 {c}, 반지름 {r}인 원 모서리를 찾지 못했습니다(가려졌거나 이 뷰에서 원이 아님).")
                    dim.References2D = [(view, (edge,))]
                    refs = "2D:" + edge
                elif ds.get("edges"):
                    eg = ds["edges"]
                    axis = str(eg.get("axis", "x"))
                    vals = eg.get("at")
                    if not vals or len(vals) != 2:
                        raise _DrawError("edges에는 axis('x'|'y')와 at=[모델 좌표 2개]가 필요합니다.")
                    names = []
                    for val in vals:
                        # 모델 좌표(축 위 값) → 뷰 좌표: 축이 뷰의 x/y와 같은 방향이라고 본다
                        p = FreeCAD.Vector(0, 0, 0)
                        if axis == "x":
                            p = FreeCAD.Vector(val, 0, 0) if abs(view.XDirection.x) > 0.5 else FreeCAD.Vector(0, val, 0)
                        else:
                            p = FreeCAD.Vector(0, 0, val) if abs(view.Direction.z) < 0.5 else FreeCAD.Vector(0, val, 0)
                        u, vv = _project(view, p)
                        e = _find_edge(view, axis, (u if axis == "x" else vv) * sc)
                        if e is None:
                            raise _DrawError(f"뷰 {view.Name}에서 {axis}={val} 위치의 직선 모서리를 찾지 못했습니다.")
                        names.append(e)
                    dim.References2D = [(view, tuple(names))]
                    refs = "2D:" + "+".join(names)
                else:
                    pa, pb = ds.get("from"), ds.get("to")
                    if not pa or not pb:
                        raise _DrawError("Distance 치수에는 from=[x,y,z], to=[x,y,z]가 필요합니다.")
                    va, da = _nearest_vertex(shape, _vec(pa), vertex_tolerance)
                    vb, db = _nearest_vertex(shape, _vec(pb), vertex_tolerance)
                    if not va or not vb:
                        raise _DrawError(f"정점을 찾지 못했습니다(허용 {vertex_tolerance}): from→{da}, to→{db}. 정점이 없는 곳이면 edges 방식을 쓰세요.")
                    dim.References3D = [(src_obj, va), (src_obj, vb)]
                    dim.References2D = [(view, "")]
                    refs = f"3D:{va}+{vb}"
                pg.addView(dim)
                off = ds.get("offset")
                if off and len(off) == 2:
                    dim.X, dim.Y = float(off[0]), float(off[1])
                else:
                    # 기본 오프셋: 뷰 밖으로 (DistanceX는 아래, DistanceY는 왼쪽)
                    vb_ = view.Source[0].Shape.BoundBox if view.Source else bb
                    if kind == "DistanceY":
                        dim.X, dim.Y = -(vb_.XLength * sc / 2 + 12 + 6 * (i % 3)), 0
                    elif kind == "DistanceX":
                        dim.X, dim.Y = 0, -(vb_.ZLength * sc / 2 + 12 + 6 * (i % 3))
                    else:
                        dim.X, dim.Y = 8 + 6 * (i % 3), 8 + 6 * (i % 3)
                dim.ScaleType = "Custom"
                dim.Scale = sc
                dims_out.append((dim, view, kind, label, refs))
            except _DrawError as e:
                warnings.append(f"치수 {i + 1} 건너뜀: {e}")
                if d.getObject("Dim_" + str(ds.get("label") or f"Dim{i + 1}")):
                    d.removeObject("Dim_" + str(ds.get("label") or f"Dim{i + 1}"))

        # --- 주석·표제란 ----------------------------------------------------------
        ann_out = []
        note_specs = notes or []
        if note_specs and all(isinstance(n, str) for n in note_specs):
            note_specs = [{"text": list(note_specs)}]
        for k, ns in enumerate(note_specs):
            ann = d.addObject("TechDraw::DrawViewAnnotation", ns.get("name") or f"Note{k + 1}")
            ann.Text = [str(t) for t in (ns.get("text") or [])]
            ann.TextSize = float(ns.get("size", 2.5))
            pg.addView(ann)
            ann.X, ann.Y = float(ns.get("x", notes_xy[0])), float(ns.get("y", notes_xy[1] + 14 * k))
            ann_out.append(ann.Name)
        et = dict(tpl.EditableTexts)
        if et:
            scale_txt = f"1:{int(round(1 / s))}" if s < 1 else (f"{int(round(s))}:1" if s > 1 else "1:1")
            defaults = {"scale": scale_txt, "CreationDate": time.strftime("%Y-%m-%d"), "AuthorName": "cadxray",
                        "FC-Title": util.label(objs[0]) if len(objs) == 1 else page, "SheetNumber": "1/1"}
            for k, v in defaults.items():
                if k in et:
                    et[k] = v
            for k, v in (title or {}).items():
                key = _TITLE_ALIASES.get(k, k)
                if key in et:
                    et[key] = str(v)
                else:
                    warnings.append(f"표제란에 '{k}' 칸이 없습니다. 있는 칸: {', '.join(sorted(et))}")
            tpl.EditableTexts = et
        d.recompute()
        _wait_for_views([v for v, _ in created.values()], wait_seconds, warnings)

        # --- 선 굵기·매끈한 모서리 (GUI 표시용. 기본 라인 그룹은 0.7 mm라 화면에서 뭉쳐 보인다) ------
        if FreeCAD.GuiUp and line_width:
            for v in pg.Views:
                vo = v.ViewObject
                for prop, val in (("LineWidth", line_width), ("HiddenWidth", line_width / 2), ("IsoWidth", line_width / 2), ("ExtraWidth", line_width * 1.5)):
                    if hasattr(vo, prop):
                        setattr(vo, prop, float(val))
        if not smooth_edges:
            for v, _ in created.values():
                if hasattr(v, "SmoothVisible"):
                    v.SmoothVisible = False
                    v.SeamVisible = False
            d.recompute()

        # --- 내보내기 --------------------------------------------------------------
        files = {}
        want = str(export or "none").lower()
        if want != "none":
            if not FreeCAD.GuiUp:
                warnings.append("GUI가 없어(FreeCADCmd) PDF/SVG 내보내기를 건너뜁니다.")
            else:
                import FreeCADGui
                import TechDrawGui

                try:
                    FreeCADGui.getDocument(d.Name).getObject(pg.Name).doubleClicked()   # 페이지 창 열기
                    FreeCADGui.updateGui()
                except Exception as e:  # noqa: BLE001
                    warnings.append(f"페이지 창을 열지 못했습니다: {e}")
                folder = out_dir or (os.path.dirname(d.FileName) if d.FileName else os.path.expanduser("~"))
                os.makedirs(folder, exist_ok=True)
                stem = os.path.join(folder, f"{d.Name}_{page}")
                for ext, fn in (("pdf", TechDrawGui.exportPageAsPdf), ("svg", TechDrawGui.exportPageAsSvg)):
                    if want in (ext, "both"):
                        try:
                            fn(pg, stem + "." + ext)
                            files[ext] = stem + "." + ext
                        except Exception as e:  # noqa: BLE001
                            warnings.append(f"{ext} 내보내기 실패: {e}")

        # --- 결과 -----------------------------------------------------------------
        views_out = []
        for name, (v, t) in created.items():
            try:
                n_edges = len(v.getVisibleEdges())
            except Exception:  # noqa: BLE001
                n_edges = None
            views_out.append({"name": name, "type": t, "scale": round(v.getScale(), 6), "x": round(float(v.X), 2),
                              "y": round(float(v.Y), 2), "edges": n_edges, "status": util.status_string(v)})
            if n_edges == 0:
                warnings.append(f"뷰 {name}에 모서리가 없습니다(소스가 비었거나 Link를 직접 넣은 경우).")
        dims_json = []
        for dim, view, kind, label, refs in dims_out:
            try:
                val = round(float(dim.getRawValue()), 4)
            except Exception:  # noqa: BLE001
                val = None
            dims_json.append({"name": dim.Name, "view": view.Name, "type": kind, "value": val, "references": refs,
                              "status": util.status_string(dim)})
        data = {
            "document": d.Name, "page": pg.Name, "template": os.path.basename(tpl_path), "size": [W, H], "scale": s,
            "source": src_obj.Name, "source_objects": [o.Name for o in objs],
            "views": views_out, "dimensions": dims_json, "annotations": ann_out,
            "files": files,
        }
        return util.envelope(data, warnings=warnings, t0=t0)
    except _DrawError as e:
        return util.error(str(e))
    except Exception as e:  # noqa: BLE001
        return util.error(f"{type(e).__name__}: {e}", exc=e)


def inspect_drawing(page=None, doc=None, max_views=100):
    """페이지의 뷰·치수·주석·표제란 값. [확인됨: api-notes 14장]"""
    t0 = time.time()
    d, err = util.get_doc(doc)
    if err:
        return util.error(err)
    if not page:
        pages = [o for o in d.Objects if o.TypeId == "TechDraw::DrawPage"]
        if len(pages) == 1:
            pg = pages[0]
        elif not pages:
            return util.error(f"문서 '{d.Name}'에 TechDraw 페이지가 없습니다.")
        else:
            return util.error("페이지가 여러 개입니다: " + ", ".join(p.Name for p in pages) + ". page로 지정하세요.")
    else:
        pg, err = util.find_object(d, page)
        if err:
            return util.error(err)
        if pg.TypeId != "TechDraw::DrawPage":
            return util.error(f"'{page}'는 TechDraw 페이지가 아닙니다({pg.TypeId}).")
    warnings = []
    tpl = pg.Template
    views, dims, anns = [], [], []
    for v in pg.Views:
        tid = v.TypeId.split("::")[-1]
        if tid == "DrawViewDimension":
            try:
                val = round(float(v.getRawValue()), 4)
            except Exception:  # noqa: BLE001
                val = None
            r3 = [(o.Name, tuple(s)) for o, s in v.References3D] if v.References3D else []
            r2 = [(o.Name, tuple(s)) for o, s in v.References2D] if v.References2D else []
            dims.append({"name": v.Name, "label": util.label(v), "type": v.Type, "value": val, "measure": v.MeasureType,
                         "references": r3 or [r for r in r2 if any(r[1])], "view": r2[0][0] if r2 else None,
                         "scale": round(float(v.Scale), 6), "x": round(float(v.X), 2), "y": round(float(v.Y), 2),
                         "status": util.status_string(v)})
        elif tid == "DrawViewAnnotation":
            anns.append({"name": v.Name, "text": list(v.Text), "x": round(float(v.X), 2), "y": round(float(v.Y), 2)})
        else:
            entry = {"name": v.Name, "type": tid, "x": round(float(v.X), 2), "y": round(float(v.Y), 2), "status": util.status_string(v)}
            if hasattr(v, "Source"):
                entry["source"] = [o.Name for o in v.Source]
            if hasattr(v, "getScale"):
                entry["scale"] = round(v.getScale(), 6)
            if hasattr(v, "Direction"):
                entry["direction"] = util.round_vec(v.Direction)
            if hasattr(v, "getVisibleEdges"):
                try:
                    entry["edges"] = len(v.getVisibleEdges())
                except Exception:  # noqa: BLE001
                    entry["edges"] = None
            if tid == "DrawViewDetail":
                entry["base"] = v.BaseView.Name if v.BaseView else None
                entry["reference"] = v.Reference
                entry["radius"] = float(v.Radius)
            if hasattr(v, "Caption"):
                entry["caption"] = v.Caption
            views.append(entry)
    truncated = False
    if len(views) > max_views:
        views, truncated = views[:max_views], True
    data = {
        "document": d.Name, "page": pg.Name, "status": util.status_string(pg),
        "template": {"file": os.path.basename(tpl.Template) if tpl else None,
                     "size": [float(tpl.Width), float(tpl.Height)] if tpl else None,
                     "editable_texts": dict(tpl.EditableTexts) if tpl else {}},
        "views_total": len(pg.Views), "views": views, "dimensions": dims, "annotations": anns,
    }
    return util.envelope(data, warnings=warnings, truncated=truncated, t0=t0)


TOOLS = {"make_drawing": make_drawing, "inspect_drawing": inspect_drawing}
