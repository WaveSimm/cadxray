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
import math
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
import freecad  # noqa: E402

_ns = os.path.join(ROOT, "freecad")
if _ns not in list(freecad.__path__):
    freecad.__path__.append(_ns)  # 저장소 체크아웃을 Mod 없이 네임스페이스에 붙인다
from freecad.cadxray import rpc_server  # noqa: E402
from freecad.cadxray.handlers import (  # noqa: E402
    documents,
    drawing,
    mesh as mesh_mod,
    sketch_fix,
    REGISTRY,
    document_graph,
    documents,
    execute,
    rebuild,
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
    container = next((o.Name for o in FreeCAD.getDocument("T6_step").Objects if o.TypeId == "App::Part"), None)
    r = shape_features.check_interference(doc="T6_step", names=[container])
    check("App::Part 하나 주면 안의 부품 4개로 풀림 (6쌍)", r["ok"] and r["data"]["pairs_total"] == 6, str(r.get("data", {}).get("pairs_total", r.get("error"))))
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


def test_drawing_tools():
    section("M8: make_drawing / inspect_drawing")
    dims = [
        {"view": "front", "type": "DistanceX", "from": [0, 0, 0], "to": [20, 0, 0], "label": "W"},
        {"view": "front", "type": "DistanceY", "from": [0, 0, 0], "to": [0, 0, 10], "label": "H"},
        {"view": "top", "type": "DistanceY", "from": [0, 0, 10], "to": [0, 12, 10], "label": "D"},
        {"view": "top", "type": "Diameter", "center": [10, 6, 10], "radius": 3.0, "label": "Hole"},
        {"view": "front", "type": "DistanceX", "edges": {"axis": "x", "at": [0, 20]}, "label": "W2"},
        {"view": "front", "type": "DistanceX", "from": [99, 99, 99], "to": [0, 0, 0], "label": "Bad"},
    ]
    r = measure("make_drawing", "T1 3면도+치수", drawing.make_drawing(source="Body", doc="T1_clean", page="PageT1", views=["front", "right", "top", "iso"],
                                                                dimensions=dims, notes=["TEST NOTE"], title={"title": "T1 TEST"}, export="none"))
    check("make_drawing ok", r["ok"], str(r.get("error")))
    d = r["data"]
    check("뷰 4개, 모서리 있음", len(d["views"]) == 4 and all(v["edges"] for v in d["views"]), str([(v["name"], v["edges"]) for v in d["views"]]))
    check("자동 축척 = 2:1 (20×12×10 부품, A3)", abs(d["scale"] - 2.0) < 1e-9, str(d["scale"]))
    vals = {x["type"] + ":" + x["references"][:2]: x["value"] for x in d["dimensions"]}
    byname = {x["name"]: x["value"] for x in d["dimensions"]}
    check("치수 5개 생성, 잘못된 1개는 경고로", len(d["dimensions"]) == 5 and any("Bad" in w or "치수 6" in w for w in r["warnings"]), str((len(d["dimensions"]), r["warnings"])))
    check("DistanceX 20 / DistanceY 10 / 깊이 12", abs(byname["Dim_W"] - 20) < 0.01 and abs(byname["Dim_H"] - 10) < 0.01 and abs(byname["Dim_D"] - 12) < 0.01, str(byname))
    check("Diameter 6 (원 모서리 참조)", abs(byname["Dim_Hole"] - 6) < 0.01, str(byname.get("Dim_Hole")))
    check("실루엣 모서리 참조 DistanceX 20", abs(byname["Dim_W2"] - 20) < 0.01, str(byname.get("Dim_W2")))
    check("표제란 제목 반영", True)
    r2 = measure("inspect_drawing", "T1 페이지", drawing.inspect_drawing(page="PageT1", doc="T1_clean"))
    check("inspect_drawing ok", r2["ok"], str(r2.get("error")))
    d2 = r2["data"]
    check("뷰 4·치수 5·주석 1", len(d2["views"]) == 4 and len(d2["dimensions"]) == 5 and len(d2["annotations"]) == 1, str((len(d2["views"]), len(d2["dimensions"]), len(d2["annotations"]))))
    check("표제란 FC-Title = T1 TEST", d2["template"]["editable_texts"].get("FC-Title") == "T1 TEST", str(d2["template"]["editable_texts"].get("FC-Title")))
    check("치수 값 일치", all(abs(x["value"] - byname[x["name"]]) < 1e-6 for x in d2["dimensions"]))
    # 같은 이름으로 다시 만들면 이전 페이지를 지우고 새로 만든다
    r3 = drawing.make_drawing(source="Body", doc="T1_clean", page="PageT1", views=["front"], export="none")
    check("재생성: 페이지 1개, 뷰 1개", r3["ok"] and len([o for o in FreeCAD.getDocument("T1_clean").Objects if o.TypeId == "TechDraw::DrawPage"]) == 1 and len(r3["data"]["views"]) == 1)
    r4 = drawing.make_drawing(source="NoSuch", doc="T1_clean", export="none")
    check("없는 소스 → 오류 봉투", not r4["ok"] and "NoSuch" in r4["error"])
    r5 = drawing.make_drawing(source="Body", doc="T1_clean", page="PageBad", template="nope.svg", export="none")
    check("없는 템플릿 → 후보 안내", not r5["ok"] and "ISO/" in r5["error"])


def test_mesh_tools():
    section("M9: import_mesh / analyze_mesh / section_profile(메시) / build_features / compare_shapes(메시) / helix / save·open")
    doc = FreeCAD.getDocument("T9_mesh")
    mesh_name = [o for o in doc.Objects if o.TypeId == "Mesh::Feature"][0].Name
    r = measure("import_mesh", "판 STL", mesh_mod.import_mesh(path=fx.T9_STL_PATH, doc="T9_mesh", label="PlateMesh2"))
    check("import_mesh ok, 솔리드", r["ok"] and r["data"]["is_solid"] and r["data"]["facets"] > 100, str(r.get("error") or r["data"]))
    check("import_mesh 크기 60×40×10", r["ok"] and [round(v) for v in r["data"]["size"]] == [60, 40, 10], str(r.get("data", {}).get("size")))
    r = mesh_mod.import_mesh(path="C:/nope.stl")
    check("없는 파일 → 오류", not r["ok"])
    r = mesh_mod.import_mesh(path=__file__)
    check("메시 파일 아님 → 오류", not r["ok"] and "STL" in r["error"])

    r = measure("analyze_mesh", "판 메시", mesh_mod.analyze_mesh(name=mesh_name, doc="T9_mesh"))
    check("analyze_mesh ok", r["ok"], str(r.get("error")))
    d = r["data"]
    pos = sorted(lv["position"] for lv in d["levels"])
    check("주축 Z, levels ⊇ {0, 6, 10} ±0.02", d["main_axis_letter"] == "Z" and all(any(abs(p - t) < 0.02 for p in pos) for t in (0, 6, 10)), str(pos))
    check("verdict prismatic", d["verdict"] == "prismatic", d["verdict"])
    check("levels에 faces 목록 없음(개수만)", all(isinstance(lv.get("facets"), int) and "faces" not in lv for lv in d["levels"]))

    r = measure("section_profile", "메시 z=3 (구멍 메움)", rebuild.section_profile(doc="T9_mesh", name=mesh_name, position=3.0))
    check("메시 단면 ok, source=mesh", r["ok"] and r["data"]["source"] == "mesh", str(r.get("error")))
    w = r["data"]["wires"]
    check("z=3: 닫힌 윤곽 1개, 선분 4개, 구멍 2개 메움", len(w) == 1 and w[0]["elements_total"] == 4 and all(e["type"] == "line" for e in w[0]["elements"]) and r["data"]["filled_holes"] == 2,
          str([(x["elements_total"], [e["type"] for e in x["elements"]]) for x in w]) + f" filled={r['data'].get('filled_holes')}")
    r = rebuild.section_profile(doc="T9_mesh", name=mesh_name, position=8.0, fill_holes=False)
    w = r["data"]["wires"]
    circles = [e for x in w for e in x["elements"] if e["type"] == "circle"]
    check("z=8: 선분 4 + 카운터보어 원 r5 ±0.02", len(w) == 2 and w[0]["elements_total"] == 4 and len(circles) == 1 and abs(circles[0]["radius"] - 5.0) < 0.02,
          str([(x["elements_total"], [e["type"] for e in x["elements"]]) for x in w]) + str([c.get("radius") for c in circles]))
    r = rebuild.section_profile(doc="T9_mesh", name=mesh_name)
    check("position=None → 메시 levels", r["ok"] and {0.0, 6.0, 10.0} <= {round(lv["position"]) + 0.0 for lv in r["data"]["levels"]}, str(r["data"].get("levels")))

    feats = [
        {"op": "pad", "name": "PadLow", "plane": "XY", "position": 0.0, "length": 6.0, "profile": {"section": {"of": mesh_name, "position": 3.0}}},
        {"op": "pad", "name": "PadHigh", "plane": "XY", "position": 5.0, "length": 5.0, "profile": {"section": {"of": mesh_name, "position": 8.0}}},
        {"op": "pocket", "name": "PocketHoles", "plane": "XY", "position": 10.0, "through": True, "profile": {"circles": [{"center": [15, 20], "diameter": 6.6}, {"center": [45, 20], "diameter": 6.6}]}},
        {"op": "pocket", "name": "PocketCB", "plane": "XY", "position": 10.0, "length": 3.0, "profile": {"circles": [{"center": [15, 20], "diameter": 10.0}]}},
        {"op": "chamfer", "name": "ChamferBottom", "size": 0.5, "edges": {"curve": "Circle", "radius": 3.3, "center": [None, None, 0.0]}},
    ]
    r = measure("build_features", "메시 단면으로 재구성", rebuild.build_features(body="RebuiltM", doc="T9_mesh", features=feats))
    check("메시 단면으로 build_features 완주", r["ok"] and r["data"]["stopped_at"] is None, str(r.get("error") or r["data"].get("stopped_at")) + str([(c["name"], c["status"][:40]) for c in r.get("data", {}).get("created", [])]))
    check("스케치 전부 DoF 0", r["ok"] and all(c.get("dof") in (0, None) for c in r["data"]["created"]), str([c.get("dof") for c in r["data"]["created"]]))
    r = measure("compare_shapes", "메시 vs Body", rebuild.compare_shapes(a=mesh_name, b="RebuiltM", doc="T9_mesh"))
    check("메시 비교 ok, method mesh_deviation", r["ok"] and r["data"]["method"] == "mesh_deviation", str(r.get("error")))
    d = r["data"]
    check("최대 편차 < 0.05, 부피 0.5 % 안, verdict match", d["deviation"]["max"] < 0.05 and d["reverse_deviation"]["max"] < 0.05 and abs(d["volume_diff_pct"]) < 0.5 and d["verdict"] == "match",
          f"dev={d['deviation']['max']} rev={d['reverse_deviation']['max']} vol={d['volume_diff_pct']} {d['verdict']}")
    r = rebuild.compare_shapes(a=mesh_name, b=mesh_name, doc="T9_mesh")
    check("메시 대 메시 → 오류", not r["ok"])

    # helix: 원기둥에 피치 2 홈 → 메시로 바꿔 analyze_mesh가 나사를 잡는다
    feats = [
        {"op": "pad", "name": "PadCyl", "plane": "XY", "position": 0.0, "length": 20.0, "profile": {"circles": [{"center": [0, 0], "diameter": 20.0}]}},
        {"op": "helix", "name": "Thread", "profile": {"polygon": [[11, -2.0], [10, -2.0], [9.0, -1.4], [9.0, -0.6], [10, 0.0], [11, 0.0]]},
         "axis_center": [0, 0], "pitch": 2.0, "height": 24.0},
    ]
    r = measure("build_features", "helix 나사", rebuild.build_features(body="Screw", doc="T9_mesh", features=feats))
    check("helix op 완주·유효", r["ok"] and r["data"]["stopped_at"] is None and r["data"]["created"][-1]["status"] == "Valid", str(r.get("error") or r["data"].get("created")))
    v_cyl = math.pi * 100 * 20
    check("나사 홈만큼 부피 감소", r["ok"] and 0.85 * v_cyl < r["data"]["created"][-1]["volume_after"] < 0.99 * v_cyl, str(r["data"]["created"][-1].get("volume_after")))
    import MeshPart
    screw = doc.getObject("Screw")
    m = MeshPart.meshFromShape(Shape=screw.Shape, LinearDeflection=0.02, AngularDeflection=0.2, Relative=False)
    mf = doc.addObject("Mesh::Feature", "ScrewMesh")
    mf.Mesh = m
    doc.recompute()
    r = measure("analyze_mesh", "나사 메시", mesh_mod.analyze_mesh(name="ScrewMesh", doc="T9_mesh"))
    th = r["data"].get("thread") if r["ok"] else None
    check("나사 감지: 피치 2 ±0.05, 오른나사, 외경 r 10", bool(th) and abs(th["pitch"] - 2.0) < 0.05 and th["handedness"] == "right" and abs(th["major_r"] - 10.0) < 0.05, str(th))
    check("공통 중심 (0, 0)", r["ok"] and r["data"]["center"] is not None and abs(r["data"]["center"][0]) < 0.05 and abs(r["data"]["center"][1]) < 0.05, str(r["data"].get("center")))

    # save / open 왕복
    import os
    import tempfile
    path = os.path.join(tempfile.gettempdir(), "cadxray_T9_roundtrip.FCStd")
    if os.path.exists(path):
        os.remove(path)
    n_before = len(doc.Objects)
    r = measure("save_document", "T9 저장", documents.save_document(doc="T9_mesh", path=path))
    check("save_document ok, 파일 생김", r["ok"] and os.path.exists(path) and r["data"]["bytes"] > 0, str(r.get("error")))
    r = documents.save_document(doc="T7_rebuild", path=path)
    check("다른 기존 파일 덮어쓰기 거부(overwrite 없음)", not r["ok"] and "overwrite" in r["error"], str(r.get("error") or r.get("data")))
    r = documents.save_document(doc="T9_mesh", path=os.path.join(tempfile.gettempdir(), "cadxray_T9_plate.stl"))
    check("FCStd가 아닌 경로 → 오류", not r["ok"] and "FCStd" in r["error"])
    r = documents.open_document(path=path)
    check("열린 파일 open → already_open", r["ok"] and r["data"]["already_open"], str(r.get("error") or r["data"]))
    FreeCAD.closeDocument("T9_mesh")
    r = measure("open_document", "T9 다시 열기", documents.open_document(path=path))
    check("open_document ok, 객체 수 같음(이름은 파일명)", r["ok"] and r["data"]["objects"] == n_before and r["data"]["name"] == "cadxray_T9_roundtrip", str(r.get("error") or r["data"]))
    if r["ok"]:
        FreeCAD.closeDocument(r["data"]["name"])
    r = documents.open_document(path="C:/nope.FCStd")
    check("없는 파일 → 오류", not r["ok"])
    r = documents.save_document(doc="T2_underconstrained")
    check("파일 없는 문서 save → 경로 요구", not r["ok"] and "path" in r["error"])


def test_sketch_fix_tools():
    section("M10: suggest_sketch_fixes / apply_sketch_fixes")
    r = measure("suggest_sketch_fixes", "T10 후보", sketch_fix.suggest_sketch_fixes(sketch="Sketch", doc="T10_fixes"))
    check("suggest ok", r["ok"], str(r.get("error")))
    d = r["data"]
    kinds = [c["kind"] for c in d["suggestions"]]
    check("add_coincident 1 (0.028 벌어진 끝점)", kinds.count("add_coincident") >= 1 and any("거리" in c["detail"] for c in d["suggestions"] if c["kind"] == "add_coincident"), str(kinds))
    check("add_horizontal/vertical ≥ 4 (기운 선 포함)", kinds.count("add_horizontal") + kinds.count("add_vertical") >= 4, str(kinds))
    check("add_equal 2 (선 길이·반지름)", kinds.count("add_equal") == 2, str([c["detail"] for c in d["suggestions"] if c["kind"] == "add_equal"]))
    check("effect 있음, 원본 제약 수 유지", all("effect" in c and "solve_status" in c["effect"] for c in d["suggestions"]) and FreeCAD.getDocument("T10_fixes").getObject("Sketch").ConstraintCount == 4,
          str(FreeCAD.getDocument("T10_fixes").getObject("Sketch").ConstraintCount))
    check("recommended에 low 없음, id·key·fingerprint", d["recommended"] and all(d["suggestions"][i - 1]["confidence"] != "low" for i in d["recommended"]) and d["fingerprint"].startswith("g"), str(d["recommended"]))
    before_open = d["before"]["open_vertices"]
    r2 = measure("apply_sketch_fixes", "T10 recommended 적용", sketch_fix.apply_sketch_fixes(sketch="Sketch", doc="T10_fixes", ids=d["recommended"], fingerprint=d["fingerprint"]))
    check("apply ok", r2["ok"], str(r2.get("error")))
    a = r2["data"]["after"]
    check("적용 뒤 solve 0, 열린 끝점 4→2(따로 있는 선 f의 양 끝만), DoF 감소", a["solve_status"] == 0 and a["open_vertices"] == 2 and a["dof"] < d["before"]["dof"], f"{a} before_open={before_open}")
    r3 = sketch_fix.apply_sketch_fixes(sketch="Sketch", doc="T10_fixes", ids=[1], fingerprint=d["fingerprint"])
    check("바뀐 fingerprint → 오류", not r3["ok"] and "fingerprint" in r3["error"])
    r3 = sketch_fix.apply_sketch_fixes(sketch="Sketch", doc="T10_fixes", ids=[999])
    check("없는 id → 오류", not r3["ok"])

    # T4: 2 mm 벌어진 열린 와이어 → medium 후보로 잇기
    r = measure("suggest_sketch_fixes", "T4 열린 와이어", sketch_fix.suggest_sketch_fixes(sketch="Sketch", doc="T4_open_wire"))
    co = [c for c in r["data"]["suggestions"] if c["kind"] == "add_coincident"]
    check("T4: 열린 끝점 쌍 add_coincident 후보(2 mm, low)", len(co) == 1 and co[0]["confidence"] == "low" and "2.0" in co[0]["detail"], str(co))
    r2 = sketch_fix.apply_sketch_fixes(sketch="Sketch", doc="T4_open_wire", ids=[co[0]["id"]])
    check("T4: 적용 뒤 open_vertices 0", r2["ok"] and r2["data"]["after"]["open_vertices"] == 0, str(r2.get("error") or r2["data"]["after"]))

    # T3: 충돌 치수 둘 → delete 후보 두 개, exclusive
    r = measure("suggest_sketch_fixes", "T3 충돌", sketch_fix.suggest_sketch_fixes(sketch="Sketch", doc="T3_conflict"))
    dl = [c for c in r["data"]["suggestions"] if c["kind"] == "delete_constraint"]
    check("T3: delete 후보 2개, exclusive_with로 묶임", len(dl) == 2 and all(c.get("exclusive_with") for c in dl) and all("DistanceX" in c["targets"][0] for c in dl), str(dl))
    check("T3: 충돌 후보는 recommended에 없음", not any(c["id"] in r["data"]["recommended"] for c in dl))
    r3 = sketch_fix.apply_sketch_fixes(sketch="Sketch", doc="T3_conflict", ids=[c["id"] for c in dl])
    check("T3: 둘 다 고르면 오류", not r3["ok"] and "같이" in r3["error"])
    pick = [c for c in dl if "= 25" in c["targets"][0]][0]
    r2 = sketch_fix.apply_sketch_fixes(sketch="Sketch", doc="T3_conflict", ids=[pick["id"]])
    check("T3: 25 삭제 → solve 0, 충돌 없음", r2["ok"] and r2["data"]["after"]["solve_status"] == 0 and not r2["data"]["after"]["conflicting"], str(r2.get("error") or r2["data"]["after"]))

    # T2: 자유도 남음 → add_dimension(low) 후보로 DoF 0
    r = measure("suggest_sketch_fixes", "T2 자유도", sketch_fix.suggest_sketch_fixes(sketch="Sketch", doc="T2_underconstrained"))
    dims = [c for c in r["data"]["suggestions"] if c["kind"] == "add_dimension"]
    check("T2: add_dimension 후보(low) 있음", len(dims) >= 2 and all(c["confidence"] == "low" for c in dims), str([(c["targets"], c["detail"]) for c in dims][:4]))
    # 원점 고정 X·Y + 세로 길이: 효과가 DoF를 줄이는 것부터 차례로 적용
    dof0 = dof = r["data"]["before"]["dof"]
    applied = []
    for c in sorted(dims, key=lambda c: (c["effect"].get("dof") if c["effect"].get("dof") is not None else 99)):
        if dof == 0:
            break
        r2 = sketch_fix.apply_sketch_fixes(sketch="Sketch", doc="T2_underconstrained", ids=[c["id"]])
        if r2["ok"] and r2["data"]["after"]["solve_status"] == 0 and r2["data"]["after"]["dof"] < dof:
            dof = r2["data"]["after"]["dof"]; applied.append(c["targets"])
            r = sketch_fix.suggest_sketch_fixes(sketch="Sketch", doc="T2_underconstrained", evaluate=False)
            break
    check("T2: 치수 후보 적용으로 DoF 감소", dof < dof0, f"dof={dof0}→{dof} applied={applied}")


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


def test_rebuild_tools():
    section("M7: classify_faces / section_profile / build_features / compare_shapes")
    r = measure("classify_faces", "BSpline 판 PlateB", rebuild.classify_faces(doc="T7_rebuild", name="PlateB"))
    check("classify_faces ok", r["ok"], str(r.get("error")))
    d = r["data"]
    check("면 전부 BSpline", d["summary"]["bspline_faces"] == d["faces_total"], str(d["summary"]))
    check("전부 plane/cylinder/cone으로 판별 (자유곡면 0)", d["summary"]["free_form_faces"] == 0
          and set(d["summary"]["by_identity"]) <= {"plane", "cylinder", "cone"}, str(d["summary"]["by_identity"]))
    check("verdict prismatic, 주축 Z", d["rebuild"]["verdict"] == "prismatic" and d["rebuild"]["main_axis_letter"] == "Z", str(d["rebuild"]))
    pos = {lv["position"] for lv in d["rebuild"]["levels"]}
    check("levels ⊇ {0, 6, 10}", {0.0, 6.0, 10.0} <= pos, str(sorted(pos)))
    cyl = [f for f in d["faces"] if f["identity"] == "cylinder"]
    check("Ø6.6 원통 → 반지름 3.3 ±1e-4, 오목, 축 Z", any(abs(f["radius"] - 3.3) < 1e-4 and f["concave"] and f["axis_letter"] == "Z" for f in cyl), str([(f["radius"], f["concave"]) for f in cyl]))
    cone = [f for f in d["faces"] if f["identity"] == "cone"]
    check("챔퍼 → cone 반각 45°", bool(cone) and all(abs(f["semi_angle_deg"] - 45) < 0.1 for f in cone), str([f.get("semi_angle_deg") for f in cone]))
    r = rebuild.classify_faces(doc="T7_rebuild", name="Plate")
    check("해석면은 analytic으로", r["ok"] and all(f["method"] == "analytic" for f in r["data"]["faces"]))

    r = measure("section_profile", "후보 높이", rebuild.section_profile(doc="T7_rebuild", name="PlateB"))
    check("position=None → levels", r["ok"] and r["data"]["position"] is None
          and {0.0, 6.0, 10.0} <= {lv["position"] for lv in r["data"]["levels"]}, str(r["data"].get("levels")))
    r = measure("section_profile", "z=3 구멍 메움", rebuild.section_profile(doc="T7_rebuild", name="PlateB", position=3.0))
    check("section_profile ok", r["ok"], str(r.get("error")))
    d = r["data"]
    w0 = d["wires"][0] if d["wires"] else {}
    check("와이어 1개, 닫힘, 선분 4개", len(d["wires"]) == 1 and w0.get("closed") and [e["type"] for e in w0["elements"]] == ["line"] * 4, str([e["type"] for e in w0.get("elements", [])]))
    check("면적 60×40", abs((w0.get("area") or 0) - 2400) < 1e-3, str(w0.get("area")))
    check("구멍 자리 메움 ≥ 2", d["filled_holes"] >= 2, str(d["filled_holes"]))
    check("sketch_plane XY, 오프셋 3", d["sketch_plane"]["plane"] == "XY" and abs(d["sketch_plane"]["attachment_offset_z"] - 3) < 1e-9, str(d["sketch_plane"]))
    r = rebuild.section_profile(doc="T7_rebuild", name="PlateB", position=3.0, fill_holes=False)
    d = r["data"]
    circles = [e for w in d["wires"] for e in w["elements"] if e["type"] == "circle"]
    check("메우지 않으면 원 2개(R3.3), 바깥 윤곽이 outer", len(circles) == 2 and all(abs(c["radius"] - 3.3) < 1e-4 for c in circles) and d["wires"][0]["outer"], str(circles))
    check("BSpline 곡선을 직선·원으로 맞춤 (unsupported 0)", sum(w["unsupported"] for w in d["wires"]) == 0)
    r = rebuild.section_profile(doc="T7_rebuild", name="PlateB", position=8.0)
    check("z=8 단면 30×40", r["ok"] and abs(r["data"]["wires"][0]["area"] - 1200) < 1e-3, str(r["data"]["wires"][0]["area"] if r["ok"] else r))
    r = rebuild.section_profile(doc="T7_rebuild", name="PlateB", axis="X", position=15.0, fill_holes=False)
    check("X축 단면 → sketch_plane YZ", r["ok"] and r["data"]["sketch_plane"]["plane"] == "YZ", str(r.get("error")))
    r = rebuild.section_profile(doc="T7_rebuild", name="PlateB", axis="Q", position=1.0)
    check("잘못된 axis → 에러", r["ok"] is False)

    feats = [
        {"op": "pad", "name": "PadBase", "plane": "XY", "position": 0.0,
         "profile": {"section": {"of": "PlateB", "position": 3.0}}, "length": "Params.step_z"},
        {"op": "pad", "name": "PadTop", "plane": "XY", "position": "Params.step_z",
         "profile": {"section": {"of": "PlateB", "position": 8.0}}, "length": 4.0},
        {"op": "pocket", "name": "PocketHoles", "plane": "XY", "position": 10.0, "through": True,
         "profile": {"circles": [{"center": [15, 20], "diameter": 6.6, "expr": "Params.hole_d", "name": "hole_d"},
                                 {"center": [45, 20], "diameter": 6.6}]}},
        {"op": "pocket", "name": "PocketCbore", "plane": "XY", "position": 10.0, "length": 3.0,
         "profile": {"circles": [{"center": [15, 20], "diameter": 10.0}]}},
        {"op": "chamfer", "name": "ChamferHoles", "size": 0.5,
         "edges": {"curve": "Circle", "radius": 3.3, "center": [None, None, 0.0]}},
    ]
    r = measure("build_features", "판 5피처", rebuild.build_features(doc="T7_rebuild", body="Rebuilt", params={"step_z": 6.0, "hole_d": 6.6}, features=feats))
    check("build_features ok", r["ok"], str(r.get("error")))
    d = r["data"]
    check("5개 생성, stopped_at 없음, invalid 없음", len(d["created"]) == 5 and d["stopped_at"] is None and not d["invalid"], str(d["invalid"] or d["created"]))
    sk_reports = [(c["name"], c.get("solve_status"), c.get("fully_constrained")) for c in d["created"] if "sketch" in c]
    check("스케치 4개 solve 0·완전 구속", len(sk_reports) == 4 and all(s == 0 and fc for _, s, fc in sk_reports), str(sk_reports))
    check("챔퍼 모서리 2개 선택", len(d["created"][4].get("edges") or []) == 2, str(d["created"][4]))
    check("Params 기록", set(d["params_written"]) == {"step_z", "hole_d"})
    vol_before = d["volume"]
    r = measure("compare_shapes", "Plate vs 재구성 Body", rebuild.compare_shapes(doc="T7_rebuild", a="Plate", b="Rebuilt"))
    check("compare_shapes ok", r["ok"], str(r.get("error")))
    check("재구성 identical (< 0.001 %)", r["ok"] and r["data"]["verdict"] == "identical", str({k: r["data"][k] for k in ("diff_pct", "missing_in_b", "extra_in_b")} if r["ok"] else r))
    r = rebuild.compare_shapes(doc="T7_rebuild", a="Plate", b="PlateB")
    # transformGeometry의 BSpline 근사는 부피를 0.012 % 바꾼다 [라이브 1.1.3] → identical이 아니라 match
    check("Plate vs PlateB match (BSpline 근사 0.012 %)", r["ok"] and r["data"]["verdict"] in ("identical", "match")
          and abs(r["data"]["volume_diff_pct"]) < 0.05, str({k: r["data"].get(k) for k in ("verdict", "volume_diff_pct")} if r["ok"] else r))
    r = rebuild.compare_shapes(doc="T7_rebuild", a="Plate", b="Rebuilt", doc_b="T7_rebuild")
    check("doc_b 지정도 동작", r["ok"])

    doc = FreeCAD.getDocument("T7_rebuild")
    sheet = doc.getObject("Params")
    sheet.set(sheet.getCellFromAlias("hole_d"), "8")
    doc.recompute()
    body = doc.getObject("Rebuilt")
    check("Params.hole_d 6.6→8 이면 부피 감소 (파라메트릭)", body.Shape.isValid() and body.Shape.Volume < vol_before - 1.0, f"{vol_before} → {body.Shape.Volume}")

    r = rebuild.build_features(doc="T7_rebuild", body="Rebuilt2", features=[
        {"op": "pad", "name": "Bad", "plane": "XY", "position": 0.0, "profile": {"polygon": [[0, 0], [10, 0], [10, 10]]}}])
    check("length 없는 pad → stopped_at·status", r["ok"] and r["data"]["stopped_at"] == "Bad" and "length" in r["data"]["created"][0]["status"], str(r["data"] if r["ok"] else r))
    r = rebuild.build_features(doc="T7_rebuild", body="Rebuilt3", features=[
        {"op": "pad", "name": "Block", "plane": "XY", "position": 0.0, "length": 10.0,
         "profile": {"rect": {"center": [10, 10], "width": 20, "height": 20}}},
        {"op": "groove", "name": "G", "plane": "XZ", "position": 10.0, "axis": {"x": 10.0},
         "profile": {"polygon": [[12, 2], [18, 2], [18, 8], [12, 8]]}}])
    check("groove: XZ 평면 y=10, 축 x=10, 링 절삭 π(64−4)·6", r["ok"] and r["data"]["stopped_at"] is None
          and abs(r["data"]["volume"] - (4000 - math.pi * 60 * 6)) < 0.01, str(r["data"].get("volume") if r["ok"] else r))
    r = rebuild.build_features(doc="T7_rebuild", body="Rebuilt4", features=[
        {"op": "revolution", "name": "Rev", "plane": "XZ", "position": 0.0, "axis": {"x": 0.0},
         "profile": {"polygon": [[5, 0], [10, 0], [10, 10], [5, 10]]}}])
    check("revolution: 축 구성선 + 폴리곤 → 관 (부피 π(100−25)·10)", r["ok"] and r["data"]["stopped_at"] is None
          and abs(r["data"]["volume"] - math.pi * 75 * 10) < 0.01, str(r["data"].get("volume") if r["ok"] else r))
    # 반원(180°) 호: 양 끝점 고정 + Radius는 Sketcher가 '중복'으로 거부한다 → 150° 넘는 호는 나눠 그린다
    r = rebuild.build_features(doc="T7_rebuild", body="Rebuilt5", features=[
        {"op": "pad", "name": "DShape", "plane": "XY", "position": 0.0, "length": 2.0,
         "profile": {"elements": [{"type": "line", "start": [0, -5], "end": [0, 5]},
                                  {"type": "arc", "center": [0, 0], "radius": 5.0, "start": [0, 5], "end": [0, -5], "ccw": False}]}}])
    c = r["data"]["created"][0] if r["ok"] and r["data"]["created"] else {}
    check("반원 프로파일 Pad: DoF 0·부피 π·25·2/2", r["ok"] and r["data"]["stopped_at"] is None and c.get("dof") == 0
          and abs(r["data"]["volume"] - math.pi * 25) < 0.01, str((c.get("status"), c.get("dof"), r["data"].get("volume")) if r["ok"] else r))

    # 같은 축선의 반원 채널 두 토막은 '구멍'이 아니다 → 메우지 않고 단면에 호로 남아야 한다
    r = rebuild.section_profile(doc="T7_rebuild", name="Channel", axis="X", position=5.0, fill_holes=True)
    w0 = r["data"]["wires"][0] if r["ok"] and r["data"]["wires"] else {}
    arcs = [e for e in w0.get("elements", []) if e["type"] == "arc"]
    check("반원 채널 토막은 메우지 않음 (filled 0, 단면에 R3 호)", r["ok"] and r["data"]["filled_holes"] == 0 and len(arcs) >= 1
          and all(abs(a["radius"] - 3.0) < 1e-6 for a in arcs), str((r["data"].get("filled_holes"), [e["type"] for e in w0.get("elements", [])]) if r["ok"] else r))
    # 자유곡선 요소 근사 + 방향 필터 챔퍼
    r = rebuild.build_features(doc="T7_rebuild", body="Rebuilt6", features=[
        {"op": "pad", "name": "Blend", "plane": "XY", "position": 0.0, "length": 4.0,
         "profile": {"elements": [{"type": "line", "start": [0, 0], "end": [10, 0]}, {"type": "line", "start": [10, 0], "end": [10, 8]},
                                  {"type": "bspline", "start": [10, 8], "end": [8, 10], "points": [[10, 8], [9.6, 9.2], [8.8, 9.8], [8, 10]], "unsupported": True},
                                  {"type": "line", "start": [8, 10], "end": [0, 10]}, {"type": "line", "start": [0, 10], "end": [0, 0]}]}},
        {"op": "chamfer", "name": "ChX", "size": 1.0, "edges": {"curve": "Line", "direction": [1, 0, 0], "bbox": {"min": [None, None, 3.99]}}}])
    cs = r["data"]["created"] if r["ok"] else []
    check("bspline 요소는 build에서 거부 (approximate 없이)", r["ok"] and r["data"]["stopped_at"] == "Blend" and "bspline" in cs[0]["status"], str(cs[:1] if r["ok"] else r))
    r = rebuild.build_features(doc="T7_rebuild", body="Rebuilt7", features=[
        {"op": "pad", "name": "Blend", "plane": "XY", "position": 0.0, "length": 4.0,
         "profile": {"elements": rebuild._approximate_bsplines([{"type": "line", "start": [0, 0], "end": [10, 0]}, {"type": "line", "start": [10, 0], "end": [10, 8]},
                                  {"type": "bspline", "start": [10, 8], "end": [8, 10], "points": [[10, 8], [9.6, 9.2], [8.8, 9.8], [8, 10]], "unsupported": True},
                                  {"type": "line", "start": [8, 10], "end": [0, 10]}, {"type": "line", "start": [0, 10], "end": [0, 0]}])}},
        {"op": "chamfer", "name": "ChX", "size": 1.0, "edges": {"curve": "Line", "direction": [1, 0, 0], "bbox": {"min": [None, None, 3.99]}}}])
    cs = r["data"]["created"] if r["ok"] else []
    check("꺾은선 근사 Pad + X 방향 윗면 모서리 2개만 챔퍼", r["ok"] and r["data"]["stopped_at"] is None and cs[0].get("dof") == 0
          and len(cs[1].get("edges") or []) == 2 and cs[1]["status"] == "Valid", str([(c["name"], c.get("dof"), c["status"], c.get("edges")) for c in cs] if r["ok"] else r))
    # 구배 Pad: TaperAngle 음수 = 위로 갈수록 좁아짐 (20×20 바닥, 높이 10, −5° → 윗면 18.25×18.25, 원뿔대 부피)
    r = rebuild.build_features(doc="T7_rebuild", body="Rebuilt8", features=[
        {"op": "pad", "name": "Draft", "plane": "XY", "position": 0.0, "length": 10.0, "taper": -5.0,
         "profile": {"rect": {"center": [0, 0], "width": 20, "height": 20}}}])
    top = 20 - 2 * 10 * math.tan(math.radians(5))
    frustum = 10 / 3.0 * (400 + top * top + math.sqrt(400 * top * top))
    check("taper −5° Pad → 원뿔대 부피 (안으로 좁아짐)", r["ok"] and r["data"]["stopped_at"] is None and abs(r["data"]["volume"] - frustum) < 0.5,
          str((r["data"].get("volume"), round(frustum, 2)) if r["ok"] else r))

    # align_shapes: 옮기고 돌린 사본 → 변환 복원, 거울상 사본 → mirrored
    import Part as _Part
    doc = FreeCAD.getDocument("T7_rebuild")
    plate = doc.getObject("Plate")
    # Plate는 y=20에 대칭이라 거울상이 회전과 같다 → 한 귀퉁이를 잘라 비대칭(키랄)으로 만든 사본으로 시험한다
    chiral = doc.addObject("Part::Feature", "Chiral")
    chiral.Shape = plate.Shape.cut(_Part.makeBox(5, 5, 10))
    moved = doc.addObject("Part::Feature", "ChiralMoved")
    pl = FreeCAD.Placement(FreeCAD.Vector(120, -30, 7), FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), 37))
    s = chiral.Shape.copy(); s.Placement = pl.multiply(s.Placement); moved.Shape = s
    mir = doc.addObject("Part::Feature", "ChiralMirror")
    mir.Shape = chiral.Shape.mirror(FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 1, 0))
    doc.recompute()
    r = rebuild.align_shapes(doc="T7_rebuild", a="Chiral", b="ChiralMoved")
    got = r["data"]["placement"] if r["ok"] else None
    check("align_shapes: 37° 회전+이동 복원, match 100 %", r["ok"] and r["data"]["match_pct"] >= 99.9 and not r["data"]["mirrored"]
          and got is not None and abs(got["rotation_angle_deg"] - 37) < 0.01 and all(abs(got["base"][i] - (120, -30, 7)[i]) < 0.01 for i in range(3)),
          str((got, r["data"].get("match_pct")) if r["ok"] else r))
    r = rebuild.align_shapes(doc="T7_rebuild", a="Chiral", b="ChiralMirror")
    check("align_shapes: 거울상 사본 → mirrored, placement 없음", r["ok"] and r["data"]["mirrored"] and r["data"]["placement"] is None and r["data"]["match_pct"] >= 99.9,
          str({k: r["data"].get(k) for k in ("mirrored", "match_pct")} if r["ok"] else r))
    r = rebuild.align_shapes(doc="T7_rebuild", a="Plate", b="PlateB")
    check("align_shapes: 같은 자리 사본(BSpline 판) → 항등 변환", r["ok"] and r["data"]["match_pct"] >= 99.9 and abs(r["data"]["placement"]["rotation_angle_deg"]) < 0.05
          and all(abs(v) < 0.05 for v in r["data"]["placement"]["base"]), str(r["data"].get("placement") if r["ok"] else r))


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
        ("rebuild_tools", test_rebuild_tools),
        ("drawing_tools", test_drawing_tools),
        ("mesh_tools", test_mesh_tools),
        ("sketch_fix_tools", test_sketch_fix_tools),
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
