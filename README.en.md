# cadxray

*한국어: [README.md](README.md)*

An MCP server that lets Claude Code **diagnose** FreeCAD models. Ask "why is Sketch003 red?" or "why does Pad001 fail?" and Claude inspects the live document with dedicated tools, explains the cause, fixes it with `execute_code`, and verifies with `tracked_recompute` and a screenshot.

- FreeCAD **1.0.x / 1.1.x** (verified on 1.1.3), Windows · macOS · Linux
- Two parts: a FreeCAD **addon** (`freecad/cadxray`, stdlib + PySide only) and an MCP **bridge** (`bridge/`, depends on `mcp` only)
- They talk over `127.0.0.1:9877` only — nothing leaves your machine

## Install — two commands

Type these in a **terminal** (Windows: PowerShell or Command Prompt; macOS: Terminal) — not in the Claude Code chat.

Prerequisites, each installed once: FreeCAD ≥ 1.0 (launch it once so the Mod folder exists), [Claude Code](https://claude.com/claude-code) (`claude --version`), [uv](https://docs.astral.sh/uv/) (`uv --version`; Windows: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`, macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`, then reopen the terminal), git.

```bash
uvx --from git+https://github.com/WaveSimm/cadxray#subdirectory=bridge cadxray install
claude mcp add --scope user cadxray -- uvx --from git+https://github.com/WaveSimm/cadxray#subdirectory=bridge cadxray
```

The first line copies the addon into FreeCAD's Mod folder; the second registers the bridge with Claude Code. Restart FreeCAD — the server starts automatically (Report view: `[CAD X-ray] 서버 시작 http://127.0.0.1:9877 (툴 27개)`; addon messages are in Korean for now). Done.

Stuck? `… cadxray doctor` checks the addon install, the FreeCAD server and version mismatches.

**Which Claude?** All three work: Claude Code CLI and the Claude Code desktop app share the registration above (`--scope user`). For the **Claude Desktop chat app**, add the same server to `claude_desktop_config.json` (Settings → Developer → Edit Config; Windows `%APPDATA%\Claude\`, macOS `~/Library/Application Support/Claude/`) and fully restart the app:

```json
{ "mcpServers": { "cadxray": { "command": "uvx",
    "args": ["--from", "git+https://github.com/WaveSimm/cadxray#subdirectory=bridge", "cadxray"] } } }
```
If Windows cannot find `uvx`, put its full path in `"command"` (`(Get-Command uvx).Source` in PowerShell).

Also installable from FreeCAD's **Addon Manager** (add this repo as a custom repository). Developers: `git clone … && cd cadxray/bridge && uv run cadxray install --dev` (symlink, edits apply immediately).

## Tools (27)

| Tool | What it does |
|---|---|
| `ping` | connection + FreeCAD version |
| `list_documents` | open documents |
| `get_document_graph` | object tree, dependencies, invalid objects — **start here** |
| `inspect_object` | every property, expression and shape summary of one object |
| `get_sketch_diagnostics` | solver status, DoF, conflicting/redundant constraint IDs (1-based, same as the GUI panel), open vertices |
| `analyze_shape` | validity, volume, faces by surface type, `check()` message |
| `tracked_recompute` | recompute with before/after diff: resolved / new errors / persistent |
| `get_screenshot` | 3D view as PNG (12 preset views) |
| `execute_code` | run Python inside FreeCAD (for fixes) |
| `reload_handlers` | reload addon handlers without restarting FreeCAD (dev) |
| `import_step` | import STEP/IGES and summarize the parts created |
| `find_holes` | hole diameter/center/depth/through, with counterbore, countersink, chamfer and drill-point attached; fillets and slot ends separated by arc angle; bolt patterns with pitch; ISO metric **thread hints** (tap drill / clearance) |
| `check_interference` | min distance and interference volume per pair; bbox prefilter (80 parts = 3,160 pairs in 6.5 s); only problem pairs returned by default |
| `get_mass_properties` | volume, area, center of mass, inertia; mass if you pass a density |
| `classify_faces` | **STEP → parametric, step 1**: what each face really is (plane / cylinder / cone / sphere / free_form) — BSpline faces are sampled and fitted, so "fake free-form" faces are resolved; main axis, band levels, radii, rebuild verdict |
| `section_profile` | cross-section at a height as sketch-ready lines/arcs/circles in sketch-local 2D; holes, counterbores and chamfers filled in 3D first so only the outline remains; BSpline curves re-identified |
| `build_features` | stacks sketch + Pad / Pocket / Groove / Revolution / Fillet / Chamfer on a Body, one feature at a time with recompute and validation; `profile.section` traces the original directly (no coordinates through the LLM); Block / point-anchored arcs / axis construction line rules built in; `params` go to a Spreadsheet |
| `compare_shapes` | volume / area / bbox difference plus fuzzy-difference pieces with bounding boxes — tells you *where* the rebuild is wrong |
| `align_shapes` | rigid transform between two instances of the same part (principal axes + on-surface probe verification); use it to place one rebuilt Body at many positions with App::Link; flags mirror images |
| `make_drawing` | **2D drawing (M8)**: Body / Part / Link group → TechDraw page (ISO title block, auto scale and layout, front/right/top/iso/detail views) + dimensions (model vertices, silhouette edges, circles — values measured on the model) + notes + title block → PDF/SVG. 27-link assembly, 5 views, 13 dimensions in 87 s |
| `inspect_drawing` | views, dimension values, notes and title-block fields of a page; finds empty views and broken dimensions |
| `import_mesh` | **STL (M9)**: load STL/OBJ/PLY/3MF as a transparent reference Mesh; closed / self-intersection checks |
| `analyze_mesh` | main axis, levels (band boundaries), per-band section circles, common center, **thread (pitch, major/minor, hand)**, verdict — the mesh counterpart of `classify_faces` |
| `section_profile` / `compare_shapes` on meshes | mesh cross-section polylines fitted to lines/arcs/circles so `build_features` can use them directly / boolean-free normal-ray deviation with worst points |
| `build_features` `helix` op | threads and helical grooves (SubtractiveHelix/AdditiveHelix) with axis center, pitch, height, hand |
| `open_document` / `save_document` | open and save FCStd (overwriting another file needs `overwrite`) |
| `suggest_sketch_fixes` | **constraint fix proposals (M10)**: join near/open endpoints, missing horizontal/vertical/equal, delete redundant/malformed/conflicting constraints, dimensions for leftover DoF — each tried on a copy with its effect (DoF, status) and a confidence; nothing is changed automatically |
| `apply_sketch_fixes` | apply only the ids the user picked, revert if the sketch gets worse, refuse if the sketch changed meanwhile (fingerprint) |

Every response is an envelope `{"ok", "data", "warnings", "truncated", "elapsed_ms"}`. List-type responses take `max_*` limits; summaries and `invalid_objects` are always computed over the whole document even when the list is truncated. Hard cap 100 KB (screenshots excepted).

## What it has been tested on

- 210 handler tests run headless: `freecadcmd tests/in_freecad/test_handlers.py` (3 s)
- A real PartDesign part (sketch with 1 DoF left, missing coincidences — found and fixed)
- Vendor STEP parts and an 80-part vendor assembly (3,149 faces): holes with counterbores and chamfers, thread hints, zero interference, 8.5 kg at steel density
- STEP → parametric rebuild: a bracket reproduced to **0.0 mm³ difference**; a 44-face clamp jaw (BSpline transitions, dovetail groove, chamfered lips) to 0.0004 % — first by hand (`examples/rebuild_bracket_from_step.py`), then again with the four M7 tools only: 12 features, every sketch fully constrained, `compare_shapes` verdict *identical* (`examples/rebuild_2b2_with_tools.py`). The 8 BSpline transition faces were identified as cones (axis, apex, 59.63° half-angle) with 6.6e-5 residual.
- STEP assembly → one PartDesign Body per part + grounded Assembly joints: `examples/step_assembly_to_bodies.py`
- **Whole assembly rebuilt parametrically**: all 20 part types of the 80-part vendor assembly rebuilt with the M7 tools (15 identical, 4 match, one at 0.14 % because of free-form fillets), then one Body per type placed 80 times via `align_shapes` into App::Links with grounded joints — 0 interference, 3.5 min (`examples/assemble_from_bodies.py`). Two part types turned out to have mirror-image instances.
- **2D drawings**: `make_drawing` produced an A3 sheet of the 27-link pole frame (3 views, 2 details, 13 dimensions all equal to the model, notes, title block, PDF) in one call, and of a single-body part in 2.7 s.
- **Drawings and photos to 3D**: DXF (PCB, structural), 1:1 vector PDF and a photographed sketch were read and rebuilt parametrically (`examples/*_from_*.py`).

## Known limits

- `through` for holes is a heuristic (material just outside both ends). A hole opening into a pocket can read as through.
- Threads are not modelled in vendor STEP files; `thread_hint` is inferred from diameter only.
- STL/OBJ meshes have no faces or solids, so hole/interference tools do not read them. Rebuild them with the M9 tools instead: `import_mesh` → `analyze_mesh` → `section_profile` (mesh sections fitted to lines/arcs/circles) → `build_features` (`profile.section` with the mesh name, threads via the `helix` op) → `compare_shapes` (mesh vs Body, ray deviation). A 5,758-facet spool-guide STL was rebuilt this way with every mesh vertex within 0.03 mm, external thread M44.5×2 included. Never call `compare_shapes` on a `makeShapeFromMesh` solid (10+ minute boolean) — pass the mesh itself.
- Verified on FreeCAD 1.1.3 / Windows only so far. 1.0.x is supported by code paths checked against the 1.0.2 sources but not yet run live.

## Notes for contributors

`docs/api-notes.md` records every FreeCAD API fact this project relies on, tagged with the version it was verified against (`[1.0.2][1.1.3]` from source, `[라이브 1.1.3]` live). Highlights: `solve()` returns `-4` for two dimension constraints with different values (not `-3`), `FullyConstrained` keeps a stale `True` after a failed solve, one unclosed corner yields two `OpenVertices`, `AddSubType` is not exposed on 1.1.3, `Body` drops its `BaseFeature`'s Placement.

The tool set and response design follow [theosib/FreeCAD-MCP-Server](https://github.com/theosib/FreeCAD-MCP-Server); the addon server pattern (main-thread queue + QTimer + XML-RPC) follows [neka-nat/freecad-mcp](https://github.com/neka-nat/freecad-mcp). Code was written from the spec, not copied. License: MIT.
