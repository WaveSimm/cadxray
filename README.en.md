# cadxray

*한국어: [README.md](README.md)*

An MCP server that lets Claude Code **diagnose** FreeCAD models. Ask "why is Sketch003 red?" or "why does Pad001 fail?" and Claude inspects the live document with dedicated tools, explains the cause, fixes it with `execute_code`, and verifies with `tracked_recompute` and a screenshot.

- FreeCAD **1.0.x / 1.1.x** (verified on 1.1.3), Windows · macOS · Linux
- Two parts: a FreeCAD **addon** (`addon/CadXray`, stdlib + PySide only) and an MCP **bridge** (`bridge/`, depends on `mcp` only)
- They talk over `127.0.0.1:9877` only — nothing leaves your machine

## Install — two commands

Type these in a **terminal** (Windows: PowerShell or Command Prompt; macOS: Terminal) — not in the Claude Code chat.

Prerequisites, each installed once: FreeCAD ≥ 1.0 (launch it once so the Mod folder exists), [Claude Code](https://claude.com/claude-code) (`claude --version`), [uv](https://docs.astral.sh/uv/) (`uv --version`; Windows: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`, macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`, then reopen the terminal), git.

```bash
uvx --from git+https://github.com/WaveSimm/cadxray#subdirectory=bridge cadxray install
claude mcp add --scope user cadxray -- uvx --from git+https://github.com/WaveSimm/cadxray#subdirectory=bridge cadxray
```

The first line copies the addon into FreeCAD's Mod folder; the second registers the bridge with Claude Code. Restart FreeCAD — the server starts automatically (Report view: `[CAD X-ray] 서버 시작 http://127.0.0.1:9877 (툴 14개)`; addon messages are in Korean for now). Done.

Stuck? `… cadxray doctor` checks the addon install, the FreeCAD server and version mismatches.

Also installable from FreeCAD's **Addon Manager** (add this repo as a custom repository). Developers: `git clone … && cd cadxray/bridge && uv run cadxray install --dev` (symlink, edits apply immediately).

## Tools (14)

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

Every response is an envelope `{"ok", "data", "warnings", "truncated", "elapsed_ms"}`. List-type responses take `max_*` limits; summaries and `invalid_objects` are always computed over the whole document even when the list is truncated. Hard cap 100 KB (screenshots excepted).

## What it has been tested on

- 109 handler tests run headless: `freecadcmd tests/in_freecad/test_handlers.py` (0.8 s)
- A real PartDesign part (sketch with 1 DoF left, missing coincidences — found and fixed)
- Vendor STEP parts and an 80-part vendor assembly (3,149 faces): holes with counterbores and chamfers, thread hints, zero interference, 8.5 kg at steel density
- STEP → parametric rebuild: a bracket reproduced to **0.0 mm³ difference**; a 44-face clamp jaw (BSpline transitions, dovetail groove, chamfered lips) to 0.0004 %. `examples/rebuild_bracket_from_step.py`
- STEP assembly → one PartDesign Body per part + grounded Assembly joints: `examples/step_assembly_to_bodies.py`

## Known limits

- `through` for holes is a heuristic (material just outside both ends). A hole opening into a pocket can read as through.
- Threads are not modelled in vendor STEP files; `thread_hint` is inferred from diameter only.
- STL/OBJ meshes have no faces or solids — none of the geometry tools apply. Ask for STEP.
- Verified on FreeCAD 1.1.3 / Windows only so far. 1.0.x is supported by code paths checked against the 1.0.2 sources but not yet run live.

## Notes for contributors

`docs/api-notes.md` records every FreeCAD API fact this project relies on, tagged with the version it was verified against (`[1.0.2][1.1.3]` from source, `[라이브 1.1.3]` live). Highlights: `solve()` returns `-4` for two dimension constraints with different values (not `-3`), `FullyConstrained` keeps a stale `True` after a failed solve, one unclosed corner yields two `OpenVertices`, `AddSubType` is not exposed on 1.1.3, `Body` drops its `BaseFeature`'s Placement.

The tool set and response design follow [theosib/FreeCAD-MCP-Server](https://github.com/theosib/FreeCAD-MCP-Server); the addon server pattern (main-thread queue + QTimer + XML-RPC) follows [neka-nat/freecad-mcp](https://github.com/neka-nat/freecad-mcp). Code was written from the spec, not copied. License: MIT.
