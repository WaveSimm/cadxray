"""애드온 핸들러 테스트. FreeCAD 안에서 돈다 (서버를 켤 필요 없음).

    # Windows
    "C:\\Program Files\\FreeCAD 1.1\\bin\\freecadcmd.exe" tests\\in_freecad\\test_handlers.py
    # macOS
    /Applications/FreeCAD.app/Contents/MacOS/FreeCADCmd tests/in_freecad/test_handlers.py
    # 실행 중인 FreeCAD GUI의 Python 콘솔에서
    exec(open(r"E:\\claude\\freecadMCP\\tests\\in_freecad\\test_handlers.py", encoding="utf-8").read())

GUI가 없으면(FreeCADCmd) get_screenshot은 SKIP한다. 마지막에 측정표(응답 크기·시간)를
마크다운으로 출력한다 — README의 표는 여기서 나온 값이다.
"""

import base64
import json
import os
import sys
import time
import traceback

# FreeCADCmd는 스크립트가 끝나면 Python 버퍼를 비우지 않고 종료한다 → 줄마다 flush.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass


def _here():
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except NameError:
        pass
    for a in reversed(sys.argv):
        if a.endswith("test_handlers.py"):
            return os.path.dirname(os.path.abspath(a))
    return os.path.join(os.getcwd(), "tests", "in_freecad")


HERE = _here()
ROOT = os.path.dirname(os.path.dirname(HERE))
for p in (os.path.join(ROOT, "addon"), os.path.join(ROOT, "tests", "fixtures")):
    if p not in sys.path:
        sys.path.insert(0, p)

import FreeCAD  # noqa: E402

import make_test_models as fx  # noqa: E402
from FreeCADDiag import rpc_server  # noqa: E402
from FreeCADDiag.handlers import (  # noqa: E402
    REGISTRY,
    document_graph,
    documents,
    execute,
    recompute,
    reload_handlers,
    screenshot,
    shape_analysis,
    shape_features,
    sketch_diag,
    step_import,
    util,
)

# --- 작은 테스트 하네스 ---------------------------------------------------------

_results = []  # (status, name, detail)
_measure = []  # (tool, case, bytes, ms)


def check(name, cond, detail=""):
    _results.append(("PASS" if cond else "FAIL", name, detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  — {detail}" if detail and not cond else ""))
    return bool(cond)


def skip(name, why):
    _results.append(("SKIP", name, why))
    print(f"  [SKIP] {name}  — {why}")


def measure(tool, case, r):
    _measure.append((tool, case, util.json_size(r), r.get("elapsed_ms", 0)))
    return r


def section(title):
    print(f"\n== {title} ==")


def run(name, fn):
    """예외를 FAIL로 바꾼다. 테스트 하나가 죽어도 나머지는 돈다."""
    try:
        fn()
    except Exception as e:
        _results.append(("FAIL", name, f"{type(e).__name__}: {e}"))
        print(f"  [FAIL] {name}  — 예외\n{traceback.format_exc()}")


# --- 테스트 ---------------------------------------------------------------------


def test_fixtures():
    section("테스트 모델 생성")
    t0 = time.time()
    summary = fx.build_all()
    print(f"  {len(summary)}개 문서, {round((time.time() - t0) * 1000)} ms")
    check("T1_clean invalid 없음", summary["T1_clean"]["invalid"] == [])
    check("T3_conflict Sketch invalid", summary["T3_conflict"]["invalid"] == ["Sketch"])
    check("T4_open_wire Pad invalid", summary["T4_open_wire"]["invalid"] == ["Pad"])
    check("T5_large 300개 이상", summary["T5_large"]["objects"] >= 300, str(summary["T5_large"]))


def test_ping_and_list():
    section("ping / list_documents")
    r = measure("ping", "-", documents.ping())
    check("ping ok", r["ok"])
    check("ping freecad_version", isinstance(r["data"]["freecad_version"], str), str(r["data"]))
    check("ping gui bool", isinstance(r["data"]["gui"], bool))
    r = measure("list_documents", "5개 문서", documents.list_documents())
    names = {d["name"] for d in r["data"]}
    check("list_documents에 T1~T5", {"T1_clean", "T5_large"} <= names, str(names))


def test_document_graph():
    section("get_document_graph")
    r = measure("get_document_graph", "T1 (13객체)", document_graph.get_document_graph(doc="T1_clean"))
    d = r["data"]
    check("T1 ok", r["ok"])
    check("T1 summary.objects == 13", d["summary"]["objects"] == 13, str(d["summary"]))
    check("T1 invalid 없음", d["invalid_objects"] == [])
    check("T1 bodies[0].tip == Pocket", d["bodies"] and d["bodies"][0]["tip"] == "Pocket", str(d["bodies"]))
    sk = next((o for o in d["objects"] if o["name"] == "Sketch"), None)
    check("T1 Sketch에 sketch 요약", sk is not None and "sketch" in sk, str(sk))

    r = measure("get_document_graph", "T5 max_objects=50", document_graph.get_document_graph(doc="T5_large", max_objects=50))
    d = r["data"]
    size = util.json_size(r)
    check("T5(50) truncated", r["truncated"] is True)
    check("T5(50) 20 KB 이하", size <= 20 * 1024, f"{size} B")
    check("T5(50) summary는 전체 기준", d["summary"]["objects"] >= 300, str(d["summary"]["objects"]))
    check("T5(50) 5초 이내", r["elapsed_ms"] < 5000, f"{r['elapsed_ms']} ms")
    check("T5(50) objects 50개", len(d["objects"]) == 50)

    r = measure("get_document_graph", "T5 max_objects=200", document_graph.get_document_graph(doc="T5_large"))
    check("T5(200) 하드캡 이하", util.json_size(r) <= util.HARD_CAP_BYTES, f"{util.json_size(r)} B")

    r = document_graph.get_document_graph(doc="T3_conflict")
    check("T3 invalid_objects == [Sketch]", r["data"]["invalid_objects"] == ["Sketch"], str(r["data"]["invalid_objects"]))
    r = document_graph.get_document_graph(doc="T1_clean", type_filter="Sketcher::SketchObject")
    check("type_filter 스케치만", all(o["type"] == "Sketcher::SketchObject" for o in r["data"]["objects"]) and len(r["data"]["objects"]) == 2)
    r = document_graph.get_document_graph(doc="없는문서")
    check("없는 문서 → ok False", r["ok"] is False and "없는문서" in r["error"])


def test_inspect_object():
    section("inspect_object")
    r = measure("inspect_object", "Pad", document_graph.inspect_object(doc="T1_clean", name="Pad"))
    d = r["data"]
    check("Pad ok", r["ok"])
    length = d["properties"].get("Length", {}).get("value")
    check("Length가 Quantity 구조", isinstance(length, dict) and length.get("value") == 10.0, str(length))
    check("Shape 값 생략", "생략" in str(d["properties"]["Shape"]["value"]))
    check("shape 요약 있음", d.get("shape", {}).get("shape_type") == "Solid", str(d.get("shape")))
    check("out에 Sketch", "Sketch" in d["out"])
    r = document_graph.inspect_object(doc="T1_clean", name="없는객체")
    check("없는 객체 → ok False", r["ok"] is False)


def test_analyze_shape():
    section("analyze_shape")
    r = measure("analyze_shape", "Pocket", shape_analysis.analyze_shape(doc="T1_clean", name="Pocket"))
    d = r["data"]
    check("Pocket ok", r["ok"])
    check("is_valid", d["is_valid"] is True)
    check("check_message 없음", d["check_message"] is None, str(d["check_message"]))
    check("원통면 1개(구멍)", d["faces_by_surface"].get("Cylinder") == 1, str(d["faces_by_surface"]))
    check("부피 = 20*12*10 - π·9·10", abs(d["volume"] - (2400 - 3.141592653589793 * 9 * 10)) < 0.5, str(d["volume"]))
    check("feature_own_shape 있음", "feature_own_shape" in d)
    r = shape_analysis.analyze_shape(doc="T1_clean", name="Pocket", max_faces=2, max_edges=2)
    check("max_faces=2 → truncated", r["truncated"] is True and len(r["data"]["face_details"]) == 2)
    r = shape_analysis.analyze_shape(doc="T1_clean", name="Sketch")
    check("스케치(Shape 있음)도 분석됨", r["ok"] and r["data"]["shape_type"] in ("Wire", "Compound", "Edge"), str(r.get("data", {}).get("shape_type")))


def test_sketch_diagnostics():
    section("get_sketch_diagnostics")
    r = measure("get_sketch_diagnostics", "T1 완전구속", sketch_diag.get_sketch_diagnostics(doc="T1_clean", sketch="Sketch"))
    check("T1 solve 0 / dof 0 / fc True", r["data"]["solve_status"] == 0 and r["data"]["dof"] == 0 and r["data"]["fully_constrained"] is True, str({k: r["data"][k] for k in ("solve_status", "dof", "fully_constrained")}))

    r = sketch_diag.get_sketch_diagnostics(doc="T2_underconstrained", sketch="Sketch")
    check("T2 dof > 0, fc False", r["data"]["solve_status"] == 0 and r["data"]["dof"] > 0 and r["data"]["fully_constrained"] is False, str({k: r["data"][k] for k in ("solve_status", "dof", "fully_constrained")}))

    r = measure("get_sketch_diagnostics", "T3 충돌", sketch_diag.get_sketch_diagnostics(doc="T3_conflict", sketch="Sketch"))
    d = r["data"]
    ids = [c["id"] for c in d["conflicting"]]
    check("T3 solve 실패", d["solve_status"] != 0, str(d["solve_status"]))
    check("T3 conflicting == [12, 13]", ids == [12, 13], str(ids))
    check("T3 fully_constrained null", d["fully_constrained"] is None)
    check("T3 index = id-1", all(c["index"] == c["id"] - 1 for c in d["conflicting"]))
    r2 = sketch_diag.get_sketch_diagnostics(doc="T3_conflict", sketch="Sketch", max_items=2)
    got = [c["i"] for c in r2["data"]["constraints"]]
    check("T3 max_items=2 에도 문제 제약 포함", 11 in got and 12 in got, str(got))

    r = sketch_diag.get_sketch_diagnostics(doc="T4_open_wire", sketch="Sketch")
    check("T4 open_vertices 2개", len(r["data"]["open_vertices"]) == 2, str(r["data"]["open_vertices"]))

    r = sketch_diag.get_sketch_diagnostics(doc="T1_clean", sketch="Pad")
    check("스케치 아님 → ok False", r["ok"] is False and "스케치가 아닙니다" in r["error"])


def test_tracked_recompute():
    section("tracked_recompute")
    doc = FreeCAD.getDocument("T1_clean")
    pad = doc.getObject("Pad")
    pad.Length = 0
    r = measure("tracked_recompute", "깨뜨린 뒤", recompute.tracked_recompute(doc="T1_clean"))
    names = [e["name"] for e in r["data"]["new_errors"]]
    check("깨뜨림 → new_errors에 Pad", "Pad" in names, str(r["data"]["new_errors"]))
    check("new_errors status에 원인", any("zero" in (e["status"] or "") for e in r["data"]["new_errors"]), str(r["data"]["new_errors"]))
    pad.Length = 10
    r = measure("tracked_recompute", "고친 뒤", recompute.tracked_recompute(doc="T1_clean"))
    names = [e["name"] for e in r["data"]["resolved"]]
    check("고침 → resolved에 Pad", "Pad" in names, str(r["data"]["resolved"]))
    check("고침 → new_errors 없음", r["data"]["new_errors"] == [])
    r = recompute.tracked_recompute(doc="T1_clean", objects=["Pad"])
    check("objects=[Pad] requested", r["data"]["requested"] == ["Pad"])
    r = recompute.tracked_recompute(doc="T1_clean", objects=["없는객체"])
    check("없는 객체 → ok False", r["ok"] is False)


def test_execute_code():
    section("execute_code")
    r = measure("execute_code", "_result = 1+1", execute.execute_code("print('hi')\n_result = 1 + 1", doc="T1_clean"))
    check("result == 2", r["ok"] and r["data"]["result"] == 2, str(r))
    check("stdout 캡처", r["data"]["stdout"].strip() == "hi")
    r = execute.execute_code("_result = doc.Name", doc="T1_clean")
    check("doc 네임스페이스", r["data"]["result"] == "T1_clean")
    r = execute.execute_code("1/0", doc="T1_clean")
    check("예외 → ok False + traceback", r["ok"] is False and "ZeroDivisionError" in r["error"] and "traceback" in r)
    r = execute.execute_code("_result = doc.getObject('Pad').Length", doc="T1_clean")
    check("Quantity 직렬화", isinstance(r["data"]["result"], dict) and r["data"]["result"].get("value") == 10.0, str(r["data"]["result"]))


def test_screenshot():
    section("get_screenshot")
    if not FreeCAD.GuiUp:
        r = screenshot.get_screenshot(doc="T1_clean", view="iso")
        check("GUI 없음 → ok False + 안내", r["ok"] is False and "GUI" in r["error"])
        skip("get_screenshot 이미지", "GUI 없음 (FreeCADCmd)")
        return
    r = measure("get_screenshot", "iso 800x600", screenshot.get_screenshot(doc="T1_clean", view="iso", width=800, height=600))
    check("iso ok", r["ok"], str(r.get("error")))
    if r["ok"]:
        png = base64.b64decode(r["data"]["png_base64"])
        check("PNG 시그니처", png[:8] == b"\x89PNG\r\n\x1a\n")
        check("크기 필드", r["data"]["width"] == 800 and r["data"]["height"] == 600)
    r = screenshot.get_screenshot(doc="T1_clean", view="옆에서")
    check("잘못된 view → ok False", r["ok"] is False)


def _by_label(doc_name, label):
    d = FreeCAD.getDocument(doc_name)
    for o in d.Objects:
        if o.Label == label:
            return o.Name
    return None


def test_step_tools():
    section("M6: import_step / find_holes / check_interference / get_mass_properties")
    path = fx.STEP_PATHS.get("T6_step")
    check("T6 STEP 파일 존재", path and os.path.isfile(path), str(path))
    plate, block = _by_label("T6_step", "Plate"), _by_label("T6_step", "Block")
    a, b = _by_label("T6_step", "BlockA"), _by_label("T6_step", "BlockB")
    check("가져온 부품 4개 라벨 유지", all((plate, block, a, b)), str((plate, block, a, b)))

    r = measure("find_holes", "판 Ø6.6×4 + 필렛 + 자리파기", shape_features.find_holes(doc="T6_step", name=plate))
    d = r["data"]
    check("find_holes ok", r["ok"], str(r.get("error")))
    real = [h for h in d["holes"] if h["kind"] == "hole"]
    big = [h for h in real if abs(h["diameter"] - 6.6) < 0.01]
    check("Ø6.6 구멍 4개 (전체 9: +자리파기 2 +접시 1 +카운터보어 1 +탭드릴 1)", len(big) == 4 and d["holes_total"] == 9, f"holes_total={d['holes_total']}, Ø6.6={len(big)}")
    check("Ø6.6 → M6 볼트 관통(보통급) 추정", all(h.get("thread_hint", {}).get("size") == "M6" and h["thread_hint"]["type"] == "clearance_medium" for h in big), str([h.get("thread_hint") for h in big]))
    tap = next((h for h in real if abs(h["diameter"] - 3.3) < 0.01), None)
    check("Ø3.3 막힌 구멍 → M4 탭 드릴 (high)", tap is not None and tap["thread_hint"]["size"] == "M4" and tap["thread_hint"]["type"] == "tap_drill" and tap["thread_hint"]["confidence"] == "high" and tap["through"] is False, str(tap))
    recess = [h for h in real if abs(h["diameter"] - 4.0) < 0.01]
    check("Ø4 자리파기(깊이 1)에는 나사 추정 안 붙음", recess and all("thread_hint" not in h for h in recess), str([h.get("thread_hint") for h in recess]))
    check("막힌 구멍엔 관통 추정 안 붙음", all(not h.get("thread_hint", {}).get("type", "").startswith("clearance") for h in real if h["through"] is False), str([(h["diameter"], h.get("thread_hint")) for h in real if h["through"] is False]))
    m3 = [h for h in real if abs(h["diameter"] - 3.4) < 0.01]
    cs = next((h for h in m3 if "countersink" in h), None)
    check("Ø3.4 + 90° 카운터싱크 입구 Ø6.5 깊이 1.55", cs is not None and abs(cs["countersink"]["top_diameter"] - 6.5) < 0.02
          and abs(cs["countersink"]["angle_deg"] - 90) < 0.5 and abs(cs["countersink"]["depth"] - 1.55) < 0.02
          and cs["countersink"]["type"] == "countersink" and cs["through"] is True, str(cs))
    cb = next((h for h in m3 if "counterbore" in h), None)
    check("Ø3.4 + Ø5.6 카운터보어 깊이 3 → 구멍 하나로 합침", cb is not None and abs(cb["counterbore"]["diameter"] - 5.6) < 0.02
          and abs(cb["counterbore"]["depth"] - 3) < 0.02 and cb["through"] is True
          and not any(abs(h["diameter"] - 5.6) < 0.01 for h in real), str(cb))
    check("카운터보어 구멍 → 'M3 … 볼트 머리 자리' 문구", cb is not None and cb["thread_hint"]["size"] == "M3" and "볼트 머리" in cb["thread_hint"]["text"], str(cb and cb.get("thread_hint")))
    check("카운터싱크 구멍 → '접시머리' 문구", cs is not None and "접시머리" in cs["thread_hint"]["text"], str(cs and cs.get("thread_hint")))
    p34 = next((p for p in d["patterns"] if abs(p["diameter"] - 3.4) < 0.01), None)
    check("Ø3.4 패턴에 countersink 1·counterbore 1 표시", p34 and p34.get("countersink") == 1 and p34.get("counterbore") == 1, str(p34))
    got = sorted(tuple(h["center"][:2]) for h in big)
    check("중심 위치 ±0.01", got == [(10.0, 10.0), (10.0, 50.0), (90.0, 10.0), (90.0, 50.0)], str(got))
    check("Ø6.6 전부 관통", all(h["through"] for h in big))
    p66 = next((p for p in d["patterns"] if abs(p["diameter"] - 6.6) < 0.01), None)
    check("패턴 pitch [40, 80]", p66 and p66["pitch"] == [40.0, 80.0], str(p66))
    fil = [h for h in d["holes"] if h["kind"] == "fillet"]
    check("각창 모서리 R2 → fillet 4개, 구멍 아님", len(fil) == 4 and d["partial_total"] == 4 and all(abs(h["arc_deg"] - 90) < 1 for h in fil), str([(h['kind'], h['arc_deg']) for h in d['holes']]))
    small = [h for h in real if abs(h["diameter"] - 4.0) < 0.01]
    check("같은 축 양쪽 자리파기 → 구멍 2개, 깊이 1, 관통 아님", len(small) == 2 and all(abs(h["depth"] - 1.0) < 0.01 and h["through"] is False for h in small), str(small))
    check("10초 이내", r["elapsed_ms"] < 10000, f"{r['elapsed_ms']} ms")
    r = shape_features.find_holes(doc="T6_step", name=block)
    check("블록 관통 구멍 Ø6 1개", r["data"]["holes_total"] == 1 and abs(r["data"]["holes"][0]["diameter"] - 6.0) < 0.01)
    r = shape_features.find_holes(doc="T6_step", name=a)
    check("구멍 없는 블록 → 0개 + 경고", r["ok"] and r["data"]["holes_total"] == 0 and r["warnings"])

    r = measure("check_interference", "블록 2개", shape_features.check_interference(doc="T6_step", names=[a, b]))
    p = r["data"]["pairs"][0]
    check("겹친 블록 → interference", p["status"] == "interference", str(p))
    check("간섭 부피 4000 ±0.01", abs(p["interference_volume"] - 4000.0) < 0.01, str(p["interference_volume"]))
    r = measure("check_interference", "부품 4개(6쌍)", shape_features.check_interference(doc="T6_step", names=[block, plate, a, b]))
    check("6쌍, 간섭 2", r["data"]["pairs_total"] == 6 and r["data"]["summary"]["interference"] == 2, str(r["data"]["summary"]))
    check("기본은 문제 쌍만 담는다 (ok 4개는 summary에만)", all(p["status"] != "ok" for p in r["data"]["pairs"]) and r["data"]["summary"]["ok"] == 4, str(r["data"]["summary"]))
    r_all = shape_features.check_interference(doc="T6_step", names=[block, plate, a, b], include_ok=True)
    check("include_ok=True → 6쌍 전부", len(r_all["data"]["pairs"]) == 6)
    check("멀리 떨어진 쌍은 bbox로 건너뜀", r_all["data"]["pairs_skipped_by_bbox"] >= 1 and any(p.get("distance_is_lower_bound") for p in r_all["data"]["pairs"]), str(r_all["data"]["pairs_skipped_by_bbox"]))
    r = shape_features.check_interference(doc="T6_step", names=[a])
    check("1개만 주면 ok False", r["ok"] is False)
    r = shape_features.check_interference(doc="T6_step", names=[plate, a], clearance=30.0)
    check("clearance 위반 판정", r["data"]["pairs"][0]["status"] == "clearance_violation", str(r["data"]["pairs"][0]))

    r = measure("get_mass_properties", "판, 밀도 2.7", shape_features.get_mass_properties(doc="T6_step", name=plate, density=2.7))
    d = r["data"]
    pi = 3.141592653589793
    frustum = pi * 1.55 / 3 * (1.7 ** 2 + 1.7 * 3.25 + 3.25 ** 2)   # 카운터싱크 원뿔대
    expected_v = (100 * 60 * 8 - 4 * pi * 3.3 ** 2 * 8          # 판 − Ø6.6×4
                  - 20 * 20 * 8 + 4 * (4 - pi) * 8                 # − 각창 + R2 필렛이 되돌리는 살
                  - 2 * pi * 2.0 ** 2 * 1.0                        # − Ø4 자리파기 2개
                  - 2 * pi * 1.7 ** 2 * 8                          # − Ø3.4 관통 2개
                  - (frustum - pi * 1.7 ** 2 * 1.55)               # − 카운터싱크가 더 깎는 살
                  - pi * (2.8 ** 2 - 1.7 ** 2) * 3                 # − 카운터보어가 더 깎는 살
                  - pi * 1.65 ** 2 * 6)                             # − M4 탭 드릴 막힌 구멍
    check("부피 = 판 − 구멍 4개", abs(d["volume_mm3"] - expected_v) < 0.5, f"{d['volume_mm3']} vs {expected_v:.2f}")
    check("질량 g = 부피/1000 × 2.7", abs(d["mass_g"] - expected_v / 1000 * 2.7) < 0.01, str(d["mass_g"]))
    cm = d["center_of_mass"]  # 자리파기·접시·카운터보어가 한쪽에 있어 중심이 조금 밀린다
    check("무게중심 ≈ [50, 30, 4]", abs(cm[0] - 50) < 0.05 and abs(cm[1] - 30) < 0.1 and abs(cm[2] - 4) < 0.01, str(cm))
    check("principal 있음", "principal" in d and len(d["principal"]["moments"]) == 3)

    r = measure("import_step", "insert(13객체)", step_import.import_step(path, doc="T6_step"))
    check("insert ok", r["ok"], str(r.get("error")))
    check("insert created 13 / solids 4", r["data"]["created_total"] == 13 and r["data"]["solids_total"] == 4, str({k: r["data"][k] for k in ("created_total", "solids_total")}))
    check("insert invalid 없음", r["data"]["invalid"] == [])
    r = measure("import_step", "새 문서", step_import.import_step(path))
    check("새 문서 ok", r["ok"] and r["data"]["document"] and r["data"]["solids_total"] == 4, str(r.get("data", {}).get("document")))
    if r["ok"]:
        FreeCAD.closeDocument(r["data"]["document"])
    r = step_import.import_step(r"C:\없는파일.step")
    check("없는 파일 → ok False", r["ok"] is False and "없습니다" in r["error"])
    r = step_import.import_step(path.replace(".step", ".stl"))
    check("STL → 메시 안내", r["ok"] is False and "메시" in r["error"])


def test_registry_and_cap():
    section("레지스트리 / 하드캡")
    expected = {
        "ping", "list_documents", "get_document_graph", "inspect_object", "analyze_shape",
        "get_sketch_diagnostics", "tracked_recompute", "get_screenshot", "execute_code",
        "reload_handlers", "import_step", "find_holes", "check_interference", "get_mass_properties",
    }
    check("툴 14개 등록", expected <= set(REGISTRY), str(sorted(set(REGISTRY) ^ expected)))
    raw = r"20250624_\X2\c6d4d30c\X0\ \X2\be0cb77ccf13\X0\(\X2\c218c815bcf8\X0\)"
    check("STEP 한글 라벨 디코딩", util.decode_step_text(raw) == "20250624_월파 브라켓(수정본)", util.decode_step_text(raw))
    check("디코딩: 이스케이프 없으면 원문", util.decode_step_text("Plate") == "Plate")
    check("디코딩: \\S\\ Latin-1", util.decode_step_text(r"caf\S\i") == "café")
    r = reload_handlers()
    check("reload_handlers ok", r["ok"] and not r["data"]["failed"], str(r["data"]["failed"]))
    check("reload 후에도 14개", expected <= set(REGISTRY))

    big = {"ok": True, "data": {"x": "a" * (util.HARD_CAP_BYTES + 10)}}
    out = json.loads(rpc_server._dump(big))
    check("하드캡 초과 → 에러 봉투", out["ok"] is False and "하드캡" in out["error"])
    out = json.loads(rpc_server._dump(big, capped=False))
    check("capped=False → 통과", out["ok"] is True)
    check("get_screenshot은 no_size_cap", getattr(screenshot.get_screenshot, "no_size_cap", False) is True)

    out = json.loads(rpc_server.call("ping", "{}"))
    check("rpc_server.call 왕복", out["ok"] is True and "freecad_version" in out["data"])
    out = json.loads(rpc_server.call("inspect_object", json.dumps({"doc": "T1_clean", "이상한인자": 1})))
    check("잘못된 인자 → 친절한 에러", out["ok"] is False and "인자 오류" in out["error"])
    out = json.loads(rpc_server.call("없는툴", "{}"))
    check("없는 툴 → 목록 안내", out["ok"] is False and "ping" in out["error"])


# --- 실행 -----------------------------------------------------------------------


def main():
    print(f"FreeCAD {util.version_string()}  GUI={FreeCAD.GuiUp}  root={ROOT}")
    t0 = time.time()
    for name, fn in (
        ("fixtures", test_fixtures),
        ("ping_and_list", test_ping_and_list),
        ("document_graph", test_document_graph),
        ("inspect_object", test_inspect_object),
        ("analyze_shape", test_analyze_shape),
        ("sketch_diagnostics", test_sketch_diagnostics),
        ("tracked_recompute", test_tracked_recompute),
        ("execute_code", test_execute_code),
        ("screenshot", test_screenshot),
        ("step_tools", test_step_tools),
        ("registry_and_cap", test_registry_and_cap),
    ):
        run(name, fn)
    fx.close_all()

    n = {"PASS": 0, "FAIL": 0, "SKIP": 0}
    for status, _, _ in _results:
        n[status] += 1
    print(f"\n결과: PASS {n['PASS']}  FAIL {n['FAIL']}  SKIP {n['SKIP']}  ({round(time.time() - t0, 1)}초)")
    if n["FAIL"]:
        print("실패:")
        for status, name, detail in _results:
            if status == "FAIL":
                print(f"  - {name}: {detail}")

    print("\n측정표 (README용):")
    print("| 툴 | 경우 | 응답 크기 | 시간 |")
    print("|---|---|---|---|")
    for tool, case, size, ms in _measure:
        print(f"| `{tool}` | {case} | {size:,} B | {ms} ms |")
    return 1 if n["FAIL"] else 0


_code = main()
sys.stdout.flush()
if not FreeCAD.GuiUp:
    sys.exit(_code)
